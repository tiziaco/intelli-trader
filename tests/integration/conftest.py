"""Integration-layer fixtures (D-13/D-15).

These fixtures serve the cross-component cascade, the run-path smoke test, and the
golden-master oracle — all of which exercise MORE than one collaborating component
(the D-15 integration boundary). They live here, not at the root, because the unit
layer never needs the frozen-oracle assets or a full ``TradingSystem``.

Golden assets moved with the tree (D-13): ``tests/golden/{trades,equity}.csv`` +
``summary.json``. The path fixtures below resolve to that moved location.
"""

import pathlib

import pytest

# This file lives at <repo>/tests/integration/, so the golden dir is one level up
# under tests/golden/.
_GOLDEN_DIR = pathlib.Path(__file__).resolve().parent.parent / "golden"


@pytest.fixture
def golden_dir():
    """Path to the committed frozen-oracle directory (tests/golden/)."""
    return _GOLDEN_DIR


@pytest.fixture
def golden_trades_path():
    """Path to the frozen trade-log CSV."""
    return _GOLDEN_DIR / "trades.csv"


@pytest.fixture
def golden_equity_path():
    """Path to the frozen equity-curve CSV."""
    return _GOLDEN_DIR / "equity.csv"


@pytest.fixture
def golden_summary_path():
    """Path to the frozen summary JSON."""
    return _GOLDEN_DIR / "summary.json"


# --- Shared operational-Postgres substrate (single suite-wide container) ------


@pytest.fixture(scope="session")
def pg_container_url():
    """The SINGLE session-scoped testcontainers Postgres for the whole integration tree.

    Models its lifecycle EXACTLY on ``tests/integration/storage/conftest.py::pg_engine``:
    the ``testcontainers`` import is DEFERRED into the body so ``--collect-only`` needs no
    Docker daemon; the ``PostgresContainer`` constructor eagerly builds a DockerClient, so an
    absent/unreachable daemon raises as early as construction (kept inside the ``try``). ANY
    startup failure is converted to a ``pytest.skip`` (D-11) — the PG arm must never hard-fail
    a Dockerless run. It yields the connection URL so consumers build their own Engine off it.

    This is the ONE container for the whole ``tests/integration/`` tree (it cascades into
    ``storage/``): ``storage/conftest.py::pg_engine`` and the ``pg_database_env`` opt-in fixture
    both consume this URL, so no second competing container is ever spun.
    """
    from testcontainers.postgres import PostgresContainer

    container = None
    try:
        # Constructor eagerly builds a DockerClient — absent daemon raises here, not .start().
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        pytest.skip(f"PostgreSQL container unavailable — skipped (D-11): {exc}")

    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def pg_database_env(pg_container_url, monkeypatch):
    """Point the ``ITRADER_DATABASE_URL`` env gate at the shared container within test scope.

    The companion for tests that go through the ``LiveTradingSystem`` env gate: it
    ``monkeypatch.setenv``s ``ITRADER_DATABASE_URL`` to the shared ``pg_container_url`` (the
    function-scoped set overrides the session-scoped dev-DB guard in ``tests/conftest.py`` and
    is undone at test teardown) and returns the URL so the test can also build a drop Engine.
    """
    monkeypatch.setenv("ITRADER_DATABASE_URL", pg_container_url)
    return pg_container_url


@pytest.fixture
def backtest_engine():
    """Factory that builds a CSV-fed backtest ``BacktestTradingSystem``.

    Returns a callable so construction is DEFERRED until a test actually invokes it.
    The BacktestTradingSystem import lives inside the inner function body so
    ``--collect-only`` succeeds even if a referenced branch is not yet wired.
    """

    def _make(
        ticker="BTCUSD",
        timeframe="1d",
        start_date="2018-01-01",
        end_date="2026-06-03",
        cash=10_000,
    ):
        # Deferred import: only executed when a test calls the factory.
        from itrader.trading_system.backtest_trading_system import (
            BacktestTradingSystem,
        )

        return BacktestTradingSystem(
            exchange="csv",
            start_date=start_date,
            end_date=end_date,
        )

    return _make
