# Phase 5: M4 — Money & Transaction Correctness - Research

**Researched:** 2026-06-06
**Domain:** Brownfield internal refactor — cash routing, transaction atomicity, order-handler layering, Protocol boundaries, execution DTO cleanup (Python 3.13, event-driven engine)
**Confidence:** HIGH (all findings from direct codebase reads at current HEAD; no external dependencies introduced)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Cash routing & reservations (M4-01, #22)
- **D-01: Full reservation lifecycle, reserve at order admission.** Cash is reserved when an
  order is accepted (PENDING), released on terminal state (fill/cancel/reject), and the fill
  settles as a debit/credit. Exercises the whole CashManager API; matches live-trading needs.
- **D-02: Sync check-and-reserve at admission (broker/Nautilus pattern).** Atomic
  check+reserve happens synchronously in `OrderManager`'s admission path via the portfolio
  access Protocol (D-12) — reserve succeeds → order emitted; reserve fails → REJECTED via the
  Phase 4 audited state-change path, nothing emitted. NOT queue-mediated (that would split
  check from act — a TOCTOU). Settlement (release + debit/credit) still flows via FillEvent
  through the queue: the queue stays the source of truth for facts; the sync call is only the
  pre-trade gate.
- **D-03: Only cash-debiting orders reserve.** BUYs reserve; SELL exits (incl. bracket SL/TP
  children) reserve nothing — no cash to earmark, no OCO double-reservation. Position-quantity
  reservation deferred to live-mode work.
- **D-04: Reservation amount = order.price × quantity + estimated commission** (from the
  exchange fee model rate). At fill: release the full reservation, debit the actual net cost.
  The reservation is a pre-trade gate, not a hard ceiling — gap fills still settle. Mirrors
  today's `_check_funds_availability` math (value-preserving).
- **D-05: `Portfolio.cash` setter and `apply_transaction_delta` both DELETED.** `cash` becomes
  a read-only property; the trade path calls `cash_manager.process_transaction_cash_flow(...)`
  with proper debit/credit semantics. `deposit`/`withdraw` survive for genuine external cash
  ops only; withdrawals draw against **available_balance** (can't withdraw reserved cash).
  Initial funding stays a DEPOSIT entry at portfolio creation.
- **D-06: One ledger entry per fill; `amount` = net cash delta; `fee` field on the entry**
  (user-proposed, CCXT/broker-statement style). `amount` is the actual cash applied
  (principal ± commission); `fee` records the commission portion included in it. Balance
  reconstruction stays trivial (balance = Σ signed amounts); total fees = Σ fee column. No
  standalone FEE entries (those only ever arise for non-trade fees — D-live).
- **D-07: Cash ledger entries route through the Phase 3 portfolio storage seam.** In-memory
  backend for backtest (same behavior as today); live/Postgres gets the durable audit trail
  for free at the persistence milestone.
- **D-08: Reservations affect only `available_balance`, never balance/equity/metrics.**
  `balance` = real cash (drives equity curve, metrics, oracle — unchanged);
  `available_balance` = balance − reservations (drives order admission only). Account-value
  vs buying-power semantics; reservations invisible to the oracle.

#### Atomicity & error contract (M4-02, #16, #23)
- **D-09: Validate-first, fail-fast — no saga.** Settlement reorders to: validate → check
  invariants → mutate position → apply cash. Nothing mutates until all checks pass, so no
  rollback machinery is needed (a fill is a FACT — solvency was enforced pre-trade by D-02;
  LMAX/Nautilus validate-first sequential shape). The never-used `ROLLED_BACK`/saga machinery
  is deleted, not finished. Durable DB-transaction rollback arrives later via the storage seam
  (live/Postgres) — never hand-rolled in application code.
- **D-10: Error contract = raise typed, return None.** `process_transaction` returns `None` on
  success and raises typed domain exceptions (`InsufficientFundsError` etc., Phase 4 hierarchy)
  on failure; the unreachable bool contract is deleted. One channel, never two. The settlement
  funds check survives as an **invariant guard**: actual cost > balance → raise (engine bug —
  the reservation gate should have prevented it). Backtest: propagates through the Phase 4
  `_on_handler_error` seam re-raise → run stops loudly (never produces corrupted numbers).
  Live (D-live, later): same raise caught at the seam → circuit breaker (halt trading, alert,
  engine stays on). Accounting code stays mode-agnostic. Value-preserving: never fires in the
  golden run.
- **D-11: `TransactionContext` deleted entirely.** TransactionState enum, pending-dict,
  cancel/retry machinery all die. The applied `Transaction` entity — recorded through the
  storage seam, carrying `fill_id`/event-derived time per Phase 4 linkage — IS the durable
  audit record. No second lifecycle on settlements (order lifecycle already lives on the Order
  entity per Phase 4 D-13).
- **D-12: `Portfolio` orchestrates the settlement sequence** under its own roof:
  validate (TransactionManager) → funds invariant (CashManager) → position mutate
  (PositionManager) → cash apply (CashManager) → record (TransactionManager). Each manager
  does exactly one concern and never touches a sibling — resolves #29 on the trade path
  (aggregate-owns-unit-of-work shape). `TransactionManager` shrinks to validation + recording
  + history queries.

#### Portfolio access Protocol (M4-04, #6)
- **D-13: One combined Protocol** (user chose simplicity over read/write interface
  segregation): a single portfolio access Protocol carrying `available_cash`, `get_position`,
  `reserve`, `release`. M4-04's "read-only views" is satisfied by the RETURNED views being
  read-only (frozen `PositionView`, Decimal values) and by killing the concrete
  `PortfolioHandler` dependency + internals access — document this interpretation in the plan.
- **D-14: `available_cash` (buying power) is the single trading-decision figure** exposed to
  sizing, validation, and risk checks — sizing and admission can never disagree. Equity/total
  cash stay on `Portfolio` for metrics/reporting and do NOT enter the order-domain surface.
  Value-preserving: available == total at every BUY decision point in the golden run
  (long-only, one position at a time, cash-debit-only reservations) — **planner/executor must
  verify this with a trace before relying on it**.
- **D-15: `get_position()` returns a frozen `PositionView` DTO** (frozen/slots dataclass:
  ticker, side, net_quantity, avg_price — exactly the fields consumers read today),
  Decimal-typed, `None` when flat. Rule: live objects inside a module, immutable snapshots
  across a boundary (CQRS/FIX-report shape, consistent with Phase 4 frozen events).
- **D-16: `PortfolioHandler` implements the Protocol directly** (structural typing — no
  adapter, no inheritance). Order-domain constructors retype from `PortfolioHandler` to the
  Protocol so `mypy --strict` enforces the narrow boundary; the concrete import dies. Module
  location for Protocol + PositionView = Claude discretion (likely `itrader/core/`, killing
  the cross-domain import direction).
- **D-17: `variable_sizer` / `advanced_risk_manager` retype to the Protocol NOW** — they're
  part of the admission path #6 covers. M5b then completes sizing policy on top of an
  already-clean boundary.

#### Order layering, locks & DTOs (M4-03, M4-05, M4-06, M4-07)
- **D-18: M4-03 facade prescription is locked by requirement:** deprecated facade methods
  (`add_pending_order`, `remove_orders`, `remove_order`) deleted; `OrderManager → OrderHandler`
  back-ref removed (manager returns events, handler owns ALL queue puts); `OrderManager` gets
  exclusive ownership of `OrderStorage`; all handler `get_*`/`search_*` reads delegate through
  the manager. Test fallout from deprecated-method deletion handled mechanically.
- **D-19: NO locks — single-writer contract** (user challenged locks entirely; confirmed
  correct). Per-manager RLocks, the portfolio lock, and the readerwriterlock theater are
  deleted. Documented contract: ALL portfolio state mutations happen on the engine thread;
  `queue.Queue` is the thread boundary (other threads only put events). Composite reads are
  consistent because nothing mutates concurrently — by architecture (LMAX/Nautilus
  single-writer). Resolves #29's cross-lock torn reads honestly. Live cross-thread reads are a
  D-live design item (queue-mediated request/response or Postgres-backed).
- **D-20: `InMemoryOrderStorage` keeps the flat `{order_id: order}` dict ONLY.** Nested dicts
  deleted (completes Phase 2's deferred M4-06 scan elimination). Queries by
  ticker/portfolio/status scan-and-filter the flat dict — O(n) over a handful of resting
  orders is nothing; lookup/removal O(1) (PERF3); one source of truth, no dual-write bugs.
- **D-21: `ExecutionResult` DELETED — events are the only execution output** (Nautilus/FIX
  shape: no sync results in the engine core). `execute_order` returns `None`; `FillEvent`
  (full Phase 4 linkage: fill_id/order_id/event_id) is the single channel. User probed the
  FastAPI implication and it's resolved: HTTP responses come from the ORDER domain —
  Order entity/`OperationResult` at admission (`POST /orders` → 201 {order_id, PENDING}),
  `OrderManager` read path + audited state history for GET, FillEvent stream for live updates.
  Surviving `result_objects` DTOs reconciled per-DTO (genuinely-used → frozen/Decimal; dead →
  deleted); the ×3 `ValidationResult` name collision resolved in passing;
  `AbstractExecutionHandler` becomes a real ABC including `on_market_data`; stale Compliance
  docstring dropped.
- **D-22: Event-money → Decimal retype (Phase 4 D-04 deferral) under byte-exact-or-stop.**
  Retype Signal/Order/Fill event money fields to Decimal and remove the preserved
  Decimal→float→Decimal boundary coercions, engineered to be numerically inert
  (`Decimal(str(x))` round-trips). Any oracle diff = STOP / investigate / §E owner decision —
  never silently absorbed, never a tolerance window.

### Claude's Discretion
- Exact Protocol + `PositionView` module location and naming (likely `itrader/core/`).
- Exact `CashOperationType` member names/semantics (debit/credit vocabulary), reservation
  reference-ID scheme (keyed by `order_id`), and the `CashOperation` field set with the new
  `fee` field.
- How the commission estimate for reservations is obtained from the fee model (rate lookup vs
  callable), as long as the admission math mirrors today's funds check.
- Which `result_objects` DTOs survive per-DTO; `ValidationResult` namespacing approach.
- `TransactionManager`'s surviving method surface after the shrink (validation + recording
  + history queries).
- Storage wiring for `OrderManager` ownership (constructed in manager vs injected) and the
  TradingSystem wiring updates.
- Order of workstreams and commit sequencing, under the standing constraints: suite + both
  byte-exact oracle layers green at every commit, each workstream bisectable (Phase 3/4
  precedent).
- Test-suite adjustments for deleted surfaces (deprecated facade methods, TransactionContext,
  locks, ExecutionResult) — update/delete tests of removed machinery, add coverage for the new
  reservation/settlement paths.

### Deferred Ideas (OUT OF SCOPE)
- **Position/quantity reservation for SELL orders** (preventing share over-commitment across
  orders) → live-mode work.
- **Live circuit-breaker policy** at the `_on_handler_error` seam → **D-live**; the seam exists
  (Phase 4 D-16).
- **Standalone FEE ledger entries for non-trade fees** (funding, withdrawal charges) → **D-live**.
- **Slippage safety buffer on reservations** → live-mode calibration (must default to 0 to stay
  value-preserving regardless).
- **Live cross-thread portfolio reads** (queue-mediated request/response or Postgres-backed) →
  **D-live** design item, replaces the deleted lock theater with a real mechanism.
- **Typed REST response objects for live exchange adapters** → **D-live** adapter boundary.
- **Uniform `on_<event>` Protocol/ABC boundary contracts across ALL handlers** → roadmap backlog.
- **Protocol equity/percent-of-equity read methods** for completed sizing policies → **M5b (M5-06)**.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M4-01 | Every trade routes cash through `CashManager`; ledger/reservations/audit live (#22 Critical) | `CashManager` already has the full target API (verified: `cash/cash_manager.py` — `process_transaction_cash_flow:222`, `reserve_cash:335`, `release_cash_reservation:385`, `available_balance:101`, `reserved_balance:107`). Trade path today routes through `apply_transaction_delta:284` (the interim CR-03 seam to delete). Cash setter at `portfolio.py:216-225` has NO production callers (only test mocks) — deletion is mechanical. See Pitfalls 1, 2, 5 and Architecture Pattern 1. |
| M4-02 | Atomic transaction processing; funds before position mutation; one error/return contract | The position-first defect is confirmed: `portfolio.py:289-308` calls `position_manager.process_position_update` BEFORE `transaction_manager.process_transaction` (cash). The unreachable contract is confirmed: `transaction_manager.py:136-138` — `except` calls `_handle_transaction_error` (which bare-`raise`s at `:308`) then has dead `return False`. `TransactionContext`/`TransactionState` deletion sites mapped (see Pattern 2). |
| M4-03 | One-directional facade→manager→storage; read path through manager; back-ref removed; manager owns storage | Deprecated methods at `order_handler.py:104-134`; back-ref is `OrderManager.__init__` third arg (`order_manager.py:41-63`, stored as `self.order_handler`, never used in any method body — pure delete); 8 handler read methods bypass the manager straight to `self.order_storage` (`order_handler.py:238-356`); storage constructed in `OrderHandler.__init__:61` and passed in by both TradingSystems (`backtest_trading_system.py:68-69`, `live_trading_system.py:111-117`). |
| M4-04 | Cross-handler reads via narrow `PortfolioReadModel` Protocol, not concrete `PortfolioHandler` | All consumer sites enumerated (see Integration Map). NOTE: the validator reads MORE than the locked Protocol surface (`exchange`, `positions` dict, `n_open_positions`, `total_equity`, `cash`) — see Open Question 1 for the reconciliation options. |
| M4-05 | Intra-portfolio coupling + thread-safety theater resolved | Full lock inventory captured (see Pattern 4): 4 per-manager RLocks, portfolio RLock, `readerwriterlock.RWLockFair` + `_operations_lock` in PortfolioHandler, `SimulatedExchange._lock`. `LiveTradingSystem._status_lock`/`_stats_lock` STAY (system lifecycle, per CONTEXT). Sibling-touching: `TransactionManager._execute_transaction` reaches into `self.portfolio.cash_manager` (`transaction_manager.py:246`) and reads `self.portfolio.cash` (`:215,245`). |
| M4-06 | O(1) flat `{order_id: order}` index, nested dicts deleted | Flat `_by_id` index exists since Phase 2 (`in_memory_storage.py:41`). Three nested dicts to delete: `active_orders`, `all_orders`, `archived_orders` (`:32-38`). All 15 query methods inventoried; active-state filtering must move to `order.is_active` predicate over the flat dict (the entity already carries the status). |
| M4-07 | Execution DTOs frozen/Decimal/real-ABC/fill_id; no discarded side-channel | `ExecutionResult` construction/consumption sites mapped (only `simulated.py` constructs; `on_order:284` discards the return; `exchanges/base.py` Protocol signature references it). `AbstractExecutionHandler` (`execution_handler/base.py`) declares only `on_order` and carries the stale Compliance docstring — confirmed. Two (not three) `ValidationResult` class definitions found — see Open Question 3. Event float fields inventoried for D-22 (see Pattern 5 + Pitfall 4). |

(M4-08, the value-preserving golden-master gate, is the phase's exit criterion — it constrains every requirement above rather than being separately implementable. Oracle mechanics verified: `tests/integration/test_backtest_oracle.py` asserts EXACT equality, no tolerance, against committed `tests/golden/{trades,equity}.csv + summary.json`.)
</phase_requirements>

## Summary

This phase is a pure brownfield refactor — **zero new dependencies, zero new external services**. Every finding below comes from direct reads of the current HEAD. The good news: most target machinery already exists. `CashManager` has the complete reservation/debit/credit API (currently dead on the trade path); the flat O(1) order index already exists (Phase 2); the Phase 4 audited-REJECTED path, `_on_handler_error` re-raise seam, and FillEvent linkage are all live. The phase is predominantly **wiring, reordering, and deleting** — not writing new subsystems.

The risk concentrates in three places. First, **value preservation under the byte-exact oracle**: the locked D-05 routing of settlements through `process_transaction_cash_flow` will silently shift the oracle unless its 2dp quantization (`_validate_and_convert_amount`, `cash_manager.py:488`) is removed for the trade path — today's `apply_transaction_delta` is deliberately precision-preserving and the golden balances carry full instrument precision. Second, **FILL dispatch ordering**: `full_event_handler.py:79-81` routes FILL to `portfolio_handler.on_fill` BEFORE `order_handler.on_fill`, which means the settlement debit executes before any reservation release done in the order domain — the D-10 invariant guard checking `balance` (not `available_balance`) is what makes the design order-independent, and the current `process_transaction_cash_flow` checks `available_balance` and must change. Third, **the D-22 Decimal event retype**: the matching engine and slippage math operate in float (`fill_price * slippage_factor`, OHLC float comparisons), and `Decimal * float` raises `TypeError` in Python — the retype needs explicit, numerically-inert boundary engineering at the bar-price and slippage seams.

**Primary recommendation:** Plan the phase as five bisectable workstreams in dependency order — (1) order-layering + flat storage (pure structure, no money semantics), (2) Protocol + PositionView + consumer retypes, (3) settlement atomicity (reorder, delete TransactionContext, raise-typed contract), (4) reservation lifecycle wiring, (5) DTO cleanup + D-22 event retype last (it has the widest blast radius against the oracle) — running the full suite + both oracle layers at every commit.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Check-and-reserve pre-trade gate | Order domain (`OrderManager` admission path) | Portfolio domain (CashManager executes the reserve via Protocol) | D-02 locked: sync call at admission; queue-mediated would be TOCTOU |
| Reservation release on terminal state | Order domain (`OrderManager.on_fill` reconciliation) — recommended | Portfolio domain (alternative: settlement releases by order_id) | The reserver should own the release (symmetric lifecycle); see Pattern 1 + Open Question 2 |
| Settlement (debit/credit, position mutate, record) | Portfolio domain (`Portfolio` orchestrates; managers each do one concern) | — | D-12 locked: aggregate-owns-unit-of-work |
| Funds invariant guard at settlement | Portfolio domain (CashManager) | — | D-10 locked: actual cost > **balance** → raise typed |
| Order matching / fills | Execution domain (`SimulatedExchange` + `MatchingEngine`) | — | Unchanged this phase; exchange is fill truth |
| Execution output channel | Event queue (`FillEvent` only) | — | D-21 locked: `ExecutionResult` deleted, no sync side-channel |
| Cross-domain portfolio reads | `itrader/core/` Protocol + frozen `PositionView` | `PortfolioHandler` implements structurally | D-13/D-16 locked; core placement kills the order→portfolio concrete import |
| Order reads (`get_*`/`search_*`) | Order domain (`OrderManager`) | `InMemoryOrderStorage` (flat dict) | D-18/D-20 locked: facade→manager→storage one-directional |
| Thread boundary | `queue.Queue` (global_queue) | — | D-19 locked: single-writer engine thread; locks deleted |

## Standard Stack

### Core

No new libraries. The phase uses only what is already in `poetry.lock`:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `decimal` | 3.13 | Money math via the existing `itrader/core/money.py` policy (`to_money`, D-01..D-04) | Already the locked program-wide money policy [VERIFIED: itrader/core/money.py] |
| Python stdlib `typing.Protocol` | 3.13 | `PortfolioReadModel` structural typing (D-16) | Phase 2 precedent: 3 runtime_checkable Protocols already in tree [VERIFIED: STATE.md Plan 02-05] |
| Python stdlib `dataclasses` (frozen/slots) | 3.13 | `PositionView` DTO, surviving execution DTOs | Phase 3/4 precedent: frozen/slots events already in tree [VERIFIED: events/order.py:15] |
| pytest | 8.4.2 | Suite + oracle gates | Existing [VERIFIED: pyproject.toml] |
| mypy (--strict) | existing | `make typecheck` gate enforcing the Protocol boundary | Stood up in Phase 2 [VERIFIED: Makefile:70-72] |

### Removal candidate

| Library | Action | Note |
|---------|--------|------|
| `readerwriterlock` 1.0.9 | Its only importer is `portfolio_handler.py:11` [VERIFIED: grep — single import site]. After D-19 deletes the lock, the dependency is dead. | Removing it from `pyproject.toml` is optional cleanup; if removed, do it in its own commit (lockfile change, bisectable). |

### Alternatives Considered

None — the user explicitly anchored each design to its industry reference during discuss-phase (Nautilus balance-locking, LMAX single-writer, FIX event-stream-as-audit) and rejected third-party event-bus/saga libraries at program level (REQUIREMENTS.md Out of Scope). Do not research or propose alternatives.

**Installation:** nothing to install.

## Package Legitimacy Audit

**No external packages are installed by this phase.** All work is internal refactoring against the existing locked dependency set (`poetry.lock` committed). slopcheck run not applicable; the one dependency *change* is a possible **removal** (`readerwriterlock`), which carries no supply-chain risk.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

Target trade-path data flow after this phase (changes marked ★):

```
SignalEvent (queue)
    │
    ▼
OrderHandler.on_signal  ──────────────── facade: queue puts ONLY ★ (D-18)
    │ delegate
    ▼
OrderManager.process_signal
    ├─ 1. resolve sizing          ── reads protocol.available_cash ★ (D-14/D-17)
    ├─ 2. build Order entity (PENDING)
    ├─ 3. validate entity         ── EnhancedOrderValidator via Protocol ★ (D-13)
    ├─ 4. CHECK-AND-RESERVE ★     ── protocol.reserve(order_id, price×qty + est_fee)  (D-02/D-04)
    │      └─ fail → audited PENDING→REJECTED, persist, nothing emitted
    └─ 5. assemble bracket, store (manager-owned storage ★), return OrderEvents
    │
    ▼  (handler puts OrderEvents on queue)
ORDER event ──▶ ExecutionHandler.on_order ──▶ SimulatedExchange
    │   execute_order(...) -> None ★ (D-21: no ExecutionResult)
    │   MARKET immediate → _emit_fill │ STOP/LIMIT → MatchingEngine.submit
    ▼
FillEvent (queue; EXECUTED / CANCELLED / REFUSED; fill_id+order_id linkage)
    │
    ├─▶ (1st) PortfolioHandler.on_fill              [dispatch order: full_event_handler.py:79-81]
    │       Transaction(+fill_id ★, +order_id ★) → Portfolio.process_transaction:
    │       validate → funds INVARIANT (cost > balance → raise ★ D-10)
    │       → position mutate → cash apply (full-precision debit/credit ★ D-05/D-06,
    │         one ledger entry per fill w/ fee field, via storage seam D-07)
    │       → record Transaction (audit record, D-11)
    │
    └─▶ (2nd) OrderHandler.on_fill → OrderManager.on_fill
            mirror reconcile (FILLED/CANCELLED/REJECTED)
            + RELEASE reservation on terminal state ★ (D-01; keyed by order_id)
```

Reservations live in the portfolio storage seam; they change `available_balance` only, never `balance` (D-08) — the oracle (equity curve/cash from `balance`) cannot see them.

### Recommended Project Structure (new/moved files only)

```
itrader/
├── core/
│   └── portfolio_read_model.py   # PortfolioReadModel Protocol + frozen PositionView ★
│                                  # (core/ placement kills order→portfolio concrete import, D-16;
│                                  #  spaces indentation — new module)
├── portfolio_handler/
│   ├── portfolio.py               # settlement orchestration reorder (D-12); cash setter deleted
│   ├── cash/cash_manager.py       # full-precision trade flows; fee field; per-ref reservations
│   ├── transaction/
│   │   ├── transaction.py         # Transaction += fill_id (+ order_id) fields
│   │   └── transaction_manager.py # shrinks: validation + recording + history (D-11/D-12)
│   ├── storage/…                  # seam: per-reference reservation API extension ★ (see Pattern 1)
│   └── portfolio_handler.py       # rwlock deleted; implements Protocol structurally
├── order_handler/
│   ├── order_handler.py           # deprecated methods deleted; reads delegate to manager
│   ├── order_manager.py           # owns storage; back-ref removed; reserve at admission
│   └── storage/in_memory_storage.py  # flat dict only (D-20)
└── execution_handler/
    ├── base.py                    # real ABC: on_order + on_market_data; Compliance docstring dropped
    ├── result_objects.py          # ExecutionResult deleted; survivors frozen/Decimal
    └── exchanges/{base,simulated}.py  # execute_order -> None
```

### Pattern 1: Reservation lifecycle (reserve-at-admission, release-at-terminal)

**What:** `OrderManager` reserves synchronously at admission via the Protocol; the release happens at terminal-state reconciliation. The seam needs per-reference tracking.

**Critical storage fact:** the Phase 3 seam holds reserved cash as a SINGLE AGGREGATE — `get_reserved_cash()/set_reserved_cash(amount)` (`portfolio_handler/base.py:251-262`) [VERIFIED: codebase]. "Release the FULL reservation keyed by order_id" (D-04 + discretion note) requires per-reference amounts. The seam (ABC + in-memory backend) must grow e.g. `add_reservation(reference_id, amount)` / `pop_reservation(reference_id) -> Decimal | None`, with `get_reserved_cash()` becoming the sum (or a maintained aggregate). This is a seam-API extension, not a behavior change — backtest backend only; Postgres backend is D-sql.

**Release ownership — recommended design:** `OrderManager.on_fill` releases on EVERY terminal status (EXECUTED, CANCELLED, REFUSED) via `protocol.release(order_id)` made idempotent (no-op when no reservation exists — covers SELLs and never-reserved orders uniformly). Rationale:
- Symmetric: the component that reserved owns the release.
- Uniform: `PortfolioHandler.on_fill` ignores non-EXECUTED fills (`portfolio_handler.py:255-262`) [VERIFIED], so putting release in settlement would leave CANCELLED/REFUSED reservations stuck or force a second release path.
- Order-independent: FILL dispatches portfolio-first (`full_event_handler.py:79-81`) [VERIFIED], so the settlement debit runs BEFORE the order-domain release. This works **iff** the settlement invariant guard checks `balance` (exactly what D-10 locks: "actual cost > balance → raise") — never `available_balance` (the order's own un-released reservation would false-positive). See Pitfall 2.

**When to use:** all NEW cash-debiting orders (BUY). SELLs and bracket children reserve nothing (D-03); idempotent release makes the on_fill path uniform.

**Commission estimate for the reservation (discretion):** the golden run uses fee 0 / slippage 0 (`scripts/run_backtest.py` D-04 pin) [VERIFIED], so any correct estimator is value-preserving for the oracle. Cleanest mode-agnostic option: call the exchange's existing `fee_model.calculate_fee(quantity, price, side, order_type)` (it already accepts `Union[float, Decimal]` and returns `Decimal` [VERIFIED: fee_model/base.py:16-23]) — but the fee model lives on the exchange, not the order domain. Recommend injecting a fee-estimator callable (or rate) into `OrderManager` at TradingSystem wiring time rather than importing across the execution boundary; `ZeroFeeModel` for backtest reproduces today's `_check_funds_availability` math exactly when commission=0.

### Pattern 2: Validate-first settlement (D-09/D-12) — the exact reorder

Current defective sequence (`portfolio.py:289-308`) [VERIFIED]:
```
process_transaction:
  position_manager.process_position_update(transaction)   # MUTATES FIRST — defect
  transaction_manager.process_transaction(transaction)     # validates+cash AFTER
```
Target sequence (D-12), all checks before any mutation:
```python
# Portfolio.process_transaction(transaction) -> None     (D-10: returns None, raises typed)
self.transaction_manager.validate(transaction)            # pure checks, raises InvalidTransactionError
self.cash_manager.assert_funds_invariant(transaction)     # BUY: cost > balance -> raise (D-10; engine-bug guard)
position = self.position_manager.process_position_update(transaction)
transaction.position_id = position.id
self.cash_manager.apply_fill_cash_flow(...)               # full-precision signed delta + fee field (D-05/D-06)
self.transaction_manager.record(transaction)              # append to seam history (D-11)
```
**Deletions bundled here** [all VERIFIED in tree]: `TransactionContext` dataclass + `_handle_transaction_error` + pending-dict calls (`transaction_manager.py:24-33, 90-142, 292-337`), `TransactionState` enum (`core/enums/portfolio.py:126-138`) and its seam methods (`set_pending_transaction`/`get_pending_transactions`/`remove_pending_transaction` in `portfolio_handler/base.py` + in-memory backend), `cancel_pending_transaction`, the unreachable `return False`, `apply_transaction_delta` (`cash_manager.py:284-333`), the cash setter (`portfolio.py:216-225`). Note `transact_shares` (`portfolio.py:382-402`) returns bool and is the actual `on_fill` entry — its contract must also become raise/None, and `PortfolioHandler.on_fill`'s `return result` (`portfolio_handler.py:286-295`) follows.

### Pattern 3: PortfolioReadModel Protocol (D-13..D-17)

```python
# itrader/core/portfolio_read_model.py  (new module — spaces, mypy --strict clean)
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable
from itrader.core.enums import PositionSide
from itrader.core.ids import PortfolioId, OrderId

@dataclass(frozen=True, slots=True)
class PositionView:
    ticker: str
    side: PositionSide
    net_quantity: Decimal
    avg_price: Decimal

@runtime_checkable
class PortfolioReadModel(Protocol):
    def available_cash(self, portfolio_id: PortfolioId) -> Decimal: ...
    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> PositionView | None: ...
    def reserve(self, portfolio_id: PortfolioId, order_id: OrderId, amount: Decimal) -> None: ...
    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None: ...
```
(Signature shapes are discretion; the four capabilities are locked by D-13. `reserve` raising `InsufficientFundsError` — already the CashManager behavior [VERIFIED: cash_manager.py:356-360] — fits D-10's raise-typed contract.)

`PortfolioHandler` implements these as plain methods delegating to the portfolio's `cash_manager`/`position_manager` (structural typing — no inheritance, D-16). Order-domain constructors (`OrderHandler.__init__`, `OrderManager.__init__`, `EnhancedOrderValidator.__init__`, `VariableSizer.__init__`, `AdvancedRiskManager.__init__`) retype the parameter annotation to `PortfolioReadModel`; the `from ..portfolio_handler.portfolio_handler import PortfolioHandler` imports die (`order_handler.py:4`, `variable_sizer.py:2`, `advanced_risk_manager.py:2`) [VERIFIED].

**Consumer-site inventory (what each reads today)** [VERIFIED by grep]:
| Consumer | Reads today | Maps to |
|----------|-------------|---------|
| `order_manager.py:441-461` (sizing) | `get_portfolio(...).cash`, `.get_open_position(ticker).net_quantity` | `available_cash`, `get_position().net_quantity` |
| `order_manager.py:237` | `get_portfolio(...).exchange` | NOT in locked Protocol — see Open Question 1 |
| `order_validator.py:258,279` | `.exchange` | same |
| `order_validator.py:367-385` | `.n_open_positions`, `.positions` dict | same |
| `order_validator.py:397-416` | `.total_equity` (WARNING-level exposure check only) | excluded by D-14 — see Open Question 1 |
| `order_validator.py:454-489` | `.cash`, `.positions` membership | `available_cash`, `get_position` |
| `variable_sizer.py:40-49` | `.positions.keys()`, `.get_open_position().net_quantity`, `.cash` | `get_position`, `available_cash` (+ see OQ1 for keys()) |
| `advanced_risk_manager.py:51+` | portfolio object | retype now (D-17) |

### Pattern 4: Single-writer lock deletion (D-19) — exact inventory

Delete [all VERIFIED by grep]:
- `CashManager._lock`, `TransactionManager._lock`, `PositionManager._lock`, `MetricsManager._lock` (4 per-manager RLocks)
- `Portfolio._lock` (`portfolio.py:65`) and every `with self._lock:` block
- `PortfolioHandler._portfolios_lock` (`rwlock.RWLockFair`, `:70`) + the `readerwriterlock` import; `_operations_lock` (`:74`) — note `_operation_context` also provides correlation-id + error-event publishing, which should survive the lock removal
- `SimulatedExchange._lock` (`simulated.py:81`) — config-update lock, same theater

KEEP: `LiveTradingSystem._status_lock` / `_stats_lock` (system lifecycle, not portfolio state — CONTEXT explicit). Document the single-writer contract where the locks died (module docstrings): *all portfolio state mutations happen on the engine thread; `queue.Queue` is the thread boundary*.

### Pattern 5: D-22 event-money Decimal retype — boundary inventory

Fields to retype `float → Decimal` [VERIFIED]: `SignalEvent.price/stop_loss/take_profit/quantity` (`events/signal.py:58-65`), `OrderEvent.price/quantity/stop_price` (`events/order.py:31-40`), `FillEvent.price/quantity/commission` (`events/fill.py:57-59`).

Coercion sites to remove/adjust [VERIFIED]:
- `OrderEvent.new_order_event` — `float(order.price)`, `float(order.quantity)` (`events/order.py:74-75`) → pass Decimal through.
- `FillEvent.new_fill` callers — `simulated.py:236` passes `commission=float(commission)`; `:211,253,273` pass `commission=0.0` → `Decimal("0")`.
- `portfolio_handler.on_fill` — `to_money(fill_event.price/quantity/commission)` (`:273-281`) become identity-ish; keep `to_money` as the domain-entry normalization (harmless on Decimal input).
- `order_manager.on_fill` — `to_money(fill_event.price)` (`:85`) same.
- Strategy boundary: `SMA_MACD` emits float prices into `SignalEvent` → `_generate_signal`/factories must enter via `to_money` (Decimal(str(x)) — numerically inert by D-04 policy).

Float-math danger zones that must keep working (see Pitfall 4): `matching_engine._evaluate` (Decimal order.price vs float OHLC — comparison OK, but `min(open_, order.price)` mixes types in the returned fill price), `simulated._emit_fill:228` (`fill_price * slippage_factor` — `Decimal * float` raises TypeError), fee/slippage model signatures (already `Union[float, Decimal]` in, `Decimal` out for fees [VERIFIED]; slippage factor returns float). `matching_engine.modify(new_price: float)` annotation follows the retype.

### Anti-Patterns to Avoid
- **Finishing the saga instead of deleting it** (D-09 locked: `ROLLED_BACK`, retry_count, pending-dict all die — a fill is a fact).
- **Queue-mediated reserve** (D-02 locked: TOCTOU — the sync Protocol call is the gate).
- **Checking `available_balance` in the settlement debit** — false `InsufficientFundsError` from the order's own un-released reservation under portfolio-first FILL dispatch (Pitfall 2).
- **Quantizing trade-path cash flows to 2dp** — byte-exact oracle break (Pitfall 1).
- **Adding new cross-handler direct calls** while wiring the reserve — the Protocol call is the ONLY sanctioned sync crossing; everything else stays queue-only.
- **Wall-clock timestamps in new ledger/audit records** — M2-09 made audit time event-derived; new `CashOperation`s must follow (Pitfall 5).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Transaction rollback | Application-level saga/undo machinery | Validate-first ordering (D-09); durable rollback later = DB transactions at the Postgres seam (D-sql) | Locked decision; hand-rolled rollback of in-memory aggregates is exactly the never-worked machinery being deleted |
| Concurrency safety | New locks / lock-free structures | Single-writer architecture + `queue.Queue` thread boundary (D-19) | `queue.Queue` is already thread-safe (stdlib); the engine is single-threaded in backtest |
| Money precision | Custom rounding helpers | Existing `itrader/core/money.py` (`to_money`, instrument scales, HALF_UP boundary policy) | Already the program-wide policy; BTCUSD 8dp scales defined [VERIFIED] |
| Read-only views | Custom proxy/wrapper classes | `@dataclass(frozen=True, slots=True)` `PositionView` | Phase 3/4 precedent; mypy enforces |
| Narrow boundary enforcement | Runtime access guards | `typing.Protocol` + `mypy --strict` (already gated via `make typecheck`) | Structural typing makes the concrete dependency a type error |
| Audit IDs / timestamps | `f"cash_op_{counter}_{datetime.now()...}"` (current scheme, `cash_manager.py:504`) | `idgen` UUIDv7 + event-derived time (Phase 2/M2-09 precedent) | Determinism is a program constraint |

**Key insight:** every "new" capability this phase needs (reservation API, audited rejection, storage seams, error seam, typed exceptions, frozen DTOs) already exists in the tree from Phases 2–4. The phase is wiring and deletion; building anything novel is a smell.

## Runtime State Inventory

(Refactor phase — categories answered explicitly.)

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `tests/golden/{trades.csv,equity.csv,summary.json}` — the frozen oracle. M4 is NOT a re-baseline point: these files must remain **byte-identical** | None — verified unchanged at every commit (the gate). `output/` is regenerated per run (gitignored) |
| Live service config | None — no external services on the backtest path (PostgreSQL/OANDA/Binance all deferred D-live/D-sql) | None — verified by deferred register in STATE.md |
| OS-registered state | None — no scheduled tasks/daemons | None |
| Secrets/env vars | `.env` loaded by Makefile; pydantic-settings `database_url` (SecretStr, required-no-default) — not touched by this phase | None — verified: no config-key renames in scope |
| Build artifacts | Stale `__pycache__/*.pyc` (incl. orphan cpython-310 files under `strategy_handler/`); `.venv` | None functionally — Python recompiles; optional hygiene only |

## Common Pitfalls

### Pitfall 1: `process_transaction_cash_flow` quantizes to 2dp — silent oracle break
**What goes wrong:** D-05 routes settlements through `process_transaction_cash_flow`, but it runs amounts through `_validate_and_convert_amount`, which quantizes to `Decimal('0.01')` HALF_UP (`cash_manager.py:239-240, 488`) [VERIFIED]. Today's trade path uses `apply_transaction_delta` precisely BECAUSE it preserves full precision (the CR-03 comment at `:284-305` documents this). BTCUSD costs carry 8dp precision; quantizing every fill's cash delta shifts `balance` → equity curve → byte-exact oracle FAIL.
**Why it happens:** the method was written for external deposits/withdrawals where 2dp is correct policy.
**How to avoid:** the settlement path must apply the exact full-precision signed delta (the semantics of `apply_transaction_delta`) under the new debit/credit API. Recommend a dedicated fill-flow method (e.g. `apply_fill_cash_flow(amount, fee, is_debit, reference_id)`) that skips the 2dp quantize and the min/max-balance policy gates, satisfying D-05 ("proper debit/credit semantics") and D-06 (fee on the entry) without inheriting deposit policy. Also note `_validate_and_convert_amount` rejects `amount <= 0` — a theoretical zero-cost edge.
**Warning signs:** oracle diff in `final_cash`/`cash_balance` columns at the 3rd+ decimal.

### Pitfall 2: FILL dispatch order vs reservation release — false InsufficientFunds
**What goes wrong:** FILL routes to `portfolio_handler.on_fill` FIRST, `order_handler.on_fill` SECOND (`full_event_handler.py:79-81`) [VERIFIED]. If the release lives in the order domain, the settlement debit executes while the order's own reservation is still held. The current debit checks `available_balance` (`cash_manager.py:247-252`): balance 10000, reservation 9500 → available 500 < debit 9500 → spurious `InsufficientFundsError` → backtest aborts via the re-raise seam.
**Why it happens:** the existing check predates reservations being live on the trade path.
**How to avoid:** D-10 already locks the fix — the settlement invariant guard compares actual cost against **`balance`**, never `available_balance`. Implement exactly that. (Alternative — release inside settlement before debit — requires `Transaction.order_id` and splits release ownership across EXECUTED vs CANCELLED/REFUSED paths; see Open Question 2.)
**Warning signs:** first golden BUY fill raises InsufficientFundsError; suite integration tests abort at the first trade.

### Pitfall 3: Reservation gate must be provably inert in the golden run
**What goes wrong:** any reservation rejection in the golden run changes the trade log = behavioral oracle break.
**Why it's safe (trace, verify before relying — D-14 mandate):** golden run is long-only, single position, fees 0 (`scripts/run_backtest.py` pins CASH=10000, fees 0, slippage 0 [VERIFIED]); sizing is `0.95 × cash / price` (`order_manager.py:460`) so reservation = `price × qty = 0.95 × cash ≤ available`; SMA_MACD emits no stop_loss/take_profit (grep found none [VERIFIED]) so no bracket legs exist in the golden run; reservations are fully released at each fill before the next admission → `available == balance` at every BUY decision point, and `reserve` never rejects. Two residual cautions: (a) `reserve_cash` quantizes the reserved amount to 2dp — harmless for the gate (rounding HALF_UP of 0.95×cash stays ≤ available given prices ≫ 1¢) but worth an explicit assertion in a unit test; (b) the executor should add a trace/assert (e.g. temporary instrumentation or a dedicated integration assertion) demonstrating reserved==0 at each admission in the oracle run, per D-14's explicit instruction.
**Warning signs:** trade count ≠ 134 / first divergent entry_date in trades.csv.

### Pitfall 4: D-22 Decimal retype — `Decimal * float` raises TypeError at the execution layer
**What goes wrong:** retyping event money to Decimal makes mixed arithmetic explode: `simulated._emit_fill:228` computes `fill_price * slippage_factor` (slippage factor is float); `matching_engine._evaluate` computes `min(open_, order.price)` / `max(open_, order.price)` mixing float OHLC with Decimal order price (comparisons are legal in Python 3, arithmetic and `min`-result types are the hazard — the fill price's TYPE then propagates into `FillEvent.price`).
**Why it happens:** bar OHLC stays float (pandas) until M5a's `Bar` struct; the execution layer was deliberately left float in Phase 4 (D-04 deferral).
**How to avoid:** decide the boundary explicitly and make it numerically inert: enter Decimal at bar-price read sites used for fills (`Decimal(str(open_))` — the D-04 string path round-trips exactly), or keep the matching/slippage math in float and convert once at `FillEvent` construction via `to_money` (also `Decimal(str(x))` — identical result). Either is byte-exact-or-stop compliant because today's path already does Decimal(str(float)) at `Transaction.new_transaction`; the engineered invariant is: *the Decimal that reaches the cash ledger must equal `to_money(old_float_value)` for every fill*. Run the oracle after EVERY sub-step of this workstream — it has the widest blast radius.
**Warning signs:** TypeError in `_emit_fill`/`_evaluate`; or oracle numeric diff at full precision (a float artifact leaked through a non-str Decimal entry).

### Pitfall 5: New ledger entries must be deterministic — current `CashOperation` is not
**What goes wrong:** `CashOperation` uses `datetime.now()` for `timestamp` and a wall-clock-derived `operation_id` (`cash_manager.py:498-518`) [VERIFIED]. Making the ledger LIVE on the trade path (M4-01 "ledger…live") with wall-clock entries violates the program determinism constraint (M2-09 made transaction/audit time event-derived) — and the new `fee` field (D-06) means the dataclass changes anyway.
**Why it happens:** the ledger was dead code on the trade path; nobody noticed.
**How to avoid:** when reshaping `CashOperation` (add `fee`, set `amount` = net signed delta per D-06): timestamp = transaction/fill event time; `operation_id` = `idgen` UUIDv7. The ledger isn't oracle-serialized, so this is determinism hygiene, not an oracle risk.
**Warning signs:** ledger snapshots differ across identical runs.

### Pitfall 6: Flat-dict storage rewrite must preserve "active" semantics and history queries
**What goes wrong:** the nested dicts encode three CLASSES of orders (active / all / archived) plus per-portfolio grouping. Deleting them naively loses `deactivate_order` semantics (filled orders leave active queries but stay queryable) and `archive_orders` (removes from flat index today — `in_memory_storage.py:355-358`).
**How to avoid:** the flat dict holds ALL orders; "active" becomes a predicate filter (`order.is_active` — the entity carries status); `deactivate_order` becomes a no-op or dies (status change already moves the order out of active queries — check its callers: `order_manager.on_fill:100`); archive either keeps a `_archived: set[OrderId]` or `archive_orders` is deleted as dead (verify callers first — likely test-only).
**Warning signs:** `get_active_orders` returns filled orders; `test_order_storage.py` failures beyond the mechanically-expected ones.

### Pitfall 7: Test fallout is wide but mechanical — inventory it up front
**What goes wrong:** suites assert on removed machinery. Found [VERIFIED by grep]: `tests/unit/portfolio/test_transaction_manager.py` (TransactionContext/pending/cash-setter at `:41,175`), `tests/unit/portfolio/test_state_storage.py` (pending-transaction seam methods), `tests/unit/execution/exchanges/test_simulated_exchange.py` (ExecutionResult assertions), `tests/unit/order/test_order_storage.py` (nested-dict shapes), `tests/unit/order/test_order_handler.py` (deprecated facade methods), `tests/unit/order/test_order_validator.py` (mocks set `.cash` — Mock attributes, unaffected by setter deletion but affected by Protocol retype). 429 tests currently collected [VERIFIED]; `filterwarnings=["error"]` + `--strict-markers` mean even deprecation noise fails the suite.
**How to avoid:** budget an explicit test-migration task per workstream; delete tests of deleted machinery in the SAME commit as the deletion (bisectability).

### Pitfall 8: `_operation_context` is not just a lock
**What goes wrong:** deleting PortfolioHandler's "operation tracking" wholesale (it looks like concurrency theater) also deletes correlation-id generation and `_publish_error_event` wiring used by `on_fill`'s except path.
**How to avoid:** remove only `_operations_lock`/`_active_operations` concurrency limiting; keep correlation-id + error-event publication (or simplify deliberately and update the error-path tests).

## Code Examples

### Settlement invariant guard (D-10 shape)
```python
# CashManager — engine-bug guard, checks BALANCE not available (Pitfall 2)
def assert_funds_invariant(self, required: Decimal) -> None:
    if required > self._balance:
        raise InsufficientFundsError(
            required_cash=float(required),
            available_cash=float(self._balance),
        )  # propagates -> _on_handler_error re-raise -> run stops loudly (Phase 4 D-16)
```

### One ledger entry per fill with fee field (D-06 shape)
```python
@dataclass(frozen=True, slots=True)
class CashOperation:
    operation_id: uuid.UUID          # idgen UUIDv7 (deterministic, Pitfall 5)
    operation_type: CashOperationType
    amount: Decimal                  # SIGNED net cash delta (principal ± commission)
    fee: Decimal                     # commission portion included in amount
    timestamp: datetime              # event-derived (transaction.time)
    description: str
    reference_id: str | None = None  # transaction id / order id
    balance_before: Decimal | None = None
    balance_after: Decimal | None = None
# balance reconstruction: balance = initial + Σ amount; total fees = Σ fee
```

### Admission check-and-reserve (D-02 placement)
```python
# OrderManager.process_signal — after validation passes, before _assemble_bracket_and_emit
if primary.action_is_buy:  # D-03: only cash-debiting orders reserve
    cost = primary.price * primary.quantity + self._estimate_commission(primary)
    try:
        self.portfolio_read_model.reserve(primary.portfolio_id, primary.id, cost)
    except InsufficientFundsError as e:
        primary.add_state_change(OrderStatus.REJECTED, str(e), triggered_by="cash_reservation")
        self.order_storage.add_order(primary)   # audited rejection persisted (Phase 4 path)
        return [OperationResult.failure_result(...)]
```

### Manager returns events, handler owns queue puts (D-18 shape)
The pattern already exists — `process_signal` returns `OperationResult`s carrying `order_events` and `OrderHandler.on_signal` puts them (`order_handler.py:90-97`) [VERIFIED]. D-18 extends this to ALL paths and deletes the unused `order_handler_ref` constructor arg (`order_manager.py:41,63` — stored, never called [VERIFIED by grep: no `self.order_handler.` usage in method bodies]).

## State of the Art

| Old Approach (current tree) | Current Approach (this phase) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Trade cash via `apply_transaction_delta` interim seam; reservations dead | Full reservation lifecycle + full-precision fill cash flow through CashManager | M4 (this phase) | #22 Critical closed; ledger/audit live |
| Position mutate → then validate+cash | Validate-first sequential settlement (LMAX/Nautilus shape) | M4 | Atomicity without rollback machinery |
| `ExecutionResult` sync return (discarded at `simulated.py:284`) | Events-only execution output (FIX/Nautilus shape) | M4 | One channel of execution truth |
| Lock theater (7+ locks, single-threaded backtest) | Documented single-writer contract | M4 | #29 resolved honestly |
| Events carry float money with boundary coercions | Decimal end-to-end on events | M4 (Phase 4 D-04 deferral closes) | #17 fully closed on the event path |

**Deprecated/outdated in-tree (delete, don't migrate):** `TransactionContext`/`TransactionState` saga, `Portfolio.cash` setter, `add_pending_order`/`remove_orders`/`remove_order` facade methods, nested order dicts, `AbstractPortfolio`/`AbstractPortfolioHandler` legacy ABCs in `portfolio_handler/base.py` are NOT in scope (don't pull forward; they're not on the M4 finding list).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Release-in-OrderManager (uniform terminal-state release) is the intended reading of D-01/D-02's "released on terminal state…flows via FillEvent" | Pattern 1, OQ2 | Low — the alternative (release inside settlement) is also compatible with the locked decisions; planner picks one and documents it |
| A2 | `archive_orders` and `deactivate_order` have no production callers beyond `order_manager.on_fill:100` (deactivate) and tests (archive) | Pitfall 6 | Low — executor must grep before deleting; behavior-preserving filter semantics keep the suite green either way |
| A3 | The "×3 ValidationResult collision" in CONTEXT counts import-site ambiguity; only 2 class definitions exist in `itrader/` (`order_validator.py:28`, `result_objects.py:169`) | OQ3 | None — resolving 2 satisfies the requirement; if a third exists in tests it surfaces mechanically |
| A4 | Industry-pattern anchors (Nautilus RiskEngine balance-locking, LMAX single-writer, FIX ExecutionReport audit) are user-locked design references, not claims requiring re-verification | State of the Art | None — locked in CONTEXT `<specifics>` |

## Open Questions

1. **Protocol surface vs. what the order domain actually reads (`exchange`, `n_open_positions`, `positions` dict/keys, `total_equity`)**
   - What we know: D-13 locks exactly four capabilities (`available_cash`, `get_position`, `reserve`, `release`); D-14 explicitly excludes equity from the order-domain surface. But the validator's exposure check reads `total_equity` (WARNING-level only — never rejects [VERIFIED: order_validator.py:410-416]), position-limit check reads `n_open_positions`+`positions`, and `_get_signal_exchange`/validator read `.exchange`; `variable_sizer` lists `positions.keys()`.
   - What's unclear: whether these reads (a) move onto a slightly-grown Protocol (e.g. `exchange_for(portfolio_id)`, `open_position_count`), (b) get reworked to compose from `get_position` per-ticker, or (c) get deleted as checks (exposure check is WARNING-only; equity exposure semantics arguably belong to M5b sizing anyway).
   - Recommendation: keep the Protocol at the four locked members + a minimal `exchange_for()` (exchange routing is admission-path metadata, not portfolio internals); rework the position-limit check to a count exposed via a narrow method or drop to the portfolio's own settlement-side validation; DELETE the equity exposure WARNING (it warns on every golden BUY at 95% sizing — pure log noise) and note it in the plan as a behavior-preserving-for-verdicts change. Whatever the choice, document the D-13 interpretation in the plan as CONTEXT instructs.

2. **Where the EXECUTED-fill reservation release lives**
   - What we know: dispatch is portfolio-first (`full_event_handler.py:79-81`); D-10 locks the settlement guard against `balance`; `PortfolioHandler.on_fill` ignores CANCELLED/REFUSED; `Transaction` carries no order_id today.
   - What's unclear: OrderManager-releases-all-terminal (uniform, recommended) vs settlement-releases-EXECUTED + OrderManager-releases-CANCELLED/REFUSED (matches D-04's "release, debit" wording literally but splits ownership and requires `Transaction.order_id`).
   - Recommendation: OrderManager releases on all terminal reconciliations via idempotent `release(order_id)`; settlement guard checks `balance` per D-10 (which makes ordering irrelevant). Add `fill_id` to `Transaction` per D-11 regardless; add `order_id` too only if the planner picks the settlement-release variant.

3. **`ValidationResult` namespacing (discretion)**
   - What we know: two definitions — order-domain pipeline result (`order_validator.py:28`) and execution-domain pre-trade check (`result_objects.py:169`); `simulated.py`/`exchanges/base.py` import the latter.
   - Recommendation: rename the execution one to `OrderPreflightResult` (or `ExchangeValidationResult`) when reconciling `result_objects.py` per-DTO; keep the order-domain name (more call sites).

4. **`reserve_cash` 2dp quantization of the reservation amount**
   - What we know: gate-only (never touches `balance`), so it cannot move the oracle; but D-04 says the math "mirrors today's `_check_funds_availability`," which compares at full precision.
   - Recommendation: store reservations at full precision (skip `_validate_and_convert_amount` quantize for reservations too) — simpler invariants (released amount == reserved amount exactly) and a faithful D-04 mirror. Low stakes either way.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Poetry + in-project `.venv` | all commands | ✓ (suite collected 429 tests via `poetry run pytest`) | — | — |
| pytest | suite + oracle gates | ✓ | 8.4.2 | — |
| mypy (`make typecheck`) | strict gate | ✓ (target verified in Makefile:70; gate live since Phase 2) | — | — |
| Golden dataset + frozen oracle | M4-08 gate | ✓ (`data/BTCUSD_1d_ohlcv_2018_2026.csv`, `tests/golden/`) | frozen at M2b | — |
| PostgreSQL / network services | NOT required | n/a — backtest path is offline by design | — | — |

**Missing dependencies with no fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Config file | `pyproject.toml` (single marker home; folder-derived TYPE markers in conftests) |
| Quick run command | `poetry run pytest tests/unit -q -x` |
| Full suite command | `make test` (429 collected) + `make typecheck` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| M4-01 | Reservation lifecycle (reserve→release→debit), ledger entry per fill w/ fee, no setter bypass | unit | `poetry run pytest tests/unit/portfolio/test_cash_manager.py -q` | ✅ exists — extend for per-ref reservations/fee field (Wave 0) |
| M4-02 | Validate-first ordering; raise-typed/return-None; no mutation on failed validation | unit | `poetry run pytest tests/unit/portfolio/test_transaction_manager.py tests/unit/portfolio/test_portfolio.py -q` | ✅ exists — heavy rewrite (TransactionContext tests die) |
| M4-03 | Facade delegates reads; no back-ref; manager owns storage | unit | `poetry run pytest tests/unit/order/test_order_handler.py tests/unit/order/test_order_manager.py -q` | ✅ exists — update for deleted methods |
| M4-04 | Protocol conformance (`isinstance` runtime_checkable); consumers typed to Protocol; frozen PositionView | unit + typecheck | `poetry run pytest tests/unit/core -q` + `make typecheck` | ❌ Wave 0: `tests/unit/core/test_portfolio_read_model.py` |
| M4-05 | Lock deletion; single-writer contract documented | unit (absence) + suite green | `make test` | ✅ no lock-behavior tests exist [VERIFIED] — mechanical |
| M4-06 | Flat-dict storage: O(1) lookup, active/history query parity | unit | `poetry run pytest tests/unit/order/test_order_storage.py -q` | ✅ exists — rewrite nested-shape assertions |
| M4-07 | `execute_order -> None`; FillEvent-only output; real ABC; Decimal events | unit | `poetry run pytest tests/unit/execution tests/unit/events -q` | ✅ exists — `test_simulated_exchange.py` ExecutionResult assertions rewritten |
| M4-08 | Byte-exact behavioral + numerical oracle | integration (slow) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists — assertions MUST NOT be modified |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit -q -x` + targeted file
- **Per wave merge:** `make test && make typecheck` + `poetry run pytest tests/integration/test_backtest_oracle.py -q` (the byte-exact gate — CONTEXT requires both oracle layers green at EVERY commit; treat the oracle run as per-commit for any money-path or event-retype commit)
- **Phase gate:** full suite + typecheck + oracle green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/core/test_portfolio_read_model.py` — Protocol conformance + frozen PositionView (M4-04)
- [ ] Reservation-lifecycle coverage in `tests/unit/portfolio/test_cash_manager.py` — per-reference reserve/release, idempotent release, fee field, full-precision fill flow (M4-01; Pitfalls 1, 5)
- [ ] Admission check-and-reserve coverage in `tests/unit/order/test_order_manager.py` — reserve-fail → audited REJECTED, BUY-only reservation, bracket children reserve nothing (M4-01/D-03)
- [ ] Settlement-ordering test: failed validation leaves position AND cash untouched (M4-02 — the defect being fixed deserves a regression lock)
- [ ] Golden-run inertness assertion: reserved == 0 at every BUY admission (D-14's mandated trace — can live as an integration assertion or temporary instrumentation)
- Framework install: none needed

## Security Domain

Internal refactor with no network surface, auth, or crypto. ASVS categories V2/V3/V4/V6: not applicable (no auth/session/access-control/crypto code touched). V5 Input Validation: applies — transaction/order validation is being restructured; the standard control is the existing typed domain-exception hierarchy + Pydantic config models (no new validation framework needed).

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent state corruption on partial settlement | Tampering (integrity) | Validate-first ordering + fail-fast re-raise seam (D-09/D-10) — this phase IS the mitigation |
| Float-money rounding drift | Tampering (integrity) | Decimal end-to-end via `to_money` string entry; byte-exact oracle gate |
| Unaudited cash mutation | Repudiation | Ledger entry per fill via storage seam (D-06/D-07); cash setter deleted |

## Sources

### Primary (HIGH confidence — direct codebase reads at HEAD, 2026-06-06)
- `itrader/portfolio_handler/cash/cash_manager.py` — full API, quantization behavior, reservation aggregate, audit-record determinism gap
- `itrader/portfolio_handler/transaction/{transaction_manager.py,transaction.py}` — saga machinery, unreachable contract, funds-check math, entity fields
- `itrader/portfolio_handler/{portfolio.py,portfolio_handler.py,base.py}` — settlement ordering defect, cash setter, lock inventory, seam reservation API, on_fill flow
- `itrader/order_handler/{order_handler.py,order_manager.py,order_validator.py,storage/in_memory_storage.py}` — facade/manager/storage layering, read sites, flat index, sizing math
- `itrader/execution_handler/{result_objects.py,base.py,exchanges/base.py,exchanges/simulated.py,matching_engine.py,fee_model/*}` — DTO inventory, discarded returns, float-math seams
- `itrader/events_handler/{full_event_handler.py,events/*}` — FILL dispatch order, event money fields, coercion sites, error seam
- `scripts/run_backtest.py`, `tests/integration/test_backtest_oracle.py`, `tests/golden/` — oracle pins (fees 0/slippage 0/cash 10k), exact-assertion mechanics
- `pyproject.toml`, `Makefile`, `poetry run pytest --collect-only` (429 tests) — gates and commands
- `.planning/phases/05-…/05-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md` — locked decisions and carry-forwards

### Secondary (MEDIUM confidence)
- Phase 2–4 CONTEXT/STATE decision log entries cited for precedent claims (flat index origin, mypy gate, event-derived audit time)

### Tertiary (LOW confidence)
- None — no external/web claims were needed for this phase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; everything verified in `pyproject.toml`/lockfile
- Architecture: HIGH — every integration point read directly; locked decisions constrain design space tightly
- Pitfalls: HIGH — each pitfall is anchored to specific verified lines; the two oracle-risk pitfalls (quantization, dispatch order) are mechanically demonstrable
- Open questions: MEDIUM — they are genuine design choices within Claude's discretion, not knowledge gaps

**Research date:** 2026-06-06
**Valid until:** any commit that touches the listed files (codebase-derived research; re-verify line anchors if Phase 5 starts after unrelated changes). Nominal: 30 days.
