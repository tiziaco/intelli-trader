# Phase 5: M4 — Money & Transaction Correctness - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

The **money & transaction correctness** phase. Route every trade's cash through `CashManager`
with a live reservation lifecycle (Critical #22), make transaction processing atomic with a
fail-fast error contract (#16/#23), enforce one-directional order-handler layering with O(1)
storage (#9/PERF3), put cross-handler reads behind a narrow portfolio access Protocol (#6),
resolve intra-portfolio coupling and the thread-safety theater (#29), and clean up the execution
result DTOs (#39) — across eight locked requirements (M4-01…M4-08), all **value-preserving**
against the oracle.

**Golden-master position:** Both oracle layers (behavioral + numerical) are byte-exact suite
assertions since Phase 3 (D-16/D-18). M4 is **NOT a sanctioned numerical re-baseline point**
(only post-M2 and post-M5 are). The working discipline is byte-exact-or-stop: any diff = STOP /
investigate / COVERAGE-INDEX §E with owner decision. M4-08's "any numeric difference is
explained" is an owner-gated escape hatch for irreducible cases only — never a silent absorb.

**Boundary with adjacent milestones (do NOT pull forward):**
- **M5a (Phase 6)** owns: `Bar` struct (#3/FR1), fill realism/look-ahead (#21), fee/slippage
  correctness (#28), price-handler split (#30).
- **M5b (Phase 7)** owns: sizing-policy completion (M5-06), `calculate_signal` contract (#24/#31),
  reporting/metrics (#38), universe stub (#33). The Protocol grows equity-read methods then if
  sizing policies need them.
- **D-live** owns: live circuit-breaker policy at the `_on_handler_error` seam, cross-thread
  portfolio reads (queue-mediated or Postgres-backed), typed REST response objects for exchange
  adapters, Postgres storage backends (real DB-transaction rollback arrives there).
- **Out of scope this phase:** uniform `on_<event>` Protocol/ABC contracts across ALL handlers
  (strategies/screeners/universe) — only the M4 surfaces get contracts (portfolio access
  Protocol, real `AbstractExecutionHandler` ABC, order facade→manager→storage).

</domain>

<decisions>
## Implementation Decisions

### Cash routing & reservations (M4-01, #22)
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

### Atomicity & error contract (M4-02, #16, #23)
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

### Portfolio access Protocol (M4-04, #6)
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

### Order layering, locks & DTOs (M4-03, M4-05, M4-06, M4-07)
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
- `TransactionManager`'s surviving method surface after the shrink (validation + recording +
  history queries).
- Storage wiring for `OrderManager` ownership (constructed in manager vs injected) and the
  TradingSystem wiring updates.
- Order of workstreams and commit sequencing, under the standing constraints: suite + both
  byte-exact oracle layers green at every commit, each workstream bisectable (Phase 3/4
  precedent).
- Test-suite adjustments for deleted surfaces (deprecated facade methods, TransactionContext,
  locks, ExecutionResult) — update/delete tests of removed machinery, add coverage for the new
  reservation/settlement paths.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REFACTOR-BRIEF.md` — program goal/scope, locked decisions (Decimal money, UUIDv7),
  golden-master discipline
- `.planning/COVERAGE-INDEX.md` — items→milestone contract; M4 row: findings 6, 9, 16, 22, 23,
  29, 39 + PERF3; §E logs any gap-discovery deltas
- `.planning/PROJECT.md` — milestone breakdown, two-point numerical re-baseline rule (M4 is NOT
  one), Out-of-Scope tags
- `.planning/REQUIREMENTS.md` — **M4-01…M4-08** (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 5 goal + 4 success criteria

### Architecture findings driving this phase
- `.planning/codebase/ARCHITECTURE-REVIEW.md` — **#22** (trade path bypasses CashManager —
  the Critical), **#23** (non-atomicity, no rollback, broken return contract), **#16**
  (TransactionContext write-only state machine + 3 concrete defects), **#6** (cross-handler
  coupling → read-model Protocol), **#9** (facade/manager split: deprecated methods, back-ref,
  storage two-owners, read-path bypass), **#29** (intra-portfolio coupling + thread-safety
  theater), **#39** (vestigial execution DTOs + fake ABC). Boundary refs (do NOT pull
  forward): #3/FR1 (Bar struct — M5a), #21/#28/#30 (validity/fees/price handler — M5a),
  #24/#31/#38/#33 (sizing/reporting/universe — M5b), #18 Postgres backends (persistence
  milestone).
- `.planning/codebase/CONCERNS.md` — PERF3 (O(n) nested-dict order lookup)

### Phase carry-forward (constrains M4)
- `.planning/phases/04-m3-event-dispatch-core/04-CONTEXT.md` — **D-04** (event money fields
  left float FOR M4-07 — this phase closes it), **D-11/D-13** (create-all-then-emit brackets;
  Order entity as pipeline state; audited REJECTED transitions — the D-02 rejection route),
  **D-12** (FillEvent fill_id/linkage IDs), **D-16** (`_on_handler_error` policy seam —
  backtest re-raises; the D-10 stop-the-run mechanism), **D-18/D-19** (domain-exception
  adoption, `ITraderError` root).
- `.planning/phases/02-m2a-identity-money-determinism/02-CONTEXT.md` + STATE.md decisions —
  Plan 02-03 (flat `Dict[uuid.UUID, Order]` index added; scan elimination deferred to M4-06 —
  this phase completes it), Plan 02-04 (portfolio.cash Decimal; cash-via-CashManager deferred
  to M4 #22 — this phase closes it; `apply_transaction_delta` interim seam to reconcile).
- `.planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/03-CONTEXT.md` —
  portfolio storage seam (the D-07 ledger route), subdomain-package reorg (cash/, transaction/,
  position/, metrics/), byte-exact oracle assertions (D-16/D-18).

### Existing patterns to mirror / golden assets
- `itrader/portfolio_handler/cash/cash_manager.py` — the CashManager API to make live
  (`process_transaction_cash_flow`, `reserve_cash`, `release_cash_reservation`,
  `available_balance`); `apply_transaction_delta` to delete.
- `itrader/portfolio_handler/transaction/transaction_manager.py` — TransactionContext to
  delete; `_check_funds_availability` math the reservation amount mirrors (D-04).
- `itrader/portfolio_handler/portfolio.py` — `process_transaction` to reorder (D-09/D-12);
  cash setter to delete (`:216-225`); position-first defect (`:289-307`).
- `itrader/order_handler/order_handler.py` + `order_manager.py` — facade/manager split to
  clean (D-18); admission path for D-02's check-and-reserve.
- `itrader/order_handler/storage/in_memory_storage.py` — flat index to make sole storage (D-20).
- `itrader/execution_handler/result_objects.py` + `base.py` — DTOs to reconcile, ExecutionResult
  to delete, fake ABC to make real (D-21).
- `itrader/core/ids.py`, `itrader/core/clock.py`, `itrader/core/enums/` — NewType/enum/clock
  patterns for any new types (Phase 2/3 precedent).
- `tests/integration/` oracle tests — behavioral identity + byte-exact numeric assertions (the
  M4-08 gate; do not modify their assertions).
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` + committed golden oracle — frozen at M2b end-state,
  reproduced exactly this phase.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CashManager` already has the full target API (`process_transaction_cash_flow`, `reserve_cash`,
  `release_cash_reservation`, `available_balance`, `reserved_balance`) — dead on the trade path
  today; this phase wires it rather than writes it.
- Flat `Dict[uuid.UUID, Order]` index already exists in `InMemoryOrderStorage` (Phase 2) —
  M4-06 is deletion of the nested dicts, not new structure.
- Phase 4's `FillEvent` linkage (fill_id, order_id, strategy_id, event_id) + audited
  `add_state_change` REJECTED path — the rejection route for failed reservations exists.
- Phase 4's `_on_handler_error` re-raise seam — the stop-the-run mechanism for D-10 exists.
- Phase 3 portfolio storage seam — the ledger persistence route for D-07 exists.

### Established Patterns
- Tabs in handler modules; spaces in config/ and newer modules — new code (Protocol, views) uses
  spaces; match files edited in place.
- `make typecheck` (mypy --strict) gate live; `filterwarnings=["error"]`, strict markers/config.
- Phase 3/4 commit discipline: bisectable workstreams, suite + byte-exact oracles green at every
  commit; pure-delete commits separate from logic commits.
- Money Decimal end-to-end (locked); enum `_missing_`/`from_string` pattern; frozen/slots DTOs.

### Integration Points
- Admission path (D-02): `order_manager.py` signal→order flow (post Phase 4 D-13 entity-based
  validation) — where check-and-reserve slots in before emit.
- Settlement path (D-09/D-12): `portfolio_handler.on_fill` → `Portfolio.process_transaction` →
  managers; `transaction_manager.py:237-256` interim cash seam to replace.
- Protocol consumers (D-14…D-17): `order_handler.py:4,38-69` (concrete import + constructors),
  `order_validator.py` (6 read sites), `order_manager.py:183`, `variable_sizer.py`,
  `advanced_risk_manager.py`.
- Lock removal (D-19): per-manager RLocks in cash/position/transaction managers, portfolio lock,
  `portfolio_handler.py` readerwriterlock; LiveTradingSystem status lock STAYS (system
  lifecycle, not portfolio state).
- DTO cleanup (D-21): `execution_handler/result_objects.py`, `exchanges/simulated.py` (discarded
  return at `:260`), `execution_handler/base.py` fake ABC.
- Event retype (D-22): `OrderEvent.new_order_event` and sibling Decimal→float coercion sites
  preserved exactly in Phase 4 — now removed.

</code_context>

<specifics>
## Specific Ideas

- User repeatedly asked "what's the most professional/reliable way?" — decisions deliberately
  anchored to industry references: broker buying-power semantics (D-04/D-08/D-14), Nautilus
  RiskEngine balance-locking (D-02), LMAX single-writer (D-19), FIX ExecutionReport
  event-stream-as-audit-trail (D-21), CQRS boundary snapshots (D-15).
- User proposed attaching the fee to each transaction ledger entry (rather than separate FEE
  entries) — adopted as D-06; they noted it's simpler and more realistic.
- User challenged whether locks are needed at all ("my framework is not asynchronous; Postgres
  locks server-side") — led to the strongest version of #29's resolution: delete the theater,
  document the single-writer contract (D-19).
- User asked what happens in backtest vs live when the settlement invariant fires — locked the
  split: backtest stops loudly; live (later) halts trading but keeps the engine on, via the
  Phase 4 seam; accounting code mode-agnostic (D-10).
- User probed the FastAPI future for ExecutionResult — locked the answer that HTTP responses
  come from the order domain (admission result + queryable order state), never from execution
  sync returns (D-21). The facade/manager split (#9) is preserved exactly for this.
- User chose ONE combined Protocol over two segregated ones for simplicity — the returned views
  stay read-only; document the M4-04 interpretation (D-13).

</specifics>

<deferred>
## Deferred Ideas

- **Position/quantity reservation for SELL orders** (preventing share over-commitment across
  orders) → live-mode work.
- **Live circuit-breaker policy** at the `_on_handler_error` seam (halt trading, alert, engine
  stays on) → **D-live**; the seam exists (Phase 4 D-16).
- **Standalone FEE ledger entries for non-trade fees** (funding, withdrawal charges) → **D-live**.
- **Slippage safety buffer on reservations** → live-mode calibration (must default to 0 to stay
  value-preserving regardless).
- **Live cross-thread portfolio reads** (queue-mediated request/response or Postgres-backed) →
  **D-live** design item, replaces the deleted lock theater with a real mechanism.
- **Typed REST response objects for live exchange adapters** → **D-live** adapter boundary
  (Nautilus pattern: adapters translate sync responses into events).
- **Uniform `on_<event>` Protocol/ABC boundary contracts across ALL handlers**
  (strategies/screeners/universe) → roadmap backlog; fits M5b's contract-enforcement work or
  later.
- **Protocol equity/percent-of-equity read methods** for completed sizing policies → **M5b
  (M5-06)** grows the Protocol deliberately then.

</deferred>

---

*Phase: 5-m4-money-transaction-correctness*
*Context gathered: 2026-06-06*
