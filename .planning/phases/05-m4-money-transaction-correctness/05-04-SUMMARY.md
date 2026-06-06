---
phase: 05-m4-money-transaction-correctness
plan: 04
subsystem: execution_handler
tags: [D-21, M4-07, OQ3, dto, abc, events-only]
requires:
  - phase: 05-02
    provides: "SimulatedExchange._lock deleted (D-19 single-writer contract)"
provides:
  - "FillEvent as the single channel of execution output (ExecutionResult deleted, D-21)"
  - "execute_order returns None on Protocol + SimulatedExchange"
  - "AbstractExecutionHandler real ABC: @abstractmethod on_order + on_market_data"
  - "Frozen/slots execution metadata DTOs (ConnectionResult, HealthStatus, OrderPreflightResult)"
  - "OrderPreflightResult — ValidationResult collision resolved (OQ3/#39)"
affects: [05-07]
tech-stack:
  added: []
  patterns:
    - "events-only execution output (Nautilus/FIX shape, D-21)"
    - "frozen=True/slots=True construct-complete DTOs (Phase 4 precedent)"
key-files:
  created: []
  modified:
    - itrader/execution_handler/base.py
    - itrader/execution_handler/result_objects.py
    - itrader/execution_handler/exchanges/base.py
    - itrader/execution_handler/exchanges/simulated.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/unit/execution/test_execution_handler.py
decisions:
  - "All three surviving DTOs kept (none dead): ConnectionResult, HealthStatus, OrderPreflightResult all have genuine non-test importers"
  - "HealthStatus.total_volume_today retyped float -> Decimal (money-denominated); internal float telemetry coerced at DTO boundary"
  - "Exception path in execute_order now emits FillEvent(REFUSED) — was a silent sync-only failure before (T-05-08)"
  - "RNG draw removed with ExecutionResult metadata (uniform(5,25)) is oracle-inert: default preset is zero-slippage/zero-fee/no-failures so nothing else consumes the RNG on the golden path"
metrics:
  duration: ~20 min
  completed: 2026-06-06
  tasks: 2
  commits: [b48894b, a7d4503]
---

# Phase 5 Plan 04: Execution DTO Surface & Events-Only Output Summary

**One-liner:** ExecutionResult deleted — FillEvents on the global queue are the only execution output (D-21); AbstractExecutionHandler is a real two-method ABC; surviving DTOs frozen/Decimal; execution-domain ValidationResult renamed OrderPreflightResult (OQ3).

## What Was Built

### Task 1 — Delete ExecutionResult; execute_order -> None; real ABC (b48894b)

- `SimulatedExchange.execute_order` returns `None`. All five `ExecutionResult(...)` construction sites removed:
  - **Validation-reject site** — already emitted `FillEvent(REFUSED)` via `_emit_rejection`; emission kept, sync return dropped.
  - **Not-connected site** — already emitted `FillEvent(REFUSED)`; same treatment.
  - **Failure-simulation site** — already emitted `FillEvent(REFUSED)`; the `_rng.choice(error_scenarios)` draw is preserved so failure-sim RNG sequencing is unchanged.
  - **Success site** — `_emit_fill` already emitted `FillEvent(EXECUTED)`; the discarded metadata dict (and its `_rng.uniform(5, 25)` draw) deleted.
  - **Exception site** — did NOT emit any event before. Added `self._emit_rejection(event, ...)` so unexpected failures surface as auditable `FillEvent(REFUSED)` (T-05-08 mitigation — no information channel lost).
- `exchanges/base.py` Protocol: `execute_order(...) -> None`; `ExecutionResult` import deleted.
- `result_objects.py`: `ExecutionResult` class deleted; now-unused `ExecutionStatus`/`Decimal` imports removed (enum members in `core/enums/execution.py` untouched — still consumed by `tests/unit/core/test_enums.py`).
- `execution_handler/base.py`: `AbstractExecutionHandler` rewritten as a real ABC modeled on `PortfolioStateStorage` house style — `@abstractmethod on_order` AND `@abstractmethod on_market_data` (signature per the exchange Protocol), class docstring cites D-21/#39, stale Compliance paragraph deleted. Tab indentation preserved.
- Tests rewritten to assert on emitted FillEvents (queue contents) via a `drain_fills` helper; added ABC-enforcement tests (base uninstantiable, both hooks abstract, `ExecutionHandler` isinstance check).
- `_emit_fill` simplified to return `None` (its tuple return only fed ExecutionResult; no other consumers — verified by grep).

### Task 2 — DTO reconciliation + OQ3 rename (a7d4503)

**Per-DTO survivor/delete decisions** (importer inventory via repo-wide grep):

| DTO | Non-test importers | Decision |
|-----|--------------------|----------|
| `ConnectionResult` | `exchanges/base.py` Protocol, `simulated.py` connect/disconnect, `execution_handler.py` reads `.success`/`.error_message` | **Survives** → frozen/slots; no money fields |
| `HealthStatus` | `exchanges/base.py` Protocol, `simulated.py` health_check, `execution_handler.py` get_exchange_health | **Survives** → frozen/slots; `total_volume_today` float → **Decimal** (money-denominated), coerced `Decimal(str(...))` at the construction boundary |
| `ValidationResult` (execution) | `exchanges/base.py` Protocol, `simulated.py` validate_order | **Survives, renamed** → `OrderPreflightResult`, frozen/slots |

- Zero dead DTOs found — nothing deleted in Task 2.
- `order_handler/order_validator.py::ValidationResult` keeps its name unchanged (verified: 1 class definition, untouched).
- Module docstring on `result_objects.py` cites D-21: these DTOs are connection/health/preflight metadata, NOT execution results.
- All construction sites already construct-complete (no post-init mutation found); added a frozen-semantics regression test (T-05-09).

## M4-07 fill_id Criterion

M4-07's `fill_id` criterion is satisfied via the **FillEvent linkage** (Phase 4 D-12): every `FillEvent` carries REQUIRED `fill_id` (fresh UUIDv7 generated at fill construction), `order_id`, and `strategy_id`, giving the full fill → order → strategy audit chain for every execution outcome including REFUSED and CANCELLED. With ExecutionResult gone, this event linkage is the sole — and sufficient — execution audit record. The D-22 Decimal event retype (the oracle-risky half of M4-07) is deliberately isolated in plan 05-07.

## Rejection-Path FillEvent Verification (T-05-08)

Audited every removal site before deletion: validation-reject, not-connected, and failure-simulation paths all already emitted `FillEvent(REFUSED)`; the success path emits `FillEvent(EXECUTED)`. The only gap was the `except Exception` path, which previously returned a sync-only failed ExecutionResult with no event — fixed by adding the `_emit_rejection` call there.

## Verification

- `poetry run python -m pytest tests/unit/execution -q` — 67 passed
- `poetry run python -m pytest tests/ -q` (make test equivalent; worktree lacks `.env`) — 435 passed
- `poetry run mypy itrader` (make typecheck equivalent) — Success: no issues in 134 files
- `poetry run python -m pytest tests/integration/test_backtest_oracle.py -q` — 2 passed; `git diff --stat tests/golden/` empty (byte-exact)
- `grep -rn "ExecutionResult" itrader/ tests/` — 0 matches
- `execution_handler/base.py` — 0 "Compliance" matches, on_order + on_market_data both `@abstractmethod`
- Oracle-inertness reasoning: the deleted `_rng.uniform(5, 25)` metadata draw is the only RNG consumer removed; the golden path uses the default preset (ZeroFeeModel, ZeroSlippageModel — no RNG draws, failure simulation disabled), so RNG-sequence change cannot affect fills. Confirmed empirically by the byte-exact oracle.

## Deviations from Plan

None - plan executed exactly as written. (The exception-path `_emit_rejection` addition was explicitly mandated by the plan's "if any rejection site does NOT emit, add the FillEvent(REFUSED) emission" instruction.)

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes beyond the plan's threat model. T-05-08 and T-05-09 mitigations applied as registered.

## Self-Check: PASSED

- itrader/execution_handler/base.py: FOUND
- itrader/execution_handler/result_objects.py: FOUND
- itrader/execution_handler/exchanges/base.py: FOUND
- itrader/execution_handler/exchanges/simulated.py: FOUND
- tests/unit/execution/exchanges/test_simulated_exchange.py: FOUND
- tests/unit/execution/test_execution_handler.py: FOUND
- Commit b48894b: FOUND
- Commit a7d4503: FOUND
