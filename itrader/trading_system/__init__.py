from .backtest_trading_system import (
    BacktestTradingSystem,
    build_backtest_system,
)

# D-12 (SEAM-04): the live surface (``LiveTradingSystem`` / ``build_live_system``) is
# DROPPED from this barrel entirely — no eager import, no PEP 562 ``__getattr__``
# re-export. Importing the ``trading_system`` barrel must NOT pull the live module onto
# the backtest import graph (that eager import was the root cause of the pervasive
# lazy-imports-inside-methods needed to keep ``test_okx_inertness.py`` green). Live
# consumers import from the live submodule directly (see the ``LiveTradingSystem``
# module docstring for the canonical submodule import path).
__all__ = [
    'BacktestTradingSystem',
    'build_backtest_system',
]
