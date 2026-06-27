# Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able) - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 4 (1 modify-source, 1 create-test, 2 modify-perf-harness)
**Analogs found:** 4 / 4 (all exact or in-file)

This is a narrow, behavior-preserving perf phase. The file list is already pinned by
CONTEXT.md `canonical_refs` — this map's job is to point each edit at the single best
in-repo pattern to copy and to surface the load-bearing excerpts so the planner does not
re-discover them.

> **Indentation hazard (CLAUDE.md / RESEARCH anti-pattern):** `bar_feed.py` is **4-space**.
> The consumers (`strategies_handler.py`, `base.py`, `catalog.py`, `handle.py`) are **tab** and
> are NOT edited this phase. The test files and perf runners are **4-space**. Match each file;
> never normalize.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/price_handler/feed/bar_feed.py` (MODIFY: `window`, `_resampled_frame`, `__init__`, `_offset_alias`) | feed / read-model | request-response (per-tick slice read) | itself — `window()` body + `current_bars()` de-pandas precedent in the SAME file; Phase 4 `_declared_hints` memoize precedent | in-file (self-analog) |
| `tests/unit/price/test_bar_feed.py` (MODIFY/CREATE: add drift+read-only assertions, or sibling `test_bar_feed_window_view.py`) | test | transform / equivalence-assert | `tests/unit/portfolio/test_realised_pnl_accumulator.py` (Phase 3 D-03) + `tests/unit/strategy/test_type_hints_equivalence.py` (Phase 4 D-05/D-07) + the existing `test_bar_feed.py` contract tests (assertion c) | exact (two precedent drift-locks + in-file contract suite) |
| `perf/runners/run_w2_sweep.py` (MODIFY: add `--check`/`--baseline-out`) | config / perf-runner | batch (sweep) + transform (schema) | `perf/runners/run_w1_benchmark.py` (`--check`/`--baseline-out`/`--json` flag plumbing) | exact (sibling runner, same pattern) |
| `Makefile` (MODIFY: `perf-w2` gating + `perf-w2-baseline`) | config | request-response (task target) | `Makefile` `perf-w1` / `perf-baseline` targets `:99-112` | exact (sibling target) |
| `perf/results/W2-BASELINE.json` (CREATE: committed baseline) | config / data artifact | — | `perf/results/W1-BASELINE.json` (schema to mirror) | exact (sibling artifact) |

---

## Pattern Assignments

### `itrader/price_handler/feed/bar_feed.py` (feed, request-response) — **4-space**

**Analog:** itself. The win is killing per-tick wrapper churn in `window()` (D-01) and
marking master frames read-only at the two build sites (D-09). The de-pandas precedent
(`current_bars`, already front-loaded to a dict in a prior phase) and the Phase 4 memoize
pattern are the in-repo templates.

**Existing `window()` to view-ify** (`:395-399` — the `_offset_alias` + `searchsorted` +
`frame.iloc[...]` slice; THIS is the slice to keep, the alias call to memoize, and the empty
case to short-circuit per D-06):
```python
        alias = _offset_alias(timeframe)
        frame = self._resampled_frame(ticker, alias)
        cutoff = asof - timeframe + self._base_timeframe
        pos = int(frame.index.searchsorted(cutoff, side="right"))
        return frame.iloc[max(0, pos - max_window):pos]
```
> RESEARCH Pitfall 2: on the homogeneous float64 single-block golden frame the `.iloc` slice
> is **already a view** — there is no large buffer copy. The win is wrapper-construction churn +
> the per-call `_offset_alias` string compute, validated by **wall-clock** (W2), not tracemalloc.
> D-07: slice-and-mark; do NOT reconstruct via `pd.DataFrame(...)` (byte-identity risk).
> D-06: short-circuit `start >= pos` → `return frame.iloc[pos:pos]` unchanged (bypass the view path).

**Master-frame build sites to mark non-writeable** (`__init__` base load `:181-188` and
`_resampled_frame` memoize `:264-274`). The two `self._frames[...] = ...` writes are the
one-time, out-of-hot-loop mark sites (D-09):
```python
        # __init__ base load (:181-188) — mark right after the frame enters self._frames
        for ticker in self._symbols:
            frame = store.read_bars(ticker)
            self._frames[(ticker, self._base_alias)] = frame      # <-- mark non-writeable here (D-09)
            self._spans[ticker] = (frame.index[0], frame.index[-1])
            self._prebuilt[ticker] = {
                ts: Bar.from_row(ts, row)
                for ts, row in frame.iterrows()                   # iterrows still works on non-writeable (Pitfall 3)
            }
```
```python
        # _resampled_frame memoize (:272-274) — mark before the return
        resampled = base.resample(alias, label="left", closed="left").agg(_AGG)
        self._frames[key] = resampled                             # <-- mark non-writeable here (D-09)
        return resampled
```
> RESEARCH Pattern 1 + Caveat: use the public handle `frame.to_numpy(copy=False).flags.writeable = False`
> (single float64 block ⇒ one flag covers all 5 cols), OR the lower-level `frame._mgr.blocks[0].values.flags.writeable = False`.
> Assert `np.shares_memory(...)` at the build site if using `to_numpy(copy=False)` (not contractually zero-copy in all cases). `resample`/`searchsorted`/`iterrows`/`ta`-reads all verified to work on a non-writeable master — **no D-09 fallback needed.**

**De-pandas precedent in the SAME file** — `current_bars()` (`:335-356`) was front-loaded to a
`{ticker: {time: Bar}}` dict in a prior phase (D-07 there). Its docstring frames the
"structural hot-loop de-pandas, bit-identical" rationale this phase mirrors for the
history-window path (but the window must stay a `pd.DataFrame`, D-01). Copy the docstring
tone (decision-tag-anchored WHY) when documenting the view change.

**Memoize `_offset_alias`** (`:78-121`) — the free win (D-01). Two locked-direction options:
- **Option A (smallest diff):** wrap the module fn with `@functools.cache` / `@functools.lru_cache(maxsize=None)`. `timedelta` is hashable; `lru_cache` does NOT cache exceptions, so the raise-on-unsupported guard is preserved (RESEARCH Pitfall 4).
- **Option B:** per-feed instance dict (`self._alias_cache: dict[timedelta, str]`).

> **Best in-repo memoize template = Phase 4 `_declared_hints`** (`itrader/strategy_handler/base.py`):
> `@functools.cache def _declared_hints(cls)` replaced a hot per-call re-walk with a once-per-key
> resolve, locked by a dedicated equivalence test (see test analog below). This is the exact
> shape to copy for Option A. Keep the `_offset_alias` **body byte-unchanged** — only wrap.

The feed already calls `_offset_alias` at `:146` (`__init__`), `:252` (`precompute`), and
`:395` (`window`) — memoizing benefits all three.

---

### `tests/unit/price/test_bar_feed.py` (test, equivalence-assert) — **4-space**

**Analog (primary template):** `tests/unit/portfolio/test_realised_pnl_accumulator.py` (Phase 3
D-03) and `tests/unit/strategy/test_type_hints_equivalence.py` (Phase 4 D-05/D-07) — both are
the established **"audit-the-invariant + dedicated equivalence drift-lock, no hot-path runtime
guard"** pattern that D-08 reuses verbatim.

**Phase 3 / Phase 4 drift-lock docstring shape to copy** (the project house style for these
tests — decision-tag anchored, names the oracle, explicitly states "no hot-path runtime guard
added because re-paying the cost is what the phase removes"):
```python
"""Equivalence drift-lock for the PERF-04 memoized type-hint resolution (D-05/D-07).
...
This test is the dedicated unit-level drift lock (D-07): the "oracle" here is the
UN-cached ``get_type_hints(cls)`` direct call. It asserts (1) ... equals ... with the SAME
keys AND order ...; (2) two calls return the SAME object (``is``) so memoization actually
fires; (3) ...
The byte-exact SMA_MACD oracle + the determinism double-run are the run-path drift locks;
... This file locks the resolution itself. No hot-path runtime guard ... is added (D-05) —
re-paying that ... cost is exactly what the phase removes.
"""
```
For Phase 6, the "oracle" is `frame.iloc[start:pos].copy()` (the old data copy); the three
D-08 assertions map to (a) content-equality, (b) read-only-raises, (c) contract stays green.

**Byte-identity assert helper to reuse** — the existing contract suite in the SAME file
already uses `pd.testing.assert_frame_equal` as the byte-identity backstop (`:167`, `:183`):
```python
    pd.testing.assert_frame_equal(window, daily_base_frame.iloc[2:5])
```
```python
        pd.testing.assert_frame_equal(window, expected, check_freq=False)
```
> Reuse `assert_frame_equal` for D-08 assertion (a) (don't hand-roll a field comparison —
> RESEARCH "Don't Hand-Roll"). Note the existing `check_freq=False` idiom on resampled frames.

**Existing fixtures to reuse** (`:78-90`, `daily_store` / `daily_feed`, plus a `daily_base_frame`
fixture used at `:167`) and the `ts()` tz-aware timestamp helper (`:49-51`). The new drift test
co-locates here so the contract suite (assertion c) and the new (a)/(b) assertions run as one
unit (RESEARCH Open Question 1 — treat D-08's literal `tests/unit/price_handler/feed/` path as
directional; co-locate in `tests/unit/price/` or a sibling `test_bar_feed_window_view.py`).

**LANDMINE for assertion (b)** (RESEARCH Pitfall 1 — the load-bearing exception map under
`filterwarnings=["error"]`): assert a **direct numpy write**, NOT a pandas chained assignment.
```python
    # (b) the REAL read-only proof — direct numpy buffer write raises ValueError:
    with pytest.raises(ValueError, match="read-only"):
        view.to_numpy(copy=False)[0, 0] = 999.0
    # do NOT assert `view.iloc[0,0] = x` raises — that fires SettingWithCopyWarning
    # (pandas copy-guard) BEFORE the read-only buffer is touched: false confidence.
```
| Mutation form | Raises (NOT the proof unless noted) |
|---------------|-------------------------------------|
| `view.iloc[0, 0] = x` | `SettingWithCopyWarning` (pandas guard — NOT read-only proof) |
| `view["close"].iloc[0] = x` | `FutureWarning` (chained-assignment deprecation) |
| `view.to_numpy(copy=False)[0, 0] = x` | **`ValueError: assignment destination is read-only`** ✅ |
| `view._mgr.blocks[0].values[0, 0] = x` | **`ValueError: assignment destination is read-only`** ✅ |

Also assert no leak: re-fetch the same window and `np.array_equal(again.to_numpy(), before)`.

---

### `perf/runners/run_w2_sweep.py` (perf-runner, batch+transform) — **4-space**

**Analog:** `perf/runners/run_w1_benchmark.py` — the sibling runner whose `--check` /
`--baseline-out` / `--json` plumbing is the exact pattern to mirror (D-05). Mechanizes the
gate-(b) ≥10%-at-50-symbols verdict.

**`main()` arg plumbing to copy** (`run_w1_benchmark.py:224-249`):
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="W1 realistic benchmark")
    parser.add_argument("--json", action="store_true",
                        help="emit the result dict as JSON (machine-readable)")
    parser.add_argument("--check", action="store_true",
                        help="compare vs W1-BASELINE.json; soft regression guard (gate b)")
    parser.add_argument("--baseline-out", metavar="PATH",
                        help="freeze: write the run as the committed baseline JSON")
    args = parser.parse_args()
    if args.baseline_out and args.check:
        print("PERF WARNING: --baseline-out and --check together compare a run "
              "against the baseline it just wrote (delta ~0%) ...")
    result = run_w1()
    if args.json:
        print(json.dumps(_to_baseline_schema(result), indent=2))
    if args.baseline_out:
        _write_baseline(result, args.baseline_out)
    if args.check:
        sys.exit(_check_regression(result, "perf/results/W1-BASELINE.json"))
```
> Note `run_w2_sweep.py` today already has `--json` (`:151-158`) and the `points` list — extend
> that `main()`, don't rewrite it.

**Baseline-schema builder to copy** (`run_w1_benchmark.py:150-186` — `_to_baseline_schema` /
`_write_baseline`). W2 keys on the **50-symbol point**; RESEARCH Code Examples gives the W2
schema shape:
```python
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
```

**Regression-guard to copy AND INVERT the sense** (`run_w1_benchmark.py:189-221`
`_check_regression`). W1's guard FAILS on a slowdown beyond a band; the W2 gate REQUIRES a win
(≥10% improvement at 50 symbols):
```python
def _check_w2(points, baseline_path, min_improvement_pct=10.0) -> int:
    base = json.load(open(baseline_path))
    base50 = base["metric"]["wall_clock_s_at_50"]
    now50  = next(p for p in points if p["n_symbols"] == 50)["wall_clock_s"]
    impr = (base50 - now50) / base50 * 100.0
    print(f"W2@50 {now50:.2f}s  improvement {impr:+.1f}%  (baseline {base50:.2f}s)")
    return 0 if impr >= min_improvement_pct else 1
```
> **Carry over W1's WR-02 zero/malformed-baseline soft guard** (`run_w1_benchmark.py:208-211`):
> non-positive `base50` → `return 1` with a message, never a `ZeroDivisionError` traceback.
> **Thermal-drift sequencing (memory `v15-perf-gateb-thermal-drift` + RESEARCH D-05 nuance):**
> capture the before-baseline (`--baseline-out W2-BASELINE-pre.json`) on the SAME machine/session
> as the after `--check`; commit the AFTER run as the standing `W2-BASELINE.json` (seeds Phase 5).

---

### `Makefile` (config, task target) — tab (Makefile recipes use tabs by format)

**Analog:** the `perf-w1` / `perf-w2` / `perf-baseline` targets (`:99-112`). Add a `--check` to
`perf-w2` and a `perf-w2-baseline` freeze target mirroring `perf-baseline`:
```makefile
perf-w1:
	@echo "⏱️  W1 benchmark + regression guard (vs frozen baseline)..."
	poetry run python -m perf.runners.run_w1_benchmark --check

perf-w2:
	@echo "📈 W2 scaling sweep {1,10,50} symbols..."
	poetry run python -m perf.runners.run_w2_sweep

perf-baseline:
	@echo "🧊 Freezing W1 baseline → perf/results/W1-BASELINE.json..."
	poetry run python -m perf.runners.run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json
```
> Add the new target name to the `.PHONY` line (`Makefile:6`). The `include .env` /
> `.EXPORT_ALL_VARIABLES` idiom and worktree `.env`-abort caveat (memory `worktree-make-test-env-abort`)
> apply — run perf in the main checkout, or `poetry run python -m perf.runners.run_w2_sweep` directly in the worktree.

---

### `perf/results/W2-BASELINE.json` (data artifact, CREATE)

**Analog:** `perf/results/W1-BASELINE.json` (the committed-schema artifact). Mirror its
`schema_version` / `frozen_at` / `metric` envelope (see `_to_w2_baseline_schema` above). Commit
the AFTER-run 50-symbol number as the standing reference (D-05; seeds Phase 5).

---

## Shared Patterns

### Decision-tag-anchored drift-lock docstring (test + source)
**Source:** `tests/unit/portfolio/test_realised_pnl_accumulator.py:1-20`,
`tests/unit/strategy/test_type_hints_equivalence.py:1-19`, `bar_feed.py` `current_bars` docstring `:335-349`.
**Apply to:** the new D-08 test AND the `window()`/build-site changes.
Open with a triple-quoted docstring citing the decision tags (D-01/D-06/D-07/D-08/D-09), name
the oracle (the old `.copy()`), and state explicitly that the run-path drift locks are the
byte-exact SMA_MACD oracle + determinism double-run, while this unit test locks the slice
itself — and that **no hot-path runtime guard is added** (re-paying the cost is what the phase
removes). This is the project's load-bearing-comment convention (CLAUDE.md).

### `pd.testing.assert_frame_equal` byte-identity backstop
**Source:** `tests/unit/price/test_bar_feed.py:167,183`.
**Apply to:** D-08 assertion (a) content-equality. Don't hand-roll a field-by-field compare.

### `--check`/`--baseline-out`/`--json` perf-runner CLI
**Source:** `perf/runners/run_w1_benchmark.py:224-249` (+ `_to_baseline_schema`/`_write_baseline`/`_check_regression`).
**Apply to:** `run_w2_sweep.py` (invert the guard sense: REQUIRE a win); carry the WR-02
zero-baseline soft guard.

### numpy read-only enforcement at build (NOT a per-tick guard)
**Source:** RESEARCH Pattern 1 (`frame.to_numpy(copy=False).flags.writeable = False`),
verified against pandas 2.3.3 / numpy 2.2.6.
**Apply to:** the two `self._frames[...] =` write sites in `bar_feed.py` (D-09). One mechanism
covers D-02 view-safety (views inherit the flag) AND master immutability.

---

## No Analog Found

None. Every file has an exact or in-file analog. The phase is deliberately scoped to one
source method + its build sites, a co-located test mirroring two prior drift-locks, and a
sibling perf runner.

---

## Metadata

**Analog search scope:** `itrader/price_handler/feed/`, `tests/unit/price/`,
`tests/unit/portfolio/`, `tests/unit/strategy/`, `perf/runners/`, `perf/results/`, `Makefile`.
**Files scanned:** `bar_feed.py` (target), `test_bar_feed.py` (in-file contract analog),
`test_realised_pnl_accumulator.py` (Phase 3 D-03), `test_type_hints_equivalence.py` (Phase 4
D-05/D-07), `run_w1_benchmark.py` (perf CLI analog), `run_w2_sweep.py` (target),
`W1-BASELINE.json` (artifact schema), `Makefile` perf block.
**Pattern extraction date:** 2026-06-24
</content>
</invoke>
