# Phase 5: M4 — Money & Transaction Correctness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-06
**Phase:** 5-m4-money-transaction-correctness
**Areas discussed:** Cash routing & reservations, Atomicity & error contract, PortfolioReadModel Protocol, Order layering & locks/DTOs

---

## Cash routing & reservations

| Option | Description | Selected |
|--------|-------------|----------|
| Reserve at order creation | Full lifecycle: reserve on accept, release on terminal state, settle at fill | ✓ |
| Reserve only resting orders | Market orders debit directly; only stop/limit reserve | |
| Debit/credit at fill only | No reservations until live mode | |

**User's choice:** Reserve at order creation (recommended).

| Option | Description | Selected |
|--------|-------------|----------|
| Delete both | cash read-only; trade path via process_transaction_cash_flow; apply_transaction_delta deleted | ✓ |
| Setter raises, seam deleted | Keep setter as a raising migration aid | |
| Keep setter as thin delegate | Backward-compatible single audited adjustment | |

**User's choice:** Delete both (recommended).

| Option | Description | Selected |
|--------|-------------|----------|
| Separate FEE entry | Distinct ledger operation per fill for commission | |
| Folded into one entry | One net entry, fees not separable | |
| Fee as field on the entry | User counter-proposal: each TRANSACTION_DEBIT/CREDIT carries a fee field | ✓ |

**User's choice:** User proposed associating the fee with every transaction debit/credit — adopted (simpler, CCXT/broker-statement realistic). Follow-up locked `amount` = net cash delta (balance = Σ amounts stays trivial).

| Option | Description | Selected |
|--------|-------------|----------|
| Sync check-and-reserve | Atomic reserve at admission via Protocol; fail → REJECTED, nothing emitted | ✓ |
| Via the queue | PortfolioHandler reserves on ORDER route dispatch | |

**User's choice:** Asked "most reliable, realistic, professional way?" — sync check-and-reserve (broker/Nautilus RiskEngine pattern; queue path splits check from act, a TOCTOU).

**Additional decisions in this area:** bracket SL/TP children reserve nothing (cash-debit-only reservations); reservation amount = price×qty + estimated fee (mirrors today's funds-check math); ledger entries route through the Phase 3 storage seam; reservations affect only available_balance (never equity/metrics/oracle); withdrawals draw against available_balance only.

---

## Atomicity & error contract

| Option | Description | Selected |
|--------|-------------|----------|
| Validate-first, fail-fast | validate → check → mutate position → apply cash; no rollback machinery | ✓ |
| Mutate + rollback (saga) | Compensating-undo in application code | |
| Both | Validate-first plus rollback safety net | |

**User's choice:** Asked "how is it done in a professional setup?" — validate-first, fail-fast (fills are facts; LMAX/Nautilus sequential shape; rollback belongs to the storage layer when durability exists).

| Option | Description | Selected |
|--------|-------------|----------|
| Raise typed, return None | Typed domain exceptions; bool contract deleted | ✓ |
| Result object | TransactionResult, never raise | |
| Honest bool | Make the documented bool real | |

**User's choice:** Asked again for the professional pattern — raise typed, return None (one channel; invariant violations are exceptions; Results are un-Pythonic).

| Option | Description | Selected |
|--------|-------------|----------|
| Delete it entirely | TransactionContext + state machine die; Transaction entity is the audit record | ✓ |
| Persist lifecycle via storage | Slimmed state machine persisted through the seam | |

**User's choice:** Delete entirely (recommended).

| Option | Description | Selected |
|--------|-------------|----------|
| Invariant guard — raise | Settlement funds check raises; backtest stops; live circuit-breaker later at the seam | ✓ |
| Apply anyway, go negative | Pure fills-are-facts; margin-call warning | |

**User's choice:** User clarified the live concern ("I should keep the engine on — what happens in backtest?") — locked: backtest stops loudly (corrupted books must never produce numbers); live keeps the engine on via the Phase 4 `_on_handler_error` seam; accounting code mode-agnostic.

| Option | Description | Selected |
|--------|-------------|----------|
| Portfolio orchestrates | Portfolio owns validate→position→cash→record; managers single-concern | ✓ |
| TransactionManager as settlement engine | Manager coordinates siblings | |

**User's choice:** Portfolio orchestrates (recommended; aggregate-owns-unit-of-work).

---

## PortfolioReadModel Protocol

| Option | Description | Selected |
|--------|-------------|----------|
| available_cash only | Buying power is the single trading-decision figure | ✓ |
| Both, explicit names | get_available_cash + get_total_cash | |

**User's choice:** Asked "most reliable option?" — available_cash only (sizing and admission can never disagree; value-preserving since available == total at every BUY decision point in the golden run).

| Option | Description | Selected |
|--------|-------------|----------|
| Frozen PositionView DTO | Immutable Decimal snapshot under the portfolio lock | ✓ |
| Live Position object | Real mutable object, no mapping | |

**User's choice:** Asked "what do professional frameworks do?" — frozen PositionView (snapshots across boundaries: CQRS/FIX; LEAN/Nautilus live objects only work because one thread owns everything).

| Option | Description | Selected |
|--------|-------------|----------|
| Two narrow Protocols | Read model + reservation service, interface segregation (recommended) | |
| One combined Protocol | Single surface with reads + reserve/release | ✓ |

**User's choice:** Asked "what's simpler?" — **chose one combined Protocol against the recommendation**, preferring simplicity. Returned views remain read-only; M4-04 interpretation documented.

| Option | Description | Selected |
|--------|-------------|----------|
| PortfolioHandler directly | Structural typing, no adapter | ✓ |
| Dedicated adapter object | Wrapper class | |

**User's choice:** Asked "best and simpler?" — PortfolioHandler directly (mypy enforces the boundary at the constructor type, adapter redundant).

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, retype now | variable_sizer / advanced_risk_manager get the Protocol this phase | ✓ |
| Defer to M5b | Leave direct reads for the sizing rewrite | |

**User's choice:** Yes, retype now (recommended).

---

## Order layering & locks/DTOs

| Option | Description | Selected |
|--------|-------------|----------|
| No locks — single-writer | Delete all portfolio-domain locks; document the contract | ✓ |
| One defensive portfolio lock | Single RLock belt-and-braces | |

**User's choice:** **User challenged whether locks are needed at all** (not async; Postgres locks server-side in live). Confirmed: single-writer architecture makes locks theater — deleted, contract documented; live cross-thread reads = D-live item.

| Option | Description | Selected |
|--------|-------------|----------|
| Flat dict only | {order_id: order} is THE storage; queries scan-and-filter | ✓ |
| Flat + secondary indexes | Maintained per-ticker/portfolio indexes | |

**User's choice:** Flat dict only (recommended).

| Option | Description | Selected |
|--------|-------------|----------|
| Delete it — events only | execute_order returns None; FillEvent single channel | ✓ |
| Internal contract, consumed | Frozen ExecutionResult consumed for logging/health | |

**User's choice:** Asked for the professional pattern + whether option 2 preserves logging/auditability/traceability + how FastAPI returns HTTP responses later. Locked: delete (Nautilus/FIX event-stream-as-audit); FastAPI responses come from the order domain (admission result + queryable order state), never execution sync returns. Note: my initial recommendation was "keep + consume" — investigating the user's questions flipped it.

| Option | Description | Selected |
|--------|-------------|----------|
| Byte-exact or stop | Event-money Decimal retype numerically inert; any diff owner-gated via §E | ✓ |
| Tolerance window | D-15-style tolerance time-boxed to M5 | |

**User's choice:** Byte-exact or stop (recommended; M4 is not a re-baseline point).

| Option | Description | Selected |
|--------|-------------|----------|
| Only M4 surfaces | Protocol/ABC contracts only where M4 requires | ✓ |
| All handlers now | Uniform on_<event> contract sweep | |

**User's choice:** Only M4 surfaces (recommended; uniform sweep → backlog).

---

## Claude's Discretion

- Protocol + PositionView module location/naming (likely `itrader/core/`)
- CashOperationType vocabulary, reservation reference-ID scheme, CashOperation field set
- Commission-estimate mechanism for reservations (must mirror today's funds-check math)
- Per-DTO survival in result_objects.py; ValidationResult namespacing
- TransactionManager surviving surface; OrderManager storage wiring
- Workstream/commit sequencing (bisectable, oracles green every commit)
- Test-suite adjustments for deleted surfaces + new coverage for reservation/settlement paths

## Deferred Ideas

- Position/quantity reservation for SELL orders → live-mode work
- Live circuit-breaker policy at the `_on_handler_error` seam → D-live
- Standalone FEE entries for non-trade fees → D-live
- Slippage safety buffer on reservations → live calibration
- Live cross-thread portfolio reads (queue-mediated or Postgres-backed) → D-live
- Typed REST response objects for live exchange adapters → D-live
- Uniform handler Protocol/ABC contracts → roadmap backlog / M5b
- Protocol equity-read methods for sizing policies → M5b (M5-06)
