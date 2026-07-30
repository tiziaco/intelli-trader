"""Unit contract for the venue-ACCOUNT domain — spec, manager, identity guard.

One module because they are one contract: a durable row becomes an ``AccountSpec``, the
manager turns that into a routable runtime, and the trust-on-first-use identity guard runs
between the session opening and the account becoming routable. Splitting them across three
files is what let the guard be tested thoroughly while never actually running on the path
that brings an account up.

Proves:

  - **The account set is STORE-DERIVED, VENUE-SCOPED and ORDERED.** It comes off durable
    rows, one venue never sees another's accounts (``account_id`` alone cannot derive its
    venue), disabled rows are excluded, and the order is ``account_id`` ASC so bring-up is
    reproducible rather than driver-dependent.
  - **The empty case is SUPPORTED.** Zero enabled rows yields ``[]`` and no error — a fresh
    deployment comes up RUNNING and empty.
  - **The degrade is NARROW.** A missing ``venue_accounts`` TABLE warns and returns ``[]``;
    ANY other fault propagates LOUD. Both halves are asserted, and the second is the one
    that matters: under DB-as-sole-truth a swallowed read means zero accounts, and then a
    refusal for every persisted portfolio — N derived errors burying the one real cause.
  - **Provisioning is CREATE-ONLY and VALIDATES BEFORE it writes.** A second ``provision``
    of the same pair raises the typed refusal and writes nothing (the classification comes
    from the database's ``IntegrityError``, never a pre-check ``SELECT``); a config the
    engine could never act on is refused before anything is persisted.
  - **provision and bring_online are TWO verbs.** ``provision`` alone leaves the account
    offline; the pair together makes it usable in the same process, no restart.
  - **bring_online is REGISTRATION-LAST.** A failure at any earlier step — config, session,
    adapter connect, identity mismatch — leaves the routing map EMPTY, so the account is
    never routable against a session that did not open or is not the right account.
  - **Teardown is per account.** ``bring_offline`` closes ITS OWN session and drops ITS OWN
    routing entry, leaving every other account online.
  - **The identity guard's six inert paths stay distinguishable**, because each needs a
    different operator action.

The store is REAL (in-memory SQLite): the missing-table probe inspects a live engine and
the duplicate refusal is the database's own, so faking either would test the fake.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named top-level
test packages break full-suite collection). 4-space indentation.
"""

from __future__ import annotations

import queue
import random
import uuid as _uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.config import ExchangeConfig
from itrader.config.sql import SqlSettings
from itrader.connectors.pool import ConnectorPool
from itrader.core.exceptions import (
    DuplicateVenueAccountProvisionError,
    UnknownVenueAccountConfigKeyError,
    ValidationError,
    VenueAccountInUseError,
    VenueAccountNotProvisionedError,
)
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.execution_handler.result_objects import ConnectionResult
from itrader.core.enums.execution import ExchangeConnectionStatus
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.venues.accounts import (
    VENUE_UID_MISMATCH_REASON,
    AccountSpec,
    VenueAccountManager,
    assert_venue_uid,
)
from itrader.venues.catalog import CATALOG, VenueCapability, VenueDescriptor
from itrader.execution_handler.exchanges.paper import paper_exchange_recipe
from itrader.execution_handler.execution_handler import COMPUTE_VENUE
from tests.support.schema import provision_schema
from tests.support.venue_wiring import single_account_read_model

_AT =datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = COMPUTE_VENUE

# A sentinel a leak assertion can search for verbatim.
_SEEDED_SECRET = "seeded-key-8f21"


def _ctx() -> Any:
    """The two fields the paper recipe reads: the bus and the run's seeded rng."""
    return SimpleNamespace(bus=queue.Queue(), rng=random.Random(42))


def _make_manager(
    *,
    provision: bool = True,
    exchange_recipes: Any = None,
    catalog: Any = None,
    pool: Any = None,
    alert_sink: Any = None,
) -> tuple[VenueAccountManager, VenueAccountStore, dict[tuple[str, str], Any]]:
    """A manager over a REAL in-memory store, optionally with its schema NOT provisioned.

    ``provision=False`` reproduces the fresh-deployment state the narrow degrade handles:
    the store registers its table on the shared MetaData but nothing creates it (the stores
    are schema-pure and nothing self-creates at runtime).

    The manager receives the bare ``(venue, account_id) -> adapter`` routing dict — the
    composition-root-owned map — NOT an execution handler. ``bring_online`` writes this map
    as its last step, and the tests assert on it.
    """
    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    if provision:
        provision_schema(store.backend)
    routing: dict[tuple[str, str], Any] = {}
    manager = VenueAccountManager(
        store=store,
        pool=pool if pool is not None else ConnectorPool(
            catalog=CATALOG, resolver=None, recipes={}),
        routing=routing,
        catalog=catalog if catalog is not None else CATALOG,
        exchange_recipes=(
            exchange_recipes if exchange_recipes is not None
            else {_VENUE: paper_exchange_recipe(ExchangeConfig.default())}),
        ctx=_ctx(),
        alert_sink=alert_sink if alert_sink is not None else LogAlertSink(),
        halt_signal=lambda reason: None,
        stream_state_listener=(lambda name: None, lambda name: None),
    )
    return manager, store, routing


# --------------------------------------------------------------------------- #
# The account set
# --------------------------------------------------------------------------- #


def test_the_account_set_is_store_derived_venue_scoped_and_ordered() -> None:
    """Durable rows, this venue only, ``account_id`` ASC."""
    manager, store, _ = _make_manager()
    try:
        for venue, account, enabled in (
            (_VENUE, "zeta", True),
            (_VENUE, "alpha", True),
            (_VENUE, "retired", False),
            ("okx", "alpha", True),
        ):
            store.upsert(venue, account, secret_ref=None, venue_uid=None,
                         enabled=enabled, config={}, at=_AT)

        rows = manager.read_enabled_for(_VENUE)
        assert [row["account_id"] for row in rows] == ["alpha", "zeta"]
        assert {row["venue_name"] for row in rows} == {_VENUE}
    finally:
        store.dispose()


def test_a_venue_with_no_enabled_rows_yields_an_empty_set_and_no_error() -> None:
    """A fresh deployment comes up empty rather than failing."""
    manager, store, _ = _make_manager()
    try:
        store.upsert(_VENUE, "retired", secret_ref=None, venue_uid=None,
                     enabled=False, config={}, at=_AT)
        assert manager.read_enabled_for(_VENUE) == []
    finally:
        store.dispose()


def test_a_missing_accounts_table_degrades_with_a_warning_and_an_empty_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fresh-deployment state warns and returns ``[]``, never raises.

    The warning is required, not incidental: a silent ``[]`` here is indistinguishable from
    "this venue genuinely has no accounts", so an un-run Alembic chain would look like a
    correctly-empty deployment forever.
    """
    manager, store, _ = _make_manager(provision=False)
    try:
        with caplog.at_level("WARNING"):
            assert manager.read_enabled_for(_VENUE) == []
        assert any(
            "venue_accounts" in record.getMessage() for record in caplog.records)
    finally:
        store.dispose()


def test_any_fault_other_than_a_missing_table_propagates_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe tests for the TABLE and nothing else; real faults are not swallowed.

    With the table PRESENT, a store read that fails must reach the caller. A catch-all
    handler here would turn one unreachable database into zero accounts and then into a
    refusal per persisted portfolio: N derived errors hiding the one real cause.
    """
    manager, store, _ = _make_manager()

    class _Boom(RuntimeError):
        pass

    def _explode(venue_name: str) -> list[Any]:
        raise _Boom("database unreachable")

    try:
        monkeypatch.setattr(store, "read_enabled_for", _explode)
        with pytest.raises(_Boom):
            manager.read_enabled_for(_VENUE)
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# Provisioning
# --------------------------------------------------------------------------- #


def test_provision_writes_exactly_one_row_and_returns_it() -> None:
    """One durable row, carrying the account's own credential POINTER."""
    manager, store, _ = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1", secret_ref="env:ACCT_1",
                                config={"region": "eea"})
        assert row["venue_name"] == _VENUE
        assert row["account_id"] == "acct-1"
        assert row["secret_ref"] == "env:ACCT_1"
        assert row["enabled"] is True
        assert row["config"] == {"region": "eea"}
        assert len(store.read_all()) == 1
    finally:
        store.dispose()


def test_a_second_provision_of_the_same_pair_refuses_and_writes_nothing() -> None:
    """The DATABASE is the arbiter; the existing row is untouched.

    Asserting only the raise would be a false-green: the damage a duplicate provision does
    is the silent OVERWRITE of the operator's ``secret_ref``/``config`` and the reset of the
    engine-written ``venue_uid``. Both are asserted unchanged.
    """
    manager, store, _ = _make_manager()
    try:
        manager.provision(_VENUE, "acct-1", secret_ref="env:FIRST",
                          config={"region": "eea"})
        store.record_venue_uid(_VENUE, "acct-1", "uid-1", _AT)

        with pytest.raises(DuplicateVenueAccountProvisionError) as excinfo:
            manager.provision(_VENUE, "acct-1", secret_ref="env:SECOND",
                              config={"region": "us"})
        assert excinfo.value.account_id == "acct-1"

        row = store.get(_VENUE, "acct-1")
        assert row is not None
        assert row["secret_ref"] == "env:FIRST"
        assert row["venue_uid"] == "uid-1"
        assert row["config"] == {"region": "eea"}
        assert len(store.read_all()) == 1
    finally:
        store.dispose()


def test_provision_validates_the_config_BEFORE_it_persists_anything() -> None:
    """A config the engine could never act on is refused with no durable trace.

    Validating only at bring-up would let ``provision`` report success on a row whose next
    boot refuses — the operator learns about the typo one restart away from the action that
    caused it, with a durable row sitting there in the meantime.
    """
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(UnknownVenueAccountConfigKeyError):
            manager.provision(_VENUE, "acct-1", config={"sandox": True})
        assert store.get(_VENUE, "acct-1") is None
        assert store.read_all() == []

        with pytest.raises(ValidationError):
            manager.provision(_VENUE, "acct-2", config={"market_type": "spott"})
        assert store.read_all() == []
    finally:
        store.dispose()


def test_provision_with_a_secret_bearing_config_refuses_and_persists_nothing() -> None:
    """A secret-looking key never reaches ``config_json``.

    Two independent controls agree here: a credential key is not on the mergeable
    allowlist, and ``VenueAccountStore`` runs its own recursive denylist as the first
    statement of the write. This asserts the outcome an operator depends on — the refusal
    is total and nothing is persisted.
    """
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(UnknownVenueAccountConfigKeyError):
            manager.provision(_VENUE, "acct-1", config={"api_key": "leaked"})
        assert store.get(_VENUE, "acct-1") is None
        assert store.read_all() == []
    finally:
        store.dispose()


def test_provision_does_not_bring_the_account_online() -> None:
    """Two verbs. The durable write alone builds no runtime."""
    manager, store, routing = _make_manager()
    try:
        manager.provision(_VENUE, "acct-1")
        assert manager.is_online(_VENUE, "acct-1") is False
        assert routing == {}
    finally:
        store.dispose()


def test_provision_then_bring_online_makes_the_account_usable_in_this_process() -> None:
    """Provisioned at runtime, usable with NO restart, through the ONE path."""
    manager, store, routing = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1", secret_ref="env:ACCT_1")
        record = manager.bring_online(row)

        assert manager.is_online(_VENUE, "acct-1") is True
        assert routing[(_VENUE, "acct-1")] is record.adapter
        assert record.spec.secret_ref == "env:ACCT_1"
        assert record.spec.venue_name == _VENUE
        assert record.spec.account_id == "acct-1"
    finally:
        store.dispose()


def test_set_enabled_on_a_pair_that_was_never_provisioned_refuses() -> None:
    """A no-such-account toggle must RAISE, not silently write nothing and report success.

    A store ``UPDATE`` matching zero rows is indistinguishable from a successful one at the
    call site, so an operator disabling a mistyped account id would walk away believing an
    account is offline when no such account exists at all.
    """
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.set_enabled(_VENUE, "ghost", False)
        assert excinfo.value.cause == VenueAccountNotProvisionedError.NOT_PROVISIONED
        assert store.read_all() == []
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# The shared routing map: one map, one writer, both arms
# --------------------------------------------------------------------------- #


def test_the_object_the_manager_registers_is_the_object_the_handler_resolves() -> None:
    """The exact adapter the manager registers for a pair IS what the handler resolves.

    The identity assertion that proves both sides hold the SAME root-owned map. A mis-wire
    would register into one map and read the other, so every live order would fail closed
    on a lookup miss behind a green offline suite.
    """
    manager, store, routing = _make_manager()
    try:
        execution_handler = ExecutionHandler(
            queue.Queue(), exchange_registry=routing,
            portfolio_read_model=single_account_read_model())
        assert execution_handler.exchanges is routing

        record = manager.bring_online(manager.provision(_VENUE, "acct-1"))

        assert execution_handler.exchanges[(_VENUE, "acct-1")] is record.adapter
    finally:
        store.dispose()


def test_the_registered_adapter_is_connected_before_it_is_routable() -> None:
    """An account is routable only once its adapter reports connected.

    A registered-but-unconnected adapter accepts orders it refuses at the fill boundary —
    the account looks healthy and trades nothing.
    """
    manager, store, routing = _make_manager()
    try:
        record = manager.bring_online(manager.provision(_VENUE, "acct-1"))
        assert record.adapter.is_connected() is True
        assert routing[(_VENUE, "acct-1")].is_connected() is True
    finally:
        store.dispose()


def test_bringing_the_same_pair_online_twice_returns_the_same_runtime() -> None:
    """One pair, one session, one adapter — a second bring-up builds nothing.

    A second adapter for one real account would double-spawn that account's fill/order
    streams, so every venue fill would be translated twice.
    """
    manager, store, routing = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1")
        first = manager.bring_online(row)
        second = manager.bring_online(row)

        assert second is first
        assert routing[(_VENUE, "acct-1")] is first.adapter
        assert len(manager.online_records()) == 1
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# The account-level config_json precedence merge
# --------------------------------------------------------------------------- #


def _row(config: Any) -> dict[str, Any]:
    """A durable account row carrying ``config`` VERBATIM — including ``None``.

    Built by hand rather than through ``provision`` so the ``config_json = NULL`` case is
    reachable: ``provision`` normalizes a missing config to ``{}`` before the write, but an
    out-of-band writer (an operator's SQL, an older migration) can leave the column NULL,
    and ``bring_online`` consumes the row either way.
    """
    return {
        "venue_name": _VENUE,
        "account_id": "acct-1",
        "secret_ref": None,
        "venue_uid": None,
        "enabled": True,
        "config": config,
        "updated_at": _AT,
    }


def test_an_account_level_key_reaches_the_spec() -> None:
    """``config_json`` gets its one READER, and it is the spec.

    The spec is the one object that travels from the durable row to both consumers (the
    connector recipe and the adapter recipe), so a key that does not land on it is a key
    the engine never acts on.
    """
    manager, store, _ = _make_manager()
    try:
        record = manager.bring_online(_row({"sandbox": True}))

        assert record.spec.sandbox is True
        # The keys the account did NOT name stay ABSENT — the venue default is in force.
        assert record.spec.region is None
        assert record.spec.market_type is None
    finally:
        store.dispose()


def test_each_allowlisted_key_overrides_independently() -> None:
    """Account values override venue values, one key at a time.

    Asserted per key rather than all three at once: a merge that only carried the FIRST key
    it saw, or that replaced the whole overlay wholesale, would pass a single-combined-case
    test and silently drop two of the three in production.
    """
    manager, store, _ = _make_manager()
    try:
        for key, value in (
            ("sandbox", False),
            ("region", "eea"),
            ("market_type", "derivative"),
        ):
            spec = manager.spec_for(_row({key: value}))
            assert getattr(spec, key) == value
            for other in {"sandbox", "region", "market_type"} - {key}:
                assert getattr(spec, other) is None, (
                    f"{other} must stay at the venue default when only {key} is named")
    finally:
        store.dispose()


def test_several_keys_merge_together_and_leave_the_unnamed_one_defaulted() -> None:
    """Two named keys override; the third is untouched (precedence, one direction)."""
    manager, store, _ = _make_manager()
    try:
        spec = manager.spec_for(_row({"region": "eea", "market_type": "derivative"}))

        assert spec.region == "eea"
        assert spec.market_type == "derivative"
        assert spec.sandbox is None
    finally:
        store.dispose()


@pytest.mark.parametrize("config", [{}, None])
def test_an_empty_and_a_null_config_are_indistinguishable_to_the_merge(
    config: Any,
) -> None:
    """``{}`` and ``NULL`` both leave every venue default in force, and neither raises.

    They arrive from different writers — ``provision`` normalizes to ``{}``, an out-of-band
    SQL insert leaves NULL — and an engine that treated one as "no config" and the other as
    an error would make a perfectly valid row un-bringable depending on who wrote it.
    """
    manager, store, _ = _make_manager()
    try:
        spec = manager.spec_for(_row(config))

        assert spec.sandbox is None
        assert spec.region is None
        assert spec.market_type is None
    finally:
        store.dispose()


def test_an_unrecognised_config_key_raises_and_brings_nothing_online() -> None:
    """THE security control: a typo REFUSES, it is never dropped.

    ``sandox`` silently ignored leaves the account on whatever the ambient environment says
    — which for the ``sandbox`` knob means a live order reaching the PRODUCTION host on an
    account the operator believed was pinned to demo. The refusal must also be TOTAL:
    asserting only the raise would be a false-green if the adapter had already been
    registered, because the pair would then be routable with a spec built from a config the
    engine refused to understand.
    """
    manager, store, routing = _make_manager()
    try:
        with pytest.raises(UnknownVenueAccountConfigKeyError) as excinfo:
            manager.bring_online(_row({"sandox": True}))

        message = str(excinfo.value)
        # The offending key, so the operator can find it in their row...
        assert "sandox" in message
        # ...and the LEGAL set, so they do not have to open the source to guess.
        for legal in ("sandbox", "region", "market_type"):
            assert legal in message

        assert manager.is_online(_VENUE, "acct-1") is False
        assert routing == {}
    finally:
        store.dispose()


def test_an_unrecognised_key_raises_even_beside_valid_ones() -> None:
    """A good key does not buy a bad one a pass — validation precedes the merge."""
    manager, store, routing = _make_manager()
    try:
        with pytest.raises(UnknownVenueAccountConfigKeyError):
            manager.bring_online(_row({"sandbox": True, "market-type": "spot"}))
        assert routing == {}
    finally:
        store.dispose()


def test_the_allowlist_names_exactly_the_three_mergeable_keys() -> None:
    """The allowlist is EXPLICIT and EXHAUSTIVE.

    Pinned as a set rather than inferred from behaviour: a fourth key added without a
    consumer would be an inert key an operator could set to no effect, and a key silently
    removed would start refusing rows that used to work.
    """
    from itrader.venues.accounts import _MERGEABLE_CONFIG_KEYS

    assert _MERGEABLE_CONFIG_KEYS == frozenset({"sandbox", "region", "market_type"})


def test_an_out_of_vocabulary_market_type_refuses() -> None:
    """A recognised KEY with an unrecognised VALUE is refused too (money-critical).

    ``market_type`` selects which channel the execution adapter reads position truth from,
    so ``"spott"`` would sail through AS a derivative: ``fetch_positions`` answers ``[]`` on
    a spot account, so the account reports FLAT while it holds coins, with nothing anywhere
    raising. ``region`` needs no equivalent check — ``OkxSettings.region`` is a ``Literal``
    that fails loud at build — so the venue keeps ownership of its own vocabulary.
    """
    manager, store, routing = _make_manager()
    try:
        with pytest.raises(ValidationError) as excinfo:
            manager.bring_online(_row({"market_type": "spott"}))

        assert "spott" in str(excinfo.value)
        assert routing == {}
    finally:
        store.dispose()


def test_a_non_boolean_sandbox_refuses() -> None:
    """``sandbox`` must be a real bool — ``"false"`` is TRUTHY and would invert the host.

    A JSON column happily holds the STRING ``"false"``, and every truthiness test in Python
    then reads it as True. An account an operator pinned to production would quietly connect
    to the demo host, or the reverse.
    """
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(ValidationError):
            manager.bring_online(_row({"sandbox": "false"}))
    finally:
        store.dispose()


def test_the_merged_spec_still_carries_the_accounts_own_secret_ref() -> None:
    """The merge must not displace the highest-consequence field on the spec.

    ``secret_ref`` is what makes two accounts authenticate as two accounts; a merge that
    rebuilt the spec and dropped it would silently revert every named account to the
    ambient credentials.
    """
    manager, store, _ = _make_manager()
    try:
        row = dict(_row({"region": "eea"}))
        row["secret_ref"] = "env:ACCT_1"
        record = manager.bring_online(row)

        assert record.spec.secret_ref == "env:ACCT_1"
        assert record.spec.region == "eea"
    finally:
        store.dispose()


def test_the_account_spec_is_frozen() -> None:
    """A spec is what a session WAS built from, so it cannot be retuned afterwards.

    ``secret_ref`` / ``sandbox`` / ``region`` are the fields the pool memoizes a session
    against; mutating one after the build would leave the recorded identity describing a
    session that no longer matches it.
    """
    spec = AccountSpec(venue_name=_VENUE, account_id="acct-1")
    with pytest.raises(Exception):
        spec.secret_ref = "env:OTHER"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Registration-LAST: the ordering gates
# --------------------------------------------------------------------------- #


class _RefusingConnectAdapter:
    """An adapter whose ``connect()`` raises — a session that never opens."""

    def connect(self) -> ConnectionResult:
        raise RuntimeError("venue session refused to open")

    def fetch_venue_uid(self) -> str | None:  # pragma: no cover - never reached
        return None


class _FailedResultAdapter:
    """An adapter whose ``connect()`` RETURNS a failure rather than raising.

    ``AbstractExchange.connect`` returns a result object, so a bring-up that ignored it
    would register an adapter whose streams never spawned — every order mirror stays
    PENDING forever while the account looks healthy.
    """

    def connect(self) -> ConnectionResult:
        return ConnectionResult(
            success=False,
            status=ExchangeConnectionStatus.ERROR,
            exchange_name="paper",
            error_message="stream spawn failed")

    def fetch_venue_uid(self) -> str | None:  # pragma: no cover - never reached
        return None


def test_a_raising_connect_during_bring_up_leaves_the_routing_map_empty() -> None:
    """The account must be UNROUTABLE when its session never opened.

    The routing map is the same ``(venue, account_id) -> adapter`` dict the order path
    reads, so a populated map after a failed bring-up means real orders route into a
    session that never opened.
    """
    manager, store, routing = _make_manager(
        exchange_recipes={_VENUE: lambda **kwargs: _RefusingConnectAdapter()})
    try:
        row = manager.provision(_VENUE, "acct-1")
        with pytest.raises(RuntimeError):
            manager.bring_online(row)

        assert routing == {}
        assert manager.online_records() == []
        assert manager.is_online(_VENUE, "acct-1") is False
    finally:
        store.dispose()


def test_an_unsuccessful_connect_result_is_raised_not_swallowed() -> None:
    """A failed ``ConnectionResult`` aborts the bring-up and registers nothing."""
    manager, store, routing = _make_manager(
        exchange_recipes={_VENUE: lambda **kwargs: _FailedResultAdapter()})
    try:
        row = manager.provision(_VENUE, "acct-1")
        with pytest.raises(RuntimeError) as excinfo:
            manager.bring_online(row)

        assert "stream spawn failed" in str(excinfo.value)
        assert routing == {}
    finally:
        store.dispose()


class _RecordingAlertSink:
    """An ``AlertSink`` double capturing every escalated ``ErrorEvent``."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def alert(self, event: Any) -> None:
        self.events.append(event)


class _UidAdapter:
    """A connectable adapter reporting a fixed venue UID."""

    def __init__(self, uid: str | None) -> None:
        self._uid = uid
        self.halt_signal: Any = None
        self.stream_listeners: Any = None

    def connect(self) -> ConnectionResult:
        return ConnectionResult(
            success=True,
            status=ExchangeConnectionStatus.CONNECTED,
            exchange_name="fake")

    def disconnect(self) -> ConnectionResult:
        return ConnectionResult(
            success=True,
            status=ExchangeConnectionStatus.DISCONNECTED,
            exchange_name="fake")

    def fetch_venue_uid(self) -> str | None:
        return self._uid

    def set_halt_signal(self, halt_signal: Any) -> None:
        self.halt_signal = halt_signal

    def set_stream_state_listener(self, on_down: Any, on_up: Any) -> None:
        self.stream_listeners = (on_down, on_up)


class _FakeConnector:
    """A session double: connectable, closable, halt-wirable."""

    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False
        self.halt_signal: Any = None

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def set_halt_signal(self, halt_signal: Any) -> None:
        self.halt_signal = halt_signal


#: A credentialed venue whose descriptor declares a credential model, so the manager opens
#: a session for it and the identity guard treats a missing UID as a degradation.
_CREDENTIALED = VenueDescriptor(
    name="fakevenue",
    credential_model=SqlSettings,
    capabilities=frozenset({VenueCapability.EXECUTION}),
    data_requires_auth=False,
    default_data_provider="okx",
)


def _credentialed_manager(
    *, uid: str | None, connectors: list[_FakeConnector], adapters: list[_UidAdapter],
    alert_sink: Any,
) -> tuple[VenueAccountManager, VenueAccountStore, dict[tuple[str, str], Any]]:
    """A manager over a venue that HAS a session, so the whole bring-up path runs."""
    def _connector_recipe(**kwargs: Any) -> Any:
        connector = _FakeConnector()
        connectors.append(connector)
        return connector

    def _exchange_recipe(**kwargs: Any) -> Any:
        adapter = _UidAdapter(uid)
        adapters.append(adapter)
        return adapter

    return _make_manager(
        catalog={"fakevenue": _CREDENTIALED},
        pool=ConnectorPool(
            catalog={"fakevenue": _CREDENTIALED}, resolver=None,
            recipes={"fakevenue": _connector_recipe}),
        exchange_recipes={"fakevenue": _exchange_recipe},
        alert_sink=alert_sink,
    )


def test_a_venue_identity_mismatch_leaves_the_account_unroutable_and_alerts() -> None:
    """The account connected with ANOTHER account's credentials must not become routable.

    The guard itself stays observe-only — it alerts and reports, it never halts the engine —
    but registration is the last step of the bring-up, so the manager refuses to complete a
    bring-up the guard flagged. The blast radius is exactly this account: everything else
    stays online.
    """
    sink = _RecordingAlertSink()
    connectors: list[_FakeConnector] = []
    adapters: list[_UidAdapter] = []
    manager, store, routing = _credentialed_manager(
        uid="uid-IMPOSTOR", connectors=connectors, adapters=adapters, alert_sink=sink)
    try:
        store.upsert("fakevenue", "acct-1", secret_ref=None, venue_uid="uid-TRUSTED",
                     enabled=True, config={}, at=_AT)
        row = store.read_enabled_for("fakevenue")[0]

        with pytest.raises(Exception):
            manager.bring_online(row)

        assert routing == {}
        assert manager.is_online("fakevenue", "acct-1") is False
        assert [event.error_type for event in sink.events] == [
            VENUE_UID_MISMATCH_REASON]
        # The trusted first-seen value survives — the guard is never self-healing.
        assert store.get("fakevenue", "acct-1")["venue_uid"] == "uid-TRUSTED"
    finally:
        store.dispose()


def test_a_session_bearing_account_is_halt_wired_before_it_is_routable() -> None:
    """The adapter AND its session are armed at bring-up, not by a separate later pass.

    An adapter registered before its halt seam is armed accepts orders while its streams
    have no way to escalate a fatal error — the arm looks healthy and silently stops
    delivering fills.
    """
    sink = _RecordingAlertSink()
    connectors: list[_FakeConnector] = []
    adapters: list[_UidAdapter] = []
    manager, store, routing = _credentialed_manager(
        uid="uid-1", connectors=connectors, adapters=adapters, alert_sink=sink)
    try:
        store.upsert("fakevenue", "acct-1", secret_ref=None, venue_uid=None,
                     enabled=True, config={}, at=_AT)
        record = manager.bring_online(store.read_enabled_for("fakevenue")[0])

        assert record.adapter.halt_signal is not None
        assert record.adapter.stream_listeners is not None
        assert record.connector is not None
        assert record.connector.halt_signal is not None
        assert record.connector.connected is True
        assert routing[("fakevenue", "acct-1")] is record.adapter
        # Trust on first use: the venue's UID was recorded through the real path.
        assert store.get("fakevenue", "acct-1")["venue_uid"] == "uid-1"
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# Per-account teardown
# --------------------------------------------------------------------------- #


def test_bring_offline_tears_down_only_its_own_account() -> None:
    """Retiring one account leaves every other account online and routable.

    The defect this pins: a teardown that closed the whole session pool would disconnect
    every OTHER account's streams too, so accounts nobody retired would stop receiving
    fills while still reporting online.
    """
    sink = _RecordingAlertSink()
    connectors: list[_FakeConnector] = []
    adapters: list[_UidAdapter] = []
    manager, store, routing = _credentialed_manager(
        uid=None, connectors=connectors, adapters=adapters, alert_sink=sink)
    try:
        for account in ("acct-1", "acct-2"):
            store.upsert("fakevenue", account, secret_ref=None, venue_uid=None,
                         enabled=True, config={}, at=_AT)
        for row in store.read_enabled_for("fakevenue"):
            manager.bring_online(row)
        assert len(routing) == 2

        manager.bring_offline("fakevenue", "acct-1")

        assert ("fakevenue", "acct-1") not in routing
        assert ("fakevenue", "acct-2") in routing
        assert manager.is_online("fakevenue", "acct-2") is True
        retired, survivor = connectors
        assert retired.disconnected is True
        assert survivor.disconnected is False, (
            "retiring one account closed another account's session")
    finally:
        store.dispose()


def test_bring_offline_on_a_pair_that_is_not_online_is_a_clean_noop() -> None:
    """Teardown runs on every path, including one where bring-up never completed."""
    manager, store, routing = _make_manager()
    try:
        manager.bring_offline(_VENUE, "never-online")
        assert routing == {}
    finally:
        store.dispose()


def test_a_raising_adapter_disconnect_still_releases_the_routing_entry() -> None:
    """A pair whose teardown raises must already be unroutable.

    The routing entry is dropped first, so a half-torn-down session is never reachable by
    an order.
    """
    class _RaisingDisconnect(_UidAdapter):
        def disconnect(self) -> ConnectionResult:
            raise RuntimeError("teardown exploded")

    sink = _RecordingAlertSink()
    connectors: list[_FakeConnector] = []

    def _connector_recipe(**kwargs: Any) -> Any:
        connector = _FakeConnector()
        connectors.append(connector)
        return connector

    manager, store, routing = _make_manager(
        catalog={"fakevenue": _CREDENTIALED},
        pool=ConnectorPool(
            catalog={"fakevenue": _CREDENTIALED}, resolver=None,
            recipes={"fakevenue": _connector_recipe}),
        exchange_recipes={"fakevenue": lambda **kwargs: _RaisingDisconnect(None)},
        alert_sink=sink,
    )
    try:
        store.upsert("fakevenue", "acct-1", secret_ref=None, venue_uid=None,
                     enabled=True, config={}, at=_AT)
        manager.bring_online(store.read_enabled_for("fakevenue")[0])

        manager.bring_offline("fakevenue", "acct-1")

        assert routing == {}
        assert manager.online_records() == []
        # The session is still released even though the adapter's teardown raised.
        assert connectors[0].disconnected is True
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# The per-pair identity-guard outcome surfaced on the manager
# --------------------------------------------------------------------------- #


def test_bring_online_surfaces_a_per_pair_guard_outcome() -> None:
    """Every online pair has an outcome OBJECT with a reason, not a bare bool.

    A bare boolean tells an operator the guard is off but not which of its holes they have,
    and the holes need different fixes.
    """
    manager, store, _ = _make_manager()
    try:
        manager.bring_online(manager.provision(_VENUE, "acct-1"))

        outcome = manager.venue_uid_guard_active()[(_VENUE, "acct-1")]

        assert not isinstance(outcome, bool)
        assert isinstance(outcome.reason, str) and outcome.reason
        # Paper declares no credential model, so it has no venue identity to protect.
        assert outcome.armed is False
        assert outcome.reason == "no-venue-identity"
    finally:
        store.dispose()


def test_two_pairs_report_their_guard_outcomes_independently() -> None:
    """One pair's guard state never masks another's.

    The map is keyed per pair for exactly this reason: a single flag on the manager would
    collapse two accounts' guard states into one, so an inert guard on account A would hide
    an armed guard on account B.
    """
    manager, store, _ = _make_manager()
    try:
        for account in ("acct-1", "acct-2"):
            manager.bring_online(manager.provision(_VENUE, account))

        active = manager.venue_uid_guard_active()
        assert (_VENUE, "acct-1") in active
        assert (_VENUE, "acct-2") in active
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# Availability, and the distinguishable causes
# --------------------------------------------------------------------------- #


def test_assert_available_on_an_absent_row_raises_not_provisioned() -> None:
    """No row at all. The operator must provision the account."""
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.assert_available(_VENUE, "ghost")
        assert excinfo.value.cause == VenueAccountNotProvisionedError.NOT_PROVISIONED
    finally:
        store.dispose()


def test_assert_available_on_a_disabled_row_raises_with_a_distinguishable_cause() -> None:
    """The row EXISTS but is disabled; that is a different operator action.

    Collapsing this into "not provisioned" would send an operator to re-provision an
    account that already exists — which then refuses as a duplicate, leaving them with two
    contradictory errors and no true one.
    """
    manager, store, _ = _make_manager()
    try:
        store.upsert(_VENUE, "acct-1", secret_ref=None, venue_uid=None,
                     enabled=False, config={}, at=_AT)
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.assert_available(_VENUE, "acct-1")
        assert excinfo.value.cause == VenueAccountNotProvisionedError.DISABLED
    finally:
        store.dispose()


def test_online_for_a_provisioned_but_never_brought_up_row_raises_not_online() -> None:
    """The distinction only the manager can make.

    An enabled row this process never brought online is NOT "no such account": it was
    provisioned after its venue came up. Answering with anything but a refusal would hand a
    caller a runtime that does not exist.
    """
    manager, store, _ = _make_manager()
    try:
        manager.provision(_VENUE, "acct-1")
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.online(_VENUE, "acct-1")
        assert excinfo.value.cause == VenueAccountNotProvisionedError.NOT_ONLINE
    finally:
        store.dispose()


def test_account_id_matching_is_exact_string() -> None:
    """No case-folding, no trimming, no normalization, anywhere.

    ``'ACCT-1'``, ``' acct-1'`` and ``'acct-1 '`` are three DIFFERENT accounts. A layer that
    trimmed or case-folded would resolve an operator's typo onto a real, funded account's
    authenticated session.
    """
    manager, store, _ = _make_manager()
    try:
        manager.bring_online(manager.provision(_VENUE, "acct-1"))

        for near_miss in ("ACCT-1", " acct-1", "acct-1 ", "Acct-1"):
            with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
                manager.assert_available(_VENUE, near_miss)
            assert excinfo.value.cause == (
                VenueAccountNotProvisionedError.NOT_PROVISIONED)
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# An account refuses to be disabled while a live portfolio depends on it
# --------------------------------------------------------------------------- #
#
# The blocking set is resolved against the DURABLE store (a live portfolio is one whose
# definition row has enabled=True AND NOT is_deleted), NOT a live in-memory portfolio
# collaborator — pause and retire are durable, so the block a disable must respect is
# durable too, and the manager keeps no portfolio-handler back-reference.


def _manager_with_portfolio_schema():
    """A manager whose engine ALSO has the ``portfolios`` table created.

    ``_make_manager`` provisions the schema BEFORE constructing the manager, but the manager
    is what registers ``portfolios`` (it builds a ``PortfolioDefinitionStore`` view over the
    shared engine). So provision AGAIN afterwards — ``create_all(checkfirst=True)`` is
    idempotent and now also creates the freshly-registered table.
    """
    manager, store, _routing = _make_manager()
    provision_schema(store.backend)
    definitions = PortfolioDefinitionStore(store.backend)
    return manager, store, definitions


def _seed_account_and_portfolio(
    store, definitions, venue, account_id, portfolio_id, *, portfolio_enabled=True
):
    """A venue account parent + one portfolio definition row referencing it."""
    store.upsert(venue, account_id, secret_ref=None, venue_uid=None,
                 enabled=True, config={}, at=_AT)
    definitions.upsert(
        portfolio_id, name="pf", venue_name=venue, account_id=account_id,
        initial_cash=Decimal("1000"), enabled=portfolio_enabled, config=None, at=_AT)


def test_disabling_an_account_a_live_portfolio_needs_is_refused_unchanged() -> None:
    """The refusal names the blocking portfolio and leaves the account row unchanged."""
    manager, store, definitions = _manager_with_portfolio_schema()
    try:
        pid = _uuid.UUID("01930000-0000-7000-8000-0000000000a1")
        _seed_account_and_portfolio(store, definitions, _VENUE, "acct-1", pid)

        before = store.get(_VENUE, "acct-1")
        with pytest.raises(VenueAccountInUseError) as excinfo:
            manager.set_enabled(_VENUE, "acct-1", False)

        assert pid in excinfo.value.portfolio_ids
        # The account row is byte-identical — a refused disable writes NOTHING.
        assert store.get(_VENUE, "acct-1") == before
    finally:
        store.dispose()


def test_pausing_the_portfolio_releases_the_block_and_the_disable_succeeds() -> None:
    """A PAUSED portfolio (enabled=False) no longer blocks; pausing IS the release."""
    manager, store, definitions = _manager_with_portfolio_schema()
    try:
        pid = _uuid.UUID("01930000-0000-7000-8000-0000000000a2")
        _seed_account_and_portfolio(store, definitions, _VENUE, "acct-1", pid)

        definitions.set_enabled(pid, False, _AT)
        manager.set_enabled(_VENUE, "acct-1", False)

        assert store.get(_VENUE, "acct-1")["enabled"] is False
    finally:
        store.dispose()


def test_a_retired_portfolio_does_not_block_the_disable() -> None:
    """A RETIRED portfolio (is_deleted=True) has released its pair; disable succeeds."""
    manager, store, definitions = _manager_with_portfolio_schema()
    try:
        pid = _uuid.UUID("01930000-0000-7000-8000-0000000000a3")
        _seed_account_and_portfolio(store, definitions, _VENUE, "acct-1", pid)

        definitions.set_deleted(pid, True, _AT)
        manager.set_enabled(_VENUE, "acct-1", False)

        assert store.get(_VENUE, "acct-1")["enabled"] is False
    finally:
        store.dispose()


def test_disabling_an_unreferenced_account_succeeds() -> None:
    """No live portfolio depends on the account, so the disable persists."""
    manager, store, definitions = _manager_with_portfolio_schema()
    try:
        store.upsert(_VENUE, "acct-lonely", secret_ref=None, venue_uid=None,
                     enabled=True, config={}, at=_AT)

        manager.set_enabled(_VENUE, "acct-lonely", False)

        assert store.get(_VENUE, "acct-lonely")["enabled"] is False
    finally:
        store.dispose()


def test_enabling_an_account_is_never_refused() -> None:
    """The refusal guards a DISABLE only; enabling a disabled account always works."""
    manager, store, definitions = _manager_with_portfolio_schema()
    try:
        pid = _uuid.UUID("01930000-0000-7000-8000-0000000000a4")
        _seed_account_and_portfolio(store, definitions, _VENUE, "acct-1", pid)
        store.set_enabled(_VENUE, "acct-1", False, _AT)

        manager.set_enabled(_VENUE, "acct-1", True)

        assert store.get(_VENUE, "acct-1")["enabled"] is True
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# The trust-on-first-use identity guard, driven directly
# --------------------------------------------------------------------------- #
#
# The guard exists because per-account credentials make the MISROUTE reachable: a mistyped
# ``secret_ref`` or a swapped vault entry means an ``account_id`` connects with a DIFFERENT
# account's keys, orders route to the wrong REAL account, and reconciliation then succeeds
# cleanly against it. The venue's self-reported account UID is the only external evidence
# that the session belongs to the account the engine thinks it does.


class _FakeStore:
    """An in-memory ``VenueAccountStore`` double recording every write."""

    def __init__(self, venue_uid: str | None = None, exists: bool = True) -> None:
        self._row: dict[str, Any] | None = (
            {
                "venue_name": "okx",
                "account_id": "acct-a",
                "secret_ref": "env:OKX_ACCT_A",
                "venue_uid": venue_uid,
                "enabled": True,
                "config": {},
                "updated_at": _AT,
            }
            if exists
            else None
        )
        self.recorded: list[tuple[str, str, str, datetime]] = []

    def get(self, venue_name: str, account_id: str) -> dict[str, Any] | None:
        return self._row

    def record_venue_uid(
        self, venue_name: str, account_id: str, venue_uid: str, at: datetime
    ) -> None:
        self.recorded.append((venue_name, account_id, venue_uid, at))
        if self._row is not None:
            self._row["venue_uid"] = venue_uid


class _ExplodingStore:
    """A store whose every read/write fails — the storage-outage case."""

    def get(self, venue_name: str, account_id: str) -> dict[str, Any] | None:
        raise RuntimeError("database is unreachable")

    def record_venue_uid(
        self, venue_name: str, account_id: str, venue_uid: str, at: datetime
    ) -> None:
        raise RuntimeError("database is unreachable")


class _WriteOnlyExplodingStore(_FakeStore):
    """A store that READS fine but whose ``record_venue_uid`` fails.

    Distinct from ``_ExplodingStore``: the read-failure and the write-failure are two
    DIFFERENT inertness paths needing two different operator investigations (a broken query
    path vs a broken write path / read-only replica), so they must not collapse into one
    reason.
    """

    def record_venue_uid(
        self, venue_name: str, account_id: str, venue_uid: str, at: datetime
    ) -> None:
        raise RuntimeError("the account row is read-only")


class _RaisingUidAdapter(_UidAdapter):
    """An adapter whose ``fetch_venue_uid`` RAISES (a broken adapter contract)."""

    def fetch_venue_uid(self) -> str | None:
        raise RuntimeError("the venue endpoint exploded")


#: A venue with NO credentials and no venue-side UID — the paper shape.
_CREDENTIAL_LESS = VenueDescriptor(
    name="paperlike",
    credential_model=None,
    capabilities=frozenset({VenueCapability.EXECUTION}),
    data_requires_auth=False,
    default_data_provider="okx",
)


def _guard(
    *,
    adapter: Any,
    store: Any,
    alert_sink: Any,
    descriptor: Any = _CREDENTIALED,
) -> Any:
    """Drive the guard with the standard okx/acct-a pair; return its outcome."""
    return assert_venue_uid(
        descriptor=descriptor,
        adapter=adapter,
        venue_name="okx",
        account_id="acct-a",
        store=store,
        alert_sink=alert_sink,
        at=_AT,
    )


def test_first_connect_records_the_uid_and_emits_zero_alerts() -> None:
    """A NULL stored ``venue_uid`` is the first connect: RECORD it, alert nothing.

    Trust-on-first-use is the half that removes the operator from the loop: the first
    connect establishes the expected value, so there is no field to look up and mistype. The
    rejected alternative — an operator-declared expected UID — adds a typo surface whose
    failure mode is blocking a correctly-configured account.
    """
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    _guard(adapter=_UidAdapter("uid-111"), store=store, alert_sink=sink)

    assert store.recorded == [("okx", "acct-a", "uid-111", _AT)]
    assert sink.events == []


def test_matching_later_connect_writes_nothing_and_alerts_nothing() -> None:
    """The steady state: a UID equal to the stored one is completely silent."""
    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    _guard(adapter=_UidAdapter("uid-111"), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []


def test_mismatch_emits_exactly_one_critical_alert_and_returns_normally() -> None:
    """THE spoofing detector: one CRITICAL alert, no raise out of the guard, no halt.

    The guard RETURNS is the explicit decision. A venue reporting its UID differently across
    endpoints must not take the whole engine down; refusing to make THAT ONE account
    routable (the manager's job, asserted above) is the proportionate response.
    """
    from itrader.core.enums import ErrorSeverity

    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    # No pytest.raises wrapper: the call returning at all IS the assertion.
    _guard(adapter=_UidAdapter("uid-999"), store=store, alert_sink=sink)

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.severity is ErrorSeverity.CRITICAL
    # A FIXED LITERAL reason, never a stringified exception or an interpolated payload.
    assert event.error_type == VENUE_UID_MISMATCH_REASON
    # The operator needs the pair and both UIDs to act on the alert.
    assert event.details is not None
    assert event.details["venue_name"] == "okx"
    assert event.details["account_id"] == "acct-a"
    assert event.details["recorded_venue_uid"] == "uid-111"
    assert event.details["observed_venue_uid"] == "uid-999"


def test_mismatch_does_not_overwrite_the_recorded_uid() -> None:
    """The RECORDED value is the trusted one and survives the mismatch.

    Overwriting on mismatch would make the guard self-healing — it would alert once and then
    happily accept the impostor forever.
    """
    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    _guard(adapter=_UidAdapter("uid-999"), store=store, alert_sink=sink)

    assert store.recorded == []
    assert store.get("okx", "acct-a")["venue_uid"] == "uid-111"


def test_mismatch_alert_carries_no_credential_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The alert payload leaks no secret and no ``secret_ref`` VALUE."""
    monkeypatch.setenv("OKX_ACCT_A_API_KEY", _SEEDED_SECRET)

    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    _guard(adapter=_UidAdapter("uid-999"), store=store, alert_sink=sink)

    rendered = repr(sink.events[0]) + repr(sink.events[0].details)
    assert _SEEDED_SECRET not in rendered
    assert "env:OKX_ACCT_A" not in rendered


def test_a_credential_less_venue_reporting_no_uid_is_a_clean_no_op() -> None:
    """A venue with no credentials has no identity: nothing recorded, nothing alerted."""
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    _guard(adapter=_UidAdapter(None), store=store, alert_sink=sink,
           descriptor=_CREDENTIAL_LESS)

    assert store.recorded == []
    assert sink.events == []


def test_a_credentialed_venue_yielding_no_uid_warns_rather_than_failing_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A venue that SHOULD expose a UID but yields ``None`` must not degrade silently.

    Otherwise a renamed venue field or a revoked read scope permanently disables the only
    spoofing detector with zero signal — the guard would keep "passing" forever.
    """
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    with caplog.at_level("WARNING"):
        _guard(adapter=_UidAdapter(None), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []
    assert any("venue-uid" in record.getMessage().lower() for record in caplog.records)


def test_a_store_outage_is_swallowed_and_never_breaks_a_healthy_connect() -> None:
    """A storage failure logs and returns — the guard cannot abort a good connect."""
    sink = _RecordingAlertSink()

    # The call completing without raising IS the assertion.
    _guard(adapter=_UidAdapter("uid-111"), store=_ExplodingStore(), alert_sink=sink)

    assert sink.events == []


def test_a_missing_account_row_is_a_no_op() -> None:
    """No row for the pair: record nothing, alert nothing.

    The guard deliberately does not create rows — it would invent an operator record from a
    connect-time code path.
    """
    store = _FakeStore(exists=False)
    sink = _RecordingAlertSink()

    _guard(adapter=_UidAdapter("uid-111"), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []


def test_each_of_the_six_inertness_paths_reports_a_DISTINCT_reason() -> None:
    """The six paths each need a different fix, so none may collapse into another.

    A bare boolean tells an operator the guard is off but not WHICH HOLE they have, and
    these six need six different actions — fix the adapter's contract, restore the renamed
    UID field, accept the credential-less no-op, restore the database read path, provision
    the missing row, fix the write path.
    """
    from itrader.venues.accounts import (
        GUARD_INERT,
        REASON_FETCH_RAISED,
        REASON_NO_ACCOUNT_ROW,
        REASON_NO_VENUE_IDENTITY,
        REASON_RECORD_WRITE_FAILED,
        REASON_STORE_READ_FAILED,
        REASON_UID_UNAVAILABLE_CREDENTIALED,
    )

    cases = {
        # 1. the adapter's fetch raised (a broken adapter contract)
        REASON_FETCH_RAISED: (
            _RaisingUidAdapter("unused"), _FakeStore(venue_uid=None), _CREDENTIALED),
        # 2. a CREDENTIALED venue supplied no uid (renamed field / revoked read scope)
        REASON_UID_UNAVAILABLE_CREDENTIALED: (
            _UidAdapter(None), _FakeStore(venue_uid=None), _CREDENTIALED),
        # 3. the venue declares NO credentials and has no venue-side identity (paper)
        REASON_NO_VENUE_IDENTITY: (
            _UidAdapter(None), _FakeStore(venue_uid=None), _CREDENTIAL_LESS),
        # 4. the store READ failed (database outage)
        REASON_STORE_READ_FAILED: (
            _UidAdapter("uid-111"), _ExplodingStore(), _CREDENTIALED),
        # 5. no account row for this pair yet
        REASON_NO_ACCOUNT_ROW: (
            _UidAdapter("uid-111"), _FakeStore(exists=False), _CREDENTIALED),
        # 6. the first-connect record WRITE failed
        REASON_RECORD_WRITE_FAILED: (
            _UidAdapter("uid-111"), _WriteOnlyExplodingStore(venue_uid=None),
            _CREDENTIALED),
    }

    observed = {}
    for expected_reason, (adapter, store, descriptor) in cases.items():
        outcome = _guard(
            adapter=adapter, store=store, alert_sink=_RecordingAlertSink(),
            descriptor=descriptor)
        assert outcome.outcome == GUARD_INERT, expected_reason
        assert outcome.reason == expected_reason
        observed[expected_reason] = outcome.reason

    # SIX paths, SIX distinct reasons — no two collapsed.
    assert len(set(observed.values())) == 6


def test_the_guard_reports_armed_on_record_match_and_detection() -> None:
    """Recording, confirming and CATCHING are all the guard working, never idle.

    Reporting a mismatch as anything but armed would invert the operator's reading of the
    status at exactly the moment it matters most.
    """
    from itrader.venues.accounts import (
        GUARD_ARMED,
        REASON_ASSERTED_MATCH,
        REASON_MISMATCH_ALERTED,
        REASON_RECORDED_FIRST_CONNECT,
    )

    recorded = _guard(
        adapter=_UidAdapter("uid-111"), store=_FakeStore(venue_uid=None),
        alert_sink=_RecordingAlertSink())
    matched = _guard(
        adapter=_UidAdapter("uid-111"), store=_FakeStore(venue_uid="uid-111"),
        alert_sink=_RecordingAlertSink())
    detected = _guard(
        adapter=_UidAdapter("uid-999"), store=_FakeStore(venue_uid="uid-111"),
        alert_sink=_RecordingAlertSink())

    assert [outcome.outcome for outcome in (recorded, matched, detected)] == (
        [GUARD_ARMED] * 3)
    assert recorded.reason == REASON_RECORDED_FIRST_CONNECT
    assert matched.reason == REASON_ASSERTED_MATCH
    assert detected.reason == REASON_MISMATCH_ALERTED
