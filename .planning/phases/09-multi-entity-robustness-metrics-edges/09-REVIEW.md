---
phase: 09-multi-entity-robustness-metrics-edges
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - tests/e2e/conftest.py
  - tests/e2e/robust/_assert_finite.py
  - tests/e2e/robust/test_determinism.py
  - tests/e2e/robust/test_metrics_finite.py
  - tests/e2e/multi/fanout_portfolios/scenario.py
  - tests/e2e/multi/fanout_portfolios/test_scenario.py
  - tests/e2e/multi/two_tickers/scenario.py
  - tests/e2e/multi/two_tickers/test_scenario.py
  - tests/e2e/multi/two_strategies/scenario.py
  - tests/e2e/multi/two_strategies/test_scenario.py
  - tests/e2e/multi/contended_cash/scenario.py
  - tests/e2e/multi/contended_cash/test_scenario.py
  - tests/e2e/robust/sparse_bar/scenario.py
  - tests/e2e/robust/sparse_bar/test_scenario.py
  - tests/e2e/robust/union_window/scenario.py
  - tests/e2e/robust/union_window/test_scenario.py
  - tests/e2e/robust/no_trade/scenario.py
  - tests/e2e/robust/no_trade/test_scenario.py
  - tests/e2e/robust/flat/scenario.py
  - tests/e2e/robust/flat/test_scenario.py
  - tests/e2e/robust/losing/scenario.py
  - tests/e2e/robust/losing/test_scenario.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 09: Code Review Report

**Reviewed:** 2026-06-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Reviewed the Phase 9 E2E golden-master deliverables: the shared `conftest.py` harness
(three Phase-9 additions — the commission-merge `pair` key, the `spec.data`
ticker-registration seam, and the per-portfolio `portfolios.csv` snapshot serializer),
two cross-cutting in-process tests (`test_determinism.py`, `test_metrics_finite.py`),
the `_assert_finite.py` guard, and the nine scenario leaves (four `multi/`, five
`robust/`).

No BLOCKER defects were found: the harness changes are additive and correctly scoped
(the `_supported_symbols` union is a per-instance superset mutation that cannot leak
across runs because each `TradingSystem()` builds a fresh exchange; the `pair` merge
key is backward-compatible because single-ticker leaves keep a unique key). The
goldens cross-check against the hand-derivations.

However, several WARNINGs concern the harness's ability to **silently mask wrong
goldens** — the exact threat this phase was told to guard. The most material:
(1) the no-tolerance summary diff accepts a JSON `Infinity` `profit_factor` with no
gate, so an all-win leaf can freeze and lock `inf` while the project's own
ROBUST-03 contract treats `inf` as a degenerate-metrics smell; (2) the determinism
test silently does NOT compare the per-portfolio / orders / cash_ops frames between
the two runs, so non-determinism in exactly the new MULTI-04 / fanout vehicles is
not caught by ROBUST-04; (3) a documented-vs-frozen slippage attribution mismatch
in `union_window` that a future re-verifier could rubber-stamp.

## Warnings

### WR-01: Determinism test omits the three new Phase-9 frames (orders / cash_ops / portfolios)

**File:** `tests/e2e/robust/test_determinism.py:67-69`
**Issue:** `_assemble` returns a 6-tuple `(trades, equity, summary, orders, cash_ops, portfolios_frame)`, but `test_double_run_identical` asserts identity on only `a[0]`/`a[1]`/`a[2]` (trades, equity, summary). The three frames that are the WHOLE POINT of Phase 9 — `portfolios_frame` (MULTI-03 cash isolation), `orders` (MULTI-04 REJECTED loser), `cash_ops` (MULTI-04 no-orphan ledger) — are computed by `once()` and then discarded. ROBUST-04 is advertised as "the two raw outputs ... asserted IDENTICAL," but the per-portfolio snapshot and the contended-cash order/ledger trail are the parts most exposed to non-determinism (registration-order winner/loser, dict iteration over portfolios). A regression that made the MULTI-04 winner/loser split flaky, or the per-portfolio snapshot order unstable, would pass this test green.
**Fix:** Extend the unpack and assert on all six artifacts:
```python
def once():
    spec = _load_spec(scenario_path)
    system, portfolio, *rest = _build_and_run(spec)
    return _assemble(spec, system, portfolio, *rest)

a = once(); b = once()
pdt.assert_frame_equal(a[0], b[0])   # trades
pdt.assert_frame_equal(a[1], b[1])   # equity
assert a[2] == b[2]                  # summary
pdt.assert_frame_equal(a[3], b[3])   # orders
pdt.assert_frame_equal(a[4], b[4])   # cash_ops
pdt.assert_frame_equal(a[5], b[5])   # portfolios
```

### WR-02: No-tolerance summary diff silently locks `profit_factor: Infinity` with no smell gate

**File:** `tests/e2e/conftest.py:524-542` (`_diff_summary`); affected goldens `tests/e2e/multi/two_tickers/golden/summary.json:8`, `tests/e2e/multi/two_strategies/golden/summary.json:8`, `tests/e2e/multi/fanout_portfolios/golden/summary.json:8`, `tests/e2e/multi/contended_cash/golden/summary.json:8`
**Issue:** Four committed `summary.json` goldens freeze `"profit_factor": Infinity` (all-win frames hit the `metrics.py:96-97` all-win branch). `_diff_summary` compares the metrics block with `==`; `inf == inf` is `True`, so the harness happily diffs and locks `inf`. The project's own ROBUST-03 design (`_assert_finite.py:8-9`) explicitly calls `inf` a degenerate-metrics smell to be avoided by "authoring naturally-finite PnL." The harness therefore enforces finiteness on exactly the three leaves that opted in (`test_metrics_finite.py`) and silently accepts `inf` everywhere else — a leaf author who unintentionally produces an all-win frame gets a green, `inf`-locked golden with no warning. This is precisely the "mask a wrong golden" risk this phase was scoped to surface. Note `json.dump` emits the non-standard token `Infinity`, which is also not portable to strict JSON consumers.
**Fix:** Either (a) extend the finite guard to every leaf that freezes a `metrics` block (run `assert_metrics_finite` over `summary["metrics"]` inside `_diff_summary` / at freeze time, not only in the opt-in `test_metrics_finite.py`), making `inf` a hard authoring failure framework-wide; or (b) if `inf` is genuinely acceptable for clean all-win multi-entity leaves, document that carve-out explicitly in the VERIFY notes of those four leaves so a future re-freezer knows `inf` is intended and not a guard that leaked off.

### WR-03: `union_window` slippage attribution is frozen but undocumented — re-verifier can rubber-stamp a wrong number

**File:** `tests/e2e/robust/union_window/golden/trades.csv:2-3`; doc `tests/e2e/robust/union_window/scenario.py:90-99`
**Issue:** The frozen BTC row has `slippage_entry=33502.87, slippage_exit=32729.12` — i.e. the slippage columns equal the raw fill prices, because `attach_slippage` reads ONE close series (`spec.ticker = AAVEUSD`, conftest.py:391) and the BTC fill timestamps (2021-07-11 / 07-14) fall BEFORE AAVE's first bar (2021-07-15), so `decision_close` returns `0.0` via the `position <= 0` guard (summary.py:72-73) and slippage = fill − 0. The AAVE row's slippage is measured against the AAVE series (271.03 − 270.75 = 0.28, matching). This is the documented single-close-series harness behavior, BUT the union_window VERIFY note never derives or even mentions the slippage columns — unlike `two_tickers`/`two_strategies`, which spell out the cross-ticker single-series attribution. A future `--freeze` re-verifier checking this leaf has no hand-derivation to confirm the slippage column against, so a regressed/garbage slippage value could be frozen and locked without anyone noticing. A no-tolerance lock without a hand-derivation is a regression lock with a blind spot.
**Fix:** Add a slippage-attribution paragraph to the union_window VERIFY note (mirroring two_tickers): BTC fills precede the AAVE close index → `decision_close` returns 0.0 → `slippage = fill_price`; AAVE entry 271.03 − decision-close 270.75 = 0.28, exit 254.06 − 256.32 = −2.26. Then the frozen `slippage_entry`/`slippage_exit` digits are hand-checkable rather than machine-trusted.

### WR-04: `_make_on_tick` resolves operator actions against `portfolio_ids[0]` only — wrong for multi-portfolio specs

**File:** `tests/e2e/conftest.py:212-274` (`_make_on_tick`) and `:363` (call site)
**Issue:** `_build_and_run` calls `_make_on_tick(spec, portfolio_ids[0])`, hard-binding every operator MODIFY/CANCEL action to the FIRST portfolio. Phase 9 introduces the first multi-portfolio specs (`fanout_portfolios` has `pf_a`/`pf_b`). None of the nine Phase-9 leaves carries `actions`, so this is latent today, but the harness is the shared seam for phases 6–9: a future multi-portfolio operator scenario would have its `cancel`/`modify` silently target `pf_a` while the "sole PENDING order" predicate (lines 247-254) asserts against `pf_a`'s book only — an action intended for `pf_b` would either spuriously fail the "no PENDING order" assert or amend the wrong portfolio's order. The hard-coded `[0]` is an unflagged single-portfolio assumption sitting under a now-multi-portfolio harness.
**Fix:** Either thread the target portfolio onto `Action` (add a `portfolio: str | None = None` field resolved to the matching `portfolio_id` by name) and pass the full `portfolio_ids` map into `_make_on_tick`, or explicitly assert/document that operator `actions` are only supported with single-portfolio specs (e.g. `assert not spec.actions or len(spec.portfolios) == 1`).

### WR-05: `attach_slippage` membership guard can raise mid-`apply`, aborting the whole run on a single off-grid fill

**File:** `itrader/reporting/summary.py:72-80` (consumed by `tests/e2e/conftest.py:391-392`)
**Issue:** `decision_close` raises `ValueError` when a fill timestamp is `> 0` in `searchsorted` but not actually a member of the close index. In multi-ticker leaves the harness attributes EVERY trade row (all tickers) against the single `spec.ticker` close series. This works for the Phase-9 leaves because the co-loaded tickers share identical date grids (BTC/ETH same dates; SOL/ETH same window; AAVE within BTC's window via the `position <= 0` early-return). But the guard is fragile: any future leaf where a non-`spec.ticker` fill lands on a date present in that ticker's grid but absent from `spec.ticker`'s grid (e.g. differing end dates — explicitly called out as out-of-scope in `union_window/scenario.py:16-18`) would raise here and abort the entire scenario with a `ValueError`, not a clean diff failure. The harness's correctness now depends on an undocumented invariant ("every traded ticker's fill dates ⊆ spec.ticker's date grid") that no assertion enforces at the harness boundary.
**Fix:** Document the invariant at the `_assemble` slippage call site (conftest.py:390-393) — "all traded tickers must share spec.ticker's fill-date grid, else attach_slippage raises" — or make the harness attribute slippage per-ticker against each row's own `pair` close series so the single-series coupling is removed. At minimum add a comment so the next multi-ticker author knows the constraint before authoring a differing-end-date leaf.

## Info

### IN-01: summary.json and portfolios.csv disagree on float precision for the same value

**File:** `tests/e2e/multi/fanout_portfolios/golden/summary.json:3` vs `tests/e2e/multi/fanout_portfolios/golden/portfolios.csv:2`
**Issue:** `pf_a.final_cash` is frozen as `11666.666666666666` in `summary.json` (raw `json.dump` of the float) and as `11666.6666666667` in `portfolios.csv` (10-dp `FLOAT_FORMAT="%.10f"`). Both are internally consistent against their own golden so no test fails, but the same quantity rendered two different ways in two committed artifacts of the same leaf is a latent foot-gun for anyone cross-reading the goldens or hand-verifying.
**Fix:** Acknowledge in the harness docstring that `summary.json` is full-`repr` float while CSV goldens are 10-dp `FLOAT_FORMAT`, so cross-artifact equality is by-value-not-by-string. No code change required.

### IN-02: `_assemble` builds the full per-portfolio snapshot every run, then discards it for single-portfolio leaves

**File:** `tests/e2e/conftest.py:459-482`
**Issue:** `portfolios_frame` is built for every scenario (the loop re-runs `build_trade_log` + `build_summary` per portfolio), but it is only diffed when a leaf commits `portfolios.csv` (the `_diff` exists() gate). For the eight single-portfolio Phase-9 leaves this is wasted work that duplicates the top-level summary already computed at lines 440-450. The comment at 452-458 calls this "oracle-dark," which is correct for the freeze/diff gate, but the always-on rebuild is unnecessary. Not a correctness issue (out-of-scope performance), flagged only because it duplicates the summary code path and could drift from it.
**Fix:** Optional — skip the per-portfolio loop when `len(spec.portfolios) == 1` and reuse the already-built top-level `summary`. Low priority.

### IN-03: `_assert_finite.py` type hint claims `dict[str, float]` but is not enforced

**File:** `tests/e2e/robust/_assert_finite.py:18,25`
**Issue:** `assert_metrics_finite(metrics: dict[str, float])` calls `math.isfinite(v)` on every value. `build_metrics_block` (summary.py:108-115) casts every metric to `float`, so this is safe today. But if a future metric value were a non-float (e.g. `None`, or a `Decimal`), `math.isfinite` raises `TypeError` instead of producing the intended diagnostic. The guard trusts the upstream `float()` cast it does not control.
**Fix:** Optional defensiveness — coerce or skip non-numeric values with a clear message, or assert `isinstance(v, (int, float))` first so a type drift fails with a readable error rather than a raw `TypeError`.

### IN-04: Heavy reliance on decision-tag prose comments that cannot be machine-verified against the harness

**File:** `tests/e2e/conftest.py` (throughout, e.g. `:89-117`, `:296-339`)
**Issue:** The harness carries extensive `D-NN`/`WR-NN`/`Pitfall N`/`PATTERNS A2` decision-tag comments asserting invariants (e.g. "_supported_symbols is STILL left untouched", "strictly ADDITIVE superset union"). These are load-bearing per project convention and are accurate against the current code, but several describe behavior of OTHER modules (`simulated.py:99-100`, `execution_handler` L104-109, `cash_manager.py:393-410`) by line number. Line-number citations drift silently as those files change; a reader trusting the comment could be misled if the cited line moved.
**Fix:** Optional — prefer symbol references over line numbers in cross-module citations (e.g. "SimulatedExchange.update_config" rather than "simulated.py:603-606"), so the anchor survives edits to the cited file.

---

_Reviewed: 2026-06-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
