---
phase: 05-m4-money-transaction-correctness
plan: 03
subsystem: portfolio-order-boundary
tags: [protocol, decimal, reservations, mypy-strict, m4-04]
requires:
  - "05-01: flat-dict InMemoryOrderStorage + one-directional order layering (D-18/D-20)"
  - "05-02: lock-free single-writer portfolio (D-19)"
provides:
  - "itrader/core/portfolio_read_model.py: PortfolioReadModel Protocol (6 members) + frozen PositionView (D-13..D-17)"
  - "Per-reference full-precision cash reservation API on the storage seam + CashManager (OQ4) — ready for 05-06 trade-path wiring"
  - "PortfolioHandler structural Protocol conformance (D-16, no inheritance)"
  - "Order domain (handler/manager/validator) + admission path (sizer/risk manager) typed against the Protocol — concrete import dead"
affects:
  - "05-06: wires reserve/release into the trade path via this seam"
tech-stack:
  added: []
  patterns:
    - "runtime_checkable Protocol as structural cross-domain seam (exchanges/base.py precedent)"
    - "frozen/slots dataclass snapshot DTO crossing a boundary (D-15: live inside, frozen across)"
    - "flat dict[str, Decimal] per-reference container (order storage _by_id shape)"
key-files:
  created:
    - itrader/core/portfolio_read_model.py
    - tests/unit/core/test_portfolio_read_model.py
  modified:
    - itrader/portfolio_handler/base.py
    - itrader/portfolio_handler/storage/in_memory_storage.py
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_validator.py
    - itrader/strategy_handler/position_sizer/variable_sizer.py
    - itrader/strategy_handler/risk_manager/advanced_risk_manager.py
    - tests/unit/portfolio/test_cash_manager.py
    - tests/unit/portfolio/test_state_storage.py
    - tests/unit/order/test_order_validator.py
decisions:
  - "OQ1 as implemented: Protocol carries exactly SIX members — four locked (available_cash, get_position, reserve, release) + two admission-metadata (exchange_for, open_position_count); positions-dict reads compose from per-ticker get_position; the validator's equity exposure WARNING block was DELETED (D-14 — log-only, never affected a verdict)"
  - "OQ4 as implemented: reservations stored per reference_id at FULL precision (reserve_cash skips the 2dp quantize); release_reservation(reference_id) pops the exact reserved amount, idempotent no-op when absent"
  - "D-13 interpretation: ONE combined Protocol; 'read-only views' satisfied by frozen Decimal PositionView returns + deleted concrete dependency — not by read/write interface segregation"
  - "Validator position cap: getattr(portfolio, 'max_positions', 50) always resolved to 50 on the run path (real Portfolio exposes the limit only under config.limits) — replaced with a local constant 50, verdict-preserving"
  - "PortfolioId casts bridge the 02-05 carry-over (events/entities still declare portfolio_id int while runtime is UUID) so the Protocol keeps its locked PortfolioId signature under mypy --strict"
metrics:
  duration: "~25 min"
  completed: "2026-06-06"
  tasks: 3
  tests: "449 passed (was 435 pre-plan), mypy --strict clean, oracle byte-exact"
---

# Phase 5 Plan 03: Portfolio Read Model Protocol Summary

**One-liner:** Narrow six-member `PortfolioReadModel` Protocol with frozen Decimal `PositionView` kills the order-domain concrete `PortfolioHandler` import (finding #6), and per-reference full-precision cash reservations land on the storage seam ready for 05-06 wiring.

## What Was Built

### Task 1 — `itrader/core/portfolio_read_model.py` (TDD)
- `PositionView`: `@dataclass(frozen=True, slots=True)` carrying exactly `ticker/side/net_quantity/avg_price`, Decimal money (D-15).
- `PortfolioReadModel`: `runtime_checkable` Protocol with the six OQ1 members; module docstring documents D-13..D-17 and the equity exclusion (D-14).
- 7 conformance tests: frozen mutation raises, exact field surface, isinstance pass for a six-method fake, isinstance FAIL for a fake missing `reserve`, Protocol surface locked to exactly six methods.

### Task 2 — Per-reference reservations + handler conformance (TDD)
- Seam (`PortfolioStateStorage`): `add_reservation(reference_id, amount)` / `pop_reservation(reference_id) -> Decimal | None` abstractmethods replace `set_reserved_cash`; in-memory backend holds a flat `dict[str, Decimal]` (order-storage `_by_id` shape); `get_reserved_cash()` returns the sum.
- `CashManager.reserve_cash(amount, description, reference_id) -> None`: stores per-reference at FULL precision (OQ4 — `Decimal("123.45678901")` round-trips exactly), keeps the typed `InsufficientFundsError` against `available_balance` (reserves nothing on failure), keeps the RESERVATION audit entry with `balance_before == balance_after`.
- `CashManager.release_reservation(reference_id) -> None` replaces `release_cash_reservation`: idempotent silent no-op for unknown refs; release audit entry only when a reservation existed.
- `PortfolioHandler` implements the Protocol structurally (D-16 — six plain methods, Protocol not in MRO): `available_cash` → `cash_manager.available_balance`; `get_position` → frozen `PositionView` from the live Position, `None` when flat; `reserve`/`release` → CashManager keyed by `str(order_id)`; `exchange_for`/`open_position_count` → portfolio attributes.

### Task 3 — Consumer retype (D-16/D-17)
- Concrete `PortfolioHandler` import deleted from all five consumers; constructors annotated `PortfolioReadModel` (Optional where the param had a None default).
- Read-site map applied per the plan inventory: `.cash` → `available_cash()` (D-14), `.get_open_position(t).net_quantity` → `get_position(...).net_quantity` with None guard, `.exchange` → `exchange_for()`, `.n_open_positions` → `open_position_count()`, positions membership → `get_position(...) is not None`.
- Validator equity exposure WARNING block (`_check_portfolio_exposure_limits`) DELETED with a D-14 tombstone comment at the call site.
- Validator test mocks converted from portfolio attribute stubs to Protocol method stubs (`available_cash.return_value = Decimal(...)`, real `PositionView` for the sell-order case); all verdict assertions unchanged.

## Value Preservation

Reservations are NOT yet wired to the trade path (plan 05-06), so `available_balance == balance` at every read — `available_cash` is numerically identical to the old `.cash` reads. Verified: full suite 449 green, `poetry run mypy itrader` clean, `tests/integration/test_backtest_oracle.py` byte-exact, `git diff --stat tests/golden/` empty.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `make` targets unusable in worktree (missing gitignored `.env`)**
- **Found during:** Task 1 verification
- **Issue:** `Makefile` does `include .env` at parse time; the worktree has no `.env` (gitignored), so `make typecheck`/`make test` abort before running anything.
- **Fix:** Ran the underlying commands directly (`poetry run mypy itrader`, `poetry run python -m pytest tests/`) — identical to the make targets. A local empty `.env` shim was touched in the worktree (gitignored, never committed).
- **Files modified:** none (committed)

**2. [Rule 3 - Blocking] `tests/unit/portfolio/test_state_storage.py` called deleted `set_reserved_cash`**
- **Found during:** Task 2
- **Issue:** The seam test (not in the plan's file list) exercised the aggregate `set_reserved_cash`, deleted by the per-reference rework.
- **Fix:** Reworked the round-trip test to `add_reservation`/`pop_reservation` (sum + idempotent pop asserted). Also reworked `test_balance_consistency_validation` in test_cash_manager.py (corruption simulated via a negative `add_reservation` through the seam).
- **Files modified:** tests/unit/portfolio/test_state_storage.py, tests/unit/portfolio/test_cash_manager.py
- **Commit:** 07be2f9

**3. [Rule 3 - Blocking] `mypy --strict` rejected int-typed event/entity `portfolio_id` against the locked `PortfolioId` Protocol signature**
- **Found during:** Task 3
- **Issue:** Events (`SignalEvent.portfolio_id: int`) and the Order entity (`PortfolioId | int`) still carry the 02-05 type carry-over; the Protocol is locked to `PortfolioId`.
- **Fix:** `cast(PortfolioId, ...)` bridges at each consumer boundary (one `_portfolio_id(order)` helper in the validator), each with a carry-over comment. Runtime values are already native UUIDs, so the casts are honest.
- **Files modified:** order_manager.py, order_validator.py, variable_sizer.py, advanced_risk_manager.py
- **Commit:** ec02b9b

**4. [Rule 2 - Missing critical] Explicit None-guard in `_resolve_signal_quantity`**
- **Found during:** Task 3
- **Issue:** Retyping `portfolio_handler` to `Optional[PortfolioReadModel]` exposed that sizing dereferenced it unguarded — previously an `AttributeError` swallowed by the upstream try/except into a failure result.
- **Fix:** Explicit typed failure result when the read model is absent. Same verdict, now explicit and mypy-clean.
- **Commit:** ec02b9b

**5. [Rule 1 - Dead code] `_check_risk_limits` unused portfolio lookup dropped**
- **Found during:** Task 3
- **Issue:** The method fetched the portfolio only for a not-found guard that was dead with the real handler (which raises) and read no portfolio state.
- **Fix:** Removed the lookup; the check reads only order fields. Verdict-preserving.
- **Commit:** ec02b9b

## OQ Resolutions (per plan output spec)

- **OQ1:** Six members as locked (four D-13 + `exchange_for` + `open_position_count`). The equity exposure WARNING (order_validator `_check_portfolio_exposure_limits`) is deleted — it fired on every golden BUY at 95% sizing and never affected a verdict; D-14 excludes equity from the order-domain surface.
- **OQ4:** Full-precision reservations — `reserve_cash` deliberately skips `_validate_and_convert_amount`'s 2dp quantize so `release_reservation` returns exactly the reserved amount. Positive-amount validation retained via a non-quantizing check.

## TDD Gate Compliance

- Task 1: RED 85e4d80 (`test`) → GREEN e65647c (`feat`)
- Task 2: RED d494680 (`test`) → GREEN 07be2f9 (`feat`)
- Task 3: non-TDD mechanical retype, ec02b9b (`refactor`)

## Known Stubs

None — no placeholder data or unwired components introduced. The reservation API is intentionally not yet on the trade path; plan 05-06 wires it (documented in plan + code comments).

## Self-Check: PASSED

- itrader/core/portfolio_read_model.py: FOUND
- tests/unit/core/test_portfolio_read_model.py: FOUND
- Commits 85e4d80, e65647c, d494680, 07be2f9, ec02b9b: FOUND
- 449 tests green; mypy --strict clean; oracle byte-exact; golden diff empty
