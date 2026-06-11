---
phase: 03-hot-path-performance
plan: 01
subsystem: portfolio_handler
tags: [performance, storage-seam, metrics, behavior-preserving, decimal]
requirements_completed: [PERF-01]
dependency_graph:
  requires:
    - "PortfolioStateStorage seam (M2-08): ABC + InMemory backend + factory"
    - "D-19 single-writer contract (M4-05): the precondition that makes copy-drop safe"
  provides:
    - "Copy-free InMemoryPortfolioStateStorage getters (5 getters return the live container)"
    - "snapshot_count() / get_latest_snapshot() count-only/last-only accessors on the ABC + InMemory backend"
    - "metrics_manager per-tick trim/last/empty path consuming the accessors (no whole-list copy)"
    - "Object-identity + accessor-behavior + consumer no-call regression locks (D-01)"
  affects:
    - "Any future query-based live/Postgres PortfolioStateStorage backend (copy-safe for free; D-04)"
    - "Phase 03 Plans 02-04 (sibling hot-path perf waves)"
tech_stack:
  added: []
  patterns:
    - "Read-only-view storage contract: getter returns the live internal container under single-writer (D-03/D-19)"
    - "Count-only / last-only storage accessors avoid whole-list copies on the per-tick read path (D-06)"
    - "Object-identity behavioral assert (`get_X() is get_X()`) proves a copy-drop landed — no wall-clock benchmark (D-01)"
    - "Consumer-side no-call regression lock (monkeypatch get_snapshots to raise) proves the per-tick path consumes accessors (D-06)"
key_files:
  created: []
  modified:
    - "itrader/portfolio_handler/storage/in_memory_storage.py"
    - "itrader/portfolio_handler/base.py"
    - "itrader/portfolio_handler/metrics/metrics_manager.py"
    - "tests/unit/portfolio/test_state_storage.py"
    - "tests/unit/portfolio/test_metrics_manager.py"
decisions:
  - "D-03: drop the defensive .copy() from all 5 InMemory getters — safe under D-19 single-writer; the copy never protected correctness, only added per-tick cost"
  - "D-04: NO *_snapshot() copy-returning twin added — a query-based live/Postgres backend is copy-safe for free, so the hedge is speculative API for deferred work (bounded gap-discovery delta, recorded below, not silently folded)"
  - "D-05: test caller-audit complete — no mutate-then-assert-storage test exists in tests/unit/portfolio/; nothing migrated"
  - "D-06: per-tick trim/last/empty path consumes snapshot_count()/get_latest_snapshot() instead of get_snapshots(); the never-firing trim no longer pays the whole-list copy"
metrics:
  tasks_completed: 2
  files_modified: 5
  completed_date: 2026-06-11
---

# Phase 3 Plan 01: Copy-Free Portfolio Read Seam + Snapshot Accessors Summary

Dropped the per-tick `.copy()` from all five `InMemoryPortfolioStateStorage` getters under
the D-19 single-writer contract, added `snapshot_count()` / `get_latest_snapshot()`
count-only/last-only accessors, rewired the `MetricsManager` per-tick snapshot path to consume
them, and locked every optimization with deterministic behavioral asserts (object-identity +
accessor-behavior + consumer no-call) — byte-exact against the golden oracle.

## What Was Built

**Task 1 — copy-drop + accessors + ABC rewrite (commit `8ccc7ed`):**
- All 5 getters (`get_positions`, `get_closed_positions`, `get_transaction_history`,
  `get_cash_operations`, `get_snapshots`) now `return self._X` (the live container) instead of
  `return self._X.copy()` (D-03/D-19).
- Added `snapshot_count() -> int` and `get_latest_snapshot() -> Optional[Any]` to the InMemory
  backend (count-only / last-only, no `.copy()`).
- Rewrote the 5 ABC getter docstrings to the D-03 read-only-view contract ("Return a read-only
  view of ... callers MUST NOT mutate — D-19 single-writer; copy yourself if you need ownership")
  and added the two new `@abstractmethod`s after `set_snapshots`, citing D-03/D-06/D-19.
- Added 5 object-identity regression locks (`get_X() is get_X()`) + a `snapshot_count`/
  `get_latest_snapshot` accessor-behavior test (empty + two-element states) in
  `test_state_storage.py` — all GREEN against the landed change (no wall-clock benchmark, D-01).

**Task 2 — metrics_manager rewire + consumer no-call lock (commit `d6bf9df`):**
- `record_snapshot` trim guard: `if self._storage.snapshot_count() > self.max_snapshots:`
  (count-only; the trim still never fires on the golden run, but no longer copies the whole list).
- `get_current_metrics`: empty-guard → `snapshot_count() == 0`; latest-read →
  `get_latest_snapshot()` (with an `assert ... is not None` invariant note to narrow the ABC's
  `Optional` for mypy strict).
- Added the GREEN consumer-side regression lock `test_trim_uses_snapshot_accessors` in
  `test_metrics_manager.py`: monkeypatches the storage's `get_snapshots` to raise, drives both
  per-tick paths, and asserts they complete without calling `get_snapshots()` while
  `snapshot_count()`/`get_latest_snapshot()` ARE exercised and the never-firing trim does not fire
  (no `set_snapshots`).

## Verification

- `pytest tests/unit/portfolio/` — **186 passed** (incl. 6 new state-storage tests + the new
  consumer no-call lock).
- `pytest tests/integration` — **12 passed**, byte-exact oracle held:
  `test_trade_log_identical_to_golden` green (134 trades / `final_equity 46189.87730727451`).
- `mypy itrader` (strict) — **Success: no issues found in 139 source files.**
- No `.copy()` remains on any getter return in `in_memory_storage.py`; no `*_snapshot()`
  copy-returning twin exists (D-04 honored).

## Scope Boundary Note (per-tick vs analytics get_snapshots)

The rewire targeted ONLY the per-tick trim/last/empty path (the three sites the plan named:
trim 171-173, empty-guard 189, last-read 193). `get_snapshots()` is still called — correctly —
in the on-demand analytics methods (`calculate_performance_metrics`, `get_drawdown_analysis`,
`get_return_distribution`, the public `get_snapshots`, `_get_period_start_date` ALL_TIME,
`_get_snapshots_for_period`), which legitimately iterate the whole history and are not on the
per-tick hot path. These were out of scope for PERF-01 and were left unchanged.

## D-04 Bounded Gap-Discovery Delta (owner-flagged, NOT silently folded)

**No `*_snapshot()` copy-returning twin was added.** The plan (D-04) declined a speculative
copy-returning twin as a hedge for the deferred live/Postgres backend. Rationale: a query-based
live/Postgres `PortfolioStateStorage` backend is **copy-safe for free** — each query materializes
a fresh result set, so there is no shared mutable container to defend. Adding a copy-returning
twin now would be pre-building API for deferred work, violating the "no pre-building for deferred
work" discipline. This is recorded here as a bounded, owner-flagged delta rather than folded into
the running phase.

## D-05 Test Caller-Audit Result

**No mutate-then-assert-storage test found.** Grepped `tests/unit/portfolio/` for any test that
mutates a getter result (`.append` / `.pop` / `[k]=`) and then asserts storage was unchanged —
none exists. Every getter-result usage in the portfolio test tree is read-only (`len()`, `==`,
`in`, indexing `[0]`/`[-1]`, iteration). The existing round-trip tests only `==`/`is`-compare and
are safe under the copy-drop. **Nothing migrated.**

## Deviations from Plan

**1. [Rule 3 - Blocking] `get_latest_snapshot()` Optional return tripped mypy union-attr**
- **Found during:** Task 2 (after rewiring `get_current_metrics`).
- **Issue:** The ABC declares `get_latest_snapshot() -> Optional[Any]`; the previous code
  `get_snapshots()[-1]` returned `Any`. mypy strict flagged `latest_snapshot.portfolio_return` /
  `.open_positions_count` as union-attr errors on the `None` arm.
- **Fix:** Added `assert latest_snapshot is not None` (with an invariant comment) immediately
  after the call — the empty-guard above guarantees at least one snapshot, so the assert is a
  type-narrowing no-op at runtime, not a behavior change.
- **Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`
- **Commit:** `d6bf9df`

## Known Stubs

None.

## Threat Flags

None — backtest-only, behavior-preserving internal refactor of the in-process portfolio read
seam. No new network endpoints, auth paths, file access, schema changes, or dependencies. The
threat register's only `mitigate` disposition (T-03-01, silent state corruption from dropping the
copy) is satisfied: D-19 single-writer is the precondition, the byte-exact oracle is the integrity
net, and the D-05 caller+test audit confirms no caller mutates a returned container.

## Self-Check: PASSED

- `03-01-SUMMARY.md` — FOUND
- Commit `8ccc7ed` (Task 1) — FOUND
- Commit `d6bf9df` (Task 2) — FOUND
- Commit `df568f6` (SUMMARY) — FOUND
