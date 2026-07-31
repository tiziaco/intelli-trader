"""The BACKTEST composition root — one of the two roots.

``build_backtest_system`` wires the component graph and ``BacktestRunner`` drives the
synchronous fail-fast for-loop. Its counterpart is ``trading_system/live/``; the two
share only the mode-blind handler graph and neither imports the other.

The separation is enforced by an import-graph boundary rather than by convention:
``tests/integration/test_okx_inertness.py`` asserts that importing this root pulls no
module under ``itrader.trading_system.live``, no venue concretion and no SQL. That is
what keeps the backtest path async/ccxt/SQL-free.
"""

from .backtest_trading_system import (
    BacktestTradingSystem,
    build_backtest_system,
)

__all__ = [
    'BacktestTradingSystem',
    'build_backtest_system',
]
