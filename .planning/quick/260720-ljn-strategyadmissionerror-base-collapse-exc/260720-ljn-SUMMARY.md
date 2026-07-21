---
phase: quick-260720-ljn
plan: 01
subsystem: core-exceptions / strategy-registry
tags: [refactor, exceptions, CR-01, D-19]
requires: [260720-km2]
provides: ["StrategyAdmissionError shared admission ancestor"]
affects: [itrader/core/exceptions, itrader/strategy_handler/registry, itrader/strategy_handler/lifecycle]
tech-stack:
  added: []
  patterns: ["shared exception ancestor replacing hand-listed catch tuples"]
key-files:
  created: []
  modified:
    - itrader/core/exceptions/strategy.py
    - itrader/core/exceptions/__init__.py
    - itrader/strategy_handler/registry/catalog.py
    - itrader/strategy_handler/registry/config_codec.py
    - itrader/strategy_handler/registry/rehydrate.py
    - itrader/strategy_handler/lifecycle/manager.py
    - tests/unit/core/test_exceptions.py
    - tests/unit/strategy/test_rehydrate.py
decisions:
  - "StrategyAdmissionError(ITraderError, ValueError) — ValueError base is load-bearing (preserves pre-existing catches AND plain-message construction), which is why rooting the family at the house ValidationError was impossible"
  - "UnwarmableTimeframeError deliberately NOT folded into the base — a FEED exception and a payload-x-environment interaction; stays a separate explicit _QUARANTINABLE member"
  - "ValueError REMAINS in all three manager.py catch tuples — a third-party validate() override raises bare ValueError and can never join our hierarchy"
metrics:
  duration: ~25min
  completed: 2026-07-20
status: complete
---

# Quick Task 260720-ljn: StrategyAdmissionError Base Collapse Summary

Introduced a single `StrategyAdmissionError` ancestor for the four strategy-domain rejection
exceptions and collapsed four divergent, hand-listed catch tuples onto it — removing the drift
surface that caused CR-01.

## What Changed

**Task 1 (`8397b8d6`)** — `StrategyAdmissionError(ITraderError, ValueError)` defined in
`core/exceptions/strategy.py` with both bases documented as load-bearing; `UnknownParamError` and
`MissingParamError` reparented to `(ValidationError, StrategyAdmissionError)`; module docstring
rewritten; exported first in the barrel's strategy group.

**Task 2 (`69ecdac4`)** — `UnknownStrategyTypeError` and `StrategyConfigError` reparented onto the
base (both still `ValueError`, all ~25 plain-message raise sites untouched).
`rehydrate._QUARANTINABLE` collapsed from 5 members to 2, with the doctrine comment rewritten to
explain the narrow-base reasoning rather than prohibit it. All three `manager.py` catch sites
collapsed to `except (StrategyAdmissionError, ValueError)`.

**Task 3 (`e124a446`)** — hierarchy + MRO pinning in `test_exceptions.py` (9 new tests); D-19
separability regression in `test_rehydrate.py` (3 new tests).

## Verification (observed, not expected)

| Gate | Result |
|------|--------|
| `tests/unit/strategy` | **340 passed** (was 337 + 3 new) |
| `tests/unit/core/test_exceptions.py` | **21 passed** (was 12 + 9 new) |
| `tests/unit/price_handler` | 24 passed |
| Full `tests/unit` | **2302 passed** |
| `tests/integration` | **204 passed, 2 skipped** (OKX creds absent) |
| Backtest oracle | **byte-exact — `trade_count=134`, `final_equity=46189.87730727451`** |
| `poetry run mypy` | **Success: no issues found in 273 source files** |

mypy raised **no** objection to the two-hierarchy multiple inheritance; no `type: ignore` was added.

Observed MRO: `UnknownParamError -> ValidationError -> StrategyAdmissionError -> ITraderError ->
ValueError -> Exception`, exactly as the plan predicted.

## Falsification of the load-bearing test

The D-19 behavioral test was proven non-vacuous: temporarily widening `_QUARANTINABLE` to include
`RuntimeError` made `test_mid_loop_infrastructure_fault_propagates_instead_of_quarantining` FAIL
(the infra error was quarantined instead of propagating). The probe was reverted immediately.

## Deviations from Plan

**1. [Plan defect — gate false positive] The Task 2 "TABS OK" probe is wrong as written.**
The probe asserts no line in the four tab files starts with a space. `rehydrate.py` has **7
pre-existing space-indented lines** — module-docstring bullet continuation prose, present
unchanged at `HEAD`. The gate would therefore have failed on an untouched tree. Substituted an
equivalent, correct gate: (a) zero space-indented lines among *added* diff lines (`git diff -U0 |
grep -P '^\+ +\S'` → NONE), (b) per-file space-indented count identical to `HEAD` (0/0/7/0 before
and after), (c) `git diff --check` clean. Indentation is correct; only the gate was faulty.

**2. [Tooling] `Write` tool refused `.md` files.** Both `SUMMARY.md` files were created via Bash
heredoc instead. No content difference.

**3. [Plan wording] `rehydrate.py` catalog import collapsed to a single-name line.** After removing
`UnknownStrategyTypeError` the parenthesized block held one name; folded to
`from ... import StrategyCatalog`. Cosmetic.

## Ground-Truth Confirmations

- `StrategyConfigError` in `rehydrate.py` **kept** — re-grepped and confirmed it is RAISED at
  `_resolve_portfolio_id` (line 206 post-edit), not merely caught. Deleting it would have broken
  the module, as the plan warned.
- `manager.py` lines 384 / 859 mention `UnknownParamError` / `UnknownStrategyTypeError` in prose
  comments only — left alone; file-wide identifier counts correctly do not reach zero.
- km2's zone-1/zone-2 two-tier guard: `git diff` shows the tier-2 `except Exception` arm, its
  four-point comment, and all zone-2 code **do not appear in the diff at all** — byte-identical.

## Out of Scope (untouched, as instructed)

Bare raises at `base.py:292` and `strategies/SMA_MACD_strategy.py:42`; `UnwarmableTimeframeError`
remains a separate `_QUARANTINABLE` member; no other 10.1-REVIEW.md finding.

## Self-Check: PASSED

All modified files exist; all three commits (`8397b8d6`, `69ecdac4`, `e124a446`) present in
`git log`; both SUMMARY files on disk.
