# Phase 5: Signal Contract & Reconcile (FRAGILE) - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 11 (10 modified + 1+ new cross-val/golden artifacts)
**Analogs found:** 11 / 11 (every change is "extend a sibling already in the same file")

> **Key framing (from RESEARCH):** This phase has almost NO greenfield surface. Every
> new file/symbol copies a pattern from an *existing sibling in the same module* — the
> new `buy_limit` factory copies `buy()` two methods up; the new `SignalIntent` fields
> copy the existing `action: Side` field; the `Side` retype copies `OrderEvent.action`
> which is *already* `Side`. The "analog" for most rows is therefore the same file, a
> few lines away. Planner: prefer the in-file sibling over RESEARCH abstractions.

> **HARD CONSTRAINT — indentation (CLAUDE.md, verified this session):**
> - **TABS:** `strategy_handler/base.py`, `strategy_handler/strategies_handler.py`,
>   `order_handler/order.py`, `order_handler/admission/admission_manager.py`,
>   `order_handler/reconcile/reconcile_manager.py`, `order_handler/brackets/bracket_book.py`
>   (verified TAB line 60), `order_handler/brackets/bracket_manager.py` (verified TAB line 143),
>   `order_handler/brackets/levels.py` (verified TAB line 38), `order_handler/order_validator.py`.
> - **4 SPACES:** `core/sizing.py`, `strategy_handler/signal_record.py`,
>   `events_handler/events/*.py`, `scripts/crossval/*.py`, `tests/e2e/**`.
>   Match the file; a mixed-indentation diff breaks a TAB file (`TabError` at import).

## File Classification

| File | Role | Data Flow | Closest Analog | Match Quality |
|------|------|-----------|----------------|---------------|
| `itrader/core/sizing.py` (`SignalIntent`) | model (value object) | transform | the existing `SignalIntent.action: Side` field + `SignalEvent.order_type/price` fields (same shape) | exact (in-file) |
| `itrader/strategy_handler/base.py` (`buy_limit`/`buy_stop`/`sell_limit`/`sell_stop`) | utility (authoring sugar) | transform | `Strategy.buy()` / `Strategy.sell()` (base.py:434-468) | exact (in-file sibling) |
| `itrader/strategy_handler/base.py` (`order_type` attr retire + `to_dict()`) | config | transform | `to_dict()` block (base.py:380-407) | exact (in-file) |
| `itrader/strategy_handler/strategies_handler.py` (fan-out 143/146) | service (handler boundary) | event-driven (fan-out) | the existing `SignalEvent(...)` construction loop in place | exact (in-file) |
| `itrader/strategy_handler/signal_record.py` (`+order_type/+entry_price`) | model (audit record) | event-driven (sink) | `SignalRecord` existing fields (`action: Side`, `stop_loss: Decimal\|None`) | exact (in-file) |
| `itrader/order_handler/order.py` (`Order.action` str→Side) | model (entity) | request-response | `OrderEvent.action: Side` (events/order.py:47) + `SignalEvent.action: Side` — target type ALREADY exists | exact (cross-file type analog) |
| `itrader/order_handler/order.py` (`new_limit_order`/`new_stop_order` action param) | model (factory) | transform | `Order.new_order` (order.py:142-196) | exact (in-file sibling) |
| `itrader/order_handler/admission/admission_manager.py` (snapshot threading) | service (admission) | request-response | the 3 existing `get_position()` sites (404/484/583) collapsed to 1 | exact (in-file refactor) |
| `itrader/order_handler/brackets/bracket_book.py` (`_PendingBracket.action` str→Side) | model (value object) | transform | `Order.action` (the sibling D-03 retype) | exact |
| `itrader/order_handler/brackets/bracket_manager.py` + `levels.py` (action literal sites) | utility | transform | existing `Side` comparisons in same files (`is Side.SELL`) | exact (in-file) |
| `itrader/order_handler/order_validator.py` (action literal sites — IF touched) | service (validator) | request-response | existing `Side.X.value` compares (order_validator.py:414-415) | exact (in-file) |
| `itrader/order_handler/reconcile/reconcile_manager.py` (`on_fill` extract-method) | service (reconcile) | event-driven | itself — extract helpers in place, try/finally byte-identical | exact (in-file refactor) |
| `scripts/crossval/<limit>_run.py` (new LIMIT runners) | config (script) | batch | `scripts/crossval/backtesting_py_run.py` + `backtrader_run.py` | role-match (MARKET→LIMIT variant) |
| `tests/e2e/matching/entries/<new>/` OR `tests/golden/` (D-07 golden) | test | batch | `tests/e2e/matching/entries/limit_touch/` (scenario.py + bars.csv + golden/) | exact (leaf template) |

---

## Pattern Assignments

### `core/sizing.py` — `SignalIntent` + `entry_price`/`order_type` (D-01) — 4 SPACES

**Analog:** the existing `SignalIntent` field block (same file). Two new fields follow the
existing `action: Side` and `quantity: Decimal | None = None` shapes; the `# TODO add order_type
and entry_price` comment at line 243 marks the exact insertion point.

**Existing field block to extend** (`core/sizing.py:237-243`):
```python
    ticker: str
    action: Side
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    exit_fraction: Decimal = Decimal("1")
    quantity: Decimal | None = None
    # TODO add order_type and entry_price for stop/limit orders   # <- REPLACE
```

**D-01 target:** add `order_type: OrderType` (never None — `MARKET` for plain buy/sell,
`LIMIT`/`STOP` for typed factories) and `entry_price: Decimal | None = None`. Import `OrderType`
from `itrader.core.enums` (the module already imports `Side` from there — add to that line).
`@dataclass(frozen=True, slots=True, kw_only=True)` is already on the class; new fields just
list under it. Decide field ordering vs `kw_only` (kw_only=True makes order non-load-bearing).

---

### `strategy_handler/base.py` — factory sugar `buy_limit`/`buy_stop`/`sell_limit`/`sell_stop` (D-01) — TABS

**Analog:** `Strategy.buy()` / `Strategy.sell()` (base.py:434-468) — copy verbatim, add `*, price`,
set `order_type`/`entry_price` on the returned intent.

**Template to copy** (`base.py:434-450`):
```python
	def buy(self, ticker: str, sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""Thin sugar returning a BUY ``SignalIntent`` for ``ticker``. ..."""
		return SignalIntent(
			ticker=ticker,
			action=Side.BUY,
			stop_loss=to_money(sl) if sl is not None else None,
			take_profit=to_money(tp) if tp is not None else None,
			exit_fraction=exit_fraction,
		)
```

**D-01 target shape** (Claude's discretion on the shared `_intent(...)` helper — RESEARCH Pattern 1):
```python
	# price is REQUIRED + keyword-only on the typed factories; order_type/entry_price set on intent.
	def buy_limit(self, ticker: str, *, price: float | Decimal,
			sl=None, tp=None, exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		return self._intent(ticker, Side.BUY, OrderType.LIMIT, to_money(price), sl, tp, exit_fraction)
```

**Byte-exact constraints:**
- `buy()` / `sell()` stay UNCHANGED in signature; inside, pass `order_type=OrderType.MARKET,
  entry_price=None` to `SignalIntent` (do NOT read `self.order_type`). RESEARCH Pitfall 1: MARKET
  must NOT carry an entry_price (it stays `None`; the fan-out keeps `to_money(bar.close)`).
- Money enters via `to_money(price)` — NEVER `Decimal(float)` (CLAUDE.md money policy).
- Import `OrderType` (base.py already imports it for the class attr — keep after retirement).

---

### `strategy_handler/base.py` — retire `order_type` class attr + `to_dict()` (D-01) — TABS

**Analog:** the `to_dict()` snapshot block itself (base.py:396-397).

**Site 1 — class attr** (`base.py:101`, retire):
```python
	order_type: OrderType = OrderType.MARKET   # <- DELETE (every call now states the type)
```
Caution: this attr is `get_type_hints`-detected by `_apply_params` (see base.py:93-97 comment).
Removing it removes a kwarg knob — verify no subclass/test passes `order_type=` to `Strategy.__init__`
expecting it to set a strategy-wide default. **NOTE:** `ScriptedEmitter` (tests/e2e/strategies/scripted_emitter.py)
still threads `order_type=order_type` into `super().__init__()` (lines 86, 110) — its per-INSTANCE
order_type IS the SIG-02 limitation this phase removes (RESEARCH OQ3). The retirement's blast radius
explicitly includes deciding ScriptedEmitter's fate (keep as MARKET-default, or wire per-bar order_type
into its script for the SIG-02 e2e proof).

**Site 2 — to_dict()** (`base.py:396-397`, drop the line):
```python
			# D-04: order_type is the OrderType enum now — serialize its value.
			"order_type": self.order_type.value,   # <- DROP both lines
```
`SignalRecord.config = strategy.to_dict()` consumes this dict (strategies_handler.py:130) — dropping
the key is the oracle-dark schema change. Verify no `to_dict()` consumer/golden snapshot asserts the
`"order_type"` key.

---

### `strategy_handler/strategies_handler.py` — fan-out per-intent (D-02) — TABS

**Analog:** the existing `SignalEvent(...)` construction in place (strategies_handler.py:140-170)
and the `SignalRecord(...)` capture above it (121-131).

**Site 1 — fan-out** (strategies_handler.py:143/146):
```python
		for portfolio_id in strategy.subscribed_portfolios:
			signal = SignalEvent(
				time=event.time,
				order_type=strategy.order_type,          # <- CHANGED: read intent.order_type
				ticker=ticker,
				action=intent.action,
				price=to_money(bar.close),               # <- CHANGED: MARKET keeps this; LIMIT/STOP -> intent.entry_price
```
**D-02 target:** `order_type=intent.order_type`; for `price`, gate on `intent.order_type` —
**MARKET keeps `to_money(bar.close)` BYTE-EXACT**, LIMIT/STOP use `intent.entry_price`
(RESEARCH Pitfall 1 — the byte-exact canary). `SignalEvent.order_type`/`price` fields already exist
(events/signal.py:78-79) — no event schema change.

**Site 2 — SignalRecord capture** (strategies_handler.py:121-131): add `order_type=intent.order_type,
entry_price=intent.entry_price,` to the `SignalRecord(...)` call (mirrors the existing
`action=intent.action,` / `stop_loss=intent.stop_loss,` lines).

---

### `strategy_handler/signal_record.py` — `+order_type`/`+entry_price` (D-02) — 4 SPACES

**Analog:** the existing `SignalRecord` field block (signal_record.py:73-85) — new fields copy the
`action: Side` and `stop_loss: Decimal | None = None` shapes exactly.

**Existing field block to extend** (signal_record.py:79-84):
```python
    action: Side
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    exit_fraction: Decimal = Decimal("1")
    quantity: Decimal | None = None
    config: dict[str, Any]
```
**D-02 target:** add `order_type: OrderType` + `entry_price: Decimal | None = None` (names are
Claude's discretion). Import `OrderType` from `itrader.core.enums` (file already imports `Side`
from there — add to line 34). Oracle-dark (D-12): never affects fills. Add matching `Attributes`
docstring entries (the file documents every field).

---

### `order_handler/order.py` — `Order.action` str→Side + factory params (D-03/SIG-03) — TABS

**Analog (target type):** `OrderEvent.action: Side` (events/order.py:47) and `SignalEvent.action: Side`
(signal.py:77) are ALREADY `Side`. SIG-03 narrows the persisted `Order` entity to match the events that
flank it.

**Site 1 — entity field** (`order.py:49`):
```python
	action: str          # <- RETYPE to: action: Side
```

**Site 2 — `new_order` boundary** (`order.py:180-181`): the `.value` conversion becomes pass-through:
```python
			# The entity stores a str action until M4 — convert at this boundary.
			signal.action.value,     # <- becomes: signal.action  (signal.action is already Side)
```

**Site 3/4 — factory params** (`order.py:199` `new_stop_order`, `:232` `new_limit_order`):
```python
	def new_stop_order(cls, time: datetime, ticker: str, action: str, price: Any, ...)  # action: str -> Side
	def new_limit_order(cls, time: datetime, ticker: str, action: str, price: Any, ...) # action: str -> Side
```
The `action` param threads straight onto the `cls(...)` positional (order.py:214/247) — once the field
is `Side`, no conversion. Caller `_build_primary_order` (admission_manager.py:343/354) passes
`action=signal_event.action.value` → **drop the `.value`** (pass the `Side` directly).

**Site 5 — `to_event` re-parse** (order.py:95 — RESEARCH blast radius): `Side(order.action)` becomes a
no-op/removable once the field is `Side`. Verify `__str__` (order.py:137) `{self.action}` still renders
acceptably (a `Side` member prints `Side.BUY`; check golden serialization at the reporting edge —
RESEARCH A4: the trades.csv emits `.value`/`.name` at the edge, value text stays the same string).

---

### `order_handler/brackets/bracket_book.py` — `_PendingBracket.action` str→Side (D-03) — TABS (verified)

**Analog:** the `Order.action` retype above (same `str`→`Side` move). The module docstring (lines 16-17)
explicitly flags `action: str` as W2-02 deferred — this phase closes it.

**Site** (`bracket_book.py:40`):
```python
	policy: PercentFromFill
	ticker: str
	action: str        # <- RETYPE to: action: Side  (drop the docstring "W2-02 deferred" note)
	quantity: Decimal
```
Import `Side` (`from ...core.enums import Side` — the events package uses this path). Then update the
two construction sites that write `_PendingBracket(action=...)` in bracket_manager.py (see next row).

---

### `order_handler/brackets/bracket_manager.py` + `levels.py` — action literal sites (D-03) — TABS (verified)

**Analog:** the existing `signal_event.action is Side.SELL` comparison already present in
bracket_manager.py:143 — the same `Side`-member idiom replaces the string literals.

**bracket_manager.py sites:**
```python
:120   signal_event.action.value)                                  # -> drop .value (Side)
:129   action=signal_event.action.value,                           # -> drop .value
:143   action='BUY' if signal_event.action is Side.SELL else 'SELL'   # -> Side.BUY if ... else Side.SELL
:157   action='BUY' if signal_event.action is Side.SELL else 'SELL'   # -> Side.BUY if ... else Side.SELL
:245   child_action = 'BUY' if pending.action == Side.SELL.value else 'SELL'
       # -> Side.BUY if pending.action is Side.SELL else Side.SELL  (depends on _PendingBracket.action: Side)
```
Note `child_action` (:245) feeds `new_stop_order`/`new_limit_order` `action=child_action` (:249/:260) —
those params are now `Side` (order.py retype above), so the literal must become a `Side` member.

**levels.py site** (`levels.py:27`, `:38`):
```python
:27    action: str) -> "tuple[Decimal, Decimal]":     # -> action: Side
:38    if action == Side.SELL.value:                  # -> if action is Side.SELL
```

---

### `order_handler/order_validator.py` — action literal sites (D-03, ONLY IF touched → W4-04 doc) — TABS

**Analog:** the existing `order.action == Side.SELL.value` compares (order_validator.py:414-415) —
narrow `.value` compares to `is`.

**Sites:**
```python
:193   if order.action not in ["BUY", "SELL"]:        # -> if order.action not in (Side.BUY, Side.SELL)
:414   position.side.name == 'LONG' and order.action == Side.SELL.value   # -> order.action is Side.SELL
:415   position.side.name == 'SHORT' and order.action == Side.BUY.value   # -> order.action is Side.BUY
```
**D-03/W4-04:** if and only if this file is edited, update the W4-04 dual-layer validator-overlap doc
(`.planning/codebase/CONVENTIONS.md` + CLAUDE.md note). Since `Order.action` becomes `Side`, the `:193`
string-membership check is now dead-on-string and must convert — so this file IS touched → the W4-04 doc
update IS required.

---

### `order_handler/admission/admission_manager.py` — snapshot threading (D-03/W1-11) — TABS

**Analog:** the three IDENTICAL `get_position()` call blocks already in this file (the refactor collapses
them; the pattern to preserve is each block's null-check + read shape).

**The three current sites (collapse to ONE capture in `process_signal` ~line 138, before the step-0 gate):**

Site A — `_enforce_direction_admission` (admission_manager.py:398-405):
```python
		if self.portfolio_handler is None:
			return None
		portfolio_id = signal_event.portfolio_id
		open_position = self.portfolio_handler.get_position(portfolio_id, signal_event.ticker)
```
Site B — `_enforce_position_admission` (admission_manager.py:478-485): byte-identical null-check + read.
Site C — `_resolve_signal_quantity` (admission_manager.py:573-584): same read after the price guard.

**D-03 target shape** (RESEARCH Pattern 2 — CONTEXT specifics):
```python
	def process_signal(self, signal_event):
		# ONCE, before the step-0 direction gate (~line 138):
		snap: Position | None = (
			self.portfolio_handler.get_position(signal_event.portfolio_id, signal_event.ticker)
			if self.portfolio_handler is not None else None)
		gate = self._enforce_direction_admission(signal_event, snap)
		...
		gate = self._enforce_position_admission(signal_event, snap)
		...
		resolved = self._resolve_signal_quantity(signal_event, snap)
```
**Caution (RESEARCH Pattern 2):** each method's `if self.portfolio_handler is None: return None` fall-through
is load-bearing (an unsized signal with no read-model falls to the sizing failure). When threading the snap,
preserve "no read-model → None snap → same fall-through". Thread the **`Position` object** (each site reads
existence / `.net_quantity`), not a scalar. Byte-exact rationale: single-writer contract — the line-208
reserve touches cash only; no fill mutates the position within one `process_signal`, so one snapshot == three
re-fetches. `Position` type import: confirm the import path used by `get_position`'s return.

**Confirm-don't-rebuild:** `_build_primary_order` (admission_manager.py:337-360) ALREADY dispatches
MARKET/LIMIT/STOP on `signal_event.order_type` and threads `signal_event.price` into the right `Order`
factory. The reserve cost basis (`price * quantity + commission`, line 206) ALREADY uses `signal.price`
(= the limit/stop price under the new contract, D-05). NO change here beyond the `.value` drop at :343/:354.

---

### `order_handler/reconcile/reconcile_manager.py` — `on_fill` extract-method (D-06/RECON-01) — TABS

**Analog:** the method itself (reconcile_manager.py:86-234) — extract IN PLACE, control flow byte-identical.

**The load-bearing skeleton that MUST stay byte-identical** (reconcile_manager.py:120-234):
```python
		should_release = False
		body_raised = False
		try:
			applied = True
			if fill_event.status == FillStatus.EXECUTED:   # -> _apply_executed(...)
				...
			elif fill_event.status == FillStatus.CANCELLED: # -> _apply_cancelled(...)
				order.cancel_order("exchange cancellation")
			elif fill_event.status == FillStatus.REFUSED:   # -> _apply_refused(...)
				order.reject_order("exchange rejection")
			else:
				self.logger.warning('Unhandled fill status %s ...')
				return out_events                           # non-terminal: HOLDS reservation
			should_release = True                           # armed AFTER terminal, BEFORE further work
			...
		except Exception as e:
			...
			body_raised = True
			raise
		finally:
			if should_release and self.portfolio_handler is not None:   # <- BYTE-IDENTICAL
				try:
					self.portfolio_handler.release(order.portfolio_id, order.id)
				except Exception:
					self.logger.error(...)
					if not body_raised:
						raise
```

**D-06 target (RESEARCH Pattern 3 — Claude's discretion on helper homes/names):**
- Extract `_classify(status) -> (terminal: bool, transition)` — names the EXECUTED/CANCELLED/REFUSED →
  FILLED/CANCELLED/REJECTED mapping + terminal-ness; the `else` unknown-status branch stays a non-terminal
  early-return INSIDE `on_fill` (it returns `out_events` and must NOT arm `should_release`).
- Extract the three arms into `_apply_executed` / `_apply_cancelled` / `_apply_refused` named helpers
  (the EXECUTED arm is the `add_fill` + `applied` flag block at :124-141).
- Extract `_release_reservation(order, should_release, body_raised)` wrapping the `finally` BODY contents
  (the inner `try/except`/re-raise-iff-not-`body_raised`) — but the `try`/`finally` STATEMENTS stay in
  `on_fill`; only the helper *contents* move.

**ANTI-PATTERN (RESEARCH + D-06 rejected opt-2):** do NOT rewrite to a `apply(); release()` state machine —
it reintroduces the WR-04 bug (a raise between apply and release skips the release). RESEARCH Pitfall 4: the
`should_release` arm point (after terminal, line 155) and the `if not body_raised: raise` gate (line 232) are
both load-bearing — keep them where they are.

**Public surface:** `OrderManager.on_fill` is a 1-line delegation — stays byte-equal (CONTEXT integration note).

---

### `scripts/crossval/<limit>_run.py` — new LIMIT-entry runners (D-07) — 4 SPACES

**Analog:** `scripts/crossval/backtesting_py_run.py` + `scripts/crossval/backtrader_run.py` (both currently
MARKET-only SMA_MACD runners). Add a LIMIT-entry variant of the same `run(prices, indicators) ->
(trade_log_df, equity_curve_series)` uniform contract.

**Contract to preserve** (backtesting_py_run.py:17-20):
```python
# Uniform contract: `run(prices=None, indicators=None) -> (trade_log_df, equity_curve_series)`.
# trade_log_df NORMALIZED to columns: entry_date, exit_date, side, realised_pnl.
# SCRIPT-ONLY (D-10): imports backtesting.py (bokeh). NEVER import under tests/.
```
**D-07 target:** a crafted minimal limit-entry strategy (NOT SMA_MACD) — `buy_limit` at `close*0.98`
every N bars + percent SL/TP, plus ONE marketable-limit bar (price above market → fills at open). The
fill-price algebra agrees by construction across all three engines: backtesting.py `min(open, limit)` /
`max(open, stop)` == iTrader `MatchingEngine._evaluate` == backtrader bracket (RESEARCH Pitfall 3 / A1).
backtrader uses `self.buy_bracket(price=..., exectype=bt.Order.Limit, stopprice=..., limitprice=...)`
(RESEARCH Code Examples). Reuse `scripts/cross_validate.py` orchestrator + `scripts/crossval/reconcile.py`
(`align_trades`/`build_metric_table` are generic — A2).

---

### `tests/e2e/matching/entries/<new>/` OR `tests/golden/` — D-07 golden — 4 SPACES

**Analog:** `tests/e2e/matching/entries/limit_touch/` — a complete leaf: `scenario.py` (ScenarioSpec +
HAND-VERIFIED VERIFY note with the full derivation), `bars.csv` (contrived round-number daily bars),
`golden/` (frozen `trades.csv` + `summary.json`), `test_scenario.py`.

**Template — `scenario.py` shape** (limit_touch/scenario.py:105-116):
```python
SCENARIO = ScenarioSpec(
    start="2020-01-01", end="2020-01-06", timeframe=_TIMEFRAME, ticker=_TICKER,
    starting_cash=_CASH, data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT, order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(user_id=1, name="limit_touch_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage.
)
```
**D-07 differences:** runs on the REAL BTCUSD golden CSV (`data/BTCUSD_1d_ohlcv_2018_2026.csv`), not contrived
bars; the strategy is a crafted limit-entry emitter (or ScriptedEmitter wired to per-bar limit). MUST: fill on
a LATER bar (not immediate), exercise entry-fill→SL/TP-bracket anchor, include a marketable-limit case. RESEARCH
OQ2: planner decides leaf-vs-`tests/golden/` home — D-07 wording leans `tests/golden/`-style evidence artifact
(`CROSS-VALIDATION-LIMIT.md`) + frozen golden, owner-signed like the existing `CROSS-VALIDATION.md`.
**Owner sign-off + full attribution is a HARD GATE before freezing** (a `checkpoint:human-verify`).

---

## Shared Patterns

### Money domain entry (CLAUDE.md money policy)
**Source:** `itrader/core/money.py` — `to_money(x)` → `Decimal(str(x))`.
**Apply to:** every new price/level that enters the Decimal domain — `buy_limit(price=...)` →
`to_money(price)`; the fan-out LIMIT/STOP `price=intent.entry_price` (already Decimal via the factory's
`to_money`). NEVER `Decimal(float)`. Pattern seen at base.py:447, order.py:182, strategies_handler.py:146.
```python
stop_loss=to_money(sl) if sl is not None else None
```

### `Side` as the canonical action type (SIG-03)
**Source:** `events/order.py:47` (`OrderEvent.action: Side`), `events/signal.py:77` (`SignalEvent.action: Side`),
`core/enums` `Side` (has case-insensitive `_missing_` parser).
**Apply to:** `Order.action`, `_PendingBracket.action`, the bracket/validator/levels literal sites. After the
retype, prefer identity compares `order.action is Side.SELL` over `== Side.SELL.value`; drop `.value` at the
factory-call boundaries. RESEARCH Don't-Hand-Roll: use `Side(value)` for any residual string parse, never
`.upper()`/`== "BUY"`.

### Frozen-dataclass value-object schema-add (D-02/D-12)
**Source:** `SignalRecord` (signal_record.py) and `SignalIntent` (sizing.py) — both
`@dataclass(frozen=True, slots=True, kw_only=True)`.
**Apply to:** the new `SignalIntent.order_type/entry_price` and `SignalRecord.order_type/entry_price` fields.
`kw_only=True` means field order is not load-bearing; add an `Attributes` docstring entry per field (house style).

### Exception-safe terminal release (RECON-01 invariant — DO NOT REWRITE)
**Source:** `reconcile_manager.py:120-234` — `should_release` armed after terminal status, released in `finally`,
inner re-raise gated on `not body_raised`.
**Apply to:** the entire RECON-01 cleanup — extract helpers AROUND this skeleton; the `try`/`finally` STATEMENTS
and the two gate points stay byte-identical (WR-03/WR-04/T-05-17).

### Cross-val runner uniform contract (D-07)
**Source:** `scripts/crossval/*_run.py` — `run(prices=None, indicators=None) -> (trade_log_df, equity_curve_series)`,
trade_log normalized to `entry_date, exit_date, side, realised_pnl`, SCRIPT-ONLY (never imported under `tests/` —
`filterwarnings=["error"]` would trip on the engines' import-time warnings).
**Apply to:** the new LIMIT runners — same signature, normalized columns, same `scripts/cross_validate.py`
orchestrator + `reconcile.py` alignment.

---

## No Analog Found

None. Every file/symbol this phase touches has an exact or near-exact analog — most are in-file siblings
(`buy()`→`buy_limit`, `new_order`→`new_limit_order`, the 3 collapsing `get_position()` blocks), and the
SIG-03 `Side` retype copies the `OrderEvent.action: Side` type that already exists one layer out. This is a
"confirm, narrow, refactor-in-place, cross-validate" phase, not a greenfield one (RESEARCH key insight).

---

## Metadata

**Analog search scope:** `itrader/core/`, `itrader/strategy_handler/`, `itrader/order_handler/`
(`order.py`, `admission/`, `brackets/`, `reconcile/`, `order_validator.py`), `itrader/events_handler/events/`,
`scripts/crossval/`, `tests/e2e/matching/entries/`, `tests/e2e/strategies/`.
**Files scanned:** ~14 source files read directly (sizing, base, strategies_handler, signal_record, order,
signal event, order event, admission_manager 5 sections, reconcile_manager full, bracket_book, scripted_emitter,
backtesting_py_run, limit_touch scenario) + grep across bracket_manager/levels/order_validator action sites.
**Indentation verified:** bracket_book.py / levels.py / bracket_manager.py confirmed TAB this session
(resolves RESEARCH A3 / Pitfall 2).
**Pattern extraction date:** 2026-06-13
