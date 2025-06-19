"""
Metrics Manager for portfolio performance tracking and analytics.
Handles portfolio metrics calculation, historical tracking, and reporting.
"""

import threading
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import statistics
import math

from itrader.portfolio_handler.exceptions import InvalidTransactionError
from itrader.logger import get_itrader_logger


class MetricsPeriod(Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"
    ALL_TIME = "ALL_TIME"


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
    
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self._lock = threading.RLock()
        self.logger = get_itrader_logger().bind(component="MetricsManager")
        
        # Store initial portfolio equity as baseline for return calculations
        self.initial_equity = Decimal(str(portfolio.total_equity))
        
        # Historical snapshots for trend analysis
        self._snapshots: List[PortfolioSnapshot] = []
        
        # Performance metrics cache
        self._metrics_cache: Dict[str, PerformanceMetrics] = {}
        self._cache_timestamp: Dict[str, datetime] = {}
        
        # Configuration
        self.cache_duration_minutes = 5  # Cache metrics for 5 minutes
        self.max_snapshots = 10000       # Maximum snapshots to keep
        self.risk_free_rate = Decimal('0.02')  # 2% annual risk-free rate
        self.trading_days_per_year = 252
        
        # Benchmark tracking (optional)
        self.benchmark_prices: Dict[datetime, Decimal] = {}
        
        self.logger.info("MetricsManager initialized",
            cache_duration=self.cache_duration_minutes,
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
        if timestamp is None:
            timestamp = datetime.now()
        
        with self._lock:
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
            
            # Store snapshot
            self._snapshots.append(snapshot)
            
            # Manage snapshot history size
            if len(self._snapshots) > self.max_snapshots:
                self._snapshots = self._snapshots[-self.max_snapshots:]
            
            # Invalidate cache when new data is added
            self._cache_timestamp.clear()
            
            self.logger.debug("Portfolio snapshot recorded",
                timestamp=timestamp.isoformat(),
                total_equity=str(total_equity),
                total_pnl=str(total_pnl)
            )
            
            return snapshot
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current portfolio metrics."""
        
        with self._lock:
            if not self._snapshots:
                # Create initial snapshot if none exists
                self.record_snapshot()
            
            latest_snapshot = self._snapshots[-1]
            
            return {
                "timestamp": latest_snapshot.timestamp.isoformat(),
                "total_equity": float(latest_snapshot.total_equity),
                "cash_balance": float(latest_snapshot.cash_balance),
                "positions_value": float(latest_snapshot.positions_value),
                "unrealized_pnl": float(latest_snapshot.unrealized_pnl),
                "realized_pnl": float(latest_snapshot.realized_pnl),
                "total_pnl": float(latest_snapshot.total_pnl),
                "portfolio_return": float(latest_snapshot.portfolio_return),
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
            if self._snapshots:
                end_date = self._snapshots[-1].timestamp
            else:
                end_date = datetime.now()
        
        cache_key = f"{period.name}_{end_date.date()}"
        
        # Check cache first
        if self._is_cache_valid(cache_key):
            return self._metrics_cache[cache_key]
        
        with self._lock:
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
            
            # Calculate metrics
            metrics = self._calculate_metrics_from_snapshots(
                period, start_date, end_date, period_snapshots
            )
            
            # Cache results
            self._metrics_cache[cache_key] = metrics
            self._cache_timestamp[cache_key] = datetime.now()
            
            return metrics
    
    def get_drawdown_analysis(self, start_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Analyze portfolio drawdowns over time.
        
        Args:
            start_date: Start date for analysis (defaults to first snapshot)
            
        Returns:
            Dict containing drawdown analysis
        """
        with self._lock:
            if not self._snapshots:
                return {"error": "No snapshots available"}
            
            if start_date is None:
                relevant_snapshots = self._snapshots
            else:
                relevant_snapshots = [s for s in self._snapshots if s.timestamp >= start_date]
            
            if len(relevant_snapshots) < 2:
                return {"error": "Insufficient data for drawdown analysis"}
            
            # Calculate running maximum and drawdowns
            equity_values = [float(s.total_equity) for s in relevant_snapshots]
            timestamps = [s.timestamp for s in relevant_snapshots]
            
            running_max = []
            drawdowns = []
            current_max = equity_values[0]
            
            for value in equity_values:
                current_max = max(current_max, value)
                running_max.append(current_max)
                
                drawdown = (value - current_max) / current_max if current_max > 0 else 0
                drawdowns.append(drawdown)
            
            # Find maximum drawdown
            max_drawdown = min(drawdowns) if drawdowns else 0
            max_dd_index = drawdowns.index(max_drawdown) if max_drawdown < 0 else 0
            
            # Calculate drawdown duration
            max_dd_duration = self._calculate_drawdown_duration(drawdowns, max_dd_index)
            
            return {
                "max_drawdown": max_drawdown,
                "max_drawdown_date": timestamps[max_dd_index].isoformat(),
                "max_drawdown_duration_days": max_dd_duration,
                "current_drawdown": drawdowns[-1],
                "drawdown_periods": len([d for d in drawdowns if d < -0.01]),  # Periods > 1% drawdown
                "recovery_periods": len([i for i, d in enumerate(drawdowns) if d == 0 and i > 0])
            }
    
    def get_return_distribution(self, period_days: int = 1) -> Dict[str, Any]:
        """
        Analyze return distribution over specified periods.
        
        Args:
            period_days: Period length in days for return calculation
            
        Returns:
            Dict containing return distribution statistics
        """
        with self._lock:
            if len(self._snapshots) < period_days + 1:
                return {"error": "Insufficient data for return analysis"}
            
            # Calculate period returns
            returns = []
            for i in range(period_days, len(self._snapshots)):
                current_equity = float(self._snapshots[i].total_equity)
                previous_equity = float(self._snapshots[i - period_days].total_equity)
                
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
    
    def set_benchmark_price(self, timestamp: datetime, price: float):
        """Set benchmark price for comparison."""
        with self._lock:
            self.benchmark_prices[timestamp] = Decimal(str(price))
    
    def get_snapshots(self, start_date: Optional[datetime] = None, 
                     end_date: Optional[datetime] = None, 
                     limit: Optional[int] = None) -> List[PortfolioSnapshot]:
        """Get portfolio snapshots for a date range."""
        
        with self._lock:
            snapshots = self._snapshots
            
            if start_date:
                snapshots = [s for s in snapshots if s.timestamp >= start_date]
            
            if end_date:
                snapshots = [s for s in snapshots if s.timestamp <= end_date]
            
            if limit:
                snapshots = snapshots[-limit:]
            
            return snapshots.copy()
    
    def export_metrics_to_dict(self, period: MetricsPeriod) -> Optional[Dict[str, Any]]:
        """Export performance metrics to dictionary format."""
        
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
    
    def _get_total_equity(self) -> Decimal:
        """Get total portfolio equity."""
        if hasattr(self.portfolio, 'total_equity'):
            return Decimal(str(self.portfolio.total_equity))
        return Decimal('0.00')
    
    def _get_cash_balance(self) -> Decimal:
        """Get cash balance."""
        if hasattr(self.portfolio, 'cash'):
            return Decimal(str(self.portfolio.cash))
        return Decimal('0.00')
    
    def _get_positions_value(self) -> Decimal:
        """Get total positions value."""
        if hasattr(self.portfolio, 'total_market_value'):
            return Decimal(str(self.portfolio.total_market_value))
        return Decimal('0.00')
    
    def _get_unrealized_pnl(self) -> Decimal:
        """Get unrealized P&L."""
        if hasattr(self.portfolio, 'total_unrealised_pnl'):
            return Decimal(str(self.portfolio.total_unrealised_pnl))
        return Decimal('0.00')
    
    def _get_realized_pnl(self) -> Decimal:
        """Get realized P&L."""
        if hasattr(self.portfolio, 'total_realised_pnl'):
            return Decimal(str(self.portfolio.total_realised_pnl))
        return Decimal('0.00')
    
    def _get_open_positions_count(self) -> int:
        """Get count of open positions."""
        if hasattr(self.portfolio, 'n_open_positions'):
            return self.portfolio.n_open_positions
        return 0
    
    def _calculate_portfolio_return(self, current_equity: Decimal) -> Decimal:
        """Calculate portfolio return from initial equity."""
        if self.initial_equity > 0:
            return ((current_equity - self.initial_equity) / self.initial_equity) * 100
        return Decimal('0.00')
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached metrics are still valid."""
        if cache_key not in self._cache_timestamp:
            return False
        
        cache_age = datetime.now() - self._cache_timestamp[cache_key]
        return cache_age.total_seconds() < (self.cache_duration_minutes * 60)
    
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
            return self._snapshots[0].timestamp if self._snapshots else end_date
    
    def _get_snapshots_for_period(self, start_date: datetime, end_date: datetime) -> List[PortfolioSnapshot]:
        """Get snapshots within a date range."""
        filtered_snapshots = []
        for snapshot in self._snapshots:
            if start_date <= snapshot.timestamp <= end_date:
                filtered_snapshots.append(snapshot)
        return filtered_snapshots
    
    def _calculate_metrics_from_snapshots(self, period: MetricsPeriod, start_date: datetime, 
                                        end_date: datetime, snapshots: List[PortfolioSnapshot]) -> PerformanceMetrics:
        """Calculate performance metrics from snapshots."""
        
        # Calculate daily returns
        daily_returns = []
        for i in range(1, len(snapshots)):
            prev_equity = float(snapshots[i-1].total_equity)
            curr_equity = float(snapshots[i].total_equity)
            
            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                daily_returns.append(Decimal(str(daily_return)))
        
        # Basic return calculations
        initial_equity = float(snapshots[0].total_equity)
        final_equity = float(snapshots[-1].total_equity)
        
        total_return = Decimal('0.00')
        if initial_equity > 0:
            total_return = Decimal(str((final_equity - initial_equity) / initial_equity))
        
        # Annualized return
        days = (end_date - start_date).days
        annualized_return = Decimal('0.00')
        if days > 0 and initial_equity > 0:
            daily_return = float(total_return) / days
            annualized_return = Decimal(str((1 + daily_return) ** 365 - 1))
        
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
    
    def _calculate_drawdown_duration(self, drawdowns: List[float], max_dd_index: int) -> int:
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
