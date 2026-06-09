# Phase 8: M5c — Cross-Validation & Final Oracle - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

The **cross-validation & final oracle** phase — the program-level definition of done.
Prove iTrader's `SMA_MACD` numbers on the golden BTCUSD CSV are trustworthy by
cross-validating against external reference engines, then freeze the **final authoritative
numerical oracle**. This is the single locked requirement **M5-10**. This phase is
*validation*, not refactoring — with two sanctioned exceptions that are explicitly in scope
(below).

**Golden-master position:** Phase 8 is inside M5 and is the **last milestone allowed to
change results** (PROJECT.md two-point re-baseline rule: the post-M5 re-baseline point is
HERE). Every result change follows the Phase 6/7 hybrid discipline: a named, owner-gated
re-freeze with an expected-diff note. Phase 8 may produce up to two result-changing events
(the golden-path Decimal cleanup, and possibly one divergence-driven iTrader bug fix), each
with its own named re-freeze. The last state is the final frozen oracle.

**Current frozen reference (what we start from):** 134 trades, `final_equity ≈ 46189.877…`,
LONG_ONLY, `FractionOfCash(0.95)`, `allow_increase=False`, fees 0 / slippage 0, next-bar-open
fills, $10k start (Phase 7 re-freezes REFREEZE-M5B-DIRECTION + REFREEZE-M5B-INCREASE).

**In scope (the two sanctioned result-changing exceptions):**
- **Golden-path Decimal cleanup** — close the float-money leaks on the result-bearing path
  (definition-of-done requires "no float money"). See D-08.
- **Divergence-driven iTrader bug fix** — only if cross-validation traces a genuine iTrader
  bug. See D-05.

**Boundary with adjacent work (do NOT pull forward):**
- **`D-live`** owns the `TradingInterface` float-money leaks (live-mode order path) and the
  full live trading surface. Explicitly deferred (D-09).
- **Margin milestone** owns shorts / `LONG_SHORT` / liquidation (carried from Phase 7 D-08/D-09).
- **`D-sql`** owns stats persistence.
- **`D-screener`** owns the time-aware Universe + rebalance loop.

</domain>

<decisions>
## Implementation Decisions

### Engine alignment (M5-10)
- **D-01: Force-match the reference engines to iTrader's exact rules.** Configure
  `backtesting.py` and `backtrader` to iTrader's exact backtest semantics: next-bar-open
  fills, 95%-of-equity sizing (`FractionOfCash(0.95)`), long-only, zero fees / zero slippage,
  $10,000 starting cash, identical SMA/MACD params (short=50, long=100, FAST=6, SLOW=12,
  WIN=3). The SMA_MACD **quirk must be replicated exactly**: the `SMA(50) >= SMA(100)` filter
  gates **both** the entry trigger AND the exit trigger (a long is NOT exited on the MACD
  down-cross when the SMA filter is false). Goal: divergence should be near-zero, so any gap
  is a real finding — not "expected difference." This is the most rigorous alignment, chosen
  deliberately over pragmatic/natural-mode options.

### Reconciliation gate (M5-10)
- **D-02: Trade-level primary + metric-level confirmation.** The pass criterion is, in
  priority order:
  1. **Primary (trade-level):** same trade count and matching entry/exit bar timing across
     engines. Rare `±1-bar` shifts are tolerated ONLY when each is traced to a specific
     indicator-boundary rounding cause (see D-03 caveat) — never a free pass.
  2. **Secondary (metric-level):** the headline metrics agree within the D-04 tolerance band.
  A compensating-errors trade structure must not be able to pass — that's why trade-level is
  primary, not metric-only.
- **D-03: Indicator-library divergence is the expected (and only legitimate) source of
  trade-timing difference.** The three engines compute SMA/MACD with different internal
  libraries (iTrader uses `ta`; the reference engines have their own). Values can differ at
  the 5th–6th decimal near a crossover, which can flip a trade's entry/exit by one bar. This
  bounds how strict trade-for-trade can be; exact-trade-for-trade was explicitly rejected as
  potentially unachievable without indicator reimplementation.
- **D-04: Tiered tolerance.** Default expectation `≤ ~1%` on headline metrics when trade
  timing matches exactly. When a documented, fully-attributed `±1-bar` indicator-boundary
  shift occurs, that run may diverge more — but the excess must be entirely accounted for by
  the shifted trade (volatility of the affected bar), not waved through. Flat-1% (too brittle
  for an explained shift) and flat-5% (loose enough to hide a bug) were both rejected.
  - **Headline metric set** (from the frozen `tests/golden/summary.json`): `final_equity`,
    `trade_count`, `cagr`, `max_drawdown`, `profit_factor`, `sharpe`, `sortino`, `win_rate`.

### Divergence policy (M5-10, golden-master discipline)
- **D-05: Root-cause decides; iTrader is correct unless proven otherwise.** Every divergence
  must be traced to a root cause. Then:
  - Cause = an **iTrader bug** → fix it → **RESULT-CHANGING** final re-freeze with a named
    diff note (Phase 8 is the last sanctioned change point). Each such fix is its own named
    re-freeze.
  - Cause = a **legitimate reference-engine semantic difference** that iTrader handles
    correctly → document it; keep iTrader's numbers.
  Default disposition: iTrader's post-M5b numbers are correct unless the trace proves a real
  defect. "Reference engines as ground truth" was explicitly rejected (they have their own
  quirks; calibrating to them could introduce errors).

### Golden-path Decimal cleanup (definition-of-done: "no float money")
- **D-06: Scope = golden/result-bearing path only.** Fix the float-money leaks that touch the
  frozen oracle: `Portfolio.total_market_value` / `total_equity` / `total_unrealised_pnl` /
  `total_realised_pnl` / `total_pnl` (currently return `float`); the `MetricsManager`
  Decimal→float coercions in `_get_latest_metrics` / `_calculate_max_drawdown` /
  `_calculate_performance_metrics`; and the golden-path validator cash checks
  (`EnhancedOrderValidator` `float(order.price)` / `float(order.quantity)` comparisons) where
  they affect golden output. Source: `.planning/codebase/CONCERNS.md` ("Float Leaks at
  Portfolio Property Boundary"). This is NOT scope creep — ROADMAP Phase 8 success criterion
  #3 requires "no float money," and Phase 8 is the last place to close it.
- **D-07: Sequencing — Decimal cleanup lands FIRST, before cross-validation.** Clean iTrader's
  numbers before comparing, so float-rounding divergence is never misattributed to the
  reference engines.
- **D-08: Decimal cleanup gets its own named re-freeze** — e.g. `REFREEZE-M5C-DECIMAL`, with
  an expected-diff note (one attributable diff per change, per Phase 6/7 discipline). If the
  cleanup turns out to be byte-exact inert (float coercion was purely presentational) no
  re-freeze is needed — but plan for a re-freeze since Decimal precision likely shifts metric
  values. Cross-validation runs against these clean numbers.
- **D-09: `TradingInterface` float leaks are DEFERRED to `D-live`.** `create_market_order` /
  `create_limit_order` `float` signatures and the `price=0.0` literal live in the live-mode
  order path (already out of program scope). Not fixed here.

### Cross-validation harness & artifacts (M5-10)
- **D-10: One-time validation + committed report; the frozen oracle is the permanent gate.**
  Add `backtesting.py` + `backtrader` (and `nautilus_trader`, see D-12) as **dev
  dependencies** (poetry dev group, pinned versions for reproducibility). The comparison runs
  as a **reproducible script** (e.g. `scripts/cross_validate.py`) that produces a **committed
  report artifact** (reconciliation table + per-divergence root-cause explanations) as the
  durable evidence of cross-validation. The reference-engine comparison is NOT wired into
  `make test` / CI — the **frozen iTrader oracle + existing integration test remain the
  permanent regression gate**. (Permanent-CI-gate and throwaway-no-code options both
  rejected.)
- **D-11: Final oracle = the existing golden artifact set, post-cleanup-and-any-fix.**
  `tests/golden/{trades.csv, equity.csv, summary.json}` (+ the M5-C re-freeze note(s)) are the
  final authoritative oracle. The cross-validation report is committed evidence, not the
  oracle itself.

### Nautilus (M5-10 — beyond the locked two-engine requirement)
- **D-12: Nautilus Trader as an OPTIONAL NON-GATING third reference.** Nautilus is the most
  production-grade candidate and the closest architectural mirror to iTrader (event-driven,
  real order/fill lifecycle, realistic matching engine — vs vectorized backtesting.py /
  hybrid backtrader), so it can catch event-semantics bugs the simpler engines structurally
  cannot. It is added to the same harness and report — reconciled, divergences explained —
  but is **NOT a pass/fail gate** for the final freeze. Rationale for non-gating: M5-10 locks
  the *gating* engines at `backtesting.py` + `backtrader`; Nautilus's richer model
  (instruments, venues, account/fill/latency config) makes exact force-matching (D-01) harder
  and riskier, and must not be able to stall the definition-of-done freeze on config wrestling.
  Full-gating and defer-entirely options both rejected.

### Definition-of-done gate (standing — ROADMAP SC#3)
- **D-13: Phase 8 must verify the program-level definition of done holds:** `SMA_MACD` runs
  end-to-end with a non-trivial trade log + equity curve; `mypy --strict` clean; **no float
  money** (closed by D-06); single UUIDv7 scheme; deterministic runs (double-run byte-
  identical); component tests green under pytest strictness + the run-path integration test.

### Claude's Discretion
- Cross-validation report artifact location/format (suggested:
  `tests/golden/CROSS-VALIDATION.md` with the reconciliation table + per-divergence
  root-cause notes). Naming of the M5-C re-freeze note(s).
- Exact reference-engine versions to pin in the poetry dev group.
- How faithfully each reference engine reimplements the SMA/MACD math (whether it must
  replicate `ta`'s exact SMA/MACD computation or can use the engine-native indicator and
  absorb the difference under D-03) — planner/researcher to determine the cleanest path to
  the D-02 trade-level match.
- Whether the harness runs the three engines in one script or one module per engine; how the
  Nautilus instrument/venue/bar-spec config is shaped to approximate D-01.
- Exact float→Decimal retype boundaries within `Portfolio` / `MetricsManager` /
  `EnhancedOrderValidator` (D-06) and how the equity-curve serialization changes
  representation in `summary.json` / `equity.csv`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REQUIREMENTS.md` — **M5-10** (the locked WHAT: cross-validate vs backtesting.py +
  backtrader; metrics reconciled; final numerical reference frozen) + the program
  definition-of-done block (lines ~184-185)
- `.planning/ROADMAP.md` — Phase 8 goal + 3 success criteria (note SC#3 = program
  definition-of-done, including "no float money")
- `.planning/PROJECT.md` — milestone breakdown, the two-point re-baseline rule (post-M5
  re-baseline point is THIS phase), Out-of-Scope (`D-live` etc.)
- `.planning/REFACTOR-BRIEF.md` — program goal, locked decisions (Decimal money, UUIDv7),
  golden-master discipline, §1 definition-of-done

### Architecture findings driving the in-scope cleanup
- `.planning/codebase/CONCERNS.md` — **"Float Leaks at Portfolio Property Boundary"** (the
  D-06 golden-path Decimal fix: exact files/lines for `Portfolio` properties, `MetricsManager`
  coercions, `EnhancedOrderValidator` float checks) and **"`TradingInterface` Bypasses Decimal
  Domain"** (the D-09 deferred live-mode leak)
- `.planning/codebase/ARCHITECTURE.md` — current event-driven component graph (informs the
  force-match reimplementation of SMA_MACD in the reference engines)

### Phase carry-forward (constrains M5c)
- `.planning/phases/07-m5b-sizing-policy-metrics-universe-coverage/07-CONTEXT.md` — D-16
  (industry-standard metric definitions matched to the Phase 8 reference engines — the
  reconciliation baseline), D-15/D-17 (frozen derived metrics + slippage columns in the
  golden artifacts), D-11 (named-re-freeze + owner-sign-off discipline this phase inherits)
- `.planning/phases/06-m5a-backtest-validity-fills-data-pipeline/06-CONTEXT.md` — D-21/D-22/
  D-23 (hybrid oracle discipline: structural-first, named expected-diff note per result
  change, owner sign-off — Phase 8's law), next-bar-open fill semantics the reference engines
  must force-match

### Golden assets (the current frozen reference + the final oracle target)
- `tests/golden/summary.json` — current frozen metrics (134 trades, final_equity ≈
  46189.877…); the headline-metric reconciliation target (D-04)
- `tests/golden/trades.csv` — current frozen trade log (entry/exit times + sides) — the
  trade-level reconciliation target (D-02)
- `tests/golden/equity.csv` — current frozen equity curve
- `tests/golden/REFREEZE-M5B-DIRECTION.md`, `tests/golden/REFREEZE-M5B-INCREASE.md`,
  `tests/golden/REFREEZE-M5A.md` — precedent format for the M5-C re-freeze note(s)
- `scripts/run_backtest.py` — the deterministic oracle generator (config: cash $10k, fees 0,
  slippage 0, SMA_MACD defaults) — the exact config the reference engines must force-match
  (D-01)
- `itrader/strategy_handler/SMA_MACD_strategy.py` — the strategy to reimplement in the
  reference engines; note the filter-gates-both-entry-and-exit quirk (D-01)
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — the golden dataset (same data into all engines)

### External (reference engines — to be added as pinned dev deps)
- `backtesting.py` (gating reference) — https://kernc.github.io/backtesting.py/
- `backtrader` (gating reference) — https://www.backtrader.com/docu/
- `nautilus_trader` (optional non-gating reference, D-12) —
  https://nautilustrader.io/docs/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/run_backtest.py` — the deterministic artifact builder; its config block (CASH=10k,
  fees 0, slippage 0, SMA_MACD defaults) is the source of truth for the D-01 force-match
  config, and its `build_trade_log` / `build_equity_curve` + `attach_slippage` produce the
  iTrader side of the reconciliation.
- `itrader/reporting/metrics.py` — the pure metric functions (D-16, matched to backtesting.py
  formulas: PERIODS=365, ddof=1) that compute the headline metrics being reconciled.
- `tests/golden/*` + the existing run-path integration test (byte-exact diff) — the permanent
  regression gate that stays in place (D-10); extended by the M5-C re-freeze.
- `itrader/portfolio_handler/portfolio.py` + `itrader/portfolio_handler/metrics/metrics_manager.py`
  + `itrader/order_handler/order_validator.py` — the D-06 float→Decimal cleanup targets
  (exact lines in CONCERNS.md).

### Established Patterns
- Hybrid oracle discipline (Phase 6 D-21 / Phase 7 D-11): result-changing work lands as a
  named re-freeze with an expected-diff note + owner sign-off. D-08 (Decimal) and any D-05
  bug-fix follow it.
- Decimal-end-to-end + `to_money` quantization (`core/money.py`); `mypy --strict` gate;
  `filterwarnings=["error"]` — the D-06 cleanup must satisfy all three.
- Tabs in handler modules; spaces in newer modules — match the file edited; new
  `scripts/cross_validate.py` is new code → spaces.
- Poetry dev-dependency group for tooling — where the reference engines are pinned (D-10).

### Integration Points
- `scripts/cross_validate.py` (new) — consumes `data/BTCUSD_1d_ohlcv_2018_2026.csv`, runs the
  three engines force-matched, emits the reconciliation report; reads iTrader's frozen
  `tests/golden/*` for the iTrader side.
- The D-06 float→Decimal retype propagates through `Portfolio` properties → `MetricsManager`
  aggregates → equity-curve / drawdown / `summary.json` serialization → the frozen artifacts
  (hence the D-08 re-freeze).
- `pyproject.toml` — poetry dev group gains backtesting.py / backtrader / nautilus_trader
  (pinned); ensure no `filterwarnings=["error"]` breakage from importing them in the script
  path (kept out of the test suite per D-10).

</code_context>

<specifics>
## Specific Ideas

- User consistently anchors on **"what's the industry standard / most professional?"** —
  surfaced Nautilus Trader as the most production-grade reference and asked whether to include
  it (resolved as the D-12 optional non-gating third engine, on its merit as the closest
  architectural mirror to iTrader's event-driven design).
- User proactively flagged the **CONCERNS.md Decimal/float bugs** from the end-of-Phase-6
  map-codebase run and asked whether they belong in this phase — resolved as the D-06
  golden-path-only Decimal cleanup (live-mode `TradingInterface` leak deferred to `D-live`).
- User favored the rigorous end of every choice: force-match-exactly (D-01) over pragmatic
  alignment, trade-level-primary (D-02) over metric-only, root-cause-decides (D-05) over
  explain-away — consistent with the program's correctness-first mandate.

</specifics>

<deferred>
## Deferred Ideas

- **`TradingInterface` Decimal cleanup** (live-mode order path: `float` signatures,
  `price=0.0` literal) → `D-live`. Noted in CONCERNS.md; out of backtest-correctness scope.
- **Nautilus as a gating engine** — could become a first-class gating reference in a future
  validation effort; this program keeps it non-gating (D-12).
- **Permanent multi-engine CI gate** — wiring the three-engine comparison into `make test`
  was considered and rejected (D-10) due to dev-dep weight + reference-engine maintenance;
  could be revisited if the engine ever needs continuous external regression.
- **Wall-clock leaks in domain code** (D-09/D-10 incomplete per CONCERNS.md — `datetime.now()`
  in MetricsManager/PositionManager/SimulatedExchange) — determinism is currently preserved
  because result-bearing paths receive explicit time; not a golden-output defect, so not in
  this phase's cleanup. Tracked for a future hardening pass.
- **Multi-strategy / multi-symbol cross-validation** — golden + cross-validation stay
  single-strategy, single-symbol (BTCUSD) this program (carried from Phase 7).

</deferred>

---

*Phase: 8-m5c-cross-validation-final-oracle*
*Context gathered: 2026-06-08*
