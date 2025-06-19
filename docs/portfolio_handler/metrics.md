# Portfolio Metrics & Analytics

## Overview

The MetricsManager provides comprehensive portfolio performance tracking, risk analytics, and reporting capabilities. It offers real-time metrics calculation, historical trend analysis, and professional-grade financial statistics.

## Available Metrics

### Core Portfolio Metrics

#### Current Snapshot Metrics
Access via `portfolio.metrics_manager.get_current_metrics()`

| Metric | Description | Type |
|--------|-------------|------|
| `total_equity` | Total portfolio value (cash + positions) | float |
| `cash_balance` | Available cash balance | float |
| `positions_value` | Combined market value of all positions | float |
| `unrealized_pnl` | Unrealized profit/loss from open positions | float |
| `realized_pnl` | Realized profit/loss from closed positions | float |
| `total_pnl` | Combined realized + unrealized P&L | float |
| `portfolio_return` | Total return since inception | float |
| `open_positions` | Number of currently open positions | int |
| `timestamp` | Metrics calculation timestamp | ISO string |

### Performance Analytics

#### Performance Metrics by Period
Access via `portfolio.metrics_manager.calculate_performance_metrics(period)`

**Available Periods**: `DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`, `YEARLY`, `ALL_TIME`

| Metric | Description | Formula |
|--------|-------------|---------|
| `total_return` | Total return for period | (End Value - Start Value) / Start Value |
| `annualized_return` | Annualized return rate | ((1 + Total Return)^(365/Days) - 1) |
| `daily_returns` | Daily return series | Daily percentage changes |
| `volatility` | Portfolio volatility (risk) | Standard deviation of daily returns |
| `max_drawdown` | Maximum peak-to-trough decline | Worst decline from any peak |
| `max_drawdown_duration_days` | Days to recover from max drawdown | Time to return to previous peak |

#### Risk-Adjusted Returns

| Metric | Description | Formula |
|--------|-------------|---------|
| `sharpe_ratio` | Return per unit of risk | (Return - Risk-free Rate) / Volatility |
| `sortino_ratio` | Return per unit of downside risk | (Return - Risk-free Rate) / Downside Deviation |
| `calmar_ratio` | Return per unit of max drawdown | Annualized Return / |Max Drawdown| |

#### Win/Loss Statistics

| Metric | Description | Type |
|--------|-------------|------|
| `win_rate` | Percentage of profitable trades | float (0.0 - 1.0) |
| `profit_factor` | Ratio of gross profit to gross loss | float |
| `average_win` | Average profit per winning trade | float |
| `average_loss` | Average loss per losing trade | float |
| `total_trades` | Total number of completed trades | int |
| `winning_trades` | Number of profitable trades | int |
| `losing_trades` | Number of losing trades | int |

### Risk Analytics

#### Drawdown Analysis
Access via `portfolio.metrics_manager.get_drawdown_analysis()`

| Metric | Description | Type |
|--------|-------------|------|
| `max_drawdown` | Largest peak-to-trough decline | float |
| `max_drawdown_date` | Date of maximum drawdown | ISO string |
| `max_drawdown_duration_days` | Recovery time from max drawdown | int |
| `current_drawdown` | Current drawdown from recent peak | float |
| `drawdown_periods` | Number of periods with >1% drawdown | int |
| `recovery_periods` | Number of recovery periods | int |

#### Return Distribution Analysis
Access via `portfolio.metrics_manager.get_return_distribution(period_days)`

| Metric | Description | Type |
|--------|-------------|------|
| `mean_return` | Average return per period | float |
| `return_std` | Standard deviation of returns | float |
| `skewness` | Distribution asymmetry | float |
| `kurtosis` | Distribution tail heaviness | float |
| `var_95` | Value at Risk (95% confidence) | float |
| `var_99` | Value at Risk (99% confidence) | float |
| `cvar_95` | Conditional VaR (95% confidence) | float |
| `positive_periods` | Number of periods with positive returns | int |
| `negative_periods` | Number of periods with negative returns | int |

## Usage Examples

### Basic Metrics Access

```python
# Get current portfolio snapshot
current_metrics = portfolio.metrics_manager.get_current_metrics()
print(f"Total Equity: ${current_metrics['total_equity']:,.2f}")
print(f"Total P&L: ${current_metrics['total_pnl']:,.2f}")
print(f"Return: {current_metrics['portfolio_return']:.2%}")
```

### Performance Analysis

```python
# Get monthly performance metrics
from itrader.portfolio_handler.metrics_manager import MetricsPeriod

monthly_metrics = portfolio.metrics_manager.calculate_performance_metrics(
    MetricsPeriod.MONTHLY
)

if monthly_metrics:
    print(f"Monthly Return: {monthly_metrics.total_return:.2%}")
    print(f"Annualized Return: {monthly_metrics.annualized_return:.2%}")
    print(f"Sharpe Ratio: {monthly_metrics.sharpe_ratio:.2f}")
    print(f"Max Drawdown: {monthly_metrics.max_drawdown:.2%}")
```

### Risk Analysis

```python
# Analyze portfolio drawdowns
drawdown_analysis = portfolio.metrics_manager.get_drawdown_analysis()
print(f"Max Drawdown: {drawdown_analysis['max_drawdown']:.2%}")
print(f"Recovery Time: {drawdown_analysis['max_drawdown_duration_days']} days")

# Get return distribution statistics
return_dist = portfolio.metrics_manager.get_return_distribution(period_days=1)
print(f"Daily Return Std: {return_dist['return_std']:.2%}")
print(f"95% VaR: {return_dist['var_95']:.2%}")
```

### Historical Snapshots

```python
# Get historical portfolio snapshots
from datetime import datetime, timedelta

snapshots = portfolio.metrics_manager.get_snapshots(
    start_date=datetime.now() - timedelta(days=30),
    limit=100
)

for snapshot in snapshots:
    print(f"{snapshot.timestamp}: ${snapshot.total_equity:.2f}")
```

## Metric Calculation Details

### Portfolio Return Calculation
```python
portfolio_return = (current_equity - initial_equity) / initial_equity
```

### Volatility Calculation
```python
# Annualized volatility from daily returns
daily_std = standard_deviation(daily_returns)
annualized_volatility = daily_std * sqrt(252)  # 252 trading days
```

### Sharpe Ratio Calculation
```python
# Assuming risk-free rate = 0 for simplicity
sharpe_ratio = annualized_return / annualized_volatility
```

### Maximum Drawdown
```python
# Running maximum equity value
running_max = cumulative_max(equity_values)

# Drawdown at each point
drawdowns = (equity_values - running_max) / running_max

# Maximum drawdown (most negative value)
max_drawdown = min(drawdowns)
```

### Value at Risk (VaR)
```python
# 95% VaR - 5th percentile of return distribution
var_95 = percentile(daily_returns, 5)

# Conditional VaR - expected loss beyond VaR threshold
cvar_95 = mean(returns[returns <= var_95])
```

## Benchmarking Support

### Benchmark Comparison
The system supports benchmark comparison for relative performance analysis:

```python
# Set benchmark prices (optional)
portfolio.metrics_manager.set_benchmark_price(datetime.now(), 100.0)

# Benchmark metrics will be included in snapshots
snapshot = portfolio.metrics_manager.record_snapshot()
benchmark_return = snapshot.benchmark_return  # Relative to benchmark
```

### Tracking Error
```python
# Calculate tracking error vs benchmark
performance_metrics = portfolio.metrics_manager.calculate_performance_metrics(
    MetricsPeriod.MONTHLY
)

# Custom calculation for tracking error
portfolio_returns = performance_metrics.daily_returns
# benchmark_returns would come from benchmark data
# tracking_error = std(portfolio_returns - benchmark_returns)
```

## Performance Considerations

### Caching
- Metrics are cached for 5 seconds by default to avoid redundant calculations
- Cache automatically invalidates when portfolio state changes
- Heavy calculations (like drawdown analysis) benefit from caching

### Memory Management
- Historical snapshots are limited to 10,000 by default
- Older snapshots are automatically pruned
- Consider periodic archival for long-running portfolios

### Thread Safety
- All metrics calculations are thread-safe
- Concurrent access is handled via locks
- Safe for use in multi-threaded applications

## Integration with Reporting

### Export Capabilities
```python
# Export metrics to dictionary for JSON serialization
metrics_dict = portfolio.metrics_manager.export_metrics()

# Suitable for:
# - API responses
# - Database storage
# - Report generation
# - Dashboard updates
```

### Real-time Updates
The metrics system automatically updates when:
- New transactions are processed
- Position market values change (via bar events)
- Manual snapshots are recorded

This ensures metrics always reflect the current portfolio state without manual intervention.
