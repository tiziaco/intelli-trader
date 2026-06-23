---
phase: quick-260623-bmg
plan: 01
subsystem: perf
tags: [perf-benchmark, coverage-instruments, trade-density, w1]
requires: []
provides:
  - "W1 coverage instruments B/C/D recycle positions (close -> free slot -> re-enter)"
affects:
  - perf/strategies/b_limit_maker.py
  - perf/strategies/c_pyramiding_trend.py
  - perf/strategies/d_short_zscore.py
tech-stack:
  added: []
  patterns: ["Decimal-end-to-end exit-bracket prices built off close/limit Decimals"]
key-files:
  created: []
  modified:
    - perf/strategies/b_limit_maker.py
    - perf/strategies/c_pyramiding_trend.py
    - perf/strategies/d_short_zscore.py
decisions:
  - "Tight exit brackets are CORRECT for coverage instruments — density (not alpha) is the coverage"
  - "Coverage semantics/docstring intent unchanged; only the exit leg + explanatory comments added"
metrics:
  duration: "~12 min"
  completed: 2026-06-23
requirements: [PERF-COVERAGE-DENSITY]
---

# Phase quick-260623-bmg Plan 01: Fix W1 coverage-instrument density (B/C/D exit leg) Summary

Added the missing recycling exit leg to the three W1 coverage instruments (B limit-maker,
C pyramiding-trend, D short-zscore) so each opens, hits a tight bracket, closes, frees a
`max_positions` slot, and re-enters — restoring the trade density these instruments exist
to generate. Verified on the 30-day diagnosis slice: total W1 fills jumped from the dead
3/3/1/1/1 (~11) baseline to **759**, with closed_positions > 0 for every gated portfolio.

## What changed

- **B (`b_limit_maker.py`)** — tightened `_TP_ABOVE` 0.01 -> 0.005 and added `_SL_BELOW =
  Decimal("0.01")`; `generate_signal` now passes both `sl` and `tp` to `buy_limit`. The
  filled resting-limit long now recycles instead of resting forever, keeping the
  resting-limit book churning.
- **C (`c_pyramiding_trend.py`)** — added `_TP_PCT = Decimal("0.02")`; `generate_signal`
  now passes `tp` alongside `sl` to `buy`. The pyramided long takes profit, frees cash, and
  re-accumulates across cycles (averaging / repeated-admission / CASH-rejection paths fire
  many times instead of one stuck position).
- **D (`d_short_zscore.py`)** — added `_TP_BELOW = Decimal("0.01")` and `_SL_ABOVE =
  Decimal("0.015")`; `generate_signal` builds the SHORT exit bracket off `Decimal(str(close))`
  (tp below entry = cover in profit, sl above = cover the loss) and passes both to `sell`.
  The short covers and re-shorts repeatedly, firing short-side admission + the 3-portfolio
  fan-out + rejections many times per portfolio.

All exit prices are built as `Decimal` off the existing `close`/`limit_price` Decimals
(no `Decimal(float)` introduced); 4-space `perf/` indentation preserved; each module
docstring/comment now notes the added exit and the recycling-for-density rationale.

## Verification

Task 1 automated gate (grep + import) passed: each call carries both an entry and an exit
leg, the new tunable constants exist, and all three modules import cleanly under
`PYTHONPATH="$PWD" poetry run python`.

Task 2 slice re-run (`start_date=2025-12-24`, `end_date=2026-01-24`, W1 topology via
`wire_w1` + runner `_make_on_tick`) — per-portfolio (fills / open / closed):

| Portfolio | fills | open | closed |
|-----------|------:|-----:|-------:|
| P1_A | 184 | 1 | 61 |
| P2_B | 17 | 3 | 7 |
| P3_C | 123 | 1 | 7 |
| P4_D | 145 | 1 | 72 |
| P5_D | 145 | 1 | 72 |
| P6_D | 145 | 1 | 72 |
| **TOTAL** | **759** | — | **291** |

Gate PASS: closed_positions > 0 for P2_B, P3_C, P4_D, P5_D, P6_D; total fills (759) are
materially above the 3/3/1/1/1 (~11) baseline. The runner's durable full-window
`_START_DATE`/`_END_DATE` (180-day window) were left untouched; the throwaway slice script
lives in the scratchpad and was NOT committed.

## Deviations from Plan

None — plan executed exactly as written. (Note: the `<worktree_branch_check>` reset the
worktree to base 3a639db, which discarded the orchestrator-staged PLAN.md from the worktree
working tree; the PLAN.md was read from the main checkout. This did not affect execution —
the `perf/` files exist at this base.)

## Self-Check: PASSED

- perf/strategies/b_limit_maker.py — FOUND, contains `_SL_BELOW`, `sl=sl`
- perf/strategies/c_pyramiding_trend.py — FOUND, contains `_TP_PCT`, `tp=tp`
- perf/strategies/d_short_zscore.py — FOUND, contains `_TP_BELOW`, `self.sell(ticker, sl=sl, tp=tp)`
- Commit 4cd2be7 — FOUND in git log
