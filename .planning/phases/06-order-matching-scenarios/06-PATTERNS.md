# Phase 6: Order Matching Scenarios - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 6 shared-infra targets + ~13 leaf scenario folders (one template)
**Analogs found:** 6 / 6 (every new file has a strong in-repo analog — this is a coverage phase, not a greenfield one)

> This is a TEST-AUTHORING phase. The "files to create" are (1) four shared-infra pieces committed FIRST in the D-13 foundational plan, and (2) ~12-15 self-contained E2E leaf folders cloned from the Phase 4 canary. Every new file copies a concrete existing analog; this map gives the planner the exact analog + line excerpts to reference.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/e2e/strategies/scripted_emitter.py` | test (strategy fixture) | event-driven (emits SignalIntent) | `tests/e2e/strategies/single_market_buy.py` | exact (generalize) |
| `tests/e2e/scenario_spec.py` (shared `ScenarioSpec`+`PortfolioSpec`+`Action`) — **promotion target** | test (value object) | transform (config dataclass) | per-leaf `ScenarioSpec` in `tests/e2e/smoke/single_market_buy/scenario.py` | exact (promote) |
| `itrader/trading_system/backtest_trading_system.py` — `run()`/`_run_backtest()` `on_tick` param | layer (run loop) | event-driven (per-tick callback) | the existing `_run_backtest` loop (same file) + `print_summary` optional-param pattern in `run()` | exact (extend) |
| `itrader/reporting/orders.py` (or extend `frames.py`) — `build_orders_snapshot` + `ORDER_SNAPSHOT_COLUMNS` | utility (serializer) | transform (entities → DataFrame) | `itrader/reporting/frames.py` `build_trade_log` + `TRADE_COLUMNS` | exact (sibling) |
| `tests/e2e/conftest.py` — `orders.csv` opt-in diff + `actions`→`on_tick` translation | test (harness) | request-response + transform | existing `equity.csv` opt-in branch + `_make_on_tick`-shaped translation in same file | exact (extend) |
| `tests/e2e/matching/<cluster>/<leaf>/{scenario.py, bars.csv, test_scenario.py, golden/}` (~13 leaves) | test (E2E scenario) | request-response (build→run→diff) | `tests/e2e/smoke/single_market_buy/` (whole folder) | exact (clone) |

---

## Pattern Assignments

### `tests/e2e/strategies/scripted_emitter.py` (test, event-driven)

**Analog:** `tests/e2e/strategies/single_market_buy.py` — generalize from bar-COUNT keying to bar-DATE keying (CONTEXT D-01/D-04).

**Imports pattern** (`single_market_buy.py:28-34`) — copy verbatim, this is the import surface the emitter needs:
```python
from decimal import Decimal
import pandas as pd
from itrader.core.sizing import FractionOfCash, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.config import BaseStrategyConfig
```

**Config construction pattern** (`single_market_buy.py:61-67`) — the emitter builds a `BaseStrategyConfig` then passes it to `super().__init__`. For STOP/LIMIT *entry* scenarios (MATCH-02/03) the emitter must add `order_type=OrderType.LIMIT`/`STOP` here (Pitfall 3 — `order_type` is per strategy INSTANCE, not on the intent):
```python
config = BaseStrategyConfig(
    timeframe=timeframe,
    tickers=list(tickers),
    sizing_policy=FractionOfCash(Decimal("0.95")),
    direction=TradingDirection.LONG_ONLY,
    allow_increase=False,
)
super().__init__("single_market_buy", config)
```
> New: import `OrderType` from `itrader.core.enums.order` and add `order_type=order_type` to the config kwargs (default `OrderType.MARKET`). `direction` may need to widen beyond `LONG_ONLY` for SELL-entry scenarios (MATCH-03 SELL STOP) — Claude's discretion.

**Core firing pattern — the thing to GENERALIZE** (`single_market_buy.py:78-83`). Today it keys on `len(bars)`:
```python
def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
    if len(bars) == self.fire_on_bar:
        return self.buy(ticker)
    if len(bars) == self.exit_on_bar:
        return self.sell(ticker)
    return None
```
**Target shape (D-04 — key by the current bar's DATE):** the emitter holds a `dict[str, dict]` script keyed by `"YYYY-MM-DD"`. Inside `generate_signal`, read `bars.index[-1]` (the current/decision bar), `strftime("%Y-%m-%d")`, look it up, and emit `self.buy(ticker, sl=, tp=, exit_fraction=)` / `self.sell(...)` per the scripted action. This sidesteps the `len(bars)`-depends-on-`max_window`/warmup gotcha the canary docstring (`single_market_buy.py:9-26`) had to explain.

**`buy()/sell()` sugar contract** (analog uses it bare; D-15 brackets need sl/tp): `Strategy.buy(ticker, sl=, tp=, exit_fraction=)` lives at `itrader/strategy_handler/base.py:131`; sl/tp go through `to_money`. The emitter passes explicit Decimal `sl`/`tp` for bracket leaves (D-15 — `sltp_policy` ignored when either >0). `exit_fraction` defaults to 1 (full exit).

**`max_window` note** (`single_market_buy.py:71-76`): keep `max_window` wide (e.g. 100) so the window is non-empty; under date-keying it no longer gates firing, but a 0-width window is always empty. Keep `self.max_window = 100` and `warmup = 0`.

---

### `tests/e2e/scenario_spec.py` — shared `ScenarioSpec` + `PortfolioSpec` + new `Action` (test, transform)

**Analog:** the per-leaf dataclasses in `tests/e2e/smoke/single_market_buy/scenario.py:104-138`.

**GAP #4 — structural decision the planner MUST make:** `ScenarioSpec`/`PortfolioSpec` are defined PER-LEAF today (inside each `scenario.py`). RESEARCH recommends PROMOTING them to a shared `tests/e2e/scenario_spec.py` during the D-13 foundational plan (shared infra by nature, committed first, parallel-safe thereafter) so the new `actions` field is defined once, not re-declared in every leaf. Capture BOTH shapes below.

**Current per-leaf shape** (`scenario.py:104-138`) — the dataclasses to promote:
```python
@dataclass(frozen=True)
class PortfolioSpec:
    user_id: int
    name: str
    cash: int


@dataclass(frozen=True)
class ScenarioSpec:
    start: str
    end: str
    timeframe: str
    ticker: str
    starting_cash: int
    data: dict[str, Any]
    strategies: list[Any]
    portfolios: list[PortfolioSpec]
    exchange: Any = None
```
> The harness reads these attributes by name (`conftest.py:158-228`): field names are a consuming contract — do not rename existing ones.

**New `actions` field (D-06)** — add to `ScenarioSpec` with a default so it stays oracle-inert:
```python
    actions: list["Action"] = ()   # default empty = no on_tick wired (oracle-dark)
```

**New `Action` dataclass (D-06/D-07 — Claude's discretion on exact shape).** Frozen, predicate-resolved (names target by ticker+status, never by literal UUID). Recommended shape from RESEARCH Code Examples (`06-RESEARCH.md:310-334`):
```python
@dataclass(frozen=True)
class Action:
    bar_date: str        # "YYYY-MM-DD" — resolved against time_event.time
    kind: str            # "cancel" | "modify"
    ticker: str          # predicate target (D-07)
    new_price: Decimal | None = None
    new_quantity: Decimal | None = None
```

**Module-level `SCENARIO` export** (`scenario.py:145-156`) — every leaf still publishes a `SCENARIO = ScenarioSpec(...)` (the harness reads `module.SCENARIO`, `conftest.py:141`). After promotion, leaves IMPORT `ScenarioSpec`/`PortfolioSpec`/`Action` from the shared module instead of redefining them.

---

### `itrader/trading_system/backtest_trading_system.py` — `on_tick` hook (layer, event-driven)

**Analog (extend in place):** the existing `_run_backtest` loop (`backtest_trading_system.py:192-217`) and the `print_summary` optional-param pattern in `run()` (`:219-232`). Indentation in this file is **TABS** — match it.

**Imports already present** (`backtest_trading_system.py:6`): `from typing import Any, Optional`. `Callable` must be added to that import line.

**Existing loop — the landing site** (`:203-213`):
```python
		for time_event in self.time_generator:
			self.clock.set_time(time_event.time)
			self.global_queue.put(time_event)
			self.event_handler.process_events()
			for portfolio in self.portfolio_handler.get_active_portfolios():
				portfolio.record_metrics(time_event.time)
```

**Existing `run()` — the default-param precedent to mirror** (`:219-232`):
```python
	def run(self, print_summary: bool = True) -> None:
		self._initialise_backtest_session()
		self._run_backtest()
		if print_summary:
			self._print_metrics_summary()
```

**Target (D-06, from `06-RESEARCH.md:285-307`)** — thread an `on_tick: Optional[Callable[["TradingSystem", Any], None]] = None`. Default `None` is byte-exact = oracle-dark (`test_backtest_oracle.py` never passes it). Place the call AFTER `process_events()` + `record_metrics` (post-bar, so a modify/cancel lands before the NEXT bar's matching — Assumption A2):
```python
		if on_tick is not None:                 # default None = byte-exact (oracle-dark)
			on_tick(self, time_event)
```
`run()` gains the same param and forwards it to `_run_backtest(on_tick=on_tick)`.

**Oracle-darkness obligation (D-13 / Wave-0 gap):** the foundational plan MUST re-run `tests/integration/test_backtest_oracle.py` to prove the `on_tick=None` change is byte-exact. `system.order_handler` is already a public attribute (constructed in `__init__`, referenced by the harness operator calls).

---

### `itrader/reporting/orders.py` — `build_orders_snapshot` + `ORDER_SNAPSHOT_COLUMNS` (utility, transform)

**Analog:** `itrader/reporting/frames.py` `build_trade_log` + `TRADE_COLUMNS` (`frames.py:24-63`). Indentation **4 spaces** (reporting package). The snapshot joins this serializer family and MUST use the same `FLOAT_FORMAT` so the round-trip diff is apples-to-apples.

**Column-pin pattern** (`frames.py:24-36`) — mirror this module-level constant style:
```python
TRADE_COLUMNS = [
    "entry_date",
    "exit_date",
    "side",
    ...
    "pair",
]
```

**Builder pattern** (`frames.py:52-63`) — rows-from-entities → DataFrame(columns=...) → deterministic `sort_values().reset_index(drop=True)`; empty-safe:
```python
def build_trade_log(portfolio: Any) -> pd.DataFrame:
    rows = [position.to_dict() for position in portfolio.closed_positions]
    frame = pd.DataFrame(rows, columns=TRADE_COLUMNS) if rows else pd.DataFrame(columns=TRADE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["entry_date", "exit_date", "side"]).reset_index(drop=True)
    return frame
```

**Purity contract to preserve** (`frames.py:11-15`): pandas + stdlib only, parameter stays DUCK-TYPED — NO handler imports. The snapshot builder takes a list of `Order`-shaped objects, not the handler.

**Target shape (D-08, from `06-RESEARCH.md:336-366`)** — business columns only, no UUID, logical ENTRY/SL/TP role derived from linkage flags. Decimal→float at the serialization edge:
```python
ORDER_SNAPSHOT_COLUMNS = [
    "role", "ticker", "order_type", "action", "status",
    "price", "quantity", "filled_quantity", "time",
]

def _order_role(order) -> str:
    if order.parent_order_id is None:
        return "ENTRY" if order.child_order_ids else "STANDALONE"
    return "SL" if order.type is OrderType.STOP else "TP"

def build_orders_snapshot(orders) -> pd.DataFrame:
    rows = [{
        "role": _order_role(o),
        "ticker": o.ticker,
        "order_type": o.type.name,
        "action": o.action,
        "status": o.status.name,        # PENDING for never-filled (NOT "ACTIVE")
        "price": float(o.price),
        "quantity": float(o.quantity),
        "filled_quantity": float(o.filled_quantity),
        "time": o.time,
    } for o in orders]
    frame = pd.DataFrame(rows, columns=ORDER_SNAPSHOT_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["role", "order_type", "action", "price"]).reset_index(drop=True)
    return frame
```
> **GAP #1 (load-bearing):** there is NO `OrderStatus.ACTIVE`. MATCH-08's never-filled order serializes as `PENDING`. The golden + VERIFY note must write `PENDING`, not `ACTIVE`.

---

### `tests/e2e/conftest.py` — `orders.csv` opt-in diff + `actions`→`on_tick` translation (test, harness)

**Analog (extend in place):** the existing `equity.csv` opt-in branches + the `_build_and_run` wiring, ALL in this same file. Indentation **4 spaces**. **D-13 constraint:** this file is shared infra — edited ONLY in the foundational plan, NEVER in a parallel leaf plan.

**(a) `on_tick` wiring in `_build_and_run`** — the `system.run` call is `conftest.py:198`:
```python
    system.run(print_summary=False)
```
Extend to build an `on_tick` from `spec.actions` and pass it: `system.run(print_summary=False, on_tick=_make_on_tick(spec, portfolio_ids[0]))`. The translation helper (D-07 predicate resolution via existing query API, `06-RESEARCH.md:310-334`):
```python
def _make_on_tick(spec, portfolio_id):
    actions = getattr(spec, "actions", ())
    if not actions:
        return None  # oracle-inert: no actions → no hook
    by_date = {}
    for a in actions:
        by_date.setdefault(a.bar_date, []).append(a)
    def on_tick(system, time_event):
        key = time_event.time.strftime("%Y-%m-%d")
        for a in by_date.get(key, []):
            candidates = system.order_handler.get_orders_by_ticker(a.ticker, portfolio_id)
            resting = [o for o in candidates if o.status == OrderStatus.PENDING]
            order = resting[0]   # "the sole resting order" predicate
            if a.kind == "cancel":
                system.order_handler.cancel_order(order.id, portfolio_id)
            elif a.kind == "modify":
                system.order_handler.modify_order(
                    order.id, new_price=a.new_price, new_quantity=a.new_quantity,
                    portfolio_id=portfolio_id)
    return on_tick
```
> **GAP #2:** `modify_order`/`cancel_order` annotate `order_id: int` but storage is UUID-keyed (`InMemoryOrderStorage.get_order_by_id` returns None for non-UUID). Pass `order.id` (a real UUID), never a literal int. mypy is scoped to `itrader` only, so the harness passing a UUID is not gate-checked.

**(b) opt-in `equity.csv` FREEZE branch — the exact pattern to clone for `orders.csv`** (`conftest.py:314-318`):
```python
    # equity.csv is opt-in (D-06): only refreshed if the leaf already froze it.
    if (golden_dir / "equity.csv").exists():
        equity[EQUITY_COLUMNS].to_csv(
            golden_dir / "equity.csv", index=False, float_format=FLOAT_FORMAT
        )
```

**(c) opt-in `equity.csv` DIFF branch — clone for `orders.csv`** (`conftest.py:359-363`):
```python
    equity_golden = golden_dir / "equity.csv"
    if equity_golden.exists():
        gold = pd.read_csv(equity_golden)
        fresh = _roundtrip(equity, EQUITY_COLUMNS)
        _diff_frame(fresh, gold, _EQUITY_IDENTITY_COLUMNS, _EQUITY_SORT_KEYS)
```
> For `orders.csv` the planner adds an identity/sort-key pair (e.g. `_ORDERS_IDENTITY_COLUMNS = ["role", "ticker", "order_type", "action"]`, `_ORDERS_SORT_KEYS = ["role", "order_type", "action", "price"]`) alongside the existing `_TRADE_*`/`_EQUITY_*` constants (`conftest.py:84-88`), assembles the snapshot in `_assemble` from `system.order_handler.get_orders_by_ticker(spec.ticker, portfolio_id)`, and threads it through `_freeze`/`_diff` exactly like equity.

**(d) `_roundtrip` normalizer (reuse verbatim)** (`conftest.py:321-337`) — serialize fresh→CSV→reload so both sides share the 10-dp `FLOAT_FORMAT` repr. The snapshot CSV uses the same `FLOAT_FORMAT` (imported at `conftest.py:71-77`).

---

### `tests/e2e/matching/<cluster>/<leaf>/` (~13 leaves) — clone of the canary (test, request-response)

**Analog:** the WHOLE `tests/e2e/smoke/single_market_buy/` folder. Each leaf is self-contained and parallel-safe (edits only its own folder — D-11). Folder shape (`06-RESEARCH.md:144-154`):
```
tests/e2e/matching/<cluster>/<scenario_name>/
├── __init__.py
├── bars.csv          # contrived OHLCV: header "Open time,Open,High,Low,Close,Volume"
├── scenario.py       # SCENARIO = ScenarioSpec(...) + VERIFY hand-derivation docstring
├── test_scenario.py  # one line: run_scenario(HERE)
└── golden/
    ├── trades.csv    # always
    ├── summary.json  # always
    └── orders.csv    # OPT-IN (MATCH-04/05/06/07/08) — presence = assertion
```

**`bars.csv` format** (copy header + tz-aware dates exactly):
```
Open time,Open,High,Low,Close,Volume
2020-01-01 00:00:00+00:00,100.0,105.0,99.0,104.0,1000.0
...
```
> All prices round numbers; author each fill price to be hand-derivable from the engine's exact trigger/gap formulas (`06-RESEARCH.md:192-200`). **Pitfall 1: every leaf MUST use ticker `BTCUSD`** — any other ticker silently REFUSES every order. **Pitfall 5: keep contrived prices in a range** where `FractionOfCash(0.95)` quantity stays within preset order-size limits (100-150 is safe).

**`test_scenario.py` — the one-line copy-template** (`tests/e2e/smoke/single_market_buy/test_scenario.py`) — clone verbatim, rename the test function:
```python
import pathlib
HERE = pathlib.Path(__file__).resolve().parent

def test_single_market_buy(run_scenario):
    run_scenario(HERE)
```

**`scenario.py` — VERIFY note + SCENARIO export.** The canary's docstring (`scenario.py:16-92`) is the VERIFY hand-derivation TEMPLATE: a bar table, decision-bar → fill-bar mapping, the next-bar-open fill prices, the sizing math, and every frozen number explained. Each leaf clones this structure and hand-derives its own fill. **Pitfall 6: explicitly mark decision bar → fill bar** (next-bar-open; the LAST dataset bar can never fill). The `SCENARIO` literal (`scenario.py:141-156`):
```python
_TICKER = "BTCUSD"
_TIMEFRAME = "1d"
_CASH = 10_000

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script={...})],
    portfolios=[PortfolioSpec(user_id=1, name="canary_pf", cash=_CASH)],
    exchange=None,   # D-14: zero-fee / zero-slippage
)
```
> Leaves import `ScenarioSpec`/`PortfolioSpec`/`Action` from the promoted shared module (GAP #4), and the new `ScriptedEmitter` from `tests/e2e/strategies/scripted_emitter.py`. MATCH-07 leaves add `actions=[Action(...)]`.

---

## Shared Patterns

### Oracle-darkness (behavior-preserving)
**Source:** `tests/integration/test_backtest_oracle.py` (gate) + the `print_summary`/`on_tick` default-param idiom.
**Apply to:** the `on_tick` hook AND any shared-infra change. Default `None`/no-op = byte-exact; the foundational plan re-runs the oracle test to prove it. v1.1 is behavior-preserving — scenarios never touch the BTCUSD oracle run.

### Exact no-tolerance diff (presence = assertion)
**Source:** `tests/e2e/conftest.py` `_diff_frame` (`:234-268`), `_roundtrip` (`:321-337`), `_diff` (`:340-369`).
**Apply to:** the new `orders.csv` opt-in golden. Identity columns asserted exact, numeric remainder auto-derived from the golden header, NO float tolerance, both sides normalized through `FLOAT_FORMAT`. A golden is diffed only if present (`equity.csv`/`orders.csv` opt-in).

### Single shared serialization path (no drift, D-16)
**Source:** `itrader/reporting/frames.py` + `itrader/reporting/summary.py` (`FLOAT_FORMAT`).
**Apply to:** `build_orders_snapshot` — same module family, same `FLOAT_FORMAT`, same Decimal→float-at-edge rule, same rows→DataFrame→sort→reset idiom. Purity contract: pandas + stdlib only, duck-typed input, no handler imports.

### Real operator round-trip for MODIFY/CANCEL (D-05 faithfulness)
**Source:** `itrader/order_handler/order_handler.py` `modify_order` (`:121`), `cancel_order` (`:158`); query API `get_orders_by_ticker` (`:290`)/`get_active_orders` (`:258`)/`get_orders_by_status` (`:240`). Live analog: `itrader/trading_system/trading_interface.py`.
**Apply to:** MATCH-07 `on_tick`. Resolve the target by PREDICATE (ticker + PENDING status), then call the REAL handler API with the resolved `order.id` (UUID). Never inject a raw `OrderEvent(MODIFY/CANCEL)` (skips `OrderManager` validation — rejected by D-05).

### Self-contained parallel-safe leaf (D-11)
**Source:** `tests/e2e/smoke/single_market_buy/` (own folder + own test + own golden).
**Apply to:** every matching leaf. `_load_spec` (`conftest.py:107-144`) derives a unique `sys.modules` name from the full leaf path, so same-named leaves in different clusters are safe (Pitfall 5-import). Parallel leaves edit ONLY their own folder — never `conftest.py` or the shared emitter/spec module.

---

## No Analog Found

None. Every new file has a strong in-repo analog. The phase's risk is **contrived-bar authoring correctness** (hand-derivation against the engine's exact `_evaluate` formulas), not building machinery — every mechanism except the four shared-infra pieces already exists and is exercised by the Phase 4 canary.

---

## Planner-Critical Gap Reminders (from RESEARCH)

1. **No `OrderStatus.ACTIVE`** — MATCH-08 never-filled order is `PENDING` in the snapshot. Write `PENDING` in the golden + VERIFY note.
2. **`modify/cancel_order` annotate `int` but storage is UUID-keyed** — pass the resolved `order.id` (UUID), never a literal int.
3. **Ticker hardwired to `BTCUSD`** on the backtest path — every leaf uses `BTCUSD` or orders silently REFUSE.
4. **`ScenarioSpec` is per-leaf today** — the foundational plan must PROMOTE `ScenarioSpec`/`PortfolioSpec`/`Action` to a shared `tests/e2e/scenario_spec.py` (recommended) OR establish a canonical `actions`-bearing copy-template. Structural decision for the planner.
5. **Order-size limits** — keep contrived prices ~100-150 so `FractionOfCash(0.95)` quantity stays within preset `max_order_size`/`min_order_size`.

---

## Metadata

**Analog search scope:** `tests/e2e/` (conftest, strategies, smoke leaf), `itrader/reporting/` (frames, summary), `itrader/trading_system/backtest_trading_system.py`, `itrader/order_handler/` (handler API), CONTEXT.md + RESEARCH.md.
**Files scanned:** 7 source/test files read in full or targeted; 13 files cited from RESEARCH source list.
**Pattern extraction date:** 2026-06-09
**Indentation note:** tests = 4 spaces (match `tests/conftest.py`); `itrader/reporting/` = 4 spaces; `itrader/trading_system/backtest_trading_system.py` = **TABS** (the `on_tick` edit must use tabs).
