"""Proof that the shared session container reaches the ``LiveTradingSystem`` env gate.

The ``pg_database_env`` fixture (``tests/integration/conftest.py``) points
``ITRADER_DATABASE_URL`` at the SINGLE suite-wide ``pg_container_url`` testcontainers
Postgres. This test opts in and constructs a ``LiveTradingSystem`` — asserting the
composition root selects the durable ``CachedSql*`` wrappers through the env gate
(overriding the session-scoped dev-DB guard in ``tests/conftest.py``). It drops the
operational tables in ``finally`` so the shared DB is left pristine for the storage
suite (mirrors ``test_store_live_drive.py``'s drop helper).

Dockerless runs skip transitively (``pg_container_url`` raises ``Skipped``, D-11).

4-space indentation (matches ``tests/integration/*``); folder-derived
``integration``/``slow`` markers; NO ``__init__.py`` in this dir (auto-memory:
package-collision hazard).
"""

# Operational tables dropped after the test so the shared session DB stays pristine.
_OPERATIONAL_TABLES = (
    "order_state_changes",
    "orders",
    "signals",
    "portfolio_snapshots",
    "portfolio_states",
    "account_states",
)


def _drop_operational_tables(url):
    """Drop the operational tables so the shared session DB is left pristine (LIFO teardown)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            for table in _OPERATIONAL_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    finally:
        engine.dispose()


def test_shared_pg_fixture_wires_live_system(pg_database_env):
    """The shared container, via the env gate, wires the durable CachedSql* storage.

    ``pg_database_env`` has set ``ITRADER_DATABASE_URL`` to the shared container URL, so the
    ``LiveTradingSystem`` composition root builds the sync-durable order working set
    (``CachedSqlOrderStorage``) and the live signal store (``CachedSqlSignalStorage``) off ONE
    shared ``SqlEngine`` — proving the new shared fixture reaches the env gate.
    """
    import itrader.trading_system.live_trading_system as lts

    system = lts.LiveTradingSystem.for_exchange("binance")
    try:
        assert type(system._signal_store).__name__ == "CachedSqlSignalStorage"
        assert type(system.portfolio_handler._order_storage).__name__ == "CachedSqlOrderStorage"
    finally:
        system.stop()
        _drop_operational_tables(pg_database_env)
