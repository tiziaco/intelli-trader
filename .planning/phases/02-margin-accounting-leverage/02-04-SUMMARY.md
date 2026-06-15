---
phase: 02-margin-accounting-leverage
plan: 04
subsystem: portfolio
tags: [margin, leverage, locked-margin, lock-and-settle, decimal, cash-manager, position]

# Dependency graph
requires:
  - phase: 02-01
    provides: "SignalEvent.leverage (D-03) + TradingRules.max_leverage/enable_margin defaulted Decimal('1')/False inert fields"
provides:
  - "CashManager position-keyed locked_margin container (lock_margin/release_margin/locked_margin_total) distinct from order-keyed reservation (D-10/Pitfall 2)"
  - "available_balance = balance − reserved − locked_margin (single buying-power authority; spot byte-exact, Pitfall 6)"
  - "Position.leverage (one effective leverage set at open, D-06) + Position.aggregate_notional (direction-agnostic margin basis, D-11)"
  - "PositionManager scale-in leverage clamp (cash-agnostic, OQ2)"
  - "Portfolio.process_transaction enable_margin lock-and-settle branch — byte-exact site #2 (D-09/D-11)"
  - "PortfolioStateStorage seam: get/add/pop_locked_margin on ABC + in-memory backend"
affects: [02-05, 02-06, shorts, liquidation, levered-kelly, xval]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "enable_margin gate: spot arm is the existing expression operand-for-operand; margin arm is the new lock-and-settle path; spot NEVER divides by leverage (Pitfall 4)"
    - "Lock-and-settle cash lifecycle driven from Portfolio.process_transaction (holds Position + CashManager); PositionManager stays cash-agnostic (OQ2)"
    - "Position-keyed locked_margin container mirrors order-keyed reserve_cash but with a position-lifetime lifecycle"

key-files:
  created: []
  modified:
    - "itrader/portfolio_handler/cash/cash_manager.py"
    - "itrader/portfolio_handler/position/position.py"
    - "itrader/portfolio_handler/position/position_manager.py"
    - "itrader/portfolio_handler/portfolio.py"
    - "itrader/portfolio_handler/base.py"
    - "itrader/portfolio_handler/storage/in_memory_storage.py"

key-decisions:
  - "Margin close cash settlement = realised_increment + p × prior_entry_commission (re-credits the closed fraction's pre-debited open commission so the round-trip cash delta equals the position's realised_pnl exactly — open commission never double-counted)"
  - "aggregate_notional = |net_quantity| × avg_price (commission-inflated avg_price is the D-11 basis per plan; direction-agnostic positive magnitude mirroring abs(market_value))"
  - "Lock basis always uses position.leverage (D-06 authoritative) not transaction.leverage — a scale-in's differing signal leverage is clamped"

patterns-established:
  - "Position-keyed locked_margin lock/release at full precision (release == lock exactly, no quantize drift)"
  - "enable_margin settlement branch with the spot arm extracted UNCHANGED into _process_transaction_spot (byte-exact regression-locked)"

requirements-completed: [MARGIN-01]

# Metrics
duration: 35min
completed: 2026-06-15
---

# Phase 2 Plan 04: Lock-and-Settle Margin Cash Model Summary

**Position-keyed locked-margin lock-and-settle model gated by `enable_margin` (D-09/D-10/D-11): opening a levered position debits ONLY commission and locks `aggregate_notional / L`, closing settles realized PnL pro-rata and releases the lock — with the spot arm byte-exact (SMA_MACD 134 / 46189.87730727451 held).**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-15T11:32Z
- **Completed:** 2026-06-15T11:42Z
- **Tasks:** 3 (all TDD)
- **Files modified:** 6 source + 3 test files

## Accomplishments

- Added a position-keyed `locked_margin` container to `CashManager` (`lock_margin`/`release_margin`/`locked_margin_total`), a DISTINCT lifecycle from the order-keyed reservation; `available_balance` now subtracts it (`balance − reserved − locked_margin`), byte-exact in spot mode via a clean `Decimal("0")` empty default.
- Gave `Position` one effective leverage set at open (D-06, default `Decimal("1")`) + an `aggregate_notional` margin basis; `PositionManager` clamps a scale-in's differing signal leverage while staying cash-agnostic (OQ2).
- Branched `Portfolio.process_transaction` on `enable_margin` (byte-exact site #2): the spot arm extracted UNCHANGED into `_process_transaction_spot`; the margin arm (`_process_transaction_margin`) implements open/scale-in/partial-close/full-close lock-and-settle.
- SMA_MACD oracle byte-exact (134 / 46189.87730727451); `mypy --strict` clean (185 files); 237 portfolio+integration tests green.

## Task Commits

Each task was committed atomically (TDD: test → feat):

1. **Task 1: position-keyed locked_margin in CashManager (D-10/Pitfall 6)** — `dc591c8` (test) → `99883b0` (feat)
2. **Task 2: one-leverage-per-position + aggregate_notional (D-06/D-11)** — `13b5772` (test) → `1b8e642` (feat)
3. **Task 3: enable_margin lock-and-settle branch (D-09/D-11)** — `5dced68` (test) → `a82ed87` (feat) → `9d1d6c7` (test correction)

## Files Created/Modified

- `itrader/portfolio_handler/cash/cash_manager.py` — `lock_margin`/`release_margin`/`locked_margin_total`; `available_balance` subtracts locked margin (4-space).
- `itrader/portfolio_handler/base.py` — `get/add/pop_locked_margin` on the `PortfolioStateStorage` ABC (4-space).
- `itrader/portfolio_handler/storage/in_memory_storage.py` — `_locked_margin` dict container + accessors; clean `Decimal("0")` when empty (4-space).
- `itrader/portfolio_handler/position/position.py` — `leverage` attribute (set at open via `to_money`, default `Decimal("1")`) + `aggregate_notional` property (TABS).
- `itrader/portfolio_handler/position/position_manager.py` — scale-in leverage clamp (documented D-06; cash-agnostic) (4-space).
- `itrader/portfolio_handler/portfolio.py` — `enable_margin` gate; `_process_transaction_spot` (byte-exact) + `_process_transaction_margin` (lock-and-settle) (TABS).

## Lock-and-Settle Cash Model (the load-bearing settlement math)

The margin arm classifies four transitions by comparing pre-mutation position state against the result:

- **OPEN** (no prior position): `lock_margin(notional/L)`, cash delta = `−commission` (Pitfall 3 — never the notional, T-02-11).
- **SCALE-IN** (same-direction add): `release_margin` then re-`lock_margin(new_aggregate_notional/L)`; cash delta = `−commission`.
- **PARTIAL CLOSE** (opposite-direction reduce, still open, fraction `p = closed_qty/prior_qty`): release the full lock, re-lock the remaining `aggregate_notional/L`; cash delta = `realised_increment + p × prior_entry_commission`.
- **FULL CLOSE**: release the whole lock; cash delta = `realised_increment + prior_entry_commission`.

The `+ p × prior_entry_commission` term re-credits the closed fraction's open commission that was already pre-debited at open, so `position.realised_pnl` (which nets both commissions) is not double-counted — **the round-trip cash delta equals the position's realized PnL exactly** (proven by `test_locked_margin_full_close_with_commission_round_trip`). The lock basis always uses `position.leverage` (D-06 authoritative), never the transaction's (clamped) leverage. `assert_funds_invariant` is fed the commission-only delta on an increase (OQ3).

## Deviations from Plan

None — plan executed exactly as written. No Rule 1–4 deviations. All three tasks landed on their declared files with the prescribed indentation (cash_manager/position_manager 4-space; portfolio/position TABS) and the enable_margin gate at exactly the planned settlement site.

One **discretionary design call** within plan scope: the close-settlement cash formula (`realised_increment + p × prior_entry_commission`) was not specified to a closed form by the plan/RESEARCH (the leveraged-long e2e is parked for P4/XVAL-01). The chosen formula is the minimal one that makes the round-trip cash delta equal `position.realised_pnl` exactly, and is hand-verified in the unit tests.

## Deferred Issues (out of scope)

- **DEF-02-03-A** (pre-existing, re-confirmed): `tests/unit/core/test_sizing.py::test_sizing_policy_union_members` asserts the OLD 3-member `SizingPolicy` union but Plan 02-02 (`e2afb00`) grew it with `LeveredFraction`. The stale assertion fails. This is in `core/sizing.py`'s test (Plan 02-02 domain) with **zero overlap** with Plan 02-04 (portfolio cash/position internals) — left unfixed per the scope boundary; tracked in `deferred-items.md`.

## Threat Surface

All four mitigate-disposition threats in the plan's threat register are covered:

- **T-02-11** (margin double-debit): the margin arm debits ONLY commission on open; spot is the only path that debits `net_delta`. Asserted by `test_locked_margin_open_debits_only_commission`.
- **T-02-12** (locked margin desync): position-keyed lock driven from `process_transaction` across all four transitions; release == lock at full precision.
- **T-02-13** (spot golden drift): empty container is a clean `Decimal("0")`; `available_balance` byte-exact in spot mode; oracle held.
- **T-02-14** (float-repr artifact): Decimal end-to-end; `to_money` string-path entry for leverage; full-precision lock/release and PnL settlement.

No new security surface introduced (engine-internal Decimals; no network/auth/schema).

## Verification

- `poetry run pytest tests/unit/portfolio/test_cash_manager.py -k locked_margin -x` → green.
- `poetry run pytest tests/unit/portfolio/test_position_manager.py -k "scale_in_margin or one_leverage" -x` → green.
- `poetry run pytest tests/unit/portfolio -k "partial_close_margin or scale_in_margin or locked_margin" -x` → 11 passed.
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed (SMA_MACD 134 / `46189.87730727451` byte-exact).
- `poetry run pytest tests/unit/portfolio tests/integration -q` → 237 passed, 3 skipped (Plan 05 Wave-0 stubs).
- `poetry run mypy itrader` → Success, no issues in 185 source files.
- Indentation intact: portfolio.py/position.py TABS; cash_manager.py/position_manager.py 4-space.

## Self-Check: PASSED

All created/modified files exist on disk and all 7 task commits (`dc591c8`, `99883b0`, `13b5772`, `1b8e642`, `5dced68`, `a82ed87`, `9d1d6c7`) are present in git history.
