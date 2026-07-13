# ForceCloseEvent — Honest Identity for System-Originated Position Closes — Design Spec

- **Date:** 2026-07-13
- **Status:** DRAFT (brainstorm output; ready for user review, then planning)
- **Branch context:** `v1.8/phase-6-live-runner`
- **Path posture:** live-only / **oracle-dark** — the backtest golden (`final_equity 46189.87730727451`) must stay byte-exact.
- **Deliverable of this doc:** a design the planner can decompose into an executable phase/plan.

> Decision tags are written `FC-NN` (Force-Close). They were **locked during the brainstorming
> session that produced this doc** and are citable by downstream plans. Per-plan specifics (exact
> signatures, migration column ordering, test names) firm up at plan time.

---

## 1. North Star & scope posture

**Core value:** a system-originated position close (universe force-remove today; operator emergency
shutdown soon) must be **honestly attributable** end-to-end — no fabricated strategy identity, no
mislabeled trigger source — without disturbing the byte-exact backtest oracle.

**The defect this closes.** `UniverseHandler._emit_force_close_exit`
(`itrader/universe/universe_handler.py:707-734`) fabricates a `SignalEvent` to liquidate a position
when a ticker is force-removed from the universe. Because `SignalEvent.strategy_id` is a mandatory
non-null field and this exit has no owning strategy, the handler mints a **fresh random UUIDv7
`StrategyId` per event** (module-level `_idgen`, line 92/728). Consequences:

1. **Unattributable id** — every force-close carries a unique random id, so these liquidations
   cannot be grouped, distinguished from real strategy signals, or traced as "universe force-close"
   anywhere downstream.
2. **Mislabeled trigger** — the fabricated `SignalEvent` enters the normal `on_signal → admission →
   Order.new_order` path, which stamps `OrderTriggerSource.STRATEGY` with the message
   `"Order created from strategy {random-uuid}"` (`order.py:235-238`). The audit trail therefore
   lies twice: a fake strategy id **and** a `STRATEGY` label on a control-plane action.

### In scope
- A new **`ForceCloseEvent`** domain event (the honest primitive) + `EventType.FORCE_CLOSE` + route.
- An **`OrderHandler.on_force_close`** consumer that direct-builds the close Order (bypasses admission
  adjudication, keeps the venue fill).
- Making **`strategy_id` optional** (`StrategyId | None`) at the Order / OrderEvent / FillEvent / SQL
  order-store layer — the load-bearing honesty change.
- Two new **`OrderTriggerSource`** members (`UNIVERSE_REMOVE`, `OPERATOR_FORCE_CLOSE`).
- Migrating `UniverseHandler` to emit `ForceCloseEvent(origin=UNIVERSE_REMOVE)`; deleting the stray
  module-level `_idgen`.
- The one-line liquidation honesty fix (`portfolio_handler.py:536` → `strategy_id=None`).

### Explicitly out of scope (this spec)
- **The operator emergency-shutdown command itself.** `ForceCloseEvent` is the primitive it will
  consume; the command's ingress + fan-out + halt orchestration is a **follow-up drafted in §8
  (marked DRAFT — must be concluded)**, not built here.
- Any change to the **margin-liquidation control flow** (`portfolio_handler.py`). It is a
  synthetic-fill-at-a-computed-price path — a genuinely different animal from a venue market exit —
  and stays its own direct-build path. It inherits only the one-line `strategy_id=None` change.
- Any change to the **strategy signal path.** `SignalEvent` is left pristine (see FC-03).

---

## 2. Scope-shaping decisions locked this session

| Tag | Decision | Rationale |
|-----|----------|-----------|
| FC-01 | **A force-close is not a strategy signal — it gets its own event type** (`ForceCloseEvent`), not a widened `SignalEvent`. | `SignalEvent` is defined as "a pure, immutable **strategy** fact." A control-plane close is definitionally not that. A dedicated type carries only what is true and needs **no `strategy_id` field at all**. |
| FC-02 | **The root cause is a non-null field that should be nullable.** Make `strategy_id` optional at the Order/Fill/store layer. | Every fake value (sentinel or random) is a symptom of modeling "no owning strategy" as non-representable. Honesty = make `None` legal where a strategy-less order genuinely lives. **No sentinel `StrategyId`** — that reads as a lie. |
| FC-03 | **`SignalEvent` stays pristine; the `Optional` blast radius is localized to the Order/Fill layer.** | `SignalEvent.strategy_id` remains mandatory (strategy signals always have an owner). Only `Order`/`OrderEvent`/`FillEvent`/`orders` table go optional — exactly where a strategy-less order exists. |
| FC-04 | **Force-close bypasses admission adjudication but keeps the venue fill** (tier-2 direct build). | An exit needs almost none of admission's adjudication (leaving-gate sanctions it, direction passes, cash releases, sizing is the whole position, the **venue re-validates at execution** regardless — D-03a). So not routing through admission costs little and avoids threading a foreign discriminator through it. |
| FC-05 | **Derive side & size at handle-time from the read model; do not carry them on the event.** | More robust than pre-computing: no stale side, and an already-flat position at handle-time is a clean no-op. Supports the operator fan-out (positions may close mid-fan-out). |
| FC-06 | **One event, discriminated by an `origin` enum** (`ForceCloseOrigin`), mapped 1:1 to `OrderTriggerSource` at order build. | Avoids event-type proliferation per origin; the origin taxonomy grows by adding enum members, not event types. |
| FC-07 | **Oracle-dark by construction.** | Universe/operator/liquidation are live-only; `OrderTriggerSource` and `strategy_id` are audit-only (never affect fills). The backtest golden cannot move. |

---

## 3. Design

### 3.1 `ForceCloseEvent` (new domain event)

New frozen event under `itrader/events_handler/events/` (domain file, e.g. `force_close.py`),
matching the events-package house style (`@dataclass(frozen=True, slots/kw_only)`, 4-space indent,
`type` pinned via the package idiom, UUIDv7 `event_id`, business `time`):

```python
class ForceCloseEvent(Event, frozen=True, kw_only=True, gc=False):
    type = EventType.FORCE_CLOSE          # new EventType member
    ticker: str
    portfolio_id: PortfolioId
    origin: ForceCloseOrigin              # UNIVERSE_REMOVE | OPERATOR
    exit_fraction: Decimal = Decimal("1") # full exit by default; (0, 1]
    # time carried by base Event
```

**No `strategy_id`. No `action`. No `quantity`.** (FC-01, FC-05) — side and size are derived at
handle-time from the live position.

`ForceCloseOrigin` is a new enum (`core/enums/`, sits with the order/execution enums or a small
control-plane enum module):

```python
class ForceCloseOrigin(Enum):
    UNIVERSE_REMOVE = "universe_remove"
    OPERATOR        = "operator"
```

### 3.2 Routing

- Add `EventType.FORCE_CLOSE` to `core/enums/event.py::EventType`.
- Register the route in the route registrar / `EventHandler._routes`:
  `routes[EventType.FORCE_CLOSE] = [OrderHandler.on_force_close]`.
- `_dispatch` already raises `NotImplementedError` on an unrouted type — no silent drop.

### 3.3 `OrderHandler.on_force_close` (the consumer — tier-2 direct build)

The liquidation pattern **generalized**, but routed through execution instead of synthesizing the
fill. Thin `OrderHandler` method delegating to `OrderManager` (matching the facade→manager split):

1. Resolve the live position via the injected `PortfolioReadModel`
   (`get_position(portfolio_id, ticker)`).
2. **No open position → clean no-op** (log at debug/info, drop the event). (FC-05 — handles races and
   operator fan-out over a position that just closed.)
3. Derive `action = SELL if LONG else BUY` and `quantity = abs(net_quantity) * exit_fraction`
   (full exit when `exit_fraction == 1`).
4. Build a MARKET `Order` **directly** via the entity constructor (as `portfolio_handler.py:527`
   does), with `strategy_id=None`, `portfolio_id`/`exchange` from the resolved portfolio, and an
   **indicative price = the resolved position's `avg_price`** (the value today's universe code
   already carries; a MARKET order fills at the venue, so the carried price is indicative only —
   no feed/price-source dependency is introduced).
5. Stamp the honest trigger source via `add_state_change(..., triggered_by=<mapped>)` where the map
   is `ForceCloseOrigin.UNIVERSE_REMOVE → OrderTriggerSource.UNIVERSE_REMOVE` and
   `ForceCloseOrigin.OPERATOR → OrderTriggerSource.OPERATOR_FORCE_CLOSE` (FC-06).
6. Register the order in the **shared mirror** (`add_order`) so the fill reconciles to FILLED
   (mirrors `portfolio_handler.py:548-549`).
7. Emit an `OrderEvent`. Normal execution takes over → the venue validates + fills → `FillEvent`
   reconciles the mirror and updates the portfolio.

Bypassed: admission's gates/sizing/cash-reservation. **Not** bypassed: execution + the venue's own
`validate_order` boundary gate (D-03a) — so force-close cannot submit a structurally invalid order.

### 3.4 `strategy_id` becomes `Optional` (FC-02 — the load-bearing change)

`StrategyId | None` across:

- `Order.strategy_id` (entity) and the `new_order` / `new_limit_order` / `new_stop_order` factory
  signatures (accept `StrategyId | None`; strategy signals always pass a real id).
- `OrderEvent.strategy_id`, `FillEvent.strategy_id`.
- `orders.strategy_id` column → `nullable=True` (Alembic migration in the order-store chain).
- `sql_storage` read/write mapping: persist `None`, hydrate `None` (no `StrategyId(row[...])` on a
  null).

**Nothing branches on `strategy_id`** (established by trace): no FK (durable strategy identity is the
**name** in `strategy_registry_store`, never this ephemeral runtime id), portfolio/reconcile never
read it, and `SignalRecord.by_strategy` never sees these events (they bypass `StrategiesHandler`). So
`None` breaks no logic — `mypy --strict` forces `None`-handling only at the serialization/log edges
(the OKX audit chain logs "no strategy"). Migration is unproblematic: **nothing is in production yet.**

### 3.5 `OrderTriggerSource` — two honest members

Add to `core/enums/order.py::OrderTriggerSource`:

```python
UNIVERSE_REMOVE      = "universe_remove"
OPERATOR_FORCE_CLOSE = "operator_force_close"
```

Audit trail now reads truthfully: *order, `strategy_id=None`, triggered by
`OPERATOR_FORCE_CLOSE`* — no random id, no `STRATEGY` lie. (`LIQUIDATION` already exists for the
margin path.)

### 3.6 Call-site changes (the payoff)

- **`universe_handler.py`** — `_emit_force_close_exit` emits
  `ForceCloseEvent(time=asof, ticker=sym, portfolio_id=portfolio_id, origin=ForceCloseOrigin.UNIVERSE_REMOVE)`
  instead of the fabricated `SignalEvent`. It no longer computes side/price/sizing (derived at
  handle-time). The module-level **`_idgen` (line 92) is deleted** — resolving the original
  convention nit (a second `IDGenerator()` instead of the process-wide singleton) by removing the
  need for it entirely.
- **`portfolio_handler.py:536`** — `strategy_id=None` (one line; no structural change to the
  liquidation path).

Result: all three fake-id mint sites are gone, and no second `IDGenerator()` survives.

---

## 4. Data flow

**Universe force-remove (this spec):**

```
UniverseHandler.on_universe_update (remove, force-close policy, holder found)
  → ForceCloseEvent(origin=UNIVERSE_REMOVE)         [on the bus]
    → OrderHandler.on_force_close
        → resolve position (read model) → derive SELL/BUY + size
        → build MARKET Order(strategy_id=None), stamp UNIVERSE_REMOVE, register mirror
        → OrderEvent                                 [on the bus]
          → ExecutionHandler.on_order → venue validate + fill → FillEvent
            → PortfolioHandler.on_fill (positions/cash)  +  OrderHandler.on_fill (mirror → FILLED)
```

**Margin liquidation (unchanged, honesty-only):** still direct-builds Order + synthetic FillEvent in
`portfolio_handler`, now with `strategy_id=None` + existing `LIQUIDATION` trigger.

---

## 5. Testing & oracle safety (FC-07)

- **Oracle byte-exactness:** re-run the SMA_MACD oracle (`tests/integration/test_backtest_oracle.py`)
  — must stay `46189.87730727451`. Guaranteed by construction (live-only, audit-only fields), proven
  by the run.
- **`ForceCloseEvent`:** construction/immutability; no-op when the position is already flat at
  handle-time; correct side/size derivation for LONG and SHORT.
- **Consumer:** `on_force_close` builds a MARKET order with `strategy_id=None` and the origin-mapped
  `OrderTriggerSource`; registers the mirror; emits an `OrderEvent`; reconciles to FILLED on the fill.
- **Universe migration:** `_emit_force_close_exit` now emits a `ForceCloseEvent` (not a `SignalEvent`);
  `_idgen` is gone.
- **Optional `strategy_id` round-trip:** an order with `strategy_id=None` persists to and hydrates
  from the SQL order store; `mypy --strict` clean.
- **Marker hygiene:** respect `filterwarnings=["error"]`, `--strict-markers` (live tests use the
  hand-applied `live` marker where appropriate).

---

## 6. Downstream / follow-on impact

- **FastAPI-readiness:** honest, queryable order attribution (real trigger source + explicit
  `None`-means-system) is strictly better for the planned web/query layer than random ids.
- **Operator shutdown (§8):** the primitive is exactly what the shutdown command fans out.

---

## 7. Decision log (citable)

`FC-01` own event type · `FC-02` optional `strategy_id`, no sentinel · `FC-03` `SignalEvent` pristine ·
`FC-04` bypass admission, keep venue fill · `FC-05` derive side/size at handle-time · `FC-06` one
event + `origin` enum mapped to `OrderTriggerSource` · `FC-07` oracle-dark.

---

## 8. Follow-up consumers (tracked as GSD pending todos)

The operator commands that *consume* this primitive are **out of scope of this spec** and captured as
pending todos, each to be concluded into its own spec before implementation:

- **Targeted single-position operator close** — one `ForceCloseEvent(origin=OPERATOR)`, no halt.
  `.planning/todos/pending/operator-force-close-position-command.md`
- **Emergency shutdown** — fan-out `ForceCloseEvent(origin=OPERATOR)` over all open positions + latch
  `HALTED`. `.planning/todos/pending/operator-emergency-shutdown-command.md`

Both depend only on the primitive delivered here (event + route + `OrderHandler.on_force_close`);
their open design questions (ingress shape, ordering vs halt, idempotency, resting-order handling,
partial-failure, authorization) live in those todos.
