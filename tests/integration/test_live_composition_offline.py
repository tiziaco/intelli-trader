"""The assembled live system, built offline — the gate the four Criticals slipped through.

The 11.2 review's root-cause finding was not four separate wiring mistakes; it was that
**the assembled system is never built in a test**. Every 11.2 unit and integration test
constructs the collaborators directly, so all of them stayed green while the object graph
the composition root actually produces was mis-wired. This file closes that gap: it drives
the REAL live composition root end to end with no credentials, no network and no Postgres,
and asserts the shape of what comes back.

**How it stays offline.** ``build_live_system`` selects its storage arm by env-presence of
a Postgres credential on the unified ``ITRADER_DATABASE_*`` surface, and
``SqlSettings.engine_url()`` returns a verbatim ``url`` with its own scheme authoritative.
Pointing ``ITRADER_DATABASE_URL`` at a file-backed SQLite database therefore drives the
FULL durable arm — durable stores, config layering, strategy rehydrate, the store-derived
venue bring-up loop — with no container and no socket. The venue is ``paper``, whose bundle
carries ``connector=None``, so no connector authenticates and no ccxt client is built.

**What is asserted here versus elsewhere.** The account-derivation logic (ordering,
venue-scoping, the exact-pair key, per-account ``secret_ref``) is unit-tested on the
manager without a boot. This file's unique job is proving production goes THROUGH those
collaborators and hands the operator a reachable, fully-wired system.

**The CR ledger.** Four probes carry ``xfail(strict=True)``, one per Critical from
``.planning/phases/11.2-account-provisioning-bootstrap-review-closures/11.2-REVIEW.md``.
``strict=True`` means a probe that starts passing FAILS the suite loudly, so the stage that
lands each fix must remove its mark in the same commit — the ledger cannot silently drift
out of date. Each probe is written against the collaborator that owns its invariant rather
than against the facade, so the four flip independently in their own stages.

Indentation: 4-space (matches ``tests/integration/*``); no ``__init__.py`` in this dir.
The ``integration`` marker is folder-derived.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.portfolio_handler.account import SimulatedCashAccount
from itrader.trading_system.live_trading_system import LiveTradingSystem
from itrader.venues.registry import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = COMPUTE_VENUE
_ACCOUNT = "acct-1"


@pytest.fixture
def sqlite_spine(tmp_path, monkeypatch):
    """A file-backed SQLite database standing in for the live Postgres spine.

    File-backed rather than ``:memory:`` on purpose: this fixture and
    ``build_live_system`` each construct their OWN ``SqlEngine``, and only a real file is
    the same database across both. Every durable store a live boot reads is instantiated
    here so its table registrar runs before ``provision_schema`` — an absent table errors
    the boot rather than degrading it.
    """
    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage import SqlEngine
    from itrader.storage.halt_record_store import HaltRecordStore
    from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
    from itrader.storage.strategy_registry_store import StrategyRegistryStore
    from itrader.storage.system_stats_store import SystemStatsStore
    from itrader.storage.system_store import SystemStore
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.storage.venue_store import VenueStore

    monkeypatch.setenv(
        "ITRADER_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'live.db'}")

    engine = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
    PortfolioDefinitionStore(engine)
    account_store = VenueAccountStore(engine)
    HaltRecordStore(engine)
    SystemStore(engine)
    SystemStatsStore(engine)
    StrategyRegistryStore(engine)
    VenueStore(engine)
    provision_schema(engine)
    try:
        yield SimpleNamespace(engine=engine, account_store=account_store)
    finally:
        engine.dispose()


@pytest.fixture
def provisioned_paper(sqlite_spine):
    """The spine carrying ONE enabled ``('paper', 'acct-1')`` row for the boot to find.

    ``secret_ref=None`` is the supported paper shape — "this account has no per-account
    credentials" — not the credential fail-open the OKX arm guards against.
    """
    sqlite_spine.account_store.upsert(
        _VENUE, _ACCOUNT, secret_ref=None, venue_uid=None,
        enabled=True, config={}, at=_AT)
    return sqlite_spine


@pytest.fixture
def live_system(provisioned_paper):
    """The system the REAL composition root returns, built and torn down per test."""
    system = LiveTradingSystem.for_exchange(_VENUE)
    try:
        yield system
    finally:
        system.stop()


# --------------------------------------------------------------------------- #
# The built system's shape — what the operator actually receives
# --------------------------------------------------------------------------- #
def test_the_builder_selects_the_durable_arm_and_wires_every_safety_collaborator(
    live_system,
) -> None:
    """A SQL spine present ⇒ the durable arm, with the whole safety plane attached.

    Each of these is a collaborator the builder assigns onto the facade AFTER
    construction. That pattern is exactly what let CR-01 happen — an object built as a
    local variable and simply never assigned reads identically at the call site — so the
    presence of every one of them is asserted, not assumed.
    """
    assert live_system._system_db_backend is not None
    assert live_system._halt_record_store is not None
    assert live_system._system_store is not None
    assert live_system._system_stats_store is not None
    assert live_system._config_router is not None
    assert live_system._feed_binder is not None

    assert live_system._safety is not None
    assert live_system._stream_recovery is not None
    assert live_system._throttle is not None
    assert live_system._live_runner is not None
    assert live_system._error_policy is not None


def test_a_provisioned_row_becomes_a_routable_exchange_through_the_real_boot(
    live_system,
) -> None:
    """One durable row ⇒ one exchange registered under the EXACT pair the order path reads.

    The identity half carries the weight. ``compose_engine`` registers the compute venue's
    own baseline exchange under ``(paper, 'default')`` on every arm, so the presence of
    that key proves nothing either way — but the named account being ALIASED onto it would
    mean orders for ``acct-1`` execute against the default account's exchange. The two
    entries must therefore be distinct objects, and the named one must be the exchange the
    account's own lifecycle assembled.
    """
    exchanges = live_system.execution_handler.exchanges
    assert (_VENUE, _ACCOUNT) in exchanges
    assert exchanges[(_VENUE, _ACCOUNT)] is not exchanges[(_VENUE, DEFAULT_ACCOUNT_ID)]

    assert set(live_system._venue_lifecycles) == {_ACCOUNT}
    lifecycle = live_system._venue_lifecycles[_ACCOUNT]
    assert lifecycle.bundle.exchange is exchanges[(_VENUE, _ACCOUNT)]


def test_a_portfolio_materializes_over_the_provisioned_account(live_system) -> None:
    """The portfolio path resolves the account the boot brought online.

    Runs through ``add_portfolio`` on the built handler — i.e. through whichever account
    authority the REAL builder injected — so a builder that wired the never-refusing
    fallback authority instead of the validating one would show up here.
    """
    portfolio_id = live_system.portfolio_handler.add_portfolio(
        name="pf", exchange=_VENUE, cash=Decimal("10000"),
        account_id=_ACCOUNT, venue_name=_VENUE)

    portfolio = live_system.portfolio_handler.get_portfolio(portfolio_id)
    assert portfolio.account_id == _ACCOUNT
    assert portfolio.venue_name == _VENUE
    assert isinstance(portfolio.account, SimulatedCashAccount)
    assert portfolio.account.balance == Decimal("10000.00")


def test_a_portfolio_naming_an_unprovisioned_account_is_refused(live_system) -> None:
    """An account with no durable row is refused, and no portfolio survives the attempt.

    The dangerous fallback is returning the compute leaf the portfolio would otherwise
    get: the pair would be silently unroutable while the portfolio looks healthy.

    The exception TYPE is deliberately left open here. On a real SQL spine the durable
    ``portfolios`` insert runs BEFORE the account authority validates, so the composite
    foreign key onto ``venue_accounts`` rejects the write first and the caller sees an
    ``IntegrityError`` rather than the domain's own ``VenueAccountNotProvisionedError``.
    That ordering is the open WR-03 finding, closed when ``add_portfolio`` validates and
    materializes ahead of the insert; this assertion tightens to the typed error then.
    """
    with pytest.raises(Exception):
        live_system.portfolio_handler.add_portfolio(
            name="ghost-pf", exchange=_VENUE, cash=Decimal("10000"),
            account_id="no-such-account", venue_name=_VENUE)

    # Whichever guard fired, the refusal must be total: no portfolio object and no
    # durable row for the unprovisioned pair.
    portfolios = live_system.portfolio_handler.get_active_portfolios()
    assert all(portfolio.account_id != "no-such-account" for portfolio in portfolios)
    persisted = live_system.portfolio_handler.definition_store.read_all()
    assert all(row["account_id"] != "no-such-account" for row in persisted)


def test_a_zero_account_spine_still_boots_running_and_empty(sqlite_spine) -> None:
    """A fresh deployment with no provisioned account comes up empty rather than broken.

    "Empty" means zero brought-online accounts. The compute venue's own baseline exchange
    under ``(paper, 'default')`` is registered by ``compose_engine`` regardless, so the
    account-derived registrations are what must be absent.
    """
    system = LiveTradingSystem.for_exchange(_VENUE)
    try:
        assert system._venue_lifecycles == {}
        assert set(system.execution_handler.exchanges) == {(_VENUE, DEFAULT_ACCOUNT_ID)}
        assert system._system_db_backend is not None
    finally:
        system.stop()


# --------------------------------------------------------------------------- #
# CR ledger — one xfail(strict=True) probe per Critical, each on the
# collaborator that owns its invariant so the four flip independently.
# --------------------------------------------------------------------------- #
@pytest.mark.xfail(
    strict=True,
    reason="CR-01: the venue-account manager is a local variable in build_live_system and "
           "is never attached to the facade, so runtime provisioning has no reachable "
           "entry point — and the typed refusal tells operators to call an attribute that "
           "does not exist. Flips in Stage 6 (required-arg facade).",
)
def test_cr01_the_facade_exposes_the_venue_account_manager_as_an_operator_surface(
    live_system,
) -> None:
    """The manager is reachable under the name the exception message already promises.

    ``VenueAccountNotProvisionedError`` instructs the operator to run
    ``system.venue_accounts.provision(venue, account_id, ...)``. Until that attribute
    exists, the one remediation string an operator will follow raises ``AttributeError``.
    """
    manager = live_system.venue_accounts
    assert callable(manager.provision)
    assert callable(manager.bring_online)
    assert callable(manager.set_enabled)


@pytest.mark.xfail(
    strict=True,
    reason="CR-02: a feed re-borrow installs a provider that is never halt-wired, never "
           "stream-state-wired and never subscribed, and abandons the previous one without "
           "stopping it. Flips in Stage 5, where the probe is rewritten to the "
           "adapter-owned-session invariant and the borrow scenario ceases to exist.",
)
def test_cr02_retiring_an_execution_account_leaves_the_feed_fully_wired() -> None:
    """Re-pointing the feed's data connection must leave the data arm armed, not silent.

    Probed on ``FeedConnectionBinder`` — the object that owns the re-borrow today — rather
    than through a built system, because reaching a re-borrow through the builder needs two
    streaming accounts and therefore credentials. The invariant is the same one the design
    makes structural: after the account whose connection the feed borrowed is retired, the
    feed's provider is halt-wired and the abandoned provider is stopped.
    """
    from itrader.venues.feed_binder import FeedConnectionBinder

    class _Provider:
        def __init__(self) -> None:
            self.halt_signal: Any = None
            self.stream_listeners: Any = None
            self.stopped = False

        def set_bar_sink(self, sink: Any) -> None:
            self.bar_sink = sink

        def set_global_queue(self, queue: Any) -> None:
            self.queue = queue

        def set_halt_signal(self, halt: Any) -> None:
            self.halt_signal = halt

        def set_stream_state_listener(self, on_down: Any, on_up: Any) -> None:
            self.stream_listeners = (on_down, on_up)

        def stop(self) -> None:
            self.stopped = True

    built: list[_Provider] = []

    class _DataPlugin:
        def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> _Provider:
            provider = _Provider()
            built.append(provider)
            return provider

    class _Registry:
        def get(self, name: str) -> _DataPlugin:
            return _DataPlugin()

    feed = SimpleNamespace(
        provider=None,
        set_provider=lambda provider: None,
        update=lambda bar: None,
    )
    binder = FeedConnectionBinder(
        feed=feed, data_registry=_Registry(), ctx=object(),
        connectors=object(), global_queue=object(),
    )

    def _candidate(account_id: str) -> tuple[str, str, Any]:
        return ("okx", account_id, SimpleNamespace(data_provider="okx"))

    # Bind to account A, then retire it so the feed must re-borrow off account B.
    binder.rebind([_candidate("acct-a"), _candidate("acct-b")])
    binder.rebind([_candidate("acct-b")])

    assert len(built) == 2, "retiring the bound account must build a replacement provider"
    previous, current = built
    assert current.halt_signal is not None, (
        "the re-borrowed provider has no halt signal — a connector-fatal on the candle "
        "stream cannot freeze the engine")
    assert current.stream_listeners is not None, (
        "the re-borrowed provider has no stream-state listener — submission is never "
        "paused when the candle stream drops")
    assert previous.stopped, (
        "the abandoned provider still holds a live stream pushing into the one feed ring")


@pytest.mark.xfail(
    strict=True,
    reason="CR-03: StreamRecoveryHandler is constructed over a `venue_accounts` dict that "
           "is declared and never written, so reconnect-resume iterates an empty list "
           "forever and its own 'never resume blind' contract is inert. Flips in Stage 3 "
           "(recovery enumerates the manager's online records).",
)
def test_cr03_recovery_account_enumeration_is_non_empty_when_an_account_is_online(
    live_system,
) -> None:
    """With an account online, the reconnect-resume path must have something to snapshot.

    Read off the handler the real builder constructed, because the defect is entirely a
    builder decision: the handler's own logic is correct, it is simply handed a container
    nothing populates.
    """
    assert live_system.execution_handler.exchanges, "precondition: an account is online"
    assert list(live_system._stream_recovery._venue_accounts()), (
        "reconnect-resume would resume blind — no account is enumerated to snapshot")


@pytest.mark.xfail(
    strict=True,
    reason="CR-04: bring_online writes the order-routing map before anything connects the "
           "session, so an account is routable against an unconnected venue. Flips in "
           "Stage 4 (registration becomes the last statement of bring_online).",
)
def test_cr04_a_failing_connect_during_bring_up_leaves_the_routing_map_empty() -> None:
    """A bring-up whose ``connect()`` fails must leave the account UNROUTABLE.

    Probed on the manager rather than a built system so it flips with the bring-up
    inversion itself. The routing map here is the same ``(venue, account_id) -> exchange``
    dict object ``ExecutionHandler.on_order`` reads, so a populated map after a failed
    bring-up means real orders route into a session that never opened.
    """
    import queue
    import random

    from itrader.config import ExchangeConfig
    from itrader.config.sql import SqlSettings
    from itrader.connectors.provider import ConnectorProvider
    from itrader.storage import SqlEngine
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.trading_system.alert_sink import LogAlertSink
    from itrader.venues.bundles import VenueBundles
    from itrader.venues.paper_plugin import PaperVenuePlugin
    from itrader.venues.registry import ExecutionVenueRegistry
    from itrader.venues.venue_account_manager import VenueAccountManager

    class _RefusingConnectPlugin(PaperVenuePlugin):
        """The real paper plugin, with the built exchange's ``connect()`` made to fail."""

        def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> Any:
            bundle = super().build_bundle(ctx, spec, connectors)

            def _refuse() -> None:
                raise RuntimeError("venue session refused to open")

            bundle.exchange.connect = _refuse
            return bundle

    engine = SqlEngine(SqlSettings.default())
    store = VenueAccountStore(engine)
    provision_schema(engine)
    try:
        store.upsert(
            _VENUE, _ACCOUNT, secret_ref=None, venue_uid=None,
            enabled=True, config={}, at=_AT)

        registry = ExecutionVenueRegistry()
        registry.register(_VENUE, _RefusingConnectPlugin(ExchangeConfig.default()))
        connectors = ConnectorProvider({})
        ctx = SimpleNamespace(bus=queue.Queue(), rng=random.Random(42))

        routing_map: dict[tuple[str, str], Any] = {}
        manager = VenueAccountManager(
            store, VenueBundles(registry, connectors, ctx), connectors, routing_map,
            alert_sink=LogAlertSink(),
            feed_binder=SimpleNamespace(
                feed_provider=None, rebind=lambda available: None),
        )

        row = store.read_enabled_for(_VENUE)[0]
        with pytest.raises(RuntimeError):
            manager.bring_online(row)
        assert routing_map == {}, (
            "the account is order-routable against a session that never connected")
    finally:
        store.dispose()
