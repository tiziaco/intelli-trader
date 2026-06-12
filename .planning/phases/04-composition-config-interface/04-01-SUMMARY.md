---
phase: 04-composition-config-interface
plan: 01
subsystem: composition-config-interface
tags: [composition, config, protocol, pydantic, spec, byte-exact, interface-first]
requires: []
provides:
  - "CommissionEstimator runtime_checkable Protocol (core/, D-15)"
  - "OrderConfig Pydantic model (config/, D-05)"
  - "SystemSpec + PortfolioSpec + Action frozen spec (trading_system/, D-01/D-02)"
affects:
  - "Wave 2 (04-02): FeeModelCommissionEstimator adapter implements CommissionEstimator + appends D-15 late-binding test"
  - "Wave 2: OrderManager threads OrderConfig + retypes commission_estimator to the Protocol"
  - "Wave 4: e2e _build_and_run collapses onto build_backtest_system(SystemSpec)"
tech-stack:
  added: []
  patterns:
    - "read-model-seam Protocol (runtime_checkable, zero itrader deps) mirrored from core/portfolio_read_model.py"
    - "thin Pydantic config model (ConfigDict(extra='forbid') + default()) from config/exchange.py"
    - "frozen declarative dataclass spec promoted from tests/e2e/scenario_spec.py"
key-files:
  created:
    - itrader/core/commission_estimator.py
    - itrader/config/order.py
    - itrader/trading_system/system_spec.py
    - tests/unit/core/test_commission_estimator.py
    - tests/unit/config/test_order_config.py
  modified: []
decisions:
  - "D-15: CommissionEstimator is a runtime_checkable Protocol in core/ with the primitive (Decimal, Decimal) -> Decimal __call__; zero itrader imports."
  - "D-05: OrderConfig folds market_execution; pydantic v2 coerces the string 'immediate' to the MarketExecution.IMMEDIATE member with NO custom validator (A1 confirmed true) — use_enum_values deliberately NOT used (would store the str)."
  - "D-01/D-02: SystemSpec is run-mode-agnostic (NOT BacktestSpec); fields match ScenarioSpec exactly; actions kept (+ Action) for a clean Wave-4 single-spec collapse."
metrics:
  duration: ~12 min
  completed: 2026-06-12
  tasks: 3
  files: 5
---

# Phase 4 Plan 01: Foundational Composition Primitives Summary

Landed the three standalone COMP-01 contracts — the `CommissionEstimator` Protocol seam (D-15), the `OrderConfig` Pydantic model (D-05), and the run-mode-agnostic `SystemSpec` declarative spec (D-01/D-02) — as brand-new, byte-exact-inert files (zero run-path import) that Wave 2 consumes.

## What Was Built

- **`itrader/core/commission_estimator.py`** (4 spaces) — a `@runtime_checkable` `CommissionEstimator(Protocol)` with a single `__call__(self, quantity: Decimal, price: Decimal) -> Decimal`. Imports only `decimal` + `typing` — zero `itrader` deps (honors core's dependency rule), mirroring `core/portfolio_read_model.py`. `__all__ = ["CommissionEstimator"]`. Structured so the Wave-2 D-15 late-binding test appends cleanly.
- **`itrader/config/order.py`** (4 spaces) — `OrderConfig(BaseModel)` with `ConfigDict(extra="forbid")`, `market_execution: MarketExecution = MarketExecution.IMMEDIATE`, and `default() -> OrderConfig`. Imports `MarketExecution` from `itrader.core.enums` (config-enum exception — NOT relocated). No validator needed: pydantic v2 coerces the `.value` string to the enum member by default (A1 confirmed).
- **`itrader/trading_system/system_spec.py`** (TABS) — frozen `SystemSpec`, `PortfolioSpec`, and `Action` promoted field-for-field from `tests/e2e/scenario_spec.py`, re-indented 4-space → tabs. Named `SystemSpec` (run-mode-agnostic, D-02); fields match the e2e harness by name; `actions` kept for a single-spec Wave-4 collapse. Not wired into any run path.
- **Tests** — `tests/unit/core/test_commission_estimator.py` (4 structural conformance tests, append-ready) and `tests/unit/config/test_order_config.py` (6 tests: coercion equivalence Trap 5, default, enum pass-through, `extra="forbid"`).

## Commits

- `b2bba53` feat(04-01): add CommissionEstimator read-model Protocol (D-15)
- `62dd1be` feat(04-01): add OrderConfig Pydantic model (D-05)
- `cbfbf03` feat(04-01): promote SystemSpec frozen spec (D-01/D-02)

## Verification

- `poetry run pytest tests/unit/core/test_commission_estimator.py tests/unit/config/test_order_config.py -q` → **10 passed**.
- `poetry run mypy itrader` → **Success: no issues found in 179 source files** (176 → 179, three new files, no regressions).
- Indentation verified per package: commission_estimator.py + order.py have zero tab chars; system_spec.py has zero 4-space body lines.
- CommissionEstimator: zero `from itrader` / `import itrader` statements (grep confirmed; the 3 raw `itrader` substring matches are docstring prose, not imports).
- No run-path file touched → BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) and e2e 58/58 are untouched by this plan (Wave 4 runs the gate).

## Deviations from Plan

None — plan executed exactly as written. Assumption A1 (pydantic v2 coerces a plain `Enum` from its string value with no extra validator) held, so no field validator was added to `OrderConfig` (the plan's contingent fallback was not triggered).

## Threat Surface

The two registered tampering threats are mitigated and tested:
- **T-04-01** (mass-assignment via unexpected keys) — `ConfigDict(extra="forbid")`, covered by `test_unknown_key_raises_validation_error`.
- **T-04-02** (market_execution type confusion) — pydantic enum validation, covered by `test_string_immediate_coerces_to_enum_member`.

No new security surface introduced (no network, no auth, no untrusted input — developer-authored config dicts only).

## Known Stubs

None. The `CommissionEstimator` Protocol's D-15 *late-binding* correctness coverage is intentionally deferred to Wave 2 (04-02 Task 2 appends the test once the `FeeModelCommissionEstimator` adapter exists) — this is documented sequencing per the plan, not a stub. The Wave-1 structural conformance test is complete on its own terms.

## Self-Check: PASSED
- itrader/core/commission_estimator.py — FOUND
- itrader/config/order.py — FOUND
- itrader/trading_system/system_spec.py — FOUND
- tests/unit/core/test_commission_estimator.py — FOUND
- tests/unit/config/test_order_config.py — FOUND
- commit b2bba53 — FOUND
- commit 62dd1be — FOUND
- commit cbfbf03 — FOUND
