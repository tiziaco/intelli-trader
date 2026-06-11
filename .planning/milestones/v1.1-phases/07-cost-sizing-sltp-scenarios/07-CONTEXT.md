# Phase 7: Cost, Sizing & SLTP Scenarios - Context

**Gathered:** 2026-06-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the **already-built** cost/sizing/SLTP machinery its **first end-to-end
golden coverage** — hand-verified, contrived-bar leaf scenarios authored on the
Phase 4 E2E harness (and the Phase 6 scripted-emitter / orders-snapshot infra),
then `--freeze` regression-locked. Twelve requirements:

- **COST-01..06** — percent + maker_taker fee models (maker vs taker on
  limit vs market), fixed + linear slippage models, slippage **not** applied to
  limit fills, and a combined fee+slippage round-trip with cash math verified to
  the cent.
- **SIZE-01..03** — `FixedQuantity` and `RiskPercent` (off stop distance)
  sizing, and over-cash sizing producing the audited insufficient-funds
  rejection.
- **SLTP-01..03** — `PercentFromDecision` (priced at signal assembly) and
  `PercentFromFill` (anchored to the actual fill) SL/TP, each across SL-hit,
  TP-hit, and held-to-end exit outcomes.

**This is a COVERAGE phase — the engine machinery already ships:**
- Fee models (zero/percent/maker_taker) and slippage models
  (zero/fixed/linear) are implemented and Decimal-native.
- **COST-05 (slippage not on limit) and maker/taker classification already
  exist** in `simulated.py` (D-03: `is_maker = order_type is LIMIT`; limit fills
  forced `slippage_factor = Decimal("1")`).
- Sizing (`FractionOfCash`/`FixedQuantity`/`RiskPercent`) resolves through the
  one `SizingResolver`; SLTP (`PercentFromDecision`/`PercentFromFill`) resolves
  in `OrderManager`.
- The `spec.exchange` → exchange-config harness seam was pre-wired in Phase 6
  (**"OPEN Q1 — deferred to Phase 7"**) — but it is currently **broken** (see
  D-09). `ScenarioSpec.exchange` already exists.

We EXERCISE this behavior; we do not BUILD it. The only new code is the thin
test scaffolding (commission golden column, emitter `sltp_policy`, exchange-seam
fix) plus the ~15 scenario leaves.

**In scope:**
- ~15 self-contained leaf scenarios under `tests/e2e/cost/`, `tests/e2e/sizing/`,
  `tests/e2e/sltp/` (one per distinct cost/sizing/SLTP story), each with
  fresh contrived `bars.csv` + scripted emitter + VERIFY hand-derivation +
  frozen golden set.
- A foundational (non-parallel) plan that adds the shared scaffolding and proves
  it on ONE canary before the parallel scenario waves (D-13).

**Out of scope (own phases / behavior-preserving):**
- Scale-in/scale-out, `max_positions` rejection, exit-then-re-entry, cash
  reservation/release lifecycle — **Phase 8** (ADMIT/CASH).
- Multi-ticker / multi-strategy / multi-portfolio, robustness, degenerate
  metrics, cross-scenario determinism — **Phase 9** (MULTI/ROBUST).
- Re-baselining the BTCUSD golden oracle — v1.1 is behavior-preserving. Every
  Phase 7 scenario runs a CONFIGURED exchange on its OWN contrived bars, so
  oracle-darkness is automatic; the BTCUSD oracle
  (`tests/integration/test_backtest_oracle.py`) is never touched, and the
  commission golden column stays out of the core `TRADE_COLUMNS` pin (D-07).

</domain>

<decisions>
## Implementation Decisions

### Cost-math golden vehicle (COST-06 "to the cent")
- **D-07:** **Explicit `commission` column on the E2E trade-log golden**, wired
  from the REAL `Position.commission` property (`position.py:132`,
  `buy_commission + sell_commission`) — NOT recomputed. The cost math is
  independently visible and frozen per trade, satisfying COST-06's "to the cent"
  audit; the per-cent derivation lives in each leaf's VERIFY note, cross-checked
  against the frozen column + `summary.json` `final_cash`.
- **D-08:** **The column is ALWAYS-ON across all E2E trade goldens** (uniform
  schema; `commission = 0.00` for zero-fee leaves). It is appended **after**
  `TRADE_COLUMNS` in the **E2E serialization path ONLY** — never added to the
  core `frames.py::TRADE_COLUMNS` pin that the BTCUSD integration oracle freezes
  (mirrors the existing D-17 `SLIPPAGE_COLUMNS` append in
  `reporting/summary.py`). **Oracle-dark.** Phase 6's zero-fee leaf trade
  goldens get a **one-time additive re-freeze** (commission column = 0.00) — a
  mechanical schema add, not a behavior change.

### Fill substrate (roadmap: "reuses matching scenarios")
- **D-09a:** **Author FRESH per-leaf bars.** "Reuses matching scenarios" means
  reuse the matching **mechanism** (scripted-emitter, harness, fill shapes) —
  NOT literal Phase 6 bar files. Each leaf authors minimal contrived bars tuned
  to ONE cost/sizing/SLTP story so the cost dimension is the only moving part and
  the per-cent math is cleanly hand-derivable. Isolated, parallel-safe (Phase 6
  D-11).

### Leaf granularity / requirement→scenario mapping (~15 leaves)
- **D-10:** **One leaf per requirement, strict one-shape-per-leaf** (Phase 6
  D-11), with the SLTP set expanded to the full matrix:
  - **COST → 6 leaves** (one per COST-01..06). COST-02 asserts maker (limit) AND
    taker (market) **within its single leaf** — that contrast IS the
    requirement. COST-05 is a **standalone** limit-no-slip proof.
  - **SIZE → 3 leaves** (FixedQuantity, RiskPercent, over-cash reject).
  - **SLTP → 6 leaves** (full 2×3 matrix: `PercentFromDecision` × {SL-hit,
    TP-hit, held-to-end} and `PercentFromFill` × {SL-hit, TP-hit, held-to-end}).
- **D-11:** **COST-02 maker/taker shape = two entries in one scenario** — a
  limit entry that rests-then-fills (maker, lower rate) followed by a market
  entry filling next-bar-open (taker, higher rate). The `commission` column
  (D-07) shows the two distinct rates side by side — one-leaf maker-vs-taker
  contrast.

### Emitter extension (test scaffolding)
- **D-12:** **Extend the single `ScriptedEmitter`** (`tests/e2e/strategies/
  scripted_emitter.py`) with an `sltp_policy` parameter (it already carries
  `sizing_policy`; the docstring flags `sltp_policy` as Phase 7 work). The policy
  flows to `SignalEvent.sltp_policy` exactly as `sizing_policy` already does. No
  bespoke per-policy strategy classes — one generic parametrized mechanism reused
  across all leaves (Phase 6 D-01). The emitter must also allow a **declarable
  stop** so `RiskPercent` can size.
- **D-13 (constraint, NOT a question):** `RiskPercent` sizes off stop
  **distance** (`(equity * risk_pct) / |price − stop|`,
  `sizing_resolver.py`). So **SIZE-02 must pair with a decision-time stop** —
  an explicit `stop_loss` level or `PercentFromDecision` — NOT `PercentFromFill`
  (whose stop isn't known until the fill → circular). Planner must wire SIZE-02's
  emitter with a known-at-decision stop.

### Exchange-config seam (the pre-wired OPEN-Q1 seam, currently broken)
- **D-14:** **Re-init from the config object, post-construction.** The harness
  sets `simulated.config = spec.exchange` then re-runs the EXISTING
  `_init_fee_model()` / `_init_slippage_model()` — replacing the **broken**
  `update_config(**exchange_config.model_dump())` call at `conftest.py:~250`
  (`model_dump()` yields NESTED keys `fee_model={...}`/`slippage_model={...}`,
  but `update_config`'s mapping only recognizes FLAT keys like `fee_model_type`/
  `fee_rate`/`base_slippage_pct` → silent no-op; there is also a `to_kwargs`
  double-prefix quirk `slippage_base_slippage_pct`). The config-object path is
  clean (no stringly-flat kwargs), uses machinery the constructor already
  exercises, and is **oracle-dark** (only fires when `spec.exchange` is
  non-None; Phase 6 None-exchange leaves and the BTCUSD oracle are untouched).
  This seam fix is part of the foundational plan and proven on the canary.

### Over-cash rejection golden vehicle (SIZE-03)
- **D-15:** **Reuse the opt-in orders-snapshot** (REJECTED status) — the Phase 6
  vehicle for no-trade outcomes (MATCH-08 never-fill, cancel). The frozen order
  mirror shows the over-cash entry at REJECTED. One consistent, already-built
  mechanism; no new audit serializer.

### Plan / wave sequencing
- **D-16:** **Foundational plan first, then 3 parallel waves** (Phase 6 D-13):
  - **Plan 1 (non-parallel):** the `commission` golden column (D-07/D-08), the
    `ScriptedEmitter.sltp_policy` extension (D-12), the exchange-seam fix (D-14),
    and ONE canary scenario proving the wiring end-to-end + the Phase 6 zero-fee
    re-freeze. Re-runs the BTCUSD oracle gate byte-exact.
  - **Then parallel waves** grouped COST / SIZE / SLTP; generate in isolated
    worktrees, then **hand-verify + freeze batched per cluster** (honors the
    roadmap "not 12-at-once" + "shared infra committed first" preconditions).

### Claude's Discretion
- Exact `commission` column name/position and the E2E-serialization append point
  (subject to D-07/D-08: real `position.commission`, oracle-dark, after
  `TRADE_COLUMNS`).
- Exact contrived `bars.csv` authoring per leaf (subject to D-09a/D-10/D-11:
  fresh, hand-derivable, one story per leaf, real `CsvPriceStore` path).
- `ScriptedEmitter.sltp_policy` parameter shape and how the stop is declared for
  RiskPercent (subject to D-12/D-13).
- Exact `tests/e2e/{cost,sizing,sltp}/` sub-directory names/depth (subject to
  Phase 4 D-14 subsystem grouping).
- Wave composition within the COST/SIZE/SLTP clusters and the batched-verify
  sitting boundaries (subject to D-16).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The harness + scenario infra this phase builds on (read FIRST)
- `.planning/phases/06-order-matching-scenarios/06-CONTEXT.md` — the directly
  preceding sibling coverage phase; the scripted-emitter (D-01), one-shape-per-
  leaf (D-11), opt-in orders-snapshot for no-trade outcomes (D-08/D-09),
  foundational-plan-first (D-13), and date-keyed scripting decisions Phase 7
  inherits wholesale.
- `.planning/phases/04-e2e-harness-framework/04-CONTEXT.md` — the base harness
  contract (per-folder one-line test → `run_scenario`; `ScenarioSpec` reuses real
  config; diff-what's-frozen; exact no-tolerance diff; CONTRIVED bars;
  `--freeze` + per-scenario VERIFY note; subsystem grouping; D-16/D-17 shared
  reporting assembly + post-hoc slippage columns).
- `tests/e2e/conftest.py` — the `run_scenario` harness + `--freeze` + exact-diff
  machinery. **The exchange seam to FIX lives here** (~L237-254: `exchange="csv"`
  construction + the broken `update_config(**model_dump())` block, D-14).
- `tests/e2e/scenario_spec.py` — `ScenarioSpec` (carries `exchange`, `actions`,
  `strategies`, `portfolios`) + `Action`/`PortfolioSpec`. Field names are a
  consuming contract — do not rename.
- `tests/e2e/strategies/scripted_emitter.py` — the generic emitter to extend with
  `sltp_policy` (D-12); already takes `sizing_policy` (defaults
  `FractionOfCash(0.95)`).
- `tests/e2e/smoke/single_market_buy/scenario.py` — the `scenario.py` + VERIFY-
  note copy-template each leaf clones.
- `tests/integration/test_backtest_oracle.py` — the byte-exact BTCUSD oracle gate
  the commission column (D-08) and seam fix (D-14) must stay DARK against; reads
  `output/trades.csv` (so the commission column must NOT enter core
  `TRADE_COLUMNS`).

### System under test — cost models (already implemented)
- `itrader/execution_handler/exchanges/simulated.py` — `_apply_fill` (~L177-229):
  applies fee + slippage, `is_maker = order_type is OrderType.LIMIT`, **COST-05
  limit-no-slip already enforced** (`slippage_factor = Decimal("1")` for LIMIT,
  D-03); `_init_fee_model`/`_init_slippage_model` (~L482-518) — **the clean
  config-object re-init path D-14 reuses**; `update_config` (~L535+, the broken
  flat-kwarg surface to STOP routing through). `__init__(config: ExchangeConfig)`
  builds models from config.
- `itrader/execution_handler/fee_model/` — `base.py` (validate_inputs raises;
  `is_maker` authoritative when provided, D-11), `percent_fee_model.py` (COST-01),
  `maker_taker_fee_model.py` (COST-02), `zero_fee_model.py`.
- `itrader/execution_handler/slippage_model/` — `base.py`, `fixed_slippage_model.py`
  (COST-03), `linear_slippage_model.py` (COST-04), `zero_slippage_model.py`.
- `itrader/config/exchange.py` — `ExchangeConfig`/`FeeModelConfig`/
  `SlippageModelConfig` (the `spec.exchange` object scenarios carry);
  `get_exchange_preset` presets; **note the `to_kwargs` double-prefix quirk**
  (`slippage_base_slippage_pct`) that D-14 sidesteps.
- `itrader/execution_handler/execution_handler.py` — `_init_exchanges` (~L97-104)
  builds `SimulatedExchange(..., rng=...)` with NO config (default preset); the
  injection point if a future faithful-construction path is ever chosen (D-14
  rejected threading through here for now).

### System under test — sizing & SLTP (already implemented)
- `itrader/core/sizing.py` — `FixedQuantity` (SIZE-01), `RiskPercent` (SIZE-02),
  `FractionOfCash`, `PercentFromDecision` (SLTP-01), `PercentFromFill` (SLTP-02),
  `SignalIntent` (`stop_loss`/`take_profit`/`exit_fraction`/`quantity`).
- `itrader/order_handler/sizing_resolver.py` — the ONE `SizingResolver`;
  `resolve_entry` match-dispatch; **RiskPercent stop-distance math + the
  SizingPolicyViolation when stop is missing/equal-to-price (D-13 constraint)**;
  over-cash path feeds SIZE-03's REJECTED.
- `itrader/order_handler/order_manager.py` — `_create_primary_order` + bracket
  assembly (~L557-746): the SLTP policy resolution (`PercentFromDecision` priced
  at `signal_event.price` ~L615-621; `PercentFromFill` deferred to a
  `_PendingBracket` armed in `on_fill` ~L118-232); `_bracket_levels` (~L727);
  audited insufficient-funds REJECTED route (SIZE-03).
- `itrader/portfolio_handler/position/position.py` — `commission` property
  (~L132), `buy_commission`/`sell_commission` (~L41-58) — **the real source D-07
  wires the golden column from**; `to_dict` (~L244) the trade-log row source.
- `itrader/strategy_handler/config.py` — `BaseStrategyConfig` carries
  `sizing_policy` + `sltp_policy`; `strategy_handler/strategies_handler.py`
  (~L138 `order_type`, ~L163 `sltp_policy`) — how declarations reach
  `SignalEvent`.

### Reporting / golden serialization
- `itrader/reporting/frames.py` — `TRADE_COLUMNS` (the oracle-pinned core list,
  D-08 must NOT touch), `build_trade_log` (from `closed_positions`).
- `itrader/reporting/summary.py` — `SLIPPAGE_COLUMNS` + `attach_slippage`: the
  **append-after-`TRADE_COLUMNS` precedent the commission column (D-07/D-08)
  follows**; `build_summary` (`final_cash`/`starting_cash`/realised PnL, COST-06).
- `itrader/events_handler/events/fill.py` — `FillEvent.commission` (Decimal,
  D-22), the per-fill fee the exchange emits.

### Phase / requirements / roadmap
- `.planning/ROADMAP.md` §"Phase 7: Cost, Sizing & SLTP Scenarios" — goal + 4
  success criteria + the Phase 6 parallelization REMINDER (shared infra committed
  first; hand-verify in deliberate batches).
- `.planning/REQUIREMENTS.md` — COST-01..06 (~L53-58), SIZE-01..03 (~L61-63),
  SLTP-01..03 (~L66-68).
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore` + `csv_paths`
  passthrough (the contrived-CSV data seam).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`run_scenario` harness + `--freeze`** (`tests/e2e/conftest.py`) — full
  build-run-diff machinery; Phase 7 fixes its exchange seam (D-14) and adds the
  commission column to its serialization.
- **`ScriptedEmitter` + `ScenarioSpec` + the leaf copy-template** — clone per
  leaf; extend the emitter with `sltp_policy` (D-12).
- **Opt-in orders-snapshot golden** (Phase 6 D-08) — reused verbatim for SIZE-03
  REJECTED (D-15).
- **`_init_fee_model`/`_init_slippage_model` on `SimulatedExchange`** — the clean
  config-object path D-14 re-runs; no new exchange plumbing.
- **All cost/sizing/SLTP engine logic already exists** — fee/slippage models,
  `SizingResolver`, SLTP bracket resolution, `Position.commission`,
  insufficient-funds REJECTED. Phase 7 COVERS these, does not build them.
- **D-17 `SLIPPAGE_COLUMNS` append** (`reporting/summary.py`) — the exact
  oracle-dark append pattern the commission column copies.

### Established Patterns
- **Self-contained, parallel-safe leaf folders** — basis for D-10 slicing + the
  parallel waves.
- **Diff-what's-frozen / presence=assertion / exact no-tolerance diff** — the
  commission column + SIZE-03 snapshot follow this.
- **Behavior-preserving / oracle-dark** — configured-exchange scenarios run on
  their own bars; the BTCUSD oracle is never touched; the commission column stays
  out of core `TRADE_COLUMNS`; the seam fix only fires for non-None
  `spec.exchange`.
- **Foundational-plan-first** (Phase 6 D-13) — shared scaffolding + one canary
  before the parallel wave.

### Integration Points
- `commission` column: `Position.commission` → E2E serialization in
  `run_scenario` (append after `TRADE_COLUMNS`, like `attach_slippage`).
- `ScriptedEmitter.sltp_policy` → `SignalEvent.sltp_policy` → `OrderManager`
  bracket resolution.
- `spec.exchange` (`ExchangeConfig`) → `simulated.config` + `_init_*` re-init
  (D-14), replacing the broken `update_config` block.
- SIZE-03 REJECTED → opt-in orders-snapshot diff.
- `tests/e2e/{cost,sizing,sltp}/` leaves ← built on all the above in the
  parallel waves.

</code_context>

<specifics>
## Specific Ideas

- **Auditability drove the cost-golden choice (D-07/D-08).** The user wanted the
  fee *explicitly visible and frozen* per trade, not buried in `final_cash` — and
  chose a uniform always-on column over an opt-in one, accepting the one-time
  Phase 6 re-freeze for schema consistency.
- **Faithfulness over convenience (continuing the Phase 6 stance).** Fresh
  per-leaf bars so each cost story is isolated (D-09a); the exchange config
  reaches the engine through the engine's OWN clean re-init path rather than a
  patched stringly-flat kwarg surface (D-14); SIZE-03 reuses the genuine REJECTED
  audit outcome (D-15).
- **The pre-wired seam was a planted Phase-7 task that turned out broken.** Phase
  6 left `spec.exchange` → `update_config` as "OPEN Q1 deferred to Phase 7";
  Phase 7 discovers it silently no-ops (nested vs flat keys) and fixes it
  correctly in the foundational plan — proven on the canary before any cost leaf
  depends on it.

</specifics>

<deferred>
## Deferred Ideas

- **Faithful construction-time exchange config** (thread `ExchangeConfig` through
  `TradingSystem` → `ExecutionHandler` → `SimulatedExchange` so the exchange is
  never built config-less). Considered for D-14 and deliberately deferred —
  touches the production composition root for a test-only need; the
  post-construction re-init is sufficient and oracle-dark. Revisit only if a
  production caller needs per-run exchange config at construction.
- **A dedicated per-trade cost-ledger golden** (gross/fee/slippage/net
  breakdown). Considered for COST-06 and rejected in favor of the simpler
  always-on `commission` column + `final_cash` (D-07). Revisit only if a future
  phase needs a richer cost attribution artifact.
- **Run-end resting-order disposition / time-in-force** (carried from Phase 6) —
  still unwired; not a Phase 7 concern.
- **Explicit per-intent limit/stop ENTRY price + per-intent `order_type`**
  (carried from Phase 6 deferred) — a real missing production feature; Phase 7
  continues to work around it via contrived bars. Owner-gated, future milestone.

None of these block Phase 7 — discussion otherwise stayed within scope.

</deferred>

---

*Phase: 7-Cost, Sizing & SLTP Scenarios*
*Context gathered: 2026-06-10*
