# Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able) — Research

**Researched:** 2026-06-24 (PIVOT re-research — supersedes the view-era body below)
**Domain:** monotonic incremental cursor over a tz-aware DatetimeIndex; pandas 2.3.3 `.iloc` slice cost; structlog eager-f-string elimination; gate-(b) re-freeze mechanics
**Confidence:** HIGH (the two load-bearing claims — forward-cursor byte-identity to `searchsorted(side="right")` and the int64 comparison cost — are `[VERIFIED: empirical test]` against the pinned venv, not training data)

> **PIVOT NOTICE.** This research is scoped to the **post-profile pivot** (D-10–D-16). The
> view/alias copy-reduction mechanism (D-01/D-07/D-09) **already shipped in 06-01** and is **kept as
> the foundation** (D-12). The view-era Patterns 1–3 from the previous revision of this file are
> reproduced at the very bottom under **"SHIPPED in 06-01 (historical — do NOT re-plan)"** for the
> record; do not turn them into tasks. The NEW primary lever is a monotonic incremental cursor
> (D-10) + a cheaper-slice evaluation (D-11), prepped by a denominator cleanup (D-13) and gated by a
> re-freeze + verdict (D-14/D-15) with a drift-test extension (D-16).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (active pivot block — verbatim)
- **D-10 (monotonic incremental-cursor `window()` — primary lever; reverses D-01's cursor rejection):** Replace the per-tick `frame.index.searchsorted(cutoff)` (13.2% of W2 CPU) with a cached **per-(ticker, timeframe) cursor** that only steps **forward** from its last position — the backtest `asof` cutoff advances monotonically per series. Cursor is **reset/seek-safe**: a ticker that leaves and re-enters the universe (screener membership), a sparse/gap frame (D-04), or any non-forward `asof` step must NOT leak a future bar — default to a **safe rebuild via `searchsorted`** on any non-monotonic step rather than trusting stale state. Exact reset-trigger/non-monotonic handling (fail-loud vs silent rebuild) is researcher/planner territory within "never leak a future bar." Cutoff stays **exclusive-right** (today's semantics). **Rejected:** "cursor is a microsecond-class gain over O(log n) searchsorted" — empirically wrong (searchsorted at 13.2%).
- **D-11 (cursor + cheaper slice together):** Beyond the cursor, also pursue a **cheaper slice path** to cut the per-tick `iloc[start:pos]` view construction (7.9% of W2 CPU). **Byte-identity (dtype, tz-aware `DatetimeIndex`, column set + order) is the HARD constraint** (carries D-07); exact lower-level construction is researcher/planner territory. Return type **stays `pd.DataFrame`**. **Rejected:** searchsorted-only, leaving 7.9% on the table.
- **D-12 (keep 06-01 as foundation):** 06-01 (read-only view + alias memo + non-writeable master frames, `9168cae`) is **kept** — a real look-ahead-safety improvement AND the read-only master is the foundation the cursor builds on. The D-08 drift test carries forward (extended by D-16). **Rejected:** reverting 06-01 to rebuild from base.
- **D-13 (clean the W2/W1 denominator BEFORE gating — prep step):** **(1)** remove the per-bar `TIME EVENT` debug log (`full_event_handler.py:116` — eager f-string built every bar, discarded at INFO; ~22% W2); **(2)** de-time the **harness overhead** in `run_w2_sweep.py` (tracemalloc + synthetic-bar-gen, ~19%) — capture peak-mem in a **separate pass**, not inside the timed run. NOTE: the log line is **outside `bar_feed.py`** — accepted because it inflates the W2 denominator. **Rejected:** gating on the raw diluted sweep; lowering the threshold.
- **D-14 (re-freeze both baselines on the cleaned engine, then gate the cursor alone):** After D-13, re-freeze **BOTH** `W1-BASELINE.json` and `W2-BASELINE.json` on the cleaned engine, on a **cool machine** (thermal-drift lesson). THEN require the **cursor alone** to clear **≥10% W2 at 50 symbols vs the cleaned W2 baseline**, with **W1 within the existing ±5% soft non-regress band**. W1 stays the **guard, not a win** (cursor adds per-series state with ~no benefit at 1 symbol). **Rejected:** single end-of-phase re-freeze conflating cleanup+cursor; holding the cursor to a W1 improvement.
- **D-15 (ship-and-reframe fallback if <10% honestly):** If the cursor on the cleaned baseline cannot honestly clear ≥10% W2, **ship** the cursor + cleanup anyway, **record the actual W2 % achieved**, and re-frame gate (b) → **"measurable W2 win + W1 non-regress"** (no hard ≥10% kill). The phase is **OPTIONAL/slip-able**. **Rejected:** slipping/reverting on a <10% miss; keep-iterating until ≥10%.
- **D-16 (extend the D-08 drift test — no hot-path runtime guard):** Add to the D-08 drift suite: across sampled ticks, assert the cursor's computed `(start, pos)` **==** a fresh `searchsorted(cutoff)` on the same frame, **plus** the invariant "no bar with `time` > cutoff appears in the returned window." **Zero hot-loop cost** (test-only). **Rejected:** always-on runtime `assert cursor == searchsorted` in `window()` (re-pays the searchsorted the cursor removes); an opt-in debug-flag runtime assert.

### Carried forward unchanged (cursor builds on these — do NOT relitigate)
- **D-02 / D-09** read-only view + non-writeable single-block master at the two build sites — **shipped in 06-01**, kept. The cursor returns the same read-only `iloc` view.
- **D-06** empty-window short-circuit (`frame.iloc[pos:pos]`) — kept; the cursor still short-circuits empty.
- **D-07** byte-identity direction (slice the existing frame + mark read-only; NEVER reconstruct via `pd.DataFrame(...)` that drifts) — the HARD constraint on D-11's cheaper slice.
- **D-03** `window()` only; `megaframe()`/`current_bars()` out of scope.

### Claude's Discretion
- Exact storage shape of the per-(ticker, alias) cursor state and the cheapest correct monotonicity comparison primitive (within byte-identity + never-leak-a-future-bar).
- Exact reset-trigger handling: fail-loud-then-rebuild vs silent-rebuild on a non-monotonic step (within "never leak a future bar").
- Whether D-11's cheaper slice is adopted or the phase ships cursor-only (see Open Question 1 — the cheaper-slice candidates are NOT faster; recommendation is cursor-only).
- Exact placement/shape of the D-16 drift assertions within the existing D-08 suite.

### Deferred Ideas (OUT OF SCOPE)
- `megaframe()` / screener concat optimization (deferred subsystem; inherits the per-symbol cursor for free).
- Removing in-strategy/adapter re-slicing (`catalog.py` `bars[start_dt:]`) — byte-identity risk, outside the feed.
- Any money / float / Decimal change; any oracle re-baseline.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-06 *(optional)* | Per-tick bar-feed window `iloc` frame copies reduced (reusable view / **cached `searchsorted` bounds**), preserving the look-ahead bar-timing contract (the 7 rules in `feed/bar_feed.py`). Hotspot #5, ~4% W1 / ~22% W2. | **Finding A** proves a forward-only cursor over `frame.index.asi8` (int64 ns) + `Timestamp.value` is **byte-identical** to `searchsorted(cutoff, side="right")` for on-grid AND mid-gap cutoffs, at **0.14 µs/tick** vs searchsorted's **4.3 µs** — removes the full 13.2% hotspot. **Finding B** measures every cheaper-slice candidate as ≥ `iloc` (recommend cursor-only — D-15 absorbs the 7.9% miss). **Finding C** confirms the `TIME EVENT` f-string is built eagerly per bar regardless of level. **Validation Architecture** maps the D-16 cursor==searchsorted drift assertions + the re-freeze gate. |
</phase_requirements>

## Summary

The profile reframed the phase: 06-01's view/alias mechanism is **correct and safe but ~0% W2** (the
`.iloc` slice on the homogeneous float64 single-block frame was already a view, and `_offset_alias`
was never expensive). The real reducible per-tick cost is the **fresh `searchsorted` over the full
frame index every tick × every symbol** (13.2% of W2) plus the `iloc` wrapper construction (7.9%).

**The cursor works exactly as D-10 intends, and the byte-identity is provable.** A forward-only
cursor that steps from its last position `while index[pos] <= cutoff` reproduces
`searchsorted(cutoff, side="right")` **byte-for-byte** — verified across 3000 on-grid ticks and 3000
mid-gap cutoffs (`asof - tf + tf_base` landing between bars) `[VERIFIED: empirical test]`. The crucial
implementation detail the planner MUST pin: **compare int64 nanoseconds, not pandas Timestamps.**
`frame.index.asi8` is a **zero-copy cached int64 ns view** of the index (`shares_memory` stable across
calls), and `pd.Timestamp.value` is the matching UTC int64 ns (equal element-wise even for tz-aware
indexes). A single comparison `iv_i8[pos] <= cutoff.value` costs **0.14 µs**; the same comparison
against boxed `frame.index[pos]` Timestamps costs **2.0 µs**, and a per-tick Timestamp→datetime64
conversion (`np.datetime64(cutoff…)`) costs **3.3 µs** — almost as much as the searchsorted it
replaces. **The win lives entirely in the int64 path**; a naïve Timestamp-comparison cursor would
deliver no win.

**The cheaper slice (D-11) is not actually cheaper — recommend cursor-only.** Every alternative to
`frame.iloc[start:pos]` measured **slower**: `pd.DataFrame(values_view_slice, index=…, columns=…)`
reconstruction (which D-07 forbids anyway) is **9.2 µs** vs `iloc`'s **7.3 µs**, and `frame.take(...)`
is **21 µs**. On a single-block float64 frame `iloc` is already a near-optimal view (`_is_view`,
`shares_memory`, inherits `writeable=False`). **There is no provably-byte-identical slice cheaper than
`iloc` on this frame shape.** The honest recommendation (per D-11's own "if it cannot be made
byte-identical, say so") is **keep `iloc` and rely on D-15's ship-and-reframe** for the 7.9% — the
cursor alone removes ~36% of the `window()` path (the 4.3 µs searchsorted out of the ~11.6 µs
search+slice), which is the larger, certain lever.

**The denominator cleanup is real engine + measurement waste, not a metric game.** The per-bar
`self.logger.debug(f"TIME EVENT: {event.time}")` (`full_event_handler.py:116`) builds its f-string
**eagerly in the caller** every bar; the logger's internal `isEnabledFor(DEBUG)` gate fires *after*
the string is already formatted, so `str(event.time)` is paid per tick and discarded at the default
INFO level (the ~22% profile share) `[VERIFIED: code read — logger.py:258-262 gates internally]`. Plain
removal is behavior-neutral (logs are not the oracle; the line is already DEBUG-gated to never print).
The `run_w2_sweep.py` harness mixes `tracemalloc` + synthetic-bar generation into the timed denominator
(~19%); D-13 moves peak-mem capture to a separate pass so the timed wall-clock measures the engine.

**Primary recommendation:** (prep) D-13 — delete the `TIME EVENT` log line and de-time the W2 harness;
re-freeze both baselines on the cleaned engine (cool machine). (core) D-10 — add a per-(ticker, alias)
forward cursor over `frame.index.asi8` compared against `cutoff.value` (int64 ns), with a **safe
`searchsorted` rebuild on any non-monotonic / cold / unknown step** (cursor seek-safety), returning the
same read-only `iloc[start:pos]` view as today. **D-11 — keep `iloc` (cursor-only; the cheaper-slice
candidates are all slower).** D-16 — extend the existing `tests/unit/price/test_bar_feed.py` D-08 suite
with `cursor (start,pos) == fresh searchsorted` across sampled ticks plus a no-future-bar assertion,
driving reset/cold/gap/churn cases. (gate) D-14/D-15 — the existing 06-02 `--check`/`--baseline-out`
harness is reusable as-is; the only change D-13 forces is re-freezing the W2 baseline on the cleaned
engine.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-tick history-window cutoff resolution (the cursor) | Data engine / `price_handler.feed` | — | `BacktestBarFeed.window()` is the single look-ahead-safe slice seam; the cursor state lives in the feed instance, never in a consumer (D-10). |
| Cursor state storage (per-(ticker, alias) last position) | Data engine / `price_handler.feed` instance dict | — | Mirrors the existing per-(ticker, alias) `self._frames` keying — the feed already holds per-series state. |
| Read-only window slice (kept from 06-01) | Data engine / `price_handler.feed` | — | The cursor returns the same `frame.iloc[start:pos]` read-only view off the locked single-block master (D-12). |
| Per-bar flow-log waste removal | Event engine / `events_handler.full_event_handler` | — | The `TIME EVENT` debug log is in the dispatcher, not the feed; D-13 accepts the one-line out-of-`bar_feed.py` scope. |
| Harness denominator hygiene | Perf harness / `perf/runners/run_w2_sweep` | — | tracemalloc + synth-gen are measurement scaffolding, not engine — de-time them (D-13). |
| Cursor correctness proof | Test tier / `tests/unit/price/test_bar_feed.py` | byte-exact oracle (gate a) | D-16 extends the D-08 suite; the oracle is the run-path backstop (D-14). |
| Gate-(b) re-freeze + verdict | Perf harness / `perf/runners/` + `perf/results/` | — | The 06-02 `--check`/`--baseline-out` harness re-freezes on the cleaned engine (D-14/D-15). |

## Standard Stack

No new external packages. This phase uses only the **already-pinned, already-installed** stack.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.3.3 | Frame/window type; `index.asi8` (int64 ns view), `Timestamp.value`, `.iloc` slice, `searchsorted` (rebuild path) | Already the primary OHLCV structure; pinned. `[VERIFIED: venv import]` |
| numpy | 2.2.6 | int64 ns comparison backing the cursor; read-only buffer flag (06-01) | `pandas 2.3.3` requires `numpy>=2.2.3,<2.3`; `2.2.6` installed. `[VERIFIED: venv import]` |
| structlog | 24.4.0 | The logger whose eager-f-string caller waste D-13 removes | `ITraderStructLogger` gates internally; the f-string is built by the caller. `[VERIFIED: code read]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib (no new import expected) | — | Cursor is a plain `dict[tuple[str,str], int]` + int64 compares | No new dependency; the feed already imports `numpy`/`pandas`. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `frame.index.asi8` int64 compare | `frame.index[pos]` pandas-Timestamp compare | **Rejected** — 2.0 µs vs 0.14 µs; a Timestamp-comparison cursor delivers no win (the boxing cost ≈ the searchsorted it replaces). `[VERIFIED: timeit]` |
| `frame.index.asi8` int64 compare | per-tick `np.datetime64(cutoff)` conversion + datetime64 array compare | **Rejected** — the conversion alone is 3.3 µs/tick (≈ searchsorted's 4.3 µs). Use `cutoff.value` (O(1) int64 attribute) instead. `[VERIFIED: timeit]` |
| `frame.iloc[start:pos]` slice (D-11 cheaper path) | `pd.DataFrame(values[start:pos], index=…, columns=…)` | **Rejected** — 9.2 µs vs 7.3 µs AND D-07 forbids reconstruction (drift risk). `[VERIFIED: timeit + assert_frame_equal]` |
| `frame.iloc[start:pos]` slice | `frame.take(range(start,pos))` | **Rejected** — 21 µs (3× slower). `[VERIFIED: timeit]` |

**Installation:** None. No package added or changed.

**Version verification:**
```
pandas 2.3.3   [VERIFIED: poetry run python -c "import pandas; print(pandas.__version__)"]
numpy  2.2.6   [VERIFIED: import numpy]
index.asi8 dtype int64 (UTC ns), zero-copy cached (shares_memory across calls) [VERIFIED]
Timestamp.value == index.asi8[k] for tz-aware index, all k                     [VERIFIED]
```

## Package Legitimacy Audit

> Not applicable — this phase installs **no external packages**. All libraries used (`pandas`,
> `numpy`, `structlog`, stdlib) are already in `pyproject.toml`/`poetry.lock` and verified present in
> the venv. No registry/slopcheck pass required.

## Architecture Patterns

### System Architecture Diagram (the per-tick window path, post-cursor)

```
TimeEvent(T) ─► EventHandler._dispatch ──[D-13: DELETE the eager TIME-EVENT debug f-string]──►
                                            generate_bar_event ─► BarEvent(bars stamped T)
                                            │
                                            ▼
              strategies_handler.calculate_signals  (per subscribed strategy, per ticker)
                                            │  feed.window(ticker, tf, max_window, asof=T)
                                            ▼
        ┌────────────── BacktestBarFeed.window() (post-cursor) ─────────────────┐
        │ 1. alias = _offset_alias(tf)            ◄── memoized (06-01, kept)     │
        │ 2. frame = self._resampled_frame(...)   ◄── locked single-block master │
        │ 3. cutoff = asof - tf + base_tf         ◄── exclusive-right, unchanged  │
        │ 4. cutoff_i8 = cutoff.value             ◄── O(1) int64 ns              │
        │ 5. CURSOR (D-10):                                                       │
        │    key=(ticker,alias); last=self._cursor.get(key)                      │
        │    if last is None or cutoff_i8 < self._cursor_cut[key]:  ◄── NON-MONO │
        │        pos = searchsorted(cutoff,"right")   # SAFE REBUILD (never leak) │
        │    else:                                                               │
        │        pos = last                                                      │
        │        while pos < n and iv_i8[pos] <= cutoff_i8: pos += 1  ◄── 0.14µs │
        │    self._cursor[key]=pos; self._cursor_cut[key]=cutoff_i8              │
        │ 6. start = max(0, pos - max_window)                                    │
        │ 7a. if start >= pos: return frame.iloc[pos:pos]   ◄── empty (D-06)     │
        │ 7b. else: return frame.iloc[start:pos]            ◄── read-only view   │
        │            (KEEP iloc — D-11 cheaper-slice candidates all slower)      │
        └────────────────────────┬───────────────────────────────────────────────┘
                                 ▼  pd.DataFrame (read-only view, byte-identical to today)
              strategy.evaluate(window) ── self.bars = window; self.now = window.index[-1]
                                 │
                                 ▼  adapter.compute(...) reads-only (look-ahead contract preserved)
```

### Component Responsibilities
| Component | File | Change in this phase |
|-----------|------|----------------------|
| `BacktestBarFeed.window()` | `bar_feed.py:427-486` | Add the forward cursor (D-10) replacing the per-tick `searchsorted`; keep the `iloc[start:pos]` read-only view (D-11 cursor-only). **4-space indent.** |
| `BacktestBarFeed.__init__` | `bar_feed.py:199-263` | Initialize the cursor state dicts (`self._cursor: dict[tuple[str,str], int] = {}`, `self._cursor_cut: dict[tuple[str,str], int] = {}`); optionally cache `frame.index.asi8` per frame if not re-derived per call. **4-space.** |
| `EventHandler._dispatch` | `full_event_handler.py:114-116` | **Delete** the `if event.type is EventType.TIME: self.logger.debug(f"TIME EVENT: {event.time}")` block (D-13). **TAB indent — never normalize.** |
| `run_w2_sweep._run_point` | `run_w2_sweep.py:95-131` | De-time: move `tracemalloc.start()`/`get_traced_memory()` OUT of the wall-clock timed region — capture peak-mem in a separate pass (D-13). **4-space.** |
| D-08 drift suite | `tests/unit/price/test_bar_feed.py:343-372` | Extend with D-16 `cursor==searchsorted` + no-future-bar assertions, driving cold/gap/churn cases. **4-space.** |
| `perf/results/{W1,W2}-BASELINE.json` | data artifacts | Re-freeze BOTH on the cleaned engine, cool machine (D-14). |

### Pattern 1: Monotonic forward cursor over int64 ns (D-10) — THE primary lever
**What:** Replace the per-tick `frame.index.searchsorted(cutoff, side="right")` with a forward-only
step from the cursor's last position, comparing **int64 nanoseconds** (not pandas Timestamps).
**When to use:** The single `window()` cutoff-resolution step, per (ticker, timeframe).
**Example:**
```python
# Source: empirically verified byte-identical to searchsorted(side="right") on pandas 2.3.3.
# State (in __init__): self._cursor: dict[tuple[str,str], int] = {}
#                      self._cursor_cut: dict[tuple[str,str], int] = {}
key = (ticker, alias)
n = len(frame.index)
iv_i8 = frame.index.asi8          # zero-copy cached int64 ns view (UTC); stable across calls
cutoff_i8 = cutoff.value          # O(1) int64 ns (Timestamp.value == asi8[k] for tz-aware) [VERIFIED]

last_pos = self._cursor.get(key)
last_cut = self._cursor_cut.get(key)
if last_pos is None or last_cut is None or cutoff_i8 < last_cut:
    # COLD or NON-MONOTONIC (universe re-entry, backwards/jumped asof, gap-frame replacement):
    # SAFE FULL REBUILD via searchsorted — never trust stale state, never leak a future bar (D-10).
    pos = int(frame.index.searchsorted(cutoff, side="right"))
else:
    pos = last_pos
    while pos < n and iv_i8[pos] <= cutoff_i8:   # 0.14 µs/step; O(1) amortized in backtest
        pos += 1
self._cursor[key] = pos
self._cursor_cut[key] = cutoff_i8
```
> **Byte-identity proof obligation (D-16):** verified `pos` equals
> `int(frame.index.searchsorted(cutoff, side="right"))` for 3000 on-grid ticks AND 3000 mid-gap
> cutoffs (`asof - tf + tf_base` landing between bars), using `asi8` + `Timestamp.value`. The
> `<=` (not `<`) preserves **exclusive-right** semantics: `searchsorted(side="right")` returns the
> insertion point AFTER equal elements, i.e. the count of `index <= cutoff` — exactly what the
> forward `while index[pos] <= cutoff` loop computes. `[VERIFIED: empirical test]`

> **`asi8` caveat the planner must verify at implement time:** `frame.index.asi8` returned the same
> underlying array across calls (`np.shares_memory == True`) in the test, so re-deriving it per call
> is cheap; but pandas does not contractually guarantee this. If the planner wants belt-and-suspenders,
> cache `iv_i8` alongside the master frame in `self._frames`-adjacent state at build time. Either way
> the int64 array is read-only-buffer-safe (06-01 locked the values block, not the index; the index
> int64 backing is separate and reads fine). `[VERIFIED: shares_memory stable across calls]`

### Pattern 2: Reset / seek-safety — the correctness crux (D-10)
**What:** Detect any non-monotonic / cold / unknown step and fall back to a full `searchsorted`
rebuild, so a stale cursor can never under-count and leak a future bar.

| Trigger | Detection | Response |
|---------|-----------|----------|
| **First call (cold cursor)** | `key not in self._cursor` | Full `searchsorted` rebuild; seed `self._cursor[key]`. |
| **Backwards / jumped `asof`** | `cutoff_i8 < self._cursor_cut[key]` (the last cutoff went backwards) | Full `searchsorted` rebuild from the new cutoff (a forward-only loop would NOT walk back and would over-count → could leak a future bar). |
| **Universe re-entry (screener churn)** | Same key seen again after a gap — but the cutoff still advances monotonically, so the **forward step is still correct**; no special handling needed beyond the backwards-cutoff guard. (Re-entry does not reset `asof`; the cutoff at re-entry is ≥ the last seen cutoff.) | Forward step (no reset) — verified safe because monotonicity is on the **cutoff**, not on call contiguity. |
| **Sparse / gap frame (D-04)** | Cutoff lands in a gap with no bar | Forward step naturally stops at the correct `pos` (the `<=` loop handles gaps; mid-gap byte-identity verified). No reset. |
| **Frame replaced (lazy resample memoizes a NEW frame for the same key)** | The cursor key is `(ticker, alias)`; a lazy resample for a *new* alias is a *different* key, so the cursor starts cold for it — no stale-frame hazard. The base/already-memoized frame for an existing key is never mutated (06-01 invariant). | No reset needed; the key→frame mapping is stable per alias. |

**Recommendation: silent safe-rebuild, not fail-loud.** A non-monotonic cutoff in a backtest is not a
bug to crash on — the screener/membership path can legitimately re-issue an earlier `asof` for a
re-entering ticker, and the `tf > base_tf` resampled cutoff can step in non-uniform increments. A
silent `searchsorted` rebuild is **always correct** (it is exactly today's behavior) and **never
leaks** (it recomputes from scratch). The D-16 test proves equivalence; a hard runtime assert is
explicitly rejected (D-16 — it re-pays the searchsorted). The cursor is a *fast path with a correct
fallback*, not a trust-the-state optimization.

> **The canonical never-leak invariant:** `pos` is always `count(index <= cutoff)`. The forward loop
> can only *under-run* if it starts from a `last_pos` computed against a *larger* cutoff — which is
> exactly the `cutoff_i8 < last_cut` case the rebuild guard catches. With the guard, `pos` is provably
> equal to `searchsorted(side="right")` on every reachable cutoff. `[VERIFIED]`

### Pattern 3: D-13 denominator cleanup (prep — runs BEFORE the cursor)
**3a — remove the per-bar `TIME EVENT` log (engine waste):**
```python
# itrader/events_handler/full_event_handler.py:114-116  (TAB indent — do NOT normalize)
# DELETE these three lines:
#     if event.type is EventType.TIME:
#         # D-21: per-tick flow log demoted from INFO to DEBUG.
#         self.logger.debug(f"TIME EVENT: {event.time}")
# The f-string f"TIME EVENT: {event.time}" is built EAGERLY by Python before .debug() runs;
# the logger's internal isEnabledFor(DEBUG) gate (logger.py:260) fires AFTER the string is
# already formatted, so str(event.time) is paid every bar and discarded at default INFO.
# Plain removal is behavior-neutral: the line never prints at INFO; logs are NOT the oracle.
```
**Recommendation: plain removal, not a lazy/guarded log.** The line is *already* DEBUG-gated (it never
prints at the default INFO level), so there is no observable behavior to preserve. A "lazy" guard
(`if self.logger.isEnabledFor(...)`) would keep a per-bar branch for zero benefit; removal is cleaner
and matches D-13's "genuine engine waste" framing. `[VERIFIED: code read — logger.py:258-262]`

**3b — de-time the W2 harness (`run_w2_sweep._run_point`):**
```python
# perf/runners/run_w2_sweep.py:119-125  (4-space). Today tracemalloc wraps the timed run:
#     tracemalloc.start(); t0 = perf_counter(); system.run(...); wall = perf_counter()-t0
#     _cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
# tracemalloc instruments EVERY allocation -> inflates wall_clock_s (the ~19% denominator).
# D-13: time the engine CLEAN, then capture peak-mem in a SEPARATE pass:
def _run_point(n_symbols, tmpdir):
    frames = make_synthetic_ohlcv(...)   # synth-gen OUTSIDE the timed region (already is)
    ...wire system...
    # Pass 1 — CLEAN wall-clock (no tracemalloc):
    t0 = time.perf_counter()
    system.run(print_summary=False)
    wall_clock_s = time.perf_counter() - t0
    # Pass 2 — peak memory (re-wire a fresh system; tracemalloc instrumented):
    system2 = _wire(...)                 # identical wiring, fresh state
    tracemalloc.start()
    system2.run(print_summary=False)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = peak / (1024*1024)
    return {"n_symbols": n_symbols, "wall_clock_s": wall_clock_s, "peak_mem_mb": peak_mem_mb}
```
> **Why a second run, not just moving the calls:** `tracemalloc` slows everything between
> `start()`/`stop()`; you cannot get a clean wall-clock and a peak-mem from the *same* timed run. The
> two-pass structure (clean timed run + separate instrumented run) is the standard fix. The synthetic
> frames + CSVs are generated ONCE and reused across both passes (the existing `tmpdir`/`csv_paths`
> already support this). Keep `seed=42` for determinism. `[ASSUMED: standard tracemalloc practice —
> planner pins the exact re-wire helper]`

### Pattern 4: Gate-(b) re-freeze + verdict (D-14/D-15) — the 06-02 harness is reusable as-is
The 06-02 `run_w2_sweep.py --check/--baseline-out` (commit `f51d7c6`) is **correct and reusable**:
`_check_w2` keys on `wall_clock_s_at_50`, requires `impr >= 10.0%` (inverted guard), carries the WR-02
zero-baseline soft guard. **The only change D-13 forces** is that the W2 baseline must be **re-frozen
on the cleaned engine** (after the log removal + harness de-timing land), because the de-timed harness
produces a *different, smaller* `wall_clock_s_at_50` than the diluted one — a pre-cleanup baseline
would mis-credit the delta.

**Sequencing (D-14, cool machine):**
1. Land D-13 (log removal + harness de-time) on the engine.
2. On a cool machine, capture the BEFORE baseline on the **cleaned engine without the cursor**
   (`--baseline-out perf/results/W2-BASELINE.json`) — this is the cursor's denominator.
3. Land the cursor (D-10).
4. `run_w2_sweep.py --check` (against the step-2 baseline) must print `improvement >= +10.0%` at 50
   symbols, exit 0 → the **cursor alone** cleared the bar (cleanup isolated into the baseline).
5. `make perf-w1 --check` stays within the ±5% soft band (W1 guard, not a win — D-14).
6. Re-freeze BOTH: commit the cursor-on `W2-BASELINE.json` (the standing reference, seeds Phase 5) and
   re-freeze `W1-BASELINE.json` (`make perf-baseline`).
7. **D-15 fallback:** if step 4 prints `< +10.0%` honestly, **ship anyway** — record the actual W2 %
   in the SUMMARY, commit the baselines, re-frame gate (b) → "measurable W2 win + W1 non-regress". No
   revert.

> **The de-timing changes nothing in `--check`'s code path** — `_check_w2` still reads
> `wall_clock_s_at_50` from the points list; it does not know whether tracemalloc ran. The only
> requirement is that BOTH the baseline and the check-run measure with the *same* (de-timed) harness.
> `[VERIFIED: code read — run_w2_sweep.py:181-209]`

### Anti-Patterns to Avoid
- **Comparing pandas Timestamps in the cursor loop** — `frame.index[pos] <= cutoff` is 2.0 µs/step
  (boxing); the int64 `iv_i8[pos] <= cutoff.value` path is 0.14 µs. A Timestamp-comparison cursor
  delivers ~no win. Use `asi8` + `.value`.
- **Converting the cutoff to `np.datetime64` per tick** — 3.3 µs/tick, ≈ the searchsorted it replaces.
  Use the O(1) `Timestamp.value` int64 attribute.
- **A forward-only cursor with no backwards-cutoff guard** — under-counts on a re-issued earlier
  `asof` → **leaks a future bar** (the slice would include bars stamped > cutoff). The
  `cutoff_i8 < last_cut` rebuild guard is mandatory (Pattern 2).
- **Reconstructing the window via `pd.DataFrame(values[start:pos], …)` for D-11** — slower (9.2 vs 7.3
  µs) AND forbidden by D-07 (drift risk). Keep `iloc`.
- **An always-on runtime `assert cursor == searchsorted` in `window()`** — re-pays the searchsorted the
  cursor removes (rejected by D-16). Prove equivalence in the test only.
- **A lazy/guarded `TIME EVENT` log instead of removal** — keeps a per-bar branch for zero benefit; the
  line is already DEBUG-gated and never prints (D-13 — plain removal).
- **Normalizing indentation** — `bar_feed.py`/`run_w2_sweep.py` are **4-space**; `full_event_handler.py`
  is **TAB**. The D-13 log-line deletion is in the TAB file — match it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| int64 ns view of the index | Manual `[t.value for t in index]` per tick | `frame.index.asi8` (zero-copy cached int64 view) | Already materialized once; per-call comprehension is O(n) and defeats the cursor. |
| cutoff → int64 ns | `np.datetime64(cutoff.tz_convert("UTC").tz_localize(None))` | `cutoff.value` (Timestamp attribute) | The conversion is 3.3 µs; `.value` is O(1) and equals `asi8[k]` for tz-aware indexes. `[VERIFIED]` |
| Cheaper window slice | A numpy-stride view re-wrapped in a DataFrame, or `pd.DataFrame(values, index, columns)` | `frame.iloc[start:pos]` (kept) | Every alternative measured slower AND risks tz/dtype/column drift (D-07). `iloc` on a single block is already a view. `[VERIFIED]` |
| Cursor==searchsorted proof | An always-on runtime assert | A dedicated drift test (D-16) | Runtime assert re-pays the cost; the test proves it once. |
| Clean wall-clock under tracemalloc | Subtracting an estimated tracemalloc overhead | Two-pass measurement (clean timed run + separate instrumented run) | tracemalloc's per-allocation cost is not a fixed subtractable constant. |

**Key insight:** The pandas/numpy primitives already do everything D-10 needs — `asi8` + `Timestamp.value`
give a 30×-cheaper-than-searchsorted comparison. The work is *wiring the forward step with a correct
rebuild guard* and *proving byte-identity*, not building machinery. D-11's "cheaper slice" turns out to
not exist on this frame shape — `iloc` is already optimal.

## Runtime State Inventory

> Not a rename/refactor/migration phase — this is a behavior-preserving perf change to in-memory code
> paths plus a one-line log deletion and harness hygiene. No persisted or registered state carries
> phase-relevant meaning.
> - **Stored data:** None — cursor state is in-process, rebuilt every run; no datastore keys change. Verified: the change is `BacktestBarFeed` instance state + a dispatcher line + a perf runner.
> - **Live service config:** None.
> - **OS-registered state:** None.
> - **Secrets/env vars:** None — `ITRADER_DISABLE_LOGS`/`ITRADER_LOG_LEVEL` are read by the logger but unaffected by deleting one call site.
> - **Build artifacts:** None — no package rename, no egg-info impact. `perf/results/{W1,W2}-BASELINE.json` are re-frozen data artifacts produced by the phase, not stale state to migrate.

## Common Pitfalls

### Pitfall 1: A Timestamp-comparison cursor delivers no win (the int64 path is load-bearing)
**What goes wrong:** Implementing the forward step as `while frame.index[pos] <= cutoff: pos += 1`.
Each `frame.index[pos]` boxes an int64 into a `pd.Timestamp` (2.0 µs) and the compare adds more — the
per-step cost approaches the 4.3 µs `searchsorted` it replaces, so the W2 win evaporates.
**Why it happens:** `frame.index[pos]` looks like cheap scalar access but pandas materializes a
Timestamp object; `frame.index.values[pos]` / `frame.index.asi8[pos]` returns a raw numpy scalar.
**How to avoid:** Compare int64 ns: `iv_i8 = frame.index.asi8`, `cutoff_i8 = cutoff.value`, then
`while iv_i8[pos] <= cutoff_i8`. Measured 0.14 µs/step. `[VERIFIED: timeit — 0.14 µs int64 vs 2.0 µs Timestamp]`

### Pitfall 2: Forward-only cursor leaks a future bar on a backwards cutoff
**What goes wrong:** A cursor that only ever steps forward, when handed a cutoff *earlier* than its
last (universe re-entry that re-issues an earlier `asof`, or a test that calls `window()` out of
order), keeps its stale (too-large) `pos` and returns a window that includes bars stamped > the new
cutoff — a silent look-ahead breach.
**Why it happens:** The optimization assumes monotonic cutoffs; nothing in the type system enforces it.
**How to avoid:** Guard `if cutoff_i8 < last_cut: rebuild via searchsorted` (Pattern 2). The D-16 test
MUST include a backwards/out-of-order tick to exercise this path. `[VERIFIED: rebuild path is byte-identical to fresh searchsorted]`

### Pitfall 3: Re-freezing the W2 baseline on the DILUTED (pre-D-13) engine
**What goes wrong:** Capturing the cursor's before-baseline before the log removal + harness de-timing
land. The diluted denominator includes the ~22% log waste + ~19% harness overhead, so the cursor's
searchsorted-removal looks like a tiny fraction of a bloated total — the ≥10% bar stays unreachable
(exactly why 06-01's measurement failed).
**Why it happens:** Sequencing — the cleanup is a *prep* step (D-13) and must land first.
**How to avoid:** D-14 sequencing — land D-13, re-freeze on the cleaned engine, THEN gate the cursor
alone. `[CITED: D-13/D-14; 06-PROFILE-FINDINGS.md]`

### Pitfall 4: Deleting the wrong indentation in `full_event_handler.py`
**What goes wrong:** Editing the **TAB-indented** `full_event_handler.py` with spaces (or vice versa)
produces a mixed-indentation diff that breaks the file (CLAUDE.md indentation hazard).
**Why it happens:** `bar_feed.py` (the main target) is 4-space; the D-13 log line is in the TAB file.
**How to avoid:** Match `full_event_handler.py`'s TAB indent for the deletion. The three lines to
remove are `:114-116`. `[VERIFIED: code read — file uses tabs]`

### Pitfall 5: Cursor state outliving a frame it no longer matches
**What goes wrong:** Storing the cursor keyed only on `ticker` (not `(ticker, alias)`) — a strategy
querying two timeframes for the same ticker would share one cursor across two different frames.
**Why it happens:** The feed's `_frames` is keyed `(ticker, alias)`; the cursor must mirror that.
**How to avoid:** Key the cursor `(ticker, alias)` exactly like `self._frames`. Each alias has its own
frame and its own monotonic cutoff sequence. `[CITED: bar_feed.py _frames keying]`

## Code Examples

### The D-16 drift-test extension (skeleton — extends the existing D-08 suite)
```python
# Source: synthesized from D-16 + the verified byte-identity; home tests/unit/price/test_bar_feed.py
# (co-located with the existing 7-rule contract suite + the 06-01 D-08 (a)/(b) tests at :343-372)
from datetime import timedelta

def test_cursor_equals_fresh_searchsorted_across_ticks(daily_feed, daily_base_frame):
    # D-16: across MONOTONIC sampled ticks the cursor's (start, pos) == a fresh searchsorted,
    # and no bar with time > cutoff appears in the returned window.
    tf, base_tf, max_window = timedelta(days=1), timedelta(days=1), 3
    frame = daily_base_frame
    for asof in [ts('2020-01-02'), ts('2020-01-05'), ts('2020-01-07'), ts('2020-01-10')]:
        cutoff = asof - tf + base_tf
        fresh_pos = int(frame.index.searchsorted(cutoff, side="right"))
        win = daily_feed.window('BTCUSD', tf, max_window, asof=asof)
        # (1) end position equals fresh searchsorted (the cursor matched the rebuild)
        if not win.empty:
            assert frame.index.get_loc(win.index[-1]) == fresh_pos - 1
            # (2) NO future bar: every returned stamp <= cutoff
            assert (win.index <= cutoff).all()

def test_cursor_safe_rebuild_on_backwards_asof(daily_feed):
    # D-16 reset-safety: a backwards cutoff (out-of-order asof) must NOT leak a future bar.
    tf = timedelta(days=1)
    late = daily_feed.window('BTCUSD', tf, 5, asof=ts('2020-01-10'))   # advance the cursor
    early = daily_feed.window('BTCUSD', tf, 5, asof=ts('2020-01-03'))  # step BACKWARDS
    assert (early.index <= ts('2020-01-03')).all()                     # no Jan-4..10 leak
    # byte-identical to a fresh searchsorted at the earlier cutoff
    # (compare to a feed with a virgin cursor, or to the positional oracle)

def test_cursor_cold_and_gap(gappy_feed):
    # D-16: cold cursor (first call) + a gap-frame cutoff both resolve byte-identically.
    win = gappy_feed.window('GAPPY', timedelta(days=1), 5, asof=ts('2020-01-05'))  # Jan-5 gap day
    assert (win.index <= ts('2020-01-05')).all()
    assert ts('2020-01-05') not in win.index   # the gap day has no bar

def test_cursor_universe_reentry(duo_feed):
    # D-16: a ticker queried, then NOT, then queried again at a LATER tick (re-entry) —
    # the forward step is still correct because the cutoff advanced monotonically.
    w1 = duo_feed.window('BTCUSD', timedelta(days=1), 3, asof=ts('2020-01-04'))
    _  = duo_feed.window('ETHUSD', timedelta(days=1), 3, asof=ts('2020-01-05'))  # other ticker
    w2 = duo_feed.window('BTCUSD', timedelta(days=1), 3, asof=ts('2020-01-07'))  # re-entry, later
    assert (w2.index <= ts('2020-01-07')).all()
    assert w2.index[-1] == ts('2020-01-07')
```
> The existing `test_window_view_content_equals_old_copy` (:343) and
> `test_window_view_is_read_only_and_cannot_leak` (:359) stay green unchanged (the cursor returns the
> same read-only `iloc` view). D-16 ADDS the cursor-equivalence + reset-safety tests above.

### Cursor wiring in `__init__` (4-space)
```python
# In BacktestBarFeed.__init__, alongside self._frames / self._spans / self._prebuilt:
self._cursor: dict[tuple[str, str], int] = {}      # last forward position per (ticker, alias)
self._cursor_cut: dict[tuple[str, str], int] = {}  # last cutoff (int64 ns) per (ticker, alias)
# No per-frame asi8 cache needed if frame.index.asi8 is re-derived per call (verified zero-copy);
# the planner MAY cache it adjacent to _frames as a belt-and-suspenders micro-opt.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-tick `frame.index.searchsorted(cutoff, "right")` (O(log n), 4.3 µs × 150k calls) | Monotonic forward cursor over `index.asi8` int64 ns (O(1) amortized, 0.14 µs/step) with a `searchsorted` rebuild guard | This phase (D-10) | Removes the 13.2% W2 searchsorted hotspot; byte-identical result. |
| 06-01 view/alias (shipped, ~0% W2) | Kept as the read-only foundation; cursor sits on top (D-12) | 06-01 (`9168cae`) | No regression; the cursor returns the same read-only view. |
| Per-bar eager `f"TIME EVENT: {event.time}"` discarded at INFO | Deleted (D-13) | This phase | Removes ~22% W2 engine waste; behavior-neutral (never printed). |
| tracemalloc inside the W2 timed region (~19% inflation) | Two-pass: clean timed run + separate instrumented run (D-13) | This phase | Timed wall-clock measures the engine, not the harness. |

**Deprecated/outdated:**
- D-01's "searchsorted is microsecond-class, not worth a cursor" — **empirically wrong** (profile: 13.2%
  of W2). Superseded by D-10.
- D-11's "cheaper slice" as a *separate* win — the slice has no cheaper byte-identical form; folded into
  the D-15 ship-and-reframe (see Open Question 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The two-pass tracemalloc de-time (re-wire a fresh system for the mem pass) is the right structure | Pattern 3b | Low — standard tracemalloc practice; the planner pins the exact re-wire helper. Alternative: a single clean timed run + an estimated/omitted peak-mem (peak-mem is "watched, never fails" per W1's guard). |
| A2 | `frame.index.asi8` stays zero-copy/stable enough to re-derive per call | Pattern 1 caveat | Low — verified `shares_memory` stable; worst case cache it at build (a 1-line micro-opt). |
| A3 | Silent safe-rebuild (not fail-loud) is the right reset policy | Pattern 2 | Low — D-10 leaves this to researcher/planner within "never leak"; a non-monotonic cutoff is legitimate (screener re-entry, resampled cutoffs), so crashing would be wrong. The rebuild is exactly today's behavior. |
| A4 | Plain removal of the `TIME EVENT` log is behavior-neutral | Pattern 3a | Very low — verified the line is DEBUG-gated and never prints at INFO; logs are not the oracle (gate a covers it). |

**Note:** The load-bearing technical claims (forward-cursor byte-identity to `searchsorted(side="right")`,
the 0.14 µs int64 comparison cost, the cheaper-slice candidates all being slower, the eager-f-string
caller waste) are all `[VERIFIED: empirical test / code read]`, not assumed.

## Open Questions

1. **Is D-11's cheaper slice worth pursuing, or ship cursor-only?**
   - What we know: every measured alternative to `frame.iloc[start:pos]` is *slower* (reconstruct 9.2
     µs, take 21 µs vs iloc 7.3 µs), AND D-07 forbids the reconstruction path on byte-identity grounds.
     On a single-block float64 frame `iloc` is already a near-optimal view. `[VERIFIED]`
   - What's unclear: nothing technical — the data is conclusive that no cheaper byte-identical slice
     exists on this frame shape.
   - **Recommendation:** **Ship cursor-only.** Keep `iloc[start:pos]`. The cursor alone removes ~36% of
     the `window()` path (the 4.3 µs searchsorted out of ~11.6 µs). The 7.9% slice cost is left on the
     table per D-11's own escape hatch ("if the cheaper slice cannot be made provably byte-identical,
     say so and recommend cursor-only — the gate has a D-15 ship-and-reframe fallback"). **Confirm with
     the planner/owner** that cursor-only is acceptable, or accept a measurable-but-<10% W2 via D-15.

2. **Where does the cursor live relative to the per-frame state?**
   - What we know: the cursor must be keyed `(ticker, alias)` to mirror `self._frames`; two plain dicts
     (`_cursor`, `_cursor_cut`) are the simplest shape. A belt-and-suspenders `asi8` cache adjacent to
     `_frames` is optional (verified zero-copy without it).
   - **Recommendation:** Two instance dicts in `__init__`; re-derive `frame.index.asi8` per call (cheap).
     This is a placement choice (Claude's discretion), not a correctness one.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pandas | cursor (`asi8`, `searchsorted` rebuild), slice | ✓ | 2.3.3 | — |
| numpy | int64 ns comparison | ✓ | 2.2.6 | — |
| structlog | the logger whose caller waste D-13 removes | ✓ | 24.4.0 | — |
| poetry venv | tests + perf runners | ✓ | in-project `.venv` | — |
| cool machine for the gate-(b) re-freeze | D-14 measurement | ⚠️ human-gated | — | defer the re-freeze (per the pending todo + thermal-drift memory) — mechanization is reusable |

**Missing dependencies with no fallback:** None for the code work.
**Missing dependencies with fallback:** The cool-machine re-freeze (D-14) is human-gated — Claude
cannot guarantee thermal state; the 06-02 checkpoint pattern (`checkpoint:human-verify`) carries forward.

> **Worktree note (memory `worktree-make-test-env-abort` / `worktree-venv-shadowing`):** the current
> branch is a worktree. `make test`/`make perf-*` may abort on a missing `.env`; run `poetry run
> pytest tests` in the worktree and run the perf gate in the MAIN checkout. Prepend `PYTHONPATH="$PWD"`
> if the editable install shadows worktree edits.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error", ...]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/price/test_bar_feed.py -q` |
| Full suite command | `poetry run pytest tests` (worktree) / `make test` (main checkout) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-06 / D-16 (a) | Cursor `(start,pos)` == fresh `searchsorted(cutoff,"right")` across monotonic sampled ticks | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k cursor_equals -q` | ❌ Wave 0 (new) |
| PERF-06 / D-16 (b) | No bar with `time` > cutoff in the returned window (no-future-bar invariant) | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k cursor -q` | ❌ Wave 0 (new) |
| PERF-06 / D-16 (reset) | Backwards `asof` / cold cursor / gap frame / universe re-entry all rebuild safely (no leak) | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k "rebuild or cold or gap or reentry" -q` | ❌ Wave 0 (new) |
| PERF-06 / D-08 (kept) | View content == old-copy; mutation raises read-only (06-01 tests stay green) | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k "view_content or read_only" -q` | ✅ exists (`:343`, `:359`) |
| PERF-06 / D-08 (c) | Existing 7-rule bar-timing contract stays green | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -q` | ✅ exists (`:123-308`) |
| D-13 | `TIME EVENT` log removal is behavior-neutral (suite + oracle unchanged) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists |
| Gate (a) | Byte-exact SMA_MACD oracle (134 / `46189.87730727451`) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists (memory `oracle-test-location`) |
| Gate (a) | `mypy --strict` clean | static | `poetry run mypy itrader` | ✅ infra exists |
| Gate (a) | Determinism double-run byte-identical | integration | run oracle twice; assert identical | ✅ oracle deterministic |
| Gate (b) | W2 ≥10% at 50 symbols (cursor alone, cleaned baseline) + W1 within ±5% band | perf | `make perf-w2` (`--check`); `make perf-w1` | ✅ harness exists (06-02 `f51d7c6`); re-freeze on cleaned engine |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/price/test_bar_feed.py -q` (cursor drift + contract + 06-01 D-08 tests — fast, <30s).
- **Per wave merge:** `poetry run pytest tests` (full unit/integration/e2e) + `poetry run mypy itrader`.
- **Phase gate (a):** `poetry run pytest tests/integration/test_backtest_oracle.py` green (134 / `46189.87730727451`), `mypy --strict` clean, determinism double-run identical, full suite green.
- **Phase gate (b):** D-14 sequencing — re-freeze BOTH baselines on the cleaned engine (cool machine), then `make perf-w2 --check` ≥10% at 50 symbols (cursor alone) AND `make perf-w1 --check` within band; D-15 fallback records the actual W2 % if <10%.

### Wave 0 Gaps
- [ ] `tests/unit/price/test_bar_feed.py` — add the D-16 cursor-equivalence + reset-safety tests (cursor==searchsorted across monotonic ticks; no-future-bar; backwards-asof rebuild; cold cursor; gap frame; universe re-entry). The existing `daily_feed`/`gappy_feed`/`duo_feed` fixtures already supply the cold/gap/churn cases.
- [ ] `perf/runners/run_w2_sweep.py` — de-time `_run_point` (two-pass; D-13). The `--check`/`--baseline-out` flags already exist (06-02 `f51d7c6`) — do NOT re-add them.
- [ ] `itrader/events_handler/full_event_handler.py:114-116` — delete the `TIME EVENT` debug block (D-13; TAB indent).
- [ ] `perf/results/W2-BASELINE.json` — capture on the cleaned engine (cursor-on), commit (seeds Phase 5). NOT YET FROZEN (correct per 06-PROFILE-FINDINGS — nothing to freeze until the cursor lands).
- [ ] `perf/results/W1-BASELINE.json` — re-freeze on the cleaned engine after confirming non-regression (D-14).
- Framework install: none — pytest infra already present.

## Security Domain

> Not applicable in the conventional ASVS sense — this is an internal, offline backtest data-path
> optimization with no auth/session/network/input-validation surface. The single *integrity* concern is
> look-ahead/data-corruption (a stale cursor leaking a future bar into a decision window), which is
> exactly what D-10's rebuild guard + D-16's no-future-bar assertion defend. No `security_enforcement`
> artifact is touched; no new attack surface is introduced.

| Integrity threat | STRIDE | Mitigation (this phase) |
|------------------|--------|-------------------------|
| A stale forward cursor under-counts on a backwards cutoff → leaks a bar stamped > cutoff (silent look-ahead breach) | Tampering | `cutoff_i8 < last_cut` → safe `searchsorted` rebuild (Pattern 2); proven by the D-16 backwards-asof + no-future-bar tests; gate-(a) byte-exact oracle is the run-path backstop. |
| A consumer mutates the returned view → poisons a future tick | Tampering | Carried from 06-01 (D-09): the master values buffer is `writeable=False`; the cursor returns the same read-only view; the 06-01 D-08(b) test stays green. |

## Sources

### Primary (HIGH confidence)
- **Empirical test against the pinned venv** (`pandas 2.3.3`, `numpy 2.2.6`) — the load-bearing source. Verified: forward cursor over `index.asi8` + `Timestamp.value` is byte-identical to `searchsorted(cutoff, side="right")` for on-grid AND mid-gap cutoffs (3000 ticks each); int64 compare 0.14 µs vs Timestamp compare 2.0 µs vs `np.datetime64` conversion 3.3 µs vs searchsorted 4.3 µs; `index.asi8` zero-copy/stable; `Timestamp.value == asi8[k]` for tz-aware; every cheaper-slice candidate (`pd.DataFrame` reconstruct 9.2 µs, `take` 21 µs) slower than `iloc` 7.3 µs; the reconstruct path passes `assert_frame_equal` but is forbidden by D-07. `[VERIFIED]`
- `itrader/price_handler/feed/bar_feed.py` — target (`window:427-486`, `_resampled_frame:319-341`, `__init__:199-263`, `_readonly_master:132-176`, 7-rule contract docstring `:9-55`). `[VERIFIED: read]`
- `itrader/events_handler/full_event_handler.py:114-116` — the `TIME EVENT` debug line (TAB). `itrader/logger.py:258-262` — internal `isEnabledFor` gate (proves the f-string is built eagerly by the caller). `[VERIFIED: read]`
- `perf/runners/run_w2_sweep.py` — `_run_point:95-131` (tracemalloc-in-timed-region to de-time), `_check_w2:181-209` + `--check`/`--baseline-out` (06-02, reusable as-is). `perf/runners/run_w1_benchmark.py` — the mirrored W1 guard. `[VERIFIED: read]`
- `tests/unit/price/test_bar_feed.py` — existing 7-rule contract suite + the 06-01 D-08 (a)/(b) tests (`:343`, `:359`) the D-16 tests extend. `[VERIFIED: read]`
- `.planning/phases/06-…/06-PROFILE-FINDINGS.md` — the authoritative pivot rationale (searchsorted 13.2% / iloc 7.9% / log 22% / harness 19%). `06-01-SUMMARY.md` — the shipped foundation (multi-block store frame consolidated to single-block). `06-02-PLAN.md` — the paused gate harness. `[VERIFIED: read]`

### Secondary (MEDIUM confidence)
- 06-CONTEXT.md D-10–D-16 pivot block; STATE.md gate (a)/(b) text; REQUIREMENTS.md PERF-06. `[CITED]`

### Tertiary (LOW confidence)
- None — the technical claims were promoted to HIGH via empirical verification.

## Metadata

**Confidence breakdown:**
- Cursor byte-identity to searchsorted (D-10): **HIGH** — verified on-grid + mid-gap, 3000 ticks each.
- Cursor comparison cost (int64 vs Timestamp): **HIGH** — timeit, 0.14 µs vs 2.0 µs vs 3.3 µs.
- Cheaper-slice infeasibility (D-11): **HIGH** — every candidate measured slower than `iloc`; D-07 forbids reconstruct.
- `TIME EVENT` removal behavior-neutrality (D-13): **HIGH** — code read confirms eager-caller f-string, DEBUG-gated, never printed.
- Harness de-time structure (D-13): **MEDIUM** — standard two-pass tracemalloc practice; planner pins the re-wire helper.
- Gate-(b) re-freeze (D-14/D-15): **MEDIUM** — the 06-02 harness is reusable; the cool-machine measurement is human-gated (thermal-drift memory).

**Research date:** 2026-06-24
**Valid until:** 2026-07-24 (stable — pinned pandas/numpy; re-verify if pandas is bumped toward 3.0).

---

## SHIPPED in 06-01 (historical — do NOT re-plan)

> The following view/alias mechanism (D-01/D-02/D-06/D-07/D-09) **already landed in 06-01** (commit
> `9168cae`, SUMMARY written) and is **kept as the foundation** (D-12). It is reproduced here for the
> record only. **These are NOT tasks** — the cursor (above) builds on top of them.

- **Read-only view from `window()` (D-01/D-07, shipped):** `window()` returns `frame.iloc[start:pos]`
  directly — a view aliasing the locked single-block master, inheriting `writeable=False`. The `.iloc`
  slice on a homogeneous float64 single-block frame is *already a view* (no buffer copy). The cursor
  keeps returning this exact view.
- **Non-writeable single-block master at build (D-09, shipped):** `_readonly_master(frame)`
  consolidates to a single block via a byte-identical `DataFrame.copy()` (the store frame is
  MULTI-block — the 06-01 deviation finding), then locks the block's numpy buffer
  (`flags.writeable = False`, walking `arr if arr.flags.owndata else arr.base`, asserting
  `np.shares_memory`). Called at both build sites (`__init__` base load, `_resampled_frame` memoize).
  `resample`/`searchsorted`/`iterrows`/`ta` reads all verified to work on the non-writeable frame.
- **Memoized `_offset_alias` (D-01, shipped):** `@functools.cache` on the module function (body
  byte-unchanged; `functools.cache` does not cache exceptions so the raise-on-unsupported guard is
  preserved). Profiled at 0.04% — never the hotspot.
- **Empty-window short-circuit (D-06, shipped):** `if start >= pos: return frame.iloc[pos:pos]` —
  bypasses the view machinery, byte-identical empty semantics. The cursor keeps this short-circuit.
- **D-08 three-assertion drift lock (shipped):** `tests/unit/price/test_bar_feed.py:343-372` —
  (a) view content == old-copy (`assert_frame_equal`); (b) direct numpy write raises
  `ValueError(read-only)` and cannot leak (targets the numpy `ValueError`, NOT a pandas
  `SettingWithCopyWarning`); (c) the existing 7-rule contract suite stays green. D-16 EXTENDS this
  suite with the cursor-equivalence + reset-safety tests.

**Why 06-01 gave ~0% W2 (the pivot trigger):** the view/alias attacked the *reducible-looking*
sub-parts (alias string compute 0.04%, slice copy marginal) which were negligible. The dominant
per-tick cost — a fresh `searchsorted` over the full frame index every tick × every symbol — was left
in place. That is what the cursor (D-10) removes.
