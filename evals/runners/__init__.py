"""iTrader-only W1 + W2 benchmark runners (PERF-BASELINE §5/§7/§11).

- ``run_w1_benchmark`` — realistic 4-strategy / 6-portfolio W1 run over the real
  5m CSVs; asserts a non-trivial trade log; prints wall-clock + peak memory + a
  per-portfolio trade breakdown.
- ``run_w2_sweep`` — synthetic scaling sweep over n_symbols in {1, 10, 50};
  prints a (n_symbols, wall_clock_s, peak_mem_mb) point per symbol count.

Both are importable AND runnable as ``__main__``. Profiling (Scalene) is Step 2,
explicitly NOT here.
"""
