"""Unit contract for VenueAccountManager — the venue-ACCOUNT domain owner (11.2-05).

Proves:

  - **ACCT-01 the account set is STORE-DERIVED, VENUE-SCOPED and ORDERED.** It comes off
    durable rows, one venue never sees another's accounts (``account_id`` alone cannot
    derive its venue — D-01), disabled rows are excluded, and the order is
    ``account_id`` ASC so bring-up is reproducible rather than driver-dependent.
  - **ACCT-01 the empty case is SUPPORTED.** Zero enabled rows yields ``[]`` and no error
    — a fresh deployment comes up RUNNING and empty (D-09).
  - **D-34 the degrade is NARROW.** A missing ``venue_accounts`` TABLE warns and returns
    ``[]``; ANY other fault propagates LOUD. Both halves are asserted, and the second is
    the one that matters: under DB-as-sole-truth a swallowed read means zero accounts, and
    then an ACCT-03 refusal for every persisted portfolio — N derived errors burying the
    one real cause. The whole policy is exercised here WITHOUT booting a system, which is
    why D-34 places it on the manager rather than in the store.
  - **D-11 provisioning is CREATE-ONLY.** A second ``provision`` of the same pair raises
    the typed refusal and writes nothing; the classification comes from the database's
    ``IntegrityError``, never a pre-check ``SELECT`` (TOCTOU, and blind to out-of-band
    writers). The existing row is asserted UNCHANGED, because a silent overwrite — not the
    missing raise — is the actual damage.
  - **D-27 provision and bring_online are TWO verbs.** ``provision`` alone leaves the
    account offline; the pair together makes it usable in the same process, no restart.
  - **ACCT-03 refusal, with the cause DISTINGUISHED.** "no such row" / "row disabled" /
    "provisioned after boot, never assembled" are three different operator actions, and
    only the manager can tell them apart (D-21). Each is asserted separately.
  - **ACCT-03 encoding: EXACT-STRING matching.** No case-folding, trimming or
    normalization, so ``' okx-1'`` and ``'okx-1'`` never resolve to each other.
  - **The delegation is under the EXACT pair,** proven with TWO independent signals — a
    call record AND a per-call identity sentinel — because a counter alone is satisfied by
    a memo that returns the wrong entry.

The store is REAL (in-memory SQLite): the D-34 probe inspects a live engine and the D-11
refusal is the database's own, so faking either would test the fake. ``VenueBundles`` is
faked structurally where only delegation is under test, and real where ``bring_online``
must actually assemble.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named top-level
test packages break full-suite collection). 4-space indentation.
"""

from __future__ import annotations

import queue
import random
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.config import ExchangeConfig
from itrader.config.sql import SqlSettings
from itrader.connectors.provider import ConnectorProvider
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.core.exceptions import (
    DuplicateVenueAccountProvisionError,
    UnknownVenueAccountConfigKeyError,
    ValidationError,
    VenueAccountNotProvisionedError,
)
from itrader.storage import SqlEngine
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.venues.bundles import VenueBundles
from itrader.venues.paper_plugin import PaperVenuePlugin
from itrader.venues.registry import COMPUTE_VENUE, ExecutionVenueRegistry
from itrader.venues.venue_account_manager import VenueAccountManager
from tests.support.schema import provision_schema
from tests.support.venue_wiring import in_memory_state_storage

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = COMPUTE_VENUE


class _NoopFeedBinder:
    """A do-nothing D-36 feed binder for the ACCT-01/02/03 paper tests.

    Feed binding is exercised in ``test_feed_binder.py``; here the paper accounts under
    test carry ``connector=None`` (no streaming connection), so ``rebind`` never has a
    connection to borrow. The manager still DRIVES the binder on every ``bring_online``,
    so this satisfies its required-collaborator contract without pulling a real provider
    build into tests that are about the account domain, not the feed.
    """

    feed_provider = None

    def rebind(self, available: Any) -> None:  # noqa: D401 - trivial no-op
        return None


class _RecordingBundles:
    """A REAL ``VenueBundles`` with only ``account_for`` instrumented.

    ``get`` / ``plugin_for`` pass straight through, so ``bring_online`` performs genuine
    assembly; only the construction hand-off is observed. Two INDEPENDENT signals per
    assertion — the recorded ``(venue, account_id)`` argument tuple AND a fresh identity
    sentinel per call. A call counter alone is satisfied by a memo that answers with some
    OTHER account's leaf, which is exactly the defect the pair key exists to prevent.
    """

    def __init__(self, inner: VenueBundles) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def plugin_for(self, venue: str) -> Any:
        return self._inner.plugin_for(venue)

    def get(self, venue: str, account_id: str, spec: Any) -> Any:
        return self._inner.get(venue, account_id, spec)

    def account_for(
        self, venue: str, account_id: str, *, spec: Any = None, **portfolio_args: Any
    ) -> Any:
        self.calls.append((venue, account_id, dict(portfolio_args)))
        return SimpleNamespace(
            venue=venue, account_id=account_id, seq=len(self.calls), spec=spec)


def _real_bundles() -> VenueBundles:
    """The backtest-shaped memo over the REAL paper plugin — what ``bring_online`` assembles."""
    registry = ExecutionVenueRegistry()
    registry.register(_VENUE, PaperVenuePlugin(ExchangeConfig.default()))
    connectors = ConnectorProvider({})
    ctx = SimpleNamespace(bus=queue.Queue(), rng=random.Random(42))
    return VenueBundles(registry, connectors, ctx)


def _make_manager(
    *, provision: bool = True, bundles: Any = None
) -> tuple[VenueAccountManager, VenueAccountStore, dict[tuple[str, str], Any]]:
    """A manager over a REAL in-memory store, optionally with its schema NOT provisioned.

    ``provision=False`` reproduces the fresh-deployment state D-34 degrades on: the store
    registers its table on the shared MetaData but nothing creates it (the stores are
    schema-pure — WR-03/D-14).

    D-43: the manager receives a bare ``(venue, account_id) -> exchange`` dict — the
    composition-root-owned registry — NOT an execution handler. ``bring_online`` writes
    this map directly, and the tests assert on it.
    """
    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    if provision:
        provision_schema(store.backend)
    registry: dict[tuple[str, str], Any] = {}
    manager = VenueAccountManager(
        store,
        bundles if bundles is not None else _real_bundles(),
        ConnectorProvider({}),
        registry,
        alert_sink=LogAlertSink(),
        feed_binder=_NoopFeedBinder(),
    )
    return manager, store, registry


# --------------------------------------------------------------------------- #
# ACCT-01 — the account set
# --------------------------------------------------------------------------- #


def test_the_account_set_is_store_derived_venue_scoped_and_ordered() -> None:
    """ACCT-01 — durable rows, this venue only, ``account_id`` ASC."""
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
    """ACCT-01/D-09 — a fresh deployment comes up empty rather than failing."""
    manager, store, _ = _make_manager()
    try:
        store.upsert(_VENUE, "retired", secret_ref=None, venue_uid=None,
                     enabled=False, config={}, at=_AT)
        assert manager.read_enabled_for(_VENUE) == []
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# D-34 — the narrow degrade
# --------------------------------------------------------------------------- #


def test_a_missing_accounts_table_degrades_with_a_warning_and_an_empty_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-34 — the fresh-deployment state warns and returns ``[]``, never raises.

    The warning is required, not incidental: a silent ``[]`` here is indistinguishable
    from "this venue genuinely has no accounts", so an un-run Alembic chain would look
    like a correctly-empty deployment forever.
    """
    manager, store, _ = _make_manager(provision=False)
    try:
        with caplog.at_level("WARNING"):
            assert manager.read_enabled_for(_VENUE) == []
        assert any(
            "venue_accounts" in record.getMessage()
            for record in caplog.records
        )
    finally:
        store.dispose()


def test_any_fault_other_than_a_missing_table_propagates_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-34 — the probe tests for the TABLE and nothing else; real faults are not swallowed.

    With the table PRESENT, a store read that fails must reach the caller. A catch-all
    handler here would turn one unreachable database into zero accounts and then into an
    ACCT-03 refusal per persisted portfolio: N derived errors hiding the one real cause.
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
# ACCT-02 / D-11 — provisioning
# --------------------------------------------------------------------------- #


def test_provision_writes_exactly_one_row_and_returns_it() -> None:
    """ACCT-02 — one durable row, carrying the account's own credential POINTER."""
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
    """D-11 — the DATABASE is the arbiter; the existing row is untouched.

    Asserting only the raise would be a false-green: the damage a duplicate provision does
    is the silent OVERWRITE of the operator's ``secret_ref``/``config`` and the reset of
    the engine-written ``venue_uid``. Both are asserted unchanged.
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


def test_provision_with_a_secret_bearing_config_refuses_and_persists_nothing() -> None:
    """The EXISTING store-side denylist is the control; the manager pins its own contract.

    The guard is NOT re-implemented on the manager (a second denylist is a drift hazard the
    store module forbids by name) — this asserts the manager inherits it, so a caller
    reaching provisioning through the manager cannot route a secret into ``config_json``.
    """
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(ValidationError):
            manager.provision(_VENUE, "acct-1", config={"api_key": "leaked"})
        assert store.get(_VENUE, "acct-1") is None
        assert store.read_all() == []
    finally:
        store.dispose()


def test_provision_does_not_bring_the_account_online() -> None:
    """D-27 — two verbs. The durable write alone builds no runtime."""
    manager, store, registry = _make_manager()
    try:
        manager.provision(_VENUE, "acct-1")
        assert manager.is_online(_VENUE, "acct-1") is False
        assert registry == {}
    finally:
        store.dispose()


def test_provision_then_bring_online_makes_the_account_usable_in_this_process() -> None:
    """D-27 — provisioned at runtime, usable with NO restart, through the ONE path."""
    manager, store, registry = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1", secret_ref="env:ACCT_1")
        record = manager.bring_online(row)

        assert manager.is_online(_VENUE, "acct-1") is True
        assert registry[(_VENUE, "acct-1")] is record.bundle.exchange
        assert record.spec.secret_ref == "env:ACCT_1"

        account = manager.account_for(
            _VENUE, "acct-1", initial_cash=Decimal("500"),
            enable_margin=False, state_storage=in_memory_state_storage())
        assert account.balance == Decimal("500")
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# D-43 — the shared exchange registry: one map, both arms
# --------------------------------------------------------------------------- #


def test_the_object_vam_registers_is_the_object_the_handler_resolves() -> None:
    """D-43 — the exact exchange VAM registers for a pair IS what the handler resolves.

    The identity assertion that proves the extraction handed BOTH handlers the SAME
    root-owned map. A mis-wire would register into one map and read the other, so every
    live order would fail closed on a lookup miss behind a green offline suite
    (T-11.2-09-06). Building a REAL ``ExecutionHandler`` over the SAME registry ``_make_
    manager`` created, then bringing an account online, exercises the whole cut edge.
    """
    manager, store, registry = _make_manager()
    try:
        execution_handler = ExecutionHandler(
            queue.Queue(), exchange_registry=registry)
        # The handler holds the SAME map object (reference identity, D-43).
        assert execution_handler.exchanges is registry

        record = manager.bring_online(manager.provision(_VENUE, "acct-1"))

        # The exact object bring_online registered is the object the handler resolves.
        assert (execution_handler.exchanges[(_VENUE, "acct-1")]
                is record.bundle.exchange)
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# D-38 / D-12 — the account-level config_json precedence merge
# --------------------------------------------------------------------------- #


def _row(config: Any) -> dict[str, Any]:
    """A durable account row carrying ``config`` VERBATIM — including ``None``.

    Built by hand rather than through ``provision`` so the ``config_json = NULL`` case
    is reachable: ``provision`` normalizes a missing config to ``{}`` before the write,
    but an out-of-band writer (an operator's SQL, an older migration) can leave the
    column NULL, and ``bring_online`` consumes the row either way.
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
    """D-38/D-12 — ``config_json`` gets its first READER, and it is the spec.

    ``config_json`` had ZERO readers before this: an operator could set it and nothing
    in the engine would ever look. The merge is what makes the column mean something,
    and the spec is where it has to land — that is the one object that travels from the
    row to both consumers (the connector plugin and the bundle builder).
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
    """Account values override venue values, one key at a time (D-38).

    Asserted per key rather than all three at once: a merge that only carried the FIRST
    key it saw, or that replaced the whole overlay wholesale, would pass a
    single-combined-case test and silently drop two of the three in production.
    """
    manager, store, _ = _make_manager()
    try:
        for key, value in (
            ("sandbox", False),
            ("region", "eea"),
            ("market_type", "derivative"),
        ):
            record = manager.bring_online(_row({key: value}))
            assert getattr(record.spec, key) == value
            others = {"sandbox", "region", "market_type"} - {key}
            for other in others:
                assert getattr(record.spec, other) is None, (
                    f"{other} must stay at the venue default when only {key} is named")
    finally:
        store.dispose()


def test_several_keys_merge_together_and_leave_the_unnamed_one_defaulted() -> None:
    """Two named keys override; the third is untouched (D-38 precedence, one direction)."""
    manager, store, _ = _make_manager()
    try:
        record = manager.bring_online(
            _row({"region": "eea", "market_type": "derivative"}))

        assert record.spec.region == "eea"
        assert record.spec.market_type == "derivative"
        assert record.spec.sandbox is None
    finally:
        store.dispose()


@pytest.mark.parametrize("config", [{}, None])
def test_an_empty_and_a_null_config_are_indistinguishable_to_the_merge(
    config: Any,
) -> None:
    """``{}`` and ``NULL`` both leave every venue default in force, and neither raises.

    They arrive from different writers — ``provision`` normalizes to ``{}``, an
    out-of-band SQL insert leaves NULL — and an engine that treated one as "no config"
    and the other as an error would make a perfectly valid row un-bringable depending on
    who wrote it.
    """
    manager, store, _ = _make_manager()
    try:
        record = manager.bring_online(_row(config))

        assert record.spec.sandbox is None
        assert record.spec.region is None
        assert record.spec.market_type is None
    finally:
        store.dispose()


def test_an_unrecognised_config_key_raises_and_brings_nothing_online() -> None:
    """THE security control (T-11.2-06-01): a typo REFUSES, it is never dropped.

    ``sandox`` silently ignored leaves the account on whatever the ambient environment
    says — which for the ``sandbox`` knob means a live order reaching the PRODUCTION
    host on an account the operator believed was pinned to demo. The refusal must also
    be TOTAL: asserting only the raise would be a false-green if the exchange had
    already been registered, because the pair would then be routable with a spec built
    from a config the engine refused to understand.
    """
    manager, store, registry = _make_manager()
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
        assert registry == {}
    finally:
        store.dispose()


def test_an_unrecognised_key_raises_even_beside_valid_ones() -> None:
    """A good key does not buy a bad one a pass — validation precedes the merge."""
    manager, store, registry = _make_manager()
    try:
        with pytest.raises(UnknownVenueAccountConfigKeyError):
            manager.bring_online(_row({"sandbox": True, "market-type": "spot"}))
        assert registry == {}
    finally:
        store.dispose()


def test_the_allowlist_names_exactly_the_three_mergeable_keys() -> None:
    """The allowlist is EXPLICIT and EXHAUSTIVE (D-38).

    Pinned as a set rather than inferred from behaviour: a fourth key added without a
    consumer would be the inert-key defect T-11.2-06-02 names, and a key silently
    removed would start refusing rows that used to work.
    """
    from itrader.venues.venue_account_manager import _MERGEABLE_CONFIG_KEYS

    assert _MERGEABLE_CONFIG_KEYS == frozenset({"sandbox", "region", "market_type"})


def test_an_out_of_vocabulary_market_type_refuses() -> None:
    """A recognised KEY with an unrecognised VALUE is refused too (money-critical).

    ``market_type`` is the one allowlisted key whose bad value fails SILENTLY rather
    than loudly: ``VenueAccount`` derives ``_cash_stream_nets_holds = market_type
    != "spot"``, so ``"spott"`` would sail through as a derivative and change the
    account's CASH ACCOUNTING with nothing anywhere reporting a problem. ``region``
    needs no equivalent check here — ``OkxSettings.region`` is a ``Literal`` that fails
    loud at build — so the venue keeps ownership of its own vocabulary.
    """
    manager, store, registry = _make_manager()
    try:
        with pytest.raises(ValidationError) as excinfo:
            manager.bring_online(_row({"market_type": "spott"}))

        assert "spott" in str(excinfo.value)
        assert registry == {}
    finally:
        store.dispose()


def test_a_non_boolean_sandbox_refuses() -> None:
    """``sandbox`` must be a real bool — ``"false"`` is TRUTHY and would invert the host.

    A JSON column happily holds the STRING ``"false"``, and every truthiness test in
    Python then reads it as True. An account an operator pinned to production would
    quietly connect to the demo host, or the reverse.
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
    ambient ``OKX_API_*`` credentials — the fail-open composite ACCT-02/WR-05 closes.
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


# --------------------------------------------------------------------------- #
# D-40 — the per-pair venue-UID guard outcome surfaced on the manager
# --------------------------------------------------------------------------- #


def test_bring_online_surfaces_a_per_pair_guard_outcome() -> None:
    """D-40 — every online pair has a ``venue_uid_guard_active`` entry, not a bare bool.

    The whole of D-40: a bare boolean tells an operator the guard is off but not which
    of its holes they have. The surface must carry an OUTCOME OBJECT with a reason per
    ``(venue, account_id)``, so the status is diagnosable rather than merely on/off.
    """
    manager, store, _ = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1")
        manager.bring_online(row)

        active = manager.venue_uid_guard_active()
        outcome = active[(_VENUE, "acct-1")]

        assert not isinstance(outcome, bool)
        assert isinstance(outcome.reason, str) and outcome.reason
    finally:
        store.dispose()


def test_two_pairs_report_their_guard_outcomes_independently() -> None:
    """One pair's guard state never masks another's (D-40).

    The map is keyed per pair for exactly this reason: a single flag on the manager
    would collapse two accounts' guard states into one, so an inert guard on account A
    would hide an armed guard on account B (or vice versa).
    """
    manager, store, _ = _make_manager()
    try:
        for account in ("acct-1", "acct-2"):
            manager.bring_online(manager.provision(_VENUE, account))

        active = manager.venue_uid_guard_active()
        assert (_VENUE, "acct-1") in active
        assert (_VENUE, "acct-2") in active
        # Two independent outcome objects, not one shared reference.
        assert active[(_VENUE, "acct-1")] is not active[(_VENUE, "acct-2")]
    finally:
        store.dispose()


def test_the_guard_outcome_reflects_the_lifecycles_actual_state() -> None:
    """The surface reads the LIVE lifecycle outcome, not a value frozen at bring-up.

    D-15's condition is that the flag reflect the guard's ACTUAL outcome. Arming happens
    at connect (inside ``VenueLifecycle.start()``), not at ``bring_online`` — this
    manager's paper bundle carries no connector, so once its lifecycle starts the guard
    never runs and the outcome names THAT, rather than staying at a stale bring-up
    placeholder.
    """
    from itrader.venues.lifecycle import GUARD_REASON_PAPER_NO_CONNECTOR

    manager, store, _ = _make_manager()
    try:
        record = manager.bring_online(manager.provision(_VENUE, "acct-1"))
        # Before start(): a "not yet connected" placeholder, never armed.
        assert manager.venue_uid_guard_active()[(_VENUE, "acct-1")].armed is False

        record.lifecycle.start()

        outcome = manager.venue_uid_guard_active()[(_VENUE, "acct-1")]
        assert outcome.armed is False
        assert outcome.reason == GUARD_REASON_PAPER_NO_CONNECTOR
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# ACCT-03 — resolution, and the three distinguishable causes
# --------------------------------------------------------------------------- #


def test_account_for_an_absent_row_raises_not_provisioned() -> None:
    """ACCT-03 — no row at all. The operator must provision the account."""
    manager, store, _ = _make_manager()
    try:
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.account_for(_VENUE, "ghost", initial_cash=Decimal("1"),
                                enable_margin=False,
                                state_storage=in_memory_state_storage())
        assert excinfo.value.cause == VenueAccountNotProvisionedError.NOT_PROVISIONED
    finally:
        store.dispose()


def test_account_for_a_disabled_row_raises_with_a_distinguishable_cause() -> None:
    """ACCT-03 — the row EXISTS but is disabled; that is a different operator action.

    Collapsing this into "not provisioned" would send an operator to re-provision an
    account that already exists — which then refuses as a duplicate (D-11), leaving them
    with two contradictory errors and no true one.
    """
    manager, store, _ = _make_manager()
    try:
        store.upsert(_VENUE, "acct-1", secret_ref=None, venue_uid=None,
                     enabled=False, config={}, at=_AT)
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.account_for(_VENUE, "acct-1", initial_cash=Decimal("1"),
                                enable_margin=False,
                                state_storage=in_memory_state_storage())
        assert excinfo.value.cause == VenueAccountNotProvisionedError.DISABLED
    finally:
        store.dispose()


def test_account_for_a_provisioned_but_never_assembled_row_raises_not_online() -> None:
    """ACCT-03/D-21 — the distinction only the manager can make.

    An enabled row that this process never brought online is NOT "no such account": it was
    provisioned after its venue came up. Resolving it anyway would let the bundle memo
    build a bundle on the side — a second, unregistered assembly path beside the one
    ``bring_online`` owns.
    """
    manager, store, _ = _make_manager()
    try:
        manager.provision(_VENUE, "acct-1")
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            manager.account_for(_VENUE, "acct-1", initial_cash=Decimal("1"),
                                enable_margin=False,
                                state_storage=in_memory_state_storage())
        assert excinfo.value.cause == VenueAccountNotProvisionedError.NOT_ONLINE
    finally:
        store.dispose()


def test_account_id_matching_is_exact_string() -> None:
    """ACCT-03 encoding — no case-folding, no trimming, no normalization, anywhere.

    ``'ACCT-1'``, ``' acct-1'`` and ``'acct-1 '`` are three DIFFERENT accounts. A layer
    that trimmed or case-folded would resolve an operator's typo onto a real, funded
    account's authenticated session.
    """
    manager, store, _ = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1")
        manager.bring_online(row)

        for near_miss in ("ACCT-1", " acct-1", "acct-1 ", "Acct-1"):
            with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
                manager.account_for(_VENUE, near_miss, initial_cash=Decimal("1"),
                                    enable_margin=False,
                                    state_storage=in_memory_state_storage())
            assert excinfo.value.cause == (
                VenueAccountNotProvisionedError.NOT_PROVISIONED)
    finally:
        store.dispose()


def test_account_for_delegates_under_the_exact_pair() -> None:
    """D-21 — the manager AUTHORIZES, ``VenueBundles`` CONSTRUCTS, under the exact pair.

    Two independent signals: the recorded argument tuple, and the per-call identity
    sentinel the fake returns (a call counter alone is satisfied by a memo answering with
    another account's leaf).
    """
    bundles = _RecordingBundles(_real_bundles())
    manager, store, _ = _make_manager(bundles=bundles)
    try:
        row = manager.provision(_VENUE, "acct-1")
        manager.bring_online(row)

        seam = in_memory_state_storage()
        account = manager.account_for(
            _VENUE, "acct-1", initial_cash=Decimal("7"), enable_margin=True,
            state_storage=seam)

        venue, account_id, portfolio_args = bundles.calls[-1]
        assert (venue, account_id) == (_VENUE, "acct-1")
        assert portfolio_args["initial_cash"] == Decimal("7")
        assert portfolio_args["enable_margin"] is True
        assert portfolio_args["state_storage"] is seam
        assert account.account_id == "acct-1"
        assert account.seq == len(bundles.calls)
    finally:
        store.dispose()
