---
phase: 03-shorts-borrow-carry
plan: 05
subsystem: portfolio_handler
tags: [carry, borrow-interest, determinism, decimal, shorts]
requires: [03-01, 03-02]
provides:
  - "Per-bar short borrow-interest carry accrual (BORROW_INTEREST cash debit)"
  - "Bar-business-time threaded into the per-bar mark hook (determinism seam)"
affects:
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/position/position.py
tech-stack:
  added: []
  patterns:
    - "Decimal end-to-end carry formula with Decimal('365') denominator"
    - "Business-time (bar_event.time) threaded down — no datetime.now on the accrual path"
    - "_universe.instrument(ticker).borrow_rate read mirroring maintenance_margin"
key-files:
  created: []
  modified:
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/cash/cash_manager.py
    - itrader/portfolio_handler/position/position.py
    - tests/unit/portfolio/test_carry.py
    - tests/unit/portfolio/test_cash_manager.py
decisions:
  - "Per-short last_accrual marker stored on Position (_last_accrual_time), seeded from entry_date, advanced to bar_time after each accrual (RESEARCH Open Q1 — per-position inside the mark loop)"
  - "Legacy mark-only callers (no bar_time/universe) keep wall-clock mark + accrue nothing — default-off no-op preserves byte-exactness"
metrics:
  duration: ~25m
  completed: 2026-06-15
---

# Phase 3 Plan 05: Borrow-Carry Accrual Summary

Per-bar short borrow-interest carry — each BAR every open short debits
`days × close × |size| × rate / Decimal("365")` (Decimal end-to-end) from realized
cash via a first-class `BORROW_INTEREST` `CashOperation`, with the days basis and op
timestamp derived from the bar's **business time** (never wall clock), keeping the
SMA_MACD oracle byte-exact under default-off (`borrow_rate=0` / no open shorts).

## What Was Built

**Task 1 — thread bar business time + Universe into the mark hook (CARRY-01/D-02/D-04):**
- `PortfolioHandler.update_portfolios_market_value` now captures `bar_event.time` and
  threads it plus the injected `self._universe` down into
  `Portfolio.update_market_value_of_portfolio(prices, bar_time, universe)`.
- `Portfolio.update_market_value_of_portfolio` marks positions at the bar's business
  `time` (was `datetime.now(UTC)`); legacy mark-only callers (no `bar_time`) keep the
  wall-clock fallback and accrue no carry.

**Task 2 — accrue per-bar short carry as a BORROW_INTEREST realized-cash debit (CARRY-01/D-03/D-08):**
- New `Portfolio._accrue_short_carry(bar_time, universe)` iterates open shorts,
  reads `universe.instrument(ticker).borrow_rate` (mirroring `maintenance_margin`),
  computes the Decimal carry over the `(bar_time − last_accrual)` day gap, and debits
  it once per short per bar.
- New `CashManager.accrue_borrow_interest(amount, reference_id, description, timestamp)`
  books a REAL outflow via `_create_operation` with `CashOperationType.BORROW_INTEREST`,
  full precision, caller-supplied bar timestamp; a non-positive amount is a silent no-op.
- `Position._last_accrual_time` accrual marker declared (seeded from `entry_date`,
  advanced to `bar_time` after each debit). Carry NEVER folds into
  `Position.realised_pnl` (D-08 — clean trade PnL; carry nets at cash/equity).

## Tests

- `tests/unit/portfolio/test_carry.py` — un-stubbed `days_basis` (1-day and 3-day gaps),
  bar-business-time op timestamp, determinism double-run (carry amount + timestamp + balance
  byte-identical).
- `tests/unit/portfolio/test_cash_manager.py` — un-stubbed `borrow_interest` /
  `borrow_interest_op`: exact-amount debit, `BORROW_INTEREST` op record with
  balance_before/after + bar timestamp, zero-amount no-op.

## Verification

- `poetry run pytest tests/unit/portfolio -k "days_basis or borrow_interest" ` — 9 passed.
- Full portfolio unit suite — 241 passed, 5 skipped (03-04/03-06 stubs, not ours).
- `make test-integration` equivalent (`pytest -m integration`) — 16 passed; the backtest
  oracle byte-exact golden equity curve held (trade count 134; default-off no-op path).
- `mypy --strict` clean on all four modified source files.
- No new `datetime.now` on the accrual path (the accrual reads only `bar_time`);
  no `Decimal(float)`; `reporting/cash_operations.py` unchanged (enum-agnostic serializer).

## Deviations from Plan

None — plan executed exactly as written. The planner left the `last_accrual` placement
and per-position vs per-portfolio loop to discretion; implemented per-position inside the
mark loop (RESEARCH Open Q1 recommendation), storing `_last_accrual_time` on `Position`.

## Self-Check: PASSED

- itrader/portfolio_handler/portfolio_handler.py — FOUND (threads bar_time + universe)
- itrader/portfolio_handler/portfolio.py — FOUND (_accrue_short_carry + bar-time mark)
- itrader/portfolio_handler/cash/cash_manager.py — FOUND (accrue_borrow_interest)
- itrader/portfolio_handler/position/position.py — FOUND (_last_accrual_time)
- Commit f2644de (test RED) — FOUND
- Commit eeef0bb (feat GREEN) — FOUND
