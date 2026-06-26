---
phase: 07-per-bar-metrics-timestamp-polish
verified: 2026-06-25T00:00:00Z
status: passed
score: 8/8
overrides_applied: 0
---

# Phase 7: Per-Bar Metrics & Timestamp Polish — Verification Report

**Phase Goal:** Memoize per-bar timestamp alignment (D-01) and land three metrics/storage
hot-path deletions (D-02 eager debug-log args, D-03 bounded deque snapshot retention, D-04
inert metrics-cache + wall-clock TTL) — zero engine numbers changed, Gate (a) byte-exact,
Gate (b) measurable W1 CPU reclaim + baseline re-frozen.

**Verified:** 2026-06-25
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `_aligned` is memoized via `@functools.lru_cache(maxsize=32)`; import functools present; body byte-unchanged (D-01) | VERIFIED | `grep -n "functools.lru_cache(maxsize=32)\|import functools\|def _aligned"` in `time_parser.py` confirms all three. Decorator at line 139, import at line 2, body at 140–170 intact. |
| 2 | `_aligned` memo is bounded: `cache_info().maxsize == 32`; T1/T2/T3 unit tests green | VERIFIED | `tests/unit/outils/test_time_parser.py` contains T1 (`test_aligned_equivalence_sampled_grid`), T2 (`test_aligned_memo_active_and_bounded`), T3 (`test_aligned_memo_bounded_currsize`); all 26 tests in the file pass. |
| 3 | Snapshot retention uses `deque(maxlen=max_snapshots)`; per-bar trim block is gone (D-03) | VERIFIED | `in_memory_storage.py` imports `from collections import deque`; `__init__` has `max_snapshots: int = 10000` param; `_snapshots` is `deque(maxlen=max_snapshots)`; `set_snapshots` rebuilds `deque(snapshots, maxlen=self._max_snapshots)`. No trim block pattern found in `metrics_manager.py`. |
| 4 | `get_snapshots()` returns a materialized list copy; value and order identical to pre-deque behavior | VERIFIED | `get_snapshots()` returns `list(self._snapshots)`. T4 (`test_get_snapshots_returns_value_equal_copy`) and T5 (`test_snapshots_bounded_deque_retains_last_n`) pass in `test_state_storage.py`. |
| 5 | Per-bar debug log eager arg construction is gone; no `isoformat()`/`str()` per-bar call (D-02) | VERIFIED | `grep "Portfolio snapshot recorded"` in non-comment lines of `metrics_manager.py` returns nothing. |
| 6 | Metrics cache (`_metrics_cache`, `_cache_timestamp`, `_is_cache_valid`, `cache_duration_minutes`, `datetime.now()`) fully removed (D-04) | VERIFIED | Python scan of non-comment lines in `metrics_manager.py` finds none of those identifiers. `calculate_performance_metrics` recomputes on each call; T7 (`test_metrics_cache_removed_recompute_reflects_new_snapshots`) asserts `not hasattr` on all four removed attrs. |
| 7 | Gate (a): SMA_MACD oracle byte-exact (134 trades / `final_equity 46189.87730727451`); full suite green (1295 passed); `mypy --strict` clean; determinism double-run byte-identical | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` → 3 passed. `make typecheck` → "Success: no issues found in 188 source files". SUMMARY.md records 1295 passed + double-run determinism. |
| 8 | Gate (b): four hotspots materially reduced in Scalene re-profile; same-machine A/B −25.7% W1 win; W1-BASELINE.json re-frozen to 19.6s / 162.2 MB with `green_at_freeze: true` | VERIFIED | `perf/results/W1-BASELINE.json` reads `wall_clock_s: 19.6`, `peak_mem_mb: 162.2`, `green_at_freeze: true`, `final_equity: 46189.87730727451`, `trade_count: 134`. 07-03-SUMMARY.md records interleaved A/B (PRE ~33.76s → POST ~25.07s = −25.7%) and Scalene delta (−21 CPU pts across all four hotspots). |

**Score:** 8/8 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/outils/time_parser.py` | `@functools.lru_cache(maxsize=32)` decorator + `import functools`; body byte-unchanged | VERIFIED | Decorator at line 139; import at line 2; 4-line body + docstring intact |
| `tests/unit/outils/test_time_parser.py` | T1/T2/T3 tests asserting equivalence, memo activity, bounded currsize | VERIFIED | Tests present at lines 243, 252, 264; 26 tests pass |
| `itrader/portfolio_handler/storage/in_memory_storage.py` | `deque(maxlen=max_snapshots)`-backed `_snapshots`; `get_snapshots()` returns `list()`; `set_snapshots()` rebuilds bounded deque | VERIFIED | All patterns confirmed via grep; `max_snapshots=10000` default plumbed |
| `itrader/portfolio_handler/metrics/metrics_manager.py` | trim block, debug log, metrics-cache layer all removed; `calculate_performance_metrics` recomputes | VERIFIED | No `_metrics_cache`, `_cache_timestamp`, `_is_cache_valid`, `cache_duration_minutes`, `datetime.now()`, or `"Portfolio snapshot recorded"` in non-comment lines |
| `tests/unit/portfolio/test_state_storage.py` | T4 value-equality + T5 last-N retention tests | VERIFIED | `test_get_snapshots_returns_value_equal_copy` and `test_snapshots_bounded_deque_retains_last_n` present |
| `tests/unit/portfolio/test_metrics_manager.py` | T7 `not hasattr` assertions + recompute-stable test; all 5 breaking tests fixed | VERIFIED | `test_metrics_cache_removed_recompute_reflects_new_snapshots` has all four `not hasattr` checks; 50 tests pass |
| `perf/results/W1-BASELINE.json` | Re-frozen: `wall_clock_s: 19.6`, `green_at_freeze: true`, trade_count 134, equity `46189.87730727451` | VERIFIED | Confirmed by direct JSON read |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `time_parser.py::check_timeframe` | `time_parser.py::_aligned` | `return _aligned(time, timeframe)` | VERIFIED | Single caller confirmed; decorator wired to the actual function |
| `_aligned` | `@functools.lru_cache(maxsize=32)` | module-level decorator | VERIFIED | `_aligned.cache_info().maxsize == 32` confirmed by T2 test |
| `in_memory_storage.py::set_snapshots` | `deque(snapshots, maxlen=self._max_snapshots)` | Pitfall-2-safe rebuild | VERIFIED | Line 142 confirmed |
| `metrics_manager.py::record_snapshot` | No per-bar trim / debug log / cache clear | All three deletion paths confirmed absent | VERIFIED | Only `add_snapshot` remains in the per-bar path |
| Plans 01+02 changes | `tests/integration/test_backtest_oracle.py` | byte-exact oracle gate | VERIFIED | Oracle runs 3/3 passed; value `46189.87730727451` / 134 trades |

---

## Data-Flow Trace (Level 4)

Not applicable. Phase modifies only timestamp/metrics/storage surfaces — no rendering or user-visible output paths. The oracle integration test is the data-flow validator.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `_aligned` memo wired (maxsize=32) | `poetry run python -c "from itrader.outils.time_parser import _aligned; print(_aligned.cache_info().maxsize)"` | 32 | PASS |
| Oracle byte-exact (Gate a) | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` | 3 passed | PASS |
| `mypy --strict` clean | `make typecheck` | Success: 188 source files | PASS |
| Portfolio+outils unit tests | `poetry run pytest tests/unit/portfolio/test_state_storage.py tests/unit/portfolio/test_metrics_manager.py tests/unit/outils/test_time_parser.py -x -q` | 76 passed | PASS |
| Metrics cache attributes absent | non-comment scan of `metrics_manager.py` | 0 occurrences of all 5 removed identifiers | PASS |
| W1-BASELINE.json re-frozen | `cat perf/results/W1-BASELINE.json` | `wall_clock_s: 19.6`, `green_at_freeze: true` | PASS |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | — | — | No TBD/FIXME/XXX markers, no stubs, no hardcoded empties, no return null patterns found in modified files |

Scanned: `itrader/outils/time_parser.py`, `itrader/portfolio_handler/storage/in_memory_storage.py`, `itrader/portfolio_handler/metrics/metrics_manager.py`. All modifications are surgical deletions and a bounded decorator — no placeholder code.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PERF-07 (D-01) | 07-01 | `_aligned` bounded memoization | SATISFIED | `@functools.lru_cache(maxsize=32)` present; T1/T2/T3 green |
| PERF-07 (D-02) | 07-02 | Per-bar debug-log eager arg removal | SATISFIED | `"Portfolio snapshot recorded"` not in non-comment lines |
| PERF-07 (D-03) | 07-02 | Snapshot retention → bounded deque; trim removed | SATISFIED | `deque(maxlen=max_snapshots)` in storage; trim block absent |
| PERF-07 (D-04) | 07-02 | Metrics-cache churn + wall-clock TTL removed | SATISFIED | All five removed identifiers absent; T7 `not hasattr` asserts hold |
| PERF-07 Gate (a) | 07-03 | Oracle byte-exact + suite green + mypy clean + determinism | SATISFIED | Oracle 3/3, 1295 suite, mypy 188 files clean |
| PERF-07 Gate (b) | 07-03 | Measurable W1 win + re-freeze | SATISFIED | −25.7% A/B, −21 CPU pts Scalene; W1-BASELINE.json 19.6s |

---

## Human Verification Required

None. Both gates are fully verifiable programmatically and the Gate (b) human checkpoint (machine temperature / re-freeze approval) was resolved during execution (documented in 07-03-SUMMARY.md as "machine verified cool, re-freeze approved").

---

## Gaps Summary

No gaps. All 8 must-have truths verified against the codebase.

---

_Verified: 2026-06-25_
_Verifier: Claude (gsd-verifier)_
