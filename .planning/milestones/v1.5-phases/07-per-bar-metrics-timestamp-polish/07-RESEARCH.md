# Phase 7: Per-Bar Metrics & Timestamp Polish (BYTE-EXACT) — Research

**Researched:** 2026-06-25
**Domain:** Python hot-path micro-optimization (stdlib `functools.lru_cache` / `collections.deque`); byte-exact behavior-preservation; Scalene re-profile + W1 re-freeze.
**Confidence:** HIGH (all evidence is direct codebase reads + grep; no external library claims; the four HOW decisions are LOCKED in CONTEXT/SPEC and are NOT re-litigated here).

## Summary

The four HOW decisions (D-01 `lru_cache` on `_aligned`; D-02 delete the per-bar debug log; D-03
`deque(maxlen)` snapshot retention; D-04 remove the `_metrics_cache`/`_cache_timestamp` layer) are
locked. This research closes only the implementation-detail gaps the CONTEXT defers: pinning `N`,
verifying the consumer call-graph is slice-free, listing the exact deletion lines, specifying the
byte-exact equivalence-test shape, and documenting the gate-(b) re-profile/re-freeze commands.

The single highest-value, lowest-risk finding is that this phase **breaks four existing tests** that
the CONTEXT did not flag, and they MUST be updated in the same plans or Gate (a) fails:
1. `test_get_snapshots_returns_live_container_no_copy` (state_storage.py:174-178) — asserts
   object **identity** `get_snapshots() is get_snapshots()`; D-03's `list(self._snapshots)` copy
   makes that False. Convert to value-equality.
2. `test_performance_metrics_caching` (test_metrics_manager.py:284-301) — asserts
   `len(mm._metrics_cache) == 1`; D-04 removes the field.
3. `test_metrics_cache_invalidation` (test_metrics_manager.py:500-522) — asserts on
   `mm._cache_timestamp`; D-04 removes the field.
4. `test_initialization`-style assert `mm.cache_duration_minutes == 5` (test_metrics_manager.py:55)
   — D-04 removes that attribute (it only fed `_is_cache_valid`).

Two more tests are *compatible but worth a sanity touch*: `test_trim_uses_snapshot_accessors`
(test_metrics_manager.py:133-190, the D-06 regression-lock that monkeypatches `get_snapshots` to a
`_boom` sentinel and asserts `set_snapshots` is never called on the per-tick path) stays GREEN
because D-03 removes the trim entirely; and `test_snapshots_replaceable_for_size_trim`
(state_storage.py:128-134) calls `set_snapshots([3,4])` — see Gap C for the `set_snapshots` + deque
hazard.

**Primary recommendation:** Pin `@functools.lru_cache(maxsize=32)` on `_aligned`. The realizable
intra-tick distinct `(ts, tf)` key count in W1 is **1** (4 strategies, all `tf=5m`, 0 screeners;
all share one `ts`); the general bound is `distinct_registered_timeframes` per tick (tiny). 32 is the
conventional small power-of-two with >30x headroom and trivially bounded memory.

## User Constraints (from CONTEXT.md / SPEC.md)

### Locked Decisions (HOW — do NOT re-open)
- **D-01:** Bounded `@functools.lru_cache(maxsize=N)` on module-level `_aligned`
  (`time_parser.py:127-157`). Function BODY byte-unchanged; only the decorator + decision-tag comment
  added. Bare `@functools.cache` is **REJECTED** (unbounded `ts` key space). **Researcher pins N.**
- **D-02:** REMOVE the per-bar `logger.debug(...)` snapshot call entirely
  (`metrics_manager.py:194-198`). It duplicates already-stored snapshot fields; only effect is the
  per-bar `isoformat()` + two `str()` calls. No money/Decimal float conversion is introduced/removed
  from any stored or reported value.
- **D-03:** `PortfolioStorage._snapshots` → `collections.deque(maxlen=max_snapshots)`;
  `get_snapshots()` returns `list(self._snapshots)` (materialized copy, NOT the live deque); remove
  the per-bar trim block (`metrics_manager.py:181-184`) and its `snapshot_count()` size guard.
- **D-04:** REMOVE the in-memory `_metrics_cache`/`_cache_timestamp` entirely, incl. the per-bar
  `clear()` churn (`:191-192`), the dicts (`:111-112`), populate/read sites (`:274-275`/`:296-297`),
  and `_is_cache_valid` (`:537-543`, incl. its wall-clock `datetime.now()` TTL).
  `calculate_performance_metrics` recomputes from snapshot history on each call (the calculation is
  NOT removed — only the memoization layer is). Live metrics deferred to a Postgres time-series (N+3b/N+4).

### Claude's Discretion (the research deliverable below)
- `maxsize=N` for the `_aligned` `lru_cache` (D-01).
- Exact deletion shape for the cache removal (D-04).
- The behavior-preservation proof shape (dedicated equivalence test per the audit-the-invariant precedent).

### Deferred Ideas (OUT OF SCOPE)
- Postgres-backed live metrics persistence (replaces the D-04-removed in-memory cache) — N+3b/N+4.
- `msgspec.Struct` event-model migration; `base.py` `to_dict`/`_json_safe` serialization; hot-path
  log-volume policy — explicit SPEC out-of-scope items.
- Changing `max_snapshots` (stays 10000), event-bus `queue.Queue`→`deque`, any money/order/fill/position change.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-07 | Cut four profiler-confirmed per-bar W1 hotspots (~24% combined) with zero engine-number change (oracle stays 134 / 46189.87730727451). | Gaps A–E below give the pinned `N`, the slice-free call-graph proof, the exact deletion line-list, the equivalence-test assertions, and the Gate-(b) re-profile/re-freeze commands a planner can act on directly. |

## Project Constraints (from CLAUDE.md)

- **Byte-exact / Decimal end-to-end:** no float-for-money introduced; the `str()`/`isoformat()`
  removals (D-02) touch only a dropped log string, never a stored/reported numeric value.
- **Determinism / no wall-clock:** D-01's memo keys are deterministic business values; D-04 actively
  *removes* a wall-clock `datetime.now()` TTL (`_is_cache_valid`) and a `datetime.now()` cache stamp.
- **Indentation (VERIFIED 2026-06-25 — SPEC's claim is WRONG):**
  `time_parser.py` → **TABS**; `portfolio_handler/base.py` → **TABS**;
  `metrics_manager.py` → **4 SPACES**; `in_memory_storage.py` → **4 SPACES**. Match each file; do
  NOT follow the SPEC constraint line's indentation claim.
- **Bounded memory:** the `lru_cache(maxsize=N)` and the `deque(maxlen)` are both inherently bounded;
  D-04 removes the only unbounded-growth-class structure (WR-03).
- **Test strictness:** `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` — no new
  warnings; markers `unit`/`integration`/`slow`/`e2e` only.
- **GSD workflow:** edits go through a GSD command (this is `/gsd:plan-phase` research).

## Standard Stack

Stdlib only — no new dependency. All three primitives already exist in the codebase.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `functools.lru_cache` | stdlib (3.13) | Bounded memo on `_aligned` (D-01) | Established codebase pattern (`@functools.cache` twice-used: `bar_feed.py:81-87`, `strategy_handler/base.py:94-108`); thread-safe (locks internally) [VERIFIED: CPython docs — `lru_cache` is thread-safe]. |
| `collections.deque(maxlen=…)` | stdlib (3.13) | O(1) append + auto-evict snapshot retention (D-03) | The exact bounded structure SPEC Requirement 3 names; drop-in for the slice-free consumer set. |

**No `npm`/`pip`/`cargo` install.** No external package is added — Package Legitimacy Audit is N/A
(see below).

## Package Legitimacy Audit

**N/A — this phase installs no external packages.** All changes use Python stdlib (`functools`,
`collections`) already imported in-tree. No registry verification or slopcheck required.

## Gap A — Pin `maxsize=N` for the `_aligned` lru_cache (D-01)

**Decision: `@functools.lru_cache(maxsize=32)`.**

### Evidence: where `_aligned` is called, and the intra-tick key distribution

`_aligned(ts, tf)` is reached ONLY via `check_timeframe(time, timeframe)` (time_parser.py:174 →
`return _aligned(time, timeframe)`). [VERIFIED: grep — `_aligned` has exactly one caller,
`check_timeframe`; `check_timeframe` has exactly two callers.]

Per-TIME-event call sites:
1. `StrategiesHandler.calculate_signals` (strategies_handler.py:94-96): `for strategy in
   self.strategies: if not check_timeframe(event.time, strategy.timeframe): continue` — one call per
   registered strategy, all with the **same `event.time`** (one `ts` per tick).
2. `ScreenersHandler` (screeners_handler.py:72-75): `for screener in self.screeners:
   check_timeframe(event.time, screener.frequency)` — one call per registered screener.

### W1 fan-out arithmetic

| Quantity | W1 value | Source |
|----------|----------|--------|
| Registered strategies | 4 (A/B/C/D) | w1_topology.py:125-128 (`add_strategy` ×4) |
| Strategy timeframes | all `"5m"` | w1_topology.py:46 `TIMEFRAME="5m"`; :119-122 all constructed `timeframe=TIMEFRAME` |
| Registered screeners | 0 | backtest wiring registers no screeners (deferred subsystem) |
| `ts` per TIME event | 1 | all strategies read the same `event.time` |
| **Distinct `(ts, tf)` live within one TIME event** | **1** | 1 ts × 1 distinct timeframe |
| Distinct `ts` across the full W1 2-month 5m window | ~17.3k | SPEC §Requirement 3 (~17.3k bars) — but each `ts` recurs ZERO times across ticks |

The realizable hit pattern is **intra-tick**: within one TIME event the same `(event.time, 5m)` is
recomputed 4× (once per strategy) → 3 cache hits + 1 miss with even `maxsize=1`. Across ticks `ts`
advances and never recurs, so a large cache buys **zero extra hits** — it only accumulates dead
entries (CONTEXT "Specific Ideas" confirms this). The general per-tick distinct-key bound is
`len(distinct registered strategy/screener timeframes)`, which is tiny in any realistic topology
(a handful of timeframes: 1m/5m/15m/1h/4h/1d…).

### Why `maxsize=32`

- **Captures ~100% of intra-tick repeats:** any reasonable multi-timeframe topology has well under
  32 distinct timeframes; W1 has 1. 32 ≥ 30× the realistic worst case.
- **Bounded memory:** ≤ 32 entries of `(datetime, timedelta) → bool` — a few KB worst case,
  independent of run length. Satisfies the SPEC bounded-memory constraint.
- **Convention:** small power-of-two; mirrors the "small bounded N" framing in CONTEXT D-01.
- **Rejected `maxsize=1`:** technically sufficient for the single-timeframe W1 case, but a
  two-timeframe strategy mix (e.g. a 5m + 1h pair) would thrash (each `check_timeframe` for the
  other timeframe evicts the first), reintroducing recompute within a tick. 32 is robust to topology
  changes for the same near-zero cost.
- **Rejected `maxsize=64/128`:** no additional hits over 32 (the intra-tick distinct-key set is far
  smaller); pure dead headroom.

### Correctness / thread-safety confirmations

- **`lru_cache` is thread-safe** — it locks internally around the cache dict [VERIFIED: CPython
  `functools` docs state the wrapper is thread-safe]. This matches the `_declared_hints` precedent's
  documented guarantee (strategy_handler/base.py:94-108: "thread-safe (locks internally) for live
  mode"). Safe for the live-mode daemon-thread path.
- **Keys are deterministic business values** — `ts` is `event.time` (business time, never wall
  clock); `tf` is a `timedelta`. Both are hashable; no determinism smell.
- **`lru_cache` does not cache exceptions** — `_aligned` raises nothing, but this is consistent with
  the `_offset_alias` precedent's stated guarantee (bar_feed.py:81-87).
- **Function body stays byte-identical** — only `@functools.lru_cache(maxsize=32)` + a decision-tag
  comment are added above `def _aligned`. `functools` is already importable; confirm the
  `import functools` line exists at the top of `time_parser.py` (add if absent — TABS file).

## Gap B — D-03 consumer call-graph is slice-free

**Confirmed: no surviving `[start:end]` slice on the storage `get_snapshots()` once the trim is
removed. The `list(self._snapshots)` copy is byte-identical to today's `list`.** One important
nuance: there are **two** `get_snapshots` methods — keep them distinct.

### The two `get_snapshots`

| Method | File:line | Returns | On per-bar path? |
|--------|-----------|---------|------------------|
| **Storage seam** `InMemoryPortfolioStateStorage.get_snapshots()` | in_memory_storage.py:120-122 | the container (→ `list(self._snapshots)` under D-03) | NO (trim was the only per-bar caller; removed by D-03) |
| **Public** `MetricsManager.get_snapshots(start_date, end_date, limit)` | metrics_manager.py:426-442 | a filtered `.copy()` | NO (reporting only) |

The CONTEXT line-refs (257/311/371/431/558/564) are **storage** `self._storage.get_snapshots()`
callers. `frames.py:72` calls the **public** `MetricsManager.get_snapshots()`.

### Storage `get_snapshots()` call-site audit (VERIFIED by reading each)

| Call site | Access pattern | Slice? |
|-----------|----------------|--------|
| metrics_manager.py:183 (trim block) | `...[-self.max_snapshots:]` | **YES — but this block is DELETED by D-03.** No surviving slice. |
| metrics_manager.py:257 (`calculate_performance_metrics`) | `_snaps[-1].timestamp` | index `[-1]` only |
| metrics_manager.py:311 (`get_drawdown_analysis`) | iterate / comprehension `[s for s in all_snaps if …]` | none |
| metrics_manager.py:371 (`get_return_distribution`) | `len(snaps)`, `snaps[i]`, `snaps[i-period_days]` | scalar index only |
| metrics_manager.py:431 (public `get_snapshots`) | `[s for s in snapshots if …]` then `snapshots[-limit:]` then `.copy()` | slices a **local list already returned from the seam** — fine; operates on the materialized list, never the deque |
| metrics_manager.py:558 (`_get_period_start_date` ALL_TIME) | `snaps[0].timestamp` | index `[0]` only |
| metrics_manager.py:564 (`_get_snapshots_for_period`) | `for snapshot in …` | iterate only |
| reporting/frames.py:72 (via public `get_snapshots()`) | `for snapshot in snapshots` | iterate only |

**Conclusion:** every survivor uses `[-1]`/`[0]`/scalar-index/iterate/`len`/comprehension on the
**returned list** (`list(self._snapshots)`), all of which behave identically on a list. The only
`[start:end]` slice that touches the deque path is in the trim block (line 183), which D-03 deletes.
The public `MetricsManager.get_snapshots`'s `[-limit:]` slice (line 440) runs on a fresh list
returned by the seam, never on the deque — safe and byte-identical.

### `set_snapshots` and `snapshot_count` post-trim disposition

| Method | Still used after D-03? | Disposition |
|--------|----------------------|-------------|
| `set_snapshots` | YES (off-hot-path): test_state_storage.py:133 `set_snapshots([3,4])`; ABC contract base.py:339-348 | **KEEP the ABC + impl method**, but `_snapshots` is now a deque → reassigning a plain `list` in `set_snapshots` would **silently drop the `maxlen` bound** (a `list` has no maxlen). **Implementation note (planner MUST address):** `set_snapshots` impl should rebuild the deque: `self._snapshots = deque(snapshots, maxlen=self.max_snapshots)`. But `max_snapshots` lives on `MetricsManager`, not the storage. Options for the planner: (a) make `InMemoryPortfolioStateStorage.__init__` take `maxlen` and store it so `set_snapshots` can rebuild a bounded deque; or (b) since the per-bar trim (the only production caller) is removed, `set_snapshots` becomes test-only — keep it but document it rebuilds an **unbounded** deque (deque(snapshots) with no maxlen) only when explicitly called. Recommend (a) for invariant safety. |
| `snapshot_count` | YES: metrics_manager.py:213/452 (the empty-guards, NOT the trim) | **KEEP.** Only the trim's `:181` size-guard caller is removed; the `== 0` empty-guards at :213 and :452 remain. `len(deque)` is O(1). |

The D-03 trim-block removal eliminates the `:181` `snapshot_count() > max_snapshots` guard AND the
`:182-184` `set_snapshots(get_snapshots()[-max_snapshots:])` body. `snapshot_count` and
`set_snapshots` themselves survive for their other callers.

## Gap C — D-04 deletion shape (exact line-list)

**`calculate_performance_metrics` has ZERO production callers** [VERIFIED: grep]. Its only in-`itrader`
caller is `export_metrics_to_dict` (metrics_manager.py:455, an off-hot-path reporting export); test
callers exist (test_metrics_manager.py:256/276/296/297/512). It is **not on the per-bar path** —
confirming the cache is inert in backtest. The calculation stays; only the cache layer goes.

### Lines to DELETE

| Lines | Content | Note |
|-------|---------|------|
| metrics_manager.py:110-112 | `# Performance metrics cache` + `self._metrics_cache: Dict[...] = {}` + `self._cache_timestamp: Dict[...] = {}` | remove both fields + comment |
| metrics_manager.py:115 | `self.cache_duration_minutes = 5  # Cache metrics for 5 minutes` | only feeds `_is_cache_valid` |
| metrics_manager.py:124 | `cache_duration=self.cache_duration_minutes,` (inside the `logger.info` init kwargs) | remove this kwarg (keep the `logger.info`, keep `max_snapshots=`) |
| metrics_manager.py:186-192 | the WR-03 invalidate comment block + `self._metrics_cache.clear()` + `self._cache_timestamp.clear()` | remove the whole per-bar invalidation block |
| metrics_manager.py:273-275 | `# Check cache first` + `if self._is_cache_valid(cache_key): return self._metrics_cache[cache_key]` | remove the read |
| metrics_manager.py:271 | `cache_key = f"{period.name}_{end_date.date()}"` | now unused → remove (it only built the cache key) |
| metrics_manager.py:295-297 | `# Cache results` + `self._metrics_cache[cache_key] = metrics` + `self._cache_timestamp[cache_key] = datetime.now()` | remove the populate (kills the wall-clock `datetime.now()`) |
| metrics_manager.py:537-543 | the entire `_is_cache_valid` method | remove (kills its wall-clock `datetime.now()` TTL) |

### Lines that SIMPLIFY (stay, minus the cache plumbing)

- `calculate_performance_metrics` (242-299): keep the `end_date` resolution (254-269), the
  `_get_period_start_date` / `_get_snapshots_for_period` / `< 2` guard / `_calculate_metrics_from_snapshots`
  path (277-293), and `return metrics` (now returns the freshly computed object every call instead of
  a cached one). Net: the method recomputes on each call — fine, zero production per-bar callers.

### `datetime.now` / `datetime` import check

After D-04, verify whether `datetime.now()` still appears elsewhere in metrics_manager.py. It is
explicitly forbidden as a *snapshot/period anchor* (WR-01 raises instead), so the only remaining
`datetime.now()` uses were the two cache sites (:297, :542) being deleted. The `datetime` symbol is
still needed for type hints (`Optional[datetime]`) and `timedelta` math (`_get_period_start_date`),
so keep the `from datetime import datetime, timedelta` import — just confirm no orphaned `datetime.now`.

### Consumers of the removed private fields (test fallout — MUST fix)

| Test | Line | Asserts on | Fix |
|------|------|-----------|-----|
| `test_initialization` (or equivalent) | test_metrics_manager.py:55 | `mm.cache_duration_minutes == 5` | delete this assertion |
| `test_performance_metrics_caching` | test_metrics_manager.py:284-301 | `len(mm._metrics_cache) == 1` (:301) | delete the cache assertion; keep `metrics1.total_return == metrics2.total_return` (recompute determinism) — rename test to e.g. `test_performance_metrics_recompute_stable` |
| `test_metrics_cache_invalidation` | test_metrics_manager.py:500-522 | `len(mm._cache_timestamp) == 1` (:513) and `== 0` (:522) | delete or rewrite as a recompute-stability test (no cache to invalidate) |

No production (non-test) consumer reads `_metrics_cache`/`_cache_timestamp`/`cache_duration_minutes`/
`_is_cache_valid` [VERIFIED: grep — all non-test refs are inside metrics_manager.py itself].

## Gap D — Byte-exact equivalence-test shape

**Established pattern (CONTEXT + verified precedents): audit-the-invariant + a dedicated
equivalence/regression test, NO hot-path runtime guard.** The direct precedents in-tree:
- `tests/unit/portfolio/test_state_storage.py:137-195` — the PERF-01/D-03/D-06 object-identity /
  accessor regression locks (copy-free getters proven by identity; count/last accessors proven by
  value). This is the closest precedent for the D-03 snapshot work.
- `tests/unit/portfolio/test_metrics_manager.py:133-190` `test_trim_uses_snapshot_accessors` — the
  D-06 per-tick-path regression lock (monkeypatch `get_snapshots` to a `_boom` sentinel; assert the
  per-tick path consumes only `snapshot_count`/`get_latest_snapshot` and never `set_snapshots`). This
  is the precedent for "prove the cost is gone without re-paying it on the hot path."
- `tests/unit/price/test_bar_feed.py::test_zero_resample_calls_on_per_tick_path` — the idiom
  `test_trim_uses_snapshot_accessors` cites as its analog.
- Gate (a) byte-exact lock: `tests/integration/test_backtest_oracle.py` (134 / 46189.87730727451)
  [per memory `oracle-test-location`: this is the oracle; `tests/golden` is artifacts].

### Recommended new/updated tests

**Placement:** unit tests live next to the modules — `tests/unit/outils/` for `_aligned`,
`tests/unit/portfolio/test_metrics_manager.py` + `tests/unit/portfolio/test_state_storage.py` for
the snapshot/cache work. The Gate-(a) byte-exact assurance is the existing oracle (held, not
changed) — no new integration test needed beyond running it.

| # | Assertion | Where | Maps to |
|---|-----------|-------|---------|
| T1 | `_aligned(ts, tf)` returns identical results for a sampled grid of `(ts, tf)` across a memoized vs a freshly-evaluated reference (e.g. parametrize daily-00:00, intraday-non-aligned, weekly, 7h-non-divisor cases — mirror the docstring examples at time_parser.py:127-157). | new `tests/unit/outils/test_time_parser.py` (TABS-agnostic for tests) | D-01 acceptance "output provably unchanged for all inputs" |
| T2 | `_aligned.cache_info()` shows the cache is **bounded** (maxsize == 32) and that repeated identical `(ts, tf)` produce hits (call twice, assert `hits >= 1`). Confirms memoization is wired, not just decorating a no-op. | same file | D-01 bounded-memory + memo-active |
| T3 | After many distinct `(ts, tf)`, `_aligned.cache_info().currsize <= 32` (never grows unbounded). | same file | SPEC bounded-memory constraint |
| T4 | `get_snapshots()` returns **value-equal** contents pre/post the deque change (build N snapshots, assert list equality + order preserved). **Update** `test_get_snapshots_returns_live_container_no_copy` (state_storage.py:174-178): the `is`-identity assert MUST change to value-equality (`==`) — the materialized `list(...)` copy is intentionally a new object each call (D-03 rationale: don't hand the live deque to readers). | `test_state_storage.py` | D-03 byte-identity of returned snapshots |
| T5 | A `>max_snapshots` run retains **exactly the last `max_snapshots`** snapshots and drops the oldest (push `max_snapshots + k`, assert `snapshot_count() == max_snapshots`, `get_latest_snapshot()` is the newest, `get_snapshots()[0]` is the `(k+1)`-th pushed). Use a smaller `max_snapshots` for test speed if the deque maxlen is parameterizable; otherwise mark `slow`. | `test_metrics_manager.py` or `test_state_storage.py` | D-03 "exact last-N retention" |
| T6 | `test_trim_uses_snapshot_accessors` (existing, :133-190) stays GREEN — assert `set_snapshots` is never called on the per-tick path (now trivially true since the trim block is deleted). Keep as the per-tick-no-copy regression lock. | `test_metrics_manager.py` | D-03 no per-bar full-copy |
| T7 | `calculate_performance_metrics` returns **equal metric values** on repeated calls after D-04 (recompute is deterministic), and `MetricsManager` no longer has `_metrics_cache`/`_cache_timestamp`/`_is_cache_valid`/`cache_duration_minutes` attributes (`assert not hasattr(...)`). Replaces the deleted cache tests (Gap C fallout). | `test_metrics_manager.py` | D-04 metrics unchanged + cache truly removed |
| T8 | (D-02) No dedicated unit test is strictly required — the dropped debug log records nothing not already in the snapshot fields. Optionally assert `record_snapshot` still returns a `PortfolioSnapshot` with the same fields (existing tests already cover this). The Gate-(a) oracle is the real proof. | existing coverage | D-02 byte-exact |
| T9 | **Gate (a) byte-exact:** run `tests/integration/test_backtest_oracle.py` — 134 / 46189.87730727451; `mypy --strict` clean; determinism double-run byte-identical. | existing oracle | Gate (a) |

## Gap E — Gate (b) re-profile / re-freeze mechanics + thermal caveat

### Commands (VERIFIED from Makefile lines 99-142 + run_w1_benchmark.py)

**Step 1 — Re-profile with Scalene to confirm the four hotspots are gone:**
```bash
make perf-profile          # = scalene run --cpu-only --program-path $(CURDIR)
                           #     -o perf/results/scalene-w1.json -m perf.runners.run_w1_benchmark
make perf-view             # opens the native Scalene viewer on the existing JSON (no re-run)
```
Confirm in the new `perf/results/scalene-w1.json` that the four lines are materially reduced/gone:
`time_parser.py:154-156` (`_aligned`), `metrics_manager.py:194-198` (the deleted debug log — line
will no longer exist), `in_memory_storage.py set_snapshots` + `metrics_manager.py:181-184` (trim —
removed), `metrics_manager.py:191-192` (`_metrics_cache.clear()` — removed).
Keep the pre-phase `perf/results/scalene-w1.json` (the logging-disabled baseline that surfaced the
hotspots) as the before-image — copy it aside first (e.g. `scalene-w1-pre07.json`) so the comparison
survives the overwrite.
*Caveats baked into the target:* `--cpu-only` (the memory profiler stalls per memory
`scalene-profiling-itrader-gotchas`); `--program-path` not `--profile-all`; do NOT use
`view --html` / `run --html` (Pitfall 1, broken in scalene 2.3.0).

**Step 2 — Same-machine A/B attribution + re-freeze on a verified-COOL machine:**
```bash
make perf-w1               # gated run: --check vs perf/results/W1-BASELINE.json
                           #   prints W1 wall_clock Δ% (FAILS only on a >+5% SLOWDOWN; an
                           #   improvement never trips the guard)
```
Attribution discipline (per memory `v15-perf-gateb-thermal-drift` + `w1-benchmark-probe-quadratic-bug`):
- The W1 benchmark is **thermally sensitive**. Do NOT trust the frozen-baseline `Δ%` on a throttled
  box. Attribute the win via a **same-machine A/B**: run `make perf-w1` (or
  `python -m perf.runners.run_w1_benchmark --json`) on the pre-phase commit and the post-phase commit
  back-to-back on the same cool machine, and compare those two numbers — not the post-phase number vs
  the (possibly cold-frozen) `W1-BASELINE.json`.
- Cross-check the attribution with the Scalene CPU-share delta from Step 1 (the four lines' combined
  share dropping ~24% is the mechanism; the wall-clock A/B is the confirmation).

**Step 3 — Re-freeze the W1 baseline (only on a verified-cool machine):**
```bash
make perf-baseline         # = run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json
                           #   writes the new committed reference (rounds wall_clock to 1 decimal,
                           #   stamps frozen_at + the oracle provenance constants)
```
Note: `--baseline-out` and `--check` together are explicitly warned against in the runner
(self-comparison, delta ~0%); the Makefile keeps them separate. Re-freeze writes
`perf/results/W1-BASELINE.json`; commit it as the new post-phase reference.

### Gate definitions (from SPEC §Acceptance + run_w1_benchmark guard)

- **Gate (a):** oracle byte-exact (134 / 46189.87730727451), e2e green, `mypy --strict` clean,
  determinism double-run byte-identical. NOT a re-baseline.
- **Gate (b):** clean W1 shows a measurable wall-clock improvement vs the re-frozen baseline
  (same-machine A/B; re-freeze on a cool machine). No hard `%` threshold for W1 (the `--check` guard
  only FAILS on a >+5% slowdown; an improvement passes). The ~24% combined CPU-share is the target
  mechanism, not a contractual wall-clock number.

## Architecture Patterns

This is a surgical micro-optimization phase; the "architecture" is the four locked decisions applied
to four files. No new components, no event-queue or routing change, no cross-domain signature change.

### Component Responsibilities (files touched)

| Capability | File:lines | Change | Indentation |
|------------|-----------|--------|-------------|
| Timestamp alignment memo (D-01) | `itrader/outils/time_parser.py:127` | add `@functools.lru_cache(maxsize=32)` + tag comment above `_aligned`; body byte-unchanged | TABS |
| Drop per-bar debug log (D-02) | `itrader/portfolio_handler/metrics/metrics_manager.py:194-198` | delete the `logger.debug(...)` call | 4 SPACES |
| Snapshot retention (D-03) | `itrader/portfolio_handler/storage/in_memory_storage.py:45,120-125` | `_snapshots` → `deque(maxlen)`; `get_snapshots` → `list(...)`; `set_snapshots` rebuilds bounded deque | 4 SPACES |
| Remove trim block (D-03) | `itrader/portfolio_handler/metrics/metrics_manager.py:181-184` | delete the size-guard + `set_snapshots(get_snapshots()[-N:])` | 4 SPACES |
| Remove metrics cache (D-04) | `itrader/portfolio_handler/metrics/metrics_manager.py` (lines per Gap C) | delete fields/populate/read/`_is_cache_valid` | 4 SPACES |
| ABC docstring touch (D-03) | `itrader/portfolio_handler/base.py:322-348` | note deque-backed + materialized list in `get_snapshots`/`set_snapshots` docstrings | TABS |

### Anti-Patterns to Avoid
- **Returning the live deque from `get_snapshots()`** — D-03 explicitly rejects this (seam
  uniformity, `Sequence` sliceability type-lie, live-iteration hazard). Always `list(self._snapshots)`.
- **`set_snapshots` reassigning a plain `list`** — silently drops the `maxlen` bound. Rebuild a deque.
- **Bare `@functools.cache` on `_aligned`** — unbounded `ts` key space → SPEC bounded-memory violation.
- **Adding a per-tick `assert` that re-evaluates `_aligned` to "prove" equivalence** — re-pays the
  removed cost; use a dedicated equivalence test (audit-the-invariant pattern) instead.
- **Normalizing indentation** — `metrics_manager.py`/`in_memory_storage.py` are 4 SPACES;
  `time_parser.py`/`base.py` are TABS. A mixed diff breaks a tab file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bounded memo on a pure function | A manual `dict` + size-eviction loop | `functools.lru_cache(maxsize=32)` | stdlib, thread-safe, twice-used precedent in-tree |
| Bounded FIFO retention | A list + per-append slice/trim | `collections.deque(maxlen=N)` | O(1) append + auto-evict; the trim cost IS the hotspot |

## Common Pitfalls

### Pitfall 1: Breaking the object-identity test
`test_get_snapshots_returns_live_container_no_copy` asserts `get_snapshots() is get_snapshots()`.
D-03's `list(...)` copy returns a new object each call → this test MUST flip to value-equality, or
Gate (a)'s suite goes red. Warning sign: green oracle but red `test_state_storage.py`.

### Pitfall 2: Orphaning the deque `maxlen` via `set_snapshots`
If `set_snapshots` reassigns `self._snapshots = list(snapshots)` (the current impl,
in_memory_storage.py:125), the `maxlen` invariant is lost. Rebuild: `deque(snapshots, maxlen=…)`.
The storage needs to know `max_snapshots` — plumb it through `__init__` (recommended) since
`max_snapshots` currently lives on `MetricsManager`.

### Pitfall 3: Leaving deleted-cache tests asserting on removed attributes
Three tests (Gap C table) assert on `_metrics_cache`/`_cache_timestamp`/`cache_duration_minutes`.
Under `filterwarnings=["error"]`+strict config the suite fails hard on the `AttributeError`. Delete
or rewrite them as recompute-stability tests in the same plan.

### Pitfall 4: Trusting the frozen-baseline Δ% on a throttled box
The W1 benchmark is thermally sensitive (memory `v15-perf-gateb-thermal-drift`). Attribute via
same-machine A/B + Scalene CPU-share; re-freeze only on a verified-cool machine.

### Pitfall 5: `make test` masking caplog/log behavior
`make test` exports `ITRADER_DISABLE_LOGS=true` (memory `make-test-env-disables-logs`) and aborts in
worktrees on a missing `.env` (memory `worktree-make-test-env-abort`). Use
`poetry run pytest tests/...` as the gate for the touched suites; the dropped D-02 log means no
caplog test should depend on that message anyway.

## Runtime State Inventory

Not a rename/refactor/migration phase — no stored data, live-service config, OS-registered state,
secrets, or build artifacts carry a renamed string. **None — verified: this phase edits four source
files' logic only; no identifiers/keys/collection-names change.** Section omitted as N/A beyond this note.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-bar recompute of `_aligned` | bounded `lru_cache` memo | this phase | ~8.7% W1 CPU reclaimed |
| Per-bar eager debug-log arg eval | log call deleted | this phase | ~8.6% W1 CPU reclaimed |
| `list` + per-bar slice-trim (latent O(n²)) | `deque(maxlen)` auto-evict | this phase | ~5% W1 CPU reclaimed |
| Per-bar metrics-cache `clear()` + wall-clock TTL | cache removed; recompute on demand | this phase | ~2.9% W1 CPU + removes a wall-clock determinism smell |

## Validation Architecture

> Nyquist validation applies (config key absent → treated as enabled). Test framework is pytest.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py tests/unit/portfolio/test_state_storage.py tests/unit/outils/ -x` |
| Full suite command | `make test` (note: exports `ITRADER_DISABLE_LOGS=true`; in worktrees use `poetry run pytest tests`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-07 / D-01 | `_aligned` output unchanged + bounded memo | unit | `poetry run pytest tests/unit/outils/test_time_parser.py -x` | ❌ Wave 0 (new file) |
| PERF-07 / D-03 | snapshot value-identity + last-N retention | unit | `poetry run pytest tests/unit/portfolio/test_state_storage.py -x` | ✅ (update T4; add T5) |
| PERF-07 / D-03 | per-tick path makes no full-copy | unit | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py -k trim_uses_snapshot_accessors` | ✅ (keep GREEN) |
| PERF-07 / D-04 | metrics recompute-stable; cache attrs gone | unit | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py -x` | ✅ (delete/rewrite 3 tests) |
| PERF-07 (Gate a) | oracle byte-exact 134 / 46189.87730727451 | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ |
| PERF-07 (Gate a) | mypy strict clean | static | `make typecheck` | ✅ |
| PERF-07 (Gate b) | W1 measurable win + re-profile | manual/perf | `make perf-profile` → `make perf-w1` → (cool machine) `make perf-baseline` | ✅ |

### Sampling Rate
- **Per task commit:** `poetry run pytest <touched test file> -x` (quick).
- **Per wave merge:** `poetry run pytest tests` (full unit+integration).
- **Phase gate:** oracle green + `mypy --strict` clean + Gate (b) re-profile/A-B/re-freeze on a cool machine.

### Wave 0 Gaps
- [ ] `tests/unit/outils/test_time_parser.py` — new file: `_aligned` equivalence (T1) + bounded-memo
  (T2) + bounded-currsize (T3). Confirm a `tests/unit/outils/` dir or create it (the source dir is
  `itrader/outils/`; the test tree exists at `tests/unit/` but `outils/` may need creating).
- [ ] Update `test_state_storage.py::test_get_snapshots_returns_live_container_no_copy` from `is` to `==` (T4).
- [ ] Add the >max_snapshots last-N retention test (T5).
- [ ] Delete/rewrite `test_performance_metrics_caching`, `test_metrics_cache_invalidation`, and the
  `cache_duration_minutes` assertion (Gap C fallout); add the recompute-stability + `not hasattr` test (T7).
- [ ] Framework install: none — pytest is present.

## Security Domain

Not applicable beyond the determinism/no-wall-clock invariant (already covered): this phase has no
auth, session, access-control, input-validation, cryptography, or external-input surface. D-04
*improves* posture by removing a wall-clock dependency. No ASVS category applies (no new
external-input or trust boundary). `security_enforcement` is not a factor for a pure internal
hot-path refactor with a byte-exact correctness gate.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `maxsize=32` is comfortably above any realistic per-tick distinct-timeframe count | Gap A | If a future topology registers >32 distinct timeframes, intra-tick thrash returns — but W1's distinct count is 1 and the general bound is tiny; trivially re-pinnable. LOW risk. |
| A2 | `import functools` is present (or trivially addable) at the top of `time_parser.py` | Gap A | If absent, add it (TABS file). Planner verifies. LOW. |
| A3 | `set_snapshots` should be made deque-maxlen-aware via `__init__` plumbing | Gap B/Pitfall 2 | If the planner instead keeps `set_snapshots` test-only-unbounded, document it; the only production caller (the trim) is removed anyway. LOW. |
| A4 | No production code path reads the removed cache fields | Gap C | VERIFIED by grep (all non-test refs are inside metrics_manager.py). LOW. |

## Open Questions (RESOLVED)

1. **Is `max_snapshots` reachable from `InMemoryPortfolioStateStorage` for the deque `maxlen`?**
   - What we know: `max_snapshots=10000` lives on `MetricsManager.__init__` (metrics_manager.py:116);
     the storage is constructed separately.
   - What's unclear: the exact wiring of `max_snapshots` into the storage constructor.
   - Recommendation: plumb `max_snapshots` into `InMemoryPortfolioStateStorage.__init__` (default
     10000) so both `__init__`'s `deque(maxlen=…)` and `set_snapshots`'s rebuild share one source.
     The planner reads the storage's construction site (PortfolioHandler/Portfolio wiring) to confirm.
   - **RESOLVED (2026-06-25):** plumb `max_snapshots=10000` into `InMemoryPortfolioStateStorage.__init__`;
     both the deque init and `set_snapshots`'s rebuild share `self._max_snapshots`. Captured in
     `07-PATTERNS.md` (storage plumbing site `storage_factory.py:49-76` + storage `__init__`) and
     implemented in Plan 07-02 Task 1.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| poetry / .venv | all test + perf runs | ✓ (assumed; project standard) | per pyproject | — |
| scalene | Gate (b) re-profile (`make perf-profile`) | ✓ (in poetry deps; `make perf-profile` exists) | 2.3.0 (per Makefile Pitfall note) | — |
| a verified-COOL machine | Gate (b) re-freeze | manual judgment | — | defer re-freeze; attribute via same-machine A/B only |

**Missing dependencies with no fallback:** none identified (all tooling is in-tree).

## Sources

### Primary (HIGH confidence — direct codebase reads, this session)
- `itrader/outils/time_parser.py:100-174` — `_aligned`/`check_timeframe` body + callers.
- `itrader/portfolio_handler/storage/in_memory_storage.py:1-136` — snapshot accessors.
- `itrader/portfolio_handler/metrics/metrics_manager.py:100-567` — cache fields, trim, debug log, `calculate_performance_metrics`, `_is_cache_valid`.
- `itrader/portfolio_handler/base.py:320-369` — storage-seam ABC contracts.
- `itrader/reporting/frames.py:60-84` — `build_equity_curve` snapshot consumer (iterate-only).
- `itrader/strategy_handler/strategies_handler.py:80-114` + `itrader/screeners_handler/screeners_handler.py:65-84` — `check_timeframe` call sites (intra-tick fan-out).
- `perf/runners/run_w1_benchmark.py` + `perf/workloads/w1_topology.py` — W1 topology (4 strategies / 6 portfolios / 4 symbols / `5m`).
- `Makefile:90-143` — `perf-w1`/`perf-baseline`/`perf-profile`/`perf-view` targets.
- `tests/unit/portfolio/test_metrics_manager.py` + `tests/unit/portfolio/test_state_storage.py` — existing tests that break/need-touch.
- grep audits: `calculate_performance_metrics`, `set_snapshots`, `snapshot_count`, `_metrics_cache`/`_cache_timestamp`/`_is_cache_valid`, `get_snapshots`, `_aligned`/`check_timeframe` callers.
- `07-CONTEXT.md`, `07-SPEC.md` — locked decisions + requirements.

### Secondary (MEDIUM — project memory, prior-phase precedents)
- Memory: `v15-perf-gateb-thermal-drift`, `w1-benchmark-probe-quadratic-bug`, `scalene-profiling-itrader-gotchas`, `make-test-env-disables-logs`, `worktree-make-test-env-abort`, `oracle-test-location`.

### Tertiary (LOW — training knowledge, low-stakes)
- `functools.lru_cache` thread-safety / "does not cache exceptions" — standard CPython behavior,
  corroborated by the in-tree `_offset_alias`/`_declared_hints` precedent comments. [ASSUMED→corroborated]

## Metadata

**Confidence breakdown:**
- Gap A (pin N): HIGH — intra-tick distinct-key count derived directly from the call sites + W1 topology.
- Gap B (call-graph): HIGH — every call site read individually.
- Gap C (deletion list): HIGH — every line read; grep confirms zero production cache consumers.
- Gap D (test shape): HIGH — precedent tests located in-tree; breakage cases identified by grep + read.
- Gap E (gate commands): HIGH — verbatim from Makefile + runner.

**Research date:** 2026-06-25
**Valid until:** ~30 days (stable internal code; re-verify line numbers if the files are edited before planning).
