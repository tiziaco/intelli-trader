"""
Metrics Manager for portfolio performance tracking and analytics.
Handles portfolio metrics calculation, historical tracking, and reporting.
"""

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import statistics
import math

from itrader.core.enums import MetricsPeriod
from itrader.logger import get_itrader_logger


@dataclass
class PortfolioSnapshot:
    """Portfolio state at a specific point in time."""
    timestamp: datetime
    total_equity: Decimal
    cash_balance: Decimal
    positions_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_pnl: Decimal
    open_positions_count: int
    portfolio_return: Decimal
    benchmark_return: Optional[Decimal] = None


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for a time period."""
    period: MetricsPeriod
    start_date: datetime
    end_date: datetime
    
    # Return metrics
    total_return: Decimal
    annualized_return: Decimal
    daily_returns: List[Decimal]
    
    # Risk metrics
    volatility: Decimal
    max_drawdown: Decimal
    max_drawdown_duration_days: int
    
    # Risk-adjusted returns
    sharpe_ratio: Optional[Decimal]
    sortino_ratio: Optional[Decimal]
    calmar_ratio: Optional[Decimal]
    
    # Win/Loss metrics
    win_rate: Decimal
    profit_factor: Optional[Decimal]
    average_win: Decimal
    average_loss: Decimal
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int


class MetricsManager:
    """
    Manages portfolio performance metrics, analytics, and reporting.
    
    Features:
    - Real-time portfolio metrics calculation
    - Historical performance tracking
    - Risk metrics and analytics
    - Benchmark comparison
    - Drawdown analysis
    - Risk-adjusted return calculations
    - Performance reporting
    """
    
    def __init__(self, portfolio: Any) -> None:
        self.portfolio = portfolio
        # D-19: lock removed — single-writer contract, see Portfolio docstring.
        self.logger = get_itrader_logger().bind(component="MetricsManager")
        
        # Store initial portfolio equity as baseline for return calculations.
        # M5-10 (D-06): total_equity is Decimal on the golden path — coerce
        # only for a lightweight test portfolio exposing a raw float.
        self.initial_equity = self._as_decimal(portfolio.total_equity)

        # Configuration
        # WR-01: this is the single source of truth for the snapshot-retention
        # bound. It is threaded into the storage backend below (directly via the
        # factory) so the deque(maxlen) the manager reads/writes is governed by
        # THIS value rather than silently diverging from a hardcoded storage
        # default. A real Portfolio injects its own state_storage (whose bound it
        # owns); a standalone-constructed manager fabricates one bounded by this.
        self.max_snapshots = 10000       # Maximum snapshots to keep (feeds deque maxlen plumbing)
        self.risk_free_rate = Decimal('0.02')  # 2% annual risk-free rate
        self.trading_days_per_year = 252

        # M2-08: metrics snapshots (append-only history) now live in the injected
        # state-storage seam. This manager no longer owns the container — it routes
        # reads/writes through self._storage. A real Portfolio always injects a
        # shared seam; a manager constructed standalone (e.g. with a lightweight
        # test portfolio) falls back to its own in-memory backend.
        from itrader.portfolio_handler.base import PortfolioStateStorage
        from itrader.portfolio_handler.storage import PortfolioStateStorageFactory
        storage = getattr(portfolio, "state_storage", None)
        if storage is None:
            # WR-01: thread max_snapshots through so the fabricated backend's
            # deque bound matches this manager's configured retention.
            storage = PortfolioStateStorageFactory.create(
                "backtest", max_snapshots=self.max_snapshots
            )
            # WR-02: share the fabricated seam with sibling managers so a
            # standalone-constructed portfolio does not end up with disjoint
            # per-manager backends (which would silently break cross-manager
            # invariants). A real Portfolio always sets state_storage first.
            try:
                portfolio.state_storage = storage
            except AttributeError:
                pass
        self._storage: PortfolioStateStorage = storage

        # D-04: the in-memory metrics cache (_metrics_cache / _cache_timestamp /
        # cache_duration_minutes / _is_cache_valid) is removed entirely.
        # calculate_performance_metrics now recomputes from the snapshot history
        # on each call (it has zero per-bar callers, so recompute-on-call is free).
        # This also kills the wall-clock TTL stamp (determinism smell,
        # inconsistent with the WR-01 no-wall-clock guard below) and the WR-03
        # unbounded-growth class. Live metrics will be Postgres-backed, not an
        # in-memory cache (owner decision, deferred to the Live Trading milestone).

        # Benchmark tracking (optional)
        self.benchmark_prices: Dict[datetime, Decimal] = {}
        
        self.logger.info("MetricsManager initialized",
            max_snapshots=self.max_snapshots
        )
    
    def record_snapshot(self, timestamp: Optional[datetime] = None) -> PortfolioSnapshot:
        """
        Record a portfolio snapshot for metrics calculation.
        
        Args:
            timestamp: Snapshot timestamp (defaults to now)
            
        Returns:
            PortfolioSnapshot: The recorded snapshot
        """
        # WR-01: do NOT silently fall back to wall clock. The locked
        # determinism contract is "business time, never wall clock" (CLAUDE.md).
        # Stamping a snapshot with datetime.now() would make the snapshot grid
        # and downstream period filtering non-reproducible. Require an explicit
        # business timestamp on every snapshot-creating path.
        if timestamp is None:
            raise ValueError(
                "record_snapshot requires an explicit business timestamp; "
                "wall-clock fallback would break determinism (WR-01)"
            )

        # Calculate current portfolio metrics
        total_equity = self._get_total_equity()
        cash_balance = self._get_cash_balance()
        positions_value = self._get_positions_value()
        unrealized_pnl = self._get_unrealized_pnl()
        realized_pnl = self._get_realized_pnl()
        total_pnl = unrealized_pnl + realized_pnl
        open_positions = self._get_open_positions_count()
            
        # Calculate portfolio return (from initial equity if available)
        portfolio_return = self._calculate_portfolio_return(total_equity)
            
        # Create snapshot
        snapshot = PortfolioSnapshot(
            timestamp=timestamp,
            total_equity=total_equity,
            cash_balance=cash_balance,
            positions_value=positions_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_pnl=total_pnl,
            open_positions_count=open_positions,
            portfolio_return=portfolio_return
        )
            
        # Store snapshot (via the seam).
        # D-03: snapshot retention is now the storage deque's maxlen — the
        # per-bar snapshot_count()>max_snapshots trim + whole-list slice-copy is
        # removed (the bounded deque auto-evicts the oldest on append, O(1)).
        # D-04: no per-bar metrics-cache clear() (the cache is gone).
        # D-02: no per-bar debug log — the snapshot already stores the raw
        # Timestamp + total_equity/total_pnl, so the log duplicated stored data
        # and only paid the per-bar isoformat()/str() arg construction.
        self._storage.add_snapshot(snapshot)

        return snapshot
    
    def get_current_metrics(self, timestamp: Optional[datetime] = None) -> Dict[str, Any]:
        """Get current portfolio metrics.

        Args:
            timestamp: Business time to stamp the initial snapshot with if none
                exists yet. WR-01: required (no wall-clock fallback) when the
                snapshot history is empty, so this read path stays deterministic.
        """

        # D-06: count-only / last-only accessors on the per-tick read path —
        # the empty-guard and the latest-read never copy the whole list.
        if self._storage.snapshot_count() == 0:
            # Create initial snapshot if none exists. WR-01: pass the supplied
            # business time through; record_snapshot raises if it is None rather
            # than reaching wall clock.
            self.record_snapshot(timestamp)

        latest_snapshot = self._storage.get_latest_snapshot()
        # Invariant: the empty-guard above guarantees at least one snapshot, so
        # get_latest_snapshot() is non-None here. Narrow for mypy (get_latest_snapshot
        # is Optional on the ABC because an empty backend returns None).
        assert latest_snapshot is not None

        # M5-10 (D-06): money fields stay Decimal end-to-end — no float()
        # coercion at this read boundary. The snapshot fields are already
        # Decimal; pass them straight through. The float boundary belongs at
        # the statistical-ratio metric inputs (drawdown/return-distribution/
        # daily-return), not here.
        return {
            "timestamp": latest_snapshot.timestamp.isoformat(),
            "total_equity": latest_snapshot.total_equity,
            "cash_balance": latest_snapshot.cash_balance,
            "positions_value": latest_snapshot.positions_value,
            "unrealized_pnl": latest_snapshot.unrealized_pnl,
            "realized_pnl": latest_snapshot.realized_pnl,
            "total_pnl": latest_snapshot.total_pnl,
            "portfolio_return": latest_snapshot.portfolio_return,
            "open_positions": latest_snapshot.open_positions_count
        }
    
    def calculate_performance_metrics(self, period: MetricsPeriod, 
                                    end_date: Optional[datetime] = None) -> Optional[PerformanceMetrics]:
        """
        Calculate comprehensive performance metrics for a period.
        
        Args:
            period: Time period for metrics
            end_date: End date for calculation (defaults to now)
            
        Returns:
            PerformanceMetrics: Calculated metrics or None if insufficient data
        """
        if end_date is None:
            # If no end_date provided and we have snapshots, use the latest snapshot's timestamp
            # This ensures tests with historical data work correctly
            _snaps = self._storage.get_snapshots()
            if _snaps:
                end_date = _snaps[-1].timestamp
            else:
                # WR-01: with no snapshots there is no business time to anchor
                # the period on, and a wall-clock end_date would make the
                # snapshot grid / period filtering non-reproducible. Caller must
                # supply an explicit business end_date in this case.
                raise ValueError(
                    "calculate_performance_metrics requires an explicit end_date "
                    "when no snapshots exist; wall-clock fallback would break "
                    "determinism (WR-01)"
                )
        
        # D-04: no cache lookup — recompute from the snapshot history each call.
        # Determine start date based on period
        start_date = self._get_period_start_date(period, end_date)
            
        # Get snapshots for the period
        period_snapshots = self._get_snapshots_for_period(start_date, end_date)
            
        if len(period_snapshots) < 2:
            self.logger.warning("Insufficient data for metrics calculation",
                period=period.name,
                snapshots_count=len(period_snapshots)
            )
            return None
            
        # Calculate metrics.
        # D-04: return the freshly computed object each call (no cache populate,
        # no wall-clock stamp).
        metrics = self._calculate_metrics_from_snapshots(
            period, start_date, end_date, period_snapshots
        )

        return metrics
    
    def get_drawdown_analysis(self, start_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Analyze portfolio drawdowns over time.
        
        Args:
            start_date: Start date for analysis (defaults to first snapshot)
            
        Returns:
            Dict containing drawdown analysis
        """
        all_snaps = self._storage.get_snapshots()
        if not all_snaps:
            return {"error": "No snapshots available"}

        if start_date is None:
            relevant_snapshots = all_snaps
        else:
            relevant_snapshots = [s for s in all_snaps if s.timestamp >= start_date]
            
        if len(relevant_snapshots) < 2:
            return {"error": "Insufficient data for drawdown analysis"}
            
        # Calculate running maximum and drawdowns.
        # WR-02: max_drawdown / current_drawdown are reported, money-derived
        # figures the project promises are trustworthy/cross-validated, so they
        # stay Decimal end-to-end (no binary-float round-trip). total_equity is
        # already Decimal; the drawdown ratio is computed in Decimal.
        equity_values = [s.total_equity for s in relevant_snapshots]
        timestamps = [s.timestamp for s in relevant_snapshots]

        _ZERO = Decimal('0')
        running_max = []
        drawdowns = []
        current_max = equity_values[0]

        for value in equity_values:
            current_max = max(current_max, value)
            running_max.append(current_max)

            # WR-02: uniform Decimal sentinel (not bare int 0) so the return
            # contract is consistent between flat-equity and real-drawdown cases.
            drawdown = (value - current_max) / current_max if current_max > 0 else _ZERO
            drawdowns.append(drawdown)

        # Find maximum drawdown
        max_drawdown = min(drawdowns) if drawdowns else _ZERO
        max_dd_index = drawdowns.index(max_drawdown) if max_drawdown < 0 else 0
            
        # Calculate drawdown duration
        max_dd_duration = self._calculate_drawdown_duration(drawdowns, max_dd_index)
            
        return {
            "max_drawdown": max_drawdown,
            "max_drawdown_date": timestamps[max_dd_index].isoformat(),
            "max_drawdown_duration_days": max_dd_duration,
            "current_drawdown": drawdowns[-1],
            "drawdown_periods": len([d for d in drawdowns if d < Decimal('-0.01')]),  # Periods > 1% drawdown
            "recovery_periods": len([i for i, d in enumerate(drawdowns) if d == _ZERO and i > 0])
        }
    
    def get_return_distribution(self, period_days: int = 1) -> Dict[str, Any]:
        """
        Analyze return distribution over specified periods.
        
        Args:
            period_days: Period length in days for return calculation
            
        Returns:
            Dict containing return distribution statistics
        """
        snaps = self._storage.get_snapshots()
        if len(snaps) < period_days + 1:
            return {"error": "Insufficient data for return analysis"}

        # Calculate period returns.
        # Statistical-ratio metric input boundary (D-06: money stays Decimal;
        # float only at the period-return ratio computation).
        returns = []
        for i in range(period_days, len(snaps)):
            current_equity = float(snaps[i].total_equity)
            previous_equity = float(snaps[i - period_days].total_equity)
                
            if previous_equity > 0:
                period_return = (current_equity - previous_equity) / previous_equity
                returns.append(period_return)
            
        if not returns:
            return {"error": "No returns calculated"}
            
        # Calculate distribution statistics
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0
            
        sorted_returns = sorted(returns)
        percentiles = {
            "5th": sorted_returns[int(len(sorted_returns) * 0.05)],
            "25th": sorted_returns[int(len(sorted_returns) * 0.25)],
            "50th": statistics.median(returns),
            "75th": sorted_returns[int(len(sorted_returns) * 0.75)],
            "95th": sorted_returns[int(len(sorted_returns) * 0.95)]
        }
            
        # Count positive/negative returns
        positive_returns = [r for r in returns if r > 0]
        negative_returns = [r for r in returns if r < 0]
            
        return {
            "period_days": period_days,
            "total_periods": len(returns),
            "mean_return": mean_return,
            "std_deviation": std_return,
            "skewness": self._calculate_skewness(returns),
            "kurtosis": self._calculate_kurtosis(returns),
            "percentiles": percentiles,
            "positive_periods": len(positive_returns),
            "negative_periods": len(negative_returns),
            "win_rate": len(positive_returns) / len(returns) if returns else 0,
            "best_return": max(returns),
            "worst_return": min(returns)
        }
    
    def set_benchmark_price(self, timestamp: datetime, price: float) -> None:
        """Set benchmark price for comparison."""
        self.benchmark_prices[timestamp] = Decimal(str(price))
    
    def get_snapshots(self, start_date: Optional[datetime] = None, 
                     end_date: Optional[datetime] = None, 
                     limit: Optional[int] = None) -> List[PortfolioSnapshot]:
        """Get portfolio snapshots for a date range."""
        
        snapshots = self._storage.get_snapshots()

        if start_date:
            snapshots = [s for s in snapshots if s.timestamp >= start_date]
            
        if end_date:
            snapshots = [s for s in snapshots if s.timestamp <= end_date]
            
        if limit:
            snapshots = snapshots[-limit:]

        # IN-03: storage.get_snapshots() already hands out a fresh
        # list(self._snapshots) each call, and the filter/limit branches above
        # rebind to new lists — so the result is always a caller-owned copy.
        # The trailing .copy() was a redundant allocation; return directly.
        return snapshots
    
    def export_metrics_to_dict(self, period: MetricsPeriod) -> Optional[Dict[str, Any]]:
        """Export performance metrics to dictionary format."""

        # WR-01: with no snapshots there is no business time to anchor the
        # period on; calculate_performance_metrics now raises rather than
        # reaching wall clock. That is genuinely insufficient data for an
        # export, so short-circuit to None (preserving the prior contract)
        # instead of propagating the determinism guard.
        if self._storage.snapshot_count() == 0:
            return None

        metrics = self.calculate_performance_metrics(period)
        if not metrics:
            return None
        
        return {
            "period": metrics.period.name,
            "start_date": metrics.start_date.isoformat(),
            "end_date": metrics.end_date.isoformat(),
            "total_return": float(metrics.total_return),
            "annualized_return": float(metrics.annualized_return),
            "volatility": float(metrics.volatility),
            "max_drawdown": float(metrics.max_drawdown),
            "max_drawdown_duration_days": metrics.max_drawdown_duration_days,
            "sharpe_ratio": float(metrics.sharpe_ratio) if metrics.sharpe_ratio else None,
            "sortino_ratio": float(metrics.sortino_ratio) if metrics.sortino_ratio else None,
            "calmar_ratio": float(metrics.calmar_ratio) if metrics.calmar_ratio else None,
            "win_rate": float(metrics.win_rate),
            "profit_factor": float(metrics.profit_factor) if metrics.profit_factor else None,
            "average_win": float(metrics.average_win),
            "average_loss": float(metrics.average_loss),
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades
        }
    
    # Private methods
    
    @staticmethod
    def _as_decimal(value: Any) -> Decimal:
        """Coerce a money read to Decimal.

        M5-10 (D-06): the real Portfolio's money properties now return Decimal,
        so this is a pass-through for the golden path (no str round-trip). The
        str() coercion only fires for a lightweight test portfolio that still
        exposes raw float attributes — never for the production engine.
        """
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def _get_total_equity(self) -> Decimal:
        """Get total portfolio equity (Decimal end-to-end; M5-10)."""
        if hasattr(self.portfolio, 'total_equity'):
            return self._as_decimal(self.portfolio.total_equity)
        return Decimal('0.00')

    def _get_cash_balance(self) -> Decimal:
        """Get cash balance (Decimal end-to-end; M2-02)."""
        if hasattr(self.portfolio, 'cash'):
            return self._as_decimal(self.portfolio.cash)
        return Decimal('0.00')

    def _get_positions_value(self) -> Decimal:
        """Get total positions value (Decimal end-to-end; M5-10)."""
        if hasattr(self.portfolio, 'total_market_value'):
            return self._as_decimal(self.portfolio.total_market_value)
        return Decimal('0.00')

    def _get_unrealized_pnl(self) -> Decimal:
        """Get unrealized P&L (Decimal end-to-end; M5-10)."""
        if hasattr(self.portfolio, 'total_unrealised_pnl'):
            return self._as_decimal(self.portfolio.total_unrealised_pnl)
        return Decimal('0.00')

    def _get_realized_pnl(self) -> Decimal:
        """Get realized P&L (Decimal end-to-end; M5-10)."""
        if hasattr(self.portfolio, 'total_realised_pnl'):
            return self._as_decimal(self.portfolio.total_realised_pnl)
        return Decimal('0.00')
    
    def _get_open_positions_count(self) -> int:
        """Get count of open positions."""
        if hasattr(self.portfolio, 'n_open_positions'):
            return int(self.portfolio.n_open_positions)
        return 0
    
    def _calculate_portfolio_return(self, current_equity: Decimal) -> Decimal:
        """Calculate portfolio return from initial equity."""
        if self.initial_equity > 0:
            return ((current_equity - self.initial_equity) / self.initial_equity) * 100
        return Decimal('0.00')
    
    def _get_period_start_date(self, period: MetricsPeriod, end_date: datetime) -> datetime:
        """Calculate start date for a given period."""
        if period == MetricsPeriod.DAILY:
            return end_date - timedelta(days=1)
        elif period == MetricsPeriod.WEEKLY:
            return end_date - timedelta(weeks=1)
        elif period == MetricsPeriod.MONTHLY:
            return end_date - timedelta(days=30)
        elif period == MetricsPeriod.QUARTERLY:
            return end_date - timedelta(days=90)
        elif period == MetricsPeriod.YEARLY:
            return end_date - timedelta(days=365)
        else:  # ALL_TIME
            snaps = self._storage.get_snapshots()
            return snaps[0].timestamp if snaps else end_date

    def _get_snapshots_for_period(self, start_date: datetime, end_date: datetime) -> List[PortfolioSnapshot]:
        """Get snapshots within a date range."""
        filtered_snapshots = []
        for snapshot in self._storage.get_snapshots():
            if start_date <= snapshot.timestamp <= end_date:
                filtered_snapshots.append(snapshot)
        return filtered_snapshots
    
    def _calculate_metrics_from_snapshots(self, period: MetricsPeriod, start_date: datetime, 
                                        end_date: datetime, snapshots: List[PortfolioSnapshot]) -> PerformanceMetrics:
        """Calculate performance metrics from snapshots."""
        
        # Calculate daily returns.
        # Statistical-ratio metric input boundary (D-06: money stays Decimal;
        # float only at the daily-return ratio computation).
        daily_returns = []
        for i in range(1, len(snapshots)):
            # total_equity is already Decimal; compute the ratio in Decimal so
            # the canonical daily_returns (List[Decimal]) stays exact rather than
            # baking a binary-float round-trip into a Decimal field.
            prev_equity = snapshots[i-1].total_equity
            curr_equity = snapshots[i].total_equity

            if prev_equity > 0:
                daily_returns.append((curr_equity - prev_equity) / prev_equity)
        
        # Basic return calculations.
        # WR-02: total_return is a reported, money-derived figure the project
        # promises is trustworthy/cross-validated. total_equity is already
        # Decimal; compute total_return in Decimal so no binary-float round-trip
        # is baked into the Decimal field. The float cast is reserved strictly
        # for the math.pow annualization exponent below.
        initial_equity = snapshots[0].total_equity
        final_equity = snapshots[-1].total_equity

        total_return = Decimal('0.00')
        if initial_equity > 0:
            total_return = (final_equity - initial_equity) / initial_equity

        # Annualized return
        days = (end_date - start_date).days
        annualized_return = Decimal('0.00')
        if days > 0 and initial_equity > 0:
            # Geometric annualization of the period total return.
            annualized_return = Decimal(str((1.0 + float(total_return)) ** (365.0 / days) - 1.0))
        
        # Volatility (standard deviation of returns)
        volatility = Decimal('0.00')
        if len(daily_returns) > 1:
            returns_float = [float(r) for r in daily_returns]
            volatility = Decimal(str(statistics.stdev(returns_float) * math.sqrt(self.trading_days_per_year)))
        
        # Risk-adjusted metrics
        sharpe_ratio = None
        if volatility > 0:
            excess_return = annualized_return - self.risk_free_rate
            sharpe_ratio = excess_return / volatility
        
        # Win/Loss metrics
        positive_returns = [r for r in daily_returns if r > 0]
        negative_returns = [r for r in daily_returns if r < 0]
        
        win_rate = Decimal(str(len(positive_returns) / len(daily_returns))) if daily_returns else Decimal('0.00')
        average_win = Decimal(str(statistics.mean([float(r) for r in positive_returns]))) if positive_returns else Decimal('0.00')
        average_loss = Decimal(str(statistics.mean([float(r) for r in negative_returns]))) if negative_returns else Decimal('0.00')
        
        return PerformanceMetrics(
            period=period,
            start_date=start_date,
            end_date=end_date,
            total_return=total_return,
            annualized_return=annualized_return,
            daily_returns=daily_returns,
            volatility=volatility,
            max_drawdown=Decimal('0.00'),  # Would need separate calculation
            max_drawdown_duration_days=0,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=None,  # Would need downside deviation calculation
            calmar_ratio=None,   # Would need max drawdown
            win_rate=win_rate,
            profit_factor=None,  # Need more complex calculation
            average_win=average_win,
            average_loss=average_loss,
            total_trades=len(daily_returns),
            winning_trades=len(positive_returns),
            losing_trades=len(negative_returns)
        )
    
    def _calculate_drawdown_duration(self, drawdowns: List[Decimal], max_dd_index: int) -> int:
        """Calculate drawdown duration in days."""
        # Simple implementation - find consecutive negative periods around max drawdown
        duration = 1
        
        # Look backwards from max drawdown
        for i in range(max_dd_index - 1, -1, -1):
            if drawdowns[i] < 0:
                duration += 1
            else:
                break
        
        # Look forwards from max drawdown
        for i in range(max_dd_index + 1, len(drawdowns)):
            if drawdowns[i] < 0:
                duration += 1
            else:
                break
        
        return duration
    
    def _calculate_skewness(self, returns: List[float]) -> float:
        """Calculate skewness of returns."""
        if len(returns) < 3:
            return 0.0
        
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)
        
        if std_return == 0:
            return 0.0
        
        skew_sum = sum(((r - mean_return) / std_return) ** 3 for r in returns)
        return skew_sum / len(returns)
    
    def _calculate_kurtosis(self, returns: List[float]) -> float:
        """Calculate kurtosis of returns."""
        if len(returns) < 4:
            return 0.0
        
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)
        
        if std_return == 0:
            return 0.0
        
        kurt_sum = sum(((r - mean_return) / std_return) ** 4 for r in returns)
        return (kurt_sum / len(returns)) - 3  # Excess kurtosis
