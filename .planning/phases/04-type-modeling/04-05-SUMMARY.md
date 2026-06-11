---
phase: 04-type-modeling
plan: 05
subsystem: order
tags: [enums, mypy, type-modeling, newtype, ids, order-domain, D-06, D-12, D-03, D-13]

# Dependency graph
requires:
  - phase: 04-type-modeling
    provides: "04-04 converted OrderStatus/OrderCommand to class-based string enums and established the value-equal enum + case-insensitive _missing_ house pattern in core/enums/order.py"
  - phase: 04-type-modeling
    provides: "Wave 1 established the core/ids NewType aliases (OrderId/PortfolioId/StrategyId) over uuid.UUID (D-12)"
  - phase: 03-hot-path-performance
    provides: "byte-exact golden oracle (134 trades / final_equity 46189.87730727451) — the gate this plan holds"
provides:
  - "MarketExecution class-based string-valued enum (IMMEDIATE='immediate'/NEXT_BAR='next_bar', value-equal) with case-insensitive _missing_, re-exported from core/enums (D-06)"
  - "market_execution coerced to the enum at the OrderManager ctor boundary (str|MarketExecution in, enum stored); NO OrderConfig model (SYN-05 split, deferred 999.5-(b))"
  - "Every order-domain public-API / factory entity-id annotation retyped int/Any -> core/ids NewType (OrderId/PortfolioId/StrategyId) across order_manager.py / order_handler.py / order.py (D-12)"
  - "_PendingBracket.portfolio_id tightened PortfolioId|int -> PortfolioId; IN-06 cast(int,...) child-cancel bridge removed (now type-correct)"
  - "D-03 lean MarketExecution enum unit coverage in tests/unit/core/test_enums.py"
affects: [order-manager-decomposition, naming-encapsulation, 999.5-OrderConfig]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Value-equal config enum coerced at a ctor boundary: the param accepts str|Enum for backward-compat but stores the enum member (MarketExecution(market_execution)); .value stays the byte-identical literal so the stored config is unchanged"
    - "NewType id annotation tightening is runtime-identical (NewType is identity); mypy --strict is the sole gate, and tightening a public param can surface internal callers that previously relied on a widened/cast type (the IN-06 cast bridge)"

key-files:
  created:
    - .planning/phases/04-type-modeling/04-05-SUMMARY.md
  modified:
    - itrader/core/enums/order.py
    - itrader/core/enums/__init__.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order.py
    - tests/unit/core/test_enums.py
    - tests/unit/order/test_order_manager.py

key-decisions:
  - "market_execution coercion stores the enum (self.market_execution = MarketExecution(market_execution)) at the OrderManager ctor boundary; OrderHandler keeps a str pass-through (coercion lives at the one boundary, per the plan interface block)"
  - "_PendingBracket.portfolio_id tightened PortfolioId|int -> PortfolioId: it is only ever fed signal_event.portfolio_id (a PortfolioId) and consumed by the now-PortfolioId new_stop/limit_order factories — the legacy | int was a dead widener and was blocking the D-12 retype (Rule 3)"
  - "The IN-06 cast(int, child_id)/cast(int, order.portfolio_id) bridge in the terminal-parent child-cancel path was removed: child_id is already OrderId and order.portfolio_id already PortfolioId, so the casts were both wrong (cast to int) and unnecessary once cancel_order declares the NewTypes; the now-unused `cast` import was dropped"

patterns-established:
  - "Config-domain string boundary (market_execution) follows the same value-equal class-based enum + case-insensitive _missing_ house pattern as the order-status/operation vocabularies, coerced once at the owning ctor"

requirements-completed: [TYPE-03, TYPE-02]

# Metrics
duration: ~15min
completed: 2026-06-11
---

# Phase 4 Plan 05: Order-Domain Type-Modeling Closeout Summary

**MarketExecution value-equal enum added and coerced at the OrderManager ctor boundary (D-06, no OrderConfig per SYN-05), every order-domain public-API/factory entity-id annotation retyped int/Any -> OrderId/PortfolioId/StrategyId (D-12) with the IN-06 cast bridge removed, D-03 MarketExecution tests added — golden byte-exact (134/46189.87730727451), mypy --strict clean, e2e 58/58.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-06-11
- **Tasks:** 2
- **Files modified:** 7 (5 source + 2 test)

## Accomplishments

- **D-06:** Added `MarketExecution(Enum)` to `core/enums/order.py` with `IMMEDIATE="immediate"`/`NEXT_BAR="next_bar"` (`.value` EQUAL to the exact current literals) and a case-insensitive `_missing_` raising a clear f-string `ValueError` (OrderType house pattern). Re-exported from the `core/enums` barrel + `__all__`. Coerced at the `OrderManager` ctor boundary: the param annotation became `str | MarketExecution` (backward-compat), and the ctor now stores the enum member (`self.market_execution = MarketExecution(market_execution)` — the `_missing_` parses a string; an enum member is a no-op coercion). `OrderHandler`'s ctor param annotation was retyped the same way and passes the value through to `OrderManager` (the single coercion boundary). **No `OrderConfig` model / `config/order.py` was created** (SYN-05 split; the model + threading is deferred to 999.5-(b)).
- **D-12:** Retyped every order-domain public-API and factory entity-id annotation from `int`/`Optional[int]`/`Optional[Any]`/`Any` to its `core/ids` NewType:
  - `order_manager.py` — `modify_order`/`cancel_order`/`get_order_by_id`/`get_order_history` `order_id -> OrderId`; `modify_order`/`cancel_order` + the whole `get_*` block `portfolio_id -> Optional[PortfolioId]`.
  - `order_handler.py` — the matching facade methods (`modify_order`/`cancel_order`/`get_order_by_id`/`get_orders_by_status`/`get_active_orders`/`get_order_history`/`get_orders_by_ticker`/`search_orders`/`get_orders_summary`) `int`/`Any -> OrderId`/`PortfolioId`.
  - `order.py` — `new_stop_order`/`new_limit_order` factory params `strategy_id: Any -> StrategyId`, `portfolio_id: Any -> PortfolioId`.
  - Annotation-only; NewType is runtime-identity. `mypy --strict` is the sole gate.
- **D-13 carve-out:** `user_id` annotations untouched (still `int`); `trading_interface.py` and `screeners/base.py` untouched (git diff empty for both).
- **D-03:** `tests/unit/core/test_enums.py` extended with lean MarketExecution coverage (member `.value`s equal the literals, case-insensitive `_missing_` parse, clear-error f-string `ValueError`), matching the existing 4-space house shape and `import pytest` / `from itrader.core.enums import ...` idiom; `unit` marker folder-derived.

## Task Commits

1. **Task 1: Add MarketExecution enum + coerce at the OrderManager ctor boundary (D-06)** - `0473047` (feat)
2. **Task 2: Retype order-domain public-API + factory entity-id annotations to NewTypes (D-12) + D-03 MarketExecution tests** - `aa4afd6` (feat)

## Files Created/Modified

- `itrader/core/enums/order.py` - added value-equal `MarketExecution` enum (IMMEDIATE/NEXT_BAR) with case-insensitive `_missing_`
- `itrader/core/enums/__init__.py` - re-export `MarketExecution` in the order-enum block + `__all__`
- `itrader/order_handler/order_manager.py` - ctor coerces `market_execution` to the enum (param `str | MarketExecution`); order-domain id annotations -> NewTypes; `_PendingBracket.portfolio_id` `PortfolioId|int -> PortfolioId`; removed the IN-06 `cast(int,...)` child-cancel bridge + the now-unused `cast` import
- `itrader/order_handler/order_handler.py` - imports `MarketExecution` + `OrderId`/`PortfolioId`; ctor param `str | MarketExecution`; facade-method id annotations -> NewTypes
- `itrader/order_handler/order.py` - `new_stop_order`/`new_limit_order` factory params `Any -> StrategyId`/`PortfolioId`
- `tests/unit/core/test_enums.py` - D-03 MarketExecution coverage (3 new tests)
- `tests/unit/order/test_order_manager.py` - ctor assertion updated to enum-member identity (`is MarketExecution.IMMEDIATE`/`NEXT_BAR`) downstream of the D-06 coercion

## Decisions Made

- **market_execution stored as the enum, OrderHandler stays str pass-through:** Per the plan interface block, the coercion lives at the single `OrderManager` ctor boundary. `OrderHandler.__init__` retains `self.market_execution = market_execution` (a str) and forwards the value; `OrderManager` is the one place that calls `MarketExecution(...)`. This keeps a single coercion boundary and a backward-compatible `str` entry on both ctors.
- **No `OrderConfig` model:** Only the enum landed (SYN-05 split). `grep` confirms no `itrader/config/order.py`. The config model + threading is NEW CONTRACT WORK deferred to 999.5-(b).
- **`_PendingBracket.portfolio_id` tightened to `PortfolioId`:** The field's legacy `"PortfolioId | int"` union was the only thing widening a value that is always a `PortfolioId` (fed `signal_event.portfolio_id`, consumed by the now-`PortfolioId` factories). Tightening it resolved the blocking mypy error the D-12 factory retype surfaced and matches the runtime reality.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated the OrderManager ctor test asserting market_execution as a string**
- **Found during:** Task 1 (the D-06 coercion stores the enum member, not the raw string)
- **Issue:** `tests/unit/order/test_order_manager.py::test_*init*` asserted `order_manager.market_execution == "immediate"` / `== "next_bar"`. After the ctor coercion, `market_execution` carries a `MarketExecution` member; a plain `Enum` member is not `==` its `.value` string, so the assertions would fail.
- **Fix:** Imported `MarketExecution`; changed the two assertions to enum-member identity (`is MarketExecution.IMMEDIATE` / `is MarketExecution.NEXT_BAR`).
- **Files modified:** `tests/unit/order/test_order_manager.py`
- **Verification:** `tests/unit/order/test_order_manager.py` 26 passed.
- **Committed in:** `0473047` (Task 1 commit)

**2. [Rule 3 - Blocking] Tightened _PendingBracket.portfolio_id and removed the IN-06 cast bridge**
- **Found during:** Task 2 (the D-12 factory + cancel_order retypes surfaced 4 internal call-site mypy errors)
- **Issue:** `new_stop_order`/`new_limit_order` now declare `portfolio_id: PortfolioId`, but they were called with `pending.portfolio_id` typed `PortfolioId | int`; and `cancel_order` now declares `OrderId`/`PortfolioId`, but the child-cancel path passed `cast(int, child_id)` / `cast(int, order.portfolio_id)` (the deferred IN-06 bridge). mypy --strict reported 4 `arg-type` errors.
- **Fix:** Tightened `_PendingBracket.portfolio_id` `PortfolioId|int -> PortfolioId` (it is only ever fed a `PortfolioId`); removed the two `cast(int, ...)` wrappers in the terminal-parent child-cancel loop (child_id is already `OrderId`, order.portfolio_id already `PortfolioId`) and dropped the now-unused `cast` import. Annotation/cast-only; runtime-identical.
- **Files modified:** `itrader/order_handler/order_manager.py`
- **Verification:** `mypy --strict itrader` clean (140 files); order unit suite 145 passed; golden byte-exact.
- **Committed in:** `aa4afd6` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 test fix downstream of the D-06 coercion, 1 Rule 3 blocking mypy fix downstream of the D-12 retype).
**Impact on plan:** Both plan tasks landed as written; the deviations are the mechanical, intended downstream of the value-equal coercion + NewType tightening. No scope creep (no `OrderConfig`, no `user_id`/off-path changes).

## Issues Encountered

- **Pre-existing, out-of-scope:** `tests/unit/portfolio/test_position_manager.py` fails at collection (stale import). Unrelated to these changes; logged in `.planning/phases/04-type-modeling/deferred-items.md`; excluded from the self-check per the orchestrator note (`--ignore`).

## Verification Results

- `mypy --strict itrader`: clean (140 source files) — the sole D-12 gate.
- `python -c "from itrader.core.enums import MarketExecution; assert MarketExecution.IMMEDIATE.value=='immediate'; assert MarketExecution('next_bar') is MarketExecution.NEXT_BAR"`: OK.
- No `OrderConfig` / `config/order.py` created (`ls` confirms absent).
- `git diff` shows `trading_interface.py` and `screeners/base.py` untouched; no `user_id` annotation changed.
- `grep -c 'OrderId\|PortfolioId\|StrategyId' order_manager.py`: 20.
- `python scripts/run_backtest.py`: 134 trades / final_equity 46189.87730727451 (golden byte-exact).
- `pytest tests/e2e -m e2e`: 58 passed.
- `pytest tests/unit/core/test_enums.py`: 19 passed (incl. the 3 new D-06 MarketExecution assertions).
- `pytest tests/unit/order`: 145 passed.
- `pytest tests/unit --ignore=tests/unit/portfolio/test_position_manager.py`: 754 passed.

## Threat Flags

None — the plan's threat register dispositions held. The single `mitigate` item (T-04-05-PARSE: the new `MarketExecution._missing_`) is a positive hardening of an existing internal ctor string boundary (loud `ValueError` on unknown strings). No new network/auth/file/schema surface introduced (enum + annotation changes only); the value-equal coercion and NewType retypes are runtime-identical and the oracle is byte-exact.

## Self-Check: PASSED

- Created files exist: `.planning/phases/04-type-modeling/04-05-SUMMARY.md`.
- Task commits exist: `0473047`, `aa4afd6`.
- STATE.md / ROADMAP.md untouched (orchestrator-owned, per the parallel-execution contract).

## Next Phase Readiness

- Phase 4 type modeling order-domain closeout complete: the last stringly-typed boundary (`market_execution`) and the order-domain `int`/`Any` id defects are closed; mypy --strict is the standing gate.
- `OrderConfig` model + threading remains deferred to 999.5-(b) (SYN-05 split) — no blocker for the phase.

---
*Phase: 04-type-modeling*
*Completed: 2026-06-11*
