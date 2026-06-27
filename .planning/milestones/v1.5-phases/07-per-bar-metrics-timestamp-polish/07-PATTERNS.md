# Phase 7: Per-Bar Metrics & Timestamp Polish (BYTE-EXACT) - Pattern Map

**Mapped:** 2026-06-25
**Files analyzed:** 8 (4 source edits + 3 test touches + 1 storage-factory plumbing site)
**Analogs found:** 8 / 8 (every change mirrors an in-tree precedent — no new pattern invented)

> This is a surgical byte-exact micro-optimization phase. Every edit COPIES an established
> in-tree pattern (the twice-used `@functools` memo convention; the storage-seam accessor
> contract; the audit-the-invariant regression-test precedent). The "analog" for each source
> file is frequently a sibling in the SAME file or a sibling accessor — copy the local
> convention, do not import a foreign one.
>
> **⚠ INDENTATION IS PER-FILE (verified 2026-06-25 — the SPEC's claim is WRONG):**
> `time_parser.py` -> **TABS** · `portfolio_handler/base.py` -> **TABS** ·
> `metrics_manager.py` -> **4 SPACES** · `in_memory_storage.py` -> **4 SPACES** ·
> `storage_factory.py` -> **4 SPACES** · tests -> match each test file (the two touched ones use 4 SPACES).
> Match each file; NEVER normalize. A mixed-indentation diff breaks a tab file.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/outils/time_parser.py` (`_aligned` D-01) | utility (pure fn) | transform | `price_handler/feed/bar_feed.py:81-87` `_offset_alias` | exact (bounded variant) | TABS |
| `itrader/portfolio_handler/metrics/metrics_manager.py` (D-02/D-03/D-04) | manager | transform / batch | sibling sites in same file | exact (in-file) | 4 SPACES |
| `itrader/portfolio_handler/storage/in_memory_storage.py` (D-03) | storage backend | CRUD (append-only history) | the 4 sibling accessors in the same file | exact (in-file) | 4 SPACES |
| `itrader/portfolio_handler/base.py` (D-03 docstring touch) | ABC / storage seam | CRUD | the 4 sibling abstract accessors :320-369 | exact (in-file) | TABS |
| `itrader/portfolio_handler/storage/storage_factory.py` (D-03 `maxlen` plumbing) | factory | config wiring | `create()` / `create_in_memory()` :49-76 | exact (in-file) | 4 SPACES |
| `tests/unit/outils/test_time_parser.py` (D-01 T1-T3) | test | transform | EXISTING file — extend in place | exact | (file uses TABS-mixed; match existing) |
| `tests/unit/portfolio/test_state_storage.py` (D-03 T4/T5) | test | CRUD | the 5 `*_returns_live_container_no_copy` tests + `test_snapshots_replaceable_for_size_trim` | exact (in-file) | 4 SPACES |
| `tests/unit/portfolio/test_metrics_manager.py` (D-04 fallout + D-03 T6) | test | transform | `test_trim_uses_snapshot_accessors` :133-190 | exact (in-file) | 4 SPACES |

> **Correction to RESEARCH Wave-0 gap:** `tests/unit/outils/test_time_parser.py` ALREADY EXISTS
> (it is the file in `<required_reading>`-adjacent context; confirmed on disk). It is NOT a new
> file — EXTEND it with T1-T3. The dir `tests/unit/outils/` exists. Add the `_aligned` memo tests
> to the existing `_aligned`-import block (line 26-30 already imports `_aligned`).

---

## Pattern Assignments

### `itrader/outils/time_parser.py` — D-01 `_aligned` memoization (utility, transform) — **TABS**

**Analog:** `itrader/price_handler/feed/bar_feed.py:81-87` `@functools.cache def _offset_alias` (Phase 6 D-01/PERF-06).
**Second precedent:** `itrader/strategy_handler/base.py:106-108` `@cache def _declared_hints` (Phase 4 D-05/PERF-04).

**The exact precedent to mirror** (`bar_feed.py:81-87`, the decision-tag comment style + decorator + "body byte-unchanged / does NOT cache exceptions"):
```python
# D-01 (PERF-06): memoize the per-call offset-alias string compute — it fires
# ONCE per distinct timeframe across __init__/precompute/the per-tick window()
# path. timedelta is hashable; functools.cache does NOT cache exceptions, so the
# raise-on-unsupported ValueError guard inside is preserved (RESEARCH Pitfall 4).
# The function BODY is byte-unchanged — only this decorator was added.
@functools.cache
def _offset_alias(timeframe: timedelta) -> str:
```

**Second precedent** (`base.py:94-108`, the thread-safety + bounded-key wording):
```python
# D-05 (PERF-04): ... functools.cache is thread-safe (locks internally) for
# live mode, and no manual invalidation is needed (the strategy-class count is
# bounded and annotations never change after import). ...
@cache
def _declared_hints(cls: type["Strategy"]) -> dict[str, Any]:
    return get_type_hints(cls)
```

**Target — `_aligned` at time_parser.py:127-157.** Body stays byte-IDENTICAL. Add ONLY the decorator + a phase-local decision-tag comment ABOVE `def _aligned` (TABS):
```python
def _aligned(ts: datetime, tf: timedelta) -> bool:
    # ... 28-line docstring (UNCHANGED) ...
    utc = ts.astimezone(pytz.utc).replace(second=0, microsecond=0)
    midnight = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = (utc - midnight).total_seconds()
    return seconds_since_midnight % int(tf.total_seconds()) == 0
```

**THE ONE ADAPTATION vs the two precedents:** use **bounded** `@functools.lru_cache(maxsize=32)`,
NOT bare `@functools.cache`. RESEARCH Gap A pins **`maxsize=32`** (intra-tick distinct `(ts,tf)` in W1 = 1;
general bound = distinct registered timeframes; 32 = ~30x headroom, few-KB bounded). Bare `cache` is
REJECTED — the `ts` key space is unbounded (per-bar ts, ~17.3k distinct) -> SPEC bounded-memory violation.

**IMPORT GAP (verified):** `time_parser.py` does NOT `import functools` today — its imports are
`re, pytz, pd, typing, datetime, itrader.config` (lines 1-6). **Add `import functools`** at the top
(TABS file). Mirrors RESEARCH assumption A2.

**Comment must cite:** D-01, the unbounded-`ts`-key rationale for the bounded variant, "body byte-unchanged",
"lru_cache does not cache exceptions (function raises nothing)", "thread-safe (locks internally) for live mode",
"keys are deterministic business values (no wall-clock)".

---

### `itrader/portfolio_handler/storage/in_memory_storage.py` — D-03 snapshot retention (storage backend, CRUD) — **4 SPACES**

**Analog:** the four sibling accessors IN THIS FILE share ONE contract — copy it exactly.

**The seam contract to preserve** (sibling accessors :55-113):
```python
    def get_positions(self) -> Dict[str, 'Position']:
        # D-03/D-19: live read-only view, no per-tick copy (single-writer contract).
        return self._positions
    # ... get_closed_positions / get_transaction_history / get_cash_operations identical shape ...
```

**Targets (current code):**
```python
        # Metrics snapshots (append-only history) — was MetricsManager._snapshots
        self._snapshots: List[Any] = []                        # :45 -> deque(maxlen=...)

    def add_snapshot(self, snapshot: Any) -> None:             # :117-118 — UNCHANGED (deque.append is O(1))
        self._snapshots.append(snapshot)

    def get_snapshots(self) -> List[Any]:                      # :120-122 -> return list(self._snapshots)
        # D-03/D-19: live read-only view, no per-tick copy (single-writer contract).
        return self._snapshots

    def set_snapshots(self, snapshots: List[Any]) -> None:     # :124-125 -> rebuild bounded deque
        self._snapshots = list(snapshots)

    def snapshot_count(self) -> int:                           # :127-130 — UNCHANGED (len(deque) is O(1))
        return len(self._snapshots)

    def get_latest_snapshot(self) -> Optional[Any]:            # :132-135 — UNCHANGED (deque[-1] is O(1))
        return self._snapshots[-1] if self._snapshots else None
```

**Required changes (D-03):**
1. `import collections` / `from collections import deque` at top (currently only `decimal`, `typing`, `..base`).
2. `__init__`: take a `max_snapshots: int = 10000` param; `self._snapshots: deque[Any] = deque(maxlen=max_snapshots)`;
   store `self._max_snapshots = max_snapshots` for `set_snapshots` rebuild.
3. `get_snapshots()` -> **`return list(self._snapshots)`** (materialized copy, NOT the live deque).
   **⚠ This DIVERGES from the 4 sibling accessors' "return the live container" rule** — and that
   divergence is INTENTIONAL (D-03): (a) handing a live `deque(maxlen)` to a reader is a
   mutation-during-iteration hazard under the live RLock model; (b) keeping the `-> List[Any]` ABC
   return type intact (a `deque` would force a `Sequence` type-lie since `deque` raises on slices).
   Update the inline comment to note "materialized list copy (D-03): the deque is bounded and
   auto-evicts; readers get a stable snapshot, never the live container."
4. `set_snapshots()` -> **`self._snapshots = deque(snapshots, maxlen=self._max_snapshots)`**
   (Pitfall 2: reassigning a plain `list` silently drops `maxlen`). RESEARCH recommends option (a):
   plumb `max_snapshots` through `__init__` so both the init-deque and the rebuild share one bound.
5. `add_snapshot` / `snapshot_count` / `get_latest_snapshot` -> bodies UNCHANGED (all O(1) on deque).

---

### `itrader/portfolio_handler/storage/storage_factory.py` — D-03 `maxlen` plumbing (factory) — **4 SPACES**

**Analog:** `create()` :49-50 and `create_in_memory()` :76 — both `return InMemoryPortfolioStateStorage()`.

**Targets:**
```python
        if environment in ('backtest', 'test'):
            return InMemoryPortfolioStateStorage()          # :50
    ...
        return InMemoryPortfolioStateStorage()              # :76
```

**Change:** if `InMemoryPortfolioStateStorage.__init__` gains a required/optional `max_snapshots`,
these two construction sites must pass it (or rely on the default `10000`). RESEARCH Open Question 1:
`max_snapshots=10000` lives on `MetricsManager.__init__` (:116), constructed separately from storage.
Default-to-10000 in the storage `__init__` keeps both call sites unchanged AND matches the
`MetricsManager` value byte-for-byte. Planner reads the `MetricsManager.__init__` storage-resolution
path (:96-108, `getattr(portfolio, "state_storage", None)` / `PortfolioStateStorageFactory.create("backtest")`)
to confirm the default flows through.

---

### `itrader/portfolio_handler/base.py` — D-03 ABC docstring touch (ABC / storage seam) — **TABS**

**Analog:** the 4 sibling abstract accessors in this file :320-369.

**Targets — `get_snapshots` :321-337 and `set_snapshots` :339-348 docstrings.** Method SIGNATURES
and `-> List[Any]` return type stay UNCHANGED (D-03 keeps the seam contract; consumers untouched).
Only the docstring prose changes.

Current `get_snapshots` docstring (:323-330) says "the backtest backend returns the live internal
container (no per-tick copy)". Under D-03 the snapshot accessor is the ONE that returns a
**materialized list copy** (not the live deque). Update its docstring to note: deque-backed storage,
`get_snapshots()` returns `list(self._snapshots)` (a materialized copy — readers get a stable
snapshot; the live deque is never handed out per the live-iteration / sliceability rationale).
Keep TABS. Do NOT touch the other four accessors' docstrings.

---

### `itrader/portfolio_handler/metrics/metrics_manager.py` — D-02 + D-03 + D-04 (manager, transform/batch) — **4 SPACES**

This file is the focus of three decisions. All three are DELETIONS of cache/log/trim plumbing; the
calculation logic stays. **4 SPACES throughout.**

#### D-02 — delete the per-bar debug log (lines :194-198)
```python
        self.logger.debug("Portfolio snapshot recorded",
            timestamp=timestamp.isoformat(),
            total_equity=str(total_equity),
            total_pnl=str(total_pnl)
        )
```
Delete entirely. The `PortfolioSnapshot` already stores the raw `Timestamp` (:163) and
`total_equity`/`total_pnl` are snapshot fields — the log records nothing not already persisted; its
only cost is the per-bar `isoformat()` + two `str()`. No money/Decimal float conversion is added or
removed from any stored/reported value. **Pattern:** intentional removal recorded as a decision
(SPEC Req 2 explicitly permits this). No structlog level-guard (rejected in D-02).

#### D-03 — delete the per-bar trim block (lines :181-184) + its size guard
```python
        if self._storage.snapshot_count() > self.max_snapshots:
            self._storage.set_snapshots(
                self._storage.get_snapshots()[-self.max_snapshots:]
            )
```
Delete the whole block — the deque `maxlen` IS the trim now. This removes the ONLY per-bar
`get_snapshots()`/`set_snapshots()` caller (RESEARCH Gap B verified). `snapshot_count()` survives
for the `== 0` empty-guards at :213 and :452 (NOT trim). `self.max_snapshots` (:116) stays for the
deque maxlen plumbing.

#### D-04 — remove the in-memory metrics cache (exact line-list from RESEARCH Gap C)
| Lines | Content | Action |
|-------|---------|--------|
| :110-112 | `# Performance metrics cache` + `self._metrics_cache` + `self._cache_timestamp` | DELETE fields + comment |
| :115 | `self.cache_duration_minutes = 5  # ...` | DELETE (only feeds `_is_cache_valid`) |
| :124 | `cache_duration=self.cache_duration_minutes,` inside `logger.info(...)` | DELETE kwarg (KEEP the `logger.info`, KEEP `max_snapshots=`) |
| :186-192 | WR-03 invalidate comment + `self._metrics_cache.clear()` + `self._cache_timestamp.clear()` | DELETE block |
| :271 | `cache_key = f"{period.name}_{end_date.date()}"` | DELETE (now unused) |
| :273-275 | `# Check cache first` + `if self._is_cache_valid(cache_key): return self._metrics_cache[cache_key]` | DELETE read |
| :295-297 | `# Cache results` + populate `_metrics_cache[cache_key]` + `_cache_timestamp[cache_key] = datetime.now()` | DELETE populate (kills wall-clock `datetime.now()`) |
| :537-543 | the entire `_is_cache_valid` method | DELETE (kills its wall-clock `datetime.now()` TTL) |

**Lines that SIMPLIFY (stay):** `calculate_performance_metrics` (:242-299) keeps end_date resolution
(:254-269), `_get_period_start_date`/`_get_snapshots_for_period`/`< 2`-guard/`_calculate_metrics_from_snapshots`
(:277-293), and `return metrics` (now the freshly computed object every call). **The calculation is
NOT removed — only the memoization layer.** `calculate_performance_metrics` has ZERO production
callers (only `export_metrics_to_dict` :455, off-hot-path), so recompute-on-call is free.

**Import check after D-04:** keep `from datetime import datetime, timedelta` (still needed for type
hints + timedelta math); confirm no orphaned `datetime.now` survives (the only two `datetime.now()`
sites were :297 and :542, both deleted) — consistent with WR-01's no-wall-clock guard 15 lines above.

---

## Shared Patterns

### Bounded-memory primitive (cross-cutting, the spine of D-01 + D-03)
**Sources:** `functools.lru_cache(maxsize=32)` (D-01) and `collections.deque(maxlen=N)` (D-03) — both stdlib, both inherently bounded.
**Apply to:** `_aligned` (D-01); `_snapshots` (D-03).
**Rule (Don't Hand-Roll):** never a manual `dict`+eviction loop or a `list`+slice-trim — the
slice-trim IS the hotspot. Both primitives are O(1) and auto-bounded.

### Audit-the-invariant + dedicated equivalence/regression test — NO hot-path runtime guard
**Sources:** Phase 3 D-03, Phase 4 D-06/D-07, Phase 6 D-08/D-16. In-tree templates:
- `tests/unit/portfolio/test_state_storage.py:137-195` — the object-identity / count-last accessor regression locks (closest precedent for the D-03 snapshot work).
- `tests/unit/portfolio/test_metrics_manager.py:133-190` `test_trim_uses_snapshot_accessors` — monkeypatch `get_snapshots` to a `_boom` sentinel, count the consumed accessors; "prove the cost is gone without re-paying it on the hot path."
- `tests/unit/price/test_bar_feed.py::test_zero_resample_calls_on_per_tick_path` — the idiom the above cites.
**Apply to:** all behavior-preservation proofs for D-01/D-03/D-04.
**Anti-pattern:** a per-tick `assert` that re-evaluates `_aligned` "to prove equivalence" — re-pays the removed cost. Use a dedicated equivalence test.

### Determinism / no-wall-clock
**Source:** the WR-01 guard in `metrics_manager.py:138-147`.
**Apply to:** D-01 (memo keys are deterministic business values — `event.time` + `timedelta`, never wall clock); D-04 (actively REMOVES the wall-clock `datetime.now()` TTL and cache stamp).

### Decision-tag comment style (load-bearing)
**Source:** every touched file. Comments cite the phase-local tag (D-01..D-04) + the precedent/evidence + the byte-exact rationale. Preserve this — the tags are references to planning artifacts.

### Gate (a) byte-exact / Gate (b) thermal-aware
**Source:** `tests/integration/test_backtest_oracle.py` (134 / `46189.87730727451`), `Makefile` perf-* targets, `perf/runners/run_w1_benchmark.py`.
**Apply to:** the phase exit. Gate (a) = oracle byte-exact + `mypy --strict` + determinism double-run. Gate (b) = same-machine A/B + Scalene CPU-share; re-freeze only on a verified-cool machine (memory `v15-perf-gateb-thermal-drift`).

---

## Test Files — Pattern Assignments

### `tests/unit/outils/test_time_parser.py` (D-01, T1-T3) — EXISTING file, EXTEND
**Status:** EXISTS (RESEARCH said "new file" — INCORRECT; the dir `tests/unit/outils/` and this file
both exist; line 26-30 already `from itrader.outils.time_parser import (_aligned, check_timeframe, to_timedelta)`).
**Analog:** the existing parametrized `_aligned`/`check_timeframe` characterization tests in the same file.
**Add (per RESEARCH Gap D):**
- **T1** `_aligned(ts, tf)` returns identical results for a sampled grid (daily-00:00, intraday-non-aligned, weekly, 7h-non-divisor — mirror the docstring examples at time_parser.py:127-145).
- **T2** `_aligned.cache_info()` shows `maxsize == 32`; repeated identical `(ts, tf)` produce `hits >= 1` (memo is wired, not a no-op).
- **T3** after many distinct `(ts, tf)`, `_aligned.cache_info().currsize <= 32` (never grows unbounded — SPEC bounded-memory).

### `tests/unit/portfolio/test_state_storage.py` (D-03, T4 update + T5 add) — **4 SPACES**
**Analog:** `test_get_snapshots_returns_live_container_no_copy` :174-178 and `test_snapshots_replaceable_for_size_trim` :128-134.
- **T4 — MUST UPDATE `test_get_snapshots_returns_live_container_no_copy` :174-178.** Currently asserts
  `get_snapshots() is get_snapshots()` (object IDENTITY). D-03's `list(self._snapshots)` returns a NEW
  object each call -> this flips to FALSE (Pitfall 1). Convert to value-equality (`==`) + rename
  (the materialized copy is intentional). This is the divergence-from-the-4-siblings point — note in
  the test docstring that snapshot is the ONE accessor that copies (live-iteration/sliceability rationale).
- **T5 — ADD** a `> max_snapshots` last-N retention test: build a deque with a small `maxlen`, push
  `maxlen + k`, assert `snapshot_count() == maxlen`, `get_latest_snapshot()` is the newest, and
  `get_snapshots()[0]` is the `(k+1)`-th pushed (oldest auto-evicted). Mirror the in-file accessor-test shape.
- **Note** `test_snapshots_replaceable_for_size_trim` :128-134 calls `set_snapshots([3,4])` — verify it
  still passes once `set_snapshots` rebuilds a `deque(snapshots, maxlen=...)` (value-equality holds; `[3,4]` is within maxlen).

### `tests/unit/portfolio/test_metrics_manager.py` (D-04 fallout + D-03 T6) — **4 SPACES**
**Analog:** `test_trim_uses_snapshot_accessors` :133-190 (the per-tick-no-copy regression lock).
**Breaking tests to DELETE/REWRITE (the suite fails hard under `filterwarnings=["error"]`+strict-config on `AttributeError`):**
- `test_metrics_manager_initialization` :51-55 — `assert mm.cache_duration_minutes == 5` (:55) -> DELETE that assertion (attr removed by D-04).
- `test_performance_metrics_caching` :284-301 — `assert len(mm._metrics_cache) == 1` (:301) -> DELETE the cache assert; KEEP `metrics1.total_return == metrics2.total_return` (recompute determinism); RENAME to e.g. `test_performance_metrics_recompute_stable`.
- `test_metrics_cache_invalidation` :500-522 — asserts `len(mm._cache_timestamp) == 1`/`== 0` (:513/:522) -> DELETE or rewrite as recompute-stability (no cache to invalidate).
- **ADD T7:** `calculate_performance_metrics` returns equal metric values on repeated calls after D-04, and `assert not hasattr(mm, "_metrics_cache" | "_cache_timestamp" | "_is_cache_valid" | "cache_duration_minutes")` (cache truly removed).
- **T6 — keep `test_trim_uses_snapshot_accessors` :133-190 GREEN** (trivially true now: the trim block is deleted, so `set_snapshots` is never called on the per-tick path; the `_boom` sentinel on `get_snapshots` never fires).

> **⚠ 5TH BREAKING TEST the RESEARCH "four breaking tests" list MISSED — `test_snapshot_history_limit`
> :112-130.** It sets `mm.max_snapshots = 5` AFTER construction, then pushes 10 snapshots and asserts
> `len(mm._storage.get_snapshots()) == 5` and `get_snapshots()[0].total_equity == Decimal("105000.0")`.
> Under D-03 the deque's `maxlen` is FIXED at construction (10000) and reassigning `mm.max_snapshots`
> does NOT re-bound the live deque -> this test will FAIL (all 10 retained). **The planner MUST
> rewrite it** to set the bound at storage-construction time (construct the storage / `MetricsManager`
> with `max_snapshots=5`) rather than mutating the attribute after the fact. Without this, Gate (a)'s
> suite goes red. This is a direct consequence of moving the trim bound from a mutable manager attr
> into the deque `maxlen` — flag it prominently in the D-03 plan.

---

## No Analog Found

None. Every change mirrors an established in-tree pattern (the twice-used `@functools` memo; the
storage-seam accessor contract; the audit-the-invariant regression-test precedent). RESEARCH's
Code-Examples / external library claims are NOT needed — the codebase analogs cover 8/8 files.

## Metadata

**Analog search scope:** `itrader/outils/`, `itrader/price_handler/feed/`, `itrader/strategy_handler/`,
`itrader/portfolio_handler/{metrics,storage,base}`, `tests/unit/{outils,portfolio}`.
**Files scanned (read):** `time_parser.py`, `bar_feed.py`, `strategy_handler/base.py`,
`metrics_manager.py`, `in_memory_storage.py`, `portfolio_handler/base.py`, `storage_factory.py`,
`test_time_parser.py`, `test_state_storage.py`, `test_metrics_manager.py`.
**Pattern extraction date:** 2026-06-25
