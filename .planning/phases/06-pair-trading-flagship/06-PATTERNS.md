# Phase 6: Pair-Trading Flagship - Pattern Map

**Mapped:** 2026-06-17
**Files analyzed:** 7 new/modified
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/strategy_handler/pair_base.py` (NEW — `PairStrategy` base, alongside `base.py`) | strategy base / ABC | transform (windows→intents) | `itrader/strategy_handler/base.py` (`Strategy`) | exact (same role, extends it) |
| `itrader/strategy_handler/strategies_handler.py` (MODIFIED — pair dispatch branch) | strategy handler | event-driven (BAR→SIGNAL) | itself (existing per-ticker dispatch loop) | exact (in-place extension) |
| `itrader/strategy_handler/strategies/<pair>_strategy.py` (NEW reference pair strategy) | strategy (concrete) | transform (β/z → 2 intents) | `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | role-match (single-leg analog) |
| `tests/unit/strategy/test_pair_strategy.py` (NEW — β/z math) | test (unit) | request-response | `tests/unit/strategy/test_strategy.py`, `test_signal_factories.py` | role-match |
| `tests/unit/strategy/test_pair_dispatch.py` (NEW — dispatch emits both legs, guards) | test (unit) | event-driven | `tests/unit/strategy/test_strategies_handler_registration.py` | role-match |
| `tests/integration/test_pair_exit_safety.py` (NEW — close-only / safe-when-flat) | test (integration) | event-driven | `tests/integration/test_backtest_smoke.py` + e2e `partial_cover` | role-match |
| `tests/integration/test_pair_flagship_snapshot.py` (NEW — STABILITY snapshot + determinism) | test (integration/slow) | batch / snapshot-diff | `tests/integration/test_backtest_oracle.py` | exact (diff mechanic) |

**Indentation per file (CONTEXT §code_context, RESEARCH Anti-Patterns):**
- `strategy_handler/` modules (`pair_base.py`, `strategies_handler.py`, reference strategy) → **TABS** (match `base.py` / `SMA_MACD_strategy.py`).
- `core/sizing.py` (imported, not edited) → 4 spaces.
- `tests/` → 4 spaces (match the existing test files).
- NEVER normalize; a mixed-indent diff in a tab file breaks it.

---

## Pattern Assignments

### `itrader/strategy_handler/pair_base.py` (NEW `PairStrategy` base, TABS)

**Analog:** `itrader/strategy_handler/base.py` (`Strategy`).

**Authoring contract to mirror** (`base.py:68-110`) — class-attr declarations introspected by `get_type_hints(type(self))`; bare annotations = REQUIRED, annotations with values = defaults:
```python
timeframe: timedelta          # required — no class-attr value
tickers: list[str]            # required (the PAIR — exactly two; IN-02 rejects non-list[str])
sizing_policy: SizingPolicy   # required
direction: TradingDirection = TradingDirection.LONG_ONLY   # PairStrategy pins LONG_SHORT
allow_increase: bool = False
max_positions: int = 1
max_window: int = 0
warmup: int = 0
name: str = "strategy"
```
`PairStrategy` adds alpha-knob class attrs: `entry_z`, `exit_z`, `z_lookback`, `beta_warmup`, `leverage = Decimal("1")`, `use_log_prices = True` (D-04 RESOLVED), and pins `direction = TradingDirection.LONG_SHORT` (D-14), `max_positions` per-leg as needed.

**Param application + enum coercion** (`base.py:112-126`, `:177-180`) — `__init__` calls `_apply_params(**kwargs)` → `validate()` → `_run_init()`; `_COERCE` (`base.py:63-66`) coerces only `timeframe`/`direction`. Reuse the inherited `_apply_params`; do NOT re-implement.

**⚠ max_window pitfall** (`base.py:258-291`, RESEARCH Pitfall 3): `_run_init` auto-derives `warmup`/`max_window` from registered indicator *handles*. A handle-free pair strategy ends at `warmup == 0`, `max_window == max(0, class value)` — and a 0-width `max_window` yields an EMPTY feed window forever (`frame.iloc[pos:pos]`). The pair base MUST set a hand-set `max_window` class attr ≥ `beta_warmup + z_lookback`. Mirror `SingleMarketBuy.max_window = 100` (`tests/e2e/strategies/single_market_buy.py:56`). Gate β-fit / z on `len(window) >= required_warmup` in the dispatch/strategy, NOT via the handle-derived `warmup`.

**Pure-alpha contract** (`base.py:69-81`, `:293-323`): NO queue, NO portfolio access, NO stamping. `evaluate(ticker, window)` is the single-leg seam. For a pair, add a `evaluate_pair(win_A, win_B) -> list[SignalIntent] | None` (A4 — name is a design choice) returning BOTH legs together. Keep `init()`/`validate()` overridable hooks.

**Intent construction gap** (RESEARCH Pattern 2, `base.py:436-485`): the inherited `buy()/sell()/_intent()` sugar does NOT thread `quantity` — it always builds `SignalIntent(exit_fraction=Decimal("1"), quantity=None)`. So `PairStrategy` must construct `SignalIntent(...)` directly for ENTRY legs (or add a `buy_qty/sell_qty` sugar) to set explicit β-weighted `quantity`. EXITS reuse the plain `buy()/sell()` sugar (quantity=None, `exit_fraction=1.0`).

---

### `itrader/strategy_handler/strategies_handler.py` (MODIFIED — pair dispatch branch, TABS)

**Analog:** itself — the existing per-ticker dispatch loop (`:93-222`).

**Hook location** (RESEARCH OQ3): a type-branch at the TOP of the per-strategy loop (`:93`), BEFORE the per-ticker loop at `:98`:
```python
for strategy in self.strategies:
    if not check_timeframe(event.time, strategy.timeframe):
        continue
    # NEW: route pair strategies to a two-leg dispatch
    if isinstance(strategy, PairStrategy):
        self._dispatch_pair(strategy, event)
        continue
    # existing per-ticker loop (:98-222) UNCHANGED for single-leg strategies
    for ticker in strategy.tickers:
        ...
```

**Both-present guard to mirror** (`:111-113`, D-02) — copy the `bar is None → continue` shape, requiring BOTH legs:
```python
bar = event.bars.get(ticker)
if bar is None:
    continue
```
`_dispatch_pair` does: `bar_A = event.bars.get(tickerA); bar_B = event.bars.get(tickerB); if bar_A is None or bar_B is None: return` (skip silently — do NOT forward-fill, RESEARCH Anti-Patterns).

**Window fetch** (`:117`) — per leg, asof from the event only (T-06-18):
```python
data = self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)
```
Fetch both legs' windows. Warmup short-circuit (`:127`): `if len(win_A) < required or len(win_B) < required: return`.

**Signal-record + per-portfolio fan-out to REUSE** (`:135-220`) — the loop must run ONCE PER INTENT for both returned legs. The `SignalRecord.add` (`:144-156`) and the `for portfolio_id in strategy.subscribed_portfolios` `SignalEvent` construction (`:185-220`) are reused verbatim per leg. Critical seams carried onto each `SignalEvent`:
```python
direction=strategy.direction,        # :202 — LONG_SHORT (D-14)
quantity=intent.quantity,            # :215 — explicit β-weighted qty on ENTRY (WR-01); None on EXIT
exit_fraction=intent.exit_fraction,  # :205 — Decimal("1") on EXIT
leverage=intent.leverage,            # :210 — Decimal("1") default (D-09)
```
MARKET price stamp (`:170-171`): `entry_price = to_money(bar.close)` for each leg's MARKET intent — do NOT read `intent.entry_price` for MARKET.

**Note** (`:235-241`): the legacy `isinstance(tickers[0], tuple)` pairs branch was REMOVED (IN-01); the new pair API is a TYPED dispatch (this branch), not runtime isinstance on the first ticker element.

---

### `itrader/strategy_handler/strategies/<pair>_strategy.py` (NEW reference pair strategy, TABS)

**Analog:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`.

**Class-attr authoring shape** (`SMA_MACD_strategy.py:25-37`):
```python
name = "SMA_MACD"
sizing_policy = FractionOfCash(Decimal("0.95"))   # pair: see D-08 explicit-quantity note
direction = TradingDirection.LONG_ONLY            # pair: TradingDirection.LONG_SHORT
short_window: int = 50                            # pair: entry_z/exit_z/z_lookback/beta_warmup/leverage knobs
```
Pair declares `tickers = ["ETHUSD", "BTCUSD"]`, `direction = LONG_SHORT`, `max_window` ≥ `beta_warmup + z_lookback` (Pitfall 3), Decimal-literal knobs via `Decimal("...")` string path (Pitfall 4: `entry_z = Decimal("2")`, `exit_z = Decimal("0.5")`).

**`validate()` cross-field hook** (`:38-42`): express pair-specific invariants (e.g. `exit_z < entry_z`, `len(tickers) == 2`).

**`init()`/`generate_signal()`** (`:44-80`): SMA_MACD registers indicator handles in `init()` and reads them in `generate_signal`. The pair strategy is handle-FREE (β/z computed from `self.bars` windows via statsmodels/numpy) — so `init()` may be a no-op and the alpha lives in `evaluate_pair`. Mirror `SingleMarketBuy` (`single_market_buy.py:75-83`) for the handle-free read-`self.bars` shape.

**β-fit + z + entry/exit construction** (RESEARCH Pattern 2 / Standard Stack):
```python
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint
X = sm.add_constant(log_B_warmup)
beta = sm.OLS(log_A_warmup, X).fit().params[1]      # log prices (D-04 RESOLVED)
t_stat, p_value, _ = coint(log_A_warmup, log_B_warmup)  # LOGGED DIAGNOSTIC, not a gate (D-10 RESOLVED)
# spread = log_A - beta*log_B; z = (spread - rolling_mean)/rolling_std
```
ENTRY intents carry explicit β-weighted `quantity` (`SignalIntent(quantity=to_money(beta*n), ...)`); EXIT intents carry NO quantity, only `exit_fraction=Decimal("1")` (RESEARCH Pattern 2, Pitfall 1). β→Decimal only via `to_money(beta)` (`Decimal(str(x))` path) — NEVER `Decimal(float)` (Pitfall 4).

---

### `tests/unit/strategy/test_pair_strategy.py` (NEW, 4 spaces)

**Analog:** `tests/unit/strategy/test_signal_factories.py`, `test_strategy.py`.
Hand-computed fixtures (D-11): β from log-OLS on a tiny window, z-score rolling mean/std + crossing detection. Pure-function assertions on `evaluate_pair` outputs (no engine wiring). Markers auto-applied (`unit`) from folder.

### `tests/unit/strategy/test_pair_dispatch.py` (NEW, 4 spaces)

**Analog:** `tests/unit/strategy/test_strategies_handler_registration.py`.
Construct a `StrategiesHandler` + a stub feed, drive a `BarEvent`, assert: (a) BOTH legs emit a `SignalEvent` once per tick, (b) one leg absent → skip (D-02), (c) the two `SignalEvent.quantity` values are N vs β·N (D-08), (d) `direction == LONG_SHORT` on each. Registration gate (`strategies_handler.py:280-287`): the handler MUST be constructed with `allow_short_selling=True, enable_margin=True` or `add_strategy` raises.

### `tests/integration/test_pair_exit_safety.py` (NEW, 4 spaces)

**Analog:** `tests/integration/test_backtest_smoke.py` + e2e `partial_cover` proof. Drive a short→cover via `exit_fraction=1.0` (no quantity); assert the cover clamps-to-flat and no-ops when flat (`admission_manager.py:784-800`, `sizing_resolver.py:174-186`). This is the live-test form of the D-12 trace.

### `tests/integration/test_pair_flagship_snapshot.py` (NEW integration/slow, 4 spaces)

**Analog:** `tests/integration/test_backtest_oracle.py` (the diff mechanic).

**Snapshot diff mechanic to reuse** (`test_backtest_oracle.py:105-125`, `:146-163`): run the ETH/BTC backtest, write trades/equity, load both fresh and committed snapshot to pandas, `pdt.assert_frame_equal(..., check_exact=True, check_like=True)` on deterministic columns sorted by a stable key. Determinism double-run: run twice, assert byte-identical (D-11).

**Critical differences from the oracle test:**
- The snapshot is GENERATED, NOT hand-verified — label it a STABILITY lock, NOT a correctness oracle (D-11). Docstring MUST say so.
- Artifact location: a NEW directory (e.g. `tests/golden/pair/` or `tests/integration/pair_snapshot/`). Do NOT touch `tests/golden/{trades,equity}.csv` (the SMA_MACD oracle — this phase does NOT re-baseline it; A5, RESEARCH Wave 0).
- Wire ETH+BTC via `csv_paths` (Pattern 3, `csv_store.py:52-63`): `csv_paths={"ETHUSD": "data/ETHUSD_1d_ohlcv.csv", "BTCUSD": "data/BTCUSD_1d_ohlcv_2018_2026.csv"}`; system constructed with `allow_short_selling=True, enable_margin=True`.

---

## Shared Patterns

### Decimal money boundary (apply to: reference strategy, dispatch quantity)
**Source:** `itrader/core/money.py::to_money` (used throughout `base.py:453-456`, `strategies_handler.py:171`).
Enter the Decimal domain ONLY via `to_money(x)` → `Decimal(str(x))`. β is a float from statsmodels — convert via `to_money(beta)` at the single boundary. NEVER `Decimal(float)` (breaks determinism double-run — RESEARCH Pitfall 4).

### Explicit-quantity entry vs `exit_fraction` exit (apply to: reference strategy)
**Source:** `itrader/core/sizing.py:309-356` (`SignalIntent.quantity` / `exit_fraction` fields) + `admission_manager.py:784-800` clamp-to-flat.
ENTRY: `SignalIntent(quantity=to_money(...), exit_fraction=Decimal("1"))`. EXIT: `SignalIntent(action=..., order_type=MARKET)` — NO quantity, default `exit_fraction=Decimal("1")`. An explicit `quantity` on an exit short-circuits the reduction resolver and opens a NEW position (the D-12 hazard, RESEARCH Pitfall 1 / Anti-Patterns).

### LONG_SHORT direction carry (apply to: dispatch branch, reference strategy)
**Source:** `core/enums/trading.py:26` + `admission_manager.py:441` (already handles LONG_SHORT — ZERO new admission code, D-14). Registration gate (`strategies_handler.py:280-287`) requires BOTH `allow_short_selling=True` AND `enable_margin=True` on the handler/system. All test wiring + the flagship run MUST set both.

### Class-attr `**kwargs` authoring (apply to: pair base, reference strategy)
**Source:** `base.py:127-220` (`_apply_params`). Reject-unknown-kwargs (`UnknownParamError`), missing-required (`MissingParamError`), enum coercion via `_COERCE`. Inherit it — do not re-implement. IN-02 (`base.py:190-196`) already rejects a non-`list[str]` `tickers`.

---

## No Analog Found

None. Every new file has a strong existing analog in the codebase (the phase is reuse-first; the only genuinely new code is the `PairStrategy` base shape and the dispatch type-branch, both extensions of existing patterns).

## Metadata

**Analog search scope:** `itrader/strategy_handler/` (base, handler, strategies), `itrader/core/sizing.py`, `itrader/price_handler/store/csv_store.py`, `tests/unit/strategy/`, `tests/integration/`, `tests/e2e/strategies/`.
**Files scanned:** 8 source/test files read in full or targeted.
**Pattern extraction date:** 2026-06-17
