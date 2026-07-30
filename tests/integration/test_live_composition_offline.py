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

**The CR ledger.** Four probes, one per Critical from
``.planning/phases/11.2-account-provisioning-bootstrap-review-closures/11.2-REVIEW.md``.
Each began as an ``xfail(strict=True)`` against the defect and now asserts the invariant its
fix installed; each is written against the collaborator that owns that invariant rather than
against the facade, so the four flipped independently in their own stages.

Indentation: 4-space (matches ``tests/integration/*``); no ``__init__.py`` in this dir.
The ``integration`` marker is folder-derived.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.core.exceptions import VenueAccountNotProvisionedError
from itrader.portfolio_handler.account import SimulatedCashAccount
from itrader import config as _live_config
from itrader.trading_system.live.build import build_live_system
from itrader.trading_system.live.system import LiveTradingSystem
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
    """The system the REAL composition root returns, booted and torn down per test.

    Construction and BOOT are two steps now: bring-up connects each account's session and
    registers it only once that session is open, so it belongs to ``start()`` rather than
    to building the object. ``_bootstrap_session`` is the exact call ``start()`` makes, so
    this drives the production boot without also spawning the drain thread.
    """
    system = build_live_system(_live_config, execution_venue=_VENUE)
    try:
        system._bootstrap_session()
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
    assert live_system._data_provider is not None

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

    records = live_system._venue_manager.online_records()
    assert [(r.spec.venue_name, r.spec.account_id) for r in records] == [
        (_VENUE, _ACCOUNT)]
    assert records[0].adapter is exchanges[(_VENUE, _ACCOUNT)]


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
    """An account with no durable row is refused BY NAME, and no portfolio survives.

    The dangerous fallback is returning the compute leaf the portfolio would otherwise
    get: the pair would be silently unroutable while the portfolio looks healthy.

    The exception TYPE is load-bearing (WR-03). ``add_portfolio`` used to run the durable
    ``portfolios`` insert BEFORE the account was validated, so the composite foreign key
    onto ``venue_accounts`` rejected the write first and the caller saw a raw
    ``IntegrityError`` — an error that names a constraint instead of naming the account and
    telling the operator to provision it. Materializing ahead of the insert is what puts the
    domain's own refusal in front.
    """
    with pytest.raises(VenueAccountNotProvisionedError):
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
    system = build_live_system(_live_config, execution_venue=_VENUE)
    try:
        system._bootstrap_session()
        assert system._venue_manager.online_records() == []
        assert set(system.execution_handler.exchanges) == {(_VENUE, DEFAULT_ACCOUNT_ID)}
        assert system._system_db_backend is not None
    finally:
        system.stop()


def test_the_production_builder_produces_every_value_a_safety_path_consumes(
    live_system,
) -> None:
    """The design-§7.2 checklist: one assertion per value a safety path READS.

    The shared lesson of ``liquidation_fee_rate``, ``venue_accounts`` and CR-01..04 is that
    each of these defects was a collaborator whose LOGIC was right and whose INPUT the
    production builder never supplied. Unit tests could not see it, because they supplied
    the input themselves. So every value a safety path consumes gets one assertion that the
    REAL builder produced it.
    """
    # (1) Record enumerations — the recovery plane and the reconcile plane read the SAME
    #     live manager enumeration, not two containers that can drift.
    assert live_system._stream_recovery._accounts() == (
        live_system._venue_manager.online_records())
    coordinator = live_system._build_reconciliation_coordinator()
    assert coordinator._records() == live_system._online_account_records()
    assert coordinator._records.__func__ is (
        live_system._online_account_records.__func__)

    # (2) Halt wiring — the drift sweep freezes the engine through the SAME latch the
    #     operator surface and the error tripwire drive.
    assert live_system.portfolio_handler._halt_signal == live_system._safety.halt
    assert live_system._error_policy._halt == live_system._safety.halt

    # (3) Snapshot plumbing — the account brought online carries an adapter that answers
    #     the reconcile/resume snapshot, and it is the SAME object the order path routes to.
    record = live_system._venue_manager.online_records()[0]
    assert callable(record.adapter.snapshot)
    assert live_system.execution_handler.exchanges[
        (_VENUE, _ACCOUNT)] is record.adapter

    # (4) Subscribed symbols — the feed the data adapter was bound to at build is the ONE
    #     feed the engine drains bars from, so start()'s per-member subscribe reaches it.
    assert live_system.feed is live_system._engine.feed
    assert live_system.feed._provider is live_system._data_provider


# --------------------------------------------------------------------------- #
# CR ledger — one xfail(strict=True) probe per Critical, each on the
# collaborator that owns its invariant so the four flip independently.
# --------------------------------------------------------------------------- #
def test_cr01_the_facade_exposes_the_venue_account_manager_as_an_operator_surface(
    live_system,
) -> None:
    """The manager is reachable under the name the exception message already promises.

    CR-01 (fixed in Stage 6). The manager used to be a local variable in the builder that
    was never attached, so runtime provisioning had no reachable entry point — and
    ``VenueAccountNotProvisionedError``, which instructs the operator to run
    ``system.venue_accounts.provision(venue, account_id, ...)``, named an attribute that
    raised ``AttributeError``.
    """
    manager = live_system.venue_accounts
    assert callable(manager.provision)
    assert callable(manager.bring_online)
    assert callable(manager.set_enabled)


def test_cr01_every_facade_collaborator_is_a_required_constructor_parameter(
    live_system,
) -> None:
    """The STRUCTURAL half of CR-01: a collaborator the root forgets is a ``TypeError``.

    Reachability alone would be a one-attribute fix. What makes the defect class
    unrepeatable is that the facade declares no defaults at all: omitting ANY collaborator
    refuses construction here rather than reading ``None`` at the one call site that needed
    it, one deployment later.

    Driven with the REAL collaborators the production builder produced, so this cannot pass
    against a facade whose parameters merely happen to be spelled the same.
    """
    import inspect

    signature = inspect.signature(LiveTradingSystem.__init__)
    defaulted = [
        name for name, parameter in signature.parameters.items()
        if name != "self" and parameter.default is not inspect.Parameter.empty
    ]
    assert defaulted == [], (
        f"these facade collaborators carry a default, so the composition root can omit "
        f"one and get None instead of a TypeError: {defaulted}")

    complete = {
        name: getattr(live_system, _FACADE_FIELDS[name])
        for name in signature.parameters if name != "self"
    }
    # The same arguments build a second facade — proof the mapping below is the real one.
    LiveTradingSystem(**complete)
    for omitted in complete:
        with pytest.raises(TypeError):
            LiveTradingSystem(**{k: v for k, v in complete.items() if k != omitted})


#: Constructor parameter -> the facade attribute that holds it, so the probe above can
#: rebuild the exact argument set the production builder passed.
_FACADE_FIELDS = {
    "engine": "_engine",
    "config": "_config",
    "exchange": "exchange",
    "telemetry": "_telemetry",
    "safety": "_safety",
    "stream_recovery": "_stream_recovery",
    "throttle": "_throttle",
    "error_policy": "_error_policy",
    "live_runner": "_live_runner",
    "stop_event": "_stop_event",
    "boot": "_boot",
    "config_router": "_config_router",
    "venue_accounts": "_venue_manager",
    "connector_pool": "_connector_pool",
    "data_provider": "_data_provider",
    "data_connector": "_data_connector",
    "sql_engine": "_system_db_backend",
    "halt_record_store": "_halt_record_store",
    "system_store": "_system_store",
    "system_stats_store": "_system_stats_store",
}


def test_cr02_retiring_an_execution_account_leaves_the_feed_fully_wired(
    live_system,
) -> None:
    """The data adapter owns its own session, so retiring an account cannot disturb it.

    CR-02 (fixed in Stage 5) — and fixed by REMOVAL: the feed used to borrow whichever
    account's authenticated connection was available and re-borrow another when that
    account retired, and the re-borrowed provider was installed without its halt signal,
    without its stream-state listener and without being subscribed. There is now nothing to
    borrow: the data plane builds ONE adapter over the venue's PUBLIC session, armed by its
    own recipe at build.

    Driven through the REAL builder — the same system every other test in this file gets —
    because the defect was a composition decision. The retire is the production
    ``bring_offline``, and every assertion after it is about the object the production
    builder installed, not a stand-in.
    """
    provider = live_system._data_provider
    assert provider is not None, "the builder installed no data adapter"
    assert live_system.feed._provider is provider

    # The structural claim: the adapter's session is the DATA plane's own public session,
    # not one borrowed from an account. Public sessions are memoized per venue, so asking
    # the pool again is an identity check rather than a second build.
    assert live_system._data_connector is not None
    assert live_system._data_connector is live_system._connector_pool.public_session("okx")
    assert live_system._data_connector not in {
        record.connector
        for record in live_system._venue_manager.online_records()
    }

    # Retire the execution account the boot brought online — the exact scenario that used
    # to re-borrow the feed's connection.
    live_system._venue_manager.bring_offline(_VENUE, _ACCOUNT)
    assert live_system._venue_manager.online_records() == []

    # Nothing about the data arm moved: same adapter, same session, still armed.
    assert live_system._data_provider is provider
    assert live_system.feed._provider is provider
    assert provider._bar_sink == live_system.feed.update
    assert provider._global_queue is live_system.global_queue
    assert provider._halt_signal is not None, (
        "the data adapter has no halt signal — a connector-fatal on the candle stream "
        "cannot freeze the engine")
    assert (provider._on_stream_down is not None
            and provider._on_stream_up is not None), (
        "the data adapter has no stream-state listener — submission is never paused when "
        "the candle stream drops")


def test_cr03_recovery_account_enumeration_is_non_empty_when_an_account_is_online(
    live_system,
) -> None:
    """With an account online, the reconnect-resume path must have something to enumerate.

    CR-03 (fixed in Stage 3). The handler used to be constructed over a ``venue_accounts``
    dict that was declared and never written, so the resume snapshot loop iterated an empty
    list forever and the handler's own "never resume blind" contract was inert. Nothing
    reported it, because the handler's logic was correct — it was simply handed a container
    nothing populated.

    Read off the handler the REAL builder constructed, because the defect was entirely a
    builder decision. The assertion is on the ENUMERATION SOURCE rather than the
    streaming-filtered adapter list: this paper account legitimately carries no connector
    and so has no streams to recover, but the handler must still be wired to something that
    reports it as online. A container nothing writes fails this; a live read of the
    manager's records does not.
    """
    assert live_system.execution_handler.exchanges, "precondition: an account is online"
    records = list(live_system._stream_recovery._accounts())
    assert records, (
        "reconnect-resume would resume blind — the handler enumerates no online account")
    assert {(record.spec.venue_name, record.spec.account_id)
            for record in records} == {(_VENUE, _ACCOUNT)}


def test_cr04_a_failing_connect_during_bring_up_leaves_the_routing_map_empty() -> None:
    """A bring-up whose ``connect()`` fails must leave the account UNROUTABLE.

    CR-04 (fixed in Stage 4). Registration used to be the FIRST thing ``bring_online`` did,
    with the connect performed later by ``start()``, so an account was order-routable
    against a session that had not opened — and a connect that never succeeded left it
    routable forever. Registration is now the LAST statement of the bring-up.

    Probed on the manager rather than through a built system so it pins the ordering
    itself. The routing map here is the same ``(venue, account_id) -> adapter`` dict object
    ``ExecutionHandler.on_order`` reads, so a populated map after a failed bring-up means
    real orders route into a session that never opened.
    """
    import queue
    import random

    from itrader.config import ExchangeConfig
    from itrader.config.sql import SqlSettings
    from itrader.connectors.pool import ConnectorPool
    from itrader.storage import SqlEngine
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.trading_system.alert_sink import LogAlertSink
    from itrader.venues.accounts import VenueAccountManager
    from itrader.venues.catalog import CATALOG
    from itrader.venues.paper_plugin import paper_exchange_recipe

    build_paper = paper_exchange_recipe(ExchangeConfig.default())

    def _refusing_recipe(**kwargs: Any) -> Any:
        """The REAL paper recipe, with the built adapter's ``connect()`` made to fail."""
        adapter = build_paper(**kwargs)

        def _refuse() -> None:
            raise RuntimeError("venue session refused to open")

        adapter.connect = _refuse
        return adapter

    engine = SqlEngine(SqlSettings.default())
    store = VenueAccountStore(engine)
    provision_schema(engine)
    try:
        store.upsert(
            _VENUE, _ACCOUNT, secret_ref=None, venue_uid=None,
            enabled=True, config={}, at=_AT)

        ctx = SimpleNamespace(bus=queue.Queue(), rng=random.Random(42))
        routing_map: dict[tuple[str, str], Any] = {}
        manager = VenueAccountManager(
            store=store,
            pool=ConnectorPool(catalog=CATALOG, resolver=None, recipes={}),
            routing=routing_map,
            catalog=CATALOG,
            exchange_recipes={_VENUE: _refusing_recipe},
            ctx=ctx,
            alert_sink=LogAlertSink(),
            halt_signal=lambda reason: None,
            stream_state_listener=(lambda name: None, lambda name: None),
        )

        row = store.read_enabled_for(_VENUE)[0]
        with pytest.raises(RuntimeError):
            manager.bring_online(row)
        assert routing_map == {}, (
            "the account is order-routable against a session that never connected")
        assert manager.online_records() == []
    finally:
        store.dispose()
