---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 01
subsystem: portfolio
tags: [account, abc, protocol, connectors, venue, livconnector, decimal]

# Dependency graph
requires:
  - phase: none
    provides: net-new interface scaffold (no upstream dependency — wave 1, depends_on [])
provides:
  - Account ABC pinning the balance / available / reserve(order_id, amount) / release(order_id) contract (D-01/D-02/D-05)
  - VenueAccount interface-only stub leaf of the Account ABC (D-11, Phase 5 deferral)
  - LiveConnector runtime_checkable Protocol marker naming data/order/lifecycle arm boundaries (D-10)
  - new top-level connectors/ package (D-13)
  - D-04 resolution in writing — SMA_MACD oracle runs the SPOT path
affects: [01-02, 01-03, phase-2-okx-connector, phase-4-paper-path, phase-5-reconciliation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ABC on the cash-vs-margin inheritance axis (fee_model/base.py analog)"
    - "runtime_checkable Protocol marker for the swap-a-fake connector seam (exchanges/base.py analog)"
    - "account/ as the fifth peer delegate under portfolio_handler/ (queue-free manager pattern)"

key-files:
  created:
    - itrader/portfolio_handler/account/__init__.py
    - itrader/portfolio_handler/account/base.py
    - itrader/portfolio_handler/account/venue.py
    - itrader/connectors/__init__.py
    - itrader/connectors/base.py
  modified: []

key-decisions:
  - "D-04 resolved: SMA_MACD oracle runs the SPOT settlement path — SimulatedCashAccount is the verbatim-critical leaf for plan 01-02"
  - "Account ABC drops portfolio_id from reserve/release (D-05, LX-04 1:1)"
  - "LiveConnector lives in a new top-level connectors/ package, not under portfolio_handler/ (D-13)"

patterns-established:
  - "Account family = ABC inheritance (cash→margin superset); connector/venue = structural Protocol"
  - "Interface-first ordering: contracts defined before implementation (01-02) and consumers (01-03)"

requirements-completed: [ACCT-01, ACCT-06]

# Metrics
duration: 3min
completed: 2026-06-30
---

# Phase 1 Plan 01: Account Abstraction Interface Scaffold Summary

**Net-new Account ABC + VenueAccount stub + LiveConnector Protocol scaffold with the D-04 oracle path pinned to SPOT — zero money-math movement, zero byte-exact risk.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-06-30T20:29:43Z
- **Completed:** 2026-06-30T20:32:07Z
- **Tasks:** 3
- **Files modified:** 5 (all created)

## Accomplishments
- Pinned D-04 in writing: the SMA_MACD byte-exact oracle runs the **SPOT** path, naming `SimulatedCashAccount` as the verbatim-critical leaf for plan 01-02.
- Created the `Account` ABC (D-01/D-02) declaring the `balance` / `available` / `reserve(order_id, amount)` / `release(order_id)` contract with `portfolio_id` dropped (D-05, LX-04 1:1).
- Created the `VenueAccount` interface-only stub leaf (D-11) with `NotImplementedError` stubs carrying Phase 5 (RECON-01) deferral docstrings.
- Created the `LiveConnector` `runtime_checkable` Protocol marker (D-10) in a new top-level `connectors/` package (D-13), naming the data / order / lifecycle arm boundaries with `...` bodies.
- `mypy --strict` clean on both new packages; no float-for-money; all files 4-space.

## D-04 resolution

**Finding: the SMA_MACD byte-exact oracle runs the SPOT settlement path.** The
`Portfolio._process_transaction_spot` leaf is on the byte-exact hot path, so
`SimulatedCashAccount` is the **verbatim-critical leaf** for plan 01-02 (must be
byte-for-byte `CashManager` code-motion). `SimulatedMarginAccount` and the
margin/liquidation math are **dark-but-must-stay-verbatim** (mypy-clean, byte-for-byte
moved, but not exercised by the oracle).

**Config evidence:**
- `scripts/run_backtest.py` (the pinned oracle run path, lines 80-95): the strategy is
  constructed with `direction=TradingDirection.LONG_ONLY`,
  `sizing_policy=FractionOfCash(Decimal("0.95"))`, `allow_increase=False`; the portfolio
  is added via `add_portfolio(user_id=1, name="oracle_pf", exchange="csv", cash=10_000)`
  with **no `portfolio_config`** argument — so the portfolio uses the default
  `PortfolioConfig`.
- `itrader/config/portfolio.py` `TradingRules` (lines 71-72): `allow_short_selling: bool = False`
  and `enable_margin: bool = False` by default. With no override, the oracle portfolio runs
  with margin disabled → the `enable_margin` branch (today selecting `_process_transaction_spot`
  vs `_process_transaction_margin`) takes the **spot** arm.

**Consequence for plans 01-02 / 01-03:** the D-03 "runtime branch → leaf selection at
wiring" maps the default `enable_margin=False` to constructing a `SimulatedCashAccount`.
That spot leaf is the byte-exact hot path; the margin leaf must still be moved verbatim
and stay mypy-clean but is not gated by the oracle numbers.

## Task Commits

Each task was committed atomically:

1. **Task 1: Resolve D-04 — pin oracle spot-vs-margin in writing** - no source edit (recorded in this SUMMARY; read-only determination)
2. **Task 2: Create Account ABC + account/ barrel + VenueAccount stub leaf** - `546aab1` (feat)
3. **Task 3: Create connectors/ package + LiveConnector Protocol marker** - `8cf43cb` (feat)

## Files Created/Modified
- `itrader/portfolio_handler/account/base.py` - `Account(ABC)` — cash-vs-margin inheritance-axis contract (balance/available/reserve/release), Decimal end-to-end
- `itrader/portfolio_handler/account/venue.py` - `VenueAccount(Account)` — interface-only stub leaf, Phase 5 (RECON-01) deferral
- `itrader/portfolio_handler/account/__init__.py` - barrel exporting `Account`, `VenueAccount` (01-02 extends with `Simulated*` leaves)
- `itrader/connectors/base.py` - `LiveConnector` `@runtime_checkable Protocol` marker (data/order/lifecycle arms)
- `itrader/connectors/__init__.py` - barrel exporting `LiveConnector`

## Decisions Made
None beyond the plan — followed plan as specified. D-04 resolved to SPOT as anticipated by the plan's primary branch (the oracle uses the default `enable_margin=False`).

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- The plan's `read_first` cited `itrader/order_handler/storage/postgresql_storage.py` as the `NotImplementedError` stub convention analog; that file no longer exists (replaced by `sql_storage.py`). Mirrored the equivalent `raise NotImplementedError(...)` convention used across the repo (`fee_model/base.py`, `execution_handler/base.py`, `strategy_handler/base.py`) instead. No impact on output.

## Verification

- `poetry run python -c "import itrader.portfolio_handler.account, itrader.connectors"` — exits 0
- `poetry run mypy --strict itrader/portfolio_handler/account itrader/connectors` — Success: no issues found in 5 source files
- No float-for-money: `grep -rn "float(" itrader/portfolio_handler/account itrader/connectors` returns nothing
- Indentation: no tabs in any new file (all 4-space, matching the newer-module convention)
- Task 2 smoke: `Account` subclasses `abc.ABC`, `VenueAccount` subclasses `Account` — ok
- Task 3 smoke: `LiveConnector._is_runtime_protocol` truthy + `isinstance(object(), LiveConnector)` does not raise — ok
- **Oracle byte-exact gate:** structurally untouched — this plan adds only net-new, unimported interface files; no consumer wired, no money-math moved, no hot-path import added.

## Self-Check: PASSED

- Files: all 5 created files FOUND on disk
- Commits: `546aab1`, `8cf43cb` FOUND in git log

## Next Phase Readiness
- Plan 01-02 receives the `Account` ABC contract and the named verbatim-critical leaf (`SimulatedCashAccount`, SPOT) directly from this SUMMARY — ready to code-motion `CashManager` → `account/simulated.py`.
- Plan 01-03 receives the `LiveConnector` Protocol and `VenueAccount` stub for downstream wiring.
- No blockers.

---
*Phase: 01-account-abstraction-portfolio-handler-refactor*
*Completed: 2026-06-30*
