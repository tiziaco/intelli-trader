# Phase 4: Liquidation & Cross-Validation Re-baseline - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 16 (8 source modified, 3 unit-test new, 3 e2e-leaf new, crossval runners + 1 evidence doc)
**Analogs found:** 16 / 16 (every seam already exists in-repo — Phase 4 is first-party-only)

> **Indentation is per-file and load-bearing.** A mixed-indentation diff breaks a tab
> file under no-autoformatter discipline. Each Pattern Assignment below pins TAB vs
> 4-SPACE from the live file. Verified this session:
> - **4 SPACES:** `core/instrument.py`, `config/portfolio.py`, `events_handler/events/fill.py`, `events_handler/events/order.py`, `portfolio_handler/cash/cash_manager.py`
> - **TABS:** `core/enums/order.py`, `portfolio_handler/portfolio_handler.py`, `portfolio_handler/portfolio.py`, `portfolio_handler/position/position.py`, `order_handler/order_handler.py`, `order_handler/reconcile/reconcile_manager.py`
>
> (Note the trap: `core/enums/order.py` is TABS even though most of `core/` is 4-space; and
> `cash/cash_manager.py` is 4-SPACE even though the rest of `portfolio_handler/` is TABS.)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/core/instrument.py` (MODIFY) | model (value object) | config/read-model | `borrow_rate` field on same file (instrument.py:90) | exact |
| `itrader/core/enums/order.py` (MODIFY) | enum (closed vocab) | n/a | `ADMISSION_*` members on `OrderTriggerSource` (order.py:189-192) | exact |
| `itrader/config/portfolio.py` (MODIFY) | config | config | `TradingRules.max_leverage` field (portfolio.py:81) | exact |
| `itrader/portfolio_handler/portfolio_handler.py` (MODIFY) | handler | event-driven (BAR route) | the P3 carry hook in `update_portfolios_market_value` (handler.py:432) + `maintenance_margin` (307) | exact |
| `itrader/portfolio_handler/portfolio.py` (MODIFY: WR-04 + forced-close settle) | aggregate | CRUD/settle | `transact_shares` close arm (portfolio.py:430-457) + `_accrue_short_carry` (657) | exact |
| `itrader/portfolio_handler/cash/cash_manager.py` (MODIFY: WR-04) | manager | CRUD/settle | `assert_lock_fits_buying_power` (437) + `apply_fill_cash_flow` (308) | exact |
| `itrader/events_handler/events/fill.py` (USE, not modify) | event factory | event-driven | `FillEvent.new_fill` (fill.py:81) — needs an OrderEvent | exact |
| `itrader/events_handler/events/order.py` (USE) | event factory | event-driven | `OrderEvent.new_order_event` (order.py:82) | exact |
| `itrader/order_handler/order_handler.py` (CONFIRM) | handler | event-driven | `on_fill` mirror dispatch (order_handler.py:150) | exact |
| `itrader/order_handler/reconcile/reconcile_manager.py` (CONFIRM) | manager | reconcile | `on_fill` EXECUTED→FILLED arm (reconcile_manager.py:242 + early-return 209-214) | exact |
| `tests/unit/portfolio/test_liquidation.py` (NEW) | test | unit | `tests/unit/portfolio/test_carry.py`, `test_portfolio_margin.py` | role-match |
| `tests/unit/order/test_liquidation_reconcile.py` (NEW) | test | unit | `tests/unit/order/test_reconcile_manager.py` | exact |
| `tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` (NEW) | test | unit | `tests/unit/portfolio/test_cash_manager.py` | exact |
| `tests/e2e/forced_liq_long/`, `forced_liq_short/`, `levered_long_into_liquidation/` (NEW) | test (white-box e2e) | e2e | `tests/e2e/levered_long/test_levered_long_scenario.py` | exact |
| `scripts/crossval/{short,levered,liquidation}_run.py` + extend `scripts/cross_validate.py` (NEW) | script | cross-validation | `scripts/cross_validate_limit.py` + `crossval/*_limit_run.py` | exact |
| `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` (NEW) | evidence doc | n/a | `tests/golden/CROSS-VALIDATION.md` (Owner Sign-Off block 206-224) | exact |

---

## Pattern Assignments

### `itrader/core/instrument.py` — ADD `liquidation_fee_rate` (model, 4 SPACES)

**Analog:** the `borrow_rate` field on the SAME frozen dataclass (instrument.py:90).

**Field block to copy** (instrument.py:82-90, kw_only frozen-slots dataclass):
```python
    symbol: str
    price_precision: Decimal
    quantity_precision: Decimal
    maintenance_margin_rate: Decimal
    max_leverage: Decimal
    quote_currency: str = "USD"
    min_order_size: Decimal | None = None
    settles_funding: bool = False
    borrow_rate: Decimal = Decimal("0")
```

**Add (D-06, exactly the `borrow_rate` shape — defaulted, Decimal, oracle-dark):**
```python
    liquidation_fee_rate: Decimal = Decimal("0")   # D-06 — default 0 = oracle-dark
```
Then extend the class docstring Fields block (the `borrow_rate:` paragraph at lines 74-79
is the template). `maintenance_margin_rate` (line 85) is already present — **IN-03 needs
no new field** (the liq formula reads it via the Universe; see handler analog below).

---

### `itrader/core/enums/order.py` — ADD `OrderTriggerSource.LIQUIDATION` (enum, TABS)

**Analog:** the `ADMISSION_*` members on the same closed-vocabulary enum (order.py:182-192).
The `_missing_` case-insensitive parser (194-201) already handles any new member — no edit there.

**Member block to copy (TABS):**
```python
	SYSTEM = "system"
	STRATEGY = "strategy"
	USER = "user"
	EXCHANGE = "exchange"
	VALIDATOR = "validator"
	CASH_RESERVATION = "cash_reservation"
	SIZING_POLICY = "sizing_policy"
	ADMISSION_DIRECTION = "admission_direction"
	ADMISSION_INCREASE = "admission_increase"
	ADMISSION_MAX_POSITIONS = "admission_max_positions"
	ADMISSION_LEVERAGE = "admission_leverage"
```

**Add (value-equal string, LIQ-03):**
```python
	LIQUIDATION = "liquidation"   # LIQ-03 — forced-close trigger source
```

---

### `itrader/config/portfolio.py` — ADD `liquidation_fee_rate` fallback (config, 4 SPACES)

**Analog:** `TradingRules.max_leverage` (portfolio.py:81) — a `Decimal = Field(...)` rate-style
field on the `extra="forbid"` Pydantic model.

**Field block to copy (portfolio.py:71-85):**
```python
    allow_short_selling: bool = False
    enable_margin: bool = False
    enable_options: bool = False
    enable_futures: bool = False
    max_leverage: Decimal = Field(default=Decimal("1"), ge=1)
    min_trade_amount: Decimal = Decimal("100.0")
    max_trade_amount: Optional[Decimal] = None
    max_transactions_per_day: Optional[int] = None
    max_cash_withdrawal_pct: float = Field(default=0.50, ge=0, le=1)
```

**Add (D-06 — config-level fallback for symbols that don't declare it on `Instrument`; default 0 = oracle-dark):**
```python
    liquidation_fee_rate: Decimal = Field(default=Decimal("0"), ge=0)
```
`model_config = ConfigDict(extra="forbid")` means the resolution path must READ this field
explicitly (Instrument-first, then `trading_rules.liquidation_fee_rate`) — mirror P1
`min_order_size` (Instrument-first → ExchangeLimits fallback).

---

### `itrader/portfolio_handler/portfolio_handler.py` — liquidation breach check (handler, TABS)

This is the heart of LIQ-01/D-04. The handler already holds `self.global_queue` (59) and
`self._universe` (88, wired by `set_universe`, line 297), and already runs a per-bar pass
over active portfolios.

**Analog 1 — the BAR-route hook to extend** (`update_portfolios_market_value`, handler.py:432-477).
The check co-locates here, run at HANDLER level AFTER the per-portfolio mark+carry call
(D-02 placement: post-carry so the breach sees carry-eroded equity). Note the existing
fail-fast `try/except` that publishes a `PortfolioErrorEvent` then re-raises (464-477) — the
liquidation check goes INSIDE/AFTER this same loop and inherits the same error contract:
```python
		for portfolio in active_portfolios:
			try:
				portfolio.update_market_value_of_portfolio(prices, bar_time, self._universe)
			except Exception as e:
				correlation_id = self._generate_correlation_id()
				self._publish_error_event(
					e, "update_portfolios_market_value", correlation_id,
					portfolio.portfolio_id)
				raise
		# NEW (LIQ-01): second pass — collect breached positions, sort
		# deterministically (D-02: symbol, then open-time, then position-id),
		# then for each mint forced-close Order + emit FillEvent(EXECUTED).
```

**Analog 2 — the per-position MMR read** (`maintenance_margin`, handler.py:307-340). The liq
formula reuses this exact Universe→Instrument read pattern (and its WR-02 unwired-Universe
`StateError` guard — copy it for the liquidation read too):
```python
		positions = portfolio.position_manager.get_all_positions()
		if positions and self._universe is None:
			raise StateError(
				portfolio_id, "universe-unwired",
				required_state="universe-wired (call set_universe)",
				operation="maintenance_margin")
		for position in positions.values():
			instrument = self._universe.instrument(position.ticker)
			total += (instrument.maintenance_margin_rate
				* abs(position.net_quantity) * position.current_price)
```
The liquidation check reads `instrument.maintenance_margin_rate` AND
`instrument.liquidation_fee_rate` per breaching position the same way.

**Analog 3 — emitting the fill on the queue.** The handler already enqueues events with
`self.global_queue.put(...)`. For the forced close, after registering the Order in storage
(Pitfall 4), do `self.global_queue.put(fill_event)` with `time=bar_time` (D-04 / Pitfall 6 —
NOT `datetime.now`, NOT routed through `ExecutionHandler`).

**Liq-price + capped-loss math (Decimal end-to-end, from RESEARCH Pattern 1 — HAND-VERIFIED):**
```python
# WB = CashManager.get_locked_margin_for(str(position.id))  (the position-keyed lock)
margin_per_unit = wb / abs(size)
# LONG:
liq_price = (entry - margin_per_unit) / (Decimal("1") - mmr)
# SHORT:
liq_price = (entry + margin_per_unit) / (Decimal("1") + mmr)
penalty = fee_rate * abs(size) * liq_price                 # D-05 → FillEvent.commission
total_realized_loss = min(realized_loss + penalty, wb)     # D-07/D-03-CORR — EXPLICIT clamp
```

---

### `itrader/portfolio_handler/portfolio.py` — WR-04 fix + forced-close settle (aggregate, TABS)

**WR-04 defect (verbatim, portfolio.py:430-457) — `release_margin` runs BEFORE the assert, so
`assert_lock_fits_buying_power` reads `own_prior_lock == 0`.** Two call sites — open/scale-in
(~430) and partial/full close (~449); **fix BOTH**:
```python
			self.cash_manager.release_margin(str(position.id))       # pops the lock FIRST
			new_lock = position.aggregate_notional / leverage
			self.cash_manager.assert_lock_fits_buying_power(new_lock, str(position.id))
			self.cash_manager.lock_margin(str(position.id), new_lock)
```
Fix shape (planner discretion): assert BEFORE release (compute `new_lock` first, assert, then
`release` + `lock`), or thread the released amount into the assert (`prior_lock=` kwarg).

**Forced-close settle reuses the EXISTING close arm (portfolio.py:438-489)** — no new PnL path.
The forced close is a normal close fill through `realised_pnl` + `apply_fill_cash_flow`:
```python
			realised_increment = position.realised_pnl - prior_realised
			open_commission_credit = self._open_commission_credit_for_close(position, closed_qty)
			cash_delta = realised_increment + open_commission_credit
		self.cash_manager.apply_fill_cash_flow(
			amount=cash_delta, fee=commission,
			description=f"Margin {transaction.type.name} {transaction.ticker}",
			reference_id=str(transaction.id), timestamp=transaction.time)
```

**Carry-accrual hook analog (`_accrue_short_carry`, portfolio.py:657-739)** — the closest model
for a per-bar, per-position pass that resolves the Instrument via the Universe, defends the
money operand (`current_price <= 0` skip), and uses `StateError` for a missing Instrument.
The liquidation per-position pass mirrors its guard structure.

---

### `itrader/portfolio_handler/cash/cash_manager.py` — WR-04 settle/assert (manager, 4 SPACES)

**Analog — `assert_lock_fits_buying_power` (cash_manager.py:437-469).** It reads
`own_prior_lock = self._storage.get_locked_margin_for(position_id)` (463) — this is the
**WB source** the liquidation floor reads, and the method whose call-order WR-04 fixes. If the
planner chooses the threaded-amount fix (Option B), this signature gains a `prior_lock=` kwarg:
```python
        own_prior_lock = self._storage.get_locked_margin_for(position_id)
        buying_power = self.available_balance + own_prior_lock
        if lock_amount > buying_power:
            raise InsufficientFundsError(
                required_cash=float(lock_amount),
                available_cash=float(buying_power))
```

**Settle analog — `apply_fill_cash_flow` (cash_manager.py:308-360)** is the ONE trade-path cash
primitive (full precision, no 2dp quantize, event-derived timestamp). The forced-close loss +
penalty settle through it via `portfolio.transact_shares` (the penalty rides
`FillEvent.commission`); `accrue_borrow_interest` (362-412) is the BORROW_INTEREST sibling
pattern if a distinct ledger line is ever wanted (it is NOT — penalty rides commission, D-04).

---

### `itrader/events_handler/events/fill.py` — mint the forced-close FillEvent (USE, 4 SPACES)

**Analog/contract — `FillEvent.new_fill` (fill.py:81-150).** Do NOT hand-roll a FillEvent
literal — it mints `fill_id`, carries the audit chain, and quantizes via `to_money`.
**It REQUIRES an `OrderEvent`** as input (Pitfall 4 — the order must exist). Pass `time=bar_time`
(the breach bar) and the penalty in `commission`:
```python
    @classmethod
    def new_fill(cls, status: str, order: OrderEvent, *,
                 price: 'Decimal | float', quantity: 'Decimal | float',
                 commission: 'Decimal | float',
                 time: 'datetime | None' = None) -> 'FillEvent':
        ...
        return cls(time=time if time is not None else order.time,
                   status=FillStatus(status), ticker=order.ticker,
                   action=order.action, price=to_money(price),
                   quantity=to_money(quantity), commission=to_money(commission),
                   portfolio_id=order.portfolio_id, fill_id=uuid_compat.uuid7(),
                   order_id=order.order_id, strategy_id=order.strategy_id, ...)
```
Call: `FillEvent.new_fill("EXECUTED", liq_order_event, price=liq_price, quantity=abs(size), commission=penalty, time=bar_time)`.
The `OrderEvent` is built via `OrderEvent.new_order_event(order)` (order.py:82-130) from the
registered forced-close Order (opposite side, qty=|size|, tagged `OrderTriggerSource.LIQUIDATION`).

---

### `itrader/order_handler/*` — mirror reconcile EXECUTED→FILLED (CONFIRM, TABS)

**Analog — `OrderHandler.on_fill` (order_handler.py:150-160)** delegates to
`order_manager.on_fill` and enqueues any returned CANCEL events. No change needed if the
forced-close Order is registered.

**Critical contract — `ReconcileManager.on_fill` (reconcile_manager.py:179-265).** The
EXECUTED arm (`_apply_executed`, dispatched at line 242-243) is the no-new-status reconcile
(LIQ-03). **Pitfall 4 lives here** — the early-returns (209-214) silently no-op if the order
isn't in storage:
```python
        order_id = getattr(fill_event, 'order_id', None)
        if order_id is None:
            return out_events
        order = self.order_storage.get_order_by_id(order_id, fill_event.portfolio_id)
        if order is None:
            return out_events
```
→ The liquidation engine MUST persist a real forced-close `Order` in `order_storage` keyed by
the fill's `order_id`, or the mirror never reaches FILLED. No edit to this file is expected —
the test (`test_liquidation_reconcile.py`) asserts the existing path fires.

---

### Test analogs

**`tests/unit/portfolio/test_liquidation.py` (NEW)** — mirror `tests/unit/portfolio/test_carry.py`
(per-bar accrual unit shape) + `test_portfolio_margin.py` (margin internals). Cover: corrected
liq-price formula (long 80.808.../short 118.811...), breach detection, penalty, the explicit
`min(loss+penalty, WB)` cap (Pitfall 2 — assert it triggers with a fat fee, NOT only MMR=0),
deterministic multi-breach order (Pitfall 3).

**`tests/unit/order/test_liquidation_reconcile.py` (NEW)** — mirror
`tests/unit/order/test_reconcile_manager.py`. Cover: registered forced-close Order →
EXECUTED→FILLED, `OrderTriggerSource.LIQUIDATION` tag, no new `FillStatus`, and the
no-order-in-storage silent no-op as a guard test (Pitfall 4).

**`tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` (NEW)** — mirror
`tests/unit/portfolio/test_cash_manager.py`. Regression: assert reads the prior-lock add-back
correctly (the defect: it reads 0 after `release_margin` pops the lock first).

**`tests/e2e/{forced_liq_long,forced_liq_short,levered_long_into_liquidation}/` (NEW)** — mirror
`tests/e2e/levered_long/test_levered_long_scenario.py` EXACTLY (the canonical white-box pattern,
NOT the `run_scenario`/`golden/` diff harness — the load-bearing asserts are liquidation
INTERNALS the trades/equity/summary CSVs don't capture). Key conventions from the analog:
- Module docstring carries the **full hand-computed arithmetic** inline (the `=== HAND COMPUTATION ===` block).
- A **synthetic ticker** (e.g. `LEVUSD`), NEVER `BTCUSD` (the spot oracle stays byte-exact 134 / 46189.87730727451).
- An **oracle-dark margin Instrument** declaring `max_leverage` / `maintenance_margin_rate` (+ now `liquidation_fee_rate`).
- Drives the REAL engine tick-by-tick via `system.engine.time_generator`; asserts on live read-model + cash/position state.
- A `bars.csv` (flat-OHLC so close == mark) in the leaf dir.
- The header has a `PARKED — NOT A GOLDEN` banner; for the FROZEN P4 set, replace with the
  D-10/D-12 freeze provenance once owner sign-off lands.

The parked P2/P3 leaves (`levered_long`, `short_roundtrip`, `short_carry`, `partial_cover`)
already follow this shape and currently have **NO `golden/` subdir** — D-10 freezes them
alongside the new P4 leaves (decide per-scenario: add `golden/` + `run_scenario`, or keep
white-box-asserted and "freeze" = commit-with-VERIFY-note).

---

### Cross-validation runners

**`scripts/cross_validate_limit.py` + `scripts/crossval/*_limit_run.py` (the v1.3 precedent).**
Add `scripts/crossval/{short,levered,liquidation}_run.py` and extend `scripts/cross_validate.py`
(or add a sibling `cross_validate_accounting.py`) following the `_limit` template. Key
conventions from `cross_validate_limit.py` (verified head):
- Reuses the generic reconcile helpers VERBATIM (`scripts/crossval/reconcile.py` —
  `align_trades` / `build_metric_table` / `recompute_headline` / `flag_divergences`).
- iTrader is the AUTHORITATIVE baseline; recompute EACH engine's headline through
  `itrader.reporting.metrics` for apples-to-apples.
- Nautilus behind a try-guard (non-gating); degrade to "not reconciled" on failure.
- **SCRIPT-ONLY (D-10):** these import the reference engines and must NEVER be imported under
  `tests/` or in `itrader/` (keeps `filterwarnings=["error"]` intact).
- For liquidation (D-08): `backtesting.py`/`backtrader` give DIRECTIONAL corroboration only
  (they don't byte-match the isolated formula) — the hand-computed e2e is PRIMARY.

**`tests/golden/CROSS-VALIDATION-ACCOUNTING.md` (NEW)** — sibling of `tests/golden/CROSS-VALIDATION.md`.
Mirror its structure: trade-level (PRIMARY) + metric-level (SECONDARY) reconciliation table,
per-divergence root-cause + disposition, and the **Owner Sign-Off** block (CROSS-VALIDATION.md:206-224):
```markdown
## Owner Sign-Off (D-12)

**Status: APPROVED** (YYYY-MM-DD, project owner). The owner accepts the per-scenario
verdict — [N BUG / N LEGITIMATE-DIFFERENCE; disposition] — as the basis for the
accounting-core golden freeze.

[blocking human-verify checkpoint evidence; per-scenario reconciliation; freeze authorization]
```
The freeze (D-10/D-12) happens ONLY after this block is filled at the blocking human-verify
checkpoint. Existing siblings `CROSS-VALIDATION-LIMIT.md` and the `REFREEZE-*.md` notes are
secondary templates for the freeze-provenance note.

---

## Shared Patterns

### Decimal end-to-end (money policy — applies to ALL new math)
**Source:** `itrader/core/money.py::to_money` / `quantize`; pattern visible across all analogs.
**Apply to:** the liq-price formula, penalty, capped loss, every new field.
- Enter the Decimal domain via `to_money(x)` (`Decimal(str(x))`) — NEVER `Decimal(float)` (Pitfall 5).
- Carry full 28-digit precision through `/(1−MMR)`; `quantize` ONLY at the `FillEvent` price boundary.
- `liquidation_fee_rate` / `maintenance_margin_rate` are `Decimal` fields on `Instrument` already.

### Determinism (double-run byte-identical gate)
**Source:** the deterministic-sort discipline; carry/mark use `bar_time` not wall clock.
**Apply to:** multi-breach ordering (Pitfall 3 — sort by symbol, then open-time, then position-id);
the forced-close `FillEvent.time = bar_time` (Pitfall 6); CashOperation timestamps event-derived.

### Universe read-model resolution (Instrument-first + config fallback)
**Source:** `maintenance_margin` (handler.py:307) + `_accrue_short_carry` (portfolio.py:657) +
P1 `min_order_size` (Instrument-first → ExchangeLimits).
**Apply to:** `liquidation_fee_rate` resolution (Instrument-first → `TradingRules` fallback) and
the per-position `maintenance_margin_rate` read; reuse the WR-02 unwired-Universe `StateError` guard.

### Fail-fast at the dispatch boundary (backtest re-raise)
**Source:** `update_portfolios_market_value` try/except (handler.py:464-477); `on_fill` (379-429);
`ReconcileManager.on_fill` re-raise-after-log (reconcile_manager.py:215-225).
**Apply to:** the liquidation check — publish `PortfolioErrorEvent` then re-raise on failure;
never swallow a breach-check error (corrupted equity is the project's cardinal sin).

### Default-off → oracle-dark byte-exact gate
**Source:** `borrow_rate = Decimal("0")` (instrument.py:90); `max_leverage = Decimal("1")` (portfolio.py:81).
**Apply to:** `liquidation_fee_rate = Decimal("0")` default + margin/shorts default-off → SMA_MACD
emits zero liquidations; `tests/integration/test_backtest_oracle.py` stays 134 / `46189.87730727451` (D-11).

---

## No Analog Found

None. Every seam Phase 4 needs already exists in-repo (the novelty is the trigger/price math
and minting the fill on the BAR route, not a new reconcile/settle/PnL path). The only genuinely
new artifacts are test files and the cross-validation evidence doc — all of which mirror an
existing sibling listed above.

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/config/`, `itrader/portfolio_handler/` (+ `cash/`, `position/`),
`itrader/order_handler/` (+ `reconcile/`), `itrader/events_handler/events/`, `tests/e2e/`,
`tests/unit/{portfolio,order}/`, `tests/golden/`, `scripts/` + `scripts/crossval/`.
**Files scanned:** ~22 (source + tests + scripts).
**Pattern extraction date:** 2026-06-16
