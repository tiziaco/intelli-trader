"""The account-provisioning loop end to end on the SQL spine (11.2-05, D-27/D-29 slice).

ONE durable ``venue_accounts`` row travels through EVERY layer the account domain
touches — store → ``VenueAccountManager`` → ``assemble_venue`` → the exchange registry →
``VenueBundles`` → a constructed account leaf — in a single test. This is deliberately
NOT four per-layer unit tests: each layer already has those, and every one of them passed
while the layers disagreed about the account key. What no unit test can show is that the
key the registry is WRITTEN under is the key the order path READS, and that the row's own
``secret_ref`` survives the whole trip.

Proves, in one path:

  - **ACCT-01 store-derived, venue-scoped, ordered.** ``read_enabled_for`` returns this
    venue's enabled rows only, ``venue_name`` ASC / ``account_id`` ASC — never a
    spec-derived set and never another venue's accounts.
  - **The exact-pair registration (T-11.2-05-02).** ``bring_online`` registers the
    exchange under ``(venue_name, account_id)`` VERBATIM. Asserted by the exact tuple AND
    by the absence of the coerced ``(venue, 'default')`` key, because a registration under
    the coerced key type-checks, boots clean, and blackholes every order for the named
    account.
  - **The ``secret_ref`` handoff (T-11.2-05-01, ACCT-02/WR-05).** The ``VenueSpec`` built
    inside ``bring_online`` carries the row's OWN pointer. Two INDEPENDENT signals: the
    spec the manager recorded, and the spec the venue PLUGIN actually received (a counter
    or a single stored copy alone cannot tell "built it right" from "built it, then
    handed the plugin something else"). Without this, every named account silently
    reverts to the ambient ``OKX_API_*`` credentials — a fail-open no test would redden.
  - **ACCT-03 resolution.** ``account_for`` returns a constructed account leaf for the
    online pair and RAISES the typed refusal for an unknown one.
  - **The empty case (ACCT-01/D-09).** A venue with zero enabled rows yields ``[]`` and no
    error — a fresh deployment comes up empty rather than failing.

The **paper** arm is used on purpose. Its ``account_factory`` requires ``state_storage``
with no default (11.2-01/WR-08) while the OKX arm still defaults it, so a test written on
the OKX-shaped arm would go green against a call shape that raises ``TypeError`` in
production. Paper is also the arm whose bundle carries ``connector=None`` — the case the
legacy boot loop SKIPPED registering, which is precisely how a named paper account became
unroutable.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir.
Folder-derived ``integration`` marker.
"""

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
    VenueAccountNotProvisionedError,
)
from itrader.portfolio_handler.account import SimulatedCashAccount
from itrader.portfolio_handler.portfolio_factory import (
    ComputeAccountAuthority,
    PortfolioFactory,
    VenueValidatedComputeAuthority,
)
from itrader.storage import SqlEngine
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.venues.bundles import VenueBundles
from itrader.venues.paper_plugin import PaperVenuePlugin
from itrader.venues.registry import (
    COMPUTE_VENUE,
    DEFAULT_ACCOUNT_ID,
    ExecutionVenueRegistry,
)
from itrader.venues.venue_account_manager import VenueAccountManager
from tests.support.schema import provision_schema
from tests.support.venue_wiring import in_memory_state_storage

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = COMPUTE_VENUE
_ACCOUNT = "acct-1"
_SECRET_REF = "env:ACCT_1"


class _RecordingPaperPlugin(PaperVenuePlugin):
    """The REAL paper plugin, recording every spec ``build_bundle`` receives.

    A subclass rather than a fake so the bundle, the exchange and the
    ``state_storage``-requiring ``account_factory`` are all production objects — the
    recording is the only addition. It is the second, independent signal for the
    ``secret_ref`` handoff: it observes what actually crossed into the venue layer, not
    what the manager kept a copy of.
    """

    def __init__(self, exchange_config: Any) -> None:
        super().__init__(exchange_config)
        self.received_specs: list[Any] = []

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> Any:
        self.received_specs.append(spec)
        return super().build_bundle(ctx, spec, connectors)


@pytest.fixture()
def wiring():
    """The in-memory SQLite spine plus the paper venue wiring the manager needs.

    ``VenueAccountStore`` is constructed FIRST so its ``build_venue_accounts_table``
    registrar puts the table on the shared MetaData before ``provision_schema`` creates
    it — the stores are schema-pure (WR-03/D-14) and nothing self-creates at runtime.

    D-43: ``exchange_registry`` is the bare ``(venue, account_id) -> exchange`` dict —
    the composition-root-owned map — that ``bring_online`` writes. It is the entire
    surface the manager touches, and booting a real handler here would pre-register
    ``(paper, default)`` and blunt the exact-pair assertion below.
    """
    engine = SqlEngine(SqlSettings.default())
    store = VenueAccountStore(engine)
    provision_schema(engine)

    bus: Any = queue.Queue()
    plugin = _RecordingPaperPlugin(ExchangeConfig.default())
    registry = ExecutionVenueRegistry()
    registry.register(_VENUE, plugin)
    connectors = ConnectorProvider({})
    ctx = SimpleNamespace(bus=bus, rng=random.Random(42))
    bundles = VenueBundles(registry, connectors, ctx)

    exchange_registry: dict[tuple[str, str], Any] = {}
    # The paper accounts here carry connector=None (no streaming connection), so the D-36
    # feed binder never has a connection to borrow; a no-op binder satisfies the manager's
    # required-collaborator contract. Feed binding is covered in test_feed_binder.py.
    manager = VenueAccountManager(
        store, bundles, connectors, exchange_registry,
        alert_sink=LogAlertSink(),
        feed_binder=SimpleNamespace(feed_provider=None, rebind=lambda available: None),
    )
    try:
        yield SimpleNamespace(
            store=store, manager=manager, plugin=plugin,
            exchange_registry=exchange_registry, bundles=bundles,
        )
    finally:
        store.dispose()


def _provision_row(store: VenueAccountStore, account_id: str = _ACCOUNT,
                   *, secret_ref: str | None = _SECRET_REF,
                   venue_name: str = _VENUE, enabled: bool = True) -> None:
    """Write one durable account row directly through the store.

    Task 1 exercises the row → runtime half of the loop; the ``provision`` verb that
    authors the row is Task 2's, and using the store here keeps this test independent of
    it.
    """
    store.upsert(
        venue_name, account_id, secret_ref=secret_ref, venue_uid=None,
        enabled=enabled, config={}, at=_AT,
    )


def test_provisioned_row_becomes_a_routable_account_and_resolves_to_a_leaf(wiring):
    """One row → bring_online → registered exchange → account_for → a built leaf (D-27).

    The tracer. Every assertion below is a link in ONE chain; a break anywhere means the
    account exists durably but is unreachable at runtime, which is the failure this whole
    plan exists to make impossible.
    """
    _provision_row(wiring.store)

    # ACCT-01 — the account SET is read off durable rows, venue-scoped and ordered.
    rows = wiring.manager.read_enabled_for(_VENUE)
    assert [row["account_id"] for row in rows] == [_ACCOUNT]
    assert rows[0]["secret_ref"] == _SECRET_REF

    record = wiring.manager.bring_online(rows[0])

    # T-11.2-05-02 — registered under the EXACT pair, with no coercion. The negative half
    # matters as much as the positive: registering under (venue, 'default') would look
    # fine and route every order for 'acct-1' into a lookup miss.
    assert (_VENUE, _ACCOUNT) in wiring.exchange_registry
    assert (_VENUE, DEFAULT_ACCOUNT_ID) not in wiring.exchange_registry
    assert wiring.exchange_registry[(_VENUE, _ACCOUNT)] is record.bundle.exchange

    # T-11.2-05-01 — the row's OWN credential pointer reached the spec, and the spec the
    # PLUGIN saw is the same one (two independent signals).
    assert record.spec.secret_ref == _SECRET_REF
    assert record.spec.account_id == _ACCOUNT
    assert [spec.secret_ref for spec in wiring.plugin.received_specs] == [_SECRET_REF]

    # ACCT-03 — the pair resolves to a CONSTRUCTED account leaf.
    account = wiring.manager.account_for(
        _VENUE, _ACCOUNT,
        initial_cash=Decimal("10000"),
        enable_margin=False,
        state_storage=in_memory_state_storage(),
    )
    assert account is not None
    assert account.balance == Decimal("10000")


def test_account_for_an_unprovisioned_pair_raises_and_never_returns_a_leaf(wiring):
    """ACCT-03 empty case: no row → the typed refusal, never a compute leaf.

    Returning the compute leaf a portfolio would otherwise get is the tempting fallback
    and the dangerous one: ``is_venue_truth=False`` silently disables the venue snapshot,
    the streams, ``VenueReconciler`` and the unexplained-residual HALT.
    """
    with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
        wiring.manager.account_for(
            _VENUE, "no-such-account",
            initial_cash=Decimal("10000"),
            enable_margin=False,
            state_storage=in_memory_state_storage(),
        )
    assert excinfo.value.cause == VenueAccountNotProvisionedError.NOT_PROVISIONED
    assert excinfo.value.account_id == "no-such-account"
    assert (_VENUE, "no-such-account") not in wiring.exchange_registry


def test_zero_enabled_rows_yields_an_empty_account_set_and_no_error(wiring):
    """ACCT-01/D-09 empty case: a fresh deployment comes up empty, not broken."""
    assert wiring.manager.read_enabled_for(_VENUE) == []


def test_fresh_deployment_provisioning_gate_walks_the_whole_loop(wiring):
    """D-29's fresh-deployment gate: the WHOLE loop in ONE test, on a zero-account spine.

    ACCT-01/ACCT-02/ACCT-03; D-09/D-11/D-27/D-29. Six steps, in the EXACT order a fresh
    deployment performs them, on ONE in-memory SQLite spine and ONE
    ``VenueAccountManager`` instance — NO process restart anywhere between them. This is
    the gate that proves deleting boot-time minting left a WORKING replacement: each step
    below pins the precise failure the deletion would otherwise reintroduce, and the
    account key WRITTEN by provisioning is the key the portfolio path READS.

    The "add_portfolio" seam here is the LIVE portfolio-creation path verbatim: a
    ``PortfolioFactory`` over a ``VenueValidatedComputeAuthority`` wrapping the REAL
    ``VenueAccountManager`` (portfolio_factory.py — the arm the live composition root
    injects). It GATES on ACCT-03 through ``manager.assert_available`` and, on success,
    builds a COMPUTE leaf carrying the real pair.

    Step 5 asserts a COMPUTE leaf carrying the REAL ``(venue, account_id)`` pair, NOT a
    venue-truth leaf and NOT ``is_venue_truth is True``: the ``VenueAccount`` swap is
    COMP-07 / Phase 12 (owner decision, wave 5, 2026-07-24) — a venue-truth balance is
    unreadable at ``Portfolio.__init__`` (T-05-07). A test asserting ``is_venue_truth``
    here would pin a defect this phase deliberately does NOT ship.
    """
    authority = VenueValidatedComputeAuthority(
        manager=wiring.manager,
        compute=ComputeAccountAuthority(
            venue_bundles=wiring.bundles, compute_venue=_VENUE),
    )
    factory = PortfolioFactory(authority=authority, environment="backtest")

    def _add_portfolio() -> Any:
        # The same manager instance and the same process perform steps 2–5 — the whole
        # point of D-27's single-path provisioning is that no restart sits in the middle.
        return factory.materialize(
            name="pf", exchange=_VENUE, cash=Decimal("10000"),
            account_id=_ACCOUNT, venue_name=_VENUE)

    # (1) A zero-account boot comes up RUNNING and empty (ACCT-01/D-09): the store read
    # yields ``[]`` with no error, and nothing is online yet.
    assert wiring.manager.read_enabled_for(_VENUE) == []
    assert wiring.exchange_registry == {}

    # (2) add_portfolio BEFORE provisioning refuses with the TYPED account-domain error —
    # not a bare KeyError/AttributeError, and never a silently-created compute leaf
    # (ACCT-03). A generic ``Exception`` assertion would pass on the very defect this pins,
    # so the concrete type and cause are asserted.
    with pytest.raises(VenueAccountNotProvisionedError) as before:
        _add_portfolio()
    assert before.value.cause == VenueAccountNotProvisionedError.NOT_PROVISIONED
    assert before.value.account_id == _ACCOUNT

    # (3) ``provision`` (the create-only verb, NOT a raw store write) writes EXACTLY ONE
    # durable row (ACCT-02/D-11).
    row = wiring.manager.provision(_VENUE, _ACCOUNT, secret_ref=_SECRET_REF)
    assert len(wiring.store.read_all()) == 1
    # ACCT-03 exact-string encoding: the id is stored VERBATIM — no case-fold, trim or
    # normalization — and reads back byte for byte.
    assert row["account_id"] == _ACCOUNT

    # (4) ``bring_online`` makes it usable in THIS process with no restart (D-27): the SAME
    # manager instance registers the exchange under the EXACT pair, never a coerced
    # ``(venue, 'default')`` — the coerced key type-checks, boots clean and blackholes
    # every order for the named account.
    wiring.manager.bring_online(row)
    assert (_VENUE, _ACCOUNT) in wiring.exchange_registry
    assert (_VENUE, DEFAULT_ACCOUNT_ID) not in wiring.exchange_registry

    # (5) The NEXT add_portfolio SUCCEEDS — on a COMPUTE leaf carrying the real pair
    # (D-23). The venue-truth swap is COMP-07/Phase 12, so this asserts the compute-leaf
    # KIND and the real ``(venue, account_id)`` identity, NOT ``is_venue_truth``. The id
    # read back off the leaf equals the id provisioned at step 3, byte for byte.
    portfolio = _add_portfolio()
    assert portfolio.account_id == _ACCOUNT
    assert portfolio.venue_name == _VENUE
    assert isinstance(portfolio.account, SimulatedCashAccount)
    assert portfolio.account.balance == Decimal("10000.00")

    # (6) A SECOND provision of the same pair refuses with the TYPED duplicate error and
    # leaves the first row INTACT (ACCT-02/D-11): create-only, never a silent overwrite
    # that would clear the engine-written ``venue_uid`` and disarm the identity guard.
    with pytest.raises(DuplicateVenueAccountProvisionError) as dup:
        wiring.manager.provision(_VENUE, _ACCOUNT, secret_ref="env:OTHER")
    assert dup.value.account_id == _ACCOUNT
    assert len(wiring.store.read_all()) == 1
