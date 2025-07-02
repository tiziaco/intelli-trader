"""
Test suite for MetricsManager class.
Tests portfolio metrics calculation, performance analysis, and reporting.
"""

import unittest
import threading
import time
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock

from itrader.portfolio_handler.metrics_manager import (
    MetricsManager,
    MetricsPeriod,
    PortfolioSnapshot,
    PerformanceMetrics
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


class TestMetricsManager(unittest.TestCase):
    """Comprehensive test suite for MetricsManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = MockPortfolio(initial_equity=100000.0)
        self.metrics_manager = MetricsManager(self.portfolio)

    def test_metrics_manager_initialization(self):
        """Test MetricsManager initialization."""
        self.assertEqual(len(self.metrics_manager._snapshots), 0)
        self.assertEqual(self.metrics_manager.cache_duration_minutes, 5)
        self.assertEqual(self.metrics_manager.max_snapshots, 10000)
        self.assertEqual(self.metrics_manager.risk_free_rate, Decimal('0.02'))

    def test_record_snapshot(self):
        """Test recording portfolio snapshots."""
        timestamp = datetime.now()
        
        snapshot = self.metrics_manager.record_snapshot(timestamp)
        
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.timestamp, timestamp)
        self.assertEqual(snapshot.total_equity, Decimal('100000.0'))
        self.assertEqual(snapshot.cash_balance, Decimal('80000.0'))
        self.assertEqual(snapshot.positions_value, Decimal('20000.0'))
        
        # Check snapshot is stored
        self.assertEqual(len(self.metrics_manager._snapshots), 1)

    def test_record_multiple_snapshots(self):
        """Test recording multiple snapshots with different values."""
        base_time = datetime.now()
        
        # Record initial snapshot
        self.metrics_manager.record_snapshot(base_time)
        
        # Update portfolio values and record another snapshot
        self.portfolio.update_values(
            equity=105000.0,
            cash=75000.0,
            market_value=30000.0,
            unrealized_pnl=2000.0,
            realized_pnl=1000.0,
            positions=2
        )
        
        second_snapshot = self.metrics_manager.record_snapshot(base_time + timedelta(days=1))
        
        self.assertEqual(len(self.metrics_manager._snapshots), 2)
        self.assertEqual(second_snapshot.total_equity, Decimal('105000.0'))
        self.assertEqual(second_snapshot.unrealized_pnl, Decimal('2000.0'))
        self.assertEqual(second_snapshot.realized_pnl, Decimal('1000.0'))

    def test_snapshot_history_limit(self):
        """Test snapshot history size limit."""
        # Set low limit for testing
        self.metrics_manager.max_snapshots = 5
        
        # Record more snapshots than limit
        base_time = datetime.now()
        for i in range(10):
            self.portfolio.update_values(
                equity=100000.0 + i * 1000,
                cash=80000.0,
                market_value=20000.0 + i * 1000,
                unrealized_pnl=i * 100,
                realized_pnl=0.0,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Should only keep the last 5 snapshots
        self.assertEqual(len(self.metrics_manager._snapshots), 5)
        
        # First snapshot should be from day 5 (index 5)
        first_snapshot = self.metrics_manager._snapshots[0]
        self.assertEqual(first_snapshot.total_equity, Decimal('105000.0'))

    def test_get_current_metrics(self):
        """Test getting current portfolio metrics."""
        self.metrics_manager.record_snapshot()
        
        current_metrics = self.metrics_manager.get_current_metrics()
        
        self.assertIn("timestamp", current_metrics)
        self.assertIn("total_equity", current_metrics)
        self.assertIn("cash_balance", current_metrics)
        self.assertIn("positions_value", current_metrics)
        self.assertIn("total_pnl", current_metrics)
        self.assertIn("portfolio_return", current_metrics)
        
        self.assertEqual(current_metrics["total_equity"], 100000.0)
        self.assertEqual(current_metrics["cash_balance"], 80000.0)

    def test_get_current_metrics_auto_snapshot(self):
        """Test that current metrics creates snapshot if none exists."""
        # No snapshots recorded yet
        self.assertEqual(len(self.metrics_manager._snapshots), 0)
        
        current_metrics = self.metrics_manager.get_current_metrics()
        
        # Should automatically create a snapshot
        self.assertEqual(len(self.metrics_manager._snapshots), 1)
        self.assertIn("total_equity", current_metrics)

    def test_calculate_performance_metrics_insufficient_data(self):
        """Test performance metrics with insufficient data."""
        metrics = self.metrics_manager.calculate_performance_metrics(MetricsPeriod.DAILY)
        
        self.assertIsNone(metrics)

    def test_calculate_performance_metrics_with_data(self):
        """Test performance metrics calculation with sufficient data."""
        base_time = datetime.now()
        
        # Create a series of snapshots with changing values
        equity_values = [100000, 102000, 101000, 105000, 107000]
        
        for i, equity in enumerate(equity_values):
            self.portfolio.update_values(
                equity=equity,
                cash=equity * 0.8,
                market_value=equity * 0.2,
                unrealized_pnl=(equity - 100000) * 0.5,
                realized_pnl=(equity - 100000) * 0.5,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Calculate weekly metrics
        metrics = self.metrics_manager.calculate_performance_metrics(MetricsPeriod.WEEKLY)
        
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.period, MetricsPeriod.WEEKLY)
        self.assertGreater(metrics.total_return, 0)  # Should be positive return
        self.assertGreater(len(metrics.daily_returns), 0)

    def test_performance_metrics_caching(self):
        """Test performance metrics caching."""
        base_time = datetime.now()
        
        # Create snapshots
        for i in range(5):
            self.portfolio.update_values(
                equity=100000 + i * 1000,
                cash=80000,
                market_value=20000 + i * 1000,
                unrealized_pnl=i * 500,
                realized_pnl=i * 500,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Calculate metrics twice
        metrics1 = self.metrics_manager.calculate_performance_metrics(MetricsPeriod.WEEKLY)
        metrics2 = self.metrics_manager.calculate_performance_metrics(MetricsPeriod.WEEKLY)
        
        # Should return same object from cache
        self.assertEqual(metrics1.total_return, metrics2.total_return)
        self.assertEqual(len(self.metrics_manager._metrics_cache), 1)

    def test_drawdown_analysis(self):
        """Test drawdown analysis calculation."""
        base_time = datetime.now()
        
        # Create snapshots with a drawdown pattern
        equity_values = [100000, 105000, 102000, 98000, 95000, 102000, 110000]
        
        for i, equity in enumerate(equity_values):
            self.portfolio.update_values(
                equity=equity,
                cash=equity * 0.8,
                market_value=equity * 0.2,
                unrealized_pnl=0,
                realized_pnl=0,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        drawdown_analysis = self.metrics_manager.get_drawdown_analysis()
        
        self.assertIn("max_drawdown", drawdown_analysis)
        self.assertIn("max_drawdown_date", drawdown_analysis)
        self.assertIn("max_drawdown_duration_days", drawdown_analysis)
        self.assertIn("current_drawdown", drawdown_analysis)
        
        # Should have negative max drawdown (from 105000 to 95000)
        self.assertLess(drawdown_analysis["max_drawdown"], 0)

    def test_drawdown_analysis_insufficient_data(self):
        """Test drawdown analysis with insufficient data."""
        drawdown_analysis = self.metrics_manager.get_drawdown_analysis()
        
        self.assertIn("error", drawdown_analysis)
        self.assertEqual(drawdown_analysis["error"], "No snapshots available")

    def test_return_distribution_analysis(self):
        """Test return distribution analysis."""
        base_time = datetime.now()
        
        # Create snapshots with varying returns
        equity_values = [100000, 102000, 101000, 105000, 103000, 107000, 106000, 110000]
        
        for i, equity in enumerate(equity_values):
            self.portfolio.update_values(
                equity=equity,
                cash=equity * 0.8,
                market_value=equity * 0.2,
                unrealized_pnl=0,
                realized_pnl=0,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        distribution = self.metrics_manager.get_return_distribution(period_days=1)
        
        self.assertIn("mean_return", distribution)
        self.assertIn("std_deviation", distribution)
        self.assertIn("percentiles", distribution)
        self.assertIn("win_rate", distribution)
        self.assertIn("best_return", distribution)
        self.assertIn("worst_return", distribution)
        
        self.assertEqual(distribution["period_days"], 1)
        self.assertGreater(distribution["total_periods"], 0)

    def test_return_distribution_insufficient_data(self):
        """Test return distribution with insufficient data."""
        distribution = self.metrics_manager.get_return_distribution()
        
        self.assertIn("error", distribution)

    def test_benchmark_price_tracking(self):
        """Test benchmark price setting and tracking."""
        timestamp = datetime.now()
        benchmark_price = 50000.0
        
        self.metrics_manager.set_benchmark_price(timestamp, benchmark_price)
        
        self.assertIn(timestamp, self.metrics_manager.benchmark_prices)
        self.assertEqual(self.metrics_manager.benchmark_prices[timestamp], Decimal('50000.0'))

    def test_get_snapshots_with_filters(self):
        """Test getting snapshots with date filters."""
        base_time = datetime.now()
        
        # Create snapshots over several days
        for i in range(10):
            self.portfolio.update_values(
                equity=100000 + i * 1000,
                cash=80000,
                market_value=20000 + i * 1000,
                unrealized_pnl=i * 100,
                realized_pnl=0,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Test date range filter
        start_date = base_time + timedelta(days=3)
        end_date = base_time + timedelta(days=7)
        
        filtered_snapshots = self.metrics_manager.get_snapshots(
            start_date=start_date,
            end_date=end_date
        )
        
        self.assertEqual(len(filtered_snapshots), 5)  # Days 3-7 inclusive
        self.assertGreaterEqual(filtered_snapshots[0].timestamp, start_date)
        self.assertLessEqual(filtered_snapshots[-1].timestamp, end_date)

    def test_get_snapshots_with_limit(self):
        """Test getting snapshots with limit."""
        base_time = datetime.now()
        
        # Create 10 snapshots
        for i in range(10):
            self.portfolio.update_values(
                equity=100000 + i * 1000,
                cash=80000,
                market_value=20000 + i * 1000,
                unrealized_pnl=i * 100,
                realized_pnl=0,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Get last 5 snapshots
        limited_snapshots = self.metrics_manager.get_snapshots(limit=5)
        
        self.assertEqual(len(limited_snapshots), 5)
        # Should be the last 5 snapshots (highest equity values)
        self.assertEqual(limited_snapshots[-1].total_equity, Decimal('109000.0'))

    def test_export_metrics_to_dict(self):
        """Test exporting metrics to dictionary format."""
        base_time = datetime.now()
        
        # Create snapshots
        for i in range(7):
            self.portfolio.update_values(
                equity=100000 + i * 1000,
                cash=80000,
                market_value=20000 + i * 1000,
                unrealized_pnl=i * 500,
                realized_pnl=i * 500,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Export weekly metrics
        metrics_dict = self.metrics_manager.export_metrics_to_dict(MetricsPeriod.WEEKLY)
        
        self.assertIsNotNone(metrics_dict)
        self.assertIn("period", metrics_dict)
        self.assertIn("total_return", metrics_dict)
        self.assertIn("volatility", metrics_dict)
        self.assertIn("win_rate", metrics_dict)
        self.assertIn("total_trades", metrics_dict)
        
        self.assertEqual(metrics_dict["period"], "WEEKLY")

    def test_export_metrics_insufficient_data(self):
        """Test exporting metrics with insufficient data."""
        metrics_dict = self.metrics_manager.export_metrics_to_dict(MetricsPeriod.DAILY)
        
        self.assertIsNone(metrics_dict)

    def test_concurrent_snapshot_recording(self):
        """Test thread safety with concurrent snapshot recording."""
        results = []
        errors = []
        
        def record_snapshot_thread(thread_id):
            try:
                # Update portfolio values
                self.portfolio.update_values(
                    equity=100000 + thread_id * 1000,
                    cash=80000,
                    market_value=20000 + thread_id * 1000,
                    unrealized_pnl=thread_id * 100,
                    realized_pnl=0,
                    positions=1
                )
                
                timestamp = datetime.now() + timedelta(seconds=thread_id)
                snapshot = self.metrics_manager.record_snapshot(timestamp)
                results.append(snapshot)
                
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=record_snapshot_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent snapshot errors: {errors}")
        self.assertEqual(len(results), 10)
        self.assertEqual(len(self.metrics_manager._snapshots), 10)

    def test_portfolio_return_calculation(self):
        """Test portfolio return calculation."""
        base_time = datetime.now()
        
        # Record initial snapshot
        self.metrics_manager.record_snapshot(base_time)
        
        # Update portfolio to show profit
        self.portfolio.update_values(
            equity=120000.0,  # 20% gain
            cash=80000.0,
            market_value=40000.0,
            unrealized_pnl=15000.0,
            realized_pnl=5000.0,
            positions=2
        )
        
        snapshot = self.metrics_manager.record_snapshot(base_time + timedelta(days=1))
        
        # Portfolio return should be 20%
        self.assertEqual(snapshot.portfolio_return, Decimal('20.0'))

    def test_metrics_cache_invalidation(self):
        """Test that cache is invalidated when new snapshots are added."""
        base_time = datetime.now()
        
        # Create initial snapshots
        for i in range(5):
            self.portfolio.update_values(
                equity=100000 + i * 1000,
                cash=80000,
                market_value=20000 + i * 1000,
                unrealized_pnl=i * 500,
                realized_pnl=i * 500,
                positions=1
            )
            self.metrics_manager.record_snapshot(base_time + timedelta(days=i))
        
        # Calculate metrics (should be cached)
        metrics1 = self.metrics_manager.calculate_performance_metrics(MetricsPeriod.WEEKLY)
        self.assertEqual(len(self.metrics_manager._cache_timestamp), 1)
        
        # Add new snapshot (should invalidate cache)
        self.portfolio.update_values(
            equity=110000,
            cash=80000,
            market_value=30000,
            unrealized_pnl=7500,
            realized_pnl=2500,
            positions=1
        )
        self.metrics_manager.record_snapshot(base_time + timedelta(days=5))
        
        # Cache should be invalidated
        self.assertEqual(len(self.metrics_manager._cache_timestamp), 0)

    def test_period_start_date_calculation(self):
        """Test calculation of start dates for different periods."""
        end_date = datetime(2024, 6, 15, 12, 0, 0)
        
        # Test different periods
        daily_start = self.metrics_manager._get_period_start_date(MetricsPeriod.DAILY, end_date)
        weekly_start = self.metrics_manager._get_period_start_date(MetricsPeriod.WEEKLY, end_date)
        monthly_start = self.metrics_manager._get_period_start_date(MetricsPeriod.MONTHLY, end_date)
        
        self.assertEqual(daily_start, end_date - timedelta(days=1))
        self.assertEqual(weekly_start, end_date - timedelta(weeks=1))
        self.assertEqual(monthly_start, end_date - timedelta(days=30))

    def test_portfolio_snapshot_properties(self):
        """Test PortfolioSnapshot properties and calculations."""
        timestamp = datetime.now()
        
        # Update portfolio with specific values
        self.portfolio.update_values(
            equity=125000.0,
            cash=75000.0,
            market_value=50000.0,
            unrealized_pnl=15000.0,
            realized_pnl=10000.0,
            positions=3
        )
        
        snapshot = self.metrics_manager.record_snapshot(timestamp)
        
        # Verify snapshot properties
        self.assertEqual(snapshot.timestamp, timestamp)
        self.assertEqual(snapshot.total_equity, Decimal('125000.0'))
        self.assertEqual(snapshot.cash_balance, Decimal('75000.0'))
        self.assertEqual(snapshot.positions_value, Decimal('50000.0'))
        self.assertEqual(snapshot.unrealized_pnl, Decimal('15000.0'))
        self.assertEqual(snapshot.realized_pnl, Decimal('10000.0'))
        self.assertEqual(snapshot.total_pnl, Decimal('25000.0'))  # unrealized + realized
        self.assertEqual(snapshot.open_positions_count, 3)
        self.assertEqual(snapshot.portfolio_return, Decimal('25.0'))  # 25% return


if __name__ == '__main__':
    unittest.main()
