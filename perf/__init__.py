"""Durable perf/ benchmark harness for the iTrader backtest engine.

This package is the long-lived performance scoreboard (PERF-BASELINE
spike, Step 1). It lives OUTSIDE the shipped ``itrader/`` package and imports
the engine via absolute imports (``from itrader.strategy_handler.base import
Strategy``). These are durable assets, regression-tracked every milestone — NOT
scratch.

Layout:
- ``tools/``      — the hardened one-shot CCXT fetch script + CSV validation gate.
- ``strategies/`` — coverage instruments A-D (exercise engine paths, NOT alpha).
- ``workloads/``  — W1 topology wiring + W2 numpy-GBM synthetic generator.
- ``runners/``    — iTrader-only W1 + W2 benchmark runners.
- ``results/``    — frozen baseline + hotspot artifacts (written in Step 2).

Convention: 4-space indentation throughout (newer-module convention per CLAUDE.md).
"""
