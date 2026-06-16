---
phase: 04-liquidation-cross-validation-re-baseline
plan: 00
subsystem: test-scaffolding
tags: [nyquist, wave-0, liquidation, test-stubs, e2e, oracle-dark]
requires:
  - "pytest ^8.4.2 (already installed)"
  - "tests/conftest.py folder-derived TYPE markers (unit/e2e)"
provides:
  - "tests/unit/portfolio/test_liquidation.py — LIQ-01/02 unit stubs"
  - "tests/unit/order/test_liquidation_reconcile.py — LIQ-03 mirror-reconcile unit stubs"
  - "tests/e2e/forced_liq_long/ — white-box forced-liq long e2e stub"
  - "tests/e2e/forced_liq_short/ — white-box forced-liq short e2e stub"
  - "tests/e2e/levered_long_into_liquidation/ — white-box leveraged-long-into-liq e2e stub"
affects:
  - "Downstream Phase-4 implementation plans (04-03 unit, 04-04 e2e) — their verify selectors now resolve >=1 collectible test"
tech-stack:
  added: []
  patterns:
    - "collectible pytest.skip Wave-0 stub (Nyquist sampling contract)"
    - "white-box e2e leaf mirroring tests/e2e/levered_long/ (NOT the run_scenario/golden harness)"
    - "folder-derived TYPE marker (no decorator)"
key-files:
  created:
    - tests/unit/portfolio/test_liquidation.py
    - tests/unit/order/test_liquidation_reconcile.py
    - tests/e2e/forced_liq_long/__init__.py
    - tests/e2e/forced_liq_long/bars.csv
    - tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
    - tests/e2e/forced_liq_short/__init__.py
    - tests/e2e/forced_liq_short/bars.csv
    - tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
    - tests/e2e/levered_long_into_liquidation/__init__.py
    - tests/e2e/levered_long_into_liquidation/bars.csv
    - tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py
  modified: []
decisions:
  - "Synthetic ticker LIQUSD in all e2e leaves (NEVER BTCUSD) so the spot oracle (134 / 46189.87730727451) is untouchable"
  - "WR-04 regression test NOT created here — owned by 04-02 (co-located TDD RED->GREEN); nyquist_compliant holds because 04-02 creates its own collectible before its RED step"
  - "e2e leaves are white-box (assert liquidation internals) NOT golden-diff — load-bearing asserts are not captured by trades/equity/summary CSVs (mirrors levered_long parked pattern, D-17)"
metrics:
  duration: 6 min
  completed: 2026-06-16
  tasks: 2
  files: 11
---

# Phase 4 Plan 00: Liquidation Wave-0 Nyquist Scaffolding Summary

Created 13 collectible `pytest.skip` Wave-0 stubs (2 unit files + 3 white-box e2e leaf dirs) so every Phase-4 LIQUIDATION verify selector resolves >=1 test before any downstream implementation RED step — a pure test-only change adding zero production code, leaving the SMA_MACD spot oracle byte-exact (D-11).

## What Was Built

**Task 1 — unit stubs (commit ce9cf95):**
- `tests/unit/portfolio/test_liquidation.py` — 6 stubs: `test_isolated_liq_price_long`, `test_isolated_liq_price_short`, `test_liquidation_breach_detected_on_bar_close`, `test_liquidation_penalty`, `test_liquidation_loss_capped_at_wb` (explicit `min(loss+penalty, WB)` clamp with a FAT fee), `test_multi_breach_deterministic` (fixed symbol-then-open-time order).
- `tests/unit/order/test_liquidation_reconcile.py` — 4 stubs: `test_liquidation_reconcile_executed_to_filled`, `test_liquidation_trigger_source` (`OrderTriggerSource.LIQUIDATION`), `test_no_new_fill_status`, `test_unregistered_order_no_ops_mirror` (Pitfall 4 guard).

**Task 2 — white-box e2e leaves (commit 4cf06ea):**
- `tests/e2e/forced_liq_long/`, `tests/e2e/forced_liq_short/`, `tests/e2e/levered_long_into_liquidation/` — each with `__init__.py` + flat-OHLC `bars.csv` (close == mark) + a scenario stub. Each mirrors `tests/e2e/levered_long/` (white-box, NOT the golden-diff harness). Synthetic ticker `LIQUSD`; the `bars.csv` price paths are crafted to cross the corrected long liq price (80.808…) / short liq price (118.811…) on bar close so the downstream 04-04 hand-computation has a working data series.

## Verification

- `poetry run pytest <all 5 paths> --collect-only -q` → **13 tests collected, 0 errors**.
- Unit selectors resolve: `-k "multi_breach_deterministic"` (1), `-k "liquidation_penalty"` (1), `tests/unit/order -k "liquidation"` (4).
- Each e2e leaf collects 1 test; all 13 run **skipped, 0 errors** under `filterwarnings=["error"]` / `--strict-markers`.
- No `backtesting`/`backtrader` import in any file.

## Deviations from Plan

None — plan executed exactly as written. (WR-04 was correctly NOT created here, per the plan's explicit ownership note — it belongs to 04-02's inline TDD task.)

## Notes

- The 11 created files contain only skipped stubs + crafted data fixtures — no production code, no stub data flowing to a UI/result. The Wave-0 stubs ARE intentional placeholders resolved by 04-03 (unit) / 04-04 (e2e), documented in each file's docstring and `pytest.skip` message.
- Oracle protection held by construction: every e2e leaf uses the synthetic `LIQUSD` ticker, never `BTCUSD`.

## Self-Check: PASSED

Files (all 11 present):
- FOUND: tests/unit/portfolio/test_liquidation.py
- FOUND: tests/unit/order/test_liquidation_reconcile.py
- FOUND: tests/e2e/forced_liq_long/{__init__.py, bars.csv, test_forced_liq_long_scenario.py}
- FOUND: tests/e2e/forced_liq_short/{__init__.py, bars.csv, test_forced_liq_short_scenario.py}
- FOUND: tests/e2e/levered_long_into_liquidation/{__init__.py, bars.csv, test_levered_long_into_liquidation_scenario.py}

Commits:
- FOUND: ce9cf95 (Task 1 unit stubs)
- FOUND: 4cf06ea (Task 2 e2e leaves)
