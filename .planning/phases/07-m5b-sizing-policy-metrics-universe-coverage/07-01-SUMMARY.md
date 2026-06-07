---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 01
subsystem: order-sizing
tags: [sizing-policy, decimal, protocol, tdd, oracle-inert]
requires: []
provides:
  - "SizingPolicy union (FractionOfCash | FixedQuantity | RiskPercent) in core/sizing.py"
  - "SLTPPolicy union (PercentFromFill | PercentFromDecision)"
  - "TradingDirection enum with case-insensitive _missing_ parse (D-08 seam)"
  - "SignalIntent D-12 strategy-return contract with exit_fraction default Decimal('1')"
  - "SizingPolicyViolation in core/exceptions/order.py (D-06 fail-loud)"
  - "PortfolioReadModel.total_equity Protocol member + PortfolioHandler Decimal-native implementation"
  - "SizingResolver (order_handler/sizing_resolver.py) — ONE resolver, match/assert_never, byte-exact FractionOfCash arm"
affects:
  - 07-05 (resolver swap into OrderManager._resolve_signal_quantity)
  - 07-02..07-08 (all later plans consume the vocabulary)
tech-stack:
  added: []
  patterns:
    - "match/assert_never exhaustive dispatch (first use in codebase, sanctioned per RESEARCH Pattern 1)"
    - "frozen/slots dataclass + __post_init__ typed validation (core/bar.py idiom)"
key-files:
  created:
    - itrader/core/sizing.py
    - itrader/order_handler/sizing_resolver.py
    - tests/unit/core/test_sizing.py
    - tests/unit/order/test_sizing_resolver.py
  modified:
    - itrader/core/exceptions/order.py
    - itrader/core/exceptions/__init__.py
    - itrader/core/portfolio_read_model.py
    - itrader/portfolio_handler/portfolio_handler.py
    - tests/unit/core/test_portfolio_read_model.py
decisions:
  - "Sizing policy kinds (FractionOfCash/FixedQuantity/RiskPercent) are frozen/slots WITHOUT kw_only so both FractionOfCash(Decimal('0.95')) and FractionOfCash(fraction=...) construct (Task 1 behavior uses keyword, Task 3 acceptance uses positional); SLTP kinds and SignalIntent are kw_only=True per the Bar precedent"
  - "total_equity computed Decimal-native from cash_manager.balance + position_manager.get_total_market_value() — no float Portfolio.total_equity property read, no to_money(float) coercion needed (Pitfall 8 clean path existed)"
  - "M5-06 NOT marked complete: this plan builds the unwired vocabulary; the requirement ('fully resolved per-portfolio in the order/risk layer') completes when plan 07-05 wires the resolver"
metrics:
  duration: "~12 min"
  completed: "2026-06-07"
  tasks: 3
  tests-added: 60
---

# Phase 7 Plan 01: Typed Sizing Vocabulary, total_equity, SizingResolver Summary

JWT-free one-liner: Typed sizing vocabulary (SizingPolicy/SLTPPolicy/TradingDirection/SignalIntent) in core/, Decimal-native total_equity on the read-model Protocol, and a match/assert_never SizingResolver whose FractionOfCash arm is proven repr-exact against order_manager.py:628 — all new code, nothing wired, oracle-inert by construction.

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | core/sizing.py — typed policy vocabulary, TradingDirection, SignalIntent | 003a75e (RED), b9cf48f (GREEN) | itrader/core/sizing.py, itrader/core/exceptions/order.py, tests/unit/core/test_sizing.py |
| 2 | PortfolioReadModel.total_equity + PortfolioHandler conformance | 836635d (RED), e0f1ce7 (GREEN) | itrader/core/portfolio_read_model.py, itrader/portfolio_handler/portfolio_handler.py, tests/unit/core/test_portfolio_read_model.py |
| 3 | sizing_resolver.py — ONE resolver, match/assert_never, byte-exact FractionOfCash arm | f12de38 (RED), cd6f56d (GREEN) | itrader/order_handler/sizing_resolver.py, tests/unit/order/test_sizing_resolver.py |

## What Was Built

**core/sizing.py (spaces, cycle-safe):** Frozen/slots dataclasses for the three D-02 sizing kinds and two D-13 SLTP kinds, all validated in `__post_init__` (fraction/exit_fraction in (0,1], qty/risk_pct/sl_pct/tp_pct > 0, step_size > 0 when set) raising `SizingPolicyViolation` with field+value in the message. `TradingDirection` copies the OrderType `_missing_` case-insensitive parse pattern. `SignalIntent` is the D-12 contract (ticker, action: Side, optional SL/TP/quantity, exit_fraction default `Decimal("1")`). Imports are stdlib + intra-core only — grep for order_handler/events_handler/strategy_handler imports returns nothing (Pitfall 3).

**total_equity:** Protocol widened from six to seven members; module docstring records the narrow D-14 amendment (oracle-dark — golden FractionOfCash never reads it). PortfolioHandler implements Decimal-native: `cash_manager.balance + position_manager.get_total_market_value()` — both internals were already Decimal, so the documented to_money(float) fallback was unnecessary. Full ledger balance used (reservation does not reduce equity — locked by test).

**SizingResolver:** Constructor-injected `PortfolioReadModel` (Protocol-typed, never the concrete handler). `resolve_entry` match-dispatches closing with `typing.assert_never`; the FractionOfCash arm is `(policy.fraction * self._read_model.available_cash(portfolio_id)) / to_money(price)` — same operands, same order as the M1 seam, locked by `str()` repr-exact tests. RiskPercent reads `total_equity` and computes Van Tharp `(equity * risk_pct) / abs(price - stop)`; missing or price-equal stop raises `SizingPolicyViolation("RiskPercent requires stop_loss ...")`. `step_size` quantizes ROUND_DOWN after dispatch; `None` performs no quantize. `resolve_exit` with `exit_fraction == 1` returns `net_quantity` without multiplying (exponent-preservation locked by a `Decimal("2.50")` test); the dust guard takes the full position when the remainder would drop below step_size.

## Verification Evidence

- `tests/unit/core/test_sizing.py` (30) + `tests/unit/core/test_portfolio_read_model.py` (15) + `tests/unit/order/test_sizing_resolver.py` (15) — 60 passed
- `make typecheck` (mypy --strict): Success, no issues in 141 source files
- Oracle inertness: `tests/integration/test_backtest_oracle.py` — 2 passed (new modules unimported by the engine)
- Full unit suite: 628 passed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree venv resolves `itrader` to the main checkout**
- **Found during:** Task 1 GREEN verification
- **Issue:** The Poetry venv lives at the main repo (`intelli-trader/.venv`) with `itrader` installed editable pointing at the main checkout — `poetry run pytest` in the worktree imported main-repo code, not the worktree's
- **Fix:** All test runs in this execution use `PYTHONPATH="$PWD"` so the worktree source shadows the editable install; `mypy itrader` already checks the worktree path directly. No repo files changed
- **Files modified:** none
- **Commit:** n/a (environment handling only)

**2. [Rule 3 - Blocking] `make typecheck` failed — `.env` missing in worktree**
- **Found during:** Task 2 verification
- **Issue:** The Makefile `include .env` aborts when `.env` (gitignored) is absent in the fresh worktree
- **Fix:** Created an empty local `.env` (gitignored, never committed)
- **Files modified:** none committed
- **Commit:** n/a

## TDD Gate Compliance

All three tasks followed RED→GREEN: `test(...)` commits (003a75e, 836635d, f12de38) precede their `feat(...)` commits (b9cf48f, e0f1ce7, cd6f56d). Each RED run was verified failing (collection ImportError for new modules; 4 assertion failures for the Protocol widening) before implementation. No refactor commits needed.

## Known Stubs

None — all new code is fully implemented and unit-locked. The vocabulary is intentionally **unwired** (nothing on the run path imports it yet); wiring is plan 07-05's job, by design, not a stub.

## Threat Model Mitigations Applied

- **T-07-01 (mitigate):** `__post_init__` validation on every policy dataclass raising `SizingPolicyViolation` — applied in core/sizing.py
- **T-07-02 (mitigate):** repr-exact `str()` unit tests reproducing order_manager.py:628; structural no-op tests for `exit_fraction=1` and `step_size=None` — applied in test_sizing_resolver.py
- **T-07-SC (accept):** zero package installs performed

## Self-Check: PASSED

- itrader/core/sizing.py — FOUND
- itrader/order_handler/sizing_resolver.py — FOUND
- tests/unit/core/test_sizing.py — FOUND
- tests/unit/order/test_sizing_resolver.py — FOUND
- Commits 003a75e, b9cf48f, 836635d, e0f1ce7, f12de38, cd6f56d — FOUND in git log
