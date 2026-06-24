# Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able) - Research

**Researched:** 2026-06-24
**Domain:** pandas 2.3.3 view/copy mechanics, numpy buffer writeability, byte-identity behavior preservation
**Confidence:** HIGH (the two CONTEXT-deferred questions were resolved by direct empirical test against the pinned `pandas 2.3.3 / numpy 2.2.6` venv, not training data)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (view-primary + memoize alias; `searchsorted` stays):** Replace `frame.iloc[start:pos]` (a per-tick data copy of N×5 float64) with a **read-only view** sharing the cached master frame's buffer. Bundle the trivial free extra: memoize `_offset_alias(timeframe)`. `window()` **keeps returning a `pd.DataFrame`**. `searchsorted` left as-is. **Rejected:** monotonic per-(ticker,tf) cursor; bounds-only caching that keeps the copy; returning a bare numpy array.
- **D-02 (hard read-only at the feed boundary; mutation fails loudly at source — NOT a global flag):** A view aliases the cached master frame; mutation would silently poison future ticks. Enforce at the source (D-09), plus a written audit and a drift test (D-08). **Rejected:** global `pd.options.mode.copy_on_write` (process-wide blast radius + byte-identity risk; mutation copies silently instead of failing loudly); audit + test only with no runtime guard.
- **D-03 (`window()` only):** `window()` is the oracle-relevant and symbol-scaling path. `megaframe()` (deferred screener) inherits the read-only view for free; `current_bars()` is already a dict lookup. **Rejected:** also reworking `megaframe()`'s concat.
- **D-06 (short-circuit empty; return the existing slice unchanged):** When the cutoff lands at the frame start, return `frame.iloc[pos:pos]` (size-0) **unchanged** — empty windows bypass the view + read-only machinery entirely. **Rejected:** routing empty windows through the uniform view path.
- **D-07 (set direction; researcher pins the exact API):** Operate on the **sliced existing frame** and mark it read-only, preserving dtype / tz-aware `DatetimeIndex` / column set+order **exactly** — do **NOT** reconstruct via a new `pd.DataFrame(...)`. Byte-identity is the hard constraint. **Rejected:** pinning the precise call now (researcher's job); fully deferring.
- **D-08 (drift/equivalence test — all three assertions):** **(a)** view content == old-copy content across sampled ticks; **(b)** mutating a returned window **RAISES** and cannot leak into the master; **(c)** the existing 7-rule bar-timing contract tests stay green. **Home:** `tests/unit/price_handler/feed/`. **Rejected:** content + contract only; leaving assertions fully to the planner.
- **D-09 (enforce read-only at source — mark master frames non-writeable at build; subsumes the view-safety mechanism):** Mark each master frame in `self._frames` non-writeable when built (after `__init__` base load and after each `_resampled_frame` resample). Views inherit non-writeable buffers automatically. **Researcher MUST confirm** marking frames non-writeable does not break `resample`/`searchsorted`/the `ta` reads on views; **if it does, fall back** to marking the per-view buffer non-writeable. **Rejected:** audit + test only (no hard runtime guard).
- **D-04 (gate on W2 measurable win + W1 non-regress; re-freeze W1):** Gate (b) for THIS phase = `perf-w2` sweep shows a measurable win AND W1 **does not regress**; re-freeze `W1-BASELINE.json` after. **Rejected:** holding the standard ≥5% W1 bar; a fully soft "any W2 win" with no threshold.
- **D-05 (commit a W2 baseline + ≥10% bar at 50 symbols):** Capture `perf-w2 --json` before/after, commit a `W2-BASELINE.json` (the 50-symbol wall-clock), require a **≥10% improvement at the 50-symbol point**. **Researcher/planner** decides whether `perf-w2` needs a `--check`/`--baseline-out` flag. **Rejected:** before/after artifacts only, no committed baseline or % bar.

### Claude's Discretion
- Exact pandas 2.3.3 view-construction API under D-07, and the precise spot to mark master frames non-writeable under D-09 — within the locked direction + byte-identity + `ta`/`resample` compatibility check.
- Shape/placement of the `_offset_alias` memoization (D-01).
- Exact placement/shape of the drift/equivalence test within the D-08 three-assertion contract.
- Whether to add a `--check`/`--baseline-out` flag to `perf-w2` (vs an ad-hoc before/after capture) to mechanize the D-05 ≥10% verdict.

### Deferred Ideas (OUT OF SCOPE)
- `megaframe()` / screener concat optimization — deferred subsystem; inherits the per-symbol view for free (D-03).
- Monotonic per-(ticker,tf) cursor replacing `searchsorted` — microsecond-class; not worth the state (D-01).
- Removing in-strategy/adapter re-slicing (`catalog.py` `bars[start_dt:]`) — strategy/adapter concern with byte-identity risk, outside the feed (D-01).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-06 | Reduce per-tick bar-feed window `iloc` frame copies (reusable view / cached slice bounds), preserving the look-ahead bar-timing contract — hotspot #5 (~4% W1 / ~22% W2). | **Finding A** pins the exact pandas-2.3.3 view-construction API (it turns out the `.iloc` slice on a homogeneous float64 single-block frame is *already a view* — the headline "copy" cost is NOT the `.iloc` slice itself; see the nuance in §Summary). **Finding B** confirms marking master frames non-writeable breaks nothing (`resample`/`searchsorted`/`ta` reads all pass). **Finding C** gives the exact exception types the D-08 (b) mutation assertion must target. **Validation Architecture** maps the D-08 three-assertion drift test + gate-(b) measurement. |
</phase_requirements>

## Summary

The two CONTEXT-deferred questions are resolved with **HIGH confidence** by direct empirical test against the pinned venv (`pandas 2.3.3`, `numpy 2.2.6`, CoW default **OFF**), not training data.

**The headline finding reframes the win.** On the golden-dataset master frame — a **homogeneous, single-block float64** OHLCV DataFrame with a tz-aware `DatetimeIndex` — `frame.iloc[start:pos]` in pandas 2.3.3 **already returns a view** (`_is_view == True`, `np.shares_memory(...) == True`, **no N×5 data copy of the buffer**). The PERF-BASELINE §2 #5 "each `iloc` slice copies a frame" characterization is imprecise for this homogeneous case: the positional slice does *not* deep-copy the float64 buffer; what is paid per tick is the **DataFrame/BlockManager/axis-object construction overhead** (a new `DataFrame` wrapper, a new sliced `DatetimeIndex`, BlockManager bookkeeping) — `O(1)`-ish in row count, not the `O(N×5)` buffer copy the spike implied. This still scales with `bars × symbols` (every tick, per symbol) and is the W2 ~22% cost, so the win is real — but the planner must understand the win is from **eliminating wrapper-construction churn and (the genuine free win) the per-call `_offset_alias` string compute**, not from eliminating a large data copy that mostly isn't happening on this frame shape.

**The locked design works exactly as written, with one mechanism doing two jobs.** Marking the master frame's underlying numpy buffer `writeable=False` at build time (D-09): (1) makes views inherit `writeable=False` automatically (subsumes D-02's view-safety), and (2) breaks **nothing** that matters — `resample` produces a NEW writeable frame, `index.searchsorted` works on a non-writeable index, and the `ta`-library column reads on views build fresh Series without issue. **No fallback to per-view marking is needed** (D-09's fallback path is not triggered). A view off a non-writeable master compares **byte-identical** (values, dtype, tz-aware index, column set+order; `DataFrame.equals == True`) to today's `frame.iloc[start:pos].copy()`. The empty-window short-circuit (D-06, `frame.iloc[pos:pos]`) is unaffected and stays byte-identical.

**The D-08 (b) mutation assertion has a landmine the planner MUST heed.** The exception raised depends on the mutation *form*, and the project runs `filterwarnings=["error"]`. A pandas-level chained assignment (`view.iloc[0,0] = x`) raises **`SettingWithCopyWarning`** (pandas' copy-detection guard fires first, BEFORE the read-only buffer is even touched) — that does NOT prove the read-only enforcement. The assertion that genuinely proves the non-writeable buffer is a **direct numpy write** to the underlying buffer (`view.to_numpy(copy=False)[0,0] = x` or `view._mgr.blocks[0].values[0,0] = x`), which raises **`ValueError: assignment destination is read-only`**. The D-08 (b) test must target the numpy `ValueError`, optionally also asserting the pandas-path raises.

**Primary recommendation:** Implement D-01/D-07 as: in `window()`, take the existing positional slice and explicitly mark its values buffer non-writeable (belt-and-suspenders, since it already inherits read-only from the master), memoize `_offset_alias` via an instance dict (or `functools.lru_cache` on the module function), and short-circuit empty per D-06. Mark master frames non-writeable at the two build sites (`__init__` base load `:183`, `_resampled_frame` memoize `:273`). Write the D-08 test targeting the **numpy `ValueError`** for assertion (b). Mechanize gate (b) by adding a `--baseline-out`/`--check` flag pair to `run_w2_sweep.py` mirroring `run_w1_benchmark.py`, keyed on the **50-symbol point with a ≥10% bar**.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-tick history-window slice | Data engine / `price_handler.feed` | — | `BacktestBarFeed.window()` is the single look-ahead-safe slice seam (module docstring); the read-only guarantee belongs in the feed, never in consumers (D-02). |
| Master-frame immutability (read-only buffer) | Data engine / `price_handler.feed` build sites | — | The `self._frames` build sites (`__init__` `:181-188`, `_resampled_frame` `:256-274`) are the one-time, out-of-hot-loop place to mark non-writeable (D-09). |
| Indicator compute over the window | Strategy engine / `indicators` | — | `catalog.py` reads `bars[col]` / `bars[start_dt:][col]` and builds NEW Series — pure consumer, never mutates (verified read-only audit, D-02). |
| Behavior-preservation proof | Test tier / `tests/unit/price_handler/feed/` | `tests/unit/price/test_bar_feed.py` (existing contract tests) | D-08 three-assertion drift test; the existing `assert_frame_equal` contract tests are the byte-identity backstop. |
| Gate-(b) measurement | Perf harness / `perf/runners/` | `perf/results/` | W2 sweep + committed `W2-BASELINE.json` (D-05); W1 non-regression guard (D-04). |

## Standard Stack

No new external packages. This phase uses only the **already-pinned, already-installed** stack.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.3.3 | The frame/window type; `.iloc` slice, `resample`, `index.searchsorted` | Already the primary OHLCV structure across all handlers (CLAUDE.md); pinned, CoW-off transition release. `[VERIFIED: venv import]` |
| numpy | 2.2.6 | Underlying buffer; `flags.writeable = False` is the read-only mechanism | `pandas 2.3.3` requires `numpy>=2.2.3,<2.3`; `2.2.6` is what is installed. `[VERIFIED: venv import]` |
| ta | 0.11.0 | Indicator compute over the window (`catalog.py`) — the read-only consumer to keep working | Confirmed reads-only on views (Finding B). `[CITED: CLAUDE.md tech stack]` |

> **Note on the pinned numpy:** CLAUDE.md/Technology-Stack lists `numpy >=2.2.3,<2.3`. The installed wheel is **2.2.6** (verified via `import numpy`), NOT a hypothetical 2.2.3. All empirical findings below are against 2.2.6. `[VERIFIED: venv import]`

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| functools.lru_cache (stdlib) | — | Optional memoization of `_offset_alias` (D-01) | If memoizing at the module-function level; an instance `dict` is the alternative (the feed already holds per-`(ticker, alias)` state). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `numpy.flags.writeable = False` on the values block | `pd.options.mode.copy_on_write = True` | **Rejected by D-02** — process-wide blast radius, and CoW makes a mutating consumer *silently copy* instead of *failing loudly*. The numpy-flag approach is the locked direction. |
| Explicit per-view re-marking | Rely solely on inherited read-only from the master | Inheritance already works (Finding B: views off a non-writeable master have `writeable == False`). A belt-and-suspenders explicit re-mark on the slice costs `O(1)` and documents intent — recommended but not strictly required. |

**Installation:** None. No package added or changed.

**Version verification:**
```
pandas 2.3.3   [VERIFIED: poetry run python -c "import pandas; print(pandas.__version__)"]
numpy  2.2.6   [VERIFIED: poetry run python -c "import numpy;  print(numpy.__version__)"]
CoW default: False   [VERIFIED: pd.options.mode.copy_on_write]
```

## Package Legitimacy Audit

> Not applicable — this phase installs **no external packages**. All libraries used (`pandas`, `numpy`, `ta`, stdlib `functools`) are already in `pyproject.toml`/`poetry.lock` and verified present in the venv. No registry/slopcheck pass required.

## Architecture Patterns

### System Architecture Diagram (the per-tick window path)

```
TimeEvent(T) ─► generate_bar_event ─► BarEvent(bars stamped T)
                                            │
                                            ▼
              strategies_handler.calculate_signals  (per subscribed strategy, per ticker)
                                            │  feed.window(ticker, tf, max_window, asof=T)   [:125, and :294-295 pair]
                                            ▼
        ┌────────────── BacktestBarFeed.window() ──────────────┐
        │ 1. alias = _offset_alias(tf)        ◄── MEMOIZE (D-01)│
        │ 2. frame = self._resampled_frame(ticker, alias)      │
        │      └─ cached master frame in self._frames          │
        │         (marked writeable=False at build, D-09)      │
        │ 3. cutoff = asof - tf + base_tf                      │
        │ 4. pos = frame.index.searchsorted(cutoff, "right")   │
        │ 5a. if empty (start==pos): return frame.iloc[pos:pos]│ ◄── SHORT-CIRCUIT (D-06)
        │ 5b. else: view = frame.iloc[start:pos]               │ ◄── ALREADY A VIEW on float64 single block
        │          (inherits writeable=False; optionally       │     (no buffer copy; D-07)
        │           re-mark the view buffer non-writeable)     │
        └──────────────────────┬───────────────────────────────┘
                               ▼  pd.DataFrame (read-only view, byte-identical to old copy)
              strategy.evaluate(window) ── self.bars = window; self.now = window.index[-1]  [base.py:368-369]
                               │
                               ▼  handle.repopulate(self.bars, now, tf)
              adapter.compute(bars, col, ...) ── reads bars[col] / bars[start_dt:][col]      [catalog.py]
                               │                  builds NEW Series (read-only, never mutates view)
                               ▼
                          SignalEvent  (look-ahead contract preserved end-to-end)
```

### Component Responsibilities
| Component | File | Change in this phase |
|-----------|------|----------------------|
| `BacktestBarFeed.window()` | `bar_feed.py:360-399` | Memoize `_offset_alias`; short-circuit empty (D-06); return read-only view; mark view buffer non-writeable. **4-space indent.** |
| `BacktestBarFeed.__init__` base load | `bar_feed.py:181-188` | Mark each master frame `writeable=False` after `store.read_bars` and before `_spans`/`_prebuilt` build (D-09). |
| `BacktestBarFeed._resampled_frame` | `bar_feed.py:256-274` | Mark the newly-resampled frame `writeable=False` before `self._frames[key] = resampled` (D-09). |
| `_offset_alias` (module fn) | `bar_feed.py:78-121` | Optionally `@lru_cache`; OR memoize in the feed. |
| Consumers (audit only) | `strategies_handler.py:125,294-295`; `base.py:368-369`; `catalog.py`; `handle.py` | **No edits** — read-only audit evidence (D-02). Tab-indent; do NOT touch. |

### Pattern 1: Mark a frame's values buffer non-writeable (D-09)
**What:** Set the underlying numpy block's `writeable` flag to `False` after a frame is built.
**When to use:** At the two `self._frames` write sites (`__init__` base load, `_resampled_frame` memoize).
**Example:**
```python
# Source: empirically verified against pandas 2.3.3 / numpy 2.2.6
# After: frame = store.read_bars(ticker)   (or)  resampled = base.resample(...).agg(_AGG)
# Mark the single float64 block non-writeable so views inherit read-only and any
# in-place mutation of the cached master fails loudly (D-09). Homogeneous float64
# OHLCV => single block => one flag set covers all 5 columns.
frame.to_numpy(copy=False).flags.writeable = False        # [VERIFIED: empirical test]
# (Equivalent lower-level form: frame._mgr.blocks[0].values.flags.writeable = False —
#  prefer the public to_numpy(copy=False) handle; planner picks the exact accessor.)
```
> **Caveat the planner must verify at implement time:** `to_numpy(copy=False)` returns the underlying buffer for a single-block homogeneous frame, but pandas does NOT *contractually* guarantee zero-copy for `to_numpy` in all cases. The empirical test confirmed `np.shares_memory(frame.to_numpy(copy=False), block.values) == True` for this frame shape. The planner should assert `shares_memory` (or use the `_mgr.blocks[0].values` accessor directly) at the build site, and the D-08 test proves the flag actually took effect end-to-end. `[VERIFIED: empirical test]`

### Pattern 2: Return a read-only view from `window()` (D-01/D-07)
**What:** Take the positional slice on the (already non-writeable) master and return it directly; optionally re-mark.
**Example:**
```python
# Source: bar_feed.py:395-399 today + empirical pandas 2.3.3 behavior
alias = self._alias_for(timeframe)              # MEMOIZED (D-01) — see Pattern 3
frame = self._resampled_frame(ticker, alias)
cutoff = asof - timeframe + self._base_timeframe
pos = int(frame.index.searchsorted(cutoff, side="right"))
start = max(0, pos - max_window)
if start >= pos:                                # D-06 empty short-circuit (unchanged semantics)
    return frame.iloc[pos:pos]
view = frame.iloc[start:pos]                    # ALREADY a view on the float64 single block
# view already inherits writeable=False from the master; explicit re-mark documents intent:
view.to_numpy(copy=False).flags.writeable = False   # [VERIFIED: harmless, idempotent on a view]
return view
```
> **Byte-identity guarantee (the hard constraint):** verified that `view` (off a non-writeable master) and today's `frame.iloc[start:pos].copy()` satisfy `np.array_equal(values)`, `dtypes.equals`, `index.equals` (incl. `tz == UTC`), identical column set+order, and `DataFrame.equals(...) == True`. `[VERIFIED: empirical test]`

### Pattern 3: Memoize `_offset_alias` (D-01, the free win)
**What:** Avoid the per-call string compute in `_offset_alias`.
**Example (two options — Claude's discretion):**
```python
# Option A — module-level lru_cache (timedelta is hashable):
import functools

@functools.lru_cache(maxsize=None)
def _offset_alias(timeframe: timedelta) -> str:
    ...  # body unchanged

# Option B — per-feed instance dict (the feed already holds per-(ticker,alias) state):
# self._alias_cache: dict[timedelta, str] = {}
def _alias_for(self, timeframe: timedelta) -> str:
    a = self._alias_cache.get(timeframe)
    if a is None:
        a = _offset_alias(timeframe)
        self._alias_cache[timeframe] = a
    return a
```
> The feed already calls `_offset_alias` at `__init__:146`, `precompute:252`, and `window:395`. Option A is the smallest diff and keeps the function self-contained; Option B avoids a process-global cache across multiple feeds. Either is correct. `[ASSUMED: stylistic — defer to planner]`

### Anti-Patterns to Avoid
- **Reconstructing the window via `pd.DataFrame(view.values, index=..., columns=...)`** — explicitly rejected by D-07; risks tz/dtype/column-order drift → breaks byte-identity. Slice + mark only.
- **Enabling `pd.options.mode.copy_on_write`** — rejected by D-02; makes mutation copy *silently* instead of failing loudly, and is process-wide.
- **Asserting D-08 (b) against `SettingWithCopyWarning`** — that proves pandas' copy-detection, NOT the read-only buffer. Target the numpy `ValueError` (see Finding C / Pitfall 1).
- **Routing the empty window through the view path** — rejected by D-06; pointless read-only marking on a zero-row buffer.
- **"Tidying" the consumer slices in `catalog.py`** — byte-identity risk, out of scope (D-01 deferred).
- **Normalizing indentation** — `bar_feed.py` is **4-space**; consumers are **tab**. This phase edits only the 4-space file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Zero-copy positional slice | A manual numpy-stride view + re-wrap in a DataFrame | `frame.iloc[start:pos]` (already a view on a float64 single block) | pandas already returns a view here; re-wrapping risks index/tz/dtype drift (D-07). |
| Read-only enforcement | A per-tick runtime guard / wrapper class intercepting `__setitem__` | numpy `flags.writeable = False` at build (D-09) | One flag at build time, zero hot-loop cost; mutation fails loudly at the C level. |
| Byte-identity check | A bespoke field-by-field comparison | `pd.testing.assert_frame_equal` / `DataFrame.equals` | The existing contract tests already use `assert_frame_equal` (`test_bar_feed.py:167,183`). |

**Key insight:** The pandas/numpy primitives already do everything D-01/D-09 needs — the work is *wiring the flag at the right build sites* and *proving it with a test*, not building machinery.

## Runtime State Inventory

> Not a rename/refactor/migration phase — this is a behavior-preserving perf change to a single in-memory code path. No stored data, live service config, OS-registered state, secrets, or build artifacts carry phase-relevant state.
>
> - **Stored data:** None — the change is in-process per-tick slicing; no datastore keys change.
> - **Live service config:** None.
> - **OS-registered state:** None.
> - **Secrets/env vars:** None.
> - **Build artifacts:** None — no package rename, no egg-info impact. (`perf/results/W1-BASELINE.json` is re-frozen and `W2-BASELINE.json` is newly committed, but these are data artifacts produced by the phase, not stale state needing migration.)

## Common Pitfalls

### Pitfall 1: The D-08 (b) mutation assertion targets the WRONG exception
**What goes wrong:** A test that does `view.iloc[0, 0] = 999` and asserts it raises will catch a **`SettingWithCopyWarning`** (under `filterwarnings=["error"]`), NOT a read-only `ValueError`. This passes even if the buffer were writeable — pandas' chained-assignment copy-detection fires *before* the buffer is touched. The test would give false confidence that read-only enforcement works.
**Why it happens:** pandas intercepts chained assignment on a slice with its own guard; the numpy read-only flag is only hit by a *direct* buffer write.
**Empirical exception map (`pandas 2.3.3` / `numpy 2.2.6`, `filterwarnings=["error"]`):**
| Mutation form | Raises |
|---------------|--------|
| `view.iloc[0, 0] = x` | `SettingWithCopyWarning` (pandas guard — NOT the read-only proof) |
| `view["close"].iloc[0] = x` | `FutureWarning` (chained-assignment deprecation) |
| `view._mgr.blocks[0].values[0, 0] = x` | **`ValueError: assignment destination is read-only`** ✅ |
| `view.to_numpy(copy=False)[0, 0] = x` | **`ValueError: assignment destination is read-only`** ✅ |
**How to avoid:** Assertion (b) MUST do a **direct numpy write** (`view.to_numpy(copy=False)[0, 0] = x` or the `_mgr.blocks[0].values` form) and assert `ValueError` with `match="read-only"`. Optionally ALSO assert the pandas-path raises (any of the three) to document the layered defense, and assert the master frame is byte-unchanged afterward (no leak). `[VERIFIED: empirical test]`

### Pitfall 2: Assuming the `.iloc` slice is the data copy (it isn't, for this frame)
**What goes wrong:** Planning the change as "eliminate the N×5 float64 copy" and expecting a memory drop proportional to window size. The homogeneous float64 single-block frame's `.iloc[start:pos]` is **already a view** — there is no large buffer copy to eliminate.
**Why it happens:** PERF-BASELINE §2 #5's "each `iloc` slice copies a frame" / "high (each `iloc` slice copies a frame)" is true for *mixed-dtype* frames (pandas copies across blocks), but the OHLCV frame is single-block. The per-tick cost is **DataFrame/Index/BlockManager wrapper construction**, not buffer copy.
**How to avoid:** Frame the win to the planner as **wrapper-construction churn + the `_offset_alias` string compute**, and validate the win by **wall-clock** (the W2 sweep), not by a tracemalloc memory drop (which may be smaller than expected). The ≥10%-at-50-symbols bar (D-05) is wall-clock — correct. `[VERIFIED: empirical test]`

### Pitfall 3: Marking the master non-writeable AFTER `_spans`/`_prebuilt` are derived
**What goes wrong:** The `__init__` loop reads `frame.index[0]`/`frame.index[-1]` (`:184`) and `frame.iterrows()` (`:187`) from the same frame. Marking the *values* buffer non-writeable does not affect index reads or `iterrows` (verified: searchsorted and reads work on non-writeable frames), so ordering is not strictly load-bearing — but mark *after* the frame is fully populated and before it is exposed, to keep the "frames written once, then immutable" invariant honest.
**How to avoid:** Mark immediately after assignment to `self._frames[...]`, i.e. right after `:183` and right before `:273`'s `return`. `[VERIFIED: resample/searchsorted/iterrows all pass on non-writeable frame]`

### Pitfall 4: `_offset_alias` memoization changing the FutureWarning behavior
**What goes wrong:** `_offset_alias` deliberately raises `ValueError` for unsupported timeframes (the Feed-owns-the-map Pitfall 2 in its docstring, guarding against the `'30m'`→MONTH-END FutureWarning). An `lru_cache` does NOT cache exceptions — each unsupported call re-raises — so caching is safe. But verify the cache key (`timedelta`) is hashable (it is) and that the existing `_offset_alias` tests still pass.
**How to avoid:** Keep the `_offset_alias` body byte-unchanged; only wrap/memoize. Run the existing alias tests. `[VERIFIED: timedelta is hashable; lru_cache does not cache exceptions — CPython semantics]`

## Code Examples

### The D-08 three-assertion drift test (skeleton)
```python
# Source: synthesized from D-08 + empirical exception map; home tests/unit/price_handler/feed/
# (planner: reconcile with the existing tests/unit/price/test_bar_feed.py — see Open Question 1)
import numpy as np
import pandas as pd
import pytest

def test_window_view_content_equals_old_copy(daily_feed, daily_base_frame):
    # (a) view content == old-copy content across sampled ticks (byte-identical).
    for asof in SAMPLED_TICKS:
        view = daily_feed.window('BTCUSD', timedelta(days=1), max_window=3, asof=asof)
        expected = daily_base_frame.iloc[<...>:<...>]  # the same positional slice, copied
        pd.testing.assert_frame_equal(view, expected, check_freq=False)

def test_window_view_is_read_only_and_cannot_leak(daily_feed):
    # (b) mutating a returned window RAISES (read-only) and cannot leak into the master.
    view = daily_feed.window('BTCUSD', timedelta(days=1), max_window=3, asof=SOME_TICK)
    before = view.to_numpy().copy()
    with pytest.raises(ValueError, match="read-only"):
        view.to_numpy(copy=False)[0, 0] = 999.0          # DIRECT numpy write — the real proof
    # master unchanged: re-fetch the same window, assert byte-identical to `before`
    again = daily_feed.window('BTCUSD', timedelta(days=1), max_window=3, asof=SOME_TICK)
    assert np.array_equal(again.to_numpy(), before)

# (c) is the existing contract suite staying green — no new test, just don't break
#     tests/unit/price/test_bar_feed.py (assert_frame_equal at :167, :183).
```

### Mechanizing gate (b): add `--check`/`--baseline-out` to `run_w2_sweep.py`
```python
# Source: mirror run_w1_benchmark.py:150-249. Keep the {1,10,50} table for visibility;
# add a W2-BASELINE.json keyed on the 50-symbol wall_clock_s with a ≥10% IMPROVEMENT bar.
def _to_w2_baseline_schema(points: list[dict]) -> dict:
    p50 = next(p for p in points if p["n_symbols"] == 50)
    return {
        "schema_version": 1,
        "frozen_at": dt.date.today().isoformat(),
        "metric": {"wall_clock_s_at_50": round(p50["wall_clock_s"], 2),
                   "peak_mem_mb_at_50": round(p50["peak_mem_mb"], 2)},
        "sweep": {"n_symbols": _N_SYMBOLS_SWEEP, "n_bars": _N_BARS, "seed": _SEED},
        "points": points,
    }

def _check_w2(points, baseline_path, min_improvement_pct=10.0) -> int:
    # PASS (return 0) iff 50-symbol wall_clock improved by >= min_improvement_pct.
    # Mirror run_w1's soft-guard tone but invert the sense (this gate REQUIRES a win).
    base = json.load(open(baseline_path))
    base50 = base["metric"]["wall_clock_s_at_50"]
    now50  = next(p for p in points if p["n_symbols"] == 50)["wall_clock_s"]
    impr = (base50 - now50) / base50 * 100.0
    print(f"W2@50 {now50:.2f}s  improvement {impr:+.1f}%  (baseline {base50:.2f}s)")
    return 0 if impr >= min_improvement_pct else 1
```
> **D-05 sequencing nuance for the planner:** the ≥10% bar compares **after** against a **before** baseline. The before-baseline must be captured on the SAME machine in the SAME session as the after-run (per memory `v15-perf-gateb-thermal-drift` — the box is thermally sensitive; a frozen cross-session baseline can drift). Recommend: capture `--baseline-out W2-BASELINE-pre.json` immediately before the change, run `--check` after, and commit the *after* run as the standing `W2-BASELINE.json` (which seeds Phase 5). `[VERIFIED: memory note v15-perf-gateb-thermal-drift; CITED: D-05]`

## State of the Art

| Old Approach | Current Approach (pandas 2.3.3) | When Changed | Impact |
|--------------|----------------------------------|--------------|--------|
| `.iloc` slice copy/view ambiguous; SettingWithCopyWarning era | CoW **opt-in** (default OFF in 2.3.x); homogeneous single-block `.iloc` slice returns a **view** | 2.3.x is the CoW transition release; CoW becomes default in 3.0 (Jan 2026) | This phase deliberately stays on the **CoW-off** path and enforces read-only via numpy flags (D-02 rejects global CoW). When the project eventually moves to pandas 3.0, the numpy-flag mechanism still works; CoW would *additionally* make mutations copy silently — but the explicit non-writeable buffer still raises loudly, so the D-08 guarantee survives the upgrade. |

**Deprecated/outdated:**
- Global `pd.options.mode.copy_on_write` as a safety mechanism here — rejected (D-02). It is the pandas-3.0 default but is the wrong tool for "fail loudly on mutation."

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `_offset_alias` memoization shape (lru_cache vs instance dict) is stylistic — either is correct | Pattern 3 | Low — both verified to preserve the raise-on-unsupported behavior; planner picks. |
| A2 | The win is wrapper-construction churn + alias string compute, not a large buffer copy | Pitfall 2 / Summary | Medium — if a future frame shape were mixed-dtype (it is not for golden OHLCV), `.iloc` WOULD copy and the win would be larger. The golden frame is verified single-block float64, so this holds for the gated path. |
| A3 | `--check`/`--baseline-out` on `run_w2_sweep.py` is the right mechanization (vs ad-hoc) | gate (b) | Low — D-05 explicitly leaves this to researcher/planner; the mirror of `run_w1` is the established pattern and also seeds Phase 5. |

**Note:** The two load-bearing technical claims (view-construction API, non-writeable-breaks-nothing, exception types, byte-identity) are all `[VERIFIED: empirical test]`, not assumed.

## Open Questions (RESOLVED)

> Both questions are advisory placement/stylistic choices (not technical unknowns) and are
> resolved in the plan action sections.

1. **D-08 test home vs existing contract tests.** **RESOLVED:** co-locate in
   `tests/unit/price/test_bar_feed.py` per 06-01 Task 0 action; D-08's literal
   `tests/unit/price_handler/feed/` path is treated as directional.
   - What we know: D-08 says home is `tests/unit/price_handler/feed/` (which does **not exist** yet). The existing 7-rule bar-timing contract tests live in `tests/unit/price/test_bar_feed.py` (383 lines, uses `assert_frame_equal` at `:167`/`:183` — the byte-identity backstop for assertion (c)).
   - What's unclear: whether to create the new `tests/unit/price_handler/feed/` dir per D-08's literal text, or co-locate the new drift test with the existing contract tests in `tests/unit/price/test_bar_feed.py`.
   - Recommendation: Co-locate the new drift test in `tests/unit/price/test_bar_feed.py` (or a sibling `test_bar_feed_window_view.py` in the SAME dir) so the existing contract suite (assertion (c)) and the new (a)/(b) assertions live together and run as one unit. Treat D-08's path as directional, not literal. Confirm with the planner; this is a placement decision, not a correctness one.

2. **Whether to add the explicit per-view re-mark.** **RESOLVED:** include the
   belt-and-suspenders re-mark per 06-01 Task 1 action (cheap, documents intent,
   survives a future refactor that forgets to mark a master). Redundant for safety
   but low-stakes positive.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pandas | window slice / resample / searchsorted | ✓ | 2.3.3 | — |
| numpy | read-only buffer flag | ✓ | 2.2.6 | — |
| ta | indicator reads on the view (consumer audit) | ✓ | 0.11.0 | — |
| poetry venv | running tests + perf runners | ✓ | in-project `.venv` | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

> **Worktree note (memory `worktree-venv-shadowing` / `worktree-make-test-env-abort`):** the current branch is a worktree (`v1.5/phase-6-bar-feed-window-copies`). `make test` may abort on a missing `.env`; run `poetry run pytest tests` in the worktree and re-run `make test` in the main checkout for the gate. Prepend `PYTHONPATH="$PWD"` if the editable install shadows worktree edits.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error", ...]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/price/test_bar_feed.py -q` |
| Full suite command | `make test` (main checkout) / `poetry run pytest tests` (worktree) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-06 (a) | View content == old-copy content across sampled ticks (byte-identical values/dtype/tz-index/columns) | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k content_equals -q` | ❌ Wave 0 (new drift test) |
| PERF-06 (b) | Mutating a returned window RAISES read-only `ValueError` and cannot leak into the master | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k read_only -q` | ❌ Wave 0 (new drift test) |
| PERF-06 (c) | Existing 7-rule bar-timing contract stays green | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -q` | ✅ exists (`:124-201`, uses `assert_frame_equal`) |
| Gate (a) | Byte-exact SMA_MACD oracle (134 / `46189.87730727451`) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists (memory `oracle-test-location`) |
| Gate (a) | `mypy --strict` clean | static | `poetry run mypy itrader` | ✅ infra exists |
| Gate (a) | Determinism double-run byte-identical | integration | (run oracle twice; assert identical) | ✅ oracle is deterministic |
| Gate (b) | W2 ≥10% improvement at 50 symbols + W1 non-regress | perf | `make perf-w2` (+ new `--check`); `make perf-w1` | ⚠️ W2 needs `--check`/`--baseline-out` (Wave 0) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/price/test_bar_feed.py -q` (the drift + contract tests — fast, <30s).
- **Per wave merge:** `make test` (full unit/integration suite) + `poetry run mypy itrader`.
- **Phase gate (a):** `poetry run pytest tests/integration/test_backtest_oracle.py` green (134 / `46189.87730727451`), `mypy --strict` clean, determinism double-run identical, full suite green.
- **Phase gate (b):** `make perf-w2 --check` shows ≥10% improvement at 50 symbols AND `make perf-w1` (`--check`) shows W1 within band (no regression); then re-freeze `W1-BASELINE.json` (`make perf-baseline`) and commit `W2-BASELINE.json`.

### Wave 0 Gaps
- [ ] `tests/unit/price/test_bar_feed.py` (or sibling in same dir) — add assertions (a) content-equality and (b) read-only-raises (Open Question 1 — placement). Assertion (b) MUST target the numpy `ValueError` (Pitfall 1).
- [ ] `perf/runners/run_w2_sweep.py` — add `--baseline-out`/`--check` flags mirroring `run_w1_benchmark.py` (D-05; Code Examples). Add `perf-w2-baseline` / `perf-w2 --check` Makefile wiring as needed.
- [ ] `perf/results/W2-BASELINE.json` — capture and commit the after-run 50-symbol baseline (seeds Phase 5).
- [ ] `perf/results/W1-BASELINE.json` — re-freeze after the change (D-04).
- Framework install: none — pytest infra already present.

## Security Domain

> Not applicable in the conventional ASVS sense — this is an internal, offline backtest data-path optimization with no auth/session/network/input-validation surface. The one *integrity* concern is look-ahead/data-corruption (a future tick reading a mutated past bar), which is exactly what D-09's read-only enforcement defends — covered by the Validation Architecture (D-08 assertion (b)) above. No external `security_enforcement` config artifact is touched; no new attack surface is introduced.

| Integrity threat | STRIDE | Mitigation (this phase) |
|------------------|--------|-------------------------|
| A consumer mutates a shared view → poisons a future tick (silent look-ahead breach) | Tampering | numpy `writeable=False` on the master buffer (D-09) → mutation raises `ValueError`; proven by D-08 assertion (b). |

## Sources

### Primary (HIGH confidence)
- **Empirical test against the pinned venv** (`pandas 2.3.3`, `numpy 2.2.6`, CoW default `False`) — the load-bearing source. Verified: `.iloc` slice on a homogeneous float64 single-block frame is already a view (`_is_view`, `shares_memory`); non-writeable master does not break `resample`/`searchsorted`/`ta` reads; view inherits `writeable=False`; byte-identity (`DataFrame.equals`, dtype/tz-index/column-order); the mutation-form→exception map (`SettingWithCopyWarning` / `FutureWarning` / `ValueError read-only`); empty-window `iloc[pos:pos]` semantics preserved. `[VERIFIED]`
- `itrader/price_handler/feed/bar_feed.py` — target code (`window:360-399`, `_resampled_frame:256-274`, `__init__:181-188`, `_offset_alias:78-121`). `[VERIFIED: read]`
- `itrader/strategy_handler/{strategies_handler.py,base.py,indicators/catalog.py,indicators/handle.py}` — consumer read-only audit evidence. `[VERIFIED: read]`
- `perf/runners/{run_w1_benchmark.py,run_w2_sweep.py}`, `Makefile:99-112` — the `--check`/`--baseline-out` pattern to mirror. `[VERIFIED: read]`
- `perf/results/PERF-BASELINE-RESULTS.md` §2 #5, §3 — the spike (authoritative hotspot source). `[VERIFIED: read]`
- `tests/unit/price/test_bar_feed.py` — existing 7-rule contract tests + `assert_frame_equal` byte-identity backstop. `[VERIFIED: read]`

### Secondary (MEDIUM confidence)
- pandas 2.3.0 / 3.0 whatsnew + PDEP-7 (CoW transition: opt-in in 2.3.x, default in 3.0) — confirms the CoW posture this phase deliberately avoids. `[CITED]`

### Tertiary (LOW confidence)
- None — the technical claims were promoted to HIGH via empirical verification.

## Metadata

**Confidence breakdown:**
- View-construction API (D-07): **HIGH** — empirically verified `.iloc` is already a view, byte-identity confirmed.
- Non-writeable-breaks-nothing (D-09): **HIGH** — `resample`/`searchsorted`/`ta` reads all verified passing; no fallback needed.
- Mutation exception types (D-08 b): **HIGH** — exact map captured under `filterwarnings=["error"]`.
- Gate-(b) mechanization (D-05): **MEDIUM** — the `--check`/`--baseline-out` mirror is the established pattern; thermal-drift sequencing per memory note.
- Win characterization (Pitfall 2): **HIGH** — verified single-block float64 means no large buffer copy; win is wrapper churn + alias compute.

**Research date:** 2026-06-24
**Valid until:** 2026-07-24 (stable — pinned pandas/numpy; re-verify if pandas is bumped toward 3.0, which flips CoW default).
