---
phase: 05-engine-native-trailing-stops
plan: 01
subsystem: order-domain
tags: [trailing-stop, order-type, config-enum, validation, dual-layer, TRAIL-01]

# Dependency graph
requires:
  - phase: 05-engine-native-trailing-stops
    plan: 00
    provides: collectible pytest.skip Wave-0 stubs (test_trailing_validation.py turned GREEN here)
provides:
  - OrderType.TRAILING_STOP first-class declarable order type + order_type_map entry
  - TrailType (PRICE/PERCENT) config-enum importable from itrader.config
  - OrderEvent.trail_type/trail_value carriage + Order.trail_type/trail_value fields
  - Order.new_trailing_stop_order factory (positive initial stop, trail_value via to_money)
  - D-TRAIL-7 dual-layer non-viable-trail rejection (domain validator + exchange agreement)
affects: [05-02, 05-03, trailing-stop]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config-enum exception: TrailType lives in config/order.py (order-domain cohesion), not core/enums/"
    - "getattr-default trail read-back (robust to order stubs predating the fields)"
    - "Pitfall 6 strategy (a): positive computed initial stop — positive-price gate NOT branched out for TRAILING_STOP"

key-files:
  created:
    - tests/unit/order/test_trailing_plumbing.py
  modified:
    - itrader/core/enums/order.py
    - itrader/config/order.py
    - itrader/config/__init__.py
    - itrader/events_handler/events/order.py
    - itrader/order_handler/order.py
    - itrader/order_handler/order_validator.py
    - itrader/execution_handler/exchanges/simulated.py
    - tests/unit/order/test_trailing_validation.py

decisions:
  - "TrailType placed in config/order.py (order-domain cohesion, PATTERNS A3) over config/exchange.py — config-enum exception per CONVENTIONS.md (stays out of core/enums to preserve the core->config dependency direction)"
  - "Pitfall 6 / Open Question 2 resolved with strategy (a) positive computed initial stop: the static price carries the fill-anchored INITIAL stop (positive), so the price <= 0 gate stays valid for TRAILING_STOP in BOTH validator layers — the gate is NOT branched out, keeping the spot oracle byte-exact"
  - "D-03a dual-layer agreement realised by NO contradictory rejection in SimulatedExchange.validate_order: the unchanged price <= 0 gate gives the same verdict as the domain validator for a viable trailing order (documented in-code)"

metrics:
  duration: 4min
  completed: 2026-06-17
---

# Phase 05 Plan 01: STATIC Trailing-Stop Plumbing Summary

**TRAILING_STOP is now a first-class declarable order type carrying trail_type/trail_value from the Order entity through OrderEvent, with a `new_trailing_stop_order` factory and a D-TRAIL-7 dual-layer viability gate (PERCENT < 1, PRICE < reference, positive trail_value/type) — all trail fields default no-op so the SMA_MACD spot oracle is byte-exact.**

## Performance

- **Duration:** ~4 min
- **Completed:** 2026-06-17
- **Tasks:** 2 (both TDD: RED -> GREEN)
- **Files:** 1 created, 8 modified (incl. tests)

## Accomplishments

- **OrderType.TRAILING_STOP** member + `order_type_map["TRAILING_STOP"]` entry (core/enums/order.py, TAB). Case-insensitive `_missing_` already resolves both `"trailing_stop"` and `"TRAILING_STOP"`. VALID_ORDER_TRANSITIONS untouched (keyed by OrderStatus, not OrderType).
- **TrailType (str, Enum)** config-enum (`PRICE`/`PERCENT`) in config/order.py (4-space, mirrors FeeModelType shape) + re-export from config/__init__.py. Importable as `from itrader.config import TrailType`.
- **OrderEvent.trail_type/trail_value** optional fields (4-space) after the existing defaulted fields, with getattr-default read-back in `new_order_event` (mirrors stop_price/leverage). TrailType imported under `TYPE_CHECKING` so the events package stays free of config import side effects.
- **Order.trail_type/trail_value** fields (TAB, after leverage) + `new_trailing_stop_order` classmethod copying `new_stop_order` with `OrderType.STOP` -> `OrderType.TRAILING_STOP`, keyword-only `trail_type`/`trail_value`, `trail_value` entered via `to_money` (D-TRAIL-8), leverage carried.
- **D-TRAIL-7 rejection** in `EnhancedOrderValidator._validate_critical_fields` (TAB? — 4-space file): gated on `order.type == OrderType.TRAILING_STOP`; emits `ValidationMessage(ERROR, ..., "trail_value", "INVALID_TRAIL")` for missing/non-positive trail_value or trail_type, PERCENT trail >= 1, or PRICE trail >= reference price. Decimal comparisons throughout (M5-10).
- **Dual-layer agreement (D-03a)** documented in `SimulatedExchange.validate_order`: the unchanged `event.price <= 0` gate gives the same accept/reject verdict for a viable trailing order with a positive initial stop.

## Task Commits

1. **Task 1 RED: failing plumbing tests** - `0d23a75` (test)
2. **Task 1 GREEN: STATIC trailing-stop plumbing** - `a74ec22` (feat)
3. **Task 2 RED: failing D-TRAIL-7 reject tests** - `e1b84eb` (test)
4. **Task 2 GREEN: D-TRAIL-7 dual-layer validation** - `3ef8f42` (feat)

## Decisions Made

- **TrailType placement:** config/order.py (order-domain cohesion, PATTERNS A3), NOT config/exchange.py and NOT core/enums/ — the config-enum exception (CONVENTIONS.md) keeps the core->config dependency direction intact.
- **Pitfall 6 / Open Question 2 strategy = (a) positive computed initial stop.** The TRAILING_STOP static `price` carries the fill-anchored INITIAL stop (positive; actual seeding lands in 05-03), so the `price <= 0` positive-price gate stays valid for trailing orders in BOTH validator layers. The gate is NOT branched out by order_type — this keeps the spot oracle byte-exact and the dual layers in agreement (D-03a).

## Deviations from Plan

None — plan executed as written. The plan's instruction to "mirror the SAME disposition in SimulatedExchange.validate_order" is satisfied by an in-code comment documenting that the unchanged price gate already agrees (strategy (a) means no executable change is needed at the exchange layer, only the documented agreement).

## Threat Surface

- **T-05-02 (Tampering — resting-order integrity, unviable trail placing stop <= 0):** mitigated — D-TRAIL-7 validates trail viability in the domain validator BEFORE the order rests; the exchange positive-price gate agrees (D-03a).
- **T-05-03 (Tampering — float entry into money math):** mitigated — `trail_value` enters Decimal only via `to_money`; all validator trail comparisons are Decimal-vs-Decimal.
- No new external/network/auth surface; zero package installs.

## Verification Results

- `OrderType('trailing_stop') is OrderType.TRAILING_STOP`, `order_type_map['TRAILING_STOP']`, `TrailType('percent')` all resolve (smoke import).
- `poetry run pytest tests/unit/order -k "trailing and reject"` -> 6 passed (05-00 stubs turned GREEN, not skip).
- `poetry run mypy --strict itrader` -> Success, no issues found in 185 source files (every OrderType arm handled; no assert_never break).
- `git diff --check` -> clean (TAB files stayed TAB, 4-space files stayed 4-space).
- Oracle byte-exact: `poetry run pytest tests/integration` -> 16 passed.
- Full suite: `poetry run pytest tests` -> **1160 passed, 10 skipped** (remaining 05-02/05-03 Wave-0 stubs); no strict-marker/warning regression.

## Known Stubs

None introduced by this plan. The 3 D-TRAIL-7 validation stubs from 05-00 were turned GREEN (and expanded to 6 reject + viable-pass cases). The remaining 10 skipped stubs belong to 05-02 (matching ratchet) and 05-03 (bracket + e2e) by design.

## Self-Check: PASSED

- `tests/unit/order/test_trailing_plumbing.py` exists on disk.
- All 4 task commits present in git log (0d23a75, a74ec22, e1b84eb, 3ef8f42).

## Next Phase Readiness

- The trailing contracts are fixed: 05-02 (MatchingEngine ratchet) and 05-03 (BracketManager seeding) build against `OrderType.TRAILING_STOP`, `TrailType`, the OrderEvent/Order trail fields, the `new_trailing_stop_order` factory, and the D-TRAIL-7 gate — no scavenger hunt.

---
*Phase: 05-engine-native-trailing-stops*
*Completed: 2026-06-17*
