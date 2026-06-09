---
phase: 01-m1-ignition-lock-the-oracle
plan: 01
subsystem: ignition + test-skeleton
tags: [config, import-cascade, time-parser, pytest, conftest, smoke-test]
requires: []
provides:
  - "Importable backtest path (from itrader.trading_system.backtest_trading_system import TradingSystem)"
  - "Package-level FORBIDDEN_SYMBOLS / TIMEZONE / Config re-exports"
  - "Defensive to_timedelta daily-path guard (raises instead of None)"
  - "Root test/conftest.py: path-based marker auto-marking + shared fixtures"
  - "RED backtest smoke scaffold (test/test_smoke/test_backtest_smoke.py)"
affects:
  - itrader/config/__init__.py
  - itrader/outils/time_parser.py
  - test/conftest.py
  - test/test_smoke/test_backtest_smoke.py
tech-stack:
  added: []
  patterns:
    - "Re-export shadowed flat-module names via importlib file-path load"
    - "pytest_collection_modifyitems path-based auto-marking (works on unittest.TestCase)"
    - "Lazy/deferred fixture factory (construction inside inner function body)"
key-files:
  created:
    - test/conftest.py
    - test/test_smoke/test_backtest_smoke.py
  modified:
    - itrader/config/__init__.py
    - itrader/outils/time_parser.py
decisions:
  - "D-14: path-based marker auto-marking via pytest_collection_modifyitems"
  - "D-15: single root test/conftest.py holding shared fixtures + the auto-marking hook"
  - "D-16: smoke half — fast, unit-marked, asserts >=1 non-zero-qty trade"
metrics:
  duration: ~12 min
  completed: 2026-06-04
---

# Phase 1 Plan 01: Ignition + Test Skeleton Summary

Unblocked the backtest import cascade by re-exporting the shadowed flat-config names
(`FORBIDDEN_SYMBOLS`/`TIMEZONE`/`Config`) from the `itrader.config` package, hardened
`to_timedelta`'s daily path to fail loudly, and stood up the pytest skeleton (root
conftest with path-based auto-marking + shared fixtures, plus a RED run-path smoke
scaffold) that gates every later plan in this phase.

## What Was Built

### Task 1 — Config re-export + to_timedelta guard (M1-01/M1-02/M1-03)
- `itrader/config/__init__.py`: the package directory shadowed the flat `itrader/config.py`,
  so `from itrader.config import FORBIDDEN_SYMBOLS` (CCXT.py:8) failed at import. Loaded the
  flat module by file path via `importlib.util` and re-exported `FORBIDDEN_SYMBOLS`, `Config`,
  and `TIMEZONE` (sourced from `Config.TIMEZONE` = `'Europe/Paris'`), adding all three to
  `__all__`. The flat `config.py` is left **unmodified** (the real config collapse is M2-06).
- `itrader/outils/time_parser.py`: `to_timedelta` now raises a clear `ValueError` on
  unsupported units / unparseable input instead of silently returning `None`. Week/month
  support remains deferred to M2-10.

### Task 2 — Root conftest (M1-09)
- `test/conftest.py` (new): `pytest_collection_modifyitems` maps each test directory segment
  to one of the 8 declared markers, applied at collection time to the 30 legacy
  `unittest.TestCase` files with **zero edits** to them. Shared fixtures added: `global_queue`,
  golden-file path fixtures (`golden_dir`/`golden_trades_path`/`golden_equity_path`/
  `golden_summary_path`), and a `backtest_engine` factory. The factory uses **lazy/deferred
  construction** — the `TradingSystem` import and the `csv` exchange reference live inside the
  inner `_make` body — so `--collect-only` stays green before the CSV branch lands.

### Task 3 — Smoke scaffold (M1-09)
- `test/test_smoke/test_backtest_smoke.py` (new): import -> construct CSV-fed `TradingSystem`
  via the `backtest_engine` fixture -> add `SMA_MACD` + a $10k portfolio -> run -> assert
  run completion AND >=1 closed position with non-zero `net_quantity`. Auto-marked `unit` via
  the `test_smoke` path. Spaces-indented, no tabs. It is **RED** (fails at runtime with
  `NotImplementedError: Exchange 'csv' not implemented`) — exactly as intended; the CSV feed
  (Plan 02) and loop/sizing fixes (Plan 03) turn it green.

## Verification Results

- `poetry run python -c "from itrader.trading_system.backtest_trading_system import TradingSystem"` — exits 0
- `poetry run python -c "from itrader.config import FORBIDDEN_SYMBOLS, TIMEZONE, Config; print(TIMEZONE)"` — prints `Europe/Paris`
- `poetry run python -c "... to_timedelta('1d') == timedelta(days=1)"` — exits 0
- `poetry run pytest test/ --collect-only -q` — exits 0 (275 tests collected, no strict-config errors)
- `poetry run pytest test/ -m events --collect-only -q` — 17 selected; `-m portfolio` — 127 selected
- `poetry run pytest test/ --ignore=test/test_smoke -q` — **274 passed** (no legacy regression)
- `git diff --stat itrader/config.py test/test_portfolio_handler test/test_events` — empty (flat config + legacy tests untouched)
- Smoke test is RED at runtime (csv exchange not yet implemented), green at collection — expected per D-16.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TIMEZONE is a Config class attribute, not a flat module-level value**
- **Found during:** Task 1 (first verification run)
- **Issue:** The plan's `<interfaces>` note claimed `TIMEZONE` exists both as a module-level
  value and a `Config` attribute in flat `config.py`. In reality it exists **only** as
  `Config.TIMEZONE` — `_flat_config.TIMEZONE` raised `AttributeError`.
- **Fix:** Source the re-exported `TIMEZONE` from `Config.TIMEZONE` (still `'Europe/Paris'`,
  matching the PingGenerator default and CSV-branch index tz per the plan's requirement).
- **Files modified:** itrader/config/__init__.py
- **Commit:** 39581c8

**2. [Rule 3 - Blocking] Removed test_smoke/__init__.py to match predominant test layout**
- **Found during:** Task 3
- **Issue:** Plan said add `__init__.py` "if the existing test layout uses package dirs".
  Only `test_portfolio_handler` has one; the other 6 sibling dirs (`test_events`,
  `test_strategy`, etc.) collect fine without it.
- **Fix:** Created then removed `test/test_smoke/__init__.py` to match the predominant
  no-`__init__` layout; collection verified to work (275 tests collected).
- **Files modified:** (none net — file removed)

## Threat Model Compliance

- T-01-01 (Tampering — re-export shadow): mitigated. Only the three named flat symbols are
  re-exported via an `importlib` file-path load; no `exec`/`eval` of arbitrary input; flat
  `config.py` left unmodified (verified by empty `git diff --stat itrader/config.py`).
- T-01-02 / T-01-SC: accept — no Postgres/network reach on import, zero new package installs.

## Known Stubs

None. The smoke test is an intentional RED scaffold (documented above, resolved by Plans 02/03),
not a stub returning placeholder data.

## Notes for Next Plan

- Plan 02 must implement the `csv` exchange branch in `PriceHandler` (skipping `SqlHandler`/CCXT)
  to make the `backtest_engine` factory and smoke test runnable.
- Plan 03 adds the sizing seam in `OrderManager._create_primary_order` + the `record_metrics`
  per-Portfolio fix + the SMA_MACD `.iloc[-1]`/`fillna=False` fix to turn the smoke test green.
- The `backtest_engine` factory passes `exchange="csv"` and accepts `ticker`/`timeframe`/`cash`
  kwargs (currently unused beyond `exchange`/dates) — wire strategy/portfolio inside it or in
  the test as the API solidifies.

## Self-Check: PASSED
- FOUND: itrader/config/__init__.py (modified)
- FOUND: itrader/outils/time_parser.py (modified)
- FOUND: test/conftest.py (created)
- FOUND: test/test_smoke/test_backtest_smoke.py (created)
- FOUND commit: 39581c8 (Task 1)
- FOUND commit: b58eaf7 (Task 2)
- FOUND commit: 5099d01 (Task 3)
