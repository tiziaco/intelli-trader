---
phase: 05-m4-money-transaction-correctness
fixed_at: 2026-06-06T00:00:00Z
review_path: .planning/phases/05-m4-money-transaction-correctness/05-REVIEW.md
iteration: 1
findings_in_scope: 14
fixed: 14
skipped: 0
status: all_fixed
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-06-06
**Source review:** .planning/phases/05-m4-money-transaction-correctness/05-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 14 (2 Critical + 12 Warning; fix_scope=critical_warning, Info excluded)
- Fixed: 14
- Skipped: 0

Every fix was verified against the full 504-test suite (including the byte-exact
backtest oracle, `tests/integration/test_backtest_oracle.py`) before committing,
and `mypy itrader` is clean after the final commit (matching the clean base).
The golden-master numbers were never perturbed.

## Fixed Issues

### CR-01: Quantity-only order modification always fails with TypeError

**Files modified:** `itrader/order_handler/order_validator.py`, `tests/unit/order/test_order_manager.py`
**Commit:** 2c8cb3c
**Applied fix:** `validate_order_modification` now skips `None` modification
values (`'new_quantity' in modifications and ... is not None`, same for
`new_price`) — a `None` kwarg means "no change" and is never compared. Added
two regression tests: quantity-only modify (no price) and price-only modify on
a PARTIALLY_FILLED order, both previously raising `TypeError`.

### CR-02: LiveTradingSystem calls nonexistent `PortfolioHandler.record_metrics`

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 1bc6924
**Applied fix:** The live TIME-event branch now iterates
`portfolio_handler.get_active_portfolios()` and calls
`portfolio.record_metrics(event.time)` per portfolio — the exact pattern the
backtest path uses (`backtest_trading_system.py:149-150`).

### WR-01: Order-mirror reconciliation ignores `fill_event.quantity`

**Files modified:** `itrader/order_handler/order_manager.py`, `tests/unit/order/test_order_manager.py`
**Commit:** 9d9a8bc
**Applied fix:** `on_fill` (EXECUTED) now reconciles `to_money(fill_event.quantity)`
instead of a blanket `remaining_quantity`. The review's suggestion was adapted
to honor the golden-master constraint: the event quantity is float-roundtripped
at the D-22 exchange boundary, so a FULL fill can legitimately differ from
`remaining_quantity` at full Decimal precision in either direction. A quantity
equal to `to_money(float(remaining))` is recognized as the full fill (quiet),
a quantity above remaining is clamped with a warning, and anything below is a
genuine partial fill tracked as PARTIALLY_FILLED. On the golden path every
fill resolves to exactly `remaining_quantity` — byte-identical to the previous
behavior (oracle verified green). Added regression tests for genuine partial
fills and lossy-roundtrip full fills.

### WR-02: Reservation release skipped when `add_fill` is rejected

**Files modified:** `itrader/order_handler/order_manager.py`, `tests/unit/order/test_order_manager.py`
**Commit:** c96baef
**Applied fix:** A rejected mirror transition (`add_fill` returns False) no
longer early-returns: only the storage update is skipped (`applied` flag), and
the uniform idempotent terminal release runs for every EXECUTED/CANCELLED/
REFUSED fill referencing a known order. The truly-unknown-status branch still
returns without releasing (not a terminal reconciliation — reservation
intentionally held). Regression test: EXECUTED fill arriving for a locally
CANCELLED order still releases.

### WR-03: Reservation leaks when bracket assembly/storage fails after reserve

**Files modified:** `itrader/order_handler/order_manager.py`, `tests/unit/order/test_order_manager.py`
**Commit:** 7448db7
**Applied fix:** `process_signal` tracks the reserve→emit window
(`reserved_primary` / `primary_emitted`). If the admission reserve succeeded
but `_assemble_bracket_and_emit` produced no successful primary result (failure
detected via `affected_order_ids`), or an exception fires anywhere between
reserve and emit (outer `except`), the orphaned reservation is released
immediately (idempotent). Regression test: storage `add_order` raising after
reserve → release called, nothing emitted.

### WR-04: Local cancel path never releases the reservation

**Files modified:** `itrader/order_handler/order_manager.py`, `tests/unit/order/test_order_manager.py`
**Commit:** b8ad032
**Applied fix:** `cancel_order` now performs the idempotent release right after
the successful local terminal transition — it no longer depends on an exchange
`FillEvent(CANCELLED)` that only arrives for orders actually resting in the
matching engine. A later exchange-driven re-release is a silent no-op.
Regression test added.

### WR-05: Bracket children orphaned when the parent is REFUSED

**Files modified:** `itrader/order_handler/order_manager.py`, `itrader/order_handler/order_handler.py`, `tests/unit/order/test_order_manager.py`
**Commits:** f78e162, 612d842 (follow-up: cast-bridge for the pre-existing
`cancel_order` int-id annotation drift so `mypy itrader` stays clean)
**Applied fix:** `OrderManager.on_fill` now returns `List[OrderEvent]`: when a
parent with non-empty `child_order_ids` reconciles to CANCELLED/REFUSED with
`filled_quantity == 0`, each child is cancelled locally (reusing
`cancel_order`, which also handles its release per WR-04) and the resulting
CANCEL OrderEvents are returned. `OrderHandler.on_fill` enqueues them so the
exchange removes the resting protective orders (D-18 preserved: the manager
never touches the queue). Regression tests: REFUSED parent cancels both
children + returns 2 CANCEL events; FILLED parent keeps children active.

### WR-06: DynamicSizer divides by zero when open positions reach `max_positions`

**Files modified:** `itrader/strategy_handler/position_sizer/variable_sizer.py`
**Commit:** 831ed39
**Applied fix:** Guard `if available_pos <= 0: return 0.0` with a warning log —
zero quantity flows into the downstream zero-quantity validation rejection
instead of `ZeroDivisionError` (slots full) or a negative quantity (over-full).

### WR-07: `Portfolio.to_dict` reports total cash as `available_cash`

**Files modified:** `itrader/portfolio_handler/portfolio.py`, `tests/unit/portfolio/test_portfolio_update.py`
**Commit:** 670d006
**Applied fix:** `'available_cash': self.cash_manager.available_balance`
(reservation-adjusted, the D-14 single trading-decision figure) plus a new
`'reserved_cash': self.cash_manager.reserved_balance` for auditability.
Golden outputs are unaffected (they derive from Position/Transaction
`to_dict`, and reservations are always zero at end-of-tick in the golden run).
Regression test asserts the serialized snapshot reflects an outstanding
reservation.

### WR-08: `max_portfolios` bound to the per-portfolio position limit

**Files modified:** `itrader/config/portfolio.py`, `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** c6e1dbd
**Applied fix:** Added a dedicated `max_portfolios: int = Field(default=50, gt=0)`
to `PortfolioLimits` (default 50 matches the previous effective value from
`max_positions`' default, so behavior is unchanged) and switched all three
handler read sites (`__init__`, `update_config`, `rollback_config`) to it.

### WR-09: Live event loop get-then-put-back breaks FIFO ordering

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 195168f
**Status note:** fixed: requires human verification — this is live-mode
event-loop logic with no automated test coverage in the suite; the change is
syntactically and structurally verified but the live loop should be smoke-run
before relying on it.
**Applied fix:** The dequeued event is dispatched directly through the event
handler's routing (`self.event_handler._dispatch(event)`) instead of being
re-enqueued behind already-queued events; the inconsistent `task_done()`
bookkeeping (which left `unfinished_tasks` drifting) is dropped with the
put-back.

### WR-10: Hardcoded database credentials in source

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 1e76608
**Applied fix:** `_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "")` — no embedded
credentials. An unset URL now logs a loud warning and falls back directly to
in-memory order storage (the same fallback the `NotImplementedError` path
already used).

### WR-11: Concurrency tests race against the lock-free CashManager (D-19)

**Files modified:** `tests/unit/portfolio/test_cash_manager.py`
**Commit:** 3f23da1
**Applied fix:** Rewrote `test_concurrent_operations` and
`test_concurrent_reservation_operations` as sequential single-writer tests
(same operation mix and final-balance assertions, run on one writer per the
D-19 contract; the reservation variant now overlaps all five reservations
before releasing to exercise multi-key accounting). Removed the now-unused
`threading`/`time` imports.

### WR-12: `Strategy._generate_signal` crashes on a ticker missing from the last bar

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 81d213e
**Applied fix:** `if last_close is None: return` guard (with a warning log)
before the money-domain entry — mirroring the matching engine's guard for the
same Optional.

## Skipped Issues

None — all in-scope findings were fixed.

## Verification

- Full suite run after EVERY fix commit: 494 baseline → 504 final, all green
  every time (10 new regression tests added).
- Backtest oracle (`tests/integration/test_backtest_oracle.py` vs
  `tests/golden/`) green throughout — golden numbers byte-exact, no re-baseline.
- `mypy itrader`: clean (no issues in 135 source files), matching the clean base.
- All work performed in an isolated git worktree and fast-forwarded onto
  `implement-phase-5`.

---

_Fixed: 2026-06-06_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
