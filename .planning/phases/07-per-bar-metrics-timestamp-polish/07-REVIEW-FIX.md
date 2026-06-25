---
phase: 07-per-bar-metrics-timestamp-polish
fixed_at: 2026-06-25T00:00:00Z
review_path: .planning/phases/07-per-bar-metrics-timestamp-polish/07-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 2
skipped: 2
status: partial
---

# Phase 7: Code Review Fix Report

**Fixed at:** 2026-06-25T00:00:00Z
**Source review:** .planning/phases/07-per-bar-metrics-timestamp-polish/07-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (1 Warning + 3 Info, fix_scope = all)
- Fixed: 2 (WR-01, IN-03)
- Skipped/Deferred: 2 (IN-01, IN-02 — both "no code change required" by the review itself)

**Gate (run from the worktree against the main checkout's venv, NOT `make test`):**
- `pytest tests/integration/test_backtest_oracle.py -x -q` → 3 passed (byte-exact: 134 trades / final_equity 46189.87730727451 preserved)
- `pytest tests/unit/portfolio tests/unit/outils -q` → 305 passed
- `mypy itrader` (strict) → Success: no issues found in 166 source files

## Fixed Issues

### WR-01: `MetricsManager.max_snapshots` is decoupled from the actual deque bound

**Files modified:** `itrader/portfolio_handler/storage/storage_factory.py`, `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** d6befb3
**Applied fix:** Took the **preferred** path from the review — threaded the bound through the factory rather than dropping the decorative attribute.

- `PortfolioStateStorageFactory.create(...)` gained a `max_snapshots: int = 10000` parameter and now constructs `InMemoryPortfolioStateStorage(max_snapshots=max_snapshots)` for the `backtest`/`test` environments (previously hardcoded the default).
- `MetricsManager.__init__` was reordered so `self.max_snapshots = 10000` is set **before** the storage-fabrication block, and the fallback (standalone test-portfolio) path now calls `PortfolioStateStorageFactory.create("backtest", max_snapshots=self.max_snapshots)`. The now-duplicated `risk_free_rate` / `trading_days_per_year` lines were folded into the relocated config block (no value change).

**Constraint compliance:**
- The factory default stays **10000** (unchanged). A real `Portfolio` still wires its storage via `PortfolioStateStorageFactory.create("backtest")` at `portfolio.py:93` with the default, and `MetricsManager.max_snapshots` also defaults to 10000 — so the two remain in sync byte-for-byte on the production/golden path. No computed engine number changes.
- Golden run is 3076 daily bars < 10000, so the deque never evicts regardless; the oracle stays byte-exact (verified: 3 passed).
- No float-for-money introduced; indentation matched the file (4 spaces in both `storage/` and `metrics/` files here — verified per-file, not assumed from the tab/space heuristic).

This makes `MetricsManager.max_snapshots` a real control again for the fabricated-storage case, and gives the factory a passthrough so a future long/intraday caller can cap retention without bypassing the factory.

### IN-03: `get_snapshots()` manager method double-copies on the filtered path

**Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** 2e999b0
**Applied fix:** Dropped the trailing `.copy()` in `MetricsManager.get_snapshots(...)` and replaced it with `return snapshots`, plus an explanatory comment. `self._storage.get_snapshots()` already returns a fresh `list(self._snapshots)`, and the filter/limit branches rebind to new lists — the result is always a caller-owned copy. This method is off the per-tick path, so the change is a pure redundant-allocation removal with no behavioral effect. Verified: metrics + oracle tests pass, mypy clean.

## Skipped / Deferred Issues

### IN-01: Module-level `lru_cache` on `_aligned` persists across backtest runs in one process

**File:** `itrader/outils/time_parser.py:139`
**Reason:** Deferred — the review explicitly states **"No code change required."** This is a discipline note: tests asserting on `cache_info()` must call `_aligned.cache_clear()` first, which the new tests already do (`test_aligned_memo_active_and_bounded`, `test_aligned_memo_bounded_currsize`). `_aligned` is a pure function, so a cached `(ts, tf)` result is valid forever — there is no staleness bug. Adding any code here would be churn with no correctness benefit and would risk perturbing the byte-exact memoization seam. No action taken.

### IN-02: `_aligned` is correct only for timezone-aware `ts`

**File:** `itrader/outils/time_parser.py:167`
**Reason:** Deferred — the review explicitly states **"No change for this phase."** The sole production callers pass `event.time` (tz-aware business clock on the golden path), the function body is unchanged from the base commit, and this is pre-existing behavior the lru_cache does not introduce. The suggested hardening (`assert ts.tzinfo is not None` at the `_aligned` boundary) is a future-hardening note, not an in-scope defect. Introducing an assert into the per-tick alignment seam during a byte-exact performance phase carries non-zero risk (assert overhead on the hot path, and a behavioral change if any test passes a naive datetime) for no correctness gain on the golden path — so it is deferred to a dedicated hardening change as the review suggests.

---

_Fixed: 2026-06-25T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
