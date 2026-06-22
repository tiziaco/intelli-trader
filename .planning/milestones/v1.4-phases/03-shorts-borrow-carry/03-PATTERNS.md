# Phase 3: Shorts & Borrow Carry - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 13 source + 7 test targets
**Analogs found:** 13 / 13 (all in-codebase; the work is *wiring and gating*, not building — RESEARCH §"Don't Hand-Roll")

> This is a brownfield additive phase on the P1/P2 core. Almost every "analog" is the
> exact file/line being modified, with the pattern to mirror living *in the same file*.
> No file is built from scratch except three parked e2e scenario dirs (template:
> `tests/e2e/levered_long/`). Default-off gate keeps SMA_MACD byte-exact (134 /
> `46189.87730727451`).

---

## Indentation Map (read_first — VERIFIED live, overrides the CLAUDE.md heuristic)

The CLAUDE.md "handlers = tabs" rule has **three exceptions** in this phase's blast radius.
A normalized diff breaks a tab file; match the file exactly.

| File | Indentation | Note |
|------|-------------|------|
| `itrader/core/instrument.py` | **4-space** | core/ |
| `itrader/core/enums/portfolio.py` | **4-space** | core/ |
| `itrader/config/portfolio.py` | **4-space** | config/ |
| `itrader/reporting/cash_operations.py` | **4-space** | reporting/ |
| `itrader/order_handler/sizing_resolver.py` | **4-space** | ⚠ handler dir but 4-space (refactored module) |
| `itrader/portfolio_handler/cash/cash_manager.py` | **4-space** | ⚠ handler dir but 4-space (refactored module) |
| `itrader/portfolio_handler/portfolio_handler.py` | **4-space** | ⚠ handler dir but 4-space (refactored module) |
| `itrader/order_handler/admission/admission_manager.py` | **tabs** | handler |
| `itrader/strategy_handler/strategies_handler.py` | **tabs** | handler |
| `itrader/portfolio_handler/portfolio.py` | **tabs** | handler |
| `itrader/portfolio_handler/position/position.py` | **tabs** | handler |

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/instrument.py` | model (value object) | transform | self — `maintenance_margin_rate`/`max_leverage` fields (:79-80) | exact (mirror sibling field) |
| `core/enums/portfolio.py` | enum/config | transform | self — `RELEASE_RESERVATION` member (:69) | exact (add member) |
| `config/portfolio.py` | config | transform | self — `allow_short_selling`/`enable_margin` (:71-72, already present) | no change (read-only) |
| `strategy_handler/strategies_handler.py` | handler (registration) | event-driven | self — `add_strategy` guard (:253) | exact (relax existing guard) |
| `order_handler/admission/admission_manager.py` | manager (order/risk) | request-response | self — long-exit predicate (:703-715) | exact (generalize existing branch) |
| `order_handler/sizing_resolver.py` | service (sizing) | transform | self — `resolve_exit` (:147-186) | no change (reuse as-is) |
| `portfolio_handler/portfolio_handler.py` | handler | event-driven | self — `update_portfolios_market_value` (:417) + `maintenance_margin` `_universe` read (:306-325) | exact (thread bar time + universe) |
| `portfolio_handler/portfolio.py` | aggregate | event-driven | self — `update_market_value_of_portfolio` (:581) + `_process_transaction_margin` (:395-462) | exact (carry hook + WR sites) |
| `portfolio_handler/cash/cash_manager.py` | manager (ledger) | CRUD | self — `_create_operation` (:586) + `apply_fill_cash_flow` (:308) + `lock/release_margin` (:470-522) | exact (new debit via existing primitives) |
| `portfolio_handler/position/position.py` | value object | transform | self — SHORT `realised_pnl`/`unrealised_pnl` branches (:182-204) | no change (confirm only) |
| `reporting/cash_operations.py` | reporting (serializer) | transform | self — duck-typed `_row` (:107-126) | no change (enum-agnostic) |
| `universe/universe.py` | read-model | request-response | self — `instrument(symbol)` (:62-81) | no change (consumed) |
| 3× `tests/e2e/{short_roundtrip,short_carry,partial_cover}/` | test | event-driven | `tests/e2e/levered_long/test_levered_long_scenario.py` | exact (PARKED template) |

---

## Pattern Assignments

### `core/instrument.py` — add `borrow_rate` (D-01) — 4-space

**Analog:** the sibling INST-03 risk fields in the *same* frozen dataclass.

**Field block to mirror** (lines 76-83):
```python
    symbol: str
    price_precision: Decimal
    quantity_precision: Decimal
    maintenance_margin_rate: Decimal
    max_leverage: Decimal
    quote_currency: str = "USD"
    min_order_size: Decimal | None = None
    settles_funding: bool = False
```

**Pattern:** `@dataclass(frozen=True, slots=True, kw_only=True)` (:40). Because it is
`kw_only`, a *defaulted* field can go anywhere — add `borrow_rate: Decimal = Decimal("0")`
alongside the defaulted tail (next to `settles_funding`). **Pitfall 3 (RESEARCH):** the
default MUST be `Decimal("0")`, never the literal `0` (int re-enters int arithmetic and
fails `mypy --strict`). Every existing `Instrument(...)` / `derive_instruments` call keeps
working because it defaults. Update the class docstring `Fields` block (mirror the
`maintenance_margin_rate:` entry style at :65-70).

---

### `core/enums/portfolio.py` — add `BORROW_INTEREST` (D-03) — 4-space

**Analog:** the `CashOperationType` enum members in the *same* file.

**Member block to mirror** (lines 64-69):
```python
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSACTION_DEBIT = "TRANSACTION_DEBIT"
    TRANSACTION_CREDIT = "TRANSACTION_CREDIT"
    RESERVATION = "RESERVATION"
    RELEASE_RESERVATION = "RELEASE_RESERVATION"
```

**Pattern:** add one member `BORROW_INTEREST = "BORROW_INTEREST"`. The `_missing_`
case-insensitive parser (:71-78) handles it automatically. No serializer change needed
downstream (see `reporting/cash_operations.py` below).

---

### `strategy_handler/strategies_handler.py` — two-flag registration gate (SHORT-01/D-07) — tabs

**Analog:** the existing `LONG_ONLY`-only guard in `add_strategy`.

**Current guard to relax** (lines 253-258):
```python
		if strategy.direction is not TradingDirection.LONG_ONLY:
			raise ValueError(
				"Only LONG_ONLY is admissible until the margin/liquidation "
				"milestone — shorting (LONG_SHORT / SHORT_ONLY) requires the "
				"margin model (D-08/D-09)"
			)
```

**Fix shape (D-07):** admit non-`LONG_ONLY` only when **both** `allow_short_selling` AND
`enable_margin` are on; otherwise raise. The two flags live on `TradingRules`
(`config/portfolio.py:71-72`) — the handler must read them from the portfolio/system
config it already holds (planner discretion: confirm how `StrategiesHandler` reaches the
`TradingRules` instance; the flags are read, not changed). Update the `Raises` docstring
(:237-247) to describe the two-flag relaxation. Both flags default off → SMA_MACD
(`LONG_ONLY`) is unaffected, oracle byte-exact.

---

### `order_handler/admission/admission_manager.py` — side-agnostic cover-arm + clamp-to-flat (SHORT-02/D-05/D-06) — tabs

**Analog:** the long-only exit predicate in the *same* method `_resolve_signal_quantity`.

**Current bug site** (lines 703-715) — a BUY-cover on a short (`net_quantity < 0`) fails
this and falls through to entry sizing (:726), flipping the book long:
```python
		if signal_event.action is Side.SELL and open_position is not None and open_position.net_quantity > 0:
			return self.sizing_resolver.resolve_exit(
				open_position.net_quantity,
				signal_event.exit_fraction,
				signal_event.sizing_policy.step_size,
			)
```

**Fix shape (D-05/D-06)** — one generalized branch (NOT a second near-duplicate;
anti-pattern in RESEARCH). Detect a reduction once and pass the **magnitude**:
```python
		if open_position is not None and (
			(signal_event.action is Side.SELL and open_position.net_quantity > 0)
			or (signal_event.action is Side.BUY and open_position.net_quantity < 0)
		):
			# D-06 clamp-to-flat: pass the magnitude; resolve_exit returns at most |net|.
			return self.sizing_resolver.resolve_exit(
				abs(open_position.net_quantity),
				signal_event.exit_fraction,
				signal_event.sizing_policy.step_size,
			)
```

**Byte-exact guarantee (RESEARCH A2):** for `net_quantity > 0`, `abs()` is identity, so
the long-exit path passes the same operands → repr-exact. The clamp-to-flat (D-06) is
implicit: `resolve_exit` returns at most the full magnitude.

**Defense-in-depth — do NOT remove** the P2 over-close guard at
`portfolio.py:399-404` (`raise InvalidTransactionError`); the admission clamp is the
primary fix, the guard stays as defense (RESEARCH Pitfall 4).

**Related — WR-04 in the same file** (`_effective_leverage`, lines 586-601): floor the
effective leverage at `Decimal("1")` and guard a zero / sub-1 instrument cap. The
instrument-cap read is already `None`-guarded (`if self._universe is not None else
Decimal("1")`, :589-591) — mirror that defensiveness for the floor.

---

### `order_handler/sizing_resolver.py` — `resolve_exit` (reused, no change) — 4-space

**Analog:** itself — `resolve_exit` (lines 147-186) already operates on a **magnitude**
and treats `exit_fraction == 1` as a structural no-op (returns `net_quantity` unchanged,
:174-177) with a dust guard (:179-185).

```python
	def resolve_exit(self, net_quantity, exit_fraction, step_size) -> Decimal:
		if exit_fraction == ONE:
			return net_quantity          # D-07 structural no-op (repr-exact)
		sized = net_quantity * exit_fraction
		if step_size is not None:
			if (net_quantity - sized) < step_size:
				return net_quantity      # dust guard: take whole position
			sized = _quantize_to_step(sized, step_size)
		return sized
```

**Pattern:** the cover branch passes `abs(open_position.net_quantity)` — no resolver
change (RESEARCH "Don't Hand-Roll"). Add unit cases only.

---

### `portfolio_handler/portfolio_handler.py` — thread bar-time + universe into the carry hook (CARRY-01/D-02/D-04) — 4-space

**This is the PRIMARY new wiring (RESEARCH Pitfall 1 — the main hazard).**

**Current hook** (lines 417-451) discards everything except `bar.close`:
```python
    def update_portfolios_market_value(self, bar_events):
        if isinstance(bar_events, BarEvent):
            bar_events = [bar_events]
        prices = {}
        for bar_event in bar_events:
            for ticker, bar in bar_event.bars.items():
                prices[ticker] = bar.close
        active_portfolios = self.get_active_portfolios()
        for portfolio in active_portfolios:
            try:
                portfolio.update_market_value_of_portfolio(prices)   # :437 — no bar time, no universe
            except Exception as e:
                ...
                raise        # WR-08 fail-fast (keep)
```

**Fix:** thread `bar_event.time` (business time, per the frozen-event contract) AND the
injected `_universe` down into `update_market_value_of_portfolio` so carry can read the
per-symbol `borrow_rate` and derive the D-04 days basis. **Do NOT use the wall-clock stamp**
(`datetime.now(UTC)`) for accrual — it breaks the determinism double-run gate.

**`_universe` read pattern to mirror** (the proven `maintenance_margin` site, lines 306-325):
```python
    def maintenance_margin(self, portfolio_id):
        portfolio = self.get_portfolio(portfolio_id)
        total = Decimal("0")
        for position in portfolio.position_manager.get_all_positions().values():
            instrument = self._universe.instrument(position.ticker)   # :319 — the per-symbol read
            total += (instrument.maintenance_margin_rate * abs(position.net_quantity) * position.current_price)
        return total
```
The carry read uses the identical `self._universe.instrument(ticker).borrow_rate` shape.

**WR-02 (Pitfall 2):** `_universe` defaults to `None` (`:87`); the bare
`self._universe.instrument(...)` raises `AttributeError` if read with open positions
before `set_universe`. Add a fail-loud `StateError` (universe-unwired, with context) at
both the `maintenance_margin` site AND the new carry read site.

---

### `portfolio_handler/portfolio.py` — per-bar carry accrual + WR-01/03/05 (CARRY-01, WR residuals) — tabs

**Carry hook analog:** the mark method that loses bar time.

**Current mark** (lines 581-587):
```python
	def update_market_value_of_portfolio(self, prices: Mapping[str, float | Decimal]) -> None:
		"""Update portfolio market values."""
		if not self.can_trade():
			return
		self.position_manager.update_position_market_values(prices, datetime.now(UTC))   # :586 wall clock
		self._last_activity = datetime.now(UTC)
```

**Fix shape (D-02/D-04/D-08):** accept the threaded `bar_time` + `borrow_rate` source;
after marking, iterate OPEN shorts and accrue `days × close × |size| × rate/365`
(Decimal end-to-end), debiting realized cash once per short per bar via a
`BORROW_INTEREST` `CashOperation` (see cash_manager below). `days` = `(bar_time −
last_accrual.time)` in days from the threaded business time. Carry is a SEPARATE cash
debit — NEVER fold into `Position.realised_pnl` (D-08 anti-pattern). Planner discretion
(CONTEXT): per-position vs per-portfolio loop placement; the `last_accrual` timestamp
bookkeeping site (RESEARCH Open Q1/Q2 recommend per-position inside the existing mark
loop).

**WR-01/03/05 site — `_process_transaction_margin`** (lines 395-462, the FRAGILE seam):
```python
		if not is_increase and transaction.quantity > prior_qty:
			raise InvalidTransactionError(...)            # :399 CR-02-residual guard — KEEP (defense)
		commission = transaction.commission
		if is_increase and commission > 0:
			self.cash_manager.assert_funds_invariant(commission)   # :412 — WR-01 extends here
		...
		self.cash_manager.release_margin(str(position.id))         # :426/:440 — WR-03 lock/release symmetry
		self.cash_manager.lock_margin(str(position.id), position.aggregate_notional / leverage)  # :427-429
		...
		cash_delta = realised_increment + fraction * prior_entry_commission   # :452 — WR-05 commission drift site
```
- **WR-01:** add a settlement-side solvency assertion that the locked margin fits buying
  power (extend the `assert_funds_invariant` discipline at :411-412).
- **WR-03:** assert/comment lock-release symmetry at the assembly-failure site
  (the `release_margin`/`lock_margin` pairing :426-444).
- **WR-05:** the `fraction * prior_entry_commission` re-credit (:452) drifts on
  non-uniform-commission scale-in; track the pre-debited open commission as a per-lock
  accumulator (Pitfall 5). Oracle-dark (margin off on the golden path).

---

### `portfolio_handler/cash/cash_manager.py` — `BORROW_INTEREST` debit + WR residuals (D-03, WR-01/03/05) — 4-space

**Analog:** the existing ledger primitives in the *same* file — book the carry debit
through them, do not invent a new mechanism (RESEARCH "Don't Hand-Roll").

**Debit primitive to reuse — `apply_fill_cash_flow`** (line 308): the full-precision
signed cash delta primitive that skips the 2dp quantize (correctness-critical for the
equity curve). The carry debit can route through this OR a dedicated small debit helper
that calls `_create_operation`.

**Operation-record primitive — `_create_operation`** (lines 586-613):
```python
    def _create_operation(self, operation_type, amount, description, reference_id,
                         balance_before, balance_after, timestamp, fee=Decimal("0")):
        operation = CashOperation(
            operation_id=uuid_compat.uuid7(),       # single UUIDv7 scheme
            operation_type=operation_type,
            amount=amount, timestamp=timestamp,      # CALLER-supplied — pass bar business time, NOT now()
            description=description, fee=fee, reference_id=reference_id,
            balance_before=balance_before, balance_after=balance_after)
        self._storage.add_cash_operation(operation)
        return operation
```
**Pattern for the carry op:** pass `CashOperationType.BORROW_INTEREST`, the Decimal carry
amount, the bar's business `timestamp` (NOT `datetime.now(UTC)` — determinism), and
record `balance_before`/`balance_after`. Mirror the `RESERVATION`/`RELEASE_RESERVATION`
call shape (:422-430 / :454-462) but with a *real* balance change (carry is an outflow,
unlike reservations which leave the balance unchanged).

**Debit reference — `process_cash_flow`** (lines 263-306) shows the debit balance math +
`InsufficientFundsError` guard + `TRANSACTION_DEBIT` op to mirror:
```python
        if is_debit:
            available = self.available_balance
            if available < amount_decimal:
                raise InsufficientFundsError(required_cash=..., available_cash=...)
            new_balance = old_balance - amount_decimal
            operation_type = CashOperationType.TRANSACTION_DEBIT
```

**Margin lock/release primitives** (lines 470-522) — `lock_margin` / `release_margin`,
position-keyed, full-precision, idempotent. WR-03 lock-release symmetry and WR-05
accumulator land against these.

---

### `portfolio_handler/position/position.py` — SHORT PnL (SHORT-03/D-08, confirm only) — tabs

**Analog:** itself — the SHORT branches already exist; SHORT-03 builds on them, no change.

**`realised_pnl` SHORT branch** (lines 182-190):
```python
		elif self.side == PositionSide.SHORT:
			if self.buy_quantity == 0:
				return Decimal("0")
			else:
				return (
					((self.avg_sold - self.avg_bought) * self.buy_quantity) -   # |size| × (entry − exit)
					((self.buy_quantity / self.sell_quantity) * self.sell_commission) -
					self.buy_commission
				)
```
**`unrealised_pnl` SHORT branch** (lines 203-204):
```python
		elif self.side == PositionSide.SHORT:
			return (self.avg_price - self.current_price) * self.net_quantity
```
**Pattern:** D-08 — `Position.realised_pnl` stays clean trade PnL; carry nets at the
cash/equity level. Add unit cases only; do not touch the branches.

---

### `reporting/cash_operations.py` — duck-typed serializer (no change) — 4-space

**Analog:** itself — the enum-agnostic `_row` builder.

**Pattern** (lines 114-126): it serializes `op.operation_type.name` — any new enum member
appears automatically:
```python
        if not hasattr(op.operation_type, "name"):
            raise TypeError(...)
        return {
            "correlation": _correlation(op.reference_id),
            "operation_type": op.operation_type.name,   # :122 — enum-agnostic
            "amount": float(op.amount),                  # float() ONLY at serialization edge
            ...
        }
```
**No change needed** (RESEARCH anti-pattern: do NOT edit this for the new op).

---

### 3× parked e2e scenarios (D-10) — new dirs

**Analog/template:** `tests/e2e/levered_long/test_levered_long_scenario.py` (+ its
`bars.csv` + `__init__.py`).

**Pattern (PARKED, NOT `--freeze`d):**
- Every asserted number is a HAND-COMPUTED literal with the arithmetic shown inline.
- Synthetic instrument only — **NEVER BTCUSD** (the spot oracle must stay byte-exact
  134 / `46189.87730727451`). Declare a synthetic symbol with a realistic crypto
  `borrow_rate` (planner discretion, oracle-dark).
- Drives the REAL `SIGNAL → ORDER → FILL → PORTFOLIO` run path (no hand-built events
  injected onto the queue; signals fan out from a strategy through the BAR route).
- Asserts on live read-model + cash/position state (margin internals), NOT the
  golden-diff harness.
- Owner-gated human-verify checkpoint; frozen as golden only at Phase 4 / XVAL-01.

| New dir | Scenario | Key assertions |
|---------|----------|----------------|
| `tests/e2e/short_roundtrip/` | SELL-to-open → BUY-to-cover | realised short PnL = `|size|×(entry−exit) − commissions`; lock released |
| `tests/e2e/short_carry/` | multi-bar held short | per-bar `BORROW_INTEREST` debits; equity = PnL − Σ carry; determinism double-run identical |
| `tests/e2e/partial_cover/` | BUY-cover `exit_fraction < 1` | reduces (not closes); remaining short carries on |

Each dir needs `__init__.py` + `bars.csv` + `test_*_scenario.py`, mirroring `levered_long/`.

---

## Shared Patterns

### Byte-exact gate via default-off
**Source:** `config/portfolio.py:71-72` (`allow_short_selling=False`, `enable_margin=False`),
`core/instrument.py` (`borrow_rate=Decimal("0")` — new).
**Apply to:** ALL new behavior. SMA_MACD is `LONG_ONLY` / margin-off / rate-0 → every
new path is gated and oracle-dark. Hold 134 / `46189.87730727451` at every step.

### Decimal end-to-end (carry formula included)
**Source:** Money Policy (CLAUDE.md); `core/money.py::to_money`.
**Apply to:** the carry formula `days × close × |size| × rate/365` stays Decimal;
`borrow_rate` default `Decimal("0")` (Pitfall 3); `float()` only at the serialization
edge (`cash_operations.py:123`).

### Determinism seam — business time, never wall clock
**Source:** the carry days basis (D-04); contrast with `portfolio.py:586`
(`datetime.now(UTC)`) and the admin-path `timestamp=datetime.now(UTC)` calls
(`cash_manager.py:429/461`).
**Apply to:** the carry accrual MUST use `bar_event.time` (threaded through the hook) and
pass it as the `_create_operation` `timestamp`. A wall-clock stamp breaks the double-run
byte-identical gate.

### `_universe` read + WR-02 fail-loud guard
**Source:** `portfolio_handler.py:319` (the proven `instrument(ticker)` read),
`universe/universe.py:62-81` (the resolver, raises `KeyError` on non-member).
**Apply to:** the new carry `borrow_rate` read AND the existing `maintenance_margin` read
— both must guard `_universe is None` with a `StateError` (universe-unwired, context-rich)
when positions exist, never a bare `AttributeError`.

### CashOperation ledger primitive (audit record)
**Source:** `cash_manager.py:586-613` (`_create_operation`, UUIDv7 + caller timestamp +
balance_before/after).
**Apply to:** the `BORROW_INTEREST` debit — book through this primitive; the serializer
(`cash_operations.py`) picks it up automatically.

### FRAGILE margin/settlement seam — single touch
**Source:** `portfolio.py:395-462` (`_process_transaction_margin`),
`cash_manager.py:470-522` (lock/release).
**Apply to:** shorts wiring + WR-01/03/05 land together under the single P4/XVAL-01
owner-gated re-baseline (D-09). Keep the CR-02-residual guard (`portfolio.py:399-404`) as
defense-in-depth — do NOT remove it.

---

## No Analog Found

None. Every source change mirrors an existing pattern in (usually) the same file; the
only built-from-scratch artifacts are the three parked e2e dirs, which copy the
`tests/e2e/levered_long/` template verbatim.

---

## Test Analog Map (Wave 0 — verify file names; RESEARCH cited two that don't exist verbatim)

| Requirement | Test file | Status |
|-------------|-----------|--------|
| SHORT-02 cover-arm, over-cover-clamp, WR-04 leverage-floor | `tests/unit/order/test_admission_rules.py` | EXISTS — add cases |
| SHORT-02 resolver behavior | `tests/unit/order/test_sizing_resolver.py` | EXISTS — add cases |
| SHORT-01 two-flag registration gate | NEW `tests/unit/strategy/test_strategies_handler_registration.py` (resolved: RESEARCH cited `test_strategies_handler.py` which does NOT exist; plans create a dedicated registration test module) | resolved |
| SHORT-03 short PnL | `tests/unit/portfolio/test_position_manager.py` (resolved: RESEARCH cited `test_position.py` which does NOT exist; use the existing position-manager module) | resolved |
| CARRY-01 borrow-interest op, WR-03 release-symmetry | `tests/unit/portfolio/test_cash_manager.py` | EXISTS — add cases |
| CARRY-01 days-basis / accrual formula | `tests/unit/portfolio/test_carry.py` | NEW |
| WR-01 funds invariant, WR-05 accumulator | `tests/unit/portfolio/test_portfolio_margin.py` | NEW (verify; `test_portfolio.py`/`test_portfolio_update.py` exist) |
| WR-02 universe-unwired → StateError | `tests/unit/portfolio/test_portfolio_handler.py` | EXISTS — add case |

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/config/`, `itrader/order_handler/`,
`itrader/portfolio_handler/`, `itrader/strategy_handler/`, `itrader/reporting/`,
`itrader/universe/`, `tests/e2e/`, `tests/unit/{order,portfolio,strategy}/`.
**Files read:** 12 source files (targeted ranges) + directory listings.
**Indentation:** verified live per file (3 handler-dir files are 4-space, overriding the
CLAUDE.md "handlers = tabs" heuristic — see Indentation Map).
**Pattern extraction date:** 2026-06-15
