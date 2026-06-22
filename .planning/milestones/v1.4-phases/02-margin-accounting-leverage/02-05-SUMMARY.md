---
phase: 02-margin-accounting-leverage
plan: 05
subsystem: portfolio-handler
tags: [margin, read-model, leverage, MARGIN-03, LEV-01, D-13, D-15, D-16]
requires:
  - "Plan 02-03 — order-domain Universe injection seam (set_universe pattern, Trap-4 ordering)"
  - "Plan 02-04 — positions carry leverage / aggregate notional; CashManager lock-and-settle"
  - "Phase 1 — Instrument.maintenance_margin_rate / max_leverage (inert, Decimal-typed)"
provides:
  - "PortfolioReadModel.maintenance_margin(portfolio_id) -> Decimal (compute-on-demand, D-13/MARGIN-03)"
  - "PortfolioReadModel.margin_ratio(portfolio_id) -> Decimal (D-12 mark-to-market, D-16 honest-when-breached)"
  - "PortfolioHandler.set_universe — Universe injection seam into the portfolio domain"
  - "max_leverage participates in update_config unchanged (D-15)"
affects:
  - "Deferred N+4 UI/live layer (reads margin health via these accessors)"
  - "Phase 4 liquidation (margin_ratio < 1 is the breach input, D-16)"
tech-stack:
  added: []
  patterns:
    - "mirror-an-existing-sibling: maintenance_margin/margin_ratio ↔ total_equity(); set_universe ↔ order-domain/exchange set_universe"
    - "compute-on-demand read-model (no stored Position field, D-13a)"
key-files:
  created: []
  modified:
    - "itrader/core/portfolio_read_model.py (Protocol members)"
    - "itrader/portfolio_handler/portfolio_handler.py (impl + Universe seam)"
    - "itrader/trading_system/backtest_runner.py (set_universe wiring)"
    - "itrader/trading_system/live_trading_system.py (set_universe wiring)"
    - "tests/unit/portfolio/test_portfolio_handler.py (5 margin tests)"
    - "tests/unit/portfolio/test_update_config.py (3 max_leverage tests)"
    - "tests/unit/core/test_portfolio_read_model.py (conformance reconcile)"
decisions:
  - "margin_ratio zero-maintenance sentinel = Decimal('0') (no open positions -> no margin required -> no div0)"
metrics:
  duration: 8
  completed: 2026-06-15
---

# Phase 2 Plan 05: Maintenance Margin / Margin Ratio Read-Model & max_leverage Reconfig Summary

Exposed `maintenance_margin` and `margin_ratio` as compute-on-demand `PortfolioReadModel` accessors (D-13/MARGIN-03), wired the `Universe` into `PortfolioHandler`, and confirmed `max_leverage` rides the uniform `update_config` seam unchanged (D-15) — SMA_MACD spot run held byte-exact at 134 / 46189.87730727451.

## What Was Built

**Task 1 — Protocol members (`core/portfolio_read_model.py`, 4-space).** Added `maintenance_margin(self, portfolio_id) -> Decimal` and `margin_ratio(self, portfolio_id) -> Decimal` mirroring `total_equity`'s signature/docstring shape. Both documented as compute-on-demand (NOT stored Position fields, D-13a) and honest-when-breached (no clamp, D-16). Commit `24a6dd4`.

**Task 2 — impl + Universe seam (TDD).**
- `PortfolioHandler.set_universe(universe)` + `self._universe` (default None at construction), mirroring the Plan 02-03 order-domain/exchange seam. Commit `6978ca1`.
- `maintenance_margin` iterates `portfolio.position_manager.get_all_positions()`, resolves each ticker's `Instrument` via `self._universe.instrument(ticker)`, and accumulates `maintenance_margin_rate × |net_quantity| × current_price` as Decimal (full precision — `net_quantity` is already `|size|` Decimal, `current_price` is Decimal, the rate is Decimal; never the float `Portfolio.total_equity` property, Pitfall 8). No open positions → `Decimal("0")`.
- `margin_ratio` = `total_equity() / maintenance_margin` (D-12 mark-to-market). Zero-maintenance returns the deterministic `Decimal("0")` sentinel (no div0). Breached equity returns a ratio < 1, unclamped (D-16).
- `portfolio_handler.set_universe(universe)` wired in `backtest_runner.py` and `live_trading_system.py` at the Trap-4 point right after the Universe is built (TABS, preserved alongside the Plan 02-03 order/exchange injections).
- `max_leverage` is a `TradingRules` field, so `deep_merge → model_validate → atomic-swap` already carries it — no code change; the order domain reads it at construction time off `config_data.trading_rules.max_leverage`, so no post-swap cache re-derive was needed.

## Tests

- 5 new margin tests in `tests/unit/portfolio/test_portfolio_handler.py` (Σ formula == 3 over {AAA: 2@100, mmr 0.01; BBB: 1@50, mmr 0.02}; zero with no positions; ratio == equity/maintenance; zero sentinel; honest-when-breached < 1).
- 3 new max_leverage tests in `tests/unit/portfolio/test_update_config.py` (rides update_config; ge=1 floor rejects 0; sibling-field preservation).
- The 3 Wave-0 skipped stubs (`test_maintenance_margin_wave0_stub`, `test_margin_ratio_wave0_stub`, `test_max_leverage_wave0_stub`) are now replaced by real green tests.

## Verification

- `poetry run pytest tests/unit/portfolio -x` → 229 passed.
- `poetry run pytest tests/unit` → 992 passed.
- `poetry run mypy itrader` → clean (185 source files).
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → SMA_MACD **134 / 46189.87730727451 byte-exact** (accessors query-only, unread on the golden path; update_config never called mid-run).
- Indentation intact: read-model + handler 4-space; runners tabs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reconciled PortfolioReadModel conformance tests with the 10-member surface**
- **Found during:** Task 2 (post-implementation full-unit-suite run)
- **Issue:** `tests/unit/core/test_portfolio_read_model.py` pins the Protocol's EXACT member set ("exactly eight methods") and conformance doubles (`_ConformingFake`, `_MissingReserveFake`). The `runtime_checkable` Protocol grew by two members in Task 1, breaking `test_protocol_declares_exactly_eight_methods` and `test_protocol_is_runtime_checkable_and_fake_conforms`.
- **Fix:** Added `maintenance_margin`/`margin_ratio` to both fakes; renamed/updated the count assertion to "exactly ten methods" with the two new names. Directly caused by this plan's Protocol change (in-scope).
- **Files modified:** `tests/unit/core/test_portfolio_read_model.py`
- **Commit:** `c5a1268`

## Threat Surface

No new threat surface beyond the plan's `<threat_model>`. The mitigations landed as designed:
- T-02-15 (stored-field drift) → compute-on-demand, no stored Position field.
- T-02-16 (clamped breach) → no clamp in `margin_ratio`; honest sub-1 reading.
- T-02-17 (float narrowing) → Decimal end-to-end (`net_quantity`/`current_price`/`maintenance_margin_rate` all Decimal; total_equity Decimal-native).
- T-02-18 (reconfig bypass) → `max_leverage` rides `update_config` validation (ge=1 floor enforced).

## Commits

- `24a6dd4` — feat(02-05): add maintenance_margin / margin_ratio Protocol members
- `02d57cf` — test(02-05): add failing tests (RED)
- `6978ca1` — feat(02-05): implement + wire Universe into PortfolioHandler (GREEN)
- `c5a1268` — test(02-05): reconcile PortfolioReadModel conformance tests

## Self-Check: PASSED

All created/modified files exist; all 4 commits present in git history.
