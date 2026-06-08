"""
Test suite for MetricsManager class.
Tests portfolio metrics calculation, performance analysis, and reporting.
"""

import threading
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from itrader.portfolio_handler.metrics.metrics_manager import (
    MetricsManager,
    MetricsPeriod,
    PortfolioSnapshot,
    PerformanceMetrics,
)


class MockPortfolio:
    """Mock portfolio for testing."""

    def __init__(self, initial_equity=100000.0):
        self.portfolio_id = 12345
        self.total_equity = initial_equity
        self.cash = initial_equity * 0.8  # 80% cash
        self.total_market_value = initial_equity * 0.2  # 20% in positions
        self.total_unrealised_pnl = 0.0
        self.total_realised_pnl = 0.0
        self.n_open_positions = 0

    def update_values(self, equity, cash, market_value, unrealized_pnl, realized_pnl, positions):
        """Update portfolio values for testing."""
        self.total_equity = equity
        self.cash = cash
        self.total_market_value = market_value
        self.total_unrealised_pnl = unrealized_pnl
        self.total_realised_pnl = realized_pnl
        self.n_open_positions = positions


@pytest.fixture
def env():
    """A MetricsManager on a $100000 mock portfolio."""
    portfolio = MockPortfolio(initial_equity=100000.0)
    metrics_manager = MetricsManager(portfolio)
    return SimpleNamespace(portfolio=portfolio, metrics_manager=metrics_manager)


def test_metrics_manager_initialization(env):
    """Test MetricsManager initialization."""
    mm = env.metrics_manager
    assert len(mm._storage.get_snapshots()) == 0
    assert mm.cache_duration_minutes == 5
    assert mm.max_snapshots == 10000
    assert mm.risk_free_rate == Decimal("0.02")


def test_record_snapshot(env):
    """Test recording portfolio snapshots."""
    mm = env.metrics_manager
    timestamp = datetime.now()

    snapshot = mm.record_snapshot(timestamp)

    assert snapshot is not None
    assert snapshot.timestamp == timestamp
    assert snapshot.total_equity == Decimal("100000.0")
    assert snapshot.cash_balance == Decimal("80000.0")
    assert snapshot.positions_value == Decimal("20000.0")

    # Check snapshot is stored
    assert len(mm._storage.get_snapshots()) == 1


def test_record_multiple_snapshots(env):
    """Test recording multiple snapshots with different values."""
    mm = env.metrics_manager
    base_time = datetime.now()

    mm.record_snapshot(base_time)

    env.portfolio.update_values(
        equity=105000.0, cash=75000.0, market_value=30000.0,
        unrealized_pnl=2000.0, realized_pnl=1000.0, positions=2,
    )

    second_snapshot = mm.record_snapshot(base_time + timedelta(days=1))

    assert len(mm._storage.get_snapshots()) == 2
    assert second_snapshot.total_equity == Decimal("105000.0")
    assert second_snapshot.unrealized_pnl == Decimal("2000.0")
    assert second_snapshot.realized_pnl == Decimal("1000.0")


def test_snapshot_history_limit(env):
    """Test snapshot history size limit."""
    mm = env.metrics_manager
    mm.max_snapshots = 5

    base_time = datetime.now()
    for i in range(10):
        env.portfolio.update_values(
            equity=100000.0 + i * 1000, cash=80000.0, market_value=20000.0 + i * 1000,
            unrealized_pnl=i * 100, realized_pnl=0.0, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    # Should only keep the last 5 snapshots
    assert len(mm._storage.get_snapshots()) == 5

    # First snapshot should be from day 5 (index 5)
    first_snapshot = mm._storage.get_snapshots()[0]
    assert first_snapshot.total_equity == Decimal("105000.0")


def test_get_current_metrics(env):
    """Test getting current portfolio metrics."""
    mm = env.metrics_manager
    mm.record_snapshot()

    current_metrics = mm.get_current_metrics()

    assert "timestamp" in current_metrics
    assert "total_equity" in current_metrics
    assert "cash_balance" in current_metrics
    assert "positions_value" in current_metrics
    assert "total_pnl" in current_metrics
    assert "portfolio_return" in current_metrics

    assert current_metrics["total_equity"] == 100000.0
    assert current_metrics["cash_balance"] == 80000.0


def test_get_current_metrics_money_fields_are_decimal(env):
    """M5-10 (D-06): get_current_metrics money fields stay Decimal end-to-end.

    The float() coercion of money is removed — only the statistical-ratio
    metric inputs (drawdown/return-distribution/daily-return) narrow to float.
    """
    mm = env.metrics_manager
    mm.record_snapshot()

    current_metrics = mm.get_current_metrics()

    for field in (
        "total_equity",
        "cash_balance",
        "positions_value",
        "unrealized_pnl",
        "realized_pnl",
        "total_pnl",
    ):
        assert isinstance(current_metrics[field], Decimal), (
            f"{field} must be Decimal, got {type(current_metrics[field])}"
        )


def test_get_current_metrics_auto_snapshot(env):
    """Test that current metrics creates snapshot if none exists."""
    mm = env.metrics_manager
    assert len(mm._storage.get_snapshots()) == 0

    current_metrics = mm.get_current_metrics()

    # Should automatically create a snapshot
    assert len(mm._storage.get_snapshots()) == 1
    assert "total_equity" in current_metrics


def test_calculate_performance_metrics_insufficient_data(env):
    """Test performance metrics with insufficient data."""
    metrics = env.metrics_manager.calculate_performance_metrics(MetricsPeriod.DAILY)
    assert metrics is None


def test_calculate_performance_metrics_with_data(env):
    """Test performance metrics calculation with sufficient data."""
    mm = env.metrics_manager
    base_time = datetime.now()

    equity_values = [100000, 102000, 101000, 105000, 107000]
    for i, equity in enumerate(equity_values):
        env.portfolio.update_values(
            equity=equity, cash=equity * 0.8, market_value=equity * 0.2,
            unrealized_pnl=(equity - 100000) * 0.5, realized_pnl=(equity - 100000) * 0.5,
            positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    metrics = mm.calculate_performance_metrics(MetricsPeriod.WEEKLY)

    assert metrics is not None
    assert metrics.period == MetricsPeriod.WEEKLY
    assert metrics.total_return > 0  # Should be positive return
    assert len(metrics.daily_returns) > 0


def test_performance_metrics_caching(env):
    """Test performance metrics caching."""
    mm = env.metrics_manager
    base_time = datetime.now()

    for i in range(5):
        env.portfolio.update_values(
            equity=100000 + i * 1000, cash=80000, market_value=20000 + i * 1000,
            unrealized_pnl=i * 500, realized_pnl=i * 500, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    metrics1 = mm.calculate_performance_metrics(MetricsPeriod.WEEKLY)
    metrics2 = mm.calculate_performance_metrics(MetricsPeriod.WEEKLY)

    # Should return same object from cache
    assert metrics1.total_return == metrics2.total_return
    assert len(mm._metrics_cache) == 1


def test_drawdown_analysis(env):
    """Test drawdown analysis calculation."""
    mm = env.metrics_manager
    base_time = datetime.now()

    equity_values = [100000, 105000, 102000, 98000, 95000, 102000, 110000]
    for i, equity in enumerate(equity_values):
        env.portfolio.update_values(
            equity=equity, cash=equity * 0.8, market_value=equity * 0.2,
            unrealized_pnl=0, realized_pnl=0, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    drawdown_analysis = mm.get_drawdown_analysis()

    assert "max_drawdown" in drawdown_analysis
    assert "max_drawdown_date" in drawdown_analysis
    assert "max_drawdown_duration_days" in drawdown_analysis
    assert "current_drawdown" in drawdown_analysis

    # Should have negative max drawdown (from 105000 to 95000)
    assert drawdown_analysis["max_drawdown"] < 0


def test_drawdown_analysis_insufficient_data(env):
    """Test drawdown analysis with insufficient data."""
    drawdown_analysis = env.metrics_manager.get_drawdown_analysis()

    assert "error" in drawdown_analysis
    assert drawdown_analysis["error"] == "No snapshots available"


def test_return_distribution_analysis(env):
    """Test return distribution analysis."""
    mm = env.metrics_manager
    base_time = datetime.now()

    equity_values = [100000, 102000, 101000, 105000, 103000, 107000, 106000, 110000]
    for i, equity in enumerate(equity_values):
        env.portfolio.update_values(
            equity=equity, cash=equity * 0.8, market_value=equity * 0.2,
            unrealized_pnl=0, realized_pnl=0, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    distribution = mm.get_return_distribution(period_days=1)

    assert "mean_return" in distribution
    assert "std_deviation" in distribution
    assert "percentiles" in distribution
    assert "win_rate" in distribution
    assert "best_return" in distribution
    assert "worst_return" in distribution

    assert distribution["period_days"] == 1
    assert distribution["total_periods"] > 0


def test_return_distribution_insufficient_data(env):
    """Test return distribution with insufficient data."""
    distribution = env.metrics_manager.get_return_distribution()
    assert "error" in distribution


def test_benchmark_price_tracking(env):
    """Test benchmark price setting and tracking."""
    mm = env.metrics_manager
    timestamp = datetime.now()

    mm.set_benchmark_price(timestamp, 50000.0)

    assert timestamp in mm.benchmark_prices
    assert mm.benchmark_prices[timestamp] == Decimal("50000.0")


def test_get_snapshots_with_filters(env):
    """Test getting snapshots with date filters."""
    mm = env.metrics_manager
    base_time = datetime.now()

    for i in range(10):
        env.portfolio.update_values(
            equity=100000 + i * 1000, cash=80000, market_value=20000 + i * 1000,
            unrealized_pnl=i * 100, realized_pnl=0, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    start_date = base_time + timedelta(days=3)
    end_date = base_time + timedelta(days=7)

    filtered_snapshots = mm.get_snapshots(start_date=start_date, end_date=end_date)

    assert len(filtered_snapshots) == 5  # Days 3-7 inclusive
    assert filtered_snapshots[0].timestamp >= start_date
    assert filtered_snapshots[-1].timestamp <= end_date


def test_get_snapshots_with_limit(env):
    """Test getting snapshots with limit."""
    mm = env.metrics_manager
    base_time = datetime.now()

    for i in range(10):
        env.portfolio.update_values(
            equity=100000 + i * 1000, cash=80000, market_value=20000 + i * 1000,
            unrealized_pnl=i * 100, realized_pnl=0, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    limited_snapshots = mm.get_snapshots(limit=5)

    assert len(limited_snapshots) == 5
    # Should be the last 5 snapshots (highest equity values)
    assert limited_snapshots[-1].total_equity == Decimal("109000.0")


def test_export_metrics_to_dict(env):
    """Test exporting metrics to dictionary format."""
    mm = env.metrics_manager
    base_time = datetime.now()

    for i in range(7):
        env.portfolio.update_values(
            equity=100000 + i * 1000, cash=80000, market_value=20000 + i * 1000,
            unrealized_pnl=i * 500, realized_pnl=i * 500, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    metrics_dict = mm.export_metrics_to_dict(MetricsPeriod.WEEKLY)

    assert metrics_dict is not None
    assert "period" in metrics_dict
    assert "total_return" in metrics_dict
    assert "volatility" in metrics_dict
    assert "win_rate" in metrics_dict
    assert "total_trades" in metrics_dict

    assert metrics_dict["period"] == "WEEKLY"


def test_export_metrics_insufficient_data(env):
    """Test exporting metrics with insufficient data."""
    metrics_dict = env.metrics_manager.export_metrics_to_dict(MetricsPeriod.DAILY)
    assert metrics_dict is None


def test_concurrent_snapshot_recording(env):
    """Test thread safety with concurrent snapshot recording."""
    mm = env.metrics_manager
    results = []
    errors = []

    def record_snapshot_thread(thread_id):
        try:
            env.portfolio.update_values(
                equity=100000 + thread_id * 1000, cash=80000,
                market_value=20000 + thread_id * 1000, unrealized_pnl=thread_id * 100,
                realized_pnl=0, positions=1,
            )
            timestamp = datetime.now() + timedelta(seconds=thread_id)
            results.append(mm.record_snapshot(timestamp))
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(10):
        thread = threading.Thread(target=record_snapshot_thread, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert len(errors) == 0, f"Concurrent snapshot errors: {errors}"
    assert len(results) == 10
    assert len(mm._storage.get_snapshots()) == 10


def test_portfolio_return_calculation(env):
    """Test portfolio return calculation."""
    mm = env.metrics_manager
    base_time = datetime.now()

    mm.record_snapshot(base_time)

    env.portfolio.update_values(
        equity=120000.0, cash=80000.0, market_value=40000.0,
        unrealized_pnl=15000.0, realized_pnl=5000.0, positions=2,
    )

    snapshot = mm.record_snapshot(base_time + timedelta(days=1))

    # Portfolio return should be 20%
    assert snapshot.portfolio_return == Decimal("20.0")


def test_metrics_cache_invalidation(env):
    """Test that cache is invalidated when new snapshots are added."""
    mm = env.metrics_manager
    base_time = datetime.now()

    for i in range(5):
        env.portfolio.update_values(
            equity=100000 + i * 1000, cash=80000, market_value=20000 + i * 1000,
            unrealized_pnl=i * 500, realized_pnl=i * 500, positions=1,
        )
        mm.record_snapshot(base_time + timedelta(days=i))

    mm.calculate_performance_metrics(MetricsPeriod.WEEKLY)
    assert len(mm._cache_timestamp) == 1

    env.portfolio.update_values(
        equity=110000, cash=80000, market_value=30000,
        unrealized_pnl=7500, realized_pnl=2500, positions=1,
    )
    mm.record_snapshot(base_time + timedelta(days=5))

    # Cache should be invalidated
    assert len(mm._cache_timestamp) == 0


def test_period_start_date_calculation(env):
    """Test calculation of start dates for different periods."""
    mm = env.metrics_manager
    end_date = datetime(2024, 6, 15, 12, 0, 0)

    daily_start = mm._get_period_start_date(MetricsPeriod.DAILY, end_date)
    weekly_start = mm._get_period_start_date(MetricsPeriod.WEEKLY, end_date)
    monthly_start = mm._get_period_start_date(MetricsPeriod.MONTHLY, end_date)

    assert daily_start == end_date - timedelta(days=1)
    assert weekly_start == end_date - timedelta(weeks=1)
    assert monthly_start == end_date - timedelta(days=30)


def test_portfolio_snapshot_properties(env):
    """Test PortfolioSnapshot properties and calculations."""
    mm = env.metrics_manager
    timestamp = datetime.now()

    env.portfolio.update_values(
        equity=125000.0, cash=75000.0, market_value=50000.0,
        unrealized_pnl=15000.0, realized_pnl=10000.0, positions=3,
    )

    snapshot = mm.record_snapshot(timestamp)

    assert snapshot.timestamp == timestamp
    assert snapshot.total_equity == Decimal("125000.0")
    assert snapshot.cash_balance == Decimal("75000.0")
    assert snapshot.positions_value == Decimal("50000.0")
    assert snapshot.unrealized_pnl == Decimal("15000.0")
    assert snapshot.realized_pnl == Decimal("10000.0")
    assert snapshot.total_pnl == Decimal("25000.0")  # unrealized + realized
    assert snapshot.open_positions_count == 3
    assert snapshot.portfolio_return == Decimal("25.0")  # 25% return
