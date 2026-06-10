# Phase 7: Cost, Sizing & SLTP Scenarios - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 4 scaffolding seams (Group A) + 1 canonical leaf template (Group B, cloned ~15×)
**Analogs found:** 5 / 5 (all exact / role-match, verified against live code)

This is a COVERAGE/test-authoring phase. The engine is the system under test; no
`itrader/` source is built. All NEW code is test scaffolding (3 seams in Plan 1) +
~15 DATA leaves (contrived `bars.csv` + `scenario.py` VERIFY note + `test_scenario.py`
+ frozen `golden/`). Every analog below is verified against live code with file:line.

**Indentation law (verified):** every file this phase edits uses **4 spaces** —
`tests/e2e/conftest.py`, `tests/e2e/scenario_spec.py`,
`tests/e2e/strategies/scripted_emitter.py`, `tests/e2e/**/scenario.py`. The engine
files cited as SOURCES (`simulated.py`, `position.py`, `execution_handler.py`) use
**tabs** but this phase only READS them — do not edit them. Match the file.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/e2e/conftest.py` — commission column (D-07/D-08) | test-harness (serialization) | transform / file-I/O | `attach_slippage` + `SLIPPAGE_COLUMNS` append in `itrader/reporting/summary.py` | exact (same append precedent) |
| `tests/e2e/conftest.py` — exchange-seam fix (D-14) | test-harness (wiring) | config | `SimulatedExchange.__init__` L70-74 + `_init_fee_model`/`_init_slippage_model` | exact (re-runs the constructor's own path) |
| `tests/e2e/strategies/scripted_emitter.py` — `sltp_policy` kwarg (D-12) | test-fixture (strategy) | event-driven | existing `sizing_policy` kwarg in same file | exact (identical kwarg→config→SignalEvent thread) |
| `tests/e2e/{cost,sizing,sltp}/<leaf>/scenario.py` (~15) | test-data (scenario spec) | request-response (fill path) | `tests/e2e/matching/brackets/oco_lifecycle/scenario.py` | exact (canonical Phase 6 leaf shape) |
| `tests/e2e/{cost,sizing,sltp}/<leaf>/test_scenario.py` (~15) | test (one-liner) | — | `tests/e2e/matching/brackets/oco_lifecycle/test_scenario.py` | exact |

---

## Pattern Assignments

### Group A — Plan 1 shared scaffolding (3 distinct analogs)

---

### A1. `commission` golden column (D-07/D-08) — `tests/e2e/conftest.py`

**Role:** test-harness serialization. **Data flow:** transform → CSV file-I/O.
**Analog:** `itrader/reporting/summary.py` `SLIPPAGE_COLUMNS` + `attach_slippage`
(the exact append-after-`TRADE_COLUMNS` precedent, D-17).

**Append-constant precedent** (`summary.py:37-39`):
```python
# D-17 slippage-attribution columns appended to the serialized trade log (after
# the relocated TRADE_COLUMNS) — float columns, so the FLOAT_FORMAT pin applies.
SLIPPAGE_COLUMNS = ["slippage_entry", "slippage_exit"]
```
→ Mirror with a conftest-LOCAL constant (do NOT add to `reporting/`):
`COMMISSION_COLUMN = ["commission"]` defined in `tests/e2e/conftest.py`.

**Where the existing append is wired in `conftest.py`** — four touch-points, all
already handling `SLIPPAGE_COLUMNS`; the commission column copies each:

1. `_assemble` (`conftest.py:298-299`) — slippage attached AFTER `build_trade_log`:
   ```python
   # D-17: post-hoc slippage attribution from the store's close series.
   closes = system.store.read_bars(spec.ticker)["close"]
   trades = attach_slippage(trades, closes)
   ```
   Add the commission attach right after this. Source is `portfolio.closed_positions`
   (verified read-model: `portfolio.py:265-267`). `build_trade_log` sorts by
   `["entry_date", "exit_date", "side"]` (`frames.py:62`) — use a **key-merge** on
   `(entry_date, exit_date, side)` (Open Q1 in RESEARCH; order-independent) rather
   than a positional zip. `Position.commission` is `buy_commission + sell_commission`
   (`position.py:131-136`); narrow `float(p.commission)` at the CSV edge only.

2. `_freeze` (`conftest.py:395`) — currently:
   ```python
   trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS].to_csv(
       golden_dir / "trades.csv", index=False, float_format=FLOAT_FORMAT
   )
   ```
   → `trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS + COMMISSION_COLUMN]`.

3. `_diff` (`conftest.py:451`) — currently:
   ```python
   fresh = _roundtrip(trades, TRADE_COLUMNS + SLIPPAGE_COLUMNS)
   ```
   → `_roundtrip(trades, TRADE_COLUMNS + SLIPPAGE_COLUMNS + COMMISSION_COLUMN)`.

4. `_roundtrip` (`conftest.py:415-431`) needs no change — it takes `columns` as a
   param; only its callers (`_freeze`, `_diff`) change.

**Why the column CANNOT ride `build_trade_log`** (verified): `build_trade_log`
(`frames.py:59-61`) does `pd.DataFrame(rows, columns=TRADE_COLUMNS)` — it RESTRICTS to
`TRADE_COLUMNS`, and `Position.to_dict()` does not even emit a `commission` key. The
column MUST be attached separately in `_assemble`, exactly like `attach_slippage`.

**Diff coverage is automatic:** `commission` is a numeric column not in
`_TRADE_IDENTITY_COLUMNS` → `_diff_frame` (`conftest.py:347-354`) auto-derives it into
the numeric remainder and compares EXACT with `FLOAT_FORMAT`. No diff-logic change.

**Always-on (D-08):** the column is written for EVERY leaf, including `exchange=None`
leaves → `commission = 0.00`. This forces the **15-golden re-freeze** (Pitfall 2): 14
`tests/e2e/matching/**/golden/trades.csv` + 1 `tests/e2e/smoke/single_market_buy/golden/trades.csv`.
`--freeze` refuses >1 selected test (`conftest.py:494-500`) → 15 separate single-leaf
freeze commands, enumerated in Plan 1.

**Oracle-dark proof (verified):** `scripts/run_backtest.py:125` writes
`TRADE_COLUMNS + SLIPPAGE_COLUMNS` (no commission); `test_backtest_oracle.py`
auto-locks numeric columns from the golden header, which never gains `commission`.
The column lives ONLY in `tests/e2e/conftest.py`. Do NOT add it to
`reporting/frames.py::TRADE_COLUMNS` or `scripts/run_backtest.py`.

---

### A2. Exchange-config seam fix (D-14) — `tests/e2e/conftest.py:246-254`

**Role:** test-harness wiring. **Data flow:** config injection.
**Analog:** `SimulatedExchange.__init__` (`simulated.py:70-74`) — the constructor's
OWN config→models path the fix re-runs.

**Constructor path the fix reuses** (`simulated.py:70-74`):
```python
# Exchange configuration
self.config = config or get_exchange_preset('default')
# Initialize models
self.fee_model = self._init_fee_model()
self.slippage_model = self._init_slippage_model()
```
`_init_fee_model`/`_init_slippage_model` (`simulated.py:482-520`) read
`self.config.fee_model` / `self.config.slippage_model` (the Pydantic submodels) and
build the concrete fee/slippage models.

**Current BROKEN block** (`conftest.py:246-254`):
```python
exchange_config = getattr(spec, "exchange", None)
if exchange_config is not None:
    simulated = system.execution_handler.exchanges["simulated"]
    # Pydantic ExchangeConfig → kwargs for update_config (simulated.py:539).
    if hasattr(exchange_config, "model_dump"):
        fields = exchange_config.model_dump()      # NESTED keys: fee_model={...}, slippage_model={...}
    else:
        fields = dict(exchange_config)
    simulated.update_config(**fields)              # BROKEN: silent no-op (nested vs flat)
```
Why broken (verified): `model_dump()` yields nested `fee_model`/`slippage_model`
dicts; `update_config` recognizes only FLAT keys (`fee_model_type`, `fee_rate`,
`base_slippage_pct`, …). The nested keys `setattr` a raw dict over the Pydantic
submodel → `_init_fee_model` later reads `self.config.fee_model.model_type` on a dict
→ AttributeError. The `to_kwargs` double-prefix quirk (`slippage_base_slippage_pct`,
`exchange.py:88`) confirms `to_kwargs()` is also not a clean path.

**The fix (D-14 — clone the constructor path):**
```python
exchange_config = getattr(spec, "exchange", None)
if exchange_config is not None:
    simulated = system.execution_handler.exchanges["simulated"]
    # D-14: re-init from the config object exactly as __init__ does (simulated.py:70-74).
    simulated.config = exchange_config
    simulated.fee_model = simulated._init_fee_model()
    simulated.slippage_model = simulated._init_slippage_model()
```

**CRITICAL load-bearing constraint for the planner (verified, NOT in RESEARCH):**
the fix MUST re-run ONLY `_init_fee_model` / `_init_slippage_model`. It must NOT
reassign `simulated._supported_symbols` from the new config. `init_exchanges`
(`execution_handler.py:104-109`) mutates the instance set to ADD `BTCUSD`
post-construction:
```python
simulated._supported_symbols = set(simulated._supported_symbols) | {'BTCUSD'}
```
The default `ExchangeConfig.limits.supported_symbols` is `{"BTCUSDT","ETHUSDT",...}`
— **no `BTCUSD`** (`exchange.py:106-108`). If the seam fix re-ran `simulated.py:98`
(`self._supported_symbols = self.config.limits.supported_symbols`) it would WIPE the
BTCUSD admission and every COST/SIZE/SLTP order would silently REFUSE
(`validate_symbol`, `simulated.py:436-438`). The D-14 fix above does NOT touch
`_supported_symbols`, so BTCUSD admission survives — this is why the fix is exactly
the two model re-inits and nothing more.

**Oracle-dark:** the block is skipped when `spec.exchange is None` → byte-identical to
today → Phase 6 None-exchange leaves + the BTCUSD oracle untouched.

---

### A3. `ScriptedEmitter.sltp_policy` kwarg (D-12) — `tests/e2e/strategies/scripted_emitter.py`

**Role:** test-fixture (strategy). **Data flow:** event-driven (→ SignalEvent).
**Analog:** the EXISTING `sizing_policy` kwarg in the same file — identical
kwarg→`BaseStrategyConfig`→`SignalEvent` thread.

**Existing `sizing_policy` precedent** (`scripted_emitter.py:75-92`):
```python
def __init__(self, timeframe: str, tickers: list[str], *,
             script: dict[str, dict],
             order_type: OrderType = OrderType.MARKET,
             direction: TradingDirection = TradingDirection.LONG_ONLY,
             sizing_policy: SizingPolicy | None = None) -> None:
    if sizing_policy is None:
        sizing_policy = FractionOfCash(Decimal("0.95"))
    config = BaseStrategyConfig(
        timeframe=timeframe,
        tickers=list(tickers),
        sizing_policy=sizing_policy,
        direction=direction,
        allow_increase=False,
        order_type=order_type,
    )
```

**The change (one kwarg, mirroring `sizing_policy`):**
```python
def __init__(self, timeframe: str, tickers: list[str], *,
             script: dict[str, dict],
             order_type: OrderType = OrderType.MARKET,
             direction: TradingDirection = TradingDirection.LONG_ONLY,
             sizing_policy: SizingPolicy | None = None,
             sltp_policy: "SLTPPolicy | None" = None) -> None:   # NEW
    ...
    config = BaseStrategyConfig(
        timeframe=timeframe,
        tickers=list(tickers),
        sizing_policy=sizing_policy,
        direction=direction,
        allow_increase=False,
        order_type=order_type,
        sltp_policy=sltp_policy,                                 # NEW
    )
```
Import `SLTPPolicy` from `itrader.core.sizing` (the existing sizing import line at
`scripted_emitter.py:47`). The downstream plumbing already exists end-to-end
(verified by RESEARCH): `BaseStrategyConfig.sltp_policy` (`config.py:55`) →
`Strategy.sltp_policy` (`base.py:67`) → `strategies_handler` sets
`SignalEvent(..., sltp_policy=strategy.sltp_policy)` (`strategies_handler.py:165`).

**Declarable stop for RiskPercent (D-12/D-13) — already supported, no code change:**
the per-bar script `"sl"` key flows `buy()`/`sell()` → `SignalIntent.stop_loss` →
`SignalEvent.stop_loss` → `resolve_entry(stop=signal.stop_loss or None)`. So SIZE-02
declares an explicit non-zero `"sl"` in its script (distinct from the decision price).
Do NOT use `PercentFromFill` for SIZE-02 (stop unknown at resolve → `SizingPolicyViolation`).

---

### Group B — the ONE canonical leaf template (cloned ~15×)

**Analog (canonical Phase 6 leaf shape):**
`tests/e2e/matching/brackets/oco_lifecycle/` — NOT the older
`tests/e2e/smoke/single_market_buy/` (which inlines its own `ScenarioSpec` dataclass
and uses the legacy `SingleMarketBuy` count-keyed strategy). The oco leaf is the
post-Phase-6 shape: imports `ScenarioSpec`/`PortfolioSpec` from `scenario_spec.py`,
uses `ScriptedEmitter`, freezes the opt-in `orders.csv`.

**Leaf folder shape (verified contents):**
```
<leaf>/
  __init__.py        # empty
  bars.csv           # contrived OHLCV, header: Open time,Open,High,Low,Close,Volume
  scenario.py        # VERIFY docstring + imports + _SCRIPT + SCENARIO = ScenarioSpec(...)
  test_scenario.py   # one-liner: run_scenario(HERE)
  golden/
    trades.csv       # always
    summary.json     # always
    orders.csv       # opt-in (only when order STATE is the assertion, e.g. SIZE-03, held-to-end)
    equity.csv       # opt-in (rarely)
```

**Canonical `scenario.py` skeleton** (from `oco_lifecycle/scenario.py:88-120`):
```python
import pathlib
from decimal import Decimal

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": Decimal("100"), "tp": Decimal("140")},
}

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-05",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(user_id=1, name="match04_pf", cash=_CASH)],
    exchange=None,  # COST/SIZE/SLTP leaves set this to an ExchangeConfig (D-14 applies it).
)
```

**Canonical `test_scenario.py`** (verbatim, `oco_lifecycle/test_scenario.py`):
```python
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_oco_lifecycle(run_scenario):   # rename fn per leaf
    run_scenario(HERE)
```

**Canonical `bars.csv` header** (verified, tz-aware UTC Open time):
```
Open time,Open,High,Low,Close,Volume
2020-01-01 00:00:00+00:00,110.0,115.0,109.0,114.0,1000.0
...
```

**VERIFY-note format** (the `scenario.py` module docstring) — every leaf carries a
hand-derivation between `==== VERIFY ====` / `==== END VERIFY ====` fences:
contrived bars table, engine knobs, decision→fill lifecycle (next-bar-open), the
per-cent sizing/fee/slippage math, and the resulting frozen trade row + final cash.
See `oco_lifecycle/scenario.py:16-87` and `single_market_buy/scenario.py:16-92` for
the two reference formats. For COST leaves the VERIFY note hand-derives the per-cent
fee against the frozen `commission` column + `summary.json` `final_cash` (D-07).

**How each cluster specializes the template** (subject to discretion D-09a/D-10/D-11):

| Cluster | `exchange=` | `sltp_policy=` / `sizing_policy=` | Frozen goldens | Source for the config shape |
|---------|-------------|-----------------------------------|----------------|------------------------------|
| COST-01 percent fee | `ExchangeConfig(fee_model=FeeModelConfig(model_type=PERCENT, fee_rate=Decimal("...")))` | default | trades.csv (+commission), summary.json | `exchange.py:45-67` |
| COST-02 maker/taker | `MAKER_TAKER` w/ maker_rate+taker_rate; script LIMIT entry then MARKET entry (D-11) | default; emitter `order_type=LIMIT` for the maker leg | trades.csv (commission shows 2 rates) | `exchange.py:50-53` |
| COST-03 fixed slippage | `SlippageModelConfig(model_type=FIXED, slippage_pct=Decimal("..."), random_variation=False)` | default | trades.csv (+commission), summary.json | `exchange.py:70-95`; Pitfall 1 |
| COST-04 linear slippage | `SlippageModelConfig(model_type=LINEAR, base_slippage_pct=Decimal("0"), size_impact_factor=Decimal("..."), max_slippage_pct=Decimal("..."))` | default | trades.csv, summary.json | RESEARCH COST-04 example; Pitfall 1 |
| COST-05 limit-no-slip | slippage configured + emitter `order_type=LIMIT` (slippage forced 1 for LIMIT) | default | trades.csv | `simulated.py:206-208` (already enforced) |
| COST-06 combined | fee + slippage both configured | default | trades.csv (+commission), summary.json (`final_cash` to the cent) | both configs |
| SIZE-01 FixedQuantity | None | `sizing_policy=FixedQuantity(qty=Decimal("..."))` | trades.csv, summary.json | `sizing_resolver.py:113-114` |
| SIZE-02 RiskPercent | None | `sizing_policy=RiskPercent(risk_pct=Decimal("..."))` + script `"sl": Decimal("...")` (D-13) | trades.csv, summary.json | `sizing_resolver.py:124` |
| SIZE-03 over-cash reject | None | `sizing_policy=FixedQuantity(qty=<huge>)` (or fraction>cash) | **orders.csv** (REJECTED) | D-15; `build_orders_snapshot` |
| SLTP-01 ×3 (from_decision) | None | `sltp_policy=PercentFromDecision(sl_pct, tp_pct)`; bars drive SL-hit / TP-hit / held-to-end | trades.csv (SL/TP-hit) or orders.csv+summary (held) | `order_manager.py:615-622` |
| SLTP-02 ×3 (from_fill) | None | `sltp_policy=PercentFromFill(sl_pct, tp_pct)`; bars drive the 3 outcomes | trades.csv / orders.csv+summary | `order_manager.py:628,743` |

**Held-to-end leaves (SLTP-03 third column):** no closed trade → assert via
`summary.json` (`trade_count=0`, non-flat `final_equity` from the open mark) AND/OR
the opt-in `orders.csv` showing SL+TP children PENDING (mirrors Phase 6 `never_fill`'s
PENDING-not-ACTIVE pattern). Do NOT freeze only an empty `trades.csv` (Pitfall 4).

---

## Shared Patterns

### Decimal string-path (correctness-critical, all leaves)
**Source:** CLAUDE.md money policy + `itrader/core/sizing.py:28-29`.
**Apply to:** every `fee_rate`, `slippage_pct`, `sl`/`tp`/`stop` level, `risk_pct`, `qty`.
Always `Decimal("0.001")` (string path), NEVER `Decimal(0.001)` (binary-float artifact
breaks byte-exact goldens — Pitfall 6).

### Slippage RNG must be zeroed for hand-derivability (COST-03/COST-04)
**Source:** `fixed_slippage_model.py:79-82`, `linear_slippage_model.py:85`.
**Apply to:** COST-03 → `random_variation=False`; COST-04 → `base_slippage_pct=Decimal("0")`.
Both models draw `self._rng.uniform(...)` otherwise → the per-cent VERIFY math won't
match the frozen golden (Pitfall 1).

### Single-leaf `--freeze` discipline
**Source:** `conftest.py:494-500` (mechanically refuses >1 selected test).
**Apply to:** the canary, all ~15 leaves, AND the 15 re-freezes. One
`poetry run pytest <leaf> --freeze` per hand-verified leaf, committed with its VERIFY note.

### BTCUSD ticker only
**Source:** `execution_handler.py:104-109` (instance set adds only `BTCUSD`).
**Apply to:** every leaf — `spec.ticker = "BTCUSD"`, portfolio universe matches. Any
other ticker silently REFUSES every order (Pitfall, `simulated.py:436-438`). Reinforced
by the D-14 constraint above (the seam fix must not re-derive `_supported_symbols`).

---

## No Analog Found

None. Every Phase 7 file maps to an exact or role-match analog in the existing E2E
harness or `reporting/` append precedent. This phase introduces no new role or data
flow — it is pure coverage over already-shipped engine machinery.

---

## Metadata

**Analog search scope:** `tests/e2e/` (harness, strategies, scenario_spec, smoke,
matching/brackets), `itrader/reporting/` (summary, frames), `itrader/execution_handler/`
(simulated exchange, execution_handler, exchange config), `itrader/portfolio_handler/`
(position, portfolio read-model).
**Files scanned:** 11 (all read or grepped this session; line numbers verified live).
**Key cross-check vs RESEARCH.md:** all RESEARCH line-number claims verified against
live code. One ADDITIONAL load-bearing constraint surfaced that RESEARCH did not call
out: the D-14 fix must NOT reassign `simulated._supported_symbols` (would wipe the
`execution_handler.py:109` BTCUSD admission). Documented in A2.
**Pattern extraction date:** 2026-06-10
