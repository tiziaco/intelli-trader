# Phase 8: Admission, Position Management & Cash Edges - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 10 (1 new serializer, 2 modified infra files, ~7 new scenario leaves)
**Analogs found:** 10 / 10 (every file has a strong in-repo analog)

This is a TEST-COVERAGE phase. No engine code changes — all new/modified files are
test scaffolding + contrived scenario leaves. The engine machinery (scale-in,
`exit_fraction`, `max_positions`, re-entry, reserve/release + `CashOperation`
ledger) already ships and is scout-confirmed. Patterns below are extracted so the
planner can write concrete `read_first` + `action` fields per plan.

**Indentation map (load-bearing, per CLAUDE.md):**
- New cash-ledger serializer (`itrader/reporting/cash_operations.py`) — **4 spaces**
  (reporting package house style; matches `itrader/reporting/orders.py`).
- `tests/e2e/conftest.py`, `tests/e2e/strategies/scripted_emitter.py`, all
  `scenario.py` leaves — **4 spaces** (test package house style).
- All money stays `Decimal`; `float(...)` only at the CSV serialization edge.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/reporting/cash_operations.py` (NEW) | reporting / serializer | transform | `itrader/reporting/orders.py` | exact (role + data flow) |
| `tests/e2e/conftest.py` (MODIFY: `_assemble`, `_freeze`, `_diff` + identity-col consts) | test harness / wiring | transform | the orders-snapshot opt-in gate already in the same file (L310-311, L458-463, L511-515) | exact (same file, same idiom) |
| `tests/e2e/strategies/scripted_emitter.py` (MODIFY: add `allow_increase`, `max_positions` ctor params) | test fixture / strategy | event-driven | the Phase 7 `sizing_policy`/`sltp_policy` ctor-param precedent in the same file (L81-104) | exact (same file, same idiom) |
| `tests/e2e/admission/scale_in/scenario.py` (NEW, ADMIT-01+CASH-01 fold) | test scenario leaf | request-response | `tests/e2e/sizing/over_cash_reject/scenario.py` (REJECTED + cash lens) + `tests/e2e/smoke/single_market_buy/scenario.py` (round-trip + VERIFY) | role-match |
| `tests/e2e/admission/scale_out/scenario.py` (NEW, ADMIT-02) | test scenario leaf | request-response | `tests/e2e/smoke/single_market_buy/scenario.py` | role-match |
| `tests/e2e/admission/max_positions/scenario.py` (NEW, ADMIT-03) | test scenario leaf | request-response | `tests/e2e/sizing/over_cash_reject/scenario.py` (REJECTED orders-snapshot) | exact (REJECTED lens) |
| `tests/e2e/admission/re_entry/scenario.py` (NEW, ADMIT-04) | test scenario leaf | request-response | `tests/e2e/smoke/single_market_buy/scenario.py` | role-match |
| `tests/e2e/cash/release_cancelled/scenario.py` (NEW, CASH-02 CANCELLED) | test scenario leaf | request-response | `tests/e2e/sizing/over_cash_reject/scenario.py` + cash-ledger snapshot opt-in | role-match |
| `tests/e2e/cash/release_refused/scenario.py` (NEW, CASH-02 REFUSED) | test scenario leaf | request-response | `tests/e2e/sizing/over_cash_reject/scenario.py` + `spec.exchange` `max_order_size` lever | role-match |
| `tests/e2e/cash/release_rejected/scenario.py` (NEW, CASH-02 REJECTED no-orphan) | test scenario leaf | request-response | `tests/e2e/sizing/over_cash_reject/scenario.py` | exact (REJECTED + negative cash assertion) |

Each leaf also gets a sibling `bars.csv` (contrived), a one-line `test_scenario.py`
(`run_scenario(pathlib.Path(__file__).parent)`), and a frozen `golden/` set.

---

## Pattern Assignments

### `itrader/reporting/cash_operations.py` (NEW serializer — the one new artifact, D-02)

**Analog:** `itrader/reporting/orders.py` (the orders-snapshot opt-in serializer, D-08).

**What to copy:** the entire shape — module docstring stating the determinism
contract, a module-level `*_COLUMNS` list of business-only fields, a duck-typed
builder that produces `rows -> pd.DataFrame(columns=...) -> sort_values(...).reset_index(drop=True)`,
and `float(...)` only at the serialization edge.

**Column-selection idiom to copy** (`itrader/reporting/orders.py:37-49`):
```python
# Deterministic order-snapshot columns (D-08) — business fields only, NO UUID,
# NO wall-clock. ``role`` is the logical bracket linkage (ENTRY/SL/TP/STANDALONE).
ORDER_SNAPSHOT_COLUMNS = [
    "role",
    "ticker",
    "order_type",
    "action",
    "status",
    "price",
    "quantity",
    "filled_quantity",
    "time",
]
```

**Builder idiom to copy** (`itrader/reporting/orders.py:77-101`):
```python
def build_orders_snapshot(orders: Any) -> pd.DataFrame:
    rows = [{
        "role": _order_role(o),
        "ticker": o.ticker,
        ...
        "price": float(o.price),          # Decimal -> float ONLY at the edge
        "time": o.time,
    } for o in orders]
    frame = pd.DataFrame(rows, columns=ORDER_SNAPSHOT_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["role", "order_type", "action", "price"]).reset_index(drop=True)
    return frame
```

**Determinism constraint (D-02), DIFFERENT from orders.py inputs:** the source is
the `CashOperation` ledger, not orders. The snapshot MUST exclude the UUIDv7
`operation_id` AND the raw `reference_id` (order id) — both non-deterministic
(mirrors how orders.py excludes `id`/`event_id`/`created_at`/`updated_at`). Assert
on the stable trail: `operation_type`, `amount`, `balance_before`,
`balance_after`, business-`time`, and a **derived stable order correlation** (e.g.
`ticker` + a per-order ordinal/role, NOT the raw uuid) so a RESERVATION matches its
RELEASE without exposing an id. This is the direct analog of orders.py's
`_order_role` deriving a logical label from linkage flags instead of raw UUIDs
(`itrader/reporting/orders.py:52-74`).

**Source ledger object** (`itrader/portfolio_handler/cash/cash_manager.py:23-42`):
```python
@dataclass
class CashOperation:
    operation_id: uuid.UUID          # EXCLUDE (non-deterministic UUIDv7)
    operation_type: CashOperationType
    amount: Decimal
    timestamp: datetime              # event-derived business time on fill path
    description: str
    fee: Decimal = Decimal("0")
    reference_id: Optional[str] = None   # EXCLUDE raw value (order id) — derive a stable correlation
    balance_before: Optional[Decimal] = None
    balance_after: Optional[Decimal] = None
```

**`operation_type` enum values** (`itrader/core/enums/portfolio.py:58-69`,
`CashOperationType`): `DEPOSIT`, `WITHDRAWAL`, `TRANSACTION_DEBIT`,
`TRANSACTION_CREDIT`, `RESERVATION`, `RELEASE_RESERVATION`. Serialize via
`op.operation_type.name` (mirrors orders.py `o.status.name`).

**Reservation determinism note** (`cash_manager.py:365-416`, `reserve_cash`):
RESERVATION records `balance_before == balance_after` (reservation does not move
the ledger balance — only `available_balance` falls). `release_reservation`
(`cash_manager.py:418-448`) is idempotent and likewise records
`balance_before == balance_after`. The `timestamp` on RESERVATION/RELEASE is
`datetime.now(UTC)` (admission audit, wall-clock — see code comments at L409, L441),
so the serializer MUST NOT emit the raw reservation `timestamp` as a frozen column
without normalizing it, OR exclude it. CONSTRAINT for the planner: confirm during
authoring which CashOperation rows carry oracle-safe (event-derived) timestamps vs
wall-clock; the no-uuid + stable-trail column set in D-02 already steers away from
raw ids — apply the same caution to `timestamp`.

---

### `tests/e2e/conftest.py` (MODIFY — opt-in wiring of the cash-ledger snapshot, D-02)

**Analog:** the orders-snapshot opt-in gate ALREADY in this same file. Copy it
verbatim for the new cash-ledger snapshot.

**(a) Import** — add alongside the existing orders import
(`tests/e2e/conftest.py:72-74`):
```python
from itrader.reporting.orders import (
    ORDER_SNAPSHOT_COLUMNS,
)
```
Add: `from itrader.reporting.cash_operations import CASH_OPERATION_COLUMNS` (name
per D-06 discretion).

**(b) Identity / sort-key constants** — mirror the orders ones
(`tests/e2e/conftest.py:103, 112`):
```python
_ORDERS_IDENTITY_COLUMNS = ["role", "ticker", "order_type", "action"]
_ORDERS_SORT_KEYS = ["role", "order_type", "action", "price", "time"]
```
Add `_CASH_OPS_IDENTITY_COLUMNS` / `_CASH_OPS_SORT_KEYS` over the determinism-safe
columns (D-02).

**(c) `_assemble` — query the ledger AFTER the run** — mirror the orders-snapshot
assembly (`tests/e2e/conftest.py:308-311`):
```python
# Phase 6 (D-08): the order-mirror snapshot for the opt-in orders.csv golden.
# Queried AFTER the run (queue-only — D-07) for the spec's ticker + portfolio.
orders = build_orders_snapshot(
    system.order_handler.get_orders_by_ticker(spec.ticker, portfolio_id))
```
New cash-ledger line: `cash_ops = build_cash_operations(portfolio.cash_manager.get_cash_operations())`.
The portfolio object is already threaded into `_assemble(spec, system, portfolio, portfolio_id)`
(L303) and exposes `portfolio.cash_manager` (`itrader/portfolio_handler/portfolio.py:93`);
`get_cash_operations()` is at `cash_manager.py:460-470`. `_assemble` must return the
new `cash_ops` frame alongside `trades, equity, summary, orders`.

**(d) Opt-in freeze gate (THE key idiom)** — copy the `exists()` gate
(`tests/e2e/conftest.py:458-463`):
```python
# orders.csv is opt-in (D-09): only refreshed if the leaf already froze it
# (matching scenarios whose assertion is the final order-mirror state).
if (golden_dir / "orders.csv").exists():
    orders[ORDER_SNAPSHOT_COLUMNS].to_csv(
        golden_dir / "orders.csv", index=False, float_format=FLOAT_FORMAT
    )
```
Add the identical block guarded by `(golden_dir / "cash_operations.csv").exists()`.
This is what keeps the new serializer ORACLE-DARK (D-02/D-05): it only materializes
when a leaf commits the placeholder golden file.

**(e) Opt-in diff gate** — copy the orders diff block
(`tests/e2e/conftest.py:511-515`):
```python
orders_golden = golden_dir / "orders.csv"
if orders_golden.exists():
    gold = pd.read_csv(orders_golden)
    fresh = _roundtrip(orders, ORDER_SNAPSHOT_COLUMNS)
    _diff_frame(fresh, gold, _ORDERS_IDENTITY_COLUMNS, _ORDERS_SORT_KEYS)
```
Add the identical block for `cash_operations.csv`. Thread the new `cash_ops`
param through `_freeze(...)`, `_diff(...)`, and the `_run` callsite
(`tests/e2e/conftest.py:557, 561, 563`).

**Pin-protection constraint (D-02/D-05):** the cash-ledger serializer MUST stay out
of the oracle-pinned `frames.py::TRADE_COLUMNS` (`tests/e2e/conftest.py:66-71`
imports it). The opt-in `exists()` gate is exactly the mechanism that satisfies this
— `tests/integration/test_backtest_oracle.py` is never touched and stays byte-exact.

---

### `tests/e2e/strategies/scripted_emitter.py` (MODIFY — add `allow_increase` + `max_positions`, D-06)

**Analog:** the EXISTING `sizing_policy`/`sltp_policy` ctor-param threading in this
same file (Phase 7 D-12 precedent). Copy that exact kwarg → `BaseStrategyConfig` →
`SignalEvent` plumbing.

**Current ctor signature** (`tests/e2e/strategies/scripted_emitter.py:81-86`):
```python
def __init__(self, timeframe: str, tickers: list[str], *,
             script: dict[str, dict],
             order_type: OrderType = OrderType.MARKET,
             direction: TradingDirection = TradingDirection.LONG_ONLY,
             sizing_policy: SizingPolicy | None = None,
             sltp_policy: "SLTPPolicy | None" = None) -> None:
```
Add keyword-only `allow_increase: bool = False` and `max_positions: int = 1`
(defaults preserve existing leaves' behavior — D-06 explicit constraint).

**Current config construction** (`tests/e2e/strategies/scripted_emitter.py:96-104`)
— note `allow_increase=False` is currently HARD-CODED here; replace with the param:
```python
config = BaseStrategyConfig(
    timeframe=timeframe,
    tickers=list(tickers),
    sizing_policy=sizing_policy,
    direction=direction,
    allow_increase=False,        # <- replace with the new param
    order_type=order_type,
    sltp_policy=sltp_policy,
)
```
Set `allow_increase=allow_increase` and add `max_positions=max_positions`.

**Propagation path is fully wired engine-side (confirmed, no engine change needed):**
- `BaseStrategyConfig.allow_increase` (`itrader/strategy_handler/config.py:52`,
  default `False`) and `.max_positions` (`config.py:53`, `Field(default=1, gt=0)`).
- `Strategy` reads them (`itrader/strategy_handler/base.py:60-61`:
  `self.allow_increase = config.allow_increase`, `self.max_positions = config.max_positions`).
- `StrategiesHandler` stamps them onto the signal
  (`itrader/strategy_handler/strategies_handler.py:155-156`:
  `allow_increase=strategy.allow_increase`, `max_positions=strategy.max_positions`).
- `SignalEvent.allow_increase` / `.max_positions` already exist (`signal.py:90-91`),
  consumed by `_enforce_position_admission` (`order_manager.py:860-948`).

`exit_fraction` is already read per-bar from the script
(`scripted_emitter.py:126`: `exit_fraction = action.get("exit_fraction", Decimal("1"))`)
— scale-out (ADMIT-02) needs NO emitter change, only a script with `exit_fraction < 1`.

---

### Scenario leaves — common copy-template

**Template analog (round-trip + VERIFY note):** `tests/e2e/smoke/single_market_buy/scenario.py`.
Clone the structure: module docstring containing a `===== VERIFY =====` block that
states the contrived bars table, which bar fires each signal, the next-bar-open fill
prices, the sizing math, and every load-bearing frozen number. Then a module-level
`SCENARIO = ScenarioSpec(...)` the harness imports via `_load_spec`.

**`ScenarioSpec` / `PortfolioSpec` contract** — import from `tests/e2e/scenario_spec.py`
(field names are a consuming contract, do not rename): `start`, `end`, `timeframe`,
`ticker`, `starting_cash`, `data` (ticker → CSV path), `strategies`, `portfolios`
(`user_id`/`name`/`cash`), `exchange` (None = zero-fee/zero-slippage defaults).

**Standard wiring tail** (`tests/e2e/sizing/over_cash_reject/scenario.py:98-110`):
```python
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-04",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                sizing_policy=_SIZING)],
    portfolios=[PortfolioSpec(user_id=1, name="size03_pf", cash=_CASH)],
    exchange=None,
)
```
Pitfall (carried, `over_cash_reject:83`): the ticker MUST be `"BTCUSD"` — any other
ticker silently REFUSES every order.

---

### `tests/e2e/admission/scale_in/scenario.py` (ADMIT-01 + CASH-01 fold, D-04 leaf 1)

**Analogs:** `over_cash_reject/scenario.py` (cash-reservation REJECTED on the
cash-ledger lens) + `single_market_buy/scenario.py` (successful entry + VERIFY math).

**New knobs:** `ScriptedEmitter(..., allow_increase=True)`. Script = an initial BUY,
a second BUY (successful scale-in add — ADMIT-01 ✓), then a third BUY that exhausts
remaining cash → `cash_reservation` rejection (CASH-01). The scale-in fall-through
is `order_manager.py:916-926` (`allow_increase=True` → entry sizing); the resolver
reads CURRENT `available_cash` as remaining cash (`sizing_resolver.py:106-112`).

**Frozen goldens:** trade golden (the filled adds) + **opt-in
`cash_operations.csv`** asserting the over-cash add's RESERVATION never commits /
`available_cash` left intact / no orphan (the D-02 cash-ledger lens — distinct from
SIZE-03's order-mirror lens, D-01). Commit an empty/placeholder
`golden/cash_operations.csv` to opt this leaf into the snapshot.

**CASH-01 vs SIZE-03 (D-01 non-duplication constraint):** different trigger
(scale-in exhaustion, NOT a single oversized first entry) and different lens
(cash-ledger no-commit, NOT the orders-snapshot REJECTED row). Do not re-prove
SIZE-03.

### `tests/e2e/admission/scale_out/scenario.py` (ADMIT-02, D-04 leaf 2)

**Analog:** `single_market_buy/scenario.py`. Script = BUY then multiple SELLs each
with `"exit_fraction": Decimal("0.5")` (or similar `< 1`), position staying open
between them, final full close. `resolve_exit` computes `net_quantity * exit_fraction`
with a dust guard (`sizing_resolver.py:165-172`); partial sell keeps `is_open`
(`position.py:218-230`). Trade golden has multiple SELL rows. No new emitter knob
(`exit_fraction` already scripted).

### `tests/e2e/admission/max_positions/scenario.py` (ADMIT-03, D-04 leaf 3)

**Analog:** `over_cash_reject/scenario.py` (REJECTED orders-snapshot — same opt-in
vehicle, reused verbatim). `ScriptedEmitter(..., max_positions=1)` (or N); script
opens a position, then a new-ticker entry while `open_position_count >= max_positions`
→ audited REJECTED, `triggered_by="admission_max_positions"` (`order_manager.py:934-947`).
Freeze opt-in `golden/orders.csv` (empty placeholder to opt in), empty `trades.csv`,
`summary.json` `trade_count=0`. The REJECTED row serializes via `o.status.name`
(GAP #1 — never `ACTIVE`).

### `tests/e2e/admission/re_entry/scenario.py` (ADMIT-04, D-04 leaf 4)

**Analog:** `single_market_buy/scenario.py`. Script = BUY → full SELL (close) →
BUY again on the same ticker. Clean path: `close_position()` sets `is_open=False`
(`position.py:233-239`); `get_position()` then returns `None` so the re-entry takes
the fresh-position admission branch (`portfolio_read_model.py:107-125`). Trade golden
shows two closed/open round-trips. No special engine handling.

### `tests/e2e/cash/release_cancelled/scenario.py` (CASH-02 CANCELLED, D-04 leaf 5)

**Analogs:** `over_cash_reject/scenario.py` (leaf shape) + the cash-ledger snapshot
(opt-in). Reuses Phase 6 operator/cancel infra (the `actions` field on `ScenarioSpec`
+ the cancel hook — see `tests/e2e/conftest.py` `_make_on_tick`/operator path).
Trigger: a resting LIMIT BUY (construct emitter with `order_type=OrderType.LIMIT`)
→ reserve → operator-cancel → assert a POSITIVE `RELEASE_RESERVATION` op in the
cash-ledger snapshot (release on local cancel: `order_manager.py:1225-1227`).

### `tests/e2e/cash/release_refused/scenario.py` (CASH-02 REFUSED, D-04 leaf 6)

**Analogs:** `over_cash_reject/scenario.py` + cash-ledger snapshot + the Phase 7
`spec.exchange` re-init seam (D-14). Trigger (D-03, deterministic — NOT the RNG
`simulate_failures` path): a BUY exceeding a tiny `max_order_size` set via
`spec.exchange` (`ExchangeConfig.limits.max_order_size`, `itrader/config/exchange.py`)
→ `simulated.py::_admit_order` `validate_order` failure (`~L122-127`) → `_emit_rejection`
→ `FillEvent(REFUSED)` → terminal release on the fill (`order_manager.py:257-273`,
`should_release` on EXECUTED/CANCELLED/REFUSED). Assert a POSITIVE
`RELEASE_RESERVATION` op. This leaf populates `spec.exchange` (NOT `None`) — see the
re-init seam at `tests/e2e/conftest.py:~237-254`.

### `tests/e2e/cash/release_rejected/scenario.py` (CASH-02 REJECTED no-orphan, D-04 leaf 7)

**Analog:** `over_cash_reject/scenario.py`. Honest-asymmetric coverage (D-03):
REJECTED structurally NEVER holds a reservation (max_positions/allow_increase reject
BEFORE `reserve()`; cash_reservation reject IS the reserve failing atomically,
`order_manager.py:399-411`). Assert the NEGATIVE in the cash-ledger snapshot: NO
orphan RESERVATION row, `available_cash` intact. Do NOT fabricate a reserve-then-REJECTED
path — none exists (deferred, owner-gated). Freeze opt-in `cash_operations.csv`
(showing the absence) + orders-snapshot REJECTED row.

---

## Shared Patterns

### Opt-in golden snapshot (the phase's central reused idiom)
**Source:** `tests/e2e/conftest.py` orders-snapshot gate — `_freeze` L458-463,
`_diff` L511-515, `_assemble` L308-311.
**Apply to:** the new cash-ledger snapshot (D-02) AND all REJECTED/no-trade leaves
(max_positions, release_rejected). A golden file is written/diffed ONLY when its
placeholder already exists in the leaf's `golden/` — this is what keeps the new
serializer oracle-dark.
```python
if (golden_dir / "orders.csv").exists():
    orders[ORDER_SNAPSHOT_COLUMNS].to_csv(
        golden_dir / "orders.csv", index=False, float_format=FLOAT_FORMAT)
```

### Determinism-safe column selection (no UUIDs, no wall-clock)
**Source:** `itrader/reporting/orders.py` — `ORDER_SNAPSHOT_COLUMNS` (L39-49) +
`_order_role` deriving a stable logical label from linkage flags instead of raw
UUIDs (L52-74).
**Apply to:** `itrader/reporting/cash_operations.py` — exclude `operation_id`
(UUIDv7) and raw `reference_id` (order id); derive a stable per-order correlation
(ticker + ordinal/role). Caution on `timestamp` (wall-clock on reserve/release).

### Decimal → float only at the edge
**Source:** `itrader/reporting/orders.py:92-94` (`float(o.price)` etc.) and
`tests/e2e/conftest.py:331` (`float(p.commission)`).
**Apply to:** the cash-ledger serializer (`float(op.amount)`,
`float(op.balance_after)`) — money stays `Decimal` everywhere upstream.

### Ctor-param threading into ScriptedEmitter
**Source:** `tests/e2e/strategies/scripted_emitter.py:81-104` (the
`sizing_policy`/`sltp_policy` precedent: kwarg → `BaseStrategyConfig` field →
already-wired `SignalEvent` plumbing).
**Apply to:** `allow_increase` + `max_positions` (D-06). Defaults
(`allow_increase=False`, `max_positions=1`) MUST preserve existing leaves' behavior.

### VERIFY-note hand-derivation + `--freeze` discipline
**Source:** `tests/e2e/smoke/single_market_buy/scenario.py:16-92` (the VERIFY block
template) and the mechanical one-scenario `--freeze` guard
(`tests/e2e/conftest.py:539-551`).
**Apply to:** every new leaf — a human verifies the derivation matches `golden/`
BEFORE the freeze is locked; freeze one hand-verified scenario at a time.

### Foundational-plan-first, then parallel waves (D-05)
**Source:** Phase 6 D-13 / Phase 7 D-16 sequencing (carried). Plan 1 (non-parallel):
the cash-ledger serializer + opt-in wiring + emitter params + ONE canary leaf,
re-running the BTCUSD oracle gate byte-exact. Then parallel ADMISSION / CASH waves
in isolated worktrees, hand-verify + freeze batched per cluster.

---

## No Analog Found

None. Every file in this phase has a strong in-repo analog (this is a coverage
phase building on already-shipped infra). The only "new" code (the cash-ledger
serializer) is a structural clone of `itrader/reporting/orders.py`.

---

## Metadata

**Analog search scope:** `itrader/reporting/`, `tests/e2e/` (conftest, strategies,
smoke, sizing leaves), `itrader/portfolio_handler/cash/`,
`itrader/strategy_handler/` (config/base/strategies_handler), `itrader/core/enums/`.
**Files scanned (read):** `itrader/reporting/orders.py`,
`tests/e2e/strategies/scripted_emitter.py`, `tests/e2e/conftest.py` (gates +
`_assemble` + `_freeze`/`_diff`), `itrader/portfolio_handler/cash/cash_manager.py`,
`tests/e2e/smoke/single_market_buy/scenario.py`,
`tests/e2e/sizing/over_cash_reject/scenario.py`, plus grep confirmation of the
`allow_increase`/`max_positions` config→signal threading and `CashOperationType`
enum members.
**Pattern extraction date:** 2026-06-10
