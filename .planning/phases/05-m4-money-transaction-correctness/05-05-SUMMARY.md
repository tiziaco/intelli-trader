---
phase: 05-m4-money-transaction-correctness
plan: 05
subsystem: portfolio_handler
tags: [D-05, D-06, D-09, D-10, D-11, D-12, M4-02, atomicity, ledger, saga-deletion]
requires:
  - phase: 05-03
    provides: "Per-reference cash reservations in CashManager + PortfolioReadModel Protocol"
provides:
  - "Validate-first atomic settlement: validate -> funds invariant -> position -> cash -> record (D-09/D-12)"
  - "CashManager.apply_fill_cash_flow: full-precision signed delta, one ledger entry per fill with fee field (D-05/D-06)"
  - "CashManager.assert_funds_invariant: balance-based debit guard, reservation-blind (D-10, Pitfall 2)"
  - "One raise-typed/return-None error contract end-to-end: process_transaction, transact_shares, on_fill (D-10)"
  - "Transaction.fill_id (required kw-only) + Transaction.net_cash_delta entity-owned cash math (D-11/D-12)"
  - "Saga machinery deleted: in-flight context dataclass, transaction-state enum, pending seam, cash setter (D-11)"
  - "Deterministic live ledger: UUIDv7 operation_id + caller-supplied event time on CashOperation (Pitfall 5)"
affects: [05-06, 05-07]
tech-stack:
  added: []
  patterns:
    - "validate-first sequential settlement (LMAX/Nautilus shape) — no rollback machinery"
    - "entity owns its money math (Transaction.net_cash_delta)"
    - "invariant guard checks balance, never reservation-adjusted buying power"
key-files:
  created: []
  modified:
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/transaction/transaction.py
    - itrader/portfolio_handler/transaction/transaction_manager.py
    - itrader/portfolio_handler/base.py
    - itrader/portfolio_handler/storage/in_memory_storage.py
    - itrader/core/enums/portfolio.py
    - itrader/core/enums/__init__.py
    - itrader/core/enums/execution.py
    - tests/unit/portfolio/test_cash_manager.py
    - tests/unit/portfolio/test_transaction_manager.py
    - tests/unit/portfolio/test_portfolio.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - tests/unit/portfolio/test_state_storage.py
decisions:
  - "Net-delta math lives on the Transaction entity (net_cash_delta property) — the recommended option; TransactionManager and Portfolio both read it, no duplicate math"
  - "_check_funds_availability deleted; its math (price*qty + commission for BUY) survives as -net_cash_delta, documented in the property docstring for the 05-06 reservation mirror"
  - "Funds invariant gated on net_cash_delta < 0 (any cash debit) rather than type==BUY; equivalent for all validated transactions (commission capped at 50% of value keeps SELL deltas positive)"
  - "fill_id is a required kw-only dataclass field — all Transaction construction sites (incl. ~35 test sites) updated in the same commit"
  - "Admin cash paths (deposit/withdraw/reserve/release) pass datetime.now(UTC) explicitly at their _create_operation call sites — wall clock preserved for non-oracle paths, zero datetime.now() in the record factory"
  - "Negative regression locks written grep-clean (dir() scans for 'pending'/'cancel', __all__ scan for '*State') so the deletion acceptance grep returns literal zero while the locks survive"
metrics:
  duration: ~25 min
  completed: 2026-06-06
  tasks: 2
  commits: [6107d53, ba7461e, bfa0bf0, de08377]
---

# Phase 5 Plan 05: Atomic Validate-First Settlement Summary

**One-liner:** Settlement is now validate-first atomic (nothing mutates until all checks pass), the never-worked saga is deleted, the error contract is raise-typed/return-None end-to-end, and every fill writes exactly one full-precision ledger entry with a fee field — oracle byte-exact.

## What Was Built

### Task 1 — CashManager fill-flow primitives (6107d53 RED, ba7461e GREEN)

- `apply_fill_cash_flow(amount, fee, description, reference_id, timestamp) -> None` — the one trade-path cash primitive. Applies the SIGNED full-precision delta directly to `_balance`, bypassing `_validate_and_convert_amount`'s 2dp quantize (Pitfall 1) and the deposit/withdraw policy gates. Records exactly one `CashOperation` per fill with `amount` = signed net delta and `fee` = commission portion (D-06), so balance reconstruction holds (`balance = initial + Σ amounts`).
- `assert_funds_invariant(required) -> None` — D-10 engine-bug guard: raises `InsufficientFundsError` when `required > self._balance`. Compares against `balance`, NEVER the reservation-adjusted buying power (Pitfall 2: under portfolio-first FILL dispatch the order's own un-released reservation would false-positive). Regression-locked by a test that reserves 95k of a 100k balance and asserts a 50k requirement passes.
- `CashOperation` reshape: `operation_id` str -> UUIDv7 (`uuid_utils.compat.uuid7()`, the fill.py precedent); `fee: Decimal = Decimal("0")` field added; `timestamp` is caller-supplied — `datetime.now()` removed from `_create_operation` entirely. Admin paths (deposit/withdraw/reserve/release) pass `datetime.now(UTC)` explicitly at their call sites; the fill path always passes transaction time.

### Task 2 — Validate-first reorder + saga deletion + raise/None contract (bfa0bf0 RED, de08377 GREEN)

- `Portfolio.process_transaction` reordered per D-12: `transaction_manager.validate` (pure checks) -> `cash_manager.assert_funds_invariant(-net_delta)` (debit-side only) -> `position_manager.process_position_update` -> `cash_manager.apply_fill_cash_flow(amount=net_delta, fee=commission, timestamp=transaction.time)` -> `transaction_manager.record`. Returns None, raises typed.
- `Transaction` gains required kw-only `fill_id: uuid.UUID` (D-11 audit chain; `new_transaction` and `PortfolioHandler.on_fill` pass `fill_event.fill_id`) and a `net_cash_delta` property carrying the exact interim-seam math (BUY: `-(price*qty + commission)`; SELL: `price*qty - commission`). `to_dict` deliberately unchanged (oracle serialization untouched).
- `TransactionManager` shrunk to `validate` / `record` / `get_transaction_history`. Deleted: the in-flight context dataclass, the pending dict + seam methods (ABC + in-memory backend), `_handle_transaction_error`, the unreachable `return False`, the interim cash seam, `_check_funds_availability`, `_execute_transaction`, `_calculate_transaction_cost`, `cancel_pending_transaction`, and the sibling-reach into `portfolio.cash_manager`.
- Deleted from the wider tree: `Portfolio.cash` setter (read property survives), `apply_transaction_delta` (same commit as its consumer), the transaction-state lifecycle enum + its `core/enums/__init__` export.
- Contract propagation: `transact_shares` bool -> None/raise; `PortfolioHandler.on_fill` bool -> None/raise (non-EXECUTED fills return None after the debug log); exceptions propagate to the Phase 4 `_on_handler_error` re-raise seam — the backtest stops loudly.

## Where Things Landed (plan output questions)

- **Net-delta math:** `Transaction.net_cash_delta` property (`itrader/portfolio_handler/transaction/transaction.py`) — the entity owns its math; Portfolio reads it for both the invariant magnitude and the cash apply.
- **`_check_funds_availability` disposition:** deleted. Its math survives as `-net_cash_delta` for the debit side, documented in the property docstring as the D-04 reservation mirror referenced by Plan 05-06.
- **Test deletions/migrations:** `test_transaction_manager.py` fully rewritten (saga/pending/bool-contract tests died with the machinery; new surface: validate/record/history + net_cash_delta + deletion regression locks). `test_state_storage.py` pending round-trip replaced with a no-pending-surface lock. `test_on_fill_status_guard.py` and `test_portfolio_handler.py` bool assertions migrated to the None contract. ~35 `Transaction(...)` construction sites across 9 test files gained `fill_id=uuid_compat.uuid7()`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `tests/unit/portfolio/test_on_fill_status_guard.py` asserted the old bool contract**
- **Found during:** Task 2 (suite run after contract propagation)
- **Issue:** File not in the plan's `files_modified` list but asserted `on_fill` truthy/falsy returns
- **Fix:** Migrated to the D-10 None contract (observable behavior — transaction/position creation — still asserted)
- **Files modified:** tests/unit/portfolio/test_on_fill_status_guard.py
- **Commit:** de08377

**2. [Rule 3 - Blocking] fill_id required field broke Transaction constructions in unowned test files**
- **Found during:** Task 2 (Pitfall 7 — wide but mechanical fallout)
- **Issue:** `test_position_manager.py`, `test_money_decimal.py`, `positions/*.py`, `test_portfolio_read_model.py`, `test_transaction_init.py` construct Transactions directly
- **Fix:** Added `fill_id=uuid_compat.uuid7()` (+ import) to every site; `test_transaction_init.py` additionally asserts the factory carries the FillEvent's fill_id
- **Files modified:** 6 test files outside the plan's list
- **Commit:** de08377

No other deviations — plan executed as written.

## Verification Evidence

- `poetry run python -m pytest tests/unit tests/integration -q` — **469 passed** (cwd-first import; worktree-safe)
- `poetry run mypy itrader` (make typecheck equivalent) — **Success: no issues found in 135 source files**
- `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` — **2 passed** (both oracle layers byte-exact); `git diff` on golden files empty
- Acceptance greps: saga/pending/setter identifiers — **0 matches repo-wide**; `return False` in transaction_manager — 0; `@cash.setter` — 0; `datetime.now()` in cash_manager — 0; `assert_funds_invariant` -A3 window contains no "available"

## Known Stubs

None — no placeholder values, no unwired data paths introduced.

## Threat Flags

None — no new network/auth/file surface; all changes sit inside the FillEvent -> settlement boundary already covered by the plan's threat model (T-05-10..13 mitigations implemented as specified).

## Self-Check: PASSED

- SUMMARY.md, apply_fill_cash_flow, fill_id artifacts verified on disk
- All 4 task commits (6107d53, ba7461e, bfa0bf0, de08377) present in git log; this docs commit follows
- No file deletions in the plan's commit range; no untracked files left behind
- TDD gates: test commit precedes feat commit for both tasks (RED -> GREEN)
