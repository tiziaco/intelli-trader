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
from itrader.core.exceptions import (
    DuplicateVenueAccountProvisionError,
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
) -> tuple[VenueAccountManager, VenueAccountStore, Any]:
    """A manager over a REAL in-memory store, optionally with its schema NOT provisioned.

    ``provision=False`` reproduces the fresh-deployment state D-34 degrades on: the store
    registers its table on the shared MetaData but nothing creates it (the stores are
    schema-pure — WR-03/D-14).
    """
    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    if provision:
        provision_schema(store.backend)
    execution_handler = SimpleNamespace(exchanges={})
    manager = VenueAccountManager(
        store,
        bundles if bundles is not None else _real_bundles(),
        ConnectorProvider({}),
        execution_handler,
        alert_sink=LogAlertSink(),
    )
    return manager, store, execution_handler


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
    manager, store, execution_handler = _make_manager()
    try:
        manager.provision(_VENUE, "acct-1")
        assert manager.is_online(_VENUE, "acct-1") is False
        assert execution_handler.exchanges == {}
    finally:
        store.dispose()


def test_provision_then_bring_online_makes_the_account_usable_in_this_process() -> None:
    """D-27 — provisioned at runtime, usable with NO restart, through the ONE path."""
    manager, store, execution_handler = _make_manager()
    try:
        row = manager.provision(_VENUE, "acct-1", secret_ref="env:ACCT_1")
        record = manager.bring_online(row)

        assert manager.is_online(_VENUE, "acct-1") is True
        assert execution_handler.exchanges[(_VENUE, "acct-1")] is record.bundle.exchange
        assert record.spec.secret_ref == "env:ACCT_1"

        account = manager.account_for(
            _VENUE, "acct-1", initial_cash=Decimal("500"),
            enable_margin=False, state_storage=in_memory_state_storage())
        assert account.balance == Decimal("500")
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
