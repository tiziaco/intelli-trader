---
phase: 04-e2e-harness-framework
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - itrader/reporting/summary.py
  - scripts/run_backtest.py
  - tests/conftest.py
  - tests/e2e/__init__.py
  - tests/e2e/conftest.py
  - tests/e2e/smoke/__init__.py
  - tests/e2e/smoke/single_market_buy/__init__.py
  - tests/e2e/smoke/single_market_buy/scenario.py
  - tests/e2e/smoke/single_market_buy/test_scenario.py
  - tests/e2e/strategies/__init__.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/unit/core/test_enums.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-09
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the Phase 4 E2E harness: the shared `tests/e2e/conftest.py` `run_scenario`
build→run→read→assemble→diff fixture, the relocated `itrader.reporting.summary`
serialization path, the oracle generator `scripts/run_backtest.py`, the canary
`single_market_buy` scenario + strategy, the root test conftest marker plumbing, and
the `FillStatus` enum characterization test.

The harness wiring is coherent and the canary golden numbers reconcile with the VERIFY
hand-derivation (entry @120, exit @140, realised_pnl 1666.66…, final_equity 11666.66…,
slippage 6.0 each leg). No security issues exist in this test-infrastructure surface, and
no money-as-float defect was found (`add_portfolio` enters Decimal via `to_money`; the
single Decimal→float boundary in `build_summary` is preserved).

The defects are correctness-of-claim and robustness gaps that will bite the Phase 6-9
scenario authors who clone this template: a documented "unique module name" invariant that
does not hold and references a `sys.modules` mechanism the code never engages; a
`decision_close` that silently emits `NaN` and breaks the exact-diff for any future fill on
the first bar; a `searchsorted` decision-bar lookup that is only correct when fill timestamps
land exactly on store-index bars; and an asymmetric summary diff that cannot catch spurious
extra keys.

## Warnings

### WR-01: "Unique module name per leaf" invariant is false for same-named leaves and references an unused `sys.modules` mechanism

**File:** `tests/e2e/conftest.py:104-126`
**Issue:** `_load_spec` derives the in-process module name from `scenario_path.parent.name`
only (`f"e2e_scenario_{scenario_path.parent.name}"`). Two leaves with the same folder name in
different parents — e.g. `e2e/smoke/single_market_buy/` and a future
`e2e/regression/single_market_buy/` — produce the IDENTICAL module name
`e2e_scenario_single_market_buy`. The docstring and inline comments (lines 108-109, 114-115)
claim this keeps "two leaves' scenario.py from colliding in sys.modules (Pitfall 4)", but the
code never assigns `sys.modules[module_name] = module`, so the stated collision-prevention
mechanism is inoperative and the name is effectively cosmetic. The uniqueness invariant the
comment advertises is also not satisfied. This is a documented-protection-vs-reality mismatch
that will mislead the Phase 6-9 authors who treat this file as ground truth, and a latent
collision if `sys.modules` registration is ever added (e.g. to support dataclass pickling or
intra-scenario relative imports).
**Fix:** Derive a name that is actually unique across the full leaf path, e.g.
```python
rel = scenario_path.parent.relative_to(pathlib.Path(__file__).parent)
module_name = "e2e_scenario_" + "_".join(rel.parts)
```
and either remove the `sys.modules` claim from the docstring/comments or register the module
deliberately (`sys.modules[module_name] = module`) so the stated behavior matches the code.

### WR-02: `attach_slippage.decision_close` emits `NaN` for a fill on the first store bar, which breaks the exact no-tolerance diff

**File:** `itrader/reporting/summary.py:59-61`
**Issue:** `decision_close` returns `float("nan")` when `position == 0` (a fill whose timestamp
is at or before the first store bar). `slippage_entry`/`slippage_exit` then become `NaN`,
serialized into `trades.csv`. Because the harness diffs with `check_exact=True` and NO
tolerance, and `NaN != NaN`, any future scenario whose entry or exit fills on the first store
bar produces a column that cannot be compared meaningfully. The canary avoids this (fills on
bars 2/4), so it is latent, but this function is the SHARED Phase 6-9 path explicitly
advertised as a copy-template, and a first-bar fill is a realistic scenario shape.
**Fix:** Decide the contract explicitly. Either guard against first-bar fills at the scenario
level, or make the column deterministic when no decision bar exists, e.g. return `0.0`
(meaning "no overnight gap measurable") rather than `NaN`:
```python
def decision_close(fill_time: Any) -> float:
    position = index.searchsorted(fill_time, side="left")
    if position <= 0:
        return 0.0  # no decision bar exists — diff-stable, document the semantics
    return float(closes.iloc[position - 1])
```
and document the chosen semantics in the docstring.

### WR-03: `decision_close` is only correct when fill timestamps coincide exactly with store-index bars

**File:** `itrader/reporting/summary.py:57-61, 71-74`
**Issue:** `decision_close` computes the decision bar as
`closes.iloc[index.searchsorted(fill_time, side="left") - 1]`, where `index` is the
base-timeframe store index (`system.store.read_bars(ticker)["close"].index`). This assumes
`fill_time` (the trade's `entry_date`/`exit_date`) lands EXACTLY on a store-index timestamp.
For the canary (1d base = 1d run) this holds. But the harness threads `spec.timeframe` while
`closes` is always the raw base store series; for any scenario where the run/fill timeframe
differs from the base store grid (resampled bars), `searchsorted(side="left")` returns an
insertion point that does not correspond to "the bar immediately before the fill", and
`position - 1` silently attributes slippage to the wrong bar — a silently-wrong number frozen
into a golden that "proves stability, not correctness". The `Any` duck-typing hides the
mismatch from mypy.
**Fix:** Either assert the fill timestamp is a member of the index (`assert fill_time in index`)
so a mismatch fails loudly instead of mis-attributing, or pass the run-timeframe (resampled)
close series rather than the raw store close series, and document that `attach_slippage`
requires fill timestamps drawn from the same grid as `closes`.

### WR-04: Summary diff is asymmetric — spurious extra top-level keys in a regressed summary are never caught

**File:** `tests/e2e/conftest.py:248-263`
**Issue:** `_diff_summary` iterates only over the GOLDEN's keys
(`for key, gold_value in golden_summary.items()`). If a regression causes `build_summary` to
emit an EXTRA top-level key, the scalar comparison silently ignores any fresh key absent from
the golden. A renamed/removed key is caught (golden key → `None` in fresh → mismatch), but an
additive drift is not. The harness is sold as a no-tolerance regression lock; this is a gap in
that guarantee.
**Fix:** After the key-by-key golden loop, assert scalar key-set equality:
```python
fresh_scalar = {k for k in fresh_summary if k != "metrics"}
gold_scalar = {k for k in golden_summary if k != "metrics"}
assert fresh_scalar == gold_scalar, (
    f"summary key drift: extra={fresh_scalar - gold_scalar} missing={gold_scalar - fresh_scalar}")
```

## Info

### IN-01: Orphan `tests/e2e/data/` directory with `.gitkeep` is referenced nowhere

**File:** `tests/e2e/data/.gitkeep`
**Issue:** The phase creates `tests/e2e/data/.gitkeep`, but no code under `tests/`, `itrader/`,
or `scripts/` references `tests/e2e/data`. The canary keeps its `bars.csv` inside its own leaf
folder (`scenario.py:144` → `HERE / "bars.csv"`), so the shared data dir is currently dead.
**Fix:** Either wire the shared data dir into the harness contract (and document it in the
`e2e/conftest.py` docstring) or remove it to avoid implying a convention authors should follow.

### IN-02: `--freeze` writes goldens for EVERY collected e2e scenario, contradicting the "one scenario at a time" discipline

**File:** `tests/e2e/conftest.py:88-101, 347-359`
**Issue:** The docstring repeatedly mandates freezing "ONE scenario at a time, after
HAND-VERIFYING it" (Pitfall 5), but `--freeze` is a global pytest flag the `run_scenario`
fixture honors for every collected leaf in the run. Nothing enforces single-scenario scope; a
developer running `pytest tests/e2e --freeze` blind-overwrites all goldens — exactly the "blind
12-scenario --freeze sweep" the docstring warns against.
**Fix:** Document that `--freeze` MUST be combined with a `-k`/path selector, or have the
fixture refuse to freeze when more than one e2e test is selected (e.g. inspect
`request.session.items` count) so the discipline is mechanically enforced, not just documented.

### IN-03: `IndexError` on an empty-portfolio spec instead of a clear harness error

**File:** `tests/e2e/conftest.py:163-180`
**Issue:** `_build_and_run` does `portfolio = ... get_portfolio(portfolio_ids[0])`. A spec with
`portfolios=[]` raises a bare `IndexError` with no context, unlike the other spec-shape
failures which `pytest.fail` with an explanatory message (`_load_spec`).
**Fix:** Guard with a clear assertion before the loop:
`assert spec.portfolios, "scenario spec must declare at least one portfolio"`.

### IN-04: Canary VERIFY note does not derive the frozen `slippage_entry`/`slippage_exit` columns

**File:** `tests/e2e/smoke/single_market_buy/scenario.py:16-84`
**Issue:** The VERIFY block claims a human confirmed `golden/trades.csv` matches the
hand-derivation, but the derivation never mentions the `slippage_entry`/`slippage_exit` columns
(both frozen as `6.0` in the golden). These are load-bearing frozen numbers; the note states the
load-bearing facts are "the fill prices, the quantity, and the realised PnL" and is silent on
the slippage columns it also locks.
**Fix:** Add the one-line derivation: entry slippage = bar2 open(120) − bar1 close(114) = 6.0;
exit slippage = bar4 open(140) − bar3 close(134) = 6.0.

### IN-05: `open()` calls for golden/summary serialization omit explicit `encoding`

**File:** `scripts/run_backtest.py:116`; `tests/e2e/conftest.py:277, 333`
**Issue:** `open(..., "w")` / `open(...)` for `summary.json` rely on the platform default
encoding. The content is currently ASCII (numeric metrics + ASCII keys), so byte-stability is
not affected today, but the harness's whole value is byte-exact golden reproducibility across
platforms; a future non-ASCII ticker/name would diverge silently.
**Fix:** Pass `encoding="utf-8"` to every `open()` that reads or writes a committed golden.

---

_Reviewed: 2026-06-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
