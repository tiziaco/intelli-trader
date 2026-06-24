# Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able) - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 reduces the per-tick **frame-copy** cost on `BacktestBarFeed.window()` (PERF-06, hotspot #5,
~4% W1 / ~22% W2 — it scales with symbol count). Today `window()` does
`_offset_alias(timeframe)` + `frame.index.searchsorted(cutoff)` + **`frame.iloc[start:pos]`**, and
that final positional slice materializes a fresh DataFrame (data copy of N×5 float64) **every tick,
per symbol, per strategy** (`strategies_handler.py:125`, and twice per pair strategy at `:294-295`).
The fix replaces that copy with a **read-only view** sharing the cached master frame's buffer,
preserving all 7 rules of the look-ahead bar-timing contract (`feed/bar_feed.py` module docstring).

This is a v1.5 **behavior-preserving** perf phase: it re-baselines **nothing** numeric. The window is
the `ta` float64 OHLCV domain (D-17), **not** money — no Decimal/float surface is touched, no oracle
re-baseline.

**In scope:**
- `BacktestBarFeed.window()` only — replace the `.iloc` data copy with a read-only view; memoize
  `_offset_alias` (D-01).
- Hard read-only enforcement implemented by marking the **master frames** (`self._frames`)
  non-writeable at build time, so views inherit non-writeable buffers and any mutation fails loudly
  at source (D-02 + D-09 — one mechanism).
- Empty-window short-circuit (D-06); slice-and-mark construction direction (D-07).
- Behavior-preservation drift/equivalence test + audit (D-08).
- Gate (b) judged on the W2 sweep + W1 non-regression; commit a W2 baseline (D-04, D-05).

**Out of scope (behavior-preserving milestone — changes NO numbers):**
- `megaframe()` / screener path rework (D-03 — deferred subsystem; inherits the per-symbol view for
  free; its `pd.concat` is inherent multi-symbol assembly).
- `current_bars()` (already de-pandas'd to a dict lookup in a prior phase, D-07 there).
- Changing the `window()` **return type** away from a `pd.DataFrame` (consumers label-slice the index:
  `bars[start_dt:][input_col]`, `window.index[-1]`).
- Rewriting in-strategy/adapter slicing (`catalog.py` `bars[start_dt:]`) — byte-identity risk, not the
  feed's concern.
- Any money / float / Decimal change; any oracle re-baseline.

**Gate (inherited from Phase 1 D-04, with a phase-specific gate-(b) verdict — see D-04/D-05):**
- **Gate (a):** byte-exact SMA_MACD oracle green (134 trades / `final_equity 46189.87730727451`); the
  e2e suite green; `mypy --strict` clean; determinism double-run byte-identical.
- **Gate (b):** the perf-w2 sweep shows a measurable win (≥10% at 50 symbols) AND W1 does not regress;
  re-freeze `W1-BASELINE.json` and commit a `W2-BASELINE.json` after.

**OPTIONAL / slip-able note:** this is the optional, contract-gated item, independent of Phases 2–5
and sequenced last (Phase 5 — Incremental Indicators, FRAGILE — is deferred to run AFTER this). The
phase is fully intended to land now; the gate (b) verdict (D-04) is framed so a W2-dominant win is
judged honestly rather than failing the W1-only ≥5% bar by design.

</domain>

<decisions>
## Implementation Decisions

### Copy-reduction mechanism (PERF-06)
- **D-01 (view-primary + memoize alias; `searchsorted` stays):** Replace `frame.iloc[start:pos]` (a
  per-tick data copy of N×5 float64) with a **read-only view** sharing the cached master frame's
  buffer — this is the named "frame copy" cost and the real win, scaling with symbol count (the ~22%
  W2). Bundle the trivial free extra: memoize `_offset_alias(timeframe)` (string compute per call).
  `window()` **keeps returning a `pd.DataFrame`** (consumers label-slice the index). `searchsorted`
  is left as-is — it is O(log ~2900) ≈ microsecond-class, not the hotspot. **Rejected:** a monotonic
  per-(ticker,tf) cursor to replace `searchsorted` (added state for a microsecond gain); bounds-only
  caching that keeps the copy (leaves the headline cost on the table); returning a bare numpy array
  (breaks the label-slicing consumers).

### View-aliasing safety / master-frame immutability (the look-ahead invariant)
- **D-02 (hard read-only at the feed boundary; mutation fails loudly at source — NOT a global flag):**
  A view aliases the cached master frame, so an in-place mutation by any consumer would silently
  poison **future** ticks (a look-ahead breach). All current consumers are **verified read-only**
  (the window lands on `strategy.bars`; indicator `compute` reads `bars[input_col]` /
  `bars[start_dt:][input_col]` and builds new Series — see `indicators/catalog.py`, `handle.py`). The
  guarantee is enforced **at the source** (see D-09), so a mutation attempt raises loudly rather than
  silently corrupting state, plus a written audit and a drift test (D-08). **Rejected:** global
  `pd.options.mode.copy_on_write` (process-wide blast radius + byte-identity risk in a byte-exact
  phase; mutation copies silently instead of failing loudly); audit + test only with no runtime guard.
- **D-09 (enforce read-only at source — mark master frames non-writeable at build; this *subsumes*
  the view-safety mechanism):** Mark each master frame in `self._frames` non-writeable when it is
  built (after the `__init__` base load and after each lazy/eager `_resampled_frame` resample). Views
  then inherit non-writeable buffers automatically (one mechanism implements D-02's view-safety too)
  **and** any accidental in-place mutation of a cached master frame also fails loudly. Lazy resample
  still **inserts NEW frames** as dict keys (never mutates an existing frame), each marked read-only on
  build — so the "frames written once, never mutated after" invariant holds and is now hard-enforced.
  **Researcher MUST confirm** marking frames non-writeable does not break `resample`/`searchsorted`/
  the `ta` reads on views; **if it does, fall back** to marking the per-view buffer non-writeable
  instead (D-07 direction still applies). **Rejected:** audit + test only (no hard runtime guard
  against a future master mutation).

### Path scope
- **D-03 (`window()` only):** `window()` is the oracle-relevant path AND the one that scales with
  symbol count (the W2 win). `megaframe()` (screener path, a **deferred** subsystem, likely not in the
  W1/W2 benchmark) inherits the read-only view for free on its per-symbol `window()` calls; its
  `pd.concat` assembly is inherent and not worth separate work in a behavior-preserving phase.
  `current_bars()` is already a pure dict lookup. **Rejected:** also reworking `megaframe()`'s
  concat (added contract surface for little gated payoff in a deferred subsystem).

### Empty-window edge
- **D-06 (short-circuit empty; return the existing slice unchanged):** When the cutoff lands at the
  frame start, `window()` returns `frame.iloc[pos:pos]` (size-0). An empty slice carries zero rows →
  zero data-copy cost **and** zero aliasing risk (no shared data), so empty windows **bypass the view
  + read-only machinery entirely** and return the existing `frame.iloc[pos:pos]` unchanged. This keeps
  byte-identical empty semantics (float64 dtype, tz-aware index, column set/order) that the
  empty-window guard (`base.py:347-351`, `window.index[-1]` would raise on size-0) and consumer
  `.empty`/`len` checks rely on, and sidesteps any `writeable=False`-on-empty concern. **Rejected:**
  routing empty windows through the uniform view path (pointless read-only marking on an empty buffer,
  must prove it's a no-op, zero gain).

### View-construction approach
- **D-07 (set direction; researcher pins the exact API):** **Direction (locked):** operate on the
  **sliced existing frame** and mark it read-only, preserving dtype / tz-aware `DatetimeIndex` /
  column set+order **exactly** — do **NOT** reconstruct via a new `pd.DataFrame(...)` (which risks
  index/tz/dtype drift and would break byte-identity). The exact pandas 2.3.3 view/CoW API + the
  `ta`-read compatibility check are **researcher/planner** territory, with **byte-identity as the hard
  constraint**. **Rejected:** pinning the precise construction call now (premature — depends on pinned
  pandas mechanics); fully deferring (doesn't steer away from the risky reconstruct path).

### Behavior-preservation proof (criterion #2/#3 — gate (a) does not observe window internals)
- **D-08 (drift/equivalence test — all three assertions; mirrors Phase 3 D-03 / Phase 4 D-06-07):**
  A dedicated test that asserts **(a)** view content == old-copy content across sampled ticks (capture
  a `.copy()` and compare — byte-identical values, dtype, index); **(b)** mutating a returned window
  **RAISES** and cannot leak into the master frame (proves D-02/D-09); **(c)** the existing 7-rule
  bar-timing contract tests stay green. **Home:** `tests/unit/price_handler/feed/`. **Rejected:**
  content + contract only (drops the direct proof of the safety guarantee); leaving assertions fully
  to the planner.

### Gate (b) verdict for a W2-dominant phase (PERF-06 is ~4% W1 / ~22% W2)
- **D-04 (gate on W2 measurable win + W1 non-regress; re-freeze W1):** The standard milestone gate (b)
  ≥5% bar is **W1-only**, and this phase is ~4% W1 **by design** — its win lives in the symbol-dense
  W2 sweep (success criterion: "most visible in the W2 symbol sweep"). So gate (b) for THIS phase =
  the `perf-w2` sweep shows a measurable win AND W1 **does not regress** (W1 stays the
  oracle-relevant non-regression guard); re-freeze `W1-BASELINE.json` after. **Rejected:** holding the
  standard ≥5% W1 bar (the phase can't pass it by design → would force an unwarranted slip/drop);
  a fully soft "any W2 win + W1 non-regress, no threshold" (looser than prior phases' concrete bars).
- **D-05 (commit a W2 baseline + ≥10% bar at 50 symbols):** Capture `perf-w2 --json` before/after,
  commit a `W2-BASELINE.json` (the 50-symbol wall-clock) as the concrete, reproducible pass record,
  and require a **≥10% improvement at the 50-symbol point**. `perf-w2` today is a visibility sweep with
  no `--check`/baseline — this seeds the standing W2 reference, which **also benefits Phase 5**
  (Incremental Indicators, W2-relevant, runs after this). **Researcher/planner** decides whether
  `perf-w2` needs a `--check`/`--baseline-out` flag (mirroring `run_w1_benchmark`) to mechanize it.
  **Rejected:** recording before/after in artifacts only with no committed baseline or % bar (no
  concrete threshold, nothing seeded for Phase 5).

### Claude's Discretion
- Exact pandas 2.3.3 view-construction API under D-07 (slice + mark read-only), and the precise spot
  to mark master frames non-writeable under D-09 — within the locked direction + byte-identity
  constraint + the `ta`/`resample` compatibility check.
- Shape/placement of the `_offset_alias` memoization (D-01).
- Exact placement/shape of the drift/equivalence test within the D-08 three-assertion contract.
- Whether to add a `--check`/`--baseline-out` flag to `perf-w2` (vs an ad-hoc before/after capture)
  to mechanize the D-05 ≥10% verdict.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Target code — the single file this phase edits
- `itrader/price_handler/feed/bar_feed.py` — **THE** target. The 7-rule bar-timing contract is in the
  module docstring (lines 9-55, the look-ahead invariant this phase MUST preserve); `window()` at
  **:360-399** (the `_offset_alias` + `searchsorted` + `frame.iloc[start:pos]` copy to view-ify, D-01);
  `_resampled_frame` at **:256-274** and `__init__` base load at **:181-188** (where master frames
  enter `self._frames` — the mark-read-only sites, D-09); `current_bars` at :335-356 (already
  de-pandas'd, out of scope); `megaframe` at :403-443 (out of scope, D-03). **4-space indent.**

### Consumers (read-only audit, D-02) — explain why a view is safe
- `itrader/strategy_handler/strategies_handler.py` — `feed.window(...)` at **:125** (single-symbol,
  per tick), **:294-295** (pair strategy, two windows). **Tab indent — read-only.**
- `itrader/strategy_handler/base.py` — `evaluate()` stashes the window on `self.bars` (**:368**) and
  `self.now = window.index[-1]`; the **empty-window guard** at **:346-351** (D-06 must preserve this).
  **Tab indent.**
- `itrader/strategy_handler/indicators/handle.py` — `repopulate(bars, ...)` → `adapter.compute(...)`.
- `itrader/strategy_handler/indicators/catalog.py` — the 5 `compute` paths (`:49/:64/:90/:122/:145`),
  all read-only column/label access (`bars[input_col]`, `bars[start_dt:][input_col]`) — the evidence
  consumers don't mutate the window. **Read-only — do NOT "tidy" the slicing (byte-identity).**

### Milestone scope + requirements + gate
- `.planning/REQUIREMENTS.md` — **PERF-06** (optional) + the milestone gate (a)/(b) definition.
- `.planning/ROADMAP.md` — Phase 6 entry + Success Criteria (4 criteria; criterion 4 = "most visible in
  the W2 symbol sweep", the basis for D-04) + the v1.5 behavior-preserving framing.
- `.planning/STATE.md` — milestone gate (a)/(b) full text; the deliberate 6-before-5 reorder.

### Perf harness + baselines (gate (b), D-04/D-05)
- `Makefile` — `perf-w1` (gated `--check` vs frozen baseline, **:99-101**), `perf-w2`
  (scaling sweep {1,10,50}, `--json`, **:104-106**), `perf-baseline` (re-freeze W1, **:110-112**).
- `perf/runners/run_w1_benchmark.py` — the W1 runner (`--check`/`--json`/`--baseline-out` flags; the
  pattern to mirror if `perf-w2` gets a `--check`/`--baseline-out`).
- `perf/runners/run_w2_sweep.py` — the W2 sweep runner (D-05 captures/commits its 50-symbol number).
- `perf/results/W1-BASELINE.json` — the frozen W1 reference (re-frozen after this phase, D-04).
  `perf/results/PERF-BASELINE-RESULTS.md` — §2 ranked hotspots (**#5** = bar-feed window copies),
  §6 phase breakdown, §7 exit criteria. **Authoritative source — the spike IS the research.**

### Precedent phases (the audit-the-invariant + dedicated test pattern, reused as D-08/D-09)
- `.planning/phases/03-running-pnl-accumulator/03-CONTEXT.md` — D-03 audit-the-invariant + equivalence
  test precedent.
- `.planning/phases/04-hot-path-discipline/04-CONTEXT.md` — D-06/D-07 behavior-preservation drift-lock
  precedent (proof without re-paying cost), and the Phase-1 D-04 ≥5%/single-timed-run gate inheritance.
- `.planning/phases/01-perf-tooling-baseline/01-CONTEXT.md` — D-04 gate (b) definition + the baseline /
  regression-guard tooling.

### Gate (a) — correctness lock (held, not changed)
- `tests/integration/test_backtest_oracle.py` — byte-exact SMA_MACD oracle (134 /
  `46189.87730727451`). (Per memory `oracle-test-location`: this is the oracle; `tests/golden` is
  artifacts, 0 tests collected.)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The window path is already a single, tight slice** — `window()` is the one method to change; the
  master frames are already cached in `self._frames` and (per the module design) written once at
  build / first resample, so a view aliasing them is well-defined (D-01/D-09).
- **`current_bars` already shows the de-pandas pattern** — it was front-loaded to a `{ticker:{time:Bar}}`
  dict in a prior phase (D-07 there); this phase applies the analogous "stop re-materializing per tick"
  idea to the history-window path, but via a view (the window must stay a DataFrame).
- **The W1/W2 harness exists** — `run_w1_benchmark` (gated `--check`) and `run_w2_sweep` (`--json`)
  from Phase 1; D-05 only adds a committed W2 baseline + threshold on top.

### Established Patterns
- **Look-ahead safety is an ENGINE invariant enforced in the window slice** (module docstring), never a
  strategy responsibility — so the read-only guarantee belongs in the feed (D-02/D-09), not in
  consumers.
- **Audit-the-invariant + dedicated equivalence/regression test, no hot-path runtime guard**
  (Phase 3 D-03, Phase 4 D-06/D-07) — reused here as D-08 (drift test) and D-09 (build-time read-only
  enforcement, not a per-tick guard).
- **Indentation hazard (CLAUDE.md):** `bar_feed.py` is **4-space**; `strategies_handler.py` /
  `base.py` / `handle.py` / `catalog.py` are **tab**. Match each file — never normalize. (This phase
  edits only the 4-space `bar_feed.py`.)

### Integration Points
- The change is internal to `BacktestBarFeed.window()` + the `self._frames` build sites — no
  event-queue, handler, ABC, or public-signature change. `window()` keeps its
  `(ticker, timeframe, max_window, asof) -> pd.DataFrame` signature; all callers are unchanged (D-01).
- The read-only marking lands at the frame-build sites (`__init__` base load, `_resampled_frame`
  memoize) — a one-time cost at construction/first-access, not the hot loop (D-09).

</code_context>

<specifics>
## Specific Ideas

- The win is killing the per-tick **frame copy** in `window()` via a read-only view — NOT caching
  `searchsorted` bounds (already cheap) and NOT touching the return type (D-01).
- Read-only is enforced **at the master frame** (mark non-writeable at build), which makes both the
  view aliasing safe and the master immutable in one mechanism (D-02 + D-09) — mutation fails loudly
  rather than silently poisoning a future tick.
- Empty windows are short-circuited and returned exactly as today — they carry no copy cost and no
  aliasing risk (D-06).
- Gate (b) is judged on the **W2 sweep** (≥10% at 50 symbols, committed `W2-BASELINE.json`) with **W1
  non-regression** — because PERF-06 is ~4% W1 / ~22% W2 by design (D-04/D-05).
- View-construction stays **slice + mark read-only** on the existing frame (preserve dtype/tz-index/
  columns); the exact pandas API is the researcher's to pin against pinned pandas 2.3.3, byte-identity
  the hard constraint (D-07).

</specifics>

<deferred>
## Deferred Ideas

- **`megaframe()` / screener concat optimization** — the screener is a deferred subsystem and its
  multi-symbol `pd.concat` is inherent assembly; it inherits the per-symbol view for free. Revisit
  only if/when the production screener is built (N+4 Live Trading Readiness) and W2 measurement shows
  it dominates (D-03).
- **Monotonic per-(ticker,tf) cursor replacing `searchsorted`** — a microsecond-class gain over the
  existing O(log n) `searchsorted`; not worth the added per-(ticker,tf) state in this phase (D-01).
  Could be revisited if a future profile shows `searchsorted` itself as a hotspot.
- **Removing the in-strategy/adapter re-slicing** (`catalog.py` `bars[start_dt:]` building an
  intermediate per compute) — a strategy/adapter concern with byte-identity risk, outside the feed's
  window path. Revisit in a future non-byte-exact cleanup if it profiles hot (D-01 out-of-scope note).

</deferred>

---

*Phase: 6-bar-feed-window-copies-optional-slip-able*
*Context gathered: 2026-06-24*
