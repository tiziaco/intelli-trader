---
phase: 07-per-bar-metrics-timestamp-polish
reviewed: 2026-06-25T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - itrader/outils/time_parser.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/metrics/metrics_manager.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - tests/unit/outils/test_time_parser.py
  - tests/unit/portfolio/test_metrics_manager.py
  - tests/unit/portfolio/test_state_storage.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-06-25T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Phase 7 (PERF-07) is a byte-exact performance polish across four production files plus
three test files. Three changes were verified against the phase-specific correctness
concerns:

1. **`_aligned` lru_cache (07-01).** The memoization is **SOUND**. The function body is
   byte-identical to the base commit (`git show 59b9287:itrader/outils/time_parser.py`
   confirms only the `@functools.lru_cache(maxsize=32)` decorator was added). The cache
   key `(ts, tf)` is `(datetime, timedelta)` — both hashable and immutable. The function
   is pure: no mutable defaults, no wall-clock read (`ts` is `event.time`, a business
   datetime), no hidden state. A bounded `maxsize=32` cannot return a stale/wrong result
   because the function is a pure function of its key — identical keys always yield
   identical booleans, and distinct keys never collide. No correctness risk to
   bar alignment.

2. **Metrics/storage deletions (07-02, D-02/D-03/D-04).** The per-bar debug log, the
   inert metrics-cache layer (`_metrics_cache`/`_cache_timestamp`/`_is_cache_valid`/
   `cache_duration_minutes`), and the per-bar slice-trim were removed; snapshot retention
   moved to `deque(maxlen=max_snapshots)`. Verified: no surviving production reference to
   any removed attribute (grep clean), all locals in `record_snapshot` are still consumed
   by the `PortfolioSnapshot` construction (no orphaned variables), and the deque-maxlen
   retention is numerically equivalent to the old `[-max_snapshots:]` trim (both retain
   the last N, both evict the oldest). The golden run is **3076 daily bars < 10000**
   bound, so the deque never evicts on the golden path — zero numerical change.

3. **`get_snapshots()` copy.** Returns `list(self._snapshots)` — a correct materialized
   copy of the bounded deque, satisfying the `List[Any]` contract (deque raises on slices).
   The four sibling accessors correctly return the live container per the single-writer
   contract.

No engine numbers can change on the golden path. The findings below are a latent
config-divergence trap (WARNING) and three INFO observations.

## Warnings

### WR-01: `MetricsManager.max_snapshots` is decoupled from the actual deque bound (silent config divergence)

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:120`, `itrader/portfolio_handler/storage/in_memory_storage.py:28,54`, `itrader/portfolio_handler/storage/storage_factory.py:50`

**Issue:** Before D-03, the retention bound was honored at trim time from
`self.max_snapshots`, so a caller could set `mm.max_snapshots = N` and have the history
re-bound. After D-03 the bound is frozen at `InMemoryPortfolioStateStorage.__init__`
(`deque(maxlen=max_snapshots)`), and `PortfolioStateStorageFactory.create("backtest")`
constructs the backend with the **hardcoded default 10000** — there is no `max_snapshots`
passthrough on the factory. `Portfolio` always wires its storage via that factory
(`portfolio.py:93`). The result: `MetricsManager.max_snapshots = 10000` is now a purely
decorative attribute on the production path — mutating it (or constructing a
`MetricsManager` expecting it to govern retention) silently has **no effect** on the live
deque. The only way to change the real bound is to bypass the factory and assign
`portfolio.state_storage = InMemoryPortfolioStateStorage(max_snapshots=N)` directly, which
the test `test_snapshot_history_limit` already documents as the new requirement.

This is benign on the golden run (3076 < 10000, no eviction) but is a maintenance trap: a
future caller who sets `mm.max_snapshots` to cap memory on a long/intraday run will get an
unbounded-to-10000 deque silently, and on a run that exceeds 10000 snapshots the ALL_TIME
return baseline (`_get_period_start_date` → `snaps[0]`), the drawdown baseline
(`get_drawdown_analysis` → `equity_values[0]`), and total-return inputs all shift when the
oldest snapshot is evicted — a number-changing eviction governed by a value the manager
attribute no longer controls.

**Fix:** Either remove the now-decorative attribute, or thread it through so the two stay
in sync. Preferred — plumb the bound through the factory and pass the manager's value at
construction:

```python
# storage_factory.py
@staticmethod
def create(environment: str, db_url: Optional[str] = None,
           max_snapshots: int = 10000) -> PortfolioStateStorage:
    ...
    if environment in ('backtest', 'test'):
        return InMemoryPortfolioStateStorage(max_snapshots=max_snapshots)
```

At minimum, drop `self.max_snapshots` from `MetricsManager.__init__` (and its
`logger.info(max_snapshots=...)` arg) so no caller mistakes it for a live control, and
document that the bound is owned by the storage backend.

## Info

### IN-01: Module-level `lru_cache` on `_aligned` persists across backtest runs in one process

**File:** `itrader/outils/time_parser.py:139`

**Issue:** The cache lives at module scope, so it is shared across every portfolio,
strategy, and **every backtest run in the same process** (notebooks, the test session).
This is correct because `_aligned` is a pure function — a cached `(ts, tf)` result is
valid forever — so there is no staleness bug. It is worth noting only because the cache is
process-global shared mutable state: tests that assert on `cache_info()`
(`hits`/`currsize`) must call `_aligned.cache_clear()` first, which the new tests
correctly do (`test_aligned_memo_active_and_bounded`, `test_aligned_memo_bounded_currsize`).

**Fix:** No code change required. If a future test asserts on `misses`/`hits` without an
isolating `cache_clear()`, it will flake on cross-test cache carryover — keep the
`cache_clear()` discipline.

### IN-02: `_aligned` is correct only for timezone-aware `ts`; a naive datetime would fire a process-wide cached `astimezone` path difference

**File:** `itrader/outils/time_parser.py:167`

**Issue:** `ts.astimezone(pytz.utc)` on a *naive* datetime assumes local system time
(platform-dependent), which would make alignment non-deterministic. This is pre-existing
behavior (the body is unchanged) and the sole production callers pass `event.time`, which
is typed `datetime` and is the business clock (tz-aware on the golden path), so it is not a
live defect. The lru_cache does not introduce the risk, but it would now *cache* a naive
result keyed by a naive datetime if one ever leaked in. No action needed for this phase;
flagged so the tz-aware precondition stays explicit.

**Fix:** No change for this phase. If hardening later, assert `ts.tzinfo is not None` at the
`_aligned` boundary so a naive datetime fails loudly instead of silently aligning against
system-local midnight.

### IN-03: `get_snapshots()` manager method double-copies on the filtered path

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:411-422`

**Issue:** `self._storage.get_snapshots()` already returns a fresh `list(self._snapshots)`
copy (storage line 137); the filter/limit branches rebind `snapshots` to new lists; the
final `return snapshots.copy()` then copies again. The extra copy is harmless (correct,
read-only) and this method is off the per-tick path, so it is not a correctness or
in-scope-performance issue — just a redundant allocation.

**Fix:** Drop the trailing `.copy()` (storage already hands out a fresh list each call):

```python
    return snapshots
```

---

_Reviewed: 2026-06-25T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
