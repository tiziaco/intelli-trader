---
phase: 05-signal-contract-reconcile-fragile
plan: 02
subsystem: order_handler
tags: [SIG-03, D-03, side-typing, admission-snapshot, byte-exact]
requires:
  - "Side enum (core/enums/event.py) with case-insensitive _missing_ parser"
  - "OrderEvent.action / SignalEvent.action already Side-typed (04-05 cutover)"
  - "PortfolioReadModel.get_position returning PositionView | None"
provides:
  - "Order.action: Side (entity field + new_stop_order/new_limit_order params)"
  - "_PendingBracket.action: Side"
  - "Single threaded admission Position snapshot (triple get_position collapsed)"
  - "W4-04 dual-layer validator-overlap convention pinned in CONVENTIONS.md"
affects:
  - "order_handler (order entity, brackets, validator, admission)"
  - "reporting/orders.py serialization edge (now reads .value)"
  - "events/order.py to_event boundary (Side re-parse now a no-op)"
tech-stack:
  added: []
  patterns:
    - "Side-member identity compares (is Side.BUY / is Side.SELL) replace .value/string literals"
    - "Single-snapshot read-model threading under the single-writer backtest contract"
key-files:
  created:
    - tests/unit/order/test_action_side_typing.py
    - tests/unit/order/test_admission_snapshot.py
  modified:
    - itrader/order_handler/order.py
    - itrader/order_handler/brackets/bracket_book.py
    - itrader/order_handler/brackets/bracket_manager.py
    - itrader/order_handler/brackets/levels.py
    - itrader/order_handler/order_validator.py
    - itrader/order_handler/admission/admission_manager.py
    - itrader/events_handler/events/order.py
    - itrader/reporting/orders.py
    - .planning/codebase/CONVENTIONS.md
decisions:
  - "D-03: narrowed Order.action / _PendingBracket.action from str to Side; mypy --strict checks side handling end-to-end inside order_handler"
  - "D-03: threaded ONE PositionView snapshot through the three admission/sizing gates (was three get_position fetches)"
metrics:
  duration: ~35m
  completed: 2026-06-13
  tasks: 2
  commits: 4
  src-files-modified: 8
  test-files: 10
requirements: [SIG-03]
---

# Phase 5 Plan 02: SIG-03 Side Retype & Admission Snapshot Threading Summary

Narrowed the persisted `action` boundary from `str` to `Side` across `order_handler/`
(the `Order` entity, both factory params, and `_PendingBracket`) so side handling is
mypy-checked end-to-end, and collapsed the triple admission `get_position()` into one
threaded `PositionView` snapshot — both behavior-preserving (oracle byte-exact at
134 / 46189.87730727451).

## What Was Built

### Task 1 — Side-typed action boundary (commit `0059cff`, RED `e8d55bc`)
- `order.py`: entity field `action: str` → `Side`; `new_stop_order`/`new_limit_order`
  `action` params → `Side`; `new_order` threads `signal.action` directly (dropped
  `.value`); `__str__` renders `self.action.name` so the rendered text stays "BUY"/"SELL";
  imported `Side`.
- `events/order.py`: the `Side(order.action)` re-parse at `new_order_event` is now a no-op
  pass-through (the entity already carries a `Side`); kept as a defensive normalizer that
  still surfaces order context for any hand-built bracket literal that bypasses the
  factories (docstring updated).
- `bracket_book.py`: `_PendingBracket.action: str` → `Side`; imported `Side`; closed the
  W2-02 deferred docstring note.
- `bracket_manager.py`: dropped `.value` at the PercentFromDecision/PercentFromFill arms;
  converted the `'BUY'/'SELL'` child-action literals (assembly + fill-anchored paths) to
  `Side.BUY`/`Side.SELL` members.
- `levels.py`: `action` param → `Side`; `== Side.SELL.value` → `is Side.SELL`.
- `order_validator.py`: `not in ["BUY","SELL"]` → `not in (Side.BUY, Side.SELL)`;
  `_is_closing_position` compares → `is Side.SELL` / `is Side.BUY`. The `:193`
  string-membership literal is dead after the retype.
- `admission_manager.py`: dropped `.value` at the reserve gate (`is Side.BUY`) and the
  `_build_primary_order` LIMIT/STOP factory calls (the order-construction edge).
- `reporting/orders.py`: the orders-snapshot "action" column now emits `o.action.value`
  so the serialized column stays "BUY"/"SELL" (keeps the e2e golden orders.csv byte-exact).
- `CONVENTIONS.md`: pinned the W4-04 dual-layer validator-overlap convention with the
  SIG-03 retype note (required because the validator path is touched).

### Task 2 — Single admission snapshot (commit `a313687`, RED `eabbf3c`)
- `process_signal` captures `snap: PositionView | None` ONCE before the step-0 direction
  gate (was the triple `get_position()` at `:404/:484/:583`).
- `_enforce_direction_admission` / `_enforce_position_admission` /
  `_resolve_signal_quantity` each take the threaded `snap`; each preserves its
  `portfolio_handler is None → None snap → fall-through` semantics exactly.
- `create_orders_from_signal` captures the same single snapshot for its sizing read.
- `open_position_count` stays a separate aggregate read-model crossing (not part of the
  snapshot).

## How It Works

`Side` is a plain `Enum`, so the only correctness-affecting edges are (1) serialization,
fixed by reading `.value`/`.name` at the reporting edge and `__str__`, and (2) the
`to_event` re-parse, which `Side(Side.BUY)` short-circuits to the member. mypy --strict is
the real enforcement gate for the retype.

The snapshot threading is byte-exact under the single-writer backtest contract: nothing
mutates the position within one `process_signal` (the cash reserve touches cash only, no
fill arrives mid-signal), so one `PositionView` read is value-identical to three.

## Verification

- `poetry run mypy --strict` — clean (160 source files).
- `poetry run pytest tests/unit/order` — 167 passed (incl. the two new RED→GREEN tests).
- `poetry run pytest tests/integration/test_backtest_oracle.py` — 134 / 46189.87730727451
  byte-identical.
- `poetry run pytest tests/e2e -m e2e` — 58/58.
- Full suite `poetry run pytest -q` — 953 passed.
- `git diff --check` — clean (no whitespace/indentation errors; tab files stayed tabs).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] reporting/orders.py serialization edge would emit a Side enum**
- **Found during:** Task 1.
- **Issue:** `reporting/orders.py:89` set `"action": o.action`; after the retype this would
  put a `Side` enum (not "BUY"/"SELL") into the orders-snapshot column, drifting the e2e
  golden orders.csv (the `action` column is an e2e identity column).
- **Fix:** emit `o.action.value` at the serialization edge.
- **Files modified:** `itrader/reporting/orders.py` (not in the plan's `files_modified`).
- **Commit:** `0059cff`.

**2. [Rule 3 — Blocking] events/order.py to_event boundary docstring + behavior**
- **Found during:** Task 1.
- **Issue:** `events/order.py:95` `Side(order.action)` was documented as a str→Side
  re-parse; after the entity retype this is a no-op pass-through. Left as-is would carry a
  stale, misleading comment (and the W4-01 str-boundary claim is no longer true).
- **Fix:** kept the call (harmless no-op that still surfaces context for hand-built
  literals) and updated the docstring to the SIG-03 reality.
- **Files modified:** `itrader/events_handler/events/order.py` (not in the plan's
  `files_modified`).
- **Commit:** `0059cff`.

**3. [Rule 3 — Blocking] test fixtures constructing Order/_PendingBracket with str actions**
- **Found during:** Task 1.
- **Issue:** the validator narrowing (`not in (Side.BUY, Side.SELL)`) makes a string
  `action="BUY"` fixture fail validation at runtime; the `__str__` test asserted
  `order.action in order_str` (TypeError on a Side). Several Order-entity test fixtures
  passed string actions.
- **Fix:** converted the Order/`_PendingBracket`-constructing fixtures to `Side.BUY`/
  `Side.SELL`; updated the `__str__` assertion to `order.action.name`. The OrderEvent
  `oe()` helpers (already `Side(action)`) were left untouched.
- **Files modified:** `tests/unit/order/test_order.py`, `test_order_manager.py`,
  `test_order_storage.py`, `test_bracket_book.py`, `test_order_validator.py`,
  `tests/unit/events/test_order_event_schema.py`.
- **Commit:** `0059cff`.

### Acceptance-criterion note (not a deviation)

The plan's Task-2 acceptance criterion `grep -c "get_position" admission_manager.py == 1`
resolves to **two call sites** (`process_signal` and the direct
`create_orders_from_signal` entry point) plus three explanatory comments. Both paths
capture exactly ONE snapshot per signal — the intent (one read-model crossing per
signal-processing path, the three method-level fetches removed) is met. The raw count is
inflated by the comment mentions and the second entry point, which the criterion did not
account for.

## Notes for Downstream

- `Side` is a plain `Enum` (not `str, Enum`): always read `.value`/`.name` at any
  serialization/string edge; never rely on `f"{side}"` to render "BUY".
- The W4-04 dual-layer validator overlap is now pinned in `.planning/codebase/CONVENTIONS.md`
  with the SIG-03 narrowing.

## Self-Check: PASSED

- Created files verified on disk: `test_action_side_typing.py`,
  `test_admission_snapshot.py`, `05-02-SUMMARY.md`.
- Commits verified in git log: `e8d55bc` (RED T1), `0059cff` (GREEN T1),
  `eabbf3c` (RED T2), `a313687` (GREEN T2).
