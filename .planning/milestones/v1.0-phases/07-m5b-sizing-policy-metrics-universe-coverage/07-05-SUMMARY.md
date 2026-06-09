---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 05
subsystem: order-sizing
tags: [sizing-policy, resolver-wiring, audited-rejection, d-06, d-04, oracle-inert, byte-exact]
requires:
  - "07-01 (SizingResolver, SizingPolicy vocabulary, PortfolioReadModel.total_equity)"
  - "07-04 (typed SignalEvent fields: sizing_policy/direction/exit_fraction)"
provides:
  - "OrderManager._resolve_signal_quantity dispatches on signal.sizing_policy via the SizingResolver — the hardcoded Decimal('0.95') M1 seam is gone (#24/#31/KB11 structural span closed)"
  - "D-06 audited sizing rejections: _reject_unsized_signal stores the entity PENDING→REJECTED with triggered_by='sizing_policy' and a reason naming the policy"
  - "order_validator: non-positive quantity is a hard ERROR (INVALID_QUANTITY) — the ZERO_QUANTITY_TRANSITION bypass is dead (D-04)"
  - "strategy_handler/{position_sizer,risk_manager,sltp_models} deleted (381 LOC, zero importers; the cash<30 floor dies with risk_manager)"
affects:
  - 07-06 (SLTP mechanics — last inert plan)
  - 07-07/07-08 (result-changing admission rules build on the resolver-wired seam)
tech-stack:
  added: []
  patterns:
    - "Audited rejected-at-admission entity (Pitfall 5 option (a)): unsized quantity-0 entity stored REJECTED before validation runs"
key-files:
  created: []
  modified:
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_validator.py
    - itrader/core/portfolio_read_model.py
    - tests/unit/order/test_on_signal.py
    - tests/unit/order/test_order_validator.py
  deleted:
    - itrader/strategy_handler/position_sizer/ (4 files)
    - itrader/strategy_handler/risk_manager/ (2 files)
    - itrader/strategy_handler/sltp_models/ (2 files)
decisions:
  - "Pitfall 5 option (a) implemented as _reject_unsized_signal: the rejected entity is built via the existing _build_primary_order factory with quantity Decimal('0'); entity construction is wrapped in try/except so an unrepresentable price (None) still returns the failure verdict with a loud audit-gap log instead of raising"
  - "Validator quantity rule merged: NEGATIVE_QUANTITY + ZERO_QUANTITY_TRANSITION collapsed into one INVALID_QUANTITY ERROR ('Quantity must be positive') mirroring the INVALID_PRICE shape — no test asserted the old NEGATIVE_QUANTITY code"
  - "SELL-with-no-long fall-through to entry sizing PRESERVED (the 2-shorts mechanism, Pitfall 4) — plan 07-07's direction guard removes it under owner sign-off"
  - "M5-06 marked complete per plan frontmatter: the structural core (policy resolved per-portfolio in the order/risk layer) is delivered; the result-changing enforcement clauses (allow_increase/max_positions) ride 07-07/07-08 as planned"
metrics:
  duration: "~15 min"
  completed: "2026-06-07"
  tasks: 3
  tests-added: 7
---

# Phase 7 Plan 05: Resolver-Wired OrderManager, Validator Hardening, Dead-Package Deletion Summary

OrderManager now sizes every unsized signal through the SizingResolver dispatching on signal.sizing_policy with loud audited REJECTED failures (triggered_by="sizing_policy"); the validator's zero-quantity "transition period" bypass and the three orphaned strategy_handler packages are dead — and the golden run is byte-exact through the entire swap (D-03).

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | Replace the M1 sizing seam with the resolver; audited D-06 rejections | 416a50c | itrader/order_handler/order_manager.py |
| 2 | Delete the zero-quantity validator bypass + the three orphaned packages | d5d41e6 | itrader/order_handler/order_validator.py, strategy_handler/{position_sizer,risk_manager,sltp_models}/ (deleted), tests/unit/order/test_order_validator.py |
| 3 | Order-path policy tests + byte-exact inertness gate | a4cf287 | tests/unit/order/test_on_signal.py |

## What Was Built

**OrderManager (tabs):** Constructor builds `self.sizing_resolver = SizingResolver(portfolio_handler)` with the same optionality as the read model. `_resolve_signal_quantity` preserves the M1 branch ORDER exactly: (a) explicit-quantity branch byte-identical (git diff shows the lines as unmodified context); (b) exit branch routes through `resolve_exit(net_quantity, signal.exit_fraction, policy.step_size)` — the golden `exit_fraction == Decimal("1")` returns `net_quantity` structurally unchanged; (c) entry branch routes through `resolve_entry(signal.sizing_policy, portfolio_id, price, stop=stop_loss or None)` — the FractionOfCash arm is operand-identical to the deleted `:628` expression. The SELL-with-no-long fall-through to entry sizing is deliberately preserved (Pitfall 4). The literal `Decimal("0.95")` no longer appears in sizing code.

**D-06 audited rejections:** New `_reject_unsized_signal` helper — invalid-price guard failures and `SizingPolicyViolation` raises both build the primary entity unsized (quantity 0) via the existing factory, transition it PENDING→REJECTED through `add_state_change(..., triggered_by="sizing_policy")` with the violation reason naming the policy, persist it to order storage, and return a `failure_result` (operation_type="signal_sizing") — the exact shape of the validator-rejection template. Timestamps stay event-derived (M2-09). The entity is REJECTED before validation, so the validator never consults the zero quantity.

**Validator (spaces):** The `ZERO_QUANTITY_TRANSITION` warning arm is deleted; a non-positive quantity is now a single hard ERROR (`INVALID_QUANTITY`, "Quantity must be positive") in the critical-field phase. `test_zero_quantity_signal` reworked to assert hard rejection (critical-field summary, no surviving transition warning); a new negative-quantity test locks the same rule.

**Deletions (D-04):** `git rm -r` on position_sizer/ (DynamicSizer with the float math and `round(quantity, 5)`), risk_manager/ (the never-wired cash<30 magic floor), sltp_models/ — 381 LOC, re-verified zero importers post-07-04 (only docstring mentions existed; `portfolio_read_model.py` docstring updated to name SizingResolver). No pyproject.toml mypy overrides named the deleted modules. The 07-04 interim `variable_sizer.py` typed-field fix dies here as expected.

**Tests (7 new/reworked in tests/unit/order):** RiskPercent-without-stop → zero emitted orders + ONE stored REJECTED order (triggered_by == "sizing_policy", reason contains "RiskPercent", timestamp == signal.time); FractionOfCash(0.95) quantity `str()`-equal to `(Decimal("0.95") * available) / to_money(price)` computed with the same operands read through the read model BEFORE the reservation; FixedQuantity(2) → quantity 2; explicit quantity bypasses policy; full exit `str()`-equal to `net_quantity`; `exit_fraction=Decimal("0.5")` → exactly half. Harness gained an `open_long` helper (fill-settled position via the canonical portfolio-first FILL order) and policy/exit_fraction factory parameters.

## Verification Evidence

- `tests/unit/order`: 119 passed (113 after Task 2 + 6 new policy tests)
- `make typecheck` (mypy --strict): Success, no issues in 129 source files
- Oracle inertness: `tests/integration/test_backtest_oracle.py` — **2 passed, byte-exact** (D-03: the resolver swap is proven oracle-inert)
- Full suite: `make test` — **691 passed**
- `grep -rn "ZERO_QUANTITY_TRANSITION\|DynamicSizer" itrader/ tests/` — zero hits
- `itrader/strategy_handler/` contains no position_sizer, risk_manager, or sltp_models directories
- `poetry run python -c "import itrader.strategy_handler"` — import OK post-deletion

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Acceptance-grep literals in docs/tests**
- **Found during:** Task 2 verification
- **Issue:** The acceptance greps (`DynamicSizer`, `ZERO_QUANTITY_TRANSITION` must return nothing) were tripped by a docstring mention in `itrader/core/portfolio_read_model.py:4` and by the reworked validator test's own docstring
- **Fix:** Read-model docstring now names SizingResolver; test docstring rephrased ("transition period" prose without the literal)
- **Files modified:** itrader/core/portfolio_read_model.py, tests/unit/order/test_order_validator.py
- **Commit:** d5d41e6

**2. [Rule 3 - Blocking] Worktree environment handling (carried from 07-01)**
- **Issue:** Worktree venv resolves `itrader` to the main checkout; `make` targets need `.env`
- **Fix:** All test runs use `PYTHONPATH="$PWD"`; empty gitignored `.env` created locally. No repo files changed
- **Commit:** n/a

### Plan-premise corrections (no code change)

**3. test_zero_quantity_signal already asserted rejection.** The plan expected tests "asserting the bypass" to need conversion to assert rejection — the existing test already asserted `result.success is False` (the zero-value order failed a later financial-risk phase). The rework strengthened it to assert the rejection now happens as a hard critical-field ERROR with the positive-quantity message, plus asserted no transition warning survives.

**4. No now-dead helpers orphaned by the resolver swap.** The plan's Task 1 step 4 (delete orphaned helpers) found nothing to delete — the M1 seam was fully inline in `_resolve_signal_quantity`.

## TDD Gate Compliance

Task 3 carries `tdd="true"`, but its behaviors are the direct output of Task 1 of this same plan — a strict RED phase (failing test before implementation) was structurally impossible within the plan's own task order, exactly as in plan 07-04. The test commit (a4cf287, `test(...)`) locks the Task-1 behavior; the implementation commit (416a50c, `feat(...)`) precedes it. Gate sequence is feat-then-test rather than test-then-feat — flagged here per protocol. The byte-exact oracle gate and the repr-exact assertions provide the regression lock the RED phase would have.

## Authentication Gates

None.

## Known Stubs

None — no placeholder values or unwired data paths introduced. The 07-04 interim shim consumers (`variable_sizer.py`) were deleted as planned.

## Threat Model Mitigations Applied

- **T-07-11 (mitigate):** Pitfall-5 option (a) implemented — sizing failures store an audited REJECTED entity with event-derived timestamps; unit-asserted (test_risk_percent_without_stop_is_audited_sizing_rejection)
- **T-07-12 (mitigate):** ZERO_QUANTITY_TRANSITION bypass deleted; tests assert quantity 0 and negative quantities fail validation
- **T-07-13 (mitigate):** Byte-exact oracle gate passed post-swap; repr-exact unit assertions on FractionOfCash and full-exit quantities; shorts fall-through deliberately preserved until the 07-07 owner-gated re-freeze
- **T-07-SC (accept):** zero package installs performed

## Self-Check: PASSED

- itrader/order_handler/order_manager.py — FOUND (contains SizingResolver, sizing_policy, triggered_by="sizing_policy")
- itrader/order_handler/order_validator.py — FOUND (no bypass)
- itrader/strategy_handler/{position_sizer,risk_manager,sltp_models}/ — DELETED
- tests/unit/order/test_on_signal.py, tests/unit/order/test_order_validator.py — FOUND
- Commits 416a50c, d5d41e6, a4cf287 — FOUND in git log
