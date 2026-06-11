# Phase 7: Cost, Sizing & SLTP Scenarios - Research

**Researched:** 2026-06-10
**Domain:** Golden-master coverage authoring (cost/sizing/SLTP) on the iTrader E2E harness
**Confidence:** HIGH (every CONTEXT.md fact verified against live code with exact line numbers)

## Summary

This is a **coverage / test-authoring phase**, not a build phase. The cost (fee/slippage), sizing,
and SLTP engine machinery is already shipped, Decimal-native, and verified in this research to behave
exactly as `07-CONTEXT.md` describes. The phase exercises that machinery with ~15 hand-derivable,
contrived-bar leaf scenarios on the Phase 4 `run_scenario` harness + Phase 6 scripted-emitter /
orders-snapshot infra, then `--freeze` regression-locks them. The only NEW code is thin test
scaffolding: an E2E-only `commission` golden column (D-07/D-08), a one-line `ScriptedEmitter.sltp_policy`
extension (D-12), and the exchange-config seam FIX (D-14) — plus the ~15 scenario leaves.

I verified all six investigation targets against the live code. Three findings sharpen the plan
materially: **(1)** the D-14 seam is broken exactly as described and the fix is two lines
(`simulated.config = spec.exchange`; re-run `_init_fee_model()`/`_init_slippage_model()`); **(2)** the
`sltp_policy` plumbing already exists end-to-end (`BaseStrategyConfig.sltp_policy`, `Strategy.sltp_policy`,
`strategies_handler` puts it on `SignalEvent`) — the emitter change is a single constructor kwarg passed
into the config; **(3)** the slippage models have a **determinism authoring trap** the planner must
encode in the leaf design: `LinearSlippageModel` ALWAYS draws RNG base-noise, and `FixedSlippageModel`
draws RNG when `random_variation=True` (the `high_fee` preset's default). COST-03/COST-04 are only
hand-derivable when base/jitter noise is zeroed (`random_variation=False` for fixed; `base_slippage_pct=0`
for linear).

**Primary recommendation:** Build the foundational plan exactly per D-16 (commission column in
`tests/e2e/conftest.py` only; emitter `sltp_policy` kwarg; D-14 two-line seam fix; ONE canary;
re-freeze all 15 existing E2E trade goldens with `commission=0.00`; re-run the BTCUSD oracle gate).
Then three parallel waves (COST/SIZE/SLTP, ~15 leaves) cloning the `matching/brackets/oco_lifecycle`
leaf pattern. Author every cost leaf with **noise disabled** so the per-cent VERIFY math is exact.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fee calculation (percent/maker_taker) | Execution (`SimulatedExchange._emit_fill` → `fee_model`) | — | Exchange is the source of fill truth; fee is applied at fill emission |
| Slippage application | Execution (`_emit_fill` → `slippage_model`) | — | Slippage adjusts fill price; gated OFF for LIMIT (D-03, COST-05) |
| Sizing resolution | Order (`OrderManager._resolve_signal_quantity` → `SizingResolver`) | Portfolio read-model (equity/cash) | Strategy declares policy; order layer resolves quantity |
| SLTP bracket pricing | Order (`OrderManager._assemble_bracket_and_emit` / `on_fill`) | — | Bracket children priced at assembly (Decision) or fill (Fill) |
| Over-cash rejection | Order (`reserve()` → `InsufficientFundsError` → audited REJECTED) | Portfolio (`reserve`) | Cash gate is synchronous check-and-reserve at admission |
| Commission visibility (golden) | Reporting/test seam (E2E `conftest._assemble`) | Portfolio (`Position.commission`) | E2E-only serialization append; never core `TRADE_COLUMNS` |
| Exchange config injection | Test harness (`conftest._build_and_run`) | Execution (`_init_*` re-init) | Post-construction re-init; oracle-dark when `spec.exchange is None` |

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-07 .. D-16)

- **D-07 — commission golden column:** Explicit `commission` column on the E2E trade-log golden, wired
  from the REAL `Position.commission` property (`position.py:132`, `buy_commission + sell_commission`) —
  NOT recomputed. Per-cent derivation lives in each leaf's VERIFY note, cross-checked against the frozen
  column + `summary.json` `final_cash`.
- **D-08 — always-on, E2E-only, oracle-dark:** The column is ALWAYS-ON across all E2E trade goldens
  (`commission = 0.00` for zero-fee leaves). Appended AFTER `TRADE_COLUMNS` in the **E2E serialization
  path ONLY** — never in core `frames.py::TRADE_COLUMNS` (the BTCUSD oracle freeze). Mirrors the existing
  `SLIPPAGE_COLUMNS` append in `reporting/summary.py`. Phase 6's zero-fee trade goldens get a one-time
  additive re-freeze (`commission = 0.00`).
- **D-09a — fresh per-leaf bars:** "Reuses matching scenarios" = reuse the matching MECHANISM
  (scripted-emitter, harness, fill shapes), NOT literal Phase 6 bar files. Each leaf authors minimal
  contrived bars tuned to ONE story.
- **D-10 — one leaf per requirement (~15 leaves):** COST → 6 (one per COST-01..06; COST-02 asserts
  maker+taker within its single leaf; COST-05 standalone limit-no-slip). SIZE → 3 (FixedQuantity,
  RiskPercent, over-cash reject). SLTP → 6 (full 2×3 matrix: `PercentFromDecision` × {SL-hit, TP-hit,
  held-to-end} and `PercentFromFill` × {SL-hit, TP-hit, held-to-end}).
- **D-11 — COST-02 shape:** Two entries in one scenario — a LIMIT entry that rests-then-fills (maker,
  lower rate) then a MARKET entry next-bar-open (taker, higher rate). The `commission` column shows the
  two distinct rates side by side.
- **D-12 — emitter `sltp_policy` extension:** Extend the single `ScriptedEmitter` with an `sltp_policy`
  parameter (it already carries `sizing_policy`). The policy flows to `SignalEvent.sltp_policy` exactly
  as `sizing_policy` does. The emitter must also allow a declarable stop so `RiskPercent` can size.
- **D-13 (constraint, NOT a question):** `RiskPercent` sizes off stop DISTANCE
  `(equity * risk_pct) / |price − stop|`. SIZE-02 MUST pair with a decision-time stop — an explicit
  `stop_loss` level or `PercentFromDecision` — NOT `PercentFromFill` (whose stop isn't known until fill).
- **D-14 — exchange-config seam fix:** Re-init from the config object, post-construction. The harness
  sets `simulated.config = spec.exchange` then re-runs the EXISTING `_init_fee_model()` /
  `_init_slippage_model()` — replacing the broken `update_config(**exchange_config.model_dump())` call at
  `conftest.py:~250`. Oracle-dark (only fires when `spec.exchange` is non-None). Part of the foundational
  plan, proven on the canary.
- **D-15 — SIZE-03 vehicle:** Reuse the opt-in orders-snapshot (REJECTED status), the Phase 6 vehicle for
  no-trade outcomes. The frozen order mirror shows the over-cash entry at REJECTED.
- **D-16 — plan sequencing:** Foundational plan first (commission column, emitter `sltp_policy`,
  exchange-seam fix, ONE canary, Phase 6 zero-fee re-freeze, BTCUSD oracle re-run byte-exact), then 3
  parallel waves grouped COST / SIZE / SLTP, hand-verify + freeze batched per cluster.

### Claude's Discretion

- Exact `commission` column name/position and the E2E-serialization append point (subject to D-07/D-08:
  real `position.commission`, oracle-dark, after `TRADE_COLUMNS`).
- Exact contrived `bars.csv` authoring per leaf (subject to D-09a/D-10/D-11: fresh, hand-derivable, one
  story per leaf, real `CsvPriceStore` path).
- `ScriptedEmitter.sltp_policy` parameter shape and how the stop is declared for RiskPercent (subject to
  D-12/D-13).
- Exact `tests/e2e/{cost,sizing,sltp}/` sub-directory names/depth (subject to Phase 4 D-14 subsystem
  grouping).
- Wave composition within the COST/SIZE/SLTP clusters and the batched-verify sitting boundaries (D-16).

### Deferred Ideas (OUT OF SCOPE)

- Faithful construction-time exchange config (threading `ExchangeConfig` through `TradingSystem` →
  `ExecutionHandler` → `SimulatedExchange`). Deliberately deferred — post-construction re-init is
  sufficient and oracle-dark.
- A dedicated per-trade cost-ledger golden (gross/fee/slippage/net). Rejected for the simpler always-on
  `commission` column + `final_cash`.
- Run-end resting-order disposition / time-in-force (carried from Phase 6) — still unwired.
- Explicit per-intent limit/stop ENTRY price + per-intent `order_type` (carried from Phase 6 deferred) —
  Phase 7 works around it via contrived bars.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COST-01 | percent fee model on a round-trip | `PercentFeeModel.calculate_fee` = `abs(qty*price) * buy_rate/sell_rate` (`percent_fee_model.py:89-95`); wired via `FeeModelConfig(model_type=PERCENT, fee_rate=...)` |
| COST-02 | maker_taker — maker vs taker distinguished (limit vs market) | `MakerTakerFeeModel`; `is_maker = order_type is LIMIT` authoritative (`simulated.py:202`); LIMIT entry → maker_rate, MARKET entry → taker_rate. One leaf, two entries (D-11) |
| COST-03 | fixed slippage model | `FixedSlippageModel`; MUST set `random_variation=False` for deterministic directional slippage (`fixed_slippage_model.py:84-88`) |
| COST-04 | linear slippage model | `LinearSlippageModel`; MUST set `base_slippage_pct=0` to zero RNG noise, leaving pure deterministic `size_impact` (`linear_slippage_model.py:85-94`) |
| COST-05 | slippage NOT applied to limit fills | Already enforced: `if event.order_type is OrderType.LIMIT: slippage_factor = Decimal("1")` (`simulated.py:206-208`). Standalone limit-no-slip proof |
| COST-06 | combined fee+slippage round-trip, cash to the cent | `commission` column (D-07) + `final_cash` in `summary.json`; full Decimal flow FillEvent→Transaction→Position→cash verified |
| SIZE-01 | `FixedQuantity` sizing | `SizingResolver.resolve_entry` `case FixedQuantity(): qty = policy.qty` (`sizing_resolver.py:113-114`) |
| SIZE-02 | `RiskPercent` off stop distance | `(equity * risk_pct) / abs(price - stop)` (`sizing_resolver.py:124`); requires decision-time stop (D-13) |
| SIZE-03 | over-cash → audited insufficient-funds rejection | `reserve()` → `InsufficientFundsError` → `add_state_change(REJECTED, triggered_by="cash_reservation")` persisted (`order_manager.py:393-414`); orders-snapshot shows REJECTED |
| SLTP-01 | `PercentFromDecision` — priced at signal assembly | `_assemble_bracket_and_emit` → `_bracket_levels(policy, to_money(signal.price), action)` (`order_manager.py:615-622`) |
| SLTP-02 | `PercentFromFill` — anchored to actual fill in `on_fill` | `_PendingBracket` armed at assembly (`order_manager.py:628`), children created in `on_fill` via `_create_fill_anchored_children` (`order_manager.py:743`) |
| SLTP-03 | SL-hit, TP-hit, held-to-end outcomes | Observable in `trades.csv` (exit price = SL or TP level) / `summary.json` (held-to-end → open position at run end, no closed trade). Contrived bars trigger each |
</phase_requirements>

## Standard Stack

This phase writes **test scenarios in the existing project** — no new external dependencies. The
"stack" is the in-repo infrastructure each leaf reuses.

### Core (existing, reused verbatim)

| Component | Location | Purpose | Why Standard |
|-----------|----------|---------|--------------|
| `run_scenario` fixture | `tests/e2e/conftest.py` (full file) | build→run→read→assemble→diff-what's-frozen + `--freeze` | The single shared E2E harness all Phase 6-9 leaves consume |
| `ScriptedEmitter` | `tests/e2e/strategies/scripted_emitter.py` | generic date-keyed signal emitter | One parametrized mechanism (D-01/D-12); already carries `sizing_policy` |
| `ScenarioSpec` / `PortfolioSpec` / `Action` | `tests/e2e/scenario_spec.py` | per-leaf contract; `exchange: Any = None` already exists (L96) | Consuming contract — do NOT rename fields |
| `build_orders_snapshot` | `itrader/reporting/orders.py` | opt-in REJECTED/order-mirror golden (SIZE-03) | Serializes `status` via `o.status.name` → REJECTED visible |
| `CsvPriceStore` | `itrader/price_handler/store/csv_store.py` | contrived-bar data seam via `csv_paths` | Real read path; `system.store.read_bars(ticker)` used in `_assemble` |

### Leaf copy-template

| Pattern source | Location | Use |
|----------------|----------|-----|
| Bracket leaf (sl/tp + orders golden) | `tests/e2e/matching/brackets/oco_lifecycle/scenario.py` | Canonical clone template for SLTP + SIZE-03 leaves (imports from `scenario_spec.py`, uses `ScriptedEmitter`, VERIFY note + orders.csv golden) |
| Pure-fill leaf (trades + summary only) | `tests/e2e/matching/entries/market_next_open/` | Clone template for COST leaves (trades.csv + summary.json) |
| Test body | any `*/test_scenario.py` | One line: `run_scenario(HERE)` — leaf adds NO assert logic |

**Installation:** None. No package installs in this phase.

## Package Legitimacy Audit

Not applicable — this phase installs no external packages. All infrastructure is in-repo Python
(Poetry-managed, already locked in `poetry.lock`). The "Don't Hand-Roll" guidance below covers reuse of
existing engine machinery rather than third-party libraries.

## Architecture Patterns

### System Architecture Diagram (the fill path each leaf exercises)

```
ScenarioSpec(exchange=ExchangeConfig)  ──┐
                                         │ (D-14 seam: conftest._build_and_run)
                                         ▼
                       simulated.config = spec.exchange
                       simulated.fee_model      = _init_fee_model()       (re-init)
                       simulated.slippage_model = _init_slippage_model()  (re-init)
                                         │
ScriptedEmitter(script, sizing_policy,  │
   sltp_policy, order_type)             │
        │ generate_signal               │
        ▼                               │
   SignalIntent ──► StrategiesHandler ──► SignalEvent(sizing_policy, sltp_policy,
        (buy/sell sugar: sl/tp →            stop_loss, take_profit, order_type, price)
         stop_loss/take_profit)              │
                                             ▼
                                      OrderManager.process_signal
                                       ├─ _resolve_signal_quantity ─► SizingResolver
                                       │    (FractionOfCash | FixedQuantity | RiskPercent)
                                       │      └─ SizingPolicyViolation → audited REJECTED
                                       ├─ reserve() ─► InsufficientFundsError
                                       │      └─ audited REJECTED (triggered_by=cash_reservation)  [SIZE-03]
                                       └─ _assemble_bracket_and_emit
                                            ├─ explicit sl/tp PRIMARY (truthy wins)
                                            ├─ PercentFromDecision → _bracket_levels(signal.price)   [SLTP-01]
                                            └─ PercentFromFill → _PendingBracket (armed in on_fill)   [SLTP-02]
                                             │
                                             ▼  OrderEvent(s)
                                      SimulatedExchange (MatchingEngine rests/triggers)
                                             │  _emit_fill:
                                             │   commission = fee_model.calculate_fee(is_maker=...)  [COST-01/02]
                                             │   slippage_factor = 1 if LIMIT else slippage_model(...) [COST-03/04/05]
                                             ▼  FillEvent(EXECUTED, commission, executed_price)
                                      PortfolioHandler.on_fill
                                       └─ Transaction.commission → Position.buy/sell_commission
                                          → Position.commission (D-07)  +  cash -= cost+commission   [COST-06]
                                             │
                          (read AFTER run, queue-only — conftest._assemble)
                                             ▼
       trades.csv [TRADE_COLUMNS + SLIPPAGE_COLUMNS + commission]   summary.json (final_cash)   orders.csv (opt-in)
```

### Component Responsibilities (where each NEW change lands)

| Change (D-tag) | File | Exact seam |
|----------------|------|------------|
| commission column (D-07/D-08) | `tests/e2e/conftest.py` `_assemble` + `_freeze` + `_diff` + `_roundtrip` | append after `TRADE_COLUMNS + SLIPPAGE_COLUMNS` |
| emitter `sltp_policy` (D-12) | `tests/e2e/strategies/scripted_emitter.py` `__init__` | new kwarg → `BaseStrategyConfig(sltp_policy=...)` |
| exchange-seam fix (D-14) | `tests/e2e/conftest.py` `_build_and_run` L246-254 | replace broken `update_config(**model_dump())` block |

### Pattern 1: The D-14 exchange-config seam fix (foundational, canary-proven)

**What:** Replace the broken post-construction config application with a clean re-init from the config
object.
**Current broken code** (`tests/e2e/conftest.py:246-254`):
```python
exchange_config = getattr(spec, "exchange", None)
if exchange_config is not None:
    simulated = system.execution_handler.exchanges["simulated"]
    if hasattr(exchange_config, "model_dump"):
        fields = exchange_config.model_dump()      # ← NESTED keys: fee_model={...}, slippage_model={...}
    else:
        fields = dict(exchange_config)
    simulated.update_config(**fields)              # ← BROKEN (see below)
```
**Why it's broken** (verified against `simulated.py:539-588` + `exchange.py:136-149`):
`model_dump()` yields top-level keys `exchange_type`, `exchange_name`, `fee_model` (a dict),
`slippage_model` (a dict), `limits`, `failure_simulation`, `connection`, `metadata`. In `update_config`,
the `config_mapping` recognizes only FLAT keys (`fee_model_type`, `fee_rate`, `base_slippage_pct`, …).
The nested keys `fee_model`/`slippage_model` fall through to `elif hasattr(self.config, key)` (both ARE
attributes of `ExchangeConfig`) and do `setattr(self.config, "fee_model", <plain dict>)` — **replacing
the Pydantic submodel with a raw dict.** The re-init guard `any(k.startswith("fee_") ...)` then matches
the `fee_model` key and calls `_init_fee_model()`, which reads `self.config.fee_model.model_type` →
`AttributeError` on a dict. Either way the configured fee/slippage NEVER reaches the models (the
CONTEXT.md "silent no-op" diagnosis is correct; the `to_kwargs` double-prefix `slippage_base_slippage_pct`
quirk at `exchange.py:88` confirms `to_kwargs()` is also not a clean path).

**The fix** (D-14 — clean, uses constructor's own machinery, oracle-dark):
```python
exchange_config = getattr(spec, "exchange", None)
if exchange_config is not None:
    simulated = system.execution_handler.exchanges["simulated"]
    # D-14: re-init from the config object exactly as __init__ does (simulated.py:70-74).
    simulated.config = exchange_config
    simulated.fee_model = simulated._init_fee_model()
    simulated.slippage_model = simulated._init_slippage_model()
```
`_init_fee_model` / `_init_slippage_model` (`simulated.py:482-520`) read `self.config.fee_model` /
`self.config.slippage_model` and build the concrete models from the Pydantic submodels — the exact path
the constructor (`__init__`, L73-74) already exercises. **When `spec.exchange is None` the whole block is
skipped → byte-identical to today → oracle-dark.**

**When to use:** Foundational Plan 1 only; proven on the canary before any COST leaf depends on it.

### Pattern 2: The commission golden column (E2E-only, oracle-dark)

**What:** Append a `commission` column to the E2E trade-log golden, sourced from the real
`Position.commission`.
**Critical mechanic:** `build_trade_log` (`frames.py:60`) does
`pd.DataFrame(rows, columns=TRADE_COLUMNS)` — it **restricts to `TRADE_COLUMNS`**, dropping every other
key. `Position.to_dict()` (`position.py:256-278`) does NOT even include `commission`. So the column
CANNOT ride through `build_trade_log`; it must be attached separately in the E2E path, exactly like
`attach_slippage` (`summary.py:42-95`) attaches `slippage_entry`/`slippage_exit`.

**Recommended implementation** (Claude's Discretion — column name `commission`, position LAST after
`SLIPPAGE_COLUMNS`):
- In `conftest._assemble`, after `trades = build_trade_log(portfolio)` and the existing
  `attach_slippage`, attach commission from the closed positions sorted to match the trade-log sort
  (`["entry_date", "exit_date", "side"]` — see `frames.py:62`). A robust approach: build a small frame
  of `(entry_date, exit_date, side, commission)` from `portfolio.closed_positions`
  (`float(p.commission)` at the edge) and merge on the identity keys, OR (simpler, since `build_trade_log`
  already sorts the same way) zip the sorted `closed_positions` commission values onto the sorted trade
  frame. Prefer a key-merge to avoid order-coupling.
- Define `COMMISSION_COLUMN = ["commission"]` local to `conftest.py` (do NOT add to
  `reporting/frames.py` or `reporting/summary.py`).
- Update `_freeze` (L395) to write `trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS + COMMISSION_COLUMN]`,
  `_roundtrip` (L451) and `_diff` (L451) to round-trip the same extended column list. The `commission`
  column is a float column → covered by the existing `FLOAT_FORMAT` + auto-numeric diff (`_diff_frame`).
- **Always-on (D-08):** the column is written for EVERY leaf (`commission = 0.00` when `exchange=None`).

**Oracle-dark proof (verified):** `scripts/run_backtest.py:125` writes
`trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS]` — no commission. `test_backtest_oracle.py` reads
`output/trades.csv` and auto-locks `_trade_numeric = [c for c in golden.columns if c not in identity]`
— since the oracle golden header never gains a `commission` column, the oracle stays byte-exact. The
commission column lives ONLY inside `tests/e2e/conftest.py`.

### Pattern 3: The `ScriptedEmitter.sltp_policy` extension (one kwarg)

**What:** Add an `sltp_policy` constructor parameter to `ScriptedEmitter`.
**Key finding — the plumbing already exists:**
- `BaseStrategyConfig.sltp_policy: SLTPPolicy | None = None` (`config.py:55`)
- `Strategy.sltp_policy = config.sltp_policy` (`base.py:67`)
- `strategies_handler` sets `SignalEvent(..., sltp_policy=strategy.sltp_policy)` (`strategies_handler.py:165`)

So the ONLY emitter change is:
```python
def __init__(self, timeframe, tickers, *, script,
             order_type=OrderType.MARKET,
             direction=TradingDirection.LONG_ONLY,
             sizing_policy=None,
             sltp_policy=None):                         # ← NEW
    ...
    config = BaseStrategyConfig(
        timeframe=timeframe, tickers=list(tickers),
        sizing_policy=sizing_policy, direction=direction,
        allow_increase=False, order_type=order_type,
        sltp_policy=sltp_policy,                        # ← NEW
    )
```
Type the kwarg `SLTPPolicy | None` (import is already in `core/sizing`).

**Declarable stop for RiskPercent (D-12/D-13):** the emitter ALREADY supports a declarable stop — the
per-bar script's `"sl"` key flows through `buy()`/`sell()` (`base.py:131-165`) into
`SignalIntent.stop_loss` → `SignalEvent.stop_loss`. So SIZE-02 declares its stop as a script `"sl"`
level (a decision-time explicit stop) OR via a `PercentFromDecision` `sltp_policy` whose SL is priced at
assembly. **Do NOT use `PercentFromFill` for SIZE-02** — its stop is unknown at resolve time, so
`SizingResolver.resolve_entry` would receive `stop=None` and raise `SizingPolicyViolation`
(`sizing_resolver.py:118-122`). **VERIFIED wiring:** `OrderManager._resolve_signal_quantity` calls
`resolve_entry(signal.sizing_policy, portfolio_id, price, stop=signal_event.stop_loss or None)`
(`order_manager.py:1037-1042`). Because `strategies_handler.py:142` sets `stop_loss = Decimal("0")` when
no `"sl"` is declared, and `Decimal("0") or None` evaluates to `None`, SIZE-02's script MUST declare an
explicit non-zero `"sl"` distinct from the decision price — that is the clean, hand-derivable choice.

### Pattern 4: SLTP-03 outcome authoring (the 2×3 matrix)

**What:** Each SLTP leaf authors bars that drive exactly one of {SL-hit, TP-hit, held-to-end}.
- **SL-hit:** a later bar's low/gap reaches the SL stop → exit at the SL level (STOP child triggers).
- **TP-hit:** a later bar's high/gap reaches the TP limit → exit at the TP level (LIMIT child triggers,
  observable exactly as `oco_lifecycle` shows: `avg_sold = TP level`).
- **Held-to-end:** no bar reaches either level → the position stays OPEN at run end → NO closed trade
  row (`trades.csv` empty / no round-trip), `summary.json` shows `trade_count = 0` and a non-flat
  `final_equity` from the open position mark. Use `orders.csv` opt-in to show both SL+TP children
  PENDING if order state is the assertion (mirrors `never_fill`'s PENDING-not-ACTIVE pattern,
  `orders.py:90`).

`PercentFromDecision` prices children at `signal.price` (decision-bar close) via `_bracket_levels`
(`order_manager.py:615-622`, `727-741`). `PercentFromFill` prices children at the ACTUAL fill price in
`on_fill` via `_create_fill_anchored_children` (`order_manager.py:743`). Because the next-bar-open fill
price differs from the decision close, the Decision and Fill leaves produce DIFFERENT SL/TP levels for
the same percentages — the VERIFY note must hand-derive each anchor explicitly.

### Anti-Patterns to Avoid

- **Adding `commission` to `reporting/frames.py::TRADE_COLUMNS` or `scripts/run_backtest.py`** — breaks
  the BTCUSD oracle (the column would enter `output/trades.csv` and the auto-locked `_trade_numeric`
  diff). The column lives ONLY in `tests/e2e/conftest.py`.
- **Authoring a COST-04 linear-slippage leaf with `base_slippage_pct > 0`** — the base noise draws RNG
  (`linear_slippage_model.py:85`), making the fill non-hand-derivable. Set `base_slippage_pct=0`.
- **Authoring a COST-03 fixed-slippage leaf with `random_variation=True`** — draws RNG jitter
  (`fixed_slippage_model.py:79-82`). Set `random_variation=False` for the deterministic directional rate.
- **Using `PercentFromFill` for SIZE-02 (RiskPercent)** — circular: stop unknown at resolve →
  `SizingPolicyViolation`.
- **Renaming `ScenarioSpec` fields** (`exchange`, `actions`, `strategies`, `portfolios`, `ticker`,
  `starting_cash`, `data`) — the harness reads them by name (`scenario_spec.py:7`).
- **`--freeze` with >1 selected test** — the harness mechanically REFUSES it (`conftest.py:494-500`).
  Freeze one hand-verified leaf at a time.
- **Using a ticker other than the one in `spec.ticker` / portfolio universe** — any unsupported ticker
  silently REFUSES every order (Phase 6 Pitfall 1; the simulated exchange's `supported_symbols`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cost visibility per trade | A recomputed fee column or cost-ledger serializer | Real `Position.commission` appended in `_assemble` (D-07) | The engine already accumulates commission FillEvent→Transaction→Position; recomputing risks drift |
| REJECTED audit for SIZE-03 | A new rejection serializer | Opt-in `build_orders_snapshot` (D-15) | Already serializes `status.name` → REJECTED; Phase 6 mechanism |
| Exchange config injection | Threading `ExchangeConfig` through the composition root | Post-construction `config=...` + `_init_*` re-init (D-14) | Production change for a test-only need; deferred |
| Per-policy strategy classes | ~10 bespoke emitter subclasses | One parametrized `ScriptedEmitter` (D-01/D-12) | One hand-verifiable mechanism; sltp_policy is a kwarg |
| Diff / freeze machinery | Per-leaf assert logic | `run_scenario` harness (D-08 exact diff, `--freeze`) | Single shared no-tolerance lock |

**Key insight:** Every Phase 7 deliverable except the three thin scaffolding changes is a DATA artifact
(contrived bars + a script + a VERIFY note + frozen goldens). The engine is the system under test; the
phase adds coverage, not capability.

## Common Pitfalls

### Pitfall 1: Slippage RNG defeats hand-derivability (COST-03 / COST-04)
**What goes wrong:** A fixed-slippage leaf with `random_variation=True`, or a linear-slippage leaf with
`base_slippage_pct>0`, produces a seeded-but-non-obvious fill price; the VERIFY per-cent math won't match
the frozen golden, or appears to "match" only because the seed happened to land.
**Why it happens:** `FixedSlippageModel` (`fixed_slippage_model.py:79-82`) and `LinearSlippageModel`
(`linear_slippage_model.py:85`) both draw `self._rng.uniform(...)`. The `high_fee` preset's
`FixedSlippageModel` defaults `random_variation=True`.
**How to avoid:** COST-03 → `SlippageModelConfig(model_type=FIXED, slippage_pct=..., random_variation=False)`.
COST-04 → `SlippageModelConfig(model_type=LINEAR, base_slippage_pct=Decimal("0"), size_impact_factor=...,
max_slippage_pct=...)` so `noise = uniform(-0,0) = 0` and only the deterministic `size_impact` remains.
**Warning signs:** A VERIFY note that can't derive the exact fill from price × a clean factor; a golden
fill price with many trailing digits unexplained by the model formula.

### Pitfall 2: The always-on commission column forces a full E2E re-freeze (15 goldens)
**What goes wrong:** Turning the commission column ON (D-08 always-on) changes the trade-log schema for
EVERY existing E2E leaf (14 matching + 1 smoke = 15 `trades.csv` goldens). If not re-frozen, all 15 E2E
tests fail on column-count drift.
**Why it happens:** `_diff` round-trips `TRADE_COLUMNS + SLIPPAGE_COLUMNS + COMMISSION_COLUMN`; the old
goldens lack the column.
**How to avoid:** Plan 1 must re-freeze all 15 goldens with `commission = 0.00`. Because `--freeze`
refuses >1 selected test (`conftest.py:494`), each is a separate single-scenario freeze (15 freeze
commands). This is mechanical (additive schema, value 0.00 — not a behavior change) but must be an
explicit, enumerated task list in Plan 1.
**Warning signs:** A green Plan 1 that only froze the canary — the other 14 + smoke will be red.

### Pitfall 3: SIZE-02 RiskPercent with no decision-time stop → SizingPolicyViolation → REJECTED (not a trade)
**What goes wrong:** Authoring SIZE-02 without a script `"sl"` (or a `PercentFromDecision` policy) makes
`resolve_entry` receive `stop=None` and raise `SizingPolicyViolation` → audited REJECTED → no trade row.
**Why it happens:** `sizing_resolver.py:118-122` raises when `stop is None or stop == price`.
**How to avoid:** SIZE-02's emitter script MUST declare an explicit `"sl"` distinct from the decision
price (D-13). Confirm `OrderManager` passes `signal.stop_loss` into `resolve_entry(stop=...)`.
**Warning signs:** SIZE-02 produces an orders.csv REJECTED instead of a closed trade.

### Pitfall 4: Held-to-end SLTP leaf has no closed trade — assert via summary/orders, not trades
**What goes wrong:** A held-to-end leaf freezes only `trades.csv` and finds it empty → no assertion of
the open position.
**Why it happens:** `build_trade_log` reads `closed_positions` only; an open position never appears.
**How to avoid:** For held-to-end leaves, assert via `summary.json` (`trade_count=0`, `final_equity`
reflecting the open mark) and/or the opt-in `orders.csv` (SL+TP children PENDING).
**Warning signs:** A held-to-end golden with an empty trades.csv and no other frozen artifact.

### Pitfall 5: pytest `filterwarnings=["error"]` + strict markers
**What goes wrong:** Any unexpected warning (e.g. a Pydantic v1 `@validator`, a pandas deprecation) fails
the suite; an undeclared marker fails collection.
**Why it happens:** `pyproject.toml` sets `filterwarnings=["error", ...]`, `--strict-markers`,
`--strict-config` (only `unit`/`integration`/`slow` declared, folder-derived).
**How to avoid:** Use Pydantic v2 decorators only; keep new test files under `tests/e2e/` (no manual
markers needed); avoid deprecated pandas idioms.
**Warning signs:** Collection errors mentioning unknown markers, or test failures with a `Warning`
traceback.

### Pitfall 6: Decimal string-path literals in scripts/policies
**What goes wrong:** `Decimal(0.001)` (float path) carries a binary-repr artifact and breaks byte-exact
goldens; `Decimal("0.001")` (string path) is exact.
**Why it happens:** Money is Decimal end-to-end; `to_money` uses `Decimal(str(x))`. Policy types enforce
the string path (`sizing.py:28-29`).
**How to avoid:** Every fee_rate, slippage_pct, sl/tp level, and risk_pct in a scenario/config MUST use
`Decimal("...")`.
**Warning signs:** A golden number with unexpected trailing digits (e.g. `0.0010000000000000002`).

## Code Examples

### A COST leaf scenario.py (clone of `matching/entries/market_next_open` + an ExchangeConfig)
```python
# Source: tests/e2e/matching/brackets/oco_lifecycle/scenario.py (template)
#         + itrader/config/exchange.py (ExchangeConfig shape)
import pathlib
from decimal import Decimal

from itrader.config import ExchangeConfig, FeeModelConfig
from itrader.config.exchange import FeeModelType, SlippageModelType, SlippageModelConfig
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent
_TICKER, _TIMEFRAME, _CASH = "BTCUSD", "1d", 10_000
_SCRIPT = {"2020-01-02": {"side": "BUY"}, "2020-01-04": {"side": "SELL"}}

# COST-01: percent fee, round-trip. String-path Decimals (Pitfall 6).
_EXCHANGE = ExchangeConfig(
    exchange_name="cost01_pf",
    fee_model=FeeModelConfig(model_type=FeeModelType.PERCENT, fee_rate=Decimal("0.001")),
    slippage_model=SlippageModelConfig(model_type=SlippageModelType.NONE),
)

SCENARIO = ScenarioSpec(
    start="2020-01-01", end="2020-01-06", timeframe=_TIMEFRAME,
    ticker=_TICKER, starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(user_id=1, name="cost01_pf", cash=_CASH)],
    exchange=_EXCHANGE,   # D-14 seam now applies it (foundational fix).
)
```

### COST-04 linear slippage — noise zeroed for hand-derivability
```python
# Source: itrader/execution_handler/slippage_model/linear_slippage_model.py:85-94
# base_slippage_pct=0 => noise = uniform(-0,0) = 0 => only deterministic size_impact.
SlippageModelConfig(
    model_type=SlippageModelType.LINEAR,
    base_slippage_pct=Decimal("0"),        # zero RNG noise
    size_impact_factor=Decimal("0.00001"), # deterministic linear term
    max_slippage_pct=Decimal("0.1"),
)
```

### SIZE-02 RiskPercent with a decision-time stop (D-13)
```python
# Source: itrader/order_handler/sizing_resolver.py:115-124 (stop-distance math)
from itrader.core.sizing import RiskPercent
_SCRIPT = {"2020-01-02": {"side": "BUY", "sl": Decimal("100")}}  # explicit decision-time stop
ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                sizing_policy=RiskPercent(risk_pct=Decimal("0.02")))
# qty = (total_equity * 0.02) / |decision_price - 100|  — hand-derivable from the bars.
```

### SLTP-02 PercentFromFill (anchored to the fill)
```python
# Source: itrader/order_handler/order_manager.py:623-636 + 743 (_create_fill_anchored_children)
from itrader.core.sizing import PercentFromFill
_SCRIPT = {"2020-01-02": {"side": "BUY"}}   # NO explicit sl/tp → policy consulted
ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                sltp_policy=PercentFromFill(sl_pct=Decimal("0.10"), tp_pct=Decimal("0.10")))
# SL/TP priced at the ACTUAL next-bar-open fill, not the decision close.
```

## Runtime State Inventory

This is a test-authoring phase with **no runtime/stored state to migrate** — every change is code or
committed-golden data inside the repo.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified: scenarios run in-memory; harness reads portfolio state AFTER `run()` (`conftest.py:283`), no datastore writes | None |
| Live service config | None — verified: contrived `CsvPriceStore` only; no n8n/Datadog/external service | None |
| OS-registered state | None — verified: pytest-only; no scheduled tasks / daemons | None |
| Secrets/env vars | None — verified: no `.env` keys touched; scenarios pin `cash`/config inline | None |
| Build artifacts | None new — but the always-on commission column re-freezes **15 committed E2E `trades.csv` goldens** (14 `tests/e2e/matching/**/golden/trades.csv` + 1 `tests/e2e/smoke/single_market_buy/golden/trades.csv`). These are committed data artifacts, not build artifacts. | Re-freeze each with `commission=0.00` (Plan 1, one `--freeze` per leaf) |

**The canonical question:** After the commission column + D-14 seam fix land, what regression-locked
artifacts still carry the OLD schema? Answer: the 15 existing E2E `trades.csv` goldens (need the additive
`commission=0.00` re-freeze) and nothing else. The BTCUSD oracle golden (`tests/golden/trades.csv`) does
NOT change — it's written by `scripts/run_backtest.py` with `TRADE_COLUMNS + SLIPPAGE_COLUMNS` only
(no commission), verified oracle-dark.

## Project Constraints (from CLAUDE.md)

- **Money is Decimal end-to-end** — `float()` only at serialization/logging edges. Every scenario
  literal (fee_rate, slippage_pct, sl/tp, risk_pct) uses `Decimal("...")` string path; `commission`
  column narrows to `float` only at the CSV edge.
- **Determinism** — seeded RNG (`performance.rng_seed=42`) is injected into slippage models. For
  hand-derivable cost leaves, ZERO the RNG paths (Pitfall 1) so the result is independent of the seed.
- **Indentation** — `tests/e2e/conftest.py`, `scenario_spec.py`, `scripted_emitter.py`,
  `itrader/config/`, `itrader/reporting/` all use **4 spaces** (the modules this phase edits). Handler
  modules under `itrader/order_handler/`, `execution_handler/`, `portfolio_handler/` use **tabs** — but
  this phase should NOT need to edit them. Match the file.
- **pytest strictness** — `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`. Only
  `unit`/`integration`/`slow` markers (folder-derived). New leaves live under `tests/e2e/` — no manual
  markers.
- **Queue-only cross-domain** — the harness reads portfolio + order-mirror AFTER `run()` (read-model);
  no mid-run cross-handler calls (the `on_tick` operator seam is the only sanctioned mid-run actor and is
  NOT needed for Phase 7's cost/sizing/SLTP leaves).
- **GSD workflow enforcement** — edits go through a GSD command (this is `plan-phase` → `execute-phase`).

## State of the Art

Not applicable — no fast-moving external ecosystem. The engine machinery is internal and stable; this
phase is pure coverage. No deprecated approaches to flag.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A2 | Re-freezing the 15 existing E2E goldens with `commission=0.00` is purely additive (no other value changes) | Pitfall 2 / Runtime State | If any existing leaf's `final_cash`/PnL is implicitly affected, the re-freeze is not purely mechanical. Risk is LOW: existing leaves use `exchange=None` (zero fee), so commission is genuinely 0.00 and no other column changes. [ASSUMED — verified zero-fee via D-14 None-path, not re-run] |

**Note:** All other claims in this research are VERIFIED against the cited live code or CITED from the
in-repo files. A1 (the RiskPercent stop-threading call site) was VERIFIED during this session
(`order_manager.py:1037-1042`) and removed from this log. A2 (zero-fee re-freeze purity) is the only
remaining item needing implementer confirmation — LOW risk.

## Open Questions (RESOLVED)

> Both questions below carry concrete recommendations that are encoded directly into
> 07-01 Task 1's action (key-merge attach; `commission` placed last after
> `SLIPPAGE_COLUMNS`). No execution-blocking ambiguity remains.

1. **Exact commission-attach mechanic (merge vs zip).** RESOLVED — key-merge.
   - What we know: `build_trade_log` and `closed_positions` both sort by `(entry_date, exit_date, side)`;
     `attach_slippage` is the append precedent.
   - What's unclear: whether a positional zip is safe or a key-merge is required (duplicate
     entry/exit/side keys across multiple closed positions in one leaf are possible but rare in
     one-shape leaves).
   - Recommendation: use a key-merge on `(entry_date, exit_date, side)` to be order-independent and
     robust; it's a few lines and removes the coupling risk.

2. **Where `commission` sits relative to `slippage_*` in the golden header.**
   - What we know: D-08 says "after `TRADE_COLUMNS`"; the existing append puts `SLIPPAGE_COLUMNS` after
     `TRADE_COLUMNS`.
   - Recommendation: place `commission` LAST (`TRADE_COLUMNS + SLIPPAGE_COLUMNS + ["commission"]`) — the
     diff is column-name based (`check_like=True`), so position is cosmetic, but last keeps the existing
     slippage columns stable in committed goldens.

## Environment Availability

No external tools/services required — pure in-repo pytest + Poetry (already installed). Skipping the
dependency probe table per the skip condition (code/test-only changes).

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | running scenarios | ✓ (Poetry-locked) | ^8.4.2 | — |
| pandas | golden serialization/diff | ✓ | ^2.3.3 | — |

**Missing dependencies:** none.

## Validation Architecture

> `workflow.nyquist_validation: true` — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (Poetry) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error"]`, strict markers/config) |
| Quick run command | `poetry run pytest tests/e2e/cost/<leaf> -x` (single leaf) |
| Full suite command | `poetry run pytest tests/e2e -x` (all E2E) + `make test` (full) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COST-01 | percent fee round-trip | e2e golden | `poetry run pytest tests/e2e/cost/percent_fee -x` | ❌ Wave (COST) |
| COST-02 | maker vs taker (limit/market) | e2e golden | `poetry run pytest tests/e2e/cost/maker_taker -x` | ❌ Wave (COST) |
| COST-03 | fixed slippage | e2e golden | `poetry run pytest tests/e2e/cost/fixed_slippage -x` | ❌ Wave (COST) |
| COST-04 | linear slippage | e2e golden | `poetry run pytest tests/e2e/cost/linear_slippage -x` | ❌ Wave (COST) |
| COST-05 | slippage not on limit | e2e golden | `poetry run pytest tests/e2e/cost/limit_no_slip -x` | ❌ Wave (COST) |
| COST-06 | combined fee+slippage to the cent | e2e golden | `poetry run pytest tests/e2e/cost/combined_roundtrip -x` | ❌ Wave (COST) |
| SIZE-01 | FixedQuantity | e2e golden | `poetry run pytest tests/e2e/sizing/fixed_quantity -x` | ❌ Wave (SIZE) |
| SIZE-02 | RiskPercent off stop distance | e2e golden | `poetry run pytest tests/e2e/sizing/risk_percent -x` | ❌ Wave (SIZE) |
| SIZE-03 | over-cash REJECTED (orders snapshot) | e2e golden | `poetry run pytest tests/e2e/sizing/over_cash_reject -x` | ❌ Wave (SIZE) |
| SLTP-01 | PercentFromDecision | e2e golden (×3 outcomes) | `poetry run pytest tests/e2e/sltp/from_decision_* -x` | ❌ Wave (SLTP) |
| SLTP-02 | PercentFromFill | e2e golden (×3 outcomes) | `poetry run pytest tests/e2e/sltp/from_fill_* -x` | ❌ Wave (SLTP) |
| SLTP-03 | SL-hit / TP-hit / held-to-end | e2e golden (the ×3 columns of the 2×3 matrix) | covered by the 6 SLTP leaves above | ❌ Wave (SLTP) |
| (gate) | BTCUSD oracle stays byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| (gate) | all 15 existing E2E goldens re-frozen | e2e | `poetry run pytest tests/e2e/matching tests/e2e/smoke -x` | ✅ exists |

### Sampling Rate
- **Per task commit:** the single-leaf quick run (`poetry run pytest tests/e2e/<sub>/<leaf> -x`).
- **Per wave merge:** all leaves in the cluster + the BTCUSD oracle (`poetry run pytest tests/e2e/cost
  tests/integration/test_backtest_oracle.py -x`).
- **Phase gate:** `make test` green (full suite, including the 274 component tests + the oracle gate)
  before `/gsd:verify-work`.

### Wave 0 Gaps (foundational Plan 1)
- [ ] `tests/e2e/conftest.py` — add the always-on `commission` column to `_assemble`/`_freeze`/`_diff`/
      `_roundtrip` (D-07/D-08).
- [ ] `tests/e2e/strategies/scripted_emitter.py` — add the `sltp_policy` constructor kwarg (D-12).
- [ ] `tests/e2e/conftest.py` `_build_and_run` L246-254 — replace the broken `update_config(**model_dump())`
      block with the D-14 `config=...` + `_init_*` re-init.
- [ ] ONE canary leaf (e.g. `tests/e2e/cost/percent_fee/`) proving commission + seam end-to-end,
      hand-verified + frozen.
- [ ] Re-freeze the 15 existing E2E `trades.csv` goldens with `commission=0.00` (one `--freeze` each).
- [ ] Re-run `tests/integration/test_backtest_oracle.py` — confirm byte-exact (oracle-dark).

*(No framework install needed — pytest infra already exists.)*

## Security Domain

> `security_enforcement` absent in `.planning/config.json` → treated as enabled. This is a test-authoring
> phase with NO authentication, session, network, crypto, or external input surface — the only "inputs"
> are committed contrived CSVs authored by the developer. No ASVS category materially applies.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a — no auth surface |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | minimal | Contrived CSV inputs are developer-authored; the engine already validates via `validate_inputs` in fee/slippage models and `SizingPolicyViolation`/`InsufficientFundsError` audit paths |
| V6 Cryptography | no | n/a — money is Decimal arithmetic, no crypto |

**Known threat patterns:** none new. The one correctness-adjacent risk is **slopsquat-style golden
corruption** — a blindly-frozen wrong golden masquerading as correct. Mitigated by the existing E2E
discipline: `--freeze` refuses multi-scenario sweeps (`conftest.py:494`), each leaf carries a
HAND-VERIFIED VERIFY note before freeze, and the diff is exact no-tolerance.

## Sources

### Primary (HIGH confidence — read in this session)
- `tests/e2e/conftest.py` (full) — `run_scenario`, `_build_and_run` (broken D-14 block L246-254),
  `_assemble`, `_freeze`/`_diff`/`_roundtrip`, `--freeze` refusal L494.
- `itrader/execution_handler/exchanges/simulated.py` — `_emit_fill` L175-229 (is_maker L202, COST-05
  limit-no-slip L206-208), `_init_fee_model`/`_init_slippage_model` L482-520, `update_config` L539-588,
  `__init__` L38-103.
- `itrader/config/exchange.py` — `ExchangeConfig`/`FeeModelConfig`/`SlippageModelConfig` shape, presets,
  `to_kwargs` double-prefix quirk L88.
- `itrader/execution_handler/fee_model/{percent,maker_taker}_fee_model.py` — fee math.
- `itrader/execution_handler/slippage_model/{fixed,linear}_slippage_model.py` — RNG noise paths
  (the COST-03/04 determinism trap).
- `itrader/order_handler/sizing_resolver.py` — RiskPercent stop-distance L115-124, SizingPolicyViolation.
- `itrader/order_handler/order_manager.py` — `_assemble_bracket_and_emit` L556-725 (SLTP dispatch
  L613-638, `_bracket_levels` L727-741), `_create_fill_anchored_children` L743, SIZE-03 REJECTED path
  L393-414.
- `itrader/core/sizing.py` — policy vocabulary (FixedQuantity/RiskPercent/PercentFromDecision/FromFill/
  SignalIntent).
- `itrader/portfolio_handler/position/position.py` — `commission` L131-136, `buy/sell_commission`
  L41-58, `to_dict` L256-278 (no commission key).
- `itrader/reporting/{frames,summary,orders}.py` — `TRADE_COLUMNS` (restricts), `attach_slippage` append
  precedent, `build_orders_snapshot` (REJECTED via `status.name`).
- `itrader/strategy_handler/{config,base,strategies_handler}.py` — `sltp_policy` already plumbed end-to-end.
- `tests/integration/test_backtest_oracle.py` + `scripts/run_backtest.py:125` — oracle reads
  `output/trades.csv` with `TRADE_COLUMNS + SLIPPAGE_COLUMNS` (no commission) → oracle-dark confirmed.
- `tests/e2e/matching/brackets/oco_lifecycle/scenario.py` + `tests/e2e/smoke/single_market_buy/{scenario,
  test_scenario,bars.csv}` — leaf copy-template + VERIFY-note format.
- `.planning/REQUIREMENTS.md` L53-68 (COST/SIZE/SLTP), `.planning/config.json` (nyquist on).

### Secondary / Tertiary
- None — all findings are from in-repo code (HIGH). No WebSearch/Context7 needed for an internal
  coverage phase.

## Metadata

**Confidence breakdown:**
- Standard stack (in-repo infra): HIGH — every reused component read and confirmed in this session.
- Architecture / seams (D-07/D-12/D-14): HIGH — exact line numbers and current signatures verified;
  the D-14 break reproduced by reading `update_config` + `model_dump` shape.
- Pitfalls (slippage RNG, re-freeze scope, RiskPercent stop): HIGH — sourced to exact model code.
- Two ASSUMED items (A1 stop-threading call site, A2 zero-fee re-freeze purity): MEDIUM — flagged for
  implementer confirmation; both LOW risk.

**Research date:** 2026-06-10
**Valid until:** stable (internal coverage phase; valid until the cost/sizing/SLTP engine or the E2E
harness is refactored — re-verify if `conftest.py`, `simulated.py`, or `sizing_resolver.py` change).
