---
phase: 07-per-bar-metrics-timestamp-polish
plan: 02
subsystem: portfolio_handler (metrics + state storage)
tags: [perf, hot-path, deque, cache-removal, determinism, byte-exact]
requires:
  - "07-01 (D-01 _aligned memoization) — independent; both in Wave 1"
provides:
  - "Bounded deque(maxlen) snapshot retention with max_snapshots plumbed through InMemoryPortfolioStateStorage.__init__"
  - "Per-bar trim-block, debug-log, and metrics-cache layer removed from MetricsManager (D-02/D-03/D-04)"
  - "Five breaking tests fixed + T4/T5/T7 behavior-preservation tests added; strict suite green"
affects:
  - "itrader/portfolio_handler/storage/in_memory_storage.py"
  - "itrader/portfolio_handler/metrics/metrics_manager.py"
  - "itrader/portfolio_handler/base.py"
tech-stack:
  added:
    - "collections.deque(maxlen=N) — stdlib bounded snapshot retention (replaces list + slice-trim)"
  patterns:
    - "Bounded-memory primitive (deque maxlen) — the spine of D-03; auto-evicts O(1)"
    - "Surgical deletion of memoization/logging/trimming layers; calculation logic untouched"
    - "Audit-the-invariant + dedicated equivalence/regression test (no hot-path runtime guard)"
key-files:
  created: []
  modified:
    - "itrader/portfolio_handler/storage/in_memory_storage.py"
    - "itrader/portfolio_handler/metrics/metrics_manager.py"
    - "itrader/portfolio_handler/base.py"
    - "tests/unit/portfolio/test_state_storage.py"
    - "tests/unit/portfolio/test_metrics_manager.py"
decisions:
  - "D-02: per-bar logger.debug snapshot log removed (duplicated stored data; paid per-bar isoformat()/str())"
  - "D-03: snapshot retention -> deque(maxlen); get_snapshots() returns list() copy; per-bar trim block deleted"
  - "D-04: in-memory metrics cache (fields/read/populate/_is_cache_valid/cache_duration_minutes + wall-clock TTL) removed; recompute-on-call"
metrics:
  duration: "~25 min"
  tasks: 3
  files-changed: 5
  completed: 2026-06-25
---

# Phase 7 Plan 02: Per-Bar Metrics & Snapshot-Retention Hot-Path Deletions Summary

Three converging metrics/storage hot-path deletions (D-02 debug-log, D-03 snapshot-retention deque,
D-04 metrics-cache) landed with ZERO change to engine numbers; the bounded `deque(maxlen)` replaces a
latent-O(n²) per-bar slice-trim, and all five breaking tests are fixed plus three behavior-preservation
tests added — the strict suite stays green and `mypy --strict` is clean.

## What Was Built

### Task 1 — Snapshot retention -> bounded deque (D-03 storage side) [5abb4d7]
- `InMemoryPortfolioStateStorage.__init__` gained `max_snapshots: int = 10000`; `self._snapshots` is now
  `deque(maxlen=max_snapshots)` (O(1) append + automatic oldest-eviction) and `self._max_snapshots` is
  stored for the `set_snapshots` rebuild.
- `get_snapshots()` returns `list(self._snapshots)` — the ONE accessor that copies (diverges from the
  four sibling "return the live container" accessors), per the D-03 mutation-during-iteration /
  `List[Any]`-sliceability rationale.
- `set_snapshots()` rebuilds `deque(snapshots, maxlen=self._max_snapshots)` (Pitfall 2 — a plain-list
  reassignment silently drops `maxlen`).
- `add_snapshot` / `snapshot_count` / `get_latest_snapshot` bodies unchanged (all O(1) on a deque).
- `base.py` ABC docstrings for `get_snapshots`/`set_snapshots` updated (signatures + `-> List[Any]`
  return type unchanged; the other four accessor docstrings untouched).
- `storage_factory.py` left unchanged — both `InMemoryPortfolioStateStorage()` construction sites rely
  on the new `max_snapshots=10000` default, which matches `MetricsManager.max_snapshots` byte-for-byte.

### Task 2 — Delete trim block, debug log, metrics-cache layer (D-02/D-03/D-04) [47247b6]
- **D-02:** deleted the per-bar `logger.debug("Portfolio snapshot recorded", ...)` call — the snapshot
  already stores the raw Timestamp + total_equity/total_pnl, so the log duplicated stored data and only
  paid the per-bar `isoformat()` + two `str()`.
- **D-03:** deleted the per-bar trim block (`snapshot_count() > max_snapshots` + the slice-copy
  `set_snapshots(get_snapshots()[-N:])`) — the deque `maxlen` IS the trim now. Kept `max_snapshots`
  (feeds the deque plumbing) and the two `snapshot_count() == 0` empty-guards.
- **D-04:** removed `_metrics_cache`/`_cache_timestamp` fields, `cache_duration_minutes`, the
  `cache_duration` logger kwarg, the per-bar `.clear()` churn, the cache read/populate sites, and the
  entire `_is_cache_valid` method (killing its wall-clock `datetime.now()` TTL). `calculate_performance_metrics`
  now recomputes from the snapshot history each call (zero per-bar callers, so recompute-on-call is free).
- `from datetime import datetime, timedelta` kept (still used by type hints + timedelta math). No
  non-comment `datetime.now()` survives.

### Task 3 — Fix five breaking tests + add T4/T5/T7 [f576006]
- **T4** (`test_get_snapshots_returns_value_equal_copy`, was `*_returns_live_container_no_copy`): flipped
  the object-identity assert to value-equality + an intentional `is not` copy assert.
- **T5** (`test_snapshots_bounded_deque_retains_last_n`): new last-N retention test in test_state_storage.py.
- **`test_metrics_manager_initialization`**: dropped the `cache_duration_minutes == 5` assertion.
- **`test_snapshot_history_limit`** (the 5th breaking test): rewritten to bound the deque at CONSTRUCTION
  (`InMemoryPortfolioStateStorage(max_snapshots=5)` attached as `portfolio.state_storage`) — under D-03,
  `maxlen` is fixed at construction and post-hoc `mm.max_snapshots` mutation no longer re-bounds the live deque.
- **`test_performance_metrics_recompute_stable`** (was `test_performance_metrics_caching`): dropped the
  `len(mm._metrics_cache) == 1` assert; kept recompute determinism.
- **T7** (`test_metrics_cache_removed_recompute_reflects_new_snapshots`, was `test_metrics_cache_invalidation`):
  `not hasattr` on all four removed cache attrs + recompute-stable + recompute-reflects-new-snapshot assertions.
- **T6** (`test_trim_uses_snapshot_accessors`): stayed GREEN unchanged (trim deleted -> `set_snapshots`
  never called on the per-tick path; the `_boom` sentinel on `get_snapshots` never fires).

## Verification Evidence

- Task 1 inline check: `get_snapshots()==[2,3,4]`, count==3, latest==4, fresh object per call -> `OK`.
- Task 2: non-comment lines have NO `_metrics_cache`/`_cache_timestamp`/`_is_cache_valid`/`cache_duration_minutes`/`datetime.now`;
  trim gone; both `snapshot_count()==0` empty-guards retained; module imports clean.
- Task 3: `pytest tests/unit/portfolio/test_state_storage.py tests/unit/portfolio/test_metrics_manager.py -x -q` -> **50 passed**.
- Full portfolio suite: `pytest tests/unit/portfolio/ -q` -> **276 passed** (strict config, filterwarnings=error).
- `mypy --strict` on the three edited engine modules -> **Success: no issues found in 3 source files**.
- `git diff --check` clean on all edited files (no tab/space mix).

Tests were run with the main-checkout venv (`/Users/.../intelli-trader/.venv/bin/python`) and
`PYTHONPATH="$PWD"` prepended — the worktree `.venv` has no deps installed, and PYTHONPATH shadows the
editable install so worktree edits are exercised (per project memory note). Module-load confirmed to
resolve to the worktree path. `make test` was intentionally NOT used in the worktree (it aborts on
missing .env and disables logs).

## Deviations from Plan

### Indentation note
The plan's interfaces block stated `base.py` is TABS. The class-method docstrings actually edited
(`get_snapshots`/`set_snapshots` at the ABC accessor level) use **4 SPACES** (the tabs in base.py are at
the module-import level, a different block). I matched the actual per-line whitespace (4 spaces) of the
edited lines; `git diff --check` is clean. No normalization performed.

### storage_factory.py — listed in `files_modified` but intentionally unchanged
The plan's `files_modified` frontmatter listed `storage_factory.py`, but Task 1's action explicitly says
to leave both construction sites as-is (they rely on the new `max_snapshots=10000` default). Confirmed by
read; no code change needed. This is the planned outcome, not a deviation in behavior.

No auto-fixes (Rules 1-3) were required — the plan's verified line numbers and exact-target guidance held.

## Known Stubs

None. No placeholder/empty-data patterns introduced; all changes are deletions of memoization/logging/
trimming plumbing with the calculation logic intact.

## Out-of-Scope (verified in Wave 2 / Plan 03)
- Gate (a) oracle byte-exactness (134 trades / `46189.87730727451`) + the full strict suite + a
  determinism double-run are verified in Plan 03 (Wave 2). This plan touched only timestamp/metrics/
  reporting surfaces — no money/position/order/fill code — so the byte-exact oracle is expected to hold.
- Gate (b) W1 re-profile + clean-benchmark re-freeze (thermal-aware) is Plan 03 / the phase exit.
