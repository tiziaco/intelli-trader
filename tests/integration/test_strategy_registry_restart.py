"""STRAT-01 — the strategy roster survives a restart (D-01 rehydrate at the composition root).

This is the phase's payoff test: everything upstream (the D-06 schema, the D-01 catalog, the
D-04 codec) exists so that ``build_live_system`` can turn stored rows back into live strategy
instances. The assertions here are deliberately made against a REAL Postgres spine through
the REAL factory, because the seam under test IS the wiring.

Placement is the load-bearing property (RESEARCH Item 2): rehydrate runs at CONSTRUCTION
time, inside the ``system_store is not None`` gate, immediately after
``_layer_persisted_overrides``. Test 5 pins the consequence — the strategies are registered
BEFORE ``start()``, so ``wire_universe`` (``StrategyDerivedSelectionModel`` derives
membership FROM the strategies) and ``register_strategy_warmup`` (the feed ring is sized
FROM them) both see the full roster.

Per RESEARCH: these tests seed ROWS and never also hand-add the same instance — doing both
would trip the D-02 duplicate-name reject.

The PG arm uses the shared session testcontainers Postgres via ``pg_database_env`` and SKIPS
Dockerless (D-11). Rows are cleaned up per-test: the container is session-scoped, so a leaked
row would bleed into a sibling test.

4-space indentation (matches ``tests/integration/*``). NO ``__init__.py`` in this dir.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from uuid_utils.compat import uuid7

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.core.ids import PortfolioId
from itrader.core.sizing import FractionOfCash
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.live_trading_system import build_live_system
from itrader.trading_system.venue_spec import build_venue_spec
from tests.support.replay_harness import TestDataPlugin
from tests.support.schema import provision_schema, seed_portfolio_definitions
from tests.support.strategy_catalog import seeded_registry_rows, test_catalog

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

# Portfolio handles are ALWAYS UUIDv7-backed ``PortfolioId`` values (FL-02).
_PID = PortfolioId(uuid7())


def _seed_store() -> StrategyRegistryStore:
    """A store over the SAME database ``build_live_system`` will build its own engine on.

    The factory owns its engine, so seeding goes through a separate handle pointed at the
    same ``ITRADER_DATABASE_URL``. ``provision_schema`` is the test-side D-14 seam (the
    stores are schema-pure — production schema is Alembic-owned).
    """
    store = StrategyRegistryStore(SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2)))
    provision_schema(store.backend)
    return store


def _seed(store: StrategyRegistryStore, strategies: Any) -> None:
    registry_rows, subscription_rows = seeded_registry_rows(strategies)
    for row in registry_rows:
        store.upsert(
            row["strategy_name"], row["strategy_type"], row["config_json"], row["enabled"], _AT
        )
    # B2 (11-03): the subscription child FKs onto ``portfolios`` with ON DELETE CASCADE, so
    # every id being subscribed needs a real definition row first.
    seed_portfolio_definitions(
        store.backend, [row["portfolio_id"] for row in subscription_rows]
    )
    for row in subscription_rows:
        store.add_portfolio_subscription(row["strategy_name"], row["portfolio_id"])


def _sma(name: str, **kwargs: Any) -> SMAMACDStrategy:
    strategy = SMAMACDStrategy(timeframe="1d", tickers=["BTCUSD"], **kwargs)
    strategy.name = name
    return strategy


def _build(**kwargs: Any) -> Any:
    """Build a paper live system through the REAL factory with the replay data plugin.

    Mirrors ``build_paper_replay_system`` but calls ``build_live_system`` directly so the
    new ``strategy_catalog`` injection seam is exercised as production would reach it.
    """
    plugin = TestDataPlugin()
    spec = build_venue_spec("paper", data_provider="replay")
    return build_live_system(spec, data_plugins={"replay": plugin}, **kwargs)


# --------------------------------------------------------------------------------------
# Offline — no SQL spine (the gate is closed)
# --------------------------------------------------------------------------------------


def test_no_sql_spine_builds_fine_and_never_rehydrates(monkeypatch) -> None:
    """With no durable spine the gate degrades to a clean no-op — rehydrate never runs."""
    for var in ("ITRADER_DATABASE_PASSWORD", "ITRADER_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)

    system = _build(strategy_catalog=test_catalog())
    try:
        assert system._system_db_backend is None
        assert system.strategies_handler.strategies == []
        assert system.get_status()["quarantined_strategies"] == []
    finally:
        system.stop(timeout=5.0)


def test_empty_registry_and_no_catalog_builds_with_zero_strategies(pg_database_env) -> None:
    """D-21 — the default for every existing live test: empty registry, no catalog, no raise.

    This is exactly why construction-time rehydrate was safe to land: no existing test seeds
    registry rows, so rehydrate is a zero-row no-op across the whole current suite.
    """
    store = _seed_store()
    try:
        system = _build()  # NO strategy_catalog injected
        try:
            assert system._system_db_backend is not None
            assert system.strategies_handler.strategies == []
        finally:
            system.stop(timeout=5.0)
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# STRAT-01 — the full restart lifecycle
# --------------------------------------------------------------------------------------


def test_seeded_rows_rehydrate_and_survive_a_rebuild(pg_database_env) -> None:
    """STRAT-01 — seeded rows become live instances, and the SAME roster resumes on rebuild.

    The load-bearing property: nothing hands the engine a strategy object. The STORE is the
    source of truth for what trades, across a full teardown + rebuild.
    """
    store = _seed_store()
    try:
        sma = _sma("sma_macd", sizing_policy=FractionOfCash(Decimal("0.75")))
        sma.subscribe_portfolio(_PID)
        _seed(store, [sma])

        # --- first boot -------------------------------------------------------------
        system = _build(strategy_catalog=test_catalog())
        try:
            registered = system.strategies_handler.strategies
            assert [s.name for s in registered] == ["sma_macd"]
            rebuilt = registered[0]
            assert type(rebuilt) is SMAMACDStrategy
            assert rebuilt.tickers == ["BTCUSD"]
            # A NON-default param: a defaults-only assertion would pass against a codec
            # that dropped the field entirely.
            assert rebuilt.sizing_policy == FractionOfCash(Decimal("0.75"))
            assert [str(p) for p in rebuilt.subscribed_portfolios] == [str(_PID)]
            first_id = rebuilt.strategy_id
        finally:
            system.stop(timeout=5.0)

        # --- restart: a brand-new engine over the SAME database ---------------------
        system2 = _build(strategy_catalog=test_catalog())
        try:
            resumed = system2.strategies_handler.strategies
            assert [s.name for s in resumed] == ["sma_macd"]
            assert resumed[0].sizing_policy == FractionOfCash(Decimal("0.75"))
            assert [str(p) for p in resumed[0].subscribed_portfolios] == [str(_PID)]
            # D-02: the durable identity is the NAME; strategy_id is ephemeral and is
            # freshly minted per construction, so it must NOT survive the restart.
            assert resumed[0].strategy_id != first_id
        finally:
            system2.stop(timeout=5.0)
    finally:
        store.delete("sma_macd")
        store.dispose()


def test_strategies_are_registered_before_start_is_called(pg_database_env) -> None:
    """The ORDERING constraint — rehydrate precedes session init (RESEARCH Item 2).

    ``wire_universe`` derives universe membership from the registered strategies and
    ``register_strategy_warmup`` sizes the feed ring from them; both run in
    ``_initialize_live_session``, which ``start()`` invokes. A strategy registered after
    either would never enter the universe and never size the ring. Asserting the roster is
    already populated when the factory RETURNS is what pins that.
    """
    store = _seed_store()
    try:
        _seed(store, [_sma("ordering_probe")])

        system = _build(strategy_catalog=test_catalog())
        try:
            # start() has NOT been called — construction alone populated the roster.
            assert [s.name for s in system.strategies_handler.strategies] == ["ordering_probe"]
        finally:
            system.stop(timeout=5.0)
    finally:
        store.delete("ordering_probe")
        store.dispose()


# --------------------------------------------------------------------------------------
# D-19 — the read-model surface + the loud infrastructure arm
# --------------------------------------------------------------------------------------


def test_unloadable_row_boots_healthy_sibling_and_surfaces_the_quarantine(
    pg_database_env,
) -> None:
    """D-19 — one unloadable row is quarantined onto the read-model; boot still succeeds.

    The healthy sibling trades. The bad name is exposed on ``state.quarantined_strategies``
    (a dedicated field — ``last_error`` is single-valued and would be overwritten), and its
    registry row is left declaring ``enabled=True`` because the DB holds operator INTENT.
    """
    store = _seed_store()
    try:
        _seed(store, [_sma("healthy")])
        # A retired class: the stored strategy_type is absent from the injected catalog.
        rows, _ = seeded_registry_rows([_sma("retired")])
        blob = dict(rows[0]["config_json"])
        blob["strategy_type"] = "RetiredStrategy"
        store.upsert("retired", "RetiredStrategy", blob, True, _AT)

        system = _build(strategy_catalog=test_catalog())
        try:
            assert [s.name for s in system.strategies_handler.strategies] == ["healthy"]
            assert system.get_status()["quarantined_strategies"] == ["retired"]
            # The row is untouched — fixing the class and restarting brings it back with no
            # manual re-enable.
            assert store.get("retired")["enabled"] is True
        finally:
            system.stop(timeout=5.0)
    finally:
        store.delete("healthy")
        store.delete("retired")
        store.dispose()


def test_rows_present_without_a_catalog_fails_the_boot_loudly(pg_database_env) -> None:
    """D-19 — rows + no catalog is a WIRING bug: the factory raises rather than booting dark.

    Booting a live engine that looks healthy and trades nothing is worse than not booting.
    """
    from itrader.strategy_handler.registry.rehydrate import RehydrateInfrastructureError

    store = _seed_store()
    try:
        _seed(store, [_sma("orphaned")])

        with pytest.raises(RehydrateInfrastructureError, match="strategy_catalog"):
            _build()  # rows exist, but no catalog was injected
    finally:
        store.delete("orphaned")
        store.dispose()
