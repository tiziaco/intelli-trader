---
phase: 04-liquidation-cross-validation-re-baseline
plan: 01
subsystem: core-contracts
tags: [liquidation, enum, instrument, config, oracle-dark]
requires:
  - "core/enums/order.py OrderTriggerSource closed-vocab enum"
  - "core/instrument.py frozen Instrument value object (borrow_rate analog)"
  - "config/portfolio.py TradingRules (max_leverage rate-field analog)"
provides:
  - "OrderTriggerSource.LIQUIDATION trigger-source member (LIQ-03)"
  - "Instrument.liquidation_fee_rate: Decimal = Decimal('0') frozen field (D-06)"
  - "TradingRules.liquidation_fee_rate: Field(default=Decimal('0'), ge=0) config fallback (D-06)"
affects:
  - "04-03 liquidation engine (consumes all three: Instrument-first -> config fallback fee rate + LIQUIDATION tag)"
tech-stack:
  added: []
  patterns:
    - "Instrument-first -> TradingRules config fallback fee-rate resolution seam (consumed by 04-03)"
    - "oracle-dark default-off plumbing (Decimal('0') / unread on spot path)"
key-files:
  created: []
  modified:
    - "itrader/core/enums/order.py (TABS — LIQUIDATION member)"
    - "itrader/core/instrument.py (4 SPACES — liquidation_fee_rate field + docstring)"
    - "itrader/config/portfolio.py (4 SPACES — TradingRules.liquidation_fee_rate Field)"
decisions:
  - "LIQUIDATION string value = 'liquidation' (planner discretion, D-discretion)"
  - "No new MMR field — maintenance_margin_rate (INST-03) already satisfies the LIQ MMR need (IN-03 clarification)"
  - "No new FillStatus — liquidation reuses EXECUTED (LOCKED), out of scope for this plan"
metrics:
  duration: "~6 min"
  tasks_completed: 3
  files_modified: 3
  completed: "2026-06-16"
requirements-completed: [LIQ-02, LIQ-03]
---

# Phase 4 Plan 01: Inert Liquidation Data/Enum Plumbing Summary

Landed the three inert, default-off contracts the Phase-4 liquidation engine (04-03) consumes —
the `OrderTriggerSource.LIQUIDATION` forced-close trigger source (LIQ-03), the per-symbol
`Instrument.liquidation_fee_rate` field, and the `TradingRules.liquidation_fee_rate` config
fallback (both D-06) — all defaulted `Decimal("0")` and proven oracle-dark (SMA_MACD byte-exact at
134 trades / `final_equity 46189.87730727451`).

## What Was Built

- **Task 1 — `OrderTriggerSource.LIQUIDATION` (TABS):** added `LIQUIDATION = "liquidation"` after
  `ADMISSION_LEVERAGE`, with a `# LIQ-03 — forced-close trigger source` comment. The existing
  case-insensitive `_missing_` parser was left untouched (it already resolves the new member). File
  stayed tab-indented (no mixed-indentation diff). Commit `86d64b1`.
- **Task 2 — `liquidation_fee_rate` on Instrument + TradingRules (4 SPACES both):**
  - `Instrument.liquidation_fee_rate: Decimal = Decimal("0")` added immediately after `borrow_rate`,
    mirroring the `borrow_rate` shape exactly (frozen, Decimal, oracle-dark default), with a Fields
    docstring paragraph noting `# D-06 — default 0 = oracle-dark`. No new MMR field —
    `maintenance_margin_rate` (INST-03) already satisfies the need.
  - `TradingRules.liquidation_fee_rate: Decimal = Field(default=Decimal("0"), ge=0)` added,
    mirroring the `max_leverage` Field shape — the config-level fallback for symbols that do not
    declare it on `Instrument` (Instrument-first -> config fallback, resolved in 04-03).
  - Commit `5a9f804`.
- **Task 3 — byte-exact + mypy proof gate (no code change):** ran the oracle and mypy to prove the
  three additions are inert. No commit (proof gate only).

## Verification

- `pytest tests/integration/test_backtest_oracle.py -x` -> 3 passed; oracle byte-exact
  (134 trades / `final_equity 46189.87730727451`, D-11).
- `mypy --strict itrader/core/instrument.py itrader/core/enums/order.py itrader/config/portfolio.py`
  -> Success: no issues found in 3 source files.
- Functional asserts:
  - `OrderTriggerSource.LIQUIDATION.value == "liquidation"`; `OrderTriggerSource("LIQUIDATION")`
    resolves via `_missing_`.
  - `Instrument(...).liquidation_fee_rate == Decimal("0")` (no override);
    `TradingRules().liquidation_fee_rate == Decimal("0")`; negative value rejected
    (`ValidationError`, `ge=0`).
- Indentation: LIQUIDATION line tab-indented; both new fields 4-space (verified `grep -P '^\t'`
  matched nothing for the new lines in the spaces files).

## Deviations from Plan

None - plan executed exactly as written.

## Threat-Model Coverage

- **T-04-01-INT / T-04-01-PREC (mitigate):** all three fields default `Decimal("0")` (string literal,
  never `Decimal(0.0)`) / unread on the spot path -> oracle-dark. Task 3 re-asserted the byte-exact
  oracle as the proof. Held.
- **T-04-01-SC (accept):** no package installs. N/A.

## Known Stubs

None — these are intentional inert contracts (oracle-dark by design), wired by the 04-03 consumer.
Documented as default-off in PROJECT/STATE; not stubs that block this plan's goal.

## Self-Check: PASSED

- Files: `itrader/core/enums/order.py`, `itrader/core/instrument.py`, `itrader/config/portfolio.py`,
  `04-01-SUMMARY.md` — all present.
- Commits: `86d64b1` (Task 1), `5a9f804` (Task 2) — both present in git log.
