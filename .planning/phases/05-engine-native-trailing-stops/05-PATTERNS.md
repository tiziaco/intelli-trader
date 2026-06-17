# Phase 5: Engine-Native Trailing Stops - Pattern Map

**Mapped:** 2026-06-17
**Files analyzed:** 13 (9 modified + 4 new test/script)
**Analogs found:** 13 / 13 (every touched file has a verified in-repo analog)

> All excerpts below were read and verified this session against the live source.
> Line numbers are current as of this mapping. **Indentation is per-file and load-bearing**
> (see the per-file flag on every assignment) — never normalize a file's whitespace.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/execution_handler/matching_engine.py` | service (matching) | event-driven (per-bar) | itself — extend `_evaluate` STOP branch + `on_bar` two-pass | exact (self-extend) | **4-SPACE** |
| `itrader/execution_handler/exchanges/simulated.py` | service (exchange) | event-driven | itself — `_emit_fill` is_maker gate (line 273), `validate_order` price branch (line ~490) | exact (self-extend) | **4-SPACE** |
| `itrader/core/enums/order.py` | enum (core) | n/a (vocabulary) | `OrderType` MARKET/STOP/LIMIT + `order_type_map` (lines 11-63) | exact | **TAB** |
| `itrader/config/order.py` (or `config/exchange.py`) | config enum | n/a | `FeeModelType`/`SlippageModelType` `(str, Enum)` (exchange.py:26-43) | exact (analog in sibling file) | **4-SPACE** |
| `itrader/config/__init__.py` | barrel re-export | n/a | `FeeModelType` import (lines 47-59) + `__all__` (67-104) | exact | **4-SPACE** |
| `itrader/events_handler/events/order.py` | event (frozen) | request-response | `stop_price`/`leverage` optional fields (58-62) + `new_order_event` getattr read-back (121-125) | exact | **4-SPACE** |
| `itrader/order_handler/order.py` | model (entity) | n/a | `new_stop_order` factory (227-271) + `leverage` field (100) | exact | **TAB** |
| `itrader/order_handler/brackets/bracket_manager.py` | service (declaration) | transform (signal→orders) | `_create_fill_anchored_children` (225-276) + fixed-SL path (138-150) | exact | **TAB** |
| `itrader/order_handler/order_validator.py` | validator | request-response | `_validate_critical_fields` price/quantity checks (213-233) | exact | **TAB** |
| `tests/unit/execution/test_matching_engine_trailing.py` (new) | test (unit) | n/a | `tests/unit/execution/test_matching_engine.py` (`make_order_event`, `make_bar`, stop-trigger cases) | exact | 4-SPACE |
| `tests/unit/order/test_trailing_validation.py` (new) | test (unit) | n/a | existing `tests/unit/order/` validator tests | role-match | 4-SPACE |
| `tests/e2e/trailing_long/` + `tests/e2e/trailing_short/` (new) | test (e2e) | n/a | `tests/e2e/sltp/`, `tests/e2e/short_roundtrip/` (use `scenario_spec.py`) | exact | 4-SPACE |
| `scripts/cross_validate_trailing.py` + `scripts/crossval/trailing_run.py` (new) | script (evidence) | batch | `scripts/cross_validate_accounting.py` + `scripts/crossval/{short_run,levered_run}.py` (reuse `reconcile.py` verbatim) | exact | 4-SPACE |

---

## Pattern Assignments

### `itrader/core/enums/order.py` (enum, **TAB**)

**Analog:** `OrderType` itself — the plain-`Enum` shape with explicit string `.value` and case-insensitive `_missing_`. `OrderType` is **NOT** `(str, Enum)` — it is a plain `Enum`. Add a member to the enum AND a parallel entry to `order_type_map`.

**Member declaration** (lines 19-21):
```python
	MARKET = "MARKET"
	STOP = "STOP"
	LIMIT = "LIMIT"
	# NEW (Phase 5, TRAIL-01):
	TRAILING_STOP = "TRAILING_STOP"
```
`_missing_` (lines 23-30) already handles any new member case-insensitively — no change needed there.

**Parallel map** (lines 59-63):
```python
order_type_map = {
	"MARKET": OrderType.MARKET,
	"STOP": OrderType.STOP,
	"LIMIT": OrderType.LIMIT,
	"TRAILING_STOP": OrderType.TRAILING_STOP,   # NEW — keep map in lockstep with enum
}
```
`VALID_ORDER_TRANSITIONS` (lines 76-84) is keyed by `OrderStatus`, NOT `OrderType` — a new order TYPE does not require a transitions change. **Do not** add a `TRAILING_STOP` key there.

---

### `itrader/config/order.py` (config enum, **4-SPACE**)

**Analog:** `FeeModelType` / `SlippageModelType` in `itrader/config/exchange.py:26-43`.

**The `(str, Enum)` config-enum shape to copy** (exchange.py:26-43):
```python
class FeeModelType(str, Enum):
    """Supported fee model types."""

    ZERO = "zero"
    NO_FEE = "no_fee"
    PERCENT = "percent"
    MAKER_TAKER = "maker_taker"
    TIERED = "tiered"
```
**New `TrailType`** (lowercase `.value`s, mirrors the locked decision):
```python
class TrailType(str, Enum):
    """Trailing-stop offset interpretation (config-enum exception, CONVENTIONS.md)."""

    PRICE = "price"       # absolute quote distance
    PERCENT = "percent"   # fraction of HWM/LWM
```

**PLACEMENT DECISION FOR PLANNER (RESEARCH A3 — flag explicitly):**
- `config/order.py` is the more *cohesive* home (it is the order-domain config module, carries `OrderConfig`). **Caveat:** `config/order.py` currently imports `MarketExecution` from `core.enums` and only re-exports `OrderConfig` — it does **not** yet define any local enum, and the file's docstring (lines 11-19) explicitly notes config-enum-exception enums it *consumes* live in `core/enums`. Adding a new `(str, Enum)` *definition* here is convention-compliant but introduces the first locally-defined enum in that file.
- `config/exchange.py` is where the existing `(str, Enum)` config enums are *defined* — the cleanest copy-from-here site. A trailing-stop is conceptually an order concept, not exchange.
- **Either is convention-compliant.** Recommend `config/order.py` for cohesion; the planner must pick one and re-export accordingly (see next file).

---

### `itrader/config/__init__.py` (barrel re-export, **4-SPACE**)

**Analog:** the `FeeModelType` re-export — an import in the domain block + a string in `__all__`.

**Import block** (the `.order` import block exists; `.exchange` block at lines 47-59 is the model to copy if `TrailType` lands in exchange.py):
```python
from .exchange import (
    ...
    FeeModelType,
    ...
)
# If TrailType lands in config/order.py, add it to the existing `from .order import (...)` block;
# if it lands in config/exchange.py, add it alongside FeeModelType above.
```

**`__all__` entry** (mirror line 97 `"FeeModelType"`; the Order-domain block is lines 84-85):
```python
__all__ = [
    ...
    # Order domain
    "OrderConfig",
    "TrailType",        # NEW — re-export the config enum at the package surface
    ...
]
```

---

### `itrader/events_handler/events/order.py` (event, **4-SPACE**)

**Analog:** the `stop_price` / `leverage` optional-field precedent on the frozen `OrderEvent` + the `getattr`-default read-back in `new_order_event`.

**Optional order-type-specific fields** (lines 58-62 — the exact precedent):
```python
    stop_price: Decimal | None = None
    leverage: Decimal = Decimal("1")
    # NEW (Phase 5) — both default to a no-op so every non-trailing order is byte-exact:
    trail_type: "TrailType | None" = None   # None for non-trailing orders
    trail_value: Decimal | None = None      # normalized Decimal, e.g. Decimal("0.02") for 2%
```
`OrderEvent` is `@dataclass(frozen=True, slots=True, kw_only=True)` (line 16). New fields MUST have defaults and go AFTER the existing defaulted fields. `TrailType` import goes at the top (forward-ref string if it would create a cycle; `config` already imports cleanly).

**`new_order_event` read-back** (lines 121-125 — the robust-to-old-stubs pattern):
```python
            stop_price=getattr(order, 'stop_price', None),
            leverage=getattr(order, 'leverage', Decimal("1")),
            # NEW — read trail fields off the entity with the same getattr-default guard:
            trail_type=getattr(order, 'trail_type', None),
            trail_value=getattr(order, 'trail_value', None),
```

**FROZEN-EVENT FLAG (CRITICAL, D-TRAIL-6):** `OrderEvent` is `frozen=True, slots=True` — HWM/LWM running state **cannot** live on it (`FrozenInstanceError` at runtime). The running extreme lives in a `MatchingEngine`-owned side-table, NOT on these fields. `trail_type`/`trail_value` are the *static declaration* (immutable); the *mutable* HWM/LWM/current-stop is engine-owned (see matching_engine assignment).

---

### `itrader/order_handler/order.py` (entity, **TAB**)

**Analog:** `new_stop_order` factory (lines 227-271) + the `leverage` field (line 100) + `stop_price` is NOT on the entity today (read off via `getattr` in the event — see line 119-121 of order.py event).

**Entity fields** (mirror `leverage` at line 100, in the dataclass body):
```python
	# NEW (Phase 5) — static trailing declaration; mutable HWM/LWM is engine-owned (D-TRAIL-6).
	trail_type: Optional["TrailType"] = None
	trail_value: Optional[Decimal] = field(default=None)
```

**New factory `new_trailing_stop_order`** — copy `new_stop_order` (227-271) verbatim, swap `OrderType.STOP` → `OrderType.TRAILING_STOP`, add `trail_type`/`trail_value` params:
```python
	@classmethod
	def new_trailing_stop_order(cls, time: datetime, ticker: str, action: Side, price: Any,
					quantity: Any, exchange: str, strategy_id: StrategyId, portfolio_id: PortfolioId, *,
					trail_type: "TrailType", trail_value: Decimal,
					leverage: Decimal = Decimal("1")) -> "Order":
		order = cls(
			time, OrderType.TRAILING_STOP, OrderStatus.PENDING, ticker, action,
			to_money(price), to_money(quantity), exchange, strategy_id, portfolio_id,
			leverage=to_money(leverage),
		)
		order.trail_type = trail_type
		order.trail_value = to_money(trail_value)
		order.add_state_change(OrderStatus.PENDING,
			f"Trailing-stop order created for {ticker}", OrderTriggerSource.SYSTEM)
		return order
```
**FLAG (Pitfall 6):** a trailing SL has NO meaningful static trigger price at declaration — its initial stop is computed from the fill (D-TRAIL-3). The `price` positional in the factory must carry something that passes the positive-price validators (see validator + Pitfall 6 below). `__post_init__` (lines 102-118) calls `to_money(self.price)` — `price` must be a positive Decimal at construction.

---

### `itrader/order_handler/brackets/bracket_manager.py` (bracket declaration, **TAB**)

**Analog (PRIMARY — D-TRAIL-3 fill-anchored seed):** `_create_fill_anchored_children` (lines 225-276). This is the `PercentFromFill` carve-out — children created at the parent's EXECUTED fill, priced from the **actual fill price**. This is structurally identical to "seed the trailing SL from the entry fill price."

**Fill-anchored child creation** (lines 242-267 — the precedent to extend):
```python
		anchor = to_money(fill_event.price)
		sl_price, tp_price = _bracket_levels(pending.policy, anchor, pending.action)
		child_action = Side.BUY if pending.action is Side.SELL else Side.SELL
		sl_order = Order.new_stop_order(
			time=fill_event.time, ticker=pending.ticker, action=child_action,
			price=sl_price, quantity=pending.quantity, exchange=pending.exchange,
			strategy_id=pending.strategy_id, portfolio_id=pending.portfolio_id)
		sl_order.parent_order_id = parent.id
		# D-TRAIL-3/D-TRAIL-5: when the bracket declares a TRAILING SL instead of a fixed SL,
		# build it via Order.new_trailing_stop_order(...) with trail_type/trail_value,
		# seeding the initial stop from `anchor` (the entry fill). EITHER fixed SL OR trailing SL.
```

**Analog (SECONDARY — fixed-SL declaration path being replaced, D-TRAIL-5):** lines 138-150:
```python
			if sl_price > 0:
				sl_order = Order.new_stop_order(
					time=signal_event.time, ticker=signal_event.ticker,
					action=Side.BUY if signal_event.action is Side.SELL else Side.SELL,
					price=sl_price, quantity=quantity, exchange=exchange,
					strategy_id=signal_event.strategy_id, portfolio_id=signal_event.portfolio_id)
				sl_order.parent_order_id = primary.id
```

**Arming pattern for a fill-anchored bracket** (lines 121-134 — `_brackets.arm` + `_PendingBracket`): the trailing SL should ride a `_PendingBracket`-style record so the initial stop is computed at fill (A2). The planner extends `_PendingBracket` (in `bracket_book.py`) to carry `trail_type`/`trail_value`, OR adds a parallel pending record. `OrderType`/policy dispatch is a `match` over `sltp_policy` with `assert_never` (lines 112-136) — if trailing is expressed as a new policy, the `assert_never` MUST gain an arm (mypy --strict gate).

**FLAG:** `BracketManager` has NO queue access (D-18) and NEVER matches — it returns `OperationResult`/`OrderEvent`; the handler enqueues. The trailing ratchet is execution-layer ONLY.

---

### `itrader/order_handler/order_validator.py` (validator, **TAB**)

**Analog:** `_validate_critical_fields` price/quantity checks (lines 213-233) — the place D-TRAIL-7 lands.

**Existing positive-price check** (lines 213-220):
```python
		# Price validation (M5-10: native Decimal comparison; Decimal vs int 0)
		if order.price <= 0:
			messages.append(ValidationMessage(
				ValidationLevel.ERROR,
				"Price must be positive",
				"price",
				"INVALID_PRICE"
			))
```

**D-TRAIL-7 — new check (reject non-viable trail)** added in the same critical-fields phase, expressed against `trail_value` + reference/entry price (NOT a static `price` field):
```python
		# D-TRAIL-7: reject a trail that would place the initial stop <= 0.
		if order.type == OrderType.TRAILING_STOP:
			tv = getattr(order, 'trail_value', None)
			tt = getattr(order, 'trail_type', None)
			if tv is None or tt is None or tv <= 0:
				messages.append(ValidationMessage(ValidationLevel.ERROR,
					"Trailing stop requires a positive trail_value and trail_type",
					"trail_value", "INVALID_TRAIL"))
			elif tt == TrailType.PERCENT and tv >= Decimal("1"):
				messages.append(ValidationMessage(ValidationLevel.ERROR,
					"Percent trail must be < 1 (would put stop at or below zero)",
					"trail_value", "INVALID_TRAIL"))
			elif tt == TrailType.PRICE and tv >= order.price:   # absolute >= reference price
				messages.append(ValidationMessage(ValidationLevel.ERROR,
					"Absolute trail must be < reference price",
					"trail_value", "INVALID_TRAIL"))
```

**FLAG (Pitfall 6 / Open Question 2 — RECONCILE BEFORE PLANNING):** the existing `if order.price <= 0` (line 214) AND `SimulatedExchange.validate_order` `if event.price <= 0` (simulated.py ~line 490) both reject a non-positive price. A trailing SL's trigger is dynamic. The planner MUST pick one: (a) seed a positive computed initial stop into `price` at fill (fill-anchored path makes this natural), or (b) branch the `price <= 0` check on `order_type == TRAILING_STOP`. The dual-layer validator overlap (CONVENTIONS.md D-03a) means BOTH validators must agree.

---

### `itrader/execution_handler/matching_engine.py` (matching service, **4-SPACE**) — THE CORE

**Analog:** itself. Trailing extends the existing STOP machinery; ~90% is reused verbatim.

**1. STOP trigger to reuse verbatim (D-TRAIL-4 gap-aware fill)** — `_evaluate` lines 158-164:
```python
        if order.order_type == OrderType.STOP:
            if order.action is Side.SELL:           # stop-loss on a long
                if low <= trigger:
                    return min(open_, trigger)      # pessimistic gap-down
            else:                                   # BUY stop (cover short)
                if high >= trigger:
                    return max(open_, trigger)      # pessimistic gap-up
```
**TRAILING_STOP arm:** add a branch in `_evaluate` that uses the **current ratcheted stop level** (from the side-table, derived from bars ≤ N-1) as `trigger`, then runs the EXACT same SELL/BUY gap-aware comparison. Do NOT recompute from this bar's extreme inside `_evaluate`. **mypy --strict:** `_evaluate`'s `if/elif` chain falls through to `return None` (line 182) — add a `TRAILING_STOP` arm, do not rely on fallthrough.

**2. The ratchet-then-evaluate ordering (D-TRAIL-2 — the phase-defining invariant)** — lives in `on_bar` (lines 184-304). The two-pass structure (parents pass 1 at 212-235, children pass 2 at 237-302) stays. Add a ratchet step that runs at the **END** of `on_bar`, AFTER both fill passes resolve, updating HWM/LWM from THIS bar's high/low and recomputing the stop for the NEXT bar. **ANTI-PATTERN (forbidden):** updating HWM/LWM at the top of `on_bar` or inside `_evaluate` from this bar's extreme then triggering same-bar.

**3. Frozen-event write-back precedent** — `modify` lines 122-127 (the `dataclasses.replace` pattern):
```python
        self._resting[order_id] = dataclasses.replace(
            order,
            price=order.price if new_price is None else to_money(new_price),
            quantity=order.quantity if new_quantity is None else to_money(new_quantity),
        )
```
**STATE-OWNERSHIP DECISION (D-TRAIL-6, Claude's discretion):** two viable layouts —
- **(preferred) side-table:** a `dict[OrderId, TrailState]` parallel to `_resting` (line 88), holding mutable `hwm`/`lwm`/`current_stop`. Pop it at every `_resting.pop` site (lines 101, 235, 299, 302) to avoid a leaked entry for a filled/cancelled order. Keeps the event immutable.
- **(heavier) `dataclasses.replace`** the resting event each bar with a new computed `price` (the `modify` precedent). Works, but rewrites the event every bar.
Both are convention-compliant; the side-table is simpler.

**4. Same-bar OCO priority to reuse verbatim (D-TRAIL-5)** — `_pick_bracket_winner` lines 306-314:
```python
    def _pick_bracket_winner(self, bracket: OrderId,
                             candidates: dict[OrderId, Decimal]) -> OrderId:
        """Among candidate legs of a bracket, prefer a STOP (pessimistic)."""
        leg_ids = [oid for oid in candidates
                   if self._resting[oid].parent_order_id == bracket]
        for oid in leg_ids:
            if self._resting[oid].order_type == OrderType.STOP:
                return oid
        return leg_ids[0]
```
**FLAG:** this prefers `OrderType.STOP` explicitly. A trailing SL is `OrderType.TRAILING_STOP`, NOT `STOP` — to keep "STOP beats LIMIT" priority for the dynamic SL leg, the planner must add `TRAILING_STOP` to this preference (`order_type in (OrderType.STOP, OrderType.TRAILING_STOP)`). The OCO sibling-cancel scan (lines 288-302) is type-agnostic — no change there.

**5. `_fill_reason` classification** — lines 316-322:
```python
    @staticmethod
    def _fill_reason(order: OrderEvent) -> str:
        if order.order_type == OrderType.STOP:
            return "stop triggered"
        if order.order_type == OrderType.LIMIT:
            return "limit triggered"
        return "market fill"
```
**FLAG:** a `TRAILING_STOP` falls through to `"market fill"` today — add a `TRAILING_STOP` arm so it classifies as a stop (`"trailing stop triggered"`).

**6. Decimal discipline (D-TRAIL-8):** carry HWM/LWM at full 28-digit precision; `quantize(value, instrument, "price")` (core/money.py) ONLY on the computed stop level used for the trigger comparison/fill — NEVER on the running extreme. `_evaluate` does NO quantization (lines 145-148) — keep that; quantize the stop where it is recomputed in the ratchet step.

---

### `itrader/execution_handler/exchanges/simulated.py` (exchange, **4-SPACE**)

**Analog:** itself — the `_emit_fill` maker/taker gate and `validate_order` price branch.

**`is_maker` gate** (line 273):
```python
		is_maker = event.order_type is OrderType.LIMIT
```
**FLAG (Pitfall 4):** a `TRAILING_STOP` must be a **taker** (`is_maker=False`, slippage applies) — like a STOP. This line already yields `False` for `TRAILING_STOP` (it is only `True` for `LIMIT`), so it is correct by construction; the conditional slippage block at line 277 (`if event.order_type is OrderType.LIMIT`) likewise correctly excludes trailing. **Verify** no other `match`/`assert_never` over `OrderType` exists that would need an arm (grep confirmed only the `is OrderType.LIMIT` checks at 273/277).

**`validate_order` price branch** (simulated.py ~line 490):
```python
		# Price validation
		if event.price <= 0:
			failed_checks.append("Order price must be positive")
```
**FLAG:** same Pitfall-6 reconcile as the domain validator — this is the defense-in-depth second path (CONVENTIONS.md D-03a). Whatever the planner picks for the trailing SL's `price` (positive computed stop vs branched check), BOTH validators must agree.

---

### `tests/unit/execution/test_matching_engine_trailing.py` (new test, 4-SPACE)

**Analog:** `tests/unit/execution/test_matching_engine.py`.

**`make_order_event` helper** (test_matching_engine.py:11-21) — extend with `trail_type`/`trail_value` kwargs:
```python
def make_order_event(order_type, action, price, order_id,
                     ticker="BTCUSDT", quantity=1.0, parent_order_id=None):
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker=ticker, action=Side(action),
        price=Decimal(str(price)), quantity=Decimal(str(quantity)),
        exchange="default", strategy_id=1, portfolio_id=1,
        order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
        command=OrderCommand.NEW,
    )
```
**`make_bar` fixture:** shared in `tests/conftest.py` (Decimal `dict[str, Bar]` payload, positional `open_, high, low, close`) — see usage at test_matching_engine.py:104-110. No new fixture needed (RESEARCH Wave 0).

**Stop-trigger case shape** (lines 104-110 — the pattern for the trailing cases):
```python
def test_sell_stop_triggers_when_low_pierces(engine, make_bar):
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
    assert len(fills) == 1
    assert fills[0].fill_price == 30.0
    assert not engine.has_order(1)
```
**Coverage required (long AND short — locked):** ratchet favorably-only (long+short), next-bar activation (never same-bar, the D-TRAIL-2 invariant), gap-through fill at open (long+short), trailing-SL vs TP-limit same-bar OCO. Use the `-k` selectors from RESEARCH §Test Map (`"trailing and long"`, `"trailing and short"`, `"trailing and next_bar"`, `"trailing and gap"`, `"trailing and oco"`).

---

### `tests/unit/order/test_trailing_validation.py` (new test, 4-SPACE)

**Analog:** existing `tests/unit/order/` validator tests. Covers D-TRAIL-7: reject percent ≥ 1, absolute ≥ reference price, missing trail_value/trail_type. `-k "trailing and reject"`.

---

### `tests/e2e/trailing_long/` + `tests/e2e/trailing_short/` (new, 4-SPACE)

**Analog:** `tests/e2e/sltp/` and `tests/e2e/short_roundtrip/` — both use `tests/e2e/scenario_spec.py`. End-to-end trailing scenario through the run path, long and short. Auto-tagged `e2e` by `tests/conftest.py`.

---

### `scripts/cross_validate_trailing.py` + `scripts/crossval/trailing_run.py` (new, 4-SPACE)

**Analog:** `scripts/cross_validate_accounting.py` (standalone sibling orchestrator) + `scripts/crossval/short_run.py` / `levered_run.py` (per-engine white-box runners). **Reuse `scripts/crossval/reconcile.py` verbatim** (`align_trades`/`build_metric_table`/`recompute_headline`/`flag_divergences`). Add backtesting.py/backtrader trailing runners (analogs: `backtesting_py_run.py`, `backtrader_run.py`, and the `*_limit_run.py` precedents for a non-default order type). `TOLERANCE = 0.01` (1% relative). Use a **synthetic ticker** (e.g. `TRAILUSD`), NEVER BTCUSD, so the spot oracle stays byte-exact.

**SCRIPT-ONLY (Pitfall 3, D-10):** `backtesting`/`backtrader` imports live under `scripts/crossval/` ONLY — never under `tests/` (would break `filterwarnings=["error"]`).

---

## Shared Patterns

### Decimal money discipline (D-TRAIL-8)
**Source:** `itrader/core/money.py` — `to_money(x)` / `quantize(value, instrument, "price")`.
**Apply to:** matching_engine ratchet step, Order factory, bracket fill-anchor, validator.
- Enter Decimal ONLY via `to_money` (NEVER `Decimal(float)`).
- Carry HWM/LWM at full precision; `quantize(..., "price")` ONLY the trigger/fill stop level.
- `_evaluate` already does NO quantization (matching_engine.py:145-148) — preserve that.

### Frozen-event + side-table state ownership (D-TRAIL-6)
**Source:** `OrderEvent` `frozen=True, slots=True` (events/order.py:16) + `modify` `dataclasses.replace` (matching_engine.py:122-127).
**Apply to:** matching_engine (mutable HWM/LWM/current-stop).
- Static declaration (`trail_type`/`trail_value`) lives on the frozen event/entity.
- Mutable running state lives in a `MatchingEngine`-owned side-table keyed by `OrderId`, popped at every `_resting.pop` site.

### mypy --strict exhaustiveness over OrderType (Pitfall 4)
**Source:** the `if/elif` chains in `_evaluate` (matching_engine.py:154-182), `_fill_reason` (316-322), `_pick_bracket_winner` (306-314); `is OrderType.LIMIT` in simulated.py:273/277; `assert_never` over `sltp_policy` in bracket_manager.py:112-136.
**Apply to:** every `OrderType` switch — add a `TRAILING_STOP` arm; do not rely on fallthrough.
- `_evaluate`: new STOP-like arm using the ratcheted level.
- `_fill_reason`: classify as a stop.
- `_pick_bracket_winner`: include `TRAILING_STOP` in the STOP-priority preference.
- simulated.py `is_maker`: stays `False` for trailing (taker) — already correct, verify.

### Dual-layer positive-price validation (Pitfall 6, CONVENTIONS.md D-03a)
**Source:** `EnhancedOrderValidator._validate_critical_fields` (order_validator.py:213-220) AND `SimulatedExchange.validate_order` (simulated.py:~490).
**Apply to:** both validators must agree on how a dynamic trailing-stop price passes the `price <= 0` gate. Pick ONE strategy (positive computed initial stop OR a `TRAILING_STOP`-branched check) and apply it to BOTH paths.

### Indentation hazard (Pitfall 5, CONVENTIONS.md)
**Source:** CONVENTIONS.md tab/space convention.
**Apply to:** every file — match the file. **TAB:** `order.py`, `bracket_manager.py`, `order_validator.py`, `core/enums/order.py`. **4-SPACE:** `matching_engine.py`, `simulated.py`, `events/order.py`, `config/*`. A mixed-indentation diff in a tab file is a `TabError`.

---

## No Analog Found

None. Every touched file has a verified in-repo analog. The phase is feature-additive to existing STOP machinery — the matching engine, order type, config enum, frozen event, factory, bracket declaration, validator, unit test, e2e leaf, and cross-val orchestrator all have direct precedents read this session.

---

## Metadata

**Analog search scope:** `itrader/execution_handler/`, `itrader/core/enums/`, `itrader/config/`, `itrader/events_handler/events/`, `itrader/order_handler/` (+ `brackets/`), `tests/unit/execution/`, `tests/unit/order/`, `tests/e2e/`, `scripts/crossval/`.
**Files scanned (read in full or targeted):** matching_engine.py, core/enums/order.py, config/exchange.py, config/order.py, config/__init__.py, events/order.py, order_handler/order.py, brackets/bracket_manager.py, order_validator.py, tests/unit/execution/test_matching_engine.py, simulated.py (targeted).
**Pattern extraction date:** 2026-06-17
