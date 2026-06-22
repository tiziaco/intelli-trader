"""Throwaway-but-kept tooling for the evals harness.

- ``fetch_binance_5m.py`` — a hardened ONE-SHOT CCXT fetch script. Its OUTPUT
  (the committed ``data/*_5m.csv`` files) is the durable artifact; the script
  itself is kept in-repo as a documented one-shot (re-runnable, not on the run
  path).
- ``validate_csv.py`` — the CSV validation gate (loud failure on bad data).
"""
