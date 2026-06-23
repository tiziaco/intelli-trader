"""W1 topology wiring + W2 synthetic generator (durable workloads).

- ``w1_topology`` — the 4-strategy / 6-portfolio W1 wiring helper (applies the
  short-selling recipe; the runner owns ``on_tick`` cancel/modify).
- ``synthetic`` — ``make_synthetic_ohlcv(n_bars, n_symbols, seed=42)``, the
  numpy-GBM scaling-sweep generator (W2).
"""

from .synthetic import make_synthetic_ohlcv

__all__ = ["make_synthetic_ohlcv"]
