from .backtest import (
    BacktestTradingSystem,
    build_backtest_system,
)

# The live surface (``LiveTradingSystem`` / ``build_live_system``) is deliberately
# absent from this barrel — no eager import, no PEP 562 ``__getattr__`` re-export.
# Either one would pull the live module onto the backtest import graph, which is what
# forced the pervasive lazy-imports-inside-methods this boundary removed. Live consumers
# import from the live submodule directly.
__all__ = [
    'BacktestTradingSystem',
    'build_backtest_system',
]
