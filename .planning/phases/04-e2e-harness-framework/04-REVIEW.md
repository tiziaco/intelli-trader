---
phase: 04-e2e-harness-framework
reviewed: 2026-06-09T15:05:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - itrader/reporting/summary.py
  - scripts/run_backtest.py
  - tests/conftest.py
  - tests/e2e/conftest.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/e2e/smoke/single_market_buy/scenario.py
  - tests/e2e/smoke/single_market_buy/test_scenario.py
  - tests/e2e/smoke/single_market_buy/bars.csv
  - tests/e2e/smoke/single_market_buy/golden/trades.csv
  - tests/e2e/smoke/single_market_buy/golden/summary.json
  - pyproject.toml
  - Makefile
  - tests/unit/core/test_enums.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-09T15:05:00Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Phase 04 builds the shared E2E harness: a relocated serialization module
(`itrader/reporting/summary.py`), a `run_scenario` fixture with golden-diff mechanics
(`tests/e2e/conftest.py`), a contrived hand-verified canary scenario, and supporting
config (`pyproject.toml` markers, `Makefile` `test-e2e` target).

I executed the canary test live: it **passes**, drift detection **works** (mutating a
golden cell produces a FAIL), `--collect-only` is **clean** (deferred `TradingSystem`
import), and `mypy` is **clean** on `summary.py`. The metrics functions are well-guarded
against NaN, so the "compare the whole metrics dict with `==`" risk does not materialize
for realistic flat/single-point equity curves.

No BLOCKER-class correctness or security defects were found in the canary path itself. The
findings below are (a) a latent multi-ticker correctness bug in the shared harness that
will silently bake wrong slippage numbers into Phase 6-9 goldens, (b) several
documentation-vs-reality drifts where the code does not do what its load-bearing docstrings
claim (these matter because the docstrings are the VERIFY contract and the freeze
discipline depends on them being accurate), and (c) minor quality items.

## Warnings

### WR-01: `attach_slippage` uses a single ticker's closes for ALL trades — latent multi-ticker correctness bug in the shared harness

**File:** `tests/e2e/conftest.py:183-208` (`_assemble`), consuming `itrader/reporting/summary.py:42-75`

**Issue:** `_assemble` computes the slippage-attribution close series from exactly one
ticker:

```python
closes = system.store.read_bars(spec.ticker)["close"]
trades = attach_slippage(trades, closes)
```

But `attach_slippage` applies that single series to EVERY row in the trades frame, and the
trades frame carries a per-trade `pair` column (`position.to_dict()` →
`'pair': self.ticker`). For the single-ticker canary this is correct. But this conftest is
explicitly sold as "the SINGLE shared infrastructure every scenario phase (6-9)
consume[s]" (module docstring lines 1-7), and a Phase 6-9 author "adds a scenario by
editing ONLY their own leaf folder." The moment a scenario trades two tickers, every trade
on the non-`spec.ticker` ticker gets `slippage_entry`/`slippage_exit` computed against the
WRONG ticker's close series. Those wrong numbers are then frozen into `golden/trades.csv`
via `--freeze` and lock in as a "verified" regression baseline. Because the harness diffs
its own output against its own freeze, the bug is self-consistent and the diff will never
catch it — the only line of defense is the human VERIFY step, which is exactly where a
multi-ticker slippage error is easiest to miss.

**Fix:** Compute slippage per-ticker by grouping the trades frame on `pair` and looking up
each ticker's own close series. For example, replace the `_assemble` slippage block with a
per-ticker dispatch, and have `attach_slippage` accept a `closes_by_ticker` mapping (or
call it once per ticker group):

```python
# _assemble
trades_parts = []
for ticker, grp in trades.groupby("pair"):
    closes = system.store.read_bars(ticker)["close"]
    trades_parts.append(attach_slippage(grp.copy(), closes))
trades = pd.concat(trades_parts).sort_index() if trades_parts else trades
```

(or pass `system.store` into `attach_slippage` and resolve `closes` per row from
`row["pair"]`). At minimum, the harness must assert single-ticker until the multi-ticker
path is implemented, so a Phase 6-9 author cannot silently freeze wrong numbers.

### WR-02: `attach_slippage` `decision_close` is fragile when a fill time is not exactly on a store bar (off-by-one risk)

**File:** `itrader/reporting/summary.py:59-61`

**Issue:**

```python
def decision_close(fill_time: Any) -> float:
    position = index.searchsorted(fill_time, side="left")
    return float(closes.iloc[position - 1]) if position > 0 else float("nan")
```

This assumes `fill_time` lands EXACTLY on a store-index timestamp so that
`searchsorted(..., side="left")` returns the index of the fill bar and `position - 1` is
the decision bar. For the canary the fill dates (`entry_date`) coincide with bar
timestamps, so it works. But if a fill is ever stamped at a time that is NOT an exact index
member (e.g. an intrabar stop/limit fill timestamped between bars, or any resampled-feed
scenario), `side="left"` returns the insertion point and `position - 1` silently selects
the wrong "decision bar," producing a wrong-but-plausible slippage number with no error.
This is the same class of silent-wrong-number risk the project's golden discipline exists
to prevent. The relocation docstring asserts the body is "character-identical" to the
oracle original, so this is inherited debt, but it is now reused by the harness across
future scenario shapes the oracle never exercised.

**Fix:** Make the bar-membership assumption explicit and loud. Either assert membership, or
distinguish "fill bar is an exact index member" from "fill time falls between bars":

```python
def decision_close(fill_time: Any) -> float:
    pos = index.searchsorted(fill_time, side="left")
    if pos >= len(index) or index[pos] != fill_time:
        # fill time is not an exact bar — the decision-bar mapping is undefined here
        raise ValueError(f"fill_time {fill_time!r} is not an exact store-bar timestamp")
    return float(closes.iloc[pos - 1]) if pos > 0 else float("nan")
```

If between-bar fills are a legitimate future case, the contract for what "decision bar"
means must be written down rather than left to `searchsorted` side-effects.

### WR-03: Summary diff is NOT round-tripped through JSON while trade/equity diffs ARE round-tripped through CSV — asymmetric precision gate contradicts the "no tolerance" contract

**File:** `tests/e2e/conftest.py:248-263` (`_diff_summary`) vs `tests/e2e/conftest.py:287-303` (`_roundtrip`) and `306-335` (`_diff`)

**Issue:** The harness goes to great lengths to normalize trade/equity frames before
comparison: `_roundtrip` serializes the fresh frame through `to_csv(float_format="%.10f")`
→ `read_csv` so "the diff compares the frozen bytes — not engine-internal dtype/precision
artifacts" (docstring lines 287-298). But `_diff_summary` compares the **in-memory**
fresh summary dict (full-precision Python floats straight from `float(Decimal)`) against
the JSON-loaded golden, with no equivalent normalization. Two separate inconsistencies
follow:

1. **Different precision gates for the same underlying number.** A trade-log numeric is
   compared at 10 decimal places (`%.10f`), so a drift below ~1e-10 is rounded away and
   *invisible*. The same value in `summary.json` is compared at full float `repr`, so the
   identical drift IS caught. This directly contradicts the repeated "NO float tolerance"
   / "zero float tolerance" claims (conftest lines 79-80, 216-217): the trade path has an
   implicit 1e-10 tolerance band; the summary path has none.
2. **Reliance on `repr(float) == json.dumps(float)`.** The summary diff only passes because
   Python's shortest-float-repr is identical between `json.dump` (golden write) and the
   in-memory float — which I verified holds for the canary. But it is an undocumented
   coincidence, not a normalized round-trip like the frames get.

**Fix:** Round-trip the fresh summary through the SAME `json.dump`/`json.load` path the
golden was written with before comparing, mirroring `_roundtrip` for frames:

```python
def _roundtrip_summary(summary):
    return json.loads(json.dumps(summary, sort_keys=True))
# in _diff:
fresh_summary = _roundtrip_summary(summary)
_diff_summary(fresh_summary, gold_summary)
```

Separately, document that the trade/equity gate is "exact to 10 dp by FLOAT_FORMAT pin,"
not "zero tolerance," so the contract text matches the actual mechanic.

### WR-04: Whole-`metrics`-dict `==` comparison will spuriously FAIL if any metric is ever NaN

**File:** `tests/e2e/conftest.py:251-255`

**Issue:**

```python
if "metrics" in golden_summary:
    assert fresh_summary.get("metrics") == golden_summary["metrics"], (...)
```

Comparing two dicts with `==` returns `False` whenever any value is `NaN`, because
`NaN != NaN`. So if a future scenario produces a `NaN` metric (e.g. a degenerate equity
curve a guard misses, or a new metric added without a guard), the harness will FAIL even
when fresh and golden are byte-identical — and the failure message will look like a real
regression. I verified the current `metrics.py` functions are well-guarded (flat/single
-point equity all return `0.0`, not NaN), so this is latent rather than active, but the
harness is the shared infra for 12+ future scenarios and a new metric is a likely
addition. The `Infinity` token already present in the canary golden
(`golden/summary.json:9`, `profit_factor: Infinity`) shows non-finite values DO flow
through this path; `inf == inf` is `True` so it survives today, but `NaN` would not.

**Fix:** Compare metrics key-by-key with explicit NaN handling instead of dict `==`:

```python
import math
for key, gold in golden_summary.get("metrics", {}).items():
    fresh = fresh_summary.get("metrics", {}).get(key)
    if isinstance(gold, float) and math.isnan(gold):
        assert isinstance(fresh, float) and math.isnan(fresh), f"metrics[{key}] NaN drift"
    else:
        assert fresh == gold, f"metrics[{key}] drift: fresh={fresh} golden={gold}"
```

## Info

### IN-01: FLOAT_FORMAT docstring overstates its coverage — money columns bypass `%.10f` entirely

**File:** `itrader/reporting/summary.py:34-35`, `tests/e2e/conftest.py:266-284` (`_freeze`)

**Issue:** `FLOAT_FORMAT = "%.10f"` is documented as the "pinned repr for cross-platform
stability (T-04-01)" and the conftest leans on it as the normalization mechanic. But
`pandas.to_csv(float_format=...)` only applies to genuine `float` columns. The money
columns (`avg_bought`, `total_bought`, `realised_pnl`, `avg_sold`, `net_quantity`, ...) are
`Decimal`-as-object, so they bypass `FLOAT_FORMAT` and serialize at full Decimal precision
— visible directly in `golden/trades.csv` as `120.0000000000000000000000000` (25 dp) next
to `slippage_entry,6.0000000000` (10 dp). Only the appended D-17 slippage columns are real
floats and actually get the 10dp pin. The result is correct and stable (Decimal repr has no
float artifacts), and the diff is symmetric because both sides read back through
`read_csv` (which casts both to float64), so this is not a bug — but the docstring implies
FLOAT_FORMAT governs the trade-log numbers, which it does not.

**Fix:** Amend the FLOAT_FORMAT docstring to state it pins ONLY the genuine-float columns
(the D-17 slippage columns + equity floats); the Decimal money columns serialize at full
precision and are normalized to float64 only on `read_csv` at diff time.

### IN-02: VERIFY note claims "zero-slippage golden run" but freezes non-zero slippage columns it never hand-derives

**File:** `tests/e2e/smoke/single_market_buy/scenario.py:37-82`, `golden/trades.csv:2`

**Issue:** The VERIFY note says "exchange = None (zero-fee / no-slippage ...)" and ends with
"the LOAD-BEARING hand-checked facts are the fill prices, the quantity, and the realised
PnL above." But the frozen `golden/trades.csv` carries `slippage_entry=6.0` and
`slippage_exit=6.0`, and the VERIFY derivation never states what those columns SHOULD be.
The numbers are in fact correct (next-bar-open gap: fill 120 − decision close 114 = 6, and
140 − 134 = 6, per the `attach_slippage` docstring), but the hand-verification — the thing
the freeze discipline says proves correctness "once, before the freeze" — does not actually
cover two of the frozen columns. A reviewer of the VERIFY note cannot confirm the slippage
cells without re-deriving them independently.

**Fix:** Add one line to the VERIFY note deriving the expected slippage columns:
`slippage_entry = entry_fill(120) − decision_close(bar1 close 114) = 6`;
`slippage_exit = exit_fill(140) − decision_close(bar3 close 134) = 6`.

### IN-03: Engine emits verbose INFO logs to stdout during `run_scenario`, despite `print_summary=False`

**File:** `tests/e2e/conftest.py:175`

**Issue:** `system.run(print_summary=False)` suppresses the summary printout, but the engine
still emits per-event INFO logs (position created, transaction recorded, position closed,
"BACKTEST COMPLETED", etc.) to stdout/stderr on every scenario run — confirmed in the live
run output. With 12+ future e2e scenarios in the default `make test` suite (D-15: e2e is
NOT slow, stays in the default run), this is meaningful noise that can also slow collection
and bury real failures. The harness owns the build/run contract and is the right place to
quiet the run.

**Fix:** Have `run_scenario` raise the log level for the duration of the run (e.g. a
`caplog`/`logging`-level context manager set to WARNING around `_build_and_run`), or set the
engine log level via config in the harness. Tests should run quiet by default.

### IN-04: `pyproject.toml` pins `pytest = "^9.0.3"` but `CLAUDE.md`/stack notes say `pytest ^8.4.2`

**File:** `pyproject.toml:32`

**Issue:** The project tech-stack documentation states "pytest ^8.4.2," and
`minversion = "8.0"`, but the actual dev dependency is `pytest = "^9.0.3"` (and the live run
reports pytest-9.0.3). This is documentation drift, not a code defect, but pytest 9 dropped
some long-deprecated APIs; anything relying on the documented 8.x baseline should be
re-checked. Not in this phase's changed surface beyond the pin itself.

**Fix:** Reconcile the documented pytest version with the actual `^9.0.3` pin (update the
stack docs), and confirm nothing in the suite relied on pytest-8-only behavior.

### IN-05: `_diff_summary` silently ignores EXTRA keys present in fresh but absent in golden — schema additions go undetected

**File:** `tests/e2e/conftest.py:256-263`

**Issue:** `_diff_summary` iterates over `golden_summary.items()` only. If the engine starts
emitting a NEW summary field (a schema addition or an accidental volatile field like a
wall-clock timestamp leaking into the summary), the golden has no such key, the loop never
checks it, and the diff passes. The D-12 contract explicitly excludes volatile fields from
serialization to keep the oracle deterministic; a regression that re-introduces one would
slip past this harness. This is partly by-design ("presence = assertion," D-05) but the
asymmetry is worth a guard given the determinism stakes.

**Fix:** When not freezing, assert the fresh summary key set is a subset of (or equal to)
the golden key set, so a newly-appearing field forces a deliberate re-freeze + re-verify:

```python
extra = set(fresh_summary) - set(golden_summary)
assert not extra, f"fresh summary has unfrozen keys {extra} — re-verify and re-freeze"
```

---

_Reviewed: 2026-06-09T15:05:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
