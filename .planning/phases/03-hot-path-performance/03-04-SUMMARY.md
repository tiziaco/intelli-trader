---
phase: 03-hot-path-performance
plan: 04
subsystem: strategy
tags: [hot-path, performance, macd, sma, phase-gate, documentation, oracle]

# Dependency graph
requires:
  - phase: 03-hot-path-performance (Plan 01)
    provides: PERF-01 storage copy-drop + snapshot accessors (must be merged before the phase-gate oracle re-run)
  - phase: 03-hot-path-performance (Plan 02)
    provides: PERF-03 eager Bar prebuild (must be merged before the phase-gate oracle re-run)
  - phase: 03-hot-path-performance (Plan 03)
    provides: PERF-02 mechanical micro-redundancy removals (must be merged before the phase-gate oracle re-run)
provides:
  - "PERF-03 W1-12: MACD computed INSIDE the SMA guard (lazy, only on ticks where the SMA filter holds); firing tick byte-identical"
  - "Doc truth-corrections: ROADMAP SC-1 (D-04 *_snapshot() declined), ROADMAP SC-2 + REQUIREMENTS PERF-02 (D-10 W1-13 descoped)"
  - "Phase-3 cross-cutting correctness gate: byte-exact oracle + full e2e + mypy --strict + full unit/integration suite, all green on the merged result of all four plans"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy-compute-inside-guard: move an unconditional indicator computation inside the filter that gates its use, so it only runs on ticks where the filter holds — firing tick stays byte-identical (only control-flow placement changes)"

key-files:
  created:
    - .planning/phases/03-hot-path-performance/03-04-SUMMARY.md
  modified:
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md

key-decisions:
  - "D-02 (owner constraint, NON-NEGOTIABLE): NO new/modified unit test against SMA_MACD. W1-12 is verified by code review + the byte-exact oracle ONLY. git diff --stat confirms only the strategy file changed under itrader/ — zero tests/ changes for SMA_MACD."
  - "D-04: the *_snapshot() variant is declined — a query-based live backend is copy-safe for free, so no speculative API was added. ROADMAP SC-1 + REQUIREMENTS PERF-01 corrected to drop the stale claim."
  - "D-10: W1-13 (active-portfolio recompute) descoped — annotated as descoped with explicit D-10 citation in both ROADMAP SC-2 and REQUIREMENTS PERF-02; W1-13 removed from the PERF-02 traceability tag but the descope is recorded (not silently deleted)."

patterns-established:
  - "Pattern: compute an indicator lazily inside the guard that gates its consumption — byte-identical on the firing tick, skips the computation on non-firing ticks"

# Verification evidence
verification:
  oracle: "tests/integration/test_backtest_oracle.py — 3 passed (check_exact); 134 trades / final_equity 46189.87730727451 EXACT"
  e2e: "tests/e2e — 58 passed (count read from the run, not a pinned magic number)"
  mypy: "poetry run mypy itrader — Success: no issues found in 161 source files (strict)"
  full_suite: "poetry run pytest -q — 825 passed"
---

# 03-04: Close Phase 3 — W1-12 MACD reorder + doc corrections + phase gate

## What was built

**Task 1 (W1-12, checkpoint:human-verify non-blocking, D-02 oracle-only):**
Moved the MACD computation in `SMA_MACD_strategy.py` from its unconditional pre-guard
position into the `if short_sma.iloc[-1] >= long_sma.iloc[-1]:` SMA filter guard, so MACD
is only computed on ticks where the SMA condition holds. `MACDhist` remains in scope for
both the buy trigger and the exit `elif` (both live inside the guard). The firing tick is
byte-identical — only control-flow placement changed, the MACD value used on a firing tick
is the same value as before, computed lazily. A WHY comment cites W1-12 / D-02. TAB
indentation preserved (no 4-space lines introduced). **No SMA_MACD test was added or
modified** (D-02).

**Task 2 (auto — doc truth-corrections):**
- **ROADMAP §Phase 3 SC-1** — dropped the trailing `*_snapshot()` variant clause (D-04
  declined that variant); appended a one-line D-04 note that a query-based live backend is
  copy-safe for free.
- **ROADMAP §Phase 3 SC-2** — removed "active-portfolio recompute," from the duplicated-work
  parenthetical (D-10 descoped W1-13); kept the other four items.
- **REQUIREMENTS PERF-01** — dropped the same stale `*_snapshot()` variant clause (D-04).
- **REQUIREMENTS PERF-02** — removed "active-portfolio recompute," from the description,
  dropped `W1-13` from the `[...]` traceability tag, and annotated "(W1-13 descoped — D-10)"
  so traceability stays explicit (not silently deleted).
- Grep gate clean: `grep -n "snapshot() variant\|active-portfolio recompute"` over both files
  returns nothing.

**Task 3 (phase gate, checkpoint:human-verify blocking — cross-cutting correctness net):**
Ran the full Phase-3 gate on the merged result of all four plans:

| Check | Command | Result |
|-------|---------|--------|
| Byte-exact oracle | `pytest tests/integration/test_backtest_oracle.py` | 3 passed — **134 trades / final_equity 46189.87730727451** EXACT |
| Full e2e suite | `pytest tests/e2e` | **58 passed** |
| `mypy --strict` | `poetry run mypy itrader` | clean — **161 source files** |
| Full unit+integration | `poetry run pytest -q` | **825 passed** |

The byte-exact oracle is the sole numeric proof of W1-12 (D-02) — it held exactly, proving
the MACD reorder produced no result drift.

## Deviations

None. The W1-12 reorder, three documentation edits, and the phase gate all landed as planned.
W1-13 remained descoped (D-10). No new SMA_MACD test was introduced (D-02).

## Self-Check: PASSED
