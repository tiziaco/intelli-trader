---
phase: 04-type-modeling
plan: 04
subsystem: order
tags: [enums, mypy, type-modeling, dataclass-freeze, order-domain, D-01, D-02, D-04, D-07, D-03]

# Dependency graph
requires:
  - phase: 04-type-modeling
    provides: "04-01 froze operation_result.py DTO shape (frozen/slots/kw_only + tuple fields)"
  - phase: 04-type-modeling
    provides: "04-02 established the class-based enum + case-insensitive _missing_ pattern in core/enums"
  - phase: 03-hot-path-performance
    provides: "byte-exact golden oracle (134 trades / final_equity 46189.87730727451) — the gate this plan holds"
provides:
  - "OrderStatus/OrderCommand as class-based string-valued enums (member name == .value) with case-insensitive _missing_ (D-01)"
  - "OrderOperationType (11 members) / OrderTriggerSource (10 members) value-equal enums re-exported from core/enums (D-04)"
  - "OperationResult.operation_type retyped str -> OrderOperationType (field + both factory params) (D-04)"
  - "_PendingBracket frozen=True, slots=True, kw_only=True (D-07)"
affects: [04-type-modeling subsequent plans, order-manager-decomposition, naming-encapsulation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Class-based string-valued enum (member name == .value or value-equal literal) + case-insensitive _missing_ raising a clear f-string ValueError (OrderType house template)"
    - "Value-equal carrier swap: the annotation type changes (str -> enum), the .value does not, so audit records/logs/serialization stay byte-identical"
    - "Enum .value serialization at an audit edge (get_order_history triggered_by) to preserve the prior lowercase string output"

key-files:
  created:
    - .planning/phases/04-type-modeling/04-04-SUMMARY.md
  modified:
    - itrader/core/enums/order.py
    - itrader/core/enums/__init__.py
    - itrader/order_handler/operation_result.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order.py
    - itrader/order_handler/storage/in_memory_storage.py
    - tests/unit/core/test_enums.py
    - tests/unit/order/test_admission_rules.py
    - tests/unit/order/test_on_signal.py
    - tests/unit/order/test_order.py
    - tests/unit/order/test_order_manager.py
    - tests/unit/order/test_order_storage.py

key-decisions:
  - "OrderOperationType has 11 members (not the 10 listed in the plan interface block): the grep-the-file-first directive surfaced an 11th literal, signal_sizing, used as the _reject_unsized_signal operation_type default — the enum includes a member for EVERY literal actually used"
  - "OrderTriggerSource has 10 members (not the 8 in the plan interface block): the codebase also passes 'strategy' (order.py new_order factory) and 'exchange' (mark_filled) to add_state_change — both included per the every-distinct-literal rule"
  - "operation_type/triggered_by defaults removed (option a): every OperationResult construction already supplies operation_type, so the param/field are non-defaulted enum types (no '' sentinel, no Optional)"
  - "get_order_history serializes triggered_by via .value (not .name): the prior output was the lowercase value string ('admission_direction'); .value preserves it byte-identically, whereas .name would emit ADMISSION_DIRECTION"

patterns-established:
  - "Order-domain audit fields carry enum MEMBERS (D-04 intent), serialize via .value at the audit edge; tests assert identity against members (is OrderTriggerSource.X)"

requirements-completed: [TYPE-03, TYPE-04, TYPE-01]

# Metrics
duration: ~20min
completed: 2026-06-11
---

# Phase 4 Plan 04: Order-Domain Vocabulary Hardening Summary

**OrderStatus/OrderCommand converted to class-based string enums (D-01), OrderOperationType/OrderTriggerSource value-equal vocabularies added + OperationResult.operation_type retyped str->OrderOperationType with every call-site swapped to members (D-04), _PendingBracket frozen/slots/kw_only (D-07), D-03 enum tests added — golden byte-exact (134/46189.87730727451), mypy --strict clean, e2e 58/58.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-11
- **Tasks:** 3
- **Files modified:** 12 (6 source + 6 test)

## Accomplishments

- **D-01:** `OrderStatus` (6 members) and `OrderCommand` (3 members) converted from the functional `Enum("Name", "...")` auto-int form to class-based string-valued enums (member name == `.value`) with a case-insensitive `_missing_` raising a clear f-string `ValueError` (OrderType house pattern). `order_status_map`, `order_command_map`, and `VALID_ORDER_TRANSITIONS` carried over unchanged (member identity is unaffected — only `.value` flips int->string).
- **D-02 audit (recorded):** clean. `grep -rn 'status\.value\s*==\s*[0-9]' itrader tests` returns no matches; both serializers (`reporting/orders.py:91`, `order.py:133`) use `.name`, never `.value`. No serializer was switched to `.value`. The int->string flip is byte-inert.
- **D-04:** `OrderOperationType` (11 members) and `OrderTriggerSource` (10 members) added to `core/enums/order.py` with `.value` EQUAL to the exact current string literals, each with a case-insensitive `_missing_`, both re-exported from the `core/enums` barrel + `__all__`. `OperationResult.operation_type` retyped `str -> OrderOperationType` (field + both factory params, defaults removed). Every `operation_type=`/`triggered_by=` call-site in `order_manager.py`/`order.py` swapped to enum members; the carrier type changed, the value did not. Reconciliation/reservation-release LOGIC frozen.
- **D-07:** `_PendingBracket` decorator changed `frozen=True` -> `frozen=True, slots=True, kw_only=True`. The single construction site (order_manager.py:626) was already fully keyword.
- **D-03:** `tests/unit/core/test_enums.py` extended with coverage for OrderStatus/OrderCommand/OrderOperationType/OrderTriggerSource (`.value`s, case-insensitive `_missing_` parse, `*_map` round-trip, `.name`-serialization invariant, clear-error f-string).

## Task Commits

1. **Task 1: Convert OrderStatus/OrderCommand to class-based string enums + D-02 audit (D-01/D-02)** - `1332fed` (feat)
2. **Task 2: Add OrderOperationType/OrderTriggerSource, retype OperationResult, value-equal swap (D-04)** - `7fa8f1f` (feat)
3. **Task 3: Freeze _PendingBracket (slots+kw_only) + D-03 enum tests (D-07/D-03)** - `4e2cb73` (feat)

## Files Created/Modified

- `itrader/core/enums/order.py` - class-based OrderStatus/OrderCommand + new OrderOperationType/OrderTriggerSource (all with case-insensitive `_missing_`)
- `itrader/core/enums/__init__.py` - re-export OrderOperationType/OrderTriggerSource in the order-enum block + `__all__`
- `itrader/order_handler/operation_result.py` - `operation_type` field + both factory params retyped `str -> OrderOperationType` (defaults removed); imports OrderOperationType
- `itrader/order_handler/order_manager.py` - every `operation_type=`/`triggered_by=` site uses enum members; `_PendingBracket` frozen/slots/kw_only; imports the two new enums
- `itrader/order_handler/order.py` - `OrderStateChange.triggered_by` field + `add_state_change` param retyped to OrderTriggerSource (default SYSTEM); positional/keyword literal call-sites swapped to members
- `itrader/order_handler/storage/in_memory_storage.py` - `get_order_history` serializes `triggered_by` via `.value` (byte-identical audit output)
- `tests/unit/core/test_enums.py` - D-03 order-enum coverage (13 new assertions across 4 enums)
- `tests/unit/order/{test_admission_rules,test_on_signal,test_order,test_order_manager,test_order_storage}.py` - assertions/constructions updated to OrderTriggerSource members (downstream of the D-04 retype)

## Decisions Made

- **OrderOperationType member count (11, not 10):** The plan interface block listed 10 literals; the action's "grep the file first — there must be a member for EVERY literal actually used" directive surfaced an 11th, `signal_sizing` (the `_reject_unsized_signal` `operation_type` default). Added `SIGNAL_SIZING = "signal_sizing"`.
- **OrderTriggerSource member count (10, not 8):** The plan interface block listed 8 (system/user/validator/cash_reservation/sizing_policy/admission_direction/admission_increase/admission_max_positions). Grepping `add_state_change` call-sites found two more distinct literals actually passed: `"strategy"` (order.py `new_order` factory) and `"exchange"` (order.py `mark_filled`). Both added per the every-distinct-literal rule.
- **No `""` default sentinel:** Every OperationResult construction already passes `operation_type` (verified by grepping all `success_result`/`failure_result`/`OperationResult(` sites), so the field and both factory params are non-defaulted `OrderOperationType` — option (a). No `Optional`/`None` needed.
- **`get_order_history` serializes `.value`:** The prior dict output was the lowercase value string (e.g. `"admission_direction"`). Using `.value` keeps the serialized audit output byte-identical; `.name` would have changed it to `ADMISSION_DIRECTION`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated order-domain tests asserting/constructing triggered_by as a string**
- **Found during:** Task 2 (the D-04 retype made `OrderStateChange.triggered_by` an enum member)
- **Issue:** `tests/unit/order/{test_admission_rules,test_on_signal,test_order,test_order_manager,test_order_storage}.py` asserted `last_change.triggered_by == "<string>"` and constructed `add_state_change(..., triggered_by="<string>")` / positional string. After the retype, `triggered_by` carries an OrderTriggerSource member, so string equality fails and string construction violates the type contract.
- **Fix:** Imported `OrderTriggerSource` into each file; assertions changed to `is OrderTriggerSource.X`; constructions pass enum members (the placeholder `"test"` triggered_by in test_order_manager became `OrderTriggerSource.SYSTEM`).
- **Files modified:** the five `tests/unit/order/` files above.
- **Verification:** full order unit suite 145 passed; broad unit suite 463 passed.
- **Committed in:** `7fa8f1f` (Task 2 commit)

**2. [Rule 1 - Bug] get_order_history audit serialization retyped to .value**
- **Found during:** Task 2 (`.triggered_by` consumer scan)
- **Issue:** `in_memory_storage.py::get_order_history` serialized `change.triggered_by` directly into a dict; after the retype it would emit an enum member object instead of the prior string.
- **Fix:** Serialize `change.triggered_by.value` (the field's `.value` equals the prior literal — byte-identical). Consistent with the sibling `from_status`/`to_status` `.name` serialization in the same dict.
- **Files modified:** `itrader/order_handler/storage/in_memory_storage.py`
- **Committed in:** `7fa8f1f` (Task 2 commit)

**3. [Rule 1 - Bug] Docstring prose mentions of triggered_by literals updated to enum members**
- **Found during:** Task 2 (the value-equal swap perl also rewrote docstring/comment prose like `(triggered_by="admission_direction")`)
- **Issue:** Several docstrings/comments in order_manager.py referenced the old string-literal form; after the swap they were updated to `OrderTriggerSource.X` for consistency with the code (and to keep the D-04 `grep -c 'triggered_by="' == 0` audit clean — no kwarg or prose string-literal form remains).
- **Fix:** Non-functional documentation consistency; no behavior change.
- **Files modified:** `itrader/order_handler/order_manager.py`
- **Committed in:** `7fa8f1f` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 1 — downstream of the intended D-04 retype, no scope creep).
**Impact on plan:** All three plan tasks landed as written; the deviations are the mechanical, intended downstream of the value-equal carrier swap.

## Issues Encountered

- **Pre-existing, out-of-scope:** `tests/unit/portfolio/test_position_manager.py` fails at collection (stale `PositionEvent` import). Reproduced on this plan's base commit; unrelated to these changes. Logged in `.planning/phases/04-type-modeling/deferred-items.md`; excluded from self-check per the orchestrator note.

## Verification Results

- `mypy --strict itrader`: clean (140 source files).
- D-02 audit: clean — `grep -rn 'status\.value\s*==\s*[0-9]' itrader tests` no matches; serializers use `.name`.
- `grep -nE 'operation_type:\s*str' itrader/order_handler/operation_result.py`: no matches (field + both factory params retyped).
- `grep -c 'operation_type="' order_manager.py`: 0; `grep -c 'triggered_by="' order_manager.py order.py`: 0.
- `from itrader.core.enums import OrderOperationType, OrderTriggerSource`: resolves.
- `python scripts/run_backtest.py`: 134 trades / final_equity 46189.87730727451 (golden byte-exact, run after each of the 3 tasks).
- `pytest tests/e2e -m e2e`: 58 passed.
- `pytest tests/unit/core/test_enums.py`: 16 passed (incl. the 13 new D-03 order-enum assertions).
- Broad suites (excluding the pre-existing broken `test_position_manager.py`): unit 463 passed; integration + portfolio 183 passed.

## Threat Flags

None — the plan's threat register dispositions held. The single `mitigate` item (T-04-04-PARSE: the new `_missing_` parsers) is a positive hardening of an existing internal string boundary (loud ValueError on unknown strings). No new network/auth/file/schema surface introduced (enum/annotation/immutability changes only); the value-equal swap is `.name`/`.value`-inert by the D-02 audit and the oracle byte-exact confirmation.

## Self-Check: PASSED

- Created files exist: `.planning/phases/04-type-modeling/04-04-SUMMARY.md`.
- Task commits exist: `1332fed`, `7fa8f1f`, `4e2cb73`.
- STATE.md / ROADMAP.md untouched (orchestrator-owned, per parallel-execution contract).

---
*Phase: 04-type-modeling*
*Completed: 2026-06-11*
</content>
</invoke>
