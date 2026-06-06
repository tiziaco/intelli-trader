---
phase: 05-m4-money-transaction-correctness
verified: 2026-06-06T11:40:00Z
status: human_needed
score: 7/8 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Confirm CR-01 fix is in scope before proceeding: quantity-only order modification raises TypeError in order_validator.py"
    expected: "Either a fix is committed before phase 6, or a formal override is accepted acknowledging the modify_order path is broken for quantity-only changes"
    why_human: "CR-01 does not block the backtest path or any phase success criterion, but it is a functional regression in a code path the phase touched (order_validator.py). Human must decide: fix-forward or override."
  - test: "Confirm CR-02 fix is in scope before proceeding: LiveTradingSystem.record_metrics AttributeError on every TIME event"
    expected: "Either a fix is committed, or a formal override is accepted acknowledging live-mode metrics are silently broken"
    why_human: "CR-02 affects live mode only — not the backtest path — but was introduced by the phase's refactoring scope. Human must decide: fix-forward or override."
---

# Phase 05: M4 Money & Transaction Correctness — Verification Report

**Phase Goal:** Route every trade's cash through `CashManager` (Critical #22), make transaction processing atomic with rollback, enforce one-directional order-handler layering with O(1) lookup and a narrow read-model Protocol, and freeze the execution result DTOs — value-preserving against the oracle.
**Verified:** 2026-06-06T11:40:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Every trade routes cash through `CashManager` with no `portfolio.cash += float(...)` setter bypass; ledger/reservations/audit are live (Critical #22 / M4-01) | VERIFIED | `Portfolio.cash` setter deleted (grep returns 0). BUY admission gate in `order_manager.py:228-248` calls `portfolio_handler.reserve(...)`. Settlement flows through `apply_fill_cash_flow` in `portfolio.py:317`. Inertness test: 137 reserve calls, reserved_balance==0 post-run, trade log byte-identical. |
| 2 | Transaction processing is atomic — funds checked before position mutation, rollback on failure, one coherent error/return contract (no unreachable `return False` behind a re-raise) | VERIFIED | `portfolio.py:301-326` shows the D-12 sequence: validate → funds invariant → position mutate → cash apply → record. `grep -c "return False" transaction_manager.py` returns 0. `process_transaction` declared `-> None` (raises typed on failure). |
| 3 | Order-handler layering is one-directional facade→manager→storage with the read path through `OrderManager`, an O(1) `{order_id: order}` index, cross-handler reads via a narrow `PortfolioReadModel` Protocol, and resolved intra-portfolio coupling | VERIFIED | `grep "self.order_storage" order_handler.py` returns 0. `grep "order_handler_ref\|self.order_handler" order_manager.py` returns 0. Flat dict `self._by_id` is the sole container (grep for nested dicts returns 0). All 7 handler read methods delegate through `self.order_manager.*`. 5 consumers retyped to `PortfolioReadModel`; concrete `PortfolioHandler` import gone from order/strategy domains. |
| 4 | Execution `result_objects`/`base` DTOs are frozen, Decimal-typed, real-ABC, and carry `fill_id` | VERIFIED | `ExecutionResult` deleted (only a docstring tombstone remains). `execution_handler/base.py` has 3 `@abstractmethod` decorators (on_order, on_market_data + ABC class). `result_objects.py` has 3 `@dataclass(frozen=True, slots=True)` classes. `ValidationResult` renamed `OrderPreflightResult`. `fill_id` criterion satisfied via `FillEvent` linkage (Phase 4 D-12 — every fill carries `fill_id`/`order_id`/`strategy_id`). |
| 5 | Event money fields (SignalEvent/OrderEvent/FillEvent) are Decimal — float coercions removed | VERIFIED | `FillEvent.price/quantity/commission: Decimal`. `OrderEvent.price/quantity: Decimal`. `SignalEvent.price/stop_loss/take_profit/quantity: Decimal`. `float(order.price)\|float(order.quantity)` in events/order.py returns 0. `commission=0.0\|float(commission)` in simulated.py returns 0. |
| 6 | D-19 single-writer contract: no portfolio-state locks, `readerwriterlock` dependency removed | VERIFIED | `grep RLock\|readerwriterlock\|rwlock` across all 4 portfolio/execution files returns 0 each. `grep "single-writer" portfolio.py` = 3, `portfolio_handler.py` = 4. `grep "readerwriterlock" pyproject.toml` = 0. `_status_lock` in `live_trading_system.py` = 3 (untouched). `_publish_error_event` = 4 (error publication survives). |
| 7 | Golden-master gate: `final_equity = 53229.68512642488` byte-exact; oracle assertions unmodified | VERIFIED | Full suite: 494 passed. Oracle test: 2 passed. `git diff --stat tests/golden/` empty. Manual `scripts/run_backtest.py` run: `final_equity = 53229.68512642488` — matches frozen M2b value. `mypy --strict`: Success, 157 source files clean. |
| 8 | CR-01 (quantity-only modify_order TypeError) and CR-02 (LiveTradingSystem.record_metrics AttributeError) — code review critical findings | UNCERTAIN | CR-01 is confirmed in `order_validator.py:530-532`: `'new_price' in modifications` is always True when both kwargs are passed; `None <= 0` raises TypeError. CR-02 is confirmed in `live_trading_system.py:246`: `portfolio_handler.record_metrics` does not exist on `PortfolioHandler`. Both defects pre-date this phase's intent and are in code paths touched by the phase. Neither blocks the backtest oracle. Human decision required. |

**Score:** 7/8 truths verified (truth 8 is UNCERTAIN — human decision needed)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/order_handler/storage/in_memory_storage.py` | Flat-dict-only (D-20) | VERIFIED | `self._by_id` is the sole container (11 references); nested dicts gone (grep=0) |
| `itrader/order_handler/order_manager.py` | Exclusive storage ownership + read methods (D-18) | VERIFIED | No `order_handler_ref`; no `self.order_handler`; no queue puts; owns `order_storage` |
| `itrader/order_handler/order_handler.py` | Thin facade (no direct storage access) | VERIFIED | `self.order_storage` grep = 0; all reads delegate through `self.order_manager` |
| `itrader/core/portfolio_read_model.py` | `PortfolioReadModel` Protocol + frozen `PositionView` (D-13..D-17) | VERIFIED | 190 lines; `@runtime_checkable` ×4; 6 Protocol methods; `@dataclass(frozen=True)` ×1 |
| `tests/unit/core/test_portfolio_read_model.py` | Protocol conformance + frozen-view tests | VERIFIED | 244 lines; exists and runs green |
| `itrader/portfolio_handler/portfolio_handler.py` | Structural Protocol implementation | VERIFIED | All 6 Protocol methods present (lines 226-258); no lock references |
| `itrader/portfolio_handler/cash/cash_manager.py` | `apply_fill_cash_flow` + `assert_funds_invariant` + per-reference reservations | VERIFIED | Both methods present; `fee: Decimal` field; `release_reservation` present; `datetime.now()` grep=0 |
| `itrader/portfolio_handler/portfolio.py` | D-12 settlement orchestration; no cash setter | VERIFIED | `process_transaction -> None` with D-12 5-step sequence; `@cash.setter` grep=0 |
| `itrader/portfolio_handler/transaction/transaction.py` | Transaction with `fill_id` linkage | VERIFIED | `fill_id: uuid.UUID = field(kw_only=True)` at line 39; `net_cash_delta` property |
| `itrader/execution_handler/base.py` | Real ABC with `@abstractmethod on_order` + `on_market_data` | VERIFIED | 3 `@abstractmethod` decorators; both hooks present; Compliance paragraph deleted |
| `itrader/execution_handler/result_objects.py` | Frozen/Decimal surviving DTOs; no `ExecutionResult` | VERIFIED | 3 `@dataclass(frozen=True, slots=True)` classes; `class ValidationResult` = 0; `class OrderPreflightResult` = 1 |
| `tests/integration/test_reservation_inertness.py` | D-14 mandated golden-run inertness trace | VERIFIED | Exists; 3 tests pass: reserve-never-rejects, reserved==0 post-run, trade-log identity |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `order_handler/order_handler.py` | `order_handler/order_manager.py` | all get_*/search_* reads delegate to manager | WIRED | Confirmed: `self.order_manager.get_*` at lines 230, 248, 264, 280, 298, 316, 332 |
| `order_handler/order_manager.py` | `order_handler/storage/in_memory_storage.py` | manager-owned `self.order_storage` | WIRED | `self.order_storage.*` in manager; handler has 0 references to `order_storage` |
| `order_handler/order_handler.py` | `core/portfolio_read_model.py` | Protocol-typed constructor annotation | WIRED | `PortfolioReadModel` referenced 3x in handler |
| `portfolio_handler/portfolio_handler.py` | `portfolio_handler/cash/cash_manager.py` | `available_cash/reserve/release` delegation | WIRED | Lines 226-257; all 6 Protocol methods delegate to portfolio internals |
| `portfolio_handler/portfolio.py` | `portfolio_handler/cash/cash_manager.py` | settlement sequence calls `assert_funds_invariant` then `apply_fill_cash_flow` | WIRED | `portfolio.py:309,317`; correct sequence confirmed |
| `portfolio_handler/portfolio_handler.py` | `portfolio_handler/portfolio.py` | `on_fill -> transact_shares -> process_transaction` (raise/None contract) | WIRED | Confirmed in `portfolio_handler.py:255-320` flow; `process_transaction` returns `None`, raises typed |
| `order_handler/order_manager.py` | `core/portfolio_read_model.py` | `protocol.reserve` at admission, `protocol.release` at terminal reconciliation | WIRED | `reserve` call at line 231-232 (BUY gate); `release` call at line 143-144 (terminal reconciliation) |
| `trading_system/backtest_trading_system.py` | `order_handler/order_manager.py` | commission-estimator wiring (fee model rate) | WIRED | `commission_estimator=_estimate_commission` at line 93 of backtest_trading_system.py |
| `execution_handler/exchanges/simulated.py` | `core/money.py` | `to_money` at float-bar → Decimal-fill boundary | WIRED | Comment at simulated.py line 201 confirms; `FillEvent.new_fill` owns normalization |
| `strategy_handler/base.py` | `core/money.py` | strategy float prices enter `SignalEvent` via `to_money` | WIRED | Confirmed: float prices converted via `to_money` in `_generate_signal` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `portfolio_handler/portfolio.py::process_transaction` | `net_delta` | `Transaction.net_cash_delta` property (entity-owned math) | Yes — computed from real fill price/quantity/commission fields | FLOWING |
| `order_handler/order_manager.py::process_signal` | `cost` for reservation | `primary.price * primary.quantity + commission_estimator` | Yes — Decimal entity fields; golden run: 137 reserve calls with amounts matching 0.95x available | FLOWING |
| `cash_manager.py::apply_fill_cash_flow` | `amount` | caller-supplied signed delta, no 2dp quantize | Yes — bypasses `_validate_and_convert_amount`; ledger reconstruction holds | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle final equity equals frozen M2b value | `scripts/run_backtest.py` | `final_equity = 53229.68512642488` | PASS |
| Full test suite green | `poetry run python -m pytest tests/ -q` | 494 passed, 0 failed | PASS |
| mypy --strict clean | `poetry run mypy itrader` | Success: no issues in 157 source files | PASS |
| Reservation inertness | `poetry run python -m pytest tests/integration/test_reservation_inertness.py -q` | 3 passed | PASS |
| Oracle (behavioral + numerical) | `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` | 2 passed (byte-exact) | PASS |

---

### Probe Execution

No `probe-*.sh` files declared or present for this phase.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| M4-01 | Plan 05-06 | Every trade routes cash through CashManager; ledger/reservations/audit live | SATISFIED | BUY-only reserve gate wired; terminal release in on_fill; settlement via apply_fill_cash_flow; no setter bypass; inertness test proves oracle-inert |
| M4-02 | Plan 05-05 | Atomic transaction — funds before mutation, rollback on failure, one error contract | SATISFIED | D-12 sequence in portfolio.py:301-326; saga deleted; `return False` in TM = 0; `process_transaction -> None` |
| M4-03 | Plan 05-01 | One-directional order-handler layering: facade→manager→storage | SATISFIED | Deprecated methods deleted; back-ref deleted; `self.order_storage` in handler = 0; reads delegate through manager |
| M4-04 | Plan 05-03 | Cross-handler reads via narrow PortfolioReadModel Protocol | SATISFIED | Protocol exists; 5 consumers retyped; concrete PortfolioHandler import = 0 in order/strategy domains |
| M4-05 | Plan 05-02 | Intra-portfolio coupling resolved (no thread-safety theater) | SATISFIED | All 8 portfolio-state locks deleted; readerwriterlock removed from pyproject.toml; single-writer contract documented |
| M4-06 | Plan 05-01 | O(1) flat `{order_id: order}` index | SATISFIED | `self._by_id` sole container; nested dicts = 0 |
| M4-07 | Plans 05-04, 05-07 | Execution DTOs frozen/Decimal/real-ABC; fill_id; events Decimal-typed | SATISFIED | ExecutionResult deleted; real ABC with 2 @abstractmethods; 3 surviving DTOs frozen=True/slots=True; 9 event money fields Decimal; fill_id via FillEvent linkage |
| M4-08 | Plan 05-07 | Value-preserving against oracle; behavioral oracle unchanged | SATISFIED | final_equity = 53229.68512642488 (frozen M2b value); oracle assertions unmodified; golden files byte-identical; mypy --strict clean |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|---------|--------|
| `order_handler/order_validator.py` | 530-532 | `if new_price <= 0:` where `new_price` may be `None` (CR-01) | WARNING | TypeError on any quantity-only `modify_order` call — function path broken but NOT on the backtest/signal/fill path used by oracle |
| `trading_system/live_trading_system.py` | 246 | `portfolio_handler.record_metrics(event.time)` — method doesn't exist on `PortfolioHandler` (CR-02) | WARNING | AttributeError swallowed by loop catch-all; live-mode metrics silently never recorded — NOT on backtest path |
| `order_handler/storage/postgresql_storage.py` | 9, 40 | "placeholder implementation" comments | INFO | Pre-existing D-sql deferred scope (explicitly out-of-scope per REQUIREMENTS.md v2 deferred register); phase only removed 2 overrides; not a new stub |

---

### Human Verification Required

#### 1. CR-01: Quantity-only order modification TypeError

**Test:** Call `order_handler.modify_order(order_id, new_quantity=Decimal("5"))` with no `new_price` argument on any order with a non-zero `filled_quantity`. Alternatively, attempt any price-only modify on a partially filled order.
**Expected:** Should succeed (or fail with a typed ValidationError), but NOT raise `TypeError`.
**Why human:** CR-01 is a confirmed defect in `order_validator.py:530-532` — `'new_price' in modifications` is always True when `order_manager.modify_order` passes both kwargs including `None` values; `if None <= 0` raises `TypeError`. The phase goal success criteria all pass (backtest oracle, full suite green), but the modify_order code path was touched in plan 05-01/05-03 and this bug surfaces there. Human must decide: (a) commit a fix before phase 6, or (b) accept a formal override documenting the deviation.

To accept without fixing, add to VERIFICATION.md frontmatter:
```yaml
overrides:
  - must_have: "CR-01: quantity-only modify_order path works"
    reason: "modify_order is not on the backtest path; golden oracle unaffected; deferred to a later cleanup phase"
    accepted_by: "{name}"
    accepted_at: "{ISO timestamp}"
```

#### 2. CR-02: LiveTradingSystem.record_metrics AttributeError

**Test:** Start `LiveTradingSystem` and let a TIME event process. Observe whether metrics are silently never recorded and whether `errors_count` increments every tick.
**Expected:** `portfolio.record_metrics(event.time)` should be called correctly on each Portfolio instance (as the backtest does at `backtest_trading_system.py:149-150`).
**Why human:** The fix is mechanical (iterate `portfolio_handler.get_active_portfolios()` and call `portfolio.record_metrics(event.time)`), but live mode cannot be exercised by the automated test suite. Human must decide: (a) commit the fix now, or (b) accept a formal override scoping this to D-live.

---

### Gaps Summary

No structural gaps were found. All 8 phase success criteria have implementation evidence in the codebase. The 7/8 score reflects that truth 8 (CR-01/CR-02 review critical findings) resolves to UNCERTAIN rather than VERIFIED — because two confirmed defects in code touched by this phase require a human decision on disposition before the phase is fully clean.

The two critical review findings (CR-01, CR-02) do not affect the primary success criteria:
- CR-01 (modify_order TypeError) is not on the backtest or signal-admission path
- CR-02 (record_metrics AttributeError) is live-mode only — the backtest path is correct

The oracle is byte-exact (`final_equity = 53229.68512642488`), the full suite is green (494 passed), and mypy --strict is clean. The phase goal is substantively achieved on the backtest path.

---

_Verified: 2026-06-06T11:40:00Z_
_Verifier: Claude (gsd-verifier)_
