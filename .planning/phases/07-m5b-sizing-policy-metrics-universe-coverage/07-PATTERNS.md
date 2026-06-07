# Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage - Pattern Map

**Mapped:** 2026-06-07
**Files analyzed:** 24 new/modified files (+ 3 package deletions)
**Analogs found:** 21 / 24

All excerpts below were read directly from the working tree (branch `implement-phase-7`).
RESEARCH.md (Patterns 1–5) supplies the *target* code for genuinely new logic; this map
supplies the *existing codebase idioms* the new files must copy so they look and behave
like the rest of the engine.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/core/sizing.py` (NEW — policy/direction/intent types) | value-object module | transform | `itrader/core/bar.py` + `itrader/core/enums/order.py` + `itrader/core/portfolio_read_model.py` | exact |
| `itrader/order_handler/sizing_resolver.py` (NEW) | service (resolver) | transform | `OrderManager._resolve_signal_quantity` (order_manager.py:553-629) | exact |
| `itrader/order_handler/order_manager.py` (admission rules, resolver wiring) | manager | request-response | itself — validator-rejection + reservation-rejection blocks | exact |
| `itrader/order_handler/order_validator.py` (delete zero-qty bypass) | validator | request-response | itself (lines 208-225) | exact |
| `itrader/core/portfolio_read_model.py` (+`total_equity`) | protocol/seam | request-response | itself — existing six members | exact |
| `itrader/events_handler/events/signal.py` (typed policy fields) | event dataclass | event-driven | itself — frozen/slots/kw_only Event | exact |
| `itrader/strategy_handler/base.py` (pure `generate_signal` ABC) | abstract base | transform | itself — `_generate_signal` body relocates | exact |
| `itrader/strategy_handler/strategies_handler.py` (intent→event fan-out) | handler | event-driven | `Strategy._generate_signal` (base.py:73-115) | exact |
| `itrader/strategy_handler/SMA_MACD_strategy.py` (intent rewrite) | strategy | transform | itself (calculate_signal:47-87) | exact |
| `itrader/strategy_handler/empty_strategy.py` (convert) | strategy | transform | SMA_MACD rewrite (same conversion) | exact |
| `itrader/reporting/metrics.py` (NEW — pure metric functions) | utility (pure functions) | transform | `itrader/core/money.py` (module shape); RESEARCH Pattern 2 (formulas) | role-match |
| `itrader/reporting/plots.py` (fix minimal set) | presentation | transform | itself (lines 12-63) + RESEARCH plotly-6 fix | exact |
| `itrader/universe/membership.py` (NEW stub) | utility | transform | `StrategiesHandler.get_strategies_universe` (strategies_handler.py:100-117) | exact |
| `itrader/price_handler/feed/bar_feed.py` (+BarEvent factory) | data feed | event-driven | `DynamicUniverse.generate_bar_event` (dynamic.py:59-86) | exact |
| `itrader/events_handler/full_event_handler.py` (TIME route) | dispatcher | event-driven | itself — `_routes` literal (lines 65-84) | exact |
| `itrader/trading_system/backtest_trading_system.py` (wiring) | composition root | request-response | itself — constructor wiring | exact |
| `itrader/trading_system/live_trading_system.py` (import shim) | composition root | request-response | backtest wiring change | role-match |
| `scripts/run_backtest.py` (metrics block + slippage cols) | artifact builder | batch/file-I/O | itself — `build_trade_log`/`build_summary` (78-132) | exact |
| `tests/unit/order/test_sizing_resolver.py` (NEW) | test | — | `tests/unit/core/test_money.py` | exact |
| `tests/unit/order/test_admission_rules.py` (NEW) | test | — | `tests/unit/order/test_on_signal.py` (harness + audited-REJECTED test) | exact |
| `tests/unit/reporting/test_metrics.py` (NEW) | test | — | `tests/unit/core/test_money.py` | exact |
| `tests/unit/reporting/test_plots_smoke.py` (NEW) | test | — | `test_money.py` shape; no smoke-test precedent | partial |
| `tests/unit/universe/test_membership.py` (NEW) | test | — | `tests/unit/core/test_money.py` | role-match |
| `tests/integration/test_backtest_oracle.py` (extend at re-freezes) | test | batch | itself — `_SUMMARY_NUMERIC_KEYS` mechanics | exact |

**Deletions (follow the established deletion discipline, no analog needed):**
`strategy_handler/{position_sizer,risk_manager,sltp_models}/`, `reporting/{statistics.py,engine_logger.py,base.py}`,
`universe/{dynamic.py,static.py,universe.py}` (collapsed to the stub), `Strategy.setting_to_dict`,
`StrategiesHandler.assign_symbol` (strategies_handler.py:67-97, dead), validator `ZERO_QUANTITY_TRANSITION` arm,
plots.py dead extras, the three `pyproject.toml` mypy `ignore_errors` overrides for the reporting modules.

---

## Pattern Assignments

### `itrader/core/sizing.py` (value-object module, transform) — NEW

**Analogs:** `itrader/core/bar.py`, `itrader/core/enums/order.py`, `itrader/core/portfolio_read_model.py`
**Indentation:** spaces (core/ convention — all three analogs use 4 spaces).

**Frozen dataclass pattern** (`core/bar.py` lines 29-50 — the house value-object idiom):
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    """Immutable OHLCV bar fact for one ticker at one tick. ..."""
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
```
`PositionView` (`core/portfolio_read_model.py:48-71`) uses `@dataclass(frozen=True, slots=True)`
*without* `kw_only` — either is in-house; use `kw_only=True` for multi-field types where call-site
clarity matters (the Bar precedent). Each policy kind (`FractionOfCash`, `FixedQuantity`,
`RiskPercent`, `PercentFromFill`, `PercentFromDecision`, `SignalIntent`) is its own frozen/slots
dataclass; unions are plain `X | Y | Z` type aliases (RESEARCH Pattern 1).

**Enum boundary-parse pattern** (`core/enums/order.py` lines 11-30 — copy verbatim for `TradingDirection`):
```python
class OrderType(Enum):
	"""Order type at the event/entity boundary. ..."""
	MARKET = "MARKET"
	STOP = "STOP"
	LIMIT = "LIMIT"

	@classmethod
	def _missing_(cls, value: object) -> "OrderType":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderType: {value!r}")
```
(Note: `core/enums/order.py` uses tabs — it is an older core file. New `core/sizing.py` should use
spaces like `bar.py`/`money.py`/`portfolio_read_model.py`. If `TradingDirection` instead joins
`core/enums/`, match that file's existing style.)

**Module-docstring pattern** (`core/money.py` lines 1-23): every core module opens with a docstring
naming the decisions it locks (`D-xx`) and the rules it enforces ("NEVER call `Decimal(float)`").
`core/sizing.py` should do the same for D-01/D-02/D-05/D-13 and the Pitfall-1 string-entry rule.

**Decimal literal rule** (`core/money.py` lines 42-49):
```python
def to_money(x: float | int | str | Decimal) -> Decimal:
    """Enter the Decimal domain via the string path (D-04). ..."""
    return Decimal(str(x))
```
Policy params must be declared `Decimal("0.95")` — never `Decimal(0.95)`.

**Import-cycle constraint (RESEARCH Pitfall 3):** these types live in `core/` precisely because
`signal.py` must carry them and `order_handler/__init__.py` → `order_handler.py` →
`events_handler.events` → `signal.py` makes a runtime import from `order_handler` circular.
`core/` imports nothing from itrader (see `bar.py` imports: stdlib only).

---

### `itrader/order_handler/sizing_resolver.py` (service, transform) — NEW

**Analog:** `OrderManager._resolve_signal_quantity` — `itrader/order_handler/order_manager.py` lines 553-629.
**Indentation:** new file → spaces (per project convention for new modules).

This is the M1 seam the resolver replaces. Its behavior contract, verbatim:

**Explicit-quantity preserved branch** (order_manager.py:583-585 — survives UNCHANGED, D-07):
```python
		if signal_event.quantity and signal_event.quantity > 0:
			# Explicit caller-supplied quantity: preserved as-is.
			return to_money(signal_event.quantity)
```

**Guard + typed-failure shape** (order_manager.py:587-600 — the failure idiom the resolver's
D-06 violations follow; note failures return `OperationResult.failure_result`, never raise across
the manager boundary):
```python
		price = signal_event.price
		if not price or price <= 0:
			return OperationResult.failure_result(
				f"Cannot size order: invalid signal price {price!r} for {signal_event.ticker}",
				operation_type="create_primary_order"
			)
```

**Exit-to-full-position branch** (order_manager.py:602-612 — becomes `net_quantity × exit_fraction`;
`exit_fraction == 1` MUST skip the multiply entirely, Pitfall 1):
```python
		portfolio_id = cast(PortfolioId, signal_event.portfolio_id)
		open_position = self.portfolio_handler.get_position(
			portfolio_id, signal_event.ticker)
		if signal_event.action is Side.SELL and open_position is not None and open_position.net_quantity > 0:
			# Long-only exit: close the open long by selling its full quantity.
			sized_qty: Decimal = open_position.net_quantity
			return sized_qty
```

**The byte-exact FractionOfCash expression** (order_manager.py:627-629 — the resolver's
`FractionOfCash` arm must reproduce these exact operands in this exact order):
```python
		available = self.portfolio_handler.available_cash(portfolio_id)
		raw_qty: Decimal = (Decimal("0.95") * available) / to_money(price)
		return raw_qty
```
With policy-declared fraction this becomes `(policy.fraction * available) / to_money(price)` where
`policy.fraction` is `Decimal("0.95")` by string construction — same value, same exponent, same repr.

**Dispatch shape:** `match policy: ... case _: assert_never(policy)` (RESEARCH Pattern 1 —
mypy --strict exhaustiveness; no codebase `match` precedent exists, this is the sanctioned new idiom).

**Dependency injection pattern** (order_manager.py:44-47, 81-85 — how collaborators enter):
```python
	def __init__(self, order_storage: OrderStorage, logger: Any,
	             market_execution: str = "immediate",
	             portfolio_handler: Optional[PortfolioReadModel] = None,
	             commission_estimator: Optional[Callable[[Decimal, Decimal], Decimal]] = None) -> None:
```
The resolver receives the `PortfolioReadModel` the same way (injected, typed to the Protocol,
never the concrete `PortfolioHandler`).

---

### `itrader/order_handler/order_manager.py` (manager, request-response) — MODIFIED

**Analog:** itself. **Indentation: tabs** (edit in place, match the file).

**Audited REJECTED route — validator precedent** (order_manager.py:245-261 — the EXACT
template for D-06/D-08/D-10 rejections; new `triggered_by` values follow `"validator"` /
`"cash_reservation"`: use `"admission_direction"`, `"admission_increase"`, `"sizing_policy"`):
```python
			if self.order_validator:
				validation_result = self.order_validator.validate_order_pipeline(primary)
				if not validation_result.success:
					error_msg = f"Signal validation failed: {validation_result.summary}"
					self.logger.error('%s - %s', error_msg,
									[msg.message for msg in validation_result.errors])
					# Audited PENDING→REJECTED transition; the timestamp defaults to
					# the order's own event-derived time (M2-09 — never wall clock).
					primary.add_state_change(
						OrderStatus.REJECTED,
						validation_result.summary,
						triggered_by="validator",
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg,
						error_details=str(validation_result.errors),
						operation_type="signal_validation")]
```

**Second rejection precedent — reservation failure** (order_manager.py:283-298, same shape):
```python
				except InsufficientFundsError as e:
					error_msg = f"Cash reservation failed: {e}"
					self.logger.error('%s for %s %s', error_msg,
									signal_event.ticker, signal_event.action)
					primary.add_state_change(
						OrderStatus.REJECTED,
						str(e),
						triggered_by="cash_reservation",
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg, ...)]
```

**Where admission rules land** — `process_signal` step 0 (order_manager.py:224-233). Today sizing
failures short-circuit BEFORE entity creation; the direction/increase guards slot in here. Pitfall 5
(RESEARCH): a rejected-at-admission order has no quantity — recommended option (a): build the entity
with quantity 0 and immediately transition PENDING→REJECTED through the audited path above.

**Check-and-reserve gate** (order_manager.py:277-282 — D-10's `allow_increase=True` path is
covered by this existing gate, unchanged):
```python
			if self.portfolio_handler is not None and primary.action == Side.BUY.value:
				cost = primary.price * primary.quantity + self._estimate_commission(primary)
				try:
					self.portfolio_handler.reserve(
						cast(PortfolioId, primary.portfolio_id), primary.id, cost)
					reserved_primary = primary
```

**Fill-time SLTP hook** — `on_fill` returns `List[OrderEvent]` the handler enqueues
(order_manager.py:98-117, docstring: "The manager never touches the queue (D-18) — the handler
enqueues these"). PercentFromFill child creation/modification at parent EXECUTED extends this
return-list mechanism (RESEARCH Pattern 5, both options ride it).

---

### `itrader/events_handler/events/signal.py` (event dataclass, event-driven) — MODIFIED

**Analog:** itself. **Indentation: tabs.**

**Current schema** (signal.py:17-68 — `strategy_setting: dict[str, Any]` dies; typed fields replace it):
```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SignalEvent(Event):
	type: EventType = field(default=EventType.SIGNAL, init=False)
	ticker: str
	action: Side
	order_type: OrderType
	price: Decimal
	stop_loss: Decimal
	take_profit: Decimal
	strategy_id: StrategyId
	portfolio_id: int
	strategy_setting: dict[str, Any]          # ← DELETED (D-01)
	quantity: Decimal | None = None
```
New fields import from `core/` only (the file already imports `from itrader.core.enums import
EventType, OrderType, Side` — add `from itrader.core.sizing import SizingPolicy, SLTPPolicy` and
`TradingDirection` from wherever it lands in core). Keep the `field(default=..., init=False)` type
tag and the frozen/slots/kw_only signature. Grep-audit every `SignalEvent(` constructor call
(Pitfall 9): `base.py:100-111`, `tests/unit/order/test_on_signal.py:32-44`,
`tests/unit/strategy/test_strategy.py`, `trading_interface.py`.

---

### `itrader/core/portfolio_read_model.py` (Protocol, request-response) — MODIFIED

**Analog:** itself. **Indentation: spaces.**

**Member shape to copy for `total_equity`** (portfolio_read_model.py:85-101 — numpydoc body, `...` stub):
```python
    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        """Return the portfolio's buying power (balance minus reservations).

        D-14: this is the SINGLE trading-decision cash figure — sizing,
        validation, and risk checks all read it, so they can never disagree.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        Decimal
            Available cash at full ledger precision.
        """
        ...
```
The module docstring (lines 10-35) records each design decision with a D-number — extend it to
note D-14's "equity excluded" rule is being narrowly amended for RiskPercent (oracle-dark).
Conformance: `PortfolioHandler` implements structurally (D-16, no adapter) — add the concrete
method there in the same plan, and extend the structural-conformance test
(`tests/unit/core/test_portfolio_read_model.py`).

---

### `itrader/strategy_handler/base.py` + `strategies_handler.py` (strategy contract) — MODIFIED

**Analogs:** themselves — the code MOVES, it isn't invented. **Indentation: tabs.**

**The SignalEvent construction that relocates** from `Strategy._generate_signal`
(base.py:89-113) into `StrategiesHandler.calculate_signals` (this exact construction, with
`self.last_event` replaced by the `event` parameter, the fan-out loop intact, and
`strategy_setting=...` replaced by the typed policy/direction fields from the strategy object):
```python
		for portfolio_id in self.subscribed_portfolios:
			signal = SignalEvent(
							time = self.last_event.time,
							order_type = OrderType(self.order_type),
							ticker = ticker,
							action = Side(action),
							price = to_money(last_close),
							stop_loss = to_money(sl),
							take_profit = to_money(tp),
							strategy_id = self.strategy_id,
							portfolio_id = portfolio_id,
							strategy_setting=self.setting_to_dict()
						)
			if self.global_queue is not None:
				self.global_queue.put(signal)
```
Preserve the WR-12 sparse-ticker guard (base.py:79-87): `bar = event.bars.get(ticker); if bar is
None: log + skip`. Preserve the boundary-parse comments' behavior: `OrderType(...)`/`Side(...)`
enum parse and `to_money(...)` Decimal entry happen at SignalEvent construction (now handler-side).

**The push loop that hosts the fan-out** (strategies_handler.py:48-59 — keep the timeframe gate
and the push-based window; replace line 59):
```python
		for strategy in self.strategies:
			if not check_timeframe(event.time, strategy.timeframe):
				continue
			strategy.last_event = event          # ← dies with the pure contract (D-12)
			for ticker in strategy.tickers:
				data = self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)
				strategy.calculate_signal(ticker, data)   # ← becomes: intent = strategy.generate_signal(ticker, data)
```

**Strategy `__init__` retype** (base.py:24-43): `max_positions: int = 1, max_allocation: float = 0.80,
allow_increase: bool = False` kwargs → `sizing_policy: SizingPolicy`, `direction: TradingDirection`,
`allow_increase: bool` (typed). `global_queue`, `last_event`, `subscribed_portfolios` handling:
`subscribed_portfolios` stays (the handler reads it for fan-out); `global_queue`/`last_event` die
from the strategy. `setting_to_dict` (base.py:45-50) dies; fix `to_dict` (base.py:52-60) which
references it. `StrategiesHandler.add_strategy` line 134 (`strategy.global_queue = self.global_queue`)
dies too. LONG_SHORT registration rejection (D-08) lands in `add_strategy` with a loud error.

**SMA_MACD rewrite contract** (SMA_MACD_strategy.py:47-76 — value-identical, RESEARCH Pattern 4):
`last_time = self.last_time()` → `last_time = bars.index[-1]`; `self.buy(ticker)` →
`return self.buy(ticker)` where `buy()`/`sell()` become thin sugar returning `SignalIntent`.
The commented-out short block (lines 79-87) stays deleted/commented — SMA_MACD declares
`TradingDirection.LONG_ONLY` and `FractionOfCash(Decimal("0.95"))` (D-03/D-08).

---

### `itrader/reporting/metrics.py` (pure functions, transform) — NEW

**Analog (module shape):** `itrader/core/money.py` — a small pure module: policy docstring pinning
conventions, module-level constants, short functions, zero itrader imports beyond stdlib.
**Analog (formulas):** NONE in codebase — `reporting/statistics.py`/`performance.py` are the
anti-pattern (handler imports, SQL, broken math) and die. Use RESEARCH Pattern 2 verbatim
(verified against backtesting.py `_stats.py`).
**Indentation:** spaces (new module).

Shape to copy from `core/money.py`:
- Module docstring pins every convention with a decision number (here: drawdown sign NEGATIVE,
  `ddof=1`, `PERIODS = 365`, `risk_free_rate = 0` — Pitfall 10 says pin these in writing).
- Constants at top (`PERIODS = 365` like money.py's `_DEFAULT_SCALES`).
- Each function ≤ ~10 lines with a guard clause (like money.py's fallback chain).
- Imports: `numpy`, `pandas` ONLY (anti-pattern note: statistics.py today imports
  `PortfolioHandler`, `Portfolio`, `PriceStore`, sqlalchemy — never repeat).

Frozen set (D-15): `sharpe`, `sortino`, `cagr`, `max_drawdown`, `profit_factor`, `win_rate`,
plus `rolling_sharpe` (D-18, unit-tested, not necessarily frozen). Pandas-2-safe idioms throughout:
`.iloc[-1]`, whole-column assignment, explicit empty-subset guards (Pitfall 2 —
`filterwarnings=["error"]` makes FutureWarning/RuntimeWarning suite-fatal).

---

### `itrader/reporting/plots.py` (presentation, transform) — MODIFIED

**Analog:** itself. **Indentation: tabs** (existing file).

**The broken pattern to fix** (plots.py:27-33 — `titlefont_size` raises hard `ValueError` on
plotly 6.8.0; verified empirically in RESEARCH):
```python
		chart.update_layout(
							xaxis_tickfont_size=12,
							yaxis=dict(
								title='[%]',
								titlefont_size=14,      # ← ValueError on plotly 6
								tickfont_size=12,
								))
```
**Fix idiom** (RESEARCH, verified against the project venv):
```python
		chart.update_layout(
			yaxis=dict(title=dict(text='[%]', font=dict(size=14)), tickfont=dict(size=12)),
		)
```
Same defect at lines 31, 55, 108, 159; `append_trace` → `add_trace(..., row=r, col=c)`.
Keep the minimal set (equity `line_equity`, drawdown `line_drwdwn`, trade P/L scatter — fix its
column bugs); delete dead extras and dev comments ("OK, FUNZIONA"). Functions take the SAME frames
as `metrics.py` (equity series / trades frame), not portfolio objects.

---

### `itrader/universe/membership.py` (utility, transform) — NEW

**Analog:** `StrategiesHandler.get_strategies_universe` — strategies_handler.py:100-117
(this logic literally survives, D-20) + `DynamicUniverse.universe` property (dynamic.py:36-41).
**Indentation:** spaces (new module).

**Union-of-tickers logic to carry over** (strategies_handler.py:109-117 — tuple-pair flattening included):
```python
		traded_tickers: list[str] = []
		for strategy in self.strategies:
			# Check if the strategy is trading pairs
			if strategy.tickers and isinstance(strategy.tickers[0], tuple):
				traded_tickers += [value for tuple in strategy.tickers for value in tuple]
			else:
				traded_tickers += strategy.tickers
		return list(set(traded_tickers))
```
**Membership union** (dynamic.py:36-41):
```python
	@property
	def universe(self) -> list[str]:
		"""Return the universe coming from both screeners and strategies."""
		return list(set(self.strategies_universe + self.screeners_universe))
```
Module docstring must prominently name the LEAN `UniverseSelectionModel` as the growth target
alongside the D-screener rebalance loop (D-20). `StaticUniverse` + the `get_assets` ABC
(`universe/static.py`, `universe/universe.py`) are deleted, not ported.

---

### `itrader/price_handler/feed/bar_feed.py` (+BarEvent factory) — MODIFIED

**Analog:** `DynamicUniverse.generate_bar_event` — dynamic.py:59-86 (the body MOVES here, D-20).
**Indentation:** spaces (bar_feed.py uses 4 spaces).

**The factory body that relocates** (dynamic.py:69-86 — already thin: `current_bars` + warn + wrap + enqueue):
```python
		bars = self.feed.current_bars(time_event.time)

		for ticker in self.strategies_universe:
			if ticker not in bars:
				self.logger.warning('Dynamic Universe: no bar for ticker %s at %s in the feed', ticker, str(time_event.time))

		bar_event = BarEvent(time=time_event.time, bars=bars)
		self.last_bar = bar_event

		if self.global_queue is not None:
			self.global_queue.put(bar_event)
			return None
		else:
			return bar_event
```
In the feed, `self.feed.current_bars(...)` becomes `self.current_bars(...)` (bar_feed.py:196-211
is already in-class). RESEARCH OQ4 recommends keeping the missing-ticker warning — the factory can
accept the membership list as a parameter. Match the feed's existing logger idiom (bar_feed.py:148):
`self.logger = get_itrader_logger().bind(component="BacktestBarFeed")`. Whether the factory
enqueues directly (taking the queue, like DynamicUniverse) or returns the BarEvent for the
TIME-route to enqueue is planner discretion — Pitfall 7's blast radius applies either way.

---

### `itrader/events_handler/full_event_handler.py` (TIME route) — MODIFIED

**Analog:** itself. **Indentation: tabs.**

**The routing literal to rewire** (full_event_handler.py:65-69 — `self.universe.generate_bar_event`
replaced by the feed-backed factory callable; constructor param `universe: Universe` at line 48
replaced/retyped in the same plan):
```python
		self._routes: dict[EventType, list[Callable[[Any], Any]]] = {
			EventType.TIME: [
				self.screeners_handler.screen_markets,
				self.universe.generate_bar_event,      # ← becomes the BarFeed-owned factory
			],
```
Blast radius (Pitfall 7, update in the SAME plan): `tests/unit/events/test_dispatch_registry.py`
(asserts `wiring.universe.generate_bar_event` at line 100), `tests/unit/events/test_error_flow.py`,
`tests/integration/test_event_wiring.py`, both trading systems
(`backtest_trading_system.py` wires `DynamicUniverse`; `live_trading_system.py:111,213` constructs
`DynamicUniverse`/calls `init_universe` — keep live importing something that exists, A4).

---

### `scripts/run_backtest.py` (artifact builder, batch) — MODIFIED

**Analog:** itself. **Indentation: spaces.**

**Summary-builder shape to extend** (run_backtest.py:114-132 — the metrics block joins this dict;
RESEARCH OQ3 recommends a nested `"metrics": {...}` block):
```python
def build_summary(portfolio, trades):
    total_realised_pnl = float(trades["realised_pnl"].sum()) if not trades.empty else 0.0
    return {
        "ticker": TICKER,
        ...
        "final_equity": float(portfolio.total_equity),
        "trade_count": int(len(trades)),
        "total_realised_pnl": total_realised_pnl,
    }
```
The docstring's "Derived ratios (sharpe/sortino/cagr) are intentionally omitted — that math is
M5-owned" carve-out (lines 19-20, 118-119) is exactly what this phase closes: call
`reporting.metrics` functions on `build_equity_curve`/`build_trade_log` output.

**Trade-log builder the slippage columns extend** (run_backtest.py:78-89; new columns appended to
`TRADE_COLUMNS` list at lines 50-62; slippage computed post-hoc per RESEARCH Pattern 3 — engine-inert,
from the store frame's decision-bar close vs fill price). Serialization stays pinned:
`float_format=FLOAT_FORMAT` (`"%.10f"`), `json.dump(..., indent=2, sort_keys=True)` (lines 168-173).

**Oracle safety (Pitfall 6):** new columns/keys may be PRODUCED early — the oracle test derives
trade-numeric columns from `golden_trades_sorted.columns` (test_backtest_oracle.py:184-186) and
summary checks from fixed tuples (`_SUMMARY_NUMERIC_KEYS`, line 55), so extras in fresh `output/`
are ignored until the goldens regenerate at the two D-11 re-freezes (golden regen + key-tuple
extension in the SAME commit, REFREEZE-M5A precedent).

---

### `tests/unit/order/test_admission_rules.py` (test) — NEW

**Analog:** `tests/unit/order/test_on_signal.py` — copy the harness + the audited-REJECTED assertion style.
**Indentation:** spaces. Markers: folder-derived `unit` (tests/conftest.py:49-56) — no hand-added markers.

**Harness pattern** (test_on_signal.py:16-56):
```python
class _OnSignalHarness:
    """OrderHandler harness with a single funded portfolio and a signal factory."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        self.last_ptf_id = self.ptf_handler.add_portfolio(1, "test_ptf", "default", 10000)

    def create_mock_signal(self, action, ticker="BTCUSDT", quantity=100.0, price=40.0, ...):
        return SignalEvent(time=datetime.now(), order_type=OrderType(order_type), ...)

@pytest.fixture
def harness():
    h = _OnSignalHarness()
    yield h
    while not h.queue.empty():    # drain to prevent cross-test bleed
        ...
```
(The signal factory must be updated for the typed policy fields — `strategy_setting={}` dies.)

**Audited-REJECTED assertion pattern** (test_on_signal.py:139-174 — the template for asserting
direction/increase rejections):
```python
def test_rejected_signal_persists_audited_rejected_order(harness):
    signal = harness.create_mock_signal("BUY", quantity=100.0, price=200.0, ...)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()                      # nothing emitted
    stored = storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 1
    assert stored[0].status == OrderStatus.REJECTED
    assert storage.get_active_orders(harness.last_ptf_id) == []

    last_change = rejected.get_latest_state_change()
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "validator"    # → "admission_direction" / "admission_increase"
    assert last_change.timestamp == signal.time       # event time, never wall clock
```

---

### `tests/unit/order/test_sizing_resolver.py`, `tests/unit/reporting/test_metrics.py`, `tests/unit/universe/test_membership.py` (tests) — NEW

**Analog:** `tests/unit/core/test_money.py` — the pure-function test idiom: flat functions,
hand-computed expected values, explanatory comments citing the decision number.

**Pattern** (test_money.py:32-52):
```python
from decimal import Decimal

import pytest

from itrader.core.money import quantize, to_money

pytestmark = pytest.mark.unit


def test_to_money_uses_str_path():
    # D-04: Decimal(str(10.1)) == Decimal("10.1"); Decimal(10.1) would NOT.
    assert to_money(10.1) == Decimal("10.1")


def test_quantize_cash_half_up_2dp():
    # D-03: USD cash scale is 2dp, ROUND_HALF_UP -> 1.005 rounds up to 1.01.
    assert quantize(Decimal("1.005"), "BTCUSD", "cash") == Decimal("1.01")
```
Notes: the explicit `pytestmark = pytest.mark.unit` is belt-and-braces (folder auto-marking also
applies — tests/conftest.py:42-56); new directories `tests/unit/reporting/` and
`tests/unit/universe/` get the `unit` marker automatically by path. For metrics, use the
hand-computable fixture from RESEARCH (`equity = pd.Series([100.0, 110.0, 99.0, 121.0])` →
`max_drawdown == -0.10` exactly). For resolver byte-exactness tests, assert on `str(result)`
(repr-exact) not just `==` (Pitfall 1: equal values can differ in exponent).

`tests/unit/reporting/test_plots_smoke.py` has no smoke-test precedent — same file shape; each test
builds one figure and asserts it constructs without raising (optionally `isinstance(fig, go.Figure)`).

---

### `tests/integration/test_backtest_oracle.py` (oracle, extend at re-freezes) — MODIFIED

**Analog:** itself.

**The key tuples that grow at the D-11 re-freezes** (test_backtest_oracle.py:39-55):
```python
_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]
_TRADE_IDENTITY_COLUMNS = _TRADE_KEY_COLUMNS + ["pair"]
_SUMMARY_IDENTITY_KEYS = ("trade_count",)
_SUMMARY_NUMERIC_KEYS = ("final_cash", "final_equity", "total_realised_pnl")
```
And the derived-column mechanic that makes new trade columns auto-locked once goldens regen
(lines 184-186):
```python
    _trade_numeric = [
        c for c in golden_trades_sorted.columns if c not in _TRADE_IDENTITY_COLUMNS
    ]
```
Re-freeze discipline: regenerate `tests/golden/*`, extend `_SUMMARY_NUMERIC_KEYS` (or add the
nested-metrics assertion per RESEARCH OQ3), and write the expected-diff note — all in ONE commit
per re-freeze (`tests/golden/REFREEZE-M5A.md` is the note-format precedent). The comment style at
lines 43-55 (narrating each re-baseline with its decision number) should be continued.

---

## Shared Patterns

### Logger binding
**Source:** `strategies_handler.py:33`, `dynamic.py:33`, `bar_feed.py:148`
**Apply to:** every class touched/created
```python
self.logger = get_itrader_logger().bind(component="ClassName")
```
Pure-function modules (`metrics.py`, `membership.py` if function-only) need no logger.

### Decimal entry and inertness
**Source:** `core/money.py:42-49`, `core/bar.py:61-68`, order_manager.py:628
**Apply to:** `core/sizing.py`, `sizing_resolver.py`, all policy literals
- Enter via `to_money(x)` / `Decimal(str(x))`; NEVER `Decimal(float)`.
- Byte-exactness: reproduce existing expressions operand-for-operand; default-valued new params
  must be structural no-ops (skip the op), not arithmetic identities (Pitfall 1).
- `step_size` quantization: `qty.quantize(step, rounding=ROUND_DOWN)` (stdlib, D-05).

### Audited rejection (Phase 4 route)
**Source:** order_manager.py:253-261 and 290-298
**Apply to:** every D-06/D-08/D-10 rejection
`primary.add_state_change(OrderStatus.REJECTED, reason, triggered_by="<gate-name>")` →
`self.order_storage.add_order(primary)` → `OperationResult.failure_result(...)`. Reason string
names the policy violation; timestamp is event-derived, never wall clock.

### Manager-never-touches-queue (D-18)
**Source:** order_manager.py:44-56 docstring, on_fill:98-117
**Apply to:** sizing resolver, admission rules, fill-time SLTP
Managers return `OperationResult`s / event lists; ONLY the handler (`OrderHandler`,
`StrategiesHandler`) performs `global_queue.put(...)`.

### Frozen/slots dataclass + decision-pinning docstrings
**Source:** `core/bar.py:29-50`, `core/portfolio_read_model.py:48-71`, `events/signal.py:17`
**Apply to:** all new types (`SizingPolicy` kinds, `SLTPPolicy` kinds, `SignalIntent`)
`@dataclass(frozen=True, slots=True[, kw_only=True])`; module docstring opens with the D-numbers
it locks; field docs in numpydoc style.

### Enum boundary parsing
**Source:** `core/enums/order.py:11-30`
**Apply to:** `TradingDirection`
Class-based Enum, explicit string values, case-insensitive `_missing_` raising
`ValueError(f"Unknown X: {value!r}")`.

### Test layout and markers
**Source:** `tests/conftest.py:42-56` (folder-derived markers), `test_money.py:29` (`pytestmark`),
`test_on_signal.py:47-56` (queue-draining fixture)
**Apply to:** all new test files. New dirs under `tests/unit/` are auto-marked `unit`. Shared bar
helpers exist as fixtures: `make_bar_struct`, `make_bar`, `make_bar_event` (tests/conftest.py:96-111).

### Indentation
Tabs: `order_manager.py`, `order_validator.py`, `base.py`, `strategies_handler.py`,
`SMA_MACD_strategy.py`, `signal.py`, `full_event_handler.py`, `plots.py`, `core/enums/*` (edit in place).
Spaces: `core/bar.py`, `core/money.py`, `core/portfolio_read_model.py`, `bar_feed.py`,
`run_backtest.py`, all tests, and ALL NEW modules.

---

## No Analog Found

Files/areas with no close codebase match (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `itrader/reporting/metrics.py` (formula bodies) | utility | transform | Existing `statistics.py`/`performance.py` are the documented anti-pattern (broken math, handler imports) — use RESEARCH Pattern 2 (verified against backtesting.py `_stats.py`) |
| `match`/`assert_never` exhaustive dispatch | idiom | — | No `match` statement exists in the codebase; sanctioned new idiom per RESEARCH (mypy --strict exhaustiveness) |
| `tests/unit/reporting/test_plots_smoke.py` | test | — | No figure-smoke-test precedent; build-without-raising per D-19 |
| Fill-time SLTP (`PercentFromFill`) mechanics | manager logic | event-driven | Genuinely new; RESEARCH Pattern 5 gives two viable options (planner discretion per D-13); the modify chain (`modify_order` order_manager.py:631 → MODIFY OrderEvent → `MatchingEngine.modify`) and the on_fill return-list mechanism are the existing rails |

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/order_handler/`, `itrader/strategy_handler/`,
`itrader/events_handler/`, `itrader/universe/`, `itrader/price_handler/feed/`, `itrader/reporting/`,
`scripts/`, `tests/unit/{core,order,price,strategy,events}/`, `tests/integration/`, `tests/conftest.py`
**Files read:** 18 (targeted reads with line ranges for order_manager.py 805 LOC and order_validator.py 555 LOC)
**Pattern extraction date:** 2026-06-07
