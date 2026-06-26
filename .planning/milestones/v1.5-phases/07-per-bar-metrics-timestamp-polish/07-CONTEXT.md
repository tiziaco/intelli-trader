# Phase 7: Per-Bar Metrics & Timestamp Polish - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Cut four profiler-confirmed per-bar CPU hotspots (~24% W1 combined) on the backtest hot path —
`_aligned` timestamp math, a per-bar `debug`-log's eager arg evaluation, the snapshot-retention
full-copy trim, and the per-bar metrics-cache clear — with **ZERO change to engine numbers**. The
SMA_MACD oracle stays byte-exact (134 trades / `final_equity 46189.87730727451`). This is a
**byte-exact** phase (NOT a re-baseline like Phase 5) — none of the four targets touch money,
positions, orders, or fills; they are timestamp / metrics / reporting surfaces only.

Requirements are LOCKED by `07-SPEC.md` (ambiguity 0.11). This discussion covered the **HOW**
(implementation) decisions only — the four locked WHATs are not re-opened here.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**4 requirements are locked.** See `07-SPEC.md` for full requirements, boundaries, and acceptance
criteria. Downstream agents MUST read `07-SPEC.md` before planning or implementing — requirements
are not duplicated here.

**In scope (from SPEC.md):**
- `_aligned` recomputation elimination (`itrader/outils/time_parser.py`).
- Removing/guarding the per-bar `record_snapshot` debug-log argument evaluation (`metrics_manager.py`).
- Snapshot retention → bounded deque + trim-block removal (`portfolio_handler/storage/in_memory_storage.py`, `metrics_manager.py`).
- Eliminating the per-bar `_metrics_cache`/`_cache_timestamp` clear churn while keeping the cache bounded (`metrics_manager.py`).
- A W1 re-profile + clean-benchmark re-freeze validating the reclaim.

**Out of scope (from SPEC.md):**
- `msgspec.Struct` dataclass/event-model migration (~10%) — separate measure-first spike.
- `strategy_handler/base.py` `to_dict`/`_json_safe` serialization (~8.5%, diffuse) — separate item.
- Event-bus `queue.Queue` → `deque` — explicitly rejected (live mode needs the lock).
- Hot-path `warning()`/`info()` log volume — a W1-coverage artifact / logging-policy question.
- Any change to money/Decimal, order/fill/position logic, or the matching engine — no numeric surface.
- Changing `max_snapshots` (stays 10000) or snapshot semantics beyond the storage structure.

</spec_lock>

<decisions>
## Implementation Decisions

> All four are HOW decisions on top of the locked SPEC requirements. Decision tags are
> phase-local (`D-01`..`D-04`, PERF-07). Each cites the precedent or evidence it derives from.

### Item 1 — `_aligned` memoization (Requirement 1)
- **D-01 (bounded `@functools.lru_cache(maxsize=N)` on the module-level `_aligned`):** Memoize
  `_aligned(ts, tf)` (`time_parser.py:127-157`) following the **established codebase pattern** —
  module-level pure function + `@functools` decorator + decision-tag comment, used twice already:
  `bar_feed.py:86` `@functools.cache def _offset_alias(timeframe)` (Phase 6 D-01/PERF-06) and
  `strategy_handler/base.py:106` `@cache def _declared_hints(cls)` (Phase 4 D-05/PERF-04). **The one
  adaptation:** use bounded `lru_cache(maxsize=N)` rather than bare `@functools.cache`, because
  `_aligned`'s `(ts, tf)` key space is **unbounded** (`ts` is a per-bar timestamp that grows without
  limit — ~17.3k distinct in W1) — unlike the two precedents whose key spaces (timeframes / strategy
  classes) are inherently bounded. Bare `cache` would grow unbounded → violates the SPEC
  bounded-memory constraint. The realizable hits are **intra-tick** (the same `(ts, tf)` repeats
  across all strategies/symbols within one TIME event; across ticks `ts` advances and never recurs),
  so a **small** `maxsize` captures ~100% of the benefit while staying bounded. Function BODY stays
  byte-unchanged (only the decorator + comment added); `lru_cache` does not cache exceptions (the
  function raises nothing, but consistent with the `_offset_alias` precedent's guarantee). Keys are
  deterministic business values (no wall-clock). **Researcher pins `N`.**
  **Rejected:** bare `@functools.cache` (unbounded → SPEC violation on the unbounded `ts` key);
  instance-bounded dict memo (no precedent; extra plumbing for a module-level free function);
  compute-once-per-tick caller restructure (unnecessary blast radius when a decorator suffices).

### Item 2 — per-bar debug-log disposition (Requirement 2)
- **D-02 (remove the `logger.debug` snapshot call entirely):** Delete `metrics_manager.py:194-198`.
  The `PortfolioSnapshot` already stores the raw `Timestamp` (line 163), and `total_equity` /
  `total_pnl` are snapshot fields — the debug log captures **nothing not already recorded**, so its
  only effect is the per-bar `isoformat()` + two `str()` conversions (~8.6% W1 CPU). Removal kills the
  cost fully with no gating complexity. SPEC Requirement 2 explicitly permits intentional removal
  "recorded as a decision." No money/Decimal float conversion is introduced or removed from any
  stored/reported value.
  **Rejected:** guard with a structlog level check (keeps a per-bar level test + the call, for a log
  that only duplicates already-stored snapshot data; structlog level-gating is also less clean than
  stdlib `isEnabledFor`).

### Item 3 — snapshot retention → bounded deque (Requirement 3)
- **D-03 (`deque(maxlen)` internally; `get_snapshots()` returns `list(...)`):** Change
  `PortfolioStorage._snapshots` (`in_memory_storage.py:45`) from `list` to
  `collections.deque(maxlen=max_snapshots)` — O(1) append + automatic oldest-eviction. **Remove the
  per-bar trim block** (`metrics_manager.py:181-184`) and its `snapshot_count()` size guard (the
  deque's `maxlen` *is* the trim now). `get_snapshots()` returns **`list(self._snapshots)`** (a
  materialized copy), NOT the live deque.
  **Why list-copy, not the live deque** (architectural, two reasons): (1) **Uniform storage seam** —
  all five ABC accessors (`get_positions`→Dict, `get_closed_positions`/`get_transaction_history`/
  `get_cash_operations`/`get_snapshots`→`List`, see `base.py:67-335`) share one contract: typed
  `List`/`Dict`, "live internal container, callers MUST NOT mutate — copy yourself (D-19/D-03)".
  Returning a `deque` would force `get_snapshots` alone to diverge to `Sequence[Any]`, breaking the
  seam's uniformity AND advertising a type-lie (`Sequence.__getitem__` implies slicing; `deque`
  raises on slices). (2) **Live-mode safety** — a `deque(maxlen)` auto-evicts on append; handing the
  *live* deque to a reader under the live `RLock` model is a mutation-during-iteration hazard. A
  `list()` snapshot is immune.
  **Why this is free on perf** — the performance win (Requirement 3, ~5% W1) comes **entirely** from
  `maxlen` killing the per-bar O(max_snapshots) trim copy. `get_snapshots()` is **NOT on the per-bar
  path**: the only per-bar metrics caller is `record_snapshot` (via `record_metrics`), which stops
  calling `get_snapshots()` once the trim is removed (verified). All remaining `get_snapshots()`
  callers (`metrics_manager.py:257/311/371/431/558/564`, `reporting/frames.py:72`) are read/reporting
  paths with **zero per-bar callers** — so the `list()` copy runs only a handful of times per run,
  immaterial to W1. Consumers use only `[-1]`, `[0]`, iterate, `len`, comprehension — **no `[start:end]`
  slice survives** the trim removal, so a list is byte-identical to today. Update only the
  `get_snapshots` docstring line (note deque + materialized list).
  **Rejected:** return the deque directly (saves only off-hot-path read copies — no W1 benefit — at
  the cost of seam uniformity, a `Sequence` sliceability type-lie, and the live iteration hazard).

### Item 4 — metrics-cache disposition (Requirement 4)
- **D-04 (REMOVE the in-memory `_metrics_cache`/`_cache_timestamp` entirely):** Delete the per-bar
  `clear()` churn (`metrics_manager.py:191-192`, ~2.9% W1), the cache dicts (`:111-112`), the
  populate/read sites (`:274-275`, `:296-297`), and `_is_cache_valid` (`:537-543`) — including its
  wall-clock `datetime.now()` TTL. `calculate_performance_metrics` recomputes from the snapshot
  history on each call. **The calculation is NOT removed — only the memoization layer is.**
  **Evidence:** `calculate_performance_metrics` (the *only* `_metrics_cache` consumer) has **zero
  callers** anywhere in `itrader/` or `tests/` today; the only per-bar metrics call is
  `record_snapshot`. So the cache is **inert in backtest** (cleared every bar, never read) and
  **broken for live** (the wall-clock 5-min TTL can serve stale metrics after new bars, and the
  per-bar `clear()` defeats it anyway). Removing it eliminates the hotspot, the wall-clock
  determinism smell (consistent with the WR-01 no-wall-clock guard 15 lines above), AND the WR-03
  unbounded-growth class — and changes nothing for the actual run. End-of-backtest metrics remain
  fully intact (recompute once, off the hot path).
  **Owner decision (the tiebreaker vs the in-memory "fix"):** live metrics will be a **Postgres-backed
  time-series**, not an in-memory cache — the long live series does not belong in process memory. So
  the in-memory cache is the wrong layer for the live "metrics-at-a-moment" use case; that need is
  deferred to the Live Trading milestone (see Deferred Ideas).
  **Rejected:** version/generation-invalidated bounded in-memory cache (the correct shape *if* live
  polling were served in-memory — but the owner will persist live metrics in Postgres, making the
  in-memory cache redundant; deferred to N+4).

### Claude's Discretion
- `maxsize=N` for the `_aligned` `lru_cache` (D-01) — within "bounded + captures the intra-tick
  repeats." Researcher pins against the W1 tick/symbol fan-out.
- Exact deletion shape for the cache removal (D-04) — which private helpers/fields disappear vs which
  `calculate_performance_metrics` lines simplify — within "no behavior change to returned metrics."
- The behavior-preservation proof shape (see Established Patterns) — a dedicated equivalence test
  per the audit-the-invariant precedent; placement/assertions the planner's, within byte-identity.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked requirements — read FIRST
- `.planning/phases/07-per-bar-metrics-timestamp-polish/07-SPEC.md` — the 4 locked requirements,
  boundaries, constraints, acceptance criteria. **MUST read before planning.**

### Target code — the files this phase edits (⚠ see indentation note in Code Insights)
- `itrader/outils/time_parser.py` — `_aligned` at **:127-157** (the `astimezone`/`replace`/
  `total_seconds`/modulo to memoize, D-01); `check_timeframe` at :159-174 delegates to it. **TABS.**
- `itrader/portfolio_handler/metrics/metrics_manager.py` — `record_snapshot`: the trim block
  **:181-184** (remove, D-03), the per-bar cache `clear()` **:191-192** + cache fields **:111-112** +
  populate/read **:274-275/:296-297** + `_is_cache_valid` **:537-543** (remove, D-04), the debug log
  **:194-198** (remove, D-02). **4 SPACES.**
- `itrader/portfolio_handler/storage/in_memory_storage.py` — `_snapshots` **:45** (→ `deque(maxlen)`,
  D-03), `add_snapshot` **:117-118**, `get_snapshots` **:120-122** (→ `list(...)`), `set_snapshots`
  **:124-125**, `snapshot_count` **:127-130**, `get_latest_snapshot` **:132-135**. **4 SPACES.**
- `itrader/portfolio_handler/base.py` — the storage-seam ABC: `get_snapshots`/`set_snapshots`/
  `snapshot_count`/`get_latest_snapshot` contracts **:322-366** and the uniform "live container /
  don't mutate" pattern across all five accessors **:67-335** (D-03 rationale). **TABS.**

### Pattern precedents — the established memoization convention (D-01)
- `itrader/price_handler/feed/bar_feed.py` — **:81-87** `@functools.cache def _offset_alias(timeframe)`
  (Phase 6 D-01/PERF-06): module-level pure fn + decorator + decision-tag comment; "body byte-unchanged,
  cache does NOT cache exceptions." The direct template for D-01 (made bounded for the unbounded key).
- `itrader/strategy_handler/base.py` — **:94-108** `@cache def _declared_hints(cls)` (Phase 4
  D-05/PERF-04): the second instance — "thread-safe (locks internally) for live mode; bounded key
  count; no manual invalidation."

### Consumers / call graph (D-03/D-04 evidence)
- Per-bar metrics caller (the hot path): `itrader/trading_system/backtest_runner.py:153` +
  `itrader/trading_system/live_trading_system.py:366` → `portfolio.record_metrics(time)` →
  `record_snapshot` (`portfolio.py:583`). The ONLY per-bar metrics call.
- `get_snapshots()` read callers (NONE per-bar): `metrics_manager.py:257/311/371/431/558/564`,
  `itrader/reporting/frames.py:72` (iterate-only).
- `calculate_performance_metrics` (the only `_metrics_cache` consumer): **zero callers** in
  `itrader/` or `tests/` — the D-04 "cache is inert" evidence.

### Gate (a) — correctness lock (byte-exact, held not changed)
- `tests/integration/test_backtest_oracle.py` — byte-exact SMA_MACD oracle (134 /
  `46189.87730727451`). (Per memory `oracle-test-location`: this is the oracle; `tests/golden` is
  artifacts, 0 tests collected.)

### Gate (b) — perf harness + baseline
- `Makefile` — `perf-w1` (gated `--check`), `perf-profile` (Scalene), `perf-baseline` (re-freeze W1).
- `perf/runners/run_w1_benchmark.py` — the W1 runner (`--check`/`--json`/`--baseline-out`).
- `perf/results/W1-BASELINE.json` — the frozen W1 reference (re-frozen after this phase on a cool
  machine). `perf/results/scalene-w1.json` — the logging-disabled re-profile that surfaced the four
  hotspots.

### Milestone scope + gate definition
- `.planning/REQUIREMENTS.md` — **PERF-07** + the milestone gate (a)/(b) definition.
- `.planning/ROADMAP.md` — Phase 7 entry + 6 Success Criteria + the byte-exact framing.
- `.planning/STATE.md` — milestone gate (a)/(b) full text.

### Precedent CONTEXT (the proof pattern + thermal-drift gate)
- `.planning/phases/06-bar-feed-window-copies-optional-slip-able/06-CONTEXT.md` — the
  audit-the-invariant + dedicated-equivalence-test pattern (D-08/D-16) and the gate-(b)
  cool-machine / same-machine-A-B attribution.
- `.planning/phases/03-running-pnl-accumulator/03-CONTEXT.md`,
  `.planning/phases/04-hot-path-discipline/04-CONTEXT.md` — D-03 / D-06-07 behavior-preservation
  drift-lock precedents (prove equivalence without re-paying the cost on the hot path).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The `@functools` memoization convention exists and is twice-used** (`_offset_alias`,
  `_declared_hints`) — D-01 mirrors it exactly (bounded variant). No new pattern to invent.
- **`collections.deque(maxlen=...)`** is the stdlib bounded structure Requirement 3 names — O(1)
  append + auto-evict, drop-in for the `list` once consumers are confirmed slice-free (they are).
- **The W1 harness exists** (Phase 1): `run_w1_benchmark --check`/`--json`, Scalene profile command,
  `perf-baseline` re-freeze — gate (b) needs no new tooling, only a re-profile + re-freeze.

### Established Patterns
- **Audit-the-invariant + dedicated equivalence/regression test, NO hot-path runtime guard**
  (Phase 3 D-03, Phase 4 D-06/D-07, Phase 6 D-08/D-16). Reuse for behavior-preservation proof: a
  test asserting `_aligned` output unchanged for sampled `(ts, tf)`, `get_snapshots()` byte-identical
  pre/post deque, last-`max_snapshots` retention on a >10k-bar run, and metrics values unchanged
  post cache-removal. No per-tick `assert` that re-pays the removed cost.
- **Gate (a) byte-exact / Gate (b) measurable W1 + re-freeze on a verified-COOL machine** via
  same-machine A/B attribution (memory `v15-perf-gateb-thermal-drift`) — never trust the frozen
  baseline compare on a throttled box.
- **Determinism:** no wall-clock — D-04 actively *removes* a wall-clock `datetime.now()` TTL; D-01's
  memo keys are deterministic business values.

### Integration Points
- All changes are internal to `time_parser._aligned`, `MetricsManager.record_snapshot` /
  `calculate_performance_metrics`, and `PortfolioStorage` snapshot accessors. No event-queue,
  handler-routing, or cross-domain signature change. `get_snapshots()` keeps its `-> List[Any]`
  contract (D-03), so the ABC seam and all consumers are untouched.
- ⚠️ **INDENTATION HAZARD — SPEC IS WRONG HERE, VERIFIED 2026-06-25.** The SPEC constraint line
  claims `metrics_manager.py` / `in_memory_storage.py` use tabs. They DO NOT — both are **4 SPACES**
  (644 / 85 indented lines, zero tab-led lines). `time_parser.py` and `portfolio_handler/base.py`
  are **TABS**. Per-file: `time_parser.py` → TABS; `base.py` → TABS; `metrics_manager.py` → 4 SPACES;
  `in_memory_storage.py` → 4 SPACES. **Match each file; do NOT follow the SPEC's indentation claim.**

</code_context>

<specifics>
## Specific Ideas

- The win is **byte-exact** end-to-end — every target is a timestamp/metrics/reporting surface; no
  stored or reported numeric value (Decimal or float) changes. The oracle (134 /
  `46189.87730727451`) is the hard lock.
- D-01's leverage is **intra-tick** repeats (`(ts, tf)` identical across strategies/symbols within
  one TIME event); a small bounded `maxsize` is sufficient — an unbounded cache adds dead entries
  with zero extra hits.
- D-04 removes a genuine **internal inconsistency**: `calculate_performance_metrics` *raises* to
  avoid a wall-clock `end_date` (WR-01) then memoizes the result behind a wall-clock TTL. Removal
  resolves it; the live replacement is Postgres, not a fixed in-memory cache.

</specifics>

<deferred>
## Deferred Ideas

- **Postgres-backed live metrics persistence + at-a-moment query** — replaces the in-memory
  `_metrics_cache` removed in D-04. The live metrics time-series can grow large and does not belong
  in process memory; persist it in Postgres and serve at-a-moment per-portfolio metrics queries from
  there. **Owner decision (2026-06-25).** Tackle in **N+3b Persistence / N+4 Live Trading
  Readiness** (per ROADMAP). *(Captured here — `gsd-sdk todo.add` was unavailable in this session;
  promote to a todo / roadmap backlog item when convenient.)*
- **`msgspec.Struct` event-model migration, `base.py` `to_dict`/`_json_safe` serialization, hot-path
  log-volume policy** — explicit SPEC out-of-scope items; separate measure-first spikes / a logging
  policy decision, not this byte-exact phase.

</deferred>

---

*Phase: 07-per-bar-metrics-timestamp-polish*
*Context gathered: 2026-06-25*
