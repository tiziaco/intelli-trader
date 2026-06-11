---
phase: 03-hot-path-performance
plan: 03
subsystem: portfolio
tags: [decimal, hot-path, performance, on_fill, simulated-exchange, csv-store]

# Dependency graph
requires:
  - phase: 03-hot-path-performance (Plan 01)
    provides: D-03 read-only-view contract (getters return the live container) — intra-wave ordering, Plan 01 → Plan 03
provides:
  - "PERF-02 micro-redundancy removals: W1-08 (no-op Decimal re-wraps), W1-03 (cached open_position_count), W1-14 (one authoritative is_connected check), W1-07 (on_fill non-EXECUTED guard hoisted above correlation-id allocation), W1-09 (load-time copy drop)"
  - "W1-07 behavioral pin: non-EXECUTED fills skip _operation_context; EXECUTED still enters it"
affects: [03-04-PLAN, order-manager-decomposition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Guard-before-resource-allocation: hoist a no-op early-return above the operation-context/correlation-id allocation it would otherwise waste"

key-files:
  created: []
  modified:
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/price_handler/store/csv_store.py
    - itrader/order_handler/order_manager.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/portfolio_handler/portfolio_handler.py
    - tests/unit/portfolio/test_on_fill_status_guard.py

key-decisions:
  - "W1-13 (get_active_portfolios per-tick cache) NOT implemented — DESCOPED (D-10): zero payoff on the single-portfolio golden run + an oracle-blind invalidation-correctness risk across ACTIVE/INACTIVE/ARCHIVED"
  - "W1-14: validate_order() is the ONE authoritative is_connected() check; the duplicate _admit_order guard was unreachable (validation already exits REFUSED on disconnect) — removed without semantic change"
  - "csv_store W1-09 .copy() drop verified warning-free under pandas 2.3.3 CoW (.columns relabel is metadata-only, no SettingWithCopyWarning under filterwarnings=error)"

patterns-established:
  - "Pattern 1: cache a repeated read-model call (open_position_count) into a local before a guard that reuses it in both the comparison and the rejection message"
  - "Pattern 2: hoist a pure no-op early-return above resource allocation it would otherwise waste (W1-07)"

requirements-completed: [PERF-02]

# Metrics
duration: ~20min
completed: 2026-06-11
---

# Phase 03 Plan 03: PERF-02 Hot-Path Micro-Redundancy Removal Summary

**Five mechanical per-tick micro-redundancy removals (W1-08/W1-03/W1-14/W1-07/W1-09), each in its owning domain, with the on_fill non-EXECUTED guard hoisted above correlation-id allocation — golden master byte-exact (134 trades / 46189.87730727451).**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-11
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- **W1-08** — dropped the four no-op `Decimal(str(Decimal))` re-wraps on the three `get_total_*` mark-to-market/equity aggregations in `position_manager.py` (`market_value`/`unrealised_pnl`/`realised_pnl` are already `-> Decimal` at source; values stay Decimal, mypy-enforced).
- **W1-09** — dropped the redundant load-time `raw[expected_cols].copy()` in `csv_store.py` (the subsequent `.columns =` relabel + `.set_index`/`.astype` build a fresh frame; verified warning-free under pandas 2.3.3 CoW).
- **W1-03** — cached `open_position_count(portfolio_id)` once into a local in `order_manager.py`, reused in both the max-positions guard comparison and the rejection f-string (was called ×2 in the same branch).
- **W1-14** — removed the redundant `_admit_order` `is_connected()` check in `simulated.py`; `validate_order()` is the one authoritative connection check, so a disconnected exchange already exits REFUSED there. Fill path byte-identical.
- **W1-07** — hoisted the `on_fill` non-EXECUTED `return` guard ABOVE the `_operation_context`/correlation-id allocation in `portfolio_handler.py`; non-EXECUTED fills now skip the context entirely while the EXECUTED path is unchanged. Added two tests pinning this observable side-effect.

## Task Commits

Each task was committed atomically:

1. **Task 1: W1-08 Decimal re-wrap drop + W1-09 load-time copy drop** - `5d7d422` (perf)
2. **Task 2: W1-03 open_position_count local-cache + W1-14 redundant is_connected removal** - `359946f` (perf)
3. **Task 3: W1-07 on_fill non-EXECUTED guard hoist + guard test extension** - `a4e30ba` (perf)

## Files Created/Modified
- `itrader/portfolio_handler/position/position_manager.py` - W1-08: three `get_total_*` aggregations sum `position.market_value`/`.unrealised_pnl`/`.realised_pnl` directly (no Decimal re-wrap)
- `itrader/price_handler/store/csv_store.py` - W1-09: `data = raw[expected_cols]` (no `.copy()`) on the load path
- `itrader/order_handler/order_manager.py` - W1-03: `open_count` local cached once before the max-positions guard
- `itrader/execution_handler/exchanges/simulated.py` - W1-14: redundant `_admit_order` `is_connected()` check removed; one authoritative check remains in `validate_order()`
- `itrader/portfolio_handler/portfolio_handler.py` - W1-07: non-EXECUTED guard hoisted above `_operation_context`
- `tests/unit/portfolio/test_on_fill_status_guard.py` - two new tests pinning the W1-07 hoist (non-EXECUTED skips `_operation_context`, EXECUTED enters it)

## Decisions Made
- **W1-13 NOT implemented (D-10 descope).** The `get_active_portfolios()` per-tick cache was explicitly NOT built — zero payoff on the single-portfolio golden run plus an oracle-blind invalidation-correctness risk across the ACTIVE/INACTIVE/ARCHIVED state machine. (Stale PERF-02/ROADMAP wording is corrected in Plan 04.)
- **W1-07 hoist left the FRAGILE reservation-release zone untouched.** The hoist edits only the non-EXECUTED early-return in `portfolio_handler.on_fill`; the `order_manager.py` fill-reconciliation / reservation-release / `should_release` / `finally`-release interplay was not modified.
- **W1-14 authoritative check.** `validate_order()` already appends "Exchange not connected" → NETWORK_ERROR and `_admit_order` exits REFUSED on its `is_valid` branch, so the duplicate guard was unreachable; removing it changes no observable behavior (the `test_order_admission_requires_connection` REFUSED + `_last_error` assertion stays green).

## Deviations from Plan

None - plan executed exactly as written.

The plan's approximate line references for `simulated.py` (122/127-135/343/400) resolved to the two actual `is_connected()` call sites in the current file (the `_admit_order` duplicate at ~133 and the authoritative one inside `validate_order` at ~403); the W1-14 intent was applied to those, not to literal line numbers.

## Issues Encountered
- Edits initially targeted the shared-checkout path (Read auto-resolves there); re-targeted to the worktree copy. No code impact.
- Pre-checked the `csv_store.py` `.copy()` drop against `filterwarnings=["error"]` by reproducing the load-path transform — confirmed no `SettingWithCopyWarning` under pandas 2.3.3 CoW before committing.

## Verification
- `pytest tests/unit/portfolio/ tests/unit/order/ tests/unit/execution/ tests/unit/price/test_csv_store.py` — 466 passed
- `mypy itrader` — strict-clean (139 source files)
- `pytest tests/integration -m integration` — 12 passed; oracle byte-exact (`test_trade_log_identical_to_golden`): 134 trades / final_equity 46189.87730727451

## Next Phase Readiness
- PERF-02 micro-redundancies removed; per-tick path byte-identical. Ready for Plan 04 (PERF-03 / stale-wording correction).
- No blockers. FRAGILE zone untouched (deferred to Phase 6 / MOD-01).

## Self-Check: PASSED
- All 6 modified files exist in the worktree.
- Task commits `5d7d422`, `359946f`, `a4e30ba` present in `git log`.

---
*Phase: 03-hot-path-performance*
*Completed: 2026-06-11*
