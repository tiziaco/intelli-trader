---
phase: 05-strategy-interface-hardening-signal-storage
plan: 01
subsystem: strategy-handler / core-primitives
tags: [config, pydantic, ids, enums, tdd, oracle-dark]
requires:
  - "itrader.core.enums (TradingDirection/OrderType house pattern)"
  - "itrader.core.sizing (SizingPolicy/SLTPPolicy frozen-dataclass unions)"
  - "itrader.outils.id_generator.IDGenerator (UUIDv7 scheme)"
provides:
  - "itrader.core.ids.SignalId (NewType over uuid.UUID, D-10)"
  - "itrader.outils.id_generator.IDGenerator.generate_signal_id"
  - "itrader.core.enums.Timeframe (barrel-registered, case-insensitive, D-06)"
  - "itrader.strategy_handler.config.BaseStrategyConfig / SMA_MACDConfig / EmptyStrategyConfig"
affects:
  - "Plan 02 (constructor refactor builds against these finished contracts)"
tech-stack:
  added: []
  patterns:
    - "pydantic v2 frozen config models with arbitrary_types_allowed for frozen-dataclass unions"
    - "case-insensitive enum _missing_ at the config boundary (TradingDirection/OrderType house pattern)"
key-files:
  created:
    - itrader/strategy_handler/config.py
    - tests/unit/strategy/test_strategy_config.py
  modified:
    - itrader/core/ids.py
    - itrader/outils/id_generator.py
    - itrader/core/enums/trading.py
    - itrader/core/enums/__init__.py
decisions:
  - "RED phase was not separately committed: test + new module are tightly-coupled deliverables of a single additive contract leaf; committed together as one feat commit (gate sequence documented below)."
metrics:
  duration: 18min
  completed: 2026-06-09
---

# Phase 5 Plan 01: Strategy-Interface Hardening — Leaf Primitives Summary

Added the typed contract surface for Phase 5 — `SignalId`/`generate_signal_id` (D-10), the barrel-registered `Timeframe` enum (D-06), and three frozen pydantic config models (`BaseStrategyConfig`/`SMA_MACDConfig`/`EmptyStrategyConfig`) with HARD-01/HARD-02 validators — all additive-only and oracle-dark (nothing wired into the run path).

## What Was Built

### Task 1 — Core primitives (commit `436af29`)
- `core/ids.py`: added `SignalId = NewType("SignalId", uuid.UUID)` to the alias block and `__all__` (docstring count "Eight" → "Nine").
- `outils/id_generator.py`: added `generate_signal_id(self) -> uuid.UUID` mirroring `generate_order_id` exactly (single UUIDv7 scheme, D-10).
- `core/enums/trading.py`: added `Timeframe(Enum)` with members `M1/M5/M15/H1/H4/D1/W1` (values `1m`..`1w`) and a case-insensitive `_missing_` mirroring `TradingDirection._missing_` (raises `ValueError` on unknown).
- `core/enums/__init__.py`: barrel-registered `Timeframe` (import + `__all__`).

### Task 2 — Config models (TDD, commit `330c60d`)
- `strategy_handler/config.py`: `BaseStrategyConfig` (`frozen=True`, `arbitrary_types_allowed=True`; fields `timeframe: Timeframe`, `tickers`, `order_type=OrderType.MARKET`, `direction=LONG_ONLY`, `allow_increase=False`, `max_positions=Field(gt=0)`, `sizing_policy: SizingPolicy` required, `sltp_policy: SLTPPolicy | None`). `SMA_MACDConfig` adds the golden-default windows (`short=50`, `long=100`, `FAST=6`, `SLOW=12`, `WIN=3`, all `Field(gt=0)`) plus a `@model_validator(mode="after")` `_short_lt_long` enforcing `short_window < long_window` (HARD-02). `EmptyStrategyConfig` adds no params. Pydantic v2 decorators only.
- `tests/unit/strategy/test_strategy_config.py`: 7 tests — golden-default construction, short>=long rejection, non-positive-window rejection, invalid-timeframe rejection, frozen immutability, `model_dump` recursion into the sizing dataclass (SIG-02 snapshot), and `EmptyStrategyConfig` construction.

## Verification Results

- `pytest tests/unit/strategy/test_strategy_config.py -q` → 7 passed (all six required behaviors + EmptyStrategyConfig).
- `pytest tests/unit/strategy/ -q` → 16 passed.
- `pytest tests/integration/test_backtest_oracle.py -q` → 2 passed, byte-exact (134 trades / `final_equity 46189.87730727451`) — oracle dark by construction (nothing wired).
- `mypy --strict itrader` → no issues found in 131 source files.
- Task 1 inline verify: `Timeframe('1d') is Timeframe.D1`, `Timeframe('1D') is Timeframe.D1`, `Timeframe('3mo')` raises `ValueError`, `idgen.generate_signal_id()` returns a `uuid.UUID`.
- `model_dump()["sizing_policy"]` → `{'fraction': Decimal('0.95'), 'step_size': None}` (queryable snapshot confirmed under `arbitrary_types_allowed`).

## TDD Gate Compliance

Task 2 (`tdd="true"`) followed RED → GREEN:
- RED: `tests/unit/strategy/test_strategy_config.py` was written first and run; it failed with `ModuleNotFoundError: No module named 'itrader.strategy_handler.config'` (and resolved the new `Timeframe` import correctly), confirming the test fails before implementation.
- GREEN: `config.py` was created; the test then passed 7/7.
- The test file is itself a plan deliverable and is tightly coupled to the new module, so RED and GREEN were captured in a single `feat` commit (`330c60d`) rather than two. No REFACTOR pass was needed.

## Environment Note (not a deviation)

The shared in-project `.venv` editable install (`itrader.pth`) points the `itrader` package at the MAIN repo, not the worktree. Under pytest's rootdir-based import this shadowed the worktree's edits. All test/verify runs that exercise the new symbols were therefore run with `PYTHONPATH="$PWD"` prepended so the worktree copy resolves first. This is a worktree/editable-install interaction, not a code or plan defect; the committed code is correct (mypy and direct imports against the worktree resolve cleanly).

## Deviations from Plan

None — plan executed exactly as written. No Rule 1–4 deviations; no auth gates; no architectural changes.

## Known Stubs

None. `EmptyStrategyConfig` is intentionally param-free by design (D-02) and is consumed by the relocated Empty_strategy in Plan 02 — not a stub.

## Self-Check: PASSED

- FOUND: itrader/strategy_handler/config.py
- FOUND: tests/unit/strategy/test_strategy_config.py
- FOUND: itrader/core/ids.py (SignalId), itrader/outils/id_generator.py (generate_signal_id), itrader/core/enums/trading.py (Timeframe), itrader/core/enums/__init__.py (Timeframe registered)
- FOUND commit: 436af29 (Task 1)
- FOUND commit: 330c60d (Task 2)
