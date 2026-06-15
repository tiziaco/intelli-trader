# Phase 2: Margin Accounting & Leverage - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 13 (12 modified + 1 new compose-root wiring task; tests tracked separately in RESEARCH Wave 0)
**Analogs found:** 13 / 13 (every change mirrors an in-repo precedent — Phase 2 is almost entirely "gate an existing primitive behind `enable_margin`" + one new container + one new sizing arm)

> Phase 2 is additive and brownfield. There are **no greenfield files** — every entry below is a surgical edit to an existing module, and the analog is most often *the same file's existing sibling pattern*. The byte-exact gate (SMA_MACD: 134 trades / `final_equity 46189.87730727451`) is held by keeping every new arm gated and oracle-dark.

---

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `itrader/core/sizing.py` | model (value object / typed vocabulary) | transform | `RiskPercent` (same file, line 128) | exact |
| `itrader/order_handler/sizing_resolver.py` | service (resolver) | transform | `RiskPercent` arm (same file, line 113) | exact |
| `itrader/events_handler/events/signal.py` | model (frozen event) | event-driven | `sizing_policy`/`exit_fraction` fields (same file) | exact |
| `itrader/config/portfolio.py` | config (Pydantic model) | config | `enable_margin`/`allow_short_selling` (same file, `TradingRules` line 66) | exact |
| `itrader/order_handler/admission/admission_manager.py` | service (admission/risk gate) | request-response | over-cash REJECTED path (same file, lines 227-248) | exact |
| `itrader/portfolio_handler/cash/cash_manager.py` | manager (cash authority) | CRUD (stateful ledger) | `reserve_cash`/`release_reservation` (same file, lines 365-448) | role-match (new key dimension: position-keyed) |
| `itrader/portfolio_handler/portfolio.py` | manager (settlement orchestration) | request-response | `process_transaction` spot branch (same file, line 270) | exact (add `enable_margin` branch) |
| `itrader/portfolio_handler/position/position.py` | model (position accounting) | transform | existing money fields (`to_money` at construction) | role-match (new attribute: `leverage`) |
| `itrader/portfolio_handler/position/position_manager.py` | manager (position lifecycle) | event-driven | `process_position_update` open/update/close (same file) | role-match |
| `itrader/core/portfolio_read_model.py` | model (Protocol read boundary) | request-response | `total_equity()` Protocol member (same file, line 214) | exact |
| `itrader/portfolio_handler/portfolio_handler.py` | service (handler / read-model impl) | request-response | `total_equity()` impl (line 270) + `update_config` (line 454) | exact |
| `itrader/core/instrument.py` | model (frozen value object) | — | fields already inert from Phase 1 (no change) | n/a (consume-only) |
| `itrader/universe/universe.py` | model (read-model facade) | request-response | `instrument(symbol)` (line 62) — no change; new INJECTION into order domain | n/a (wiring gap, see Shared Patterns) |

**Indentation per file (VERIFIED — `grep -P '^\t'`):**

| File | Indentation |
|------|-------------|
| `core/sizing.py` | **4 spaces** |
| `order_handler/sizing_resolver.py` | **4 spaces** (RESEARCH flagged "VERIFY" — confirmed SPACES, not tabs) |
| `events_handler/events/signal.py` | **4 spaces** |
| `config/portfolio.py` | **4 spaces** |
| `core/portfolio_read_model.py` | **4 spaces** |
| `core/instrument.py` | **4 spaces** |
| `universe/universe.py` | **4 spaces** |
| `portfolio_handler/cash/cash_manager.py` | **4 spaces** |
| `portfolio_handler/portfolio_handler.py` | **4 spaces** |
| `portfolio_handler/position/position_manager.py` | **4 spaces** |
| `order_handler/admission/admission_manager.py` | **TABS** |
| `portfolio_handler/portfolio.py` | **TABS** |
| `portfolio_handler/position/position.py` | **TABS** |

> CLAUDE.md hazard: a mixed-indentation diff breaks a tab file. The three TAB files above (`admission_manager.py`, `portfolio.py`, `position.py`) are the ones to watch — match tabs exactly.

---

## Pattern Assignments

### `itrader/core/sizing.py` — new `LeveredFraction` sizing kind (D-07) [4-space file]

**Analog:** `RiskPercent` dataclass + `_require_positive` guard + the `SizingPolicy` union (same file).

**Frozen-dataclass pattern** (mirror `RiskPercent`, lines 128-149):
```python
@dataclass(frozen=True, slots=True)
class RiskPercent:
    risk_pct: Decimal
    step_size: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive("RiskPercent", "risk_pct", self.risk_pct)
        _validate_step_size("RiskPercent", self.step_size)
```
The new `LeveredFraction` copies this shape exactly. **Critical divergence:** it uses `_require_positive` (`f > 0`), NOT `_require_unit_interval` — `FractionOfCash` (lines 100-105) keeps its strict `(0, 1]` guard intact (oracle-dark byte-exact path untouched). The `f > 1 only when enable_margin` guard does NOT live here (the policy is config-agnostic) — it lives in `AdmissionManager` (RESEARCH A3).

**Union growth (D-02 growth rule)** — line 152-154:
```python
# D-01/D-02: the resolver match-dispatches on exactly these kinds, closing
# with assert_never so mypy --strict fails on an unhandled kind.
SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent
```
Add the new kind to this union. Adding it WITHOUT the resolver `case` arm breaks `mypy --strict` at `assert_never` — the intended fail-loud growth gate (RESEARCH Pitfall 5).

**Available guards** (lines 62-81): `_require_positive(kind, field, value)` (`> 0`), `_require_unit_interval(kind, field, value)` (`(0, 1]`), `_validate_step_size(kind, step_size)`. Reuse `_require_positive` — do NOT add a new guard.

**`SignalIntent.leverage` mirror field** (lines 211-253): the strategy-return contract. Add `leverage: Decimal = Decimal("1")` here too (the handler fans it onto `SignalEvent`, same pattern as `sizing_policy`). Note: `SignalIntent` is `kw_only=True` so a defaulted field is legal among required ones.

---

### `itrader/order_handler/sizing_resolver.py` — new resolver arm (D-07/LEV-02) [4-space file]

**Analog:** the `RiskPercent` case arm in `resolve_entry` (same file, lines 113-122).

**Resolver arm pattern** (mirror lines 113-122):
```python
case RiskPercent():
    if stop is None or stop == price:
        raise SizingPolicyViolation(
            "RiskPercent requires stop_loss distinct from price: "
            f"got stop={stop!r} at price={price!r}"
        )
    equity = self._read_model.total_equity(portfolio_id)
    qty = (equity * policy.risk_pct) / abs(price - stop)
```
The new arm reads `total_equity()` the same way (D-12 mark-to-market) and computes `qty = (policy.fraction * equity) / to_money(price)` (notional = f × equity). It does NOT know `enable_margin` (resolver purity, RESEARCH A3) — `f > 1` is admitted/rejected downstream in `AdmissionManager`.

**Exhaustiveness gate** (lines 123-124):
```python
case _:
    assert_never(policy)
```
Adding the union member (above) forces a new `case` here or `mypy --strict` fails — add both in the same change (RESEARCH Pitfall 5).

**Import to extend** (line 39):
```python
from itrader.core.sizing import FixedQuantity, FractionOfCash, RiskPercent, SizingPolicy
```
Add the new kind to this import. **Money entry:** use `to_money(price)` (line 37 import already present) — NEVER `Decimal(float)`. **Read boundary:** `self._read_model` is the injected `PortfolioReadModel` Protocol only (line 66-67) — the resolver never touches the concrete handler.

---

### `itrader/events_handler/events/signal.py` — `leverage` field (D-03) [4-space file]

**Analog:** the existing defaulted fields on `SignalEvent` (`exit_fraction`, `allow_increase`, `sltp_policy`, `quantity` — lines 91-95).

**Field pattern** (mirror lines 89-95):
```python
sizing_policy: SizingPolicy
direction: TradingDirection
allow_increase: bool = False
max_positions: int = 1
exit_fraction: Decimal = Decimal("1")
sltp_policy: SLTPPolicy | None = None
quantity: Decimal | None = None
```
Add `leverage: Decimal = Decimal("1")`. The class is `@dataclass(frozen=True, slots=True, kw_only=True)` (line 19) — `kw_only` means a defaulted field can sit among required ones. Default `Decimal("1")` keeps SMA_MACD byte-exact (the strategy never sets it). Add a `Parameters` docstring entry mirroring the `exit_fraction` block (lines 62-65). **Decimal literal MUST be string-path** (`Decimal("1")`, never `Decimal(1.0)`).

---

### `itrader/config/portfolio.py` — `TradingRules.max_leverage` (D-14) [4-space file]

**Analog:** the existing `enable_margin` / `allow_short_selling` bools in `TradingRules` (lines 66-79).

**Config-field pattern** (mirror lines 66-79):
```python
class TradingRules(BaseModel):
    """Trading rules and preferences."""

    model_config = ConfigDict(extra="forbid")

    allow_short_selling: bool = False
    enable_margin: bool = False
    enable_options: bool = False
    enable_futures: bool = False
    min_trade_amount: Decimal = Decimal("100.0")
    ...
```
Add `max_leverage: Decimal = Decimal("1")` here as the account-wide cap. Default `1` → byte-exact. `Decimal` is already imported (line 8). Note `extra="forbid"` (line 69) — the field MUST be declared or any caller passing it fails. NO `default_leverage` (D-14 — leverage is a strategy/signal concern). For a bounded field, the established style uses `Field(default=..., gt=0)` (see `PortfolioLimits`, lines 38-44) — consider `Field(default=Decimal("1"), ge=1)` if a floor guard is wanted (planner discretion).

---

### `itrader/order_handler/admission/admission_manager.py` — leverage cap + margin reservation + over-margin reject (D-01/D-04/D-05/D-08) [TAB file]

**Analog:** the existing cash-reservation gate + over-cash REJECTED path (same file, lines 227-248). This is the **byte-exact site #1**.

**The reservation + reject pattern to branch** (lines 227-248):
```python
if self.portfolio_handler is not None and primary.action is Side.BUY:
    cost = primary.price * primary.quantity + self._estimate_commission(primary)
    try:
        self.portfolio_handler.reserve(
            primary.portfolio_id, primary.id, cost)
        reserved_primary = primary
    except InsufficientFundsError as e:
        error_msg = f"Cash reservation failed: {e}"
        self.logger.warning('%s for %s %s', error_msg,
                        signal_event.ticker, signal_event.action)
        primary.add_state_change(
            OrderStatus.REJECTED,
            str(e),
            triggered_by=OrderTriggerSource.CASH_RESERVATION,
        )
        self.order_storage.add_order(primary)
        return [OperationResult.failure_result(error_msg,
            error_details=str(e),
            operation_type=OrderOperationType.CASH_RESERVATION)]
```

**Phase-2 branch (Pattern 1, byte-exact gate)** — only the `cost` computation changes; the `try/except → REJECTED` block is **reused verbatim** (D-01):
```python
notional = primary.price * primary.quantity
commission = self._estimate_commission(primary)
if enable_margin:                                    # D-09 gate
    cost = notional / effective_leverage + commission   # D-08 initial_margin
else:
    cost = notional + commission                     # UNCHANGED — operand-for-operand
                                                     # identical to line 228; == notional/1
```
**CRITICAL (RESEARCH Pitfall 4):** the spot arm must NOT route through `notional / 1` — Decimal division is context-sensitive and can shift the exponent. Use a real `if enable_margin:` branch; the `False` arm computes `notional + commission` with NO division.

**Leverage cap helper (D-04/D-05)** — new method, lives here because admission is the order/risk layer:
```python
def _effective_leverage(self, signal_event) -> Decimal:
    if not self._enable_margin:                 # D-04: forced to 1 when margin off
        return Decimal("1")                     # spot byte-exact — no instrument read
    instr_cap = (self._universe.instrument(signal_event.ticker).max_leverage
                 if self._universe is not None else Decimal("1"))
    pf_cap = self._portfolio_max_leverage       # from TradingRules.max_leverage (D-14)
    requested = signal_event.leverage           # D-03 scalar, default Decimal("1")
    capped = min(requested, instr_cap, pf_cap)
    if requested > capped:                      # D-05: clamp + warn, NOT reject
        self.logger.warning("leverage clamped to cap",
                            requested=str(requested), capped=str(capped),
                            ticker=signal_event.ticker)
    return capped
```

**Constructor injection seam (BLOCKING — RESEARCH Pitfall 1):** `AdmissionManager.__init__` (lines 60-76) currently takes `order_storage, logger, order_validator, sizing_resolver, portfolio_handler, commission_estimator, brackets, bracket_manager` — **no instrument seam**. `Universe` is injected only into `SimulatedExchange` today. Add `Optional[Universe] = None` (plus `enable_margin` / `portfolio_max_leverage`) to the constructor and thread it through `OrderManager` to the compose root. With `None` or `enable_margin=False`, the cap degrades to 1 with no instrument read (byte-exact). See Shared Patterns → Instrument-access seam.

**`f > 1` gate (D-07/LEV-02, RESEARCH A3):** a `LeveredFraction(fraction > 1)` reaching admission with `enable_margin=False` → audited REJECTED (reuse the same `add_state_change(REJECTED, ...)` path above). This guard lives HERE, not in the resolver.

**Money discipline:** `to_money` imported (line 42); intermediates never quantized (line 226 comment). Indentation: **TABS** — match exactly.

---

### `itrader/portfolio_handler/cash/cash_manager.py` — position-keyed locked-margin container (D-10/D-11) [4-space file]

**Analog:** the order-keyed `reserve_cash` / `release_reservation` mechanism (same file, lines 365-448) and the `available_balance` property (line 107).

**The order-keyed reservation pattern to mirror** (lines 365-399, the reserve half):
```python
def reserve_cash(self, amount, description, reference_id) -> None:
    amount_decimal = to_money(amount)
    if amount_decimal <= 0:
        raise InvalidTransactionError(...)
    available = self.available_balance
    if available < amount_decimal:
        raise InsufficientFundsError(
            required_cash=float(amount_decimal),
            available_cash=float(available))
    self._storage.add_reservation(reference_id, amount_decimal)
    self._create_operation(CashOperationType.RESERVATION, ...)
```
The new locked-margin container mirrors `add_reservation`/`pop_reservation` but is **keyed by `position_id`, not `order_id`** (D-10, RESEARCH Pitfall 2 — distinct lifecycle). It is locked on the opening fill's SETTLEMENT and released on the closing fill, surviving the order's terminal reservation release.

**`available_balance` to extend** (lines 107-109) — the single buying-power figure (RESEARCH Pitfall 6):
```python
@property
def available_balance(self) -> Decimal:
    """Get available cash balance (total - reserved)."""
    return self._balance - self._storage.get_reserved_cash()
```
Becomes `balance − reserved − locked_margin` (D-10: one cash authority). In spot mode `locked_margin == Decimal("0")` → byte-exact (`x - Decimal("0")` preserves `x`). **CRITICAL:** the empty container default MUST be a clean `Decimal("0")` (RESEARCH Pitfall 6) — verify the storage seam returns a clean zero, and prefer subtracting a provably-zero default.

**Full-precision discipline:** `reserve_cash` deliberately skips `_validate_and_convert_amount`'s 2dp quantize (line 384 — full precision so release == reserve exactly). The locked-margin lock/release MUST do the same. `apply_fill_cash_flow` (lines 288-340) is the settlement primitive that also skips quantize (Pitfall 1, line 290-298) — the PnL settlement on close rides this. `assert_funds_invariant` (lines 342-363) checks `required` against `self._balance` (NOT reservation-adjusted) — in margin mode feed it the commission-only delta on open (RESEARCH OQ3).

---

### `itrader/portfolio_handler/portfolio.py` — lock-and-settle settlement branch (D-09/D-11, Pattern 2) [TAB file]

**Analog:** the existing `process_transaction` spot settlement sequence (same file, lines 270-322). This is the **byte-exact site #2**.

**The settlement sequence to branch** (lines 300-319):
```python
# 2. Funds invariant on the debit side (D-10).
net_delta = transaction.net_cash_delta
if net_delta < 0:
    self.cash_manager.assert_funds_invariant(-net_delta)
# 3. Position mutation.
position = self.position_manager.process_position_update(transaction)
transaction.position_id = position.id
# 4. Cash apply — full-precision signed delta, one ledger entry.
self.cash_manager.apply_fill_cash_flow(
    amount=net_delta,
    fee=transaction.commission,
    description=f"Transaction {transaction.type.name} {transaction.ticker}",
    reference_id=str(transaction.id),
    timestamp=transaction.time,
)
# 5. Record.
self.transaction_manager.record(transaction)
```
**Phase-2 branch (Pattern 2):** gate on `enable_margin`. **Spot arm: UNCHANGED** — still calls `apply_fill_cash_flow(net_delta, ...)`. **Margin arm:** on OPEN debit ONLY commission (D-08), lock `aggregate_notional / L` into `CashManager`'s position-keyed container; on CLOSE settle realized PnL + release the locked margin (RESEARCH Pattern 2 / Pitfall 3). The lock/release is driven from `process_transaction` (it holds both the returned `Position` and the `CashManager`) — keep `PositionManager` cash-agnostic (RESEARCH OQ2).

**The spot debit primitive** — `Transaction.net_cash_delta` (`transaction/transaction.py`, lines 84-107):
```python
@property
def net_cash_delta(self) -> Decimal:
    if self.type == TransactionType.BUY:
        return -(self.price * self.quantity + self.commission)
    else:  # SELL
        return self.price * self.quantity - self.commission
```
Margin mode must NOT debit this full notional on open (RESEARCH Pitfall 3 — double-count). Indentation: **TABS**.

---

### `itrader/portfolio_handler/position/position.py` — one-leverage-per-position + aggregate notional (D-06/D-11) [TAB file]

**Analog:** the existing money-field construction pattern (same file, lines 31-62) — every money field enters via `to_money` at the construction boundary.

**Construction-boundary pattern** (lines 49-58):
```python
# Money fields enter the Decimal domain at the construction boundary (D-04):
self.current_price = to_money(price)
self.buy_quantity = to_money(buy_quantity)
self.avg_bought = to_money(avg_bought)
...
```
Add a `leverage` attribute set at open (D-06: one effective leverage per position, isolated margin). A scale-in clamps a differing `signal.leverage` to the position's leverage (documented). `aggregate_notional` is derived from `net_quantity` × `avg_price` (existing `market_value` property, lines 69-79, shows the direction-aware shape). `locked_margin = aggregate_notional / L` is computed off these (D-11 pro-rata, recomputed as fills aggregate — NOT stored on the Position; the lock lives in `CashManager`). Indentation: **TABS**.

---

### `itrader/portfolio_handler/position/position_manager.py` — scale-in/partial-close margin proportioning (D-11) [4-space file]

**Analog:** the open/update/close lifecycle in `process_position_update` (same file, lines 95-194).

**Lifecycle dispatch pattern** (lines 95-115):
```python
def process_position_update(self, transaction: Transaction) -> Position:
    ticker = transaction.ticker
    existing_position = self._storage.get_position(ticker)
    if existing_position:
        return self._update_existing_position(existing_position, transaction)
    else:
        return self._create_new_position(transaction)
```
The open (`_create_new_position`, line 117) / scale-in+partial-close (`_update_existing_position`, line 155) / full-close (`_should_close_position` → `_close_position`, lines 184-193) transitions are where the margin lifecycle is OBSERVED — but `PositionManager` stays **cash-agnostic** (it has no `CashManager` access today; preserve that, RESEARCH OQ2). The lock/release recompute (`locked_margin = new_aggregate_notional / L`; partial close releases `p × locked_margin`, settles `p × PnL`) is driven from `Portfolio.process_transaction` reading the returned `Position`, NOT from here. This file carries the one-leverage-per-position invariant enforcement (clamp scale-in leverage to the position's). Indentation: **4 spaces**.

---

### `itrader/core/portfolio_read_model.py` — `maintenance_margin` / `margin_ratio` Protocol members (D-13/MARGIN-03) [4-space file]

**Analog:** the `total_equity()` Protocol member (same file, lines 214-233).

**Protocol-member pattern** (lines 214-233):
```python
def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
    """Return total equity: full cash balance plus position market values.
    ...
    """
    ...
```
Add `maintenance_margin(self, portfolio_id) -> Decimal` and `margin_ratio(self, portfolio_id) -> Decimal` as compute-on-demand accessors (D-13 — NOT a stored `Position` field; D-13a live-readiness). Same docstring style (`Parameters`/`Returns`), `...` body (Protocol). `maintenance_margin = Σ (instr.maintenance_margin_rate × |size| × current_price)` over open positions; `margin_ratio = total_equity() / maintenance_margin`. Both read honestly when breached (D-16 — no clamp). Indentation: **4 spaces**.

---

### `itrader/portfolio_handler/portfolio_handler.py` — read-model impl + `update_config` (D-13/D-15) [4-space file]

**Analog:** the `total_equity()` impl (line 270) for the read-model methods; `update_config` (line 454) for config plumbing.

**Read-model impl pattern** (`total_equity`, lines 270-285):
```python
def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
    portfolio = self.get_portfolio(portfolio_id)
    return (
        portfolio.cash_manager.balance
        + portfolio.position_manager.get_total_market_value()
    )
```
Implement `maintenance_margin` / `margin_ratio` in the same block (lines 234-285): iterate open positions, resolve each ticker's `Instrument` via the injected `Universe` (the order-domain seam mirrors the same injection need here), accumulate Decimal. Same Decimal-native discipline (RESEARCH Pitfall 8 — never the float `Portfolio.total_equity` property). Existing accessors to mirror for shape: `available_cash` (234), `reserve`/`release` (250-258), `open_position_count` (265).

**`update_config` seam (D-15, COMP-02)** — lines 454-473:
```python
def update_config(self, updates: Dict[str, Any]) -> None:
    merged = deep_merge(self.config_data.model_dump(), updates)
    try:
        new_config = PortfolioConfig.model_validate(merged)
    except pydantic.ValidationError as e:
        raise ConfigurationError(reason=str(e)) from e
    self.config_data = new_config  # atomic GIL-safe reference swap (D-11)
    self.max_portfolios = self.config_data.limits.max_portfolios
    self.logger.info("Configuration updated successfully", updates=updates)
```
`max_leverage` rides this UNCHANGED — it is a `TradingRules` field, so `deep_merge → model_validate → atomic-swap` already carries it (D-15). The only possible addition: cache a `max_leverage` derived value after the swap (mirror the `self.max_portfolios` re-derive on line 472) IF admission reads it off the handler. Caveat (D-15): open positions keep opened-under terms; new config applies only to new orders. Indentation: **4 spaces**.

---

### `itrader/core/instrument.py` — NO CHANGE (consume-only)

The `maintenance_margin_rate` and `max_leverage` fields (lines 79-80) landed **inert in Phase 1** (`@dataclass(frozen=True, slots=True, kw_only=True)`, Decimal-typed). Phase 2 simply consumes them via `Universe.instrument(symbol)`. The parked leveraged-long scenario sets realistic crypto BTCUSD values (planner discretion; oracle-dark). No edit to this file.

---

## Shared Patterns

### The byte-exact `enable_margin` gate (the central cross-cutting pattern)
**Source:** RESEARCH Pattern 1; precedent is the existing spot expressions.
**Apply to:** `admission_manager.py` (reservation `cost`), `portfolio.py` (settlement), `cash_manager.py` (`available_balance`), `_effective_leverage` (force-to-1).
**Rule:** every new behavior branches on `enable_margin`; the `False` arm is the EXISTING expression, operand-for-operand untouched. NEVER route the spot path through `/ leverage` even with `leverage == 1` (Decimal exponent risk — RESEARCH Pitfall 4). Use a real `if enable_margin:` branch.

### Instrument-access seam into the order domain (BLOCKING wiring gap — RESEARCH Pitfall 1)
**Source:** `universe/universe.py::instrument(symbol)` (line 62) — currently injected ONLY into `SimulatedExchange` (`execution_handler/exchanges/simulated.py`, `set_universe`).
**Apply to:** `AdmissionManager.__init__` (and thread through `OrderManager` to the compose root `trading_system/`).
```python
def instrument(self, symbol: str) -> Instrument:
    """Return the resolved Instrument for symbol. Raises KeyError if not a member."""
    return self._instruments[symbol]
```
Inject `Optional[Universe] = None` for v1 (smallest seam — the order domain already injects concrete read-models like `BacktestBarFeed`). With `None` or `enable_margin=False`, the leverage cap degrades to 1 with no instrument read (byte-exact). **The planner MUST add a compose-root wiring task.** (Open: concrete `Universe` vs a narrow `InstrumentReadModel` Protocol — RESEARCH recommends `Optional[Universe]` for v1.)

### Audited REJECTED path (D-01 / V5 fail-loud)
**Source:** `admission_manager.py` lines 233-248 (the `InsufficientFundsError` → `add_state_change(REJECTED, triggered_by=CASH_RESERVATION)` → persist → `OperationResult.failure_result` path).
**Apply to:** over-margin reject (MARGIN-02) and the `f > 1 with enable_margin=False` gate (LEV-02). Reuse verbatim — empty cash ledger, no reservation, audited entity, nothing emitted. Rejected signals never vanish.

### Decimal money discipline (locked project policy)
**Source:** `core/money.py::to_money` / `quantize`; `core/sizing.py` Pitfall 1.
**Apply to:** every new file. Enter Decimal only via `to_money(x)` (string path) — NEVER `Decimal(float)`. Every Decimal literal is string-constructed (`Decimal("1")`). Carry full precision through margin math (`notional / L`, commission, equity); quantize only at money boundaries via `quantize(value, instrument, kind)`.

### `assert_never` exhaustiveness growth gate (D-02)
**Source:** `sizing_resolver.py` line 124.
**Apply to:** the union grows in `core/sizing.py` AND the `case` arm is added in `sizing_resolver.py` in the SAME change. Tests run under `filterwarnings=["error"]` + `--strict-markers` — any unexpected warning also fails (RESEARCH Pitfall 5).

### Don't-hand-roll inventory (RESEARCH)
| Need | Reuse (don't build) |
|------|---------------------|
| Pending-order cash reservation | `CashManager.reserve_cash` / `release_reservation` |
| Over-margin REJECTED | existing `InsufficientFundsError` → REJECTED path (`admission_manager.py:233-248`) |
| Equity for sizing/margin checks | `PortfolioReadModel.total_equity()` (impl `portfolio_handler.py:270`) |
| Symbol → Instrument | `Universe.instrument(symbol)` (`universe.py:62`) |
| Decimal entry / rounding | `to_money(x)` / `quantize(value, instrument, kind)` |
| Config merge+validate+swap | `PortfolioHandler.update_config` (`portfolio_handler.py:454`) |

> Main architectural risk (RESEARCH): the temptation to build a `MarginManager` or a parallel reservation system. D-10 forbids it — locked margin IS cash state, owned by the one `CashManager` authority.

---

## No Analog Found

None. Every Phase-2 change has a direct in-repo precedent — the phase is additive gating + one new container (`locked_margin`, mirrored on `reserve_cash`) + one new sizing arm (`LeveredFraction`, mirrored on `RiskPercent`). The planner does NOT need to fall back to RESEARCH-only patterns for any file.

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/order_handler/`, `itrader/portfolio_handler/`, `itrader/config/`, `itrader/events_handler/events/`, `itrader/universe/`.
**Files read (full or targeted):** `core/sizing.py`, `order_handler/sizing_resolver.py`, `config/portfolio.py`, `portfolio_handler/cash/cash_manager.py`, `events_handler/events/signal.py`, `order_handler/admission/admission_manager.py` (1-80, 180-289), `core/portfolio_read_model.py` (150-233), `core/instrument.py`, `portfolio_handler/portfolio_handler.py` (230-330, 448-522), `portfolio_handler/portfolio.py` (270-329), `portfolio_handler/position/position.py` (1-90), `portfolio_handler/transaction/transaction.py` (75-109), `portfolio_handler/position/position_manager.py` (95-194), `universe/universe.py`.
**Indentation verified by:** `grep -P '^\t'` across all 13 files.
**Pattern extraction date:** 2026-06-15

## PATTERN MAPPING COMPLETE

**Phase:** 2 - Margin Accounting & Leverage
**Files classified:** 13 (12 edited + Instrument consume-only; tests in RESEARCH Wave 0)
**Analogs found:** 13 / 13

### Coverage
- Files with exact analog: 9 (`sizing.py`, `sizing_resolver.py`, `signal.py`, `portfolio.py` config, `admission_manager.py`, `portfolio.py` settlement, `portfolio_read_model.py`, `portfolio_handler.py`)
- Files with role-match analog: 3 (`cash_manager.py` position-keyed lock, `position.py` leverage attr, `position_manager.py` lifecycle)
- Files with no analog: 0
- Consume-only / wiring: `instrument.py` (no change), `universe.py` (no change to file; new injection seam)

### Key Patterns Identified
- **byte-exact `enable_margin` gate** at exactly two cash sites (`admission_manager.py:228` reservation, `portfolio.py:303` settlement) + `available_balance` + the leverage force-to-1; the `False` arm is the existing expression with NO division (Pitfall 4).
- **mirror-an-existing-sibling** is the dominant strategy: `LeveredFraction` ↔ `RiskPercent`, position-keyed `locked_margin` ↔ order-keyed `reserve_cash`, `maintenance_margin`/`margin_ratio` ↔ `total_equity()`, `max_leverage` ↔ `enable_margin`, `SignalEvent.leverage` ↔ `exit_fraction`.
- **BLOCKING wiring gap:** `AdmissionManager` has no `Instrument`/`Universe` seam today — `Universe` is injected only into `SimulatedExchange`; the planner must add `Optional[Universe]` to the order-domain constructor and a compose-root wiring task.
- **audited REJECTED path reused verbatim** for over-margin (MARGIN-02) and the `f>1`-without-margin gate (LEV-02).
- **indentation split confirmed:** TABS in `admission_manager.py`, `portfolio.py`, `position.py`; 4 SPACES in everything else (including `sizing_resolver.py` and `position_manager.py`, which RESEARCH had flagged to verify).

### File Created
`.planning/phases/02-margin-accounting-leverage/02-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. The planner can reference each analog (file + line range + excerpt) directly in PLAN.md action sections. The two non-negotiables to carry into plans: the byte-exact `enable_margin` branch sites (Pattern 1 + Pitfall 4) and the compose-root `Universe`-injection wiring task (Pitfall 1).
