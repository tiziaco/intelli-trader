"""The BACKTEST composition root — one of the two roots the redesign separates.

This package is the whole backtest construction surface: ``build_backtest_system`` wires
the component graph and ``BacktestRunner`` drives the synchronous fail-fast for-loop. Its
counterpart is ``trading_system/live/``, and the two share only the mode-blind handler
graph — neither root imports the other.

The separation is enforced by an import-graph boundary rather than by convention: the
inertness probe asserts that importing this root pulls no module under
``itrader.trading_system.live``, no venue concretion and no SQL. That is what keeps the
backtest path async/ccxt/SQL-free.

Both modules here are TAB-indented (they moved into this package byte-for-byte); this
barrel is 4-space, like every new module in the redesign.
"""

from .backtest_trading_system import (
    BacktestTradingSystem,
    build_backtest_system,
)

__all__ = [
    'BacktestTradingSystem',
    'build_backtest_system',
]
