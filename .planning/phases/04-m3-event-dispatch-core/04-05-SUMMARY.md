---
phase: 04-m3-event-dispatch-core
plan: 05
subsystem: events
tags: [events, cutover, frozen-dataclass, side-enum, ordertype-enum, big-bang, behavior-preserving]
requires:
  - "04-01 (EventType + Side in core/enums, TimeEvent family)"
  - "04-02 (SignalEvent de-mutation, Order-entity pipeline)"
  - "04-03 (construct-complete new_fill, replace-in-book matching)"
  - "04-04 (frozen events_handler/events/ package — inert until this cutover)"
provides:
  - "The entire runtime constructs and consumes events from itrader.events_handler.events — events_handler/event.py DELETED (big-bang, no shim)"
  - "Signal/Order/Fill events carry enum-typed action (Side) and order_type (OrderType); every in-scope action comparison uses Side members or enum-derived values"
  - "OrderType class-based enum with case-insensitive _missing_ in core/enums (string values; was a functional int enum)"
  - "OrderEvent.order_id required and always present; trading_interface minimal conformance with call-site uuid7 (D-12)"
  - "Portfolio maps Side→TransactionType at its fill boundary (D-05); _publish_error_event emits the frozen PortfolioErrorEvent with type=EventType.ERROR (D-06)"
  - "sltp_models return computed SL/TP levels instead of mutating frozen signals"
affects: [04-06, 04-07, 04-08]
tech-stack:
  added: []
  patterns:
    - "boundary parse at _generate_signal: Side(action) / OrderType(self.order_type) — strategies keep their string contract (M5b owns it)"
    - "entity-keeps-str rule: the Order ENTITY stores str action until M4; conversions via signal.action.value at construction and Side(order.action) at the event factory"
    - "enum-value comparison for entity strings: order.action == Side.SELL.value (validator), transactions.action == TransactionType.BUY.name (reporting) — zero bare string literals"
    - "frozen-event test mutation via dataclasses.replace (never attribute assignment)"
key-files:
  created: []
  modified:
    - itrader/core/enums/order.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/sltp_models/sltp_models.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order.py
    - itrader/order_handler/order_validator.py
    - itrader/execution_handler/matching_engine.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/transaction/transaction.py
    - itrader/trading_system/trading_interface.py
    - itrader/events_handler/full_event_handler.py
    - itrader/reporting/plots.py
    - "18 test files (tests/unit/events|order|execution|portfolio|strategy, tests/integration)"
  deleted:
    - itrader/events_handler/event.py
key-decisions:
  - "OrderType converted to class-based enum with case-insensitive _missing_ (string values MARKET/STOP/LIMIT): the plan's boundary parse OrderType('market') requires it and the functional int enum could not parse strings; zero .value/constructor callers existed, so the conversion is ripple-free"
  - "sltp_models reworked to RETURN computed levels instead of mutating the signal: in-place mutation of frozen events raises FrozenInstanceError and fails mypy strict; zero in-scope callers (only out-of-scope my_strategies used the old contract)"
  - "plots.py action comparisons converted to TransactionType.BUY.name (entity-derived strings, behavior-identical) so the zero-string-literal acceptance grep holds repo-wide despite the plan's 'plots.py untouched' note"
  - "Tasks 1+2 landed as a single commit (sanctioned by the plan's NOTE ON COMMITS): old-package tests construct str-action events that the Side-typed production path cannot keep green between tasks — D-22 outranks intra-plan bisect granularity"
metrics:
  duration: "~22 min"
  completed: "2026-06-05"
  tasks: 3
  files: 51
---

# Phase 4 Plan 05: Big-Bang Events Cutover Summary

The whole codebase (31 production + 18 test files) now runs on the frozen events package with Side/OrderType enum typing, required linkage IDs, and the type=ERROR PortfolioErrorEvent — events_handler/event.py is deleted with no shim, the suite is 397 green (zero tests lost), mypy strict is clean, and both oracle layers reproduce byte-exact with unmodified assertions (M3-01 landed on the live run path).

## Tasks Completed

| Task | Name | Commit(s) | Key Files |
| ---- | ---- | --------- | --------- |
| 1+2 | Production cutover (imports, keyword construction, Side/OrderType typing, required IDs, ErrorEvent) + tests/scripts cutover | 9f6dbcc | strategy base, order_manager/order/validator, matching_engine, simulated, portfolio_handler, transaction, trading_interface, full_event_handler, core/enums/order.py + 18 test files |
| 3 | Delete events_handler/event.py + final sweep | 6c91d24 | event.py (DELETED), reporting/plots.py |

## What Was Built

- **Import cutover:** every `from itrader.events_handler.event import ...` in itrader/ and tests/ repointed to `itrader.events_handler.events`; `full_event_handler.py` and `backtest_trading_system.py` take EventType from its single definition surface; `event.py` deleted (488 lines), bytecode cleared.
- **D-05 enum typing:** `_generate_signal` parses `action=Side(action)` / `order_type=OrderType(self.order_type)` at the strategy boundary (case-insensitive `_missing_` raises on unknown strings, T-04-12); comparison sites converted — `order_manager` (SL/TP inversion on `is Side.SELL`, exit sizing gate), `matching_engine` (stop/limit trigger direction), `portfolio_handler` (`TransactionType.BUY if fill_event.action is Side.BUY else TransactionType.SELL` — the D-05 boundary map), `transaction.py` (`TransactionType(filled_order.action.value)`), `sltp_models` (~12 sites), validator (`order.action == Side.SELL.value` — entity str until M4).
- **OrderType (core/enums/order.py):** class-based with explicit string values + FillStatus-style `_missing_`; `order_type_map`/`order_status_map` kept for remaining consumers. `Order.new_order` uses `signal.order_type` directly (map lookup + bare ValueError collapsed); `_build_primary_order` dispatches on enum members.
- **D-12 required IDs:** `trading_interface` constructs both OrderEvents keyword-form with `order_id=uuid_compat.uuid7()` at the call site plus explicit `order_type` (the old code omitted the required order_type field entirely — latent TypeError on the D-live path, now correct); `BINANCE_Live` TimeEvent keyword-form.
- **D-06 ErrorEvent:** `_publish_error_event` constructs the frozen `PortfolioErrorEvent` from the new package — field names unchanged, `source="portfolio"` from the child default, `time=datetime.now(UTC)` kept with the wall-clock carve-out comment (error paths never fire during a green oracle run). The event now carries `type=EventType.ERROR`; the dispatch chain has no ERROR branch yet (equivalent latent behavior to the old missing-UPDATE branch — Plan 04-06 adds the route).
- **Numeric boundary preservation (D-04/T-04-14):** every float()/Decimal coercion bit-identical; the fee/slippage models keep their lowercase-string contract via `event.action.value.lower()` in `simulated.py`.
- **Tests:** keyword-form pass over 18 files; `Side`/`OrderType` members at every construction; required `fill_id`/`order_id`/`strategy_id` supplied via small fixture factories in portfolio tests; schema tests extended for event_id/created_at/child_order_ids/fill_id/strategy_id (+3 tests); `test_order_manager` frozen-event mutation replaced with `dataclasses.replace`; `test_event_wiring` EventType import repointed (fixture intact).

## Verification Results

- `grep` old-path imports in itrader/ tests/ scripts/ → 0; `event.py` does not exist; `git log` records the deletion as the dedicated Task 3 commit
- `grep "action == ['\"]"` in itrader/ (excl. my_strategies) → 0; sweep greps `EventType.PING` / `event_type_map` / `\.verified` / `PingEvent` → all 0
- Full suite: **397 passed** at both commits (baseline 394 + 3 new schema tests; zero tests lost in collection)
- `tests/integration/test_backtest_oracle.py`: **2 passed UNMODIFIED** — behavioral + numerical oracle byte-exact (M3-04, D-22); `git diff` over the oracle file empty
- `poetry run mypy itrader` (the `make typecheck` command): Success — 134 files at 9f6dbcc, 133 at 6c91d24 (event.py removed)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] OrderType could not parse strings — converted to class-based enum with `_missing_`**
- **Found during:** Task 1 (strategy-base boundary parse)
- **Issue:** the plan instructs `order_type=OrderType(self.order_type)` "(the `_missing_` classmethods handle case)", but OrderType was a functional `Enum("OrderType", "MARKET STOP LIMIT")` with int values and no `_missing_` — `OrderType("market")` raised ValueError unconditionally
- **Fix:** class-based OrderType with string values + the FillStatus-style case-insensitive `_missing_`; zero `.value` consumers or constructor callers existed, so no ripple
- **Files modified:** itrader/core/enums/order.py
- **Commit:** 9f6dbcc

**2. [Rule 1 - Bug] sltp_models mutated frozen SignalEvents**
- **Found during:** Task 1 (the plan only listed the action-comparison updates)
- **Issue:** `calculate_sl`/`calculate_tp` wrote `signal.stop_loss = ...` — FrozenInstanceError at runtime and mypy-strict errors against the frozen dataclass
- **Fix:** functions return the computed level (float) instead of mutating; Side comparisons applied; zero in-scope callers (only out-of-scope my_strategies used the mutation contract)
- **Files modified:** itrader/strategy_handler/sltp_models/sltp_models.py
- **Commit:** 9f6dbcc

**3. [Rule 1 - Bug] fee/slippage `side=event.action.lower()` broke with Side-typed action**
- **Found during:** Task 1 (simulated exchange read-through; not in the plan's site inventory)
- **Issue:** `Side.BUY.lower()` is an AttributeError — this is on the oracle-critical fill path
- **Fix:** `event.action.value.lower()` at both model calls, preserving the models' lowercase-string contract
- **Files modified:** itrader/execution_handler/exchanges/simulated.py
- **Commit:** 9f6dbcc

**4. [Rule 3 - Blocking] frozen-event mutation in test fixture**
- **Found during:** Task 2
- **Issue:** `test_unknown_order_id_is_safe` assigned `fake.order_id = 999999` on a now-frozen FillEvent
- **Fix:** `dataclasses.replace(fill, order_id=999999)`
- **Files modified:** tests/unit/order/test_order_manager.py
- **Commit:** 9f6dbcc

### Minor in-scope clarifications

- **plots.py comparison form (Task 3):** the plan's action text says plots.py is "untouched if the entity keeps str", but the acceptance grep demands zero `action == ['\"]` matches repo-wide (excl. my_strategies). Converted the two DataFrame comparisons to `transactions.action == TransactionType.BUY.name` — behavior-identical (the frame column holds `Transaction.type.name` strings) and satisfies both constraints. Commit 6c91d24.
- **Plan line numbers vs. reality:** the plan's verified inventory cited `order_validator.py:424-425` as `signal.action` comparisons; the validator has been entity-based since 04-02, so those sites compare the str-typed entity — converted to `Side.X.value` comparisons (no parse overhead, gate-clean). `matching_engine` sites were at :106/:117 (book holds Side-typed OrderEvents → `is Side.SELL`).
- **trading_interface order_type:** the old constructions omitted the required `order_type` positional field — a latent TypeError on the (never-exercised) D-live path. The keyword-form fix adds `OrderType.MARKET`/`OrderType.LIMIT` explicitly as part of the D-12 minimal conformance.
- **Tasks 1+2 single commit:** explicitly sanctioned by the plan's NOTE ON COMMITS — old-package tests construct str-action events that the Side-typed production pipeline cannot keep green between the two tasks.
- Worktree environment notes from 04-01..04-04 applied: all test runs with `PYTHONPATH=<worktree-root>`, `poetry run mypy itrader` in place of `make typecheck`/`make test` (gitignored `.env` absent in the worktree).

## Known Stubs

None — no placeholder values or unwired data introduced. The EventType.ERROR dispatch route is deliberately absent until Plan 04-06 (stated plan design, equivalent latent behavior to the legacy missing-UPDATE branch).

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-12 mitigated (Side/OrderType `_missing_` raise ValueError on unknown strings — OrderType gained the classmethod this plan); T-04-13 mitigated (event.py deleted, zero old-path-import greps, single definition surface); T-04-14 mitigated (float()/Decimal coercions preserved bit-identical; oracle byte-exact at every commit).

## TDD Gate Compliance

Not applicable — plan type is `execute` (behavior-preserving cutover), not `tdd`.

## Self-Check: PASSED

- `itrader/events_handler/event.py` does not exist; `itrader/events_handler/events/__init__.py` exists (single import surface)
- Commits exist: 9f6dbcc, 6c91d24
- Deletion check: only the intentional `event.py` deletion across both commits (`git diff --diff-filter=D` for 9f6dbcc empty)
- Oracle assertions untouched: `git diff` over `tests/integration/test_backtest_oracle.py` empty across the plan
