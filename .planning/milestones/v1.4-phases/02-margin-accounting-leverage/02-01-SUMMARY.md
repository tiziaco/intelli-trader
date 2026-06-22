---
phase: 02-margin-accounting-leverage
plan: 01
subsystem: contracts (signal event + portfolio config)
tags: [leverage, margin, contract-field, oracle-dark, D-03, D-14, LEV-01]
requires:
  - "02-00 (Wave 0 collectible test stubs satisfying the Nyquist contract)"
provides:
  - "SignalEvent.leverage: Decimal field (default Decimal('1')) — the cross-domain leverage transport (D-03)"
  - "TradingRules.max_leverage: Decimal field (default Decimal('1'), ge=1) — the account-wide leverage cap (D-14)"
affects:
  - "Wave 2 admission-gate leverage cap (D-04) consumes both fields"
tech-stack:
  added: []
  patterns:
    - "Defaulted kw_only field among required ones on a frozen dataclass (mirrors exit_fraction)"
    - "Pydantic bounded Field(default=..., ge=1) style (mirrors PortfolioLimits)"
key-files:
  created: []
  modified:
    - "itrader/events_handler/events/signal.py (SignalEvent.leverage field + docstring)"
    - "itrader/config/portfolio.py (TradingRules.max_leverage field)"
decisions:
  - "leverage rides the SignalEvent (strategy/signal concern), not a portfolio default — no default_leverage on TradingRules (D-14)"
  - "max_leverage floor is ge=1 (sub-1 account leverage cap is nonsensical); default Decimal('1') is unlevered/byte-exact"
  - "Both Decimal literals use the string path Decimal('1') — never Decimal(1.0) (money discipline, T-02-02 mitigation)"
metrics:
  duration: ~5 min
  completed: 2026-06-15
  tasks: 2
  files: 2
---

# Phase 2 Plan 01: Margin/Leverage Contract Fields Summary

Landed the two inert leverage/margin contract fields that downstream Wave-2 waves consume: `SignalEvent.leverage: Decimal` (D-03 — strategy declares, engine resolves) and `TradingRules.max_leverage: Decimal` account-wide cap (D-14). Both default `Decimal("1")`, so the SMA_MACD spot run is oracle-dark and the golden master is untouched.

## What Was Built

- **`SignalEvent.leverage: Decimal = Decimal("1")`** — a defaulted kw_only field on the frozen dataclass, placed among the other defaulted fields (after `exit_fraction`), with a `Parameters` docstring entry mirroring the `exit_fraction` block. It is the D-03 strategy-declared leverage scalar; the engine caps it against `max_leverage` and applies it in the order layer (Wave 2). No consumer reads it yet.
- **`TradingRules.max_leverage: Decimal = Field(default=Decimal("1"), ge=1)`** — the account-wide leverage cap, declared in the `extra="forbid"` Pydantic model alongside `enable_margin`/`allow_short_selling`, using the bounded-`Field` style from `PortfolioLimits`. The `ge=1` floor rejects sub-1 leverage caps. No `default_leverage` was added — leverage is a strategy/signal concern (D-14).

## Verification

- Task 1 automated check: `dataclasses.fields(SignalEvent)` includes `leverage` with default `Decimal("1")` → OK.
- Task 2 automated check: `TradingRules().max_leverage == Decimal("1")`; `TradingRules(max_leverage=Decimal("0.5"))` raises `pydantic.ValidationError` (ge=1 floor); `TradingRules(max_leverage=Decimal("5"))` constructs → OK.
- `poetry run mypy itrader` → Success: no issues found in 185 source files.
- `poetry run pytest tests/unit/order tests/unit/portfolio -x` → 378 passed, 13 skipped (the expected Wave 0 stubs; no consumer reads the new fields so existing tests are unaffected).
- `poetry run pytest tests/integration` → 16 passed; the byte-exact BTCUSD oracle gate (134 trades / `final_equity 46189.87730727451`) holds — both fields are oracle-dark.
- 4-space indentation preserved in both files (no tab introduced); string-path Decimal literals only.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both fields are intentionally inert (defaulted, no consumer) by design — Wave 2 (admission-gate leverage cap, D-04) wires them. This is the contract-landing plan, not the wiring plan; documented as oracle-dark in the plan objective and truths.

## Threat Flags

None. No new security-relevant surface — both are engine-internal Decimal contract fields with defaults pinned to the string-path `Decimal("1")` (T-02-01 / T-02-02 mitigations: default-drift and float-repr are guarded by the byte-exact gate and the string literal respectively).

## Commits

- `b50e622` feat(02-01): add SignalEvent.leverage field (D-03)
- `fe3ba7f` feat(02-01): add TradingRules.max_leverage config field (D-14)

## Self-Check: PASSED

- FOUND: itrader/events_handler/events/signal.py (leverage field)
- FOUND: itrader/config/portfolio.py (max_leverage field)
- FOUND commit: b50e622
- FOUND commit: fe3ba7f
