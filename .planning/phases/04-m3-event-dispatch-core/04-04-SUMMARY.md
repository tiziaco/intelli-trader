---
phase: 04-m3-event-dispatch-core
plan: 04
subsystem: events
tags: [events, frozen-dataclass, immutability, uuid7, error-events, inert-package]
requires:
  - "04-01 (EventType + Side in core/enums, FillId/EventId aliases, TimeEvent family)"
  - "04-02 (SignalEvent de-mutation, Order-entity pipeline)"
  - "04-03 (construct-complete new_fill shape, replace-in-book matching)"
provides:
  - "Complete frozen events package itrader/events_handler/events/ — base.py (Event with event_id uuid7 default_factory + created_at defaulting to business time), market.py (TimeEvent/BarEvent/PortfolioUpdateEvent/ScreenerEvent), signal.py, order.py, fill.py, error.py"
  - "Event base: @dataclass(frozen=True, slots=True, kw_only=True); type is a real init=False field set per subclass"
  - "OrderEvent.order_id REQUIRED non-Optional (D-12); child_order_ids tuple (D-11); keyword-form factory preserving every float() boundary coercion (D-04)"
  - "FillEvent fill_id/order_id/strategy_id REQUIRED; construct-complete new_fill per Plan 04-03 with fill_id=uuid_compat.uuid7() inside the factory"
  - "ErrorEvent concrete instantiable base + PortfolioErrorEvent child, both type=EventType.ERROR (D-06 — type=UPDATE hack design dead)"
  - "test_event_immutability.py locks the inverted contract (D-23 group 2): FrozenInstanceError for all ten classes, required-linkage TypeErrors, uuid7 event_id, created_at default, enum-typed action/order_type"
affects: [04-05, 04-06]
tech-stack:
  added: []
  patterns:
    - "frozen/slots/kw_only Event base with per-subclass type: field(default=EventType.X, init=False) (RESEARCH Pattern 1, execution-verified)"
    - "created_at defaulting to business time via object.__setattr__ in frozen __post_init__ (D-02 — no wall clock on the engine path)"
    - "concrete error-event base + narrowing children mirroring core/exceptions hierarchy shape (D-06, FastAPI-style)"
    - "grouped __init__ re-exports with commented __all__ (core/enums house pattern; __all__ satisfies mypy no_implicit_reexport)"
key-files:
  created:
    - itrader/events_handler/events/__init__.py
    - itrader/events_handler/events/base.py
    - itrader/events_handler/events/market.py
    - itrader/events_handler/events/signal.py
    - itrader/events_handler/events/order.py
    - itrader/events_handler/events/fill.py
    - itrader/events_handler/events/error.py
  modified:
    - tests/unit/events/test_event_immutability.py
key-decisions:
  - "Order entity carries no stop_price field — new_order_event keeps the legacy getattr(order, 'stop_price', None) read (documented inline) instead of a direct attribute access; all other entity reads are direct (order.id, order.type, order.parent_order_id, tuple(order.child_order_ids))"
  - "FillEvent.strategy_id REQUIRED (non-Optional) in the new package per the plan field list — the 04-03 Optional default was a transitional concession for old-package fixtures; new-package fixtures construct complete"
  - "ErrorEvent.to_dict dropped — its only consumer is logging and the Plan 04-06 log consumer logs fields directly (plan-resolved discretion)"
  - "Event base itself included in the ten frozen classes under test (it is instantiable; type is unset until a subclass pins it)"
metrics:
  duration: "~15 min"
  completed: "2026-06-05"
  tasks: 2
  files: 8
---

# Phase 4 Plan 04: Frozen Events Package Summary

Complete frozen/slots/kw_only events package built INERT alongside the runtime: ten immutable Event subclasses with uuid7 event_id + business-time created_at, required linkage IDs (order_id/fill_id/strategy_id), enum-typed action/order_type, and the FastAPI-style ErrorEvent hierarchy with type=EventType.ERROR — the inverted immutability contract locked by 42 tests while old event.py still serves the runtime (suite 394 green, oracle byte-exact, mypy strict clean).

## Tasks Completed

| Task | Name | Commit(s) | Key Files |
| ---- | ---- | --------- | --------- |
| 1 | Frozen Event base + market/signal/order/fill modules | ab7aa9e | events/base.py, market.py, signal.py, order.py, fill.py, __init__.py (all NEW) |
| 2 | ErrorEvent hierarchy (D-06) + inverted immutability contract | bee9978, 5cef457 (docstring grep-gate fix) | events/error.py (NEW), events/__init__.py, tests/unit/events/test_event_immutability.py |

## What Was Built

- **base.py:** `Event` per RESEARCH Pattern 1 verbatim — `@dataclass(frozen=True, slots=True, kw_only=True)` with `type: EventType = field(init=False)` (no base default), `time: datetime`, `event_id: uuid.UUID = field(default_factory=uuid_compat.uuid7)`, `created_at: datetime | None = None` filled to business time in `__post_init__` via `object.__setattr__` (D-01/D-02).
- **market.py:** TimeEvent (TIME), BarEvent (BAR — `bars` dict payload and all four `get_last_*` accessors verbatim; M5a owns the Bar struct), PortfolioUpdateEvent (UPDATE — `portfolios` dict shape unchanged, D-07), ScreenerEvent (SCREENER — fields unchanged, frozen structurally).
- **signal.py:** SignalEvent — `action: Side`, `order_type: OrderType` (D-05), `quantity: float | None = None` (D-10), no verdict flag (D-03), money fields float (D-04), `portfolio_id: int` kept.
- **order.py:** OrderEvent — `order_id: OrderId` REQUIRED (D-12), `parent_order_id: OrderId | None = None`, `child_order_ids: tuple[OrderId, ...] = ()` (D-11), `command`, `stop_price`. `new_order_event(order, command)` keyword-form: every `float()` coercion bit-identical with the M2a boundary comment preserved, `order_id=order.id` (no getattr-None), `action=Side(order.action)` (entity stores a string), `child_order_ids=tuple(order.child_order_ids)`.
- **fill.py:** FillEvent — `fill_id: uuid.UUID`, `order_id: OrderId`, `strategy_id: StrategyId` all REQUIRED, `action: Side`. `new_fill(status, order, *, price, quantity, commission)` exactly as landed in 04-03: `FillStatus(status)` parse kept, `fill_id=uuid_compat.uuid7()` generated inside the factory.
- **error.py:** concrete `ErrorEvent(Event)` with `type=EventType.ERROR` and the legacy PortfolioErrorEvent field NAMES (source/error_type/error_message/operation/correlation_id/severity/details) so the `_publish_error_event` cutover change is minimal; `PortfolioErrorEvent(ErrorEvent)` narrows `source: str = "portfolio"` and adds `portfolio_id: Any | None = None`. Whole tree frozen (Pitfall 4). `to_dict` dropped.
- **__init__.py:** grouped re-exports + commented `__all__` per the core/enums pattern; EventType re-exported from core.enums (single definition).
- **test_event_immutability.py (rewritten, 42 tests):** (a) FrozenInstanceError on field assignment for all ten classes (parametrized) + payload-field spot checks; (b) TypeError for OrderEvent without order_id and FillEvent without fill_id/order_id; (c) event_id is stdlib uuid.UUID version 7, unique across constructions; (d) created_at == time when omitted (+ explicit value preserved); (e) per-class EventType member via real field; (f) isinstance(x, Event) for all; (g) PortfolioErrorEvent is an ErrorEvent with type ERROR and source "portfolio"; (h) Side/OrderType enum members held by the fields. Zero imports of `itrader.events_handler.event`.

## Verification Results

- Import smoke: `TimeEvent(time=t)` → `created_at == time`, `event_id.version == 7`, `isinstance(t, Event)`, `type is EventType.TIME`; OrderEvent without order_id raises TypeError
- `grep "events_handler.event import\|from itrader.events_handler import event"` in the test file → 0
- `grep verified` in signal.py → 0; base.py contains `kw_only=True` + `default_factory=uuid_compat.uuid7`; error.py contains `class PortfolioErrorEvent(ErrorEvent)`; `__init__.py` contains `__all__`
- Old `event.py` untouched: `git diff HEAD~3..HEAD -- itrader/events_handler/event.py` empty — runtime still on the old module
- Full suite: 360 passed (ab7aa9e), 394 passed (bee9978, 5cef457 — 42 immutability tests replacing the old 8)
- `tests/integration/test_backtest_oracle.py`: 2 passed UNMODIFIED — behavioral + numerical oracle byte-exact (M3-04, D-22); `git diff` over `tests/integration/` empty
- `poetry run mypy itrader` (the `make typecheck` command): Success, 134 source files (127 + 7 new modules)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] signal.py module docstring contained the word "verified"**
- **Found during:** Final acceptance-criteria grep ("signal.py contains no `verified`")
- **Issue:** the docstring explained the flag's absence by naming it, tripping the grep gate
- **Fix:** reworded to "no verdict flag"
- **Files modified:** itrader/events_handler/events/signal.py
- **Commit:** 5cef457

### Minor in-scope clarifications

- `new_order_event` reads `stop_price` via `getattr(order, 'stop_price', None)` (documented inline): the Order entity has no stop_price field today, so a direct attribute read would crash; behavior identical to the legacy factory.
- `FillEvent.strategy_id` is REQUIRED in the new package (plan field list), tightening the 04-03 Optional-with-default transitional shape — old-package fixtures are unaffected (package inert).
- Worktree environment notes from 04-01/04-02/04-03 applied: all test runs with `PYTHONPATH=<worktree-root>`, `poetry run mypy itrader` in place of `make typecheck` (gitignored `.env` absent in worktree).

## Known Stubs

None — the package is deliberately INERT this plan (old `event.py` serves the runtime until the Plan 04-05 cutover); that is the plan's stated design, not an unwired stub, and the new package is fully exercised by its own 42-test suite.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-09 mitigated (frozen=True/slots=True on the whole tree; FrozenInstanceError locked by parametrized tests); T-04-10 mitigated (kw_only + required non-Optional linkage IDs make malformed construction a TypeError; enum-typed action/order_type reject unknown values via `_missing_`); T-04-11 mitigated (every event carries a unique time-ordered UUIDv7 event_id + created_at).

## TDD Gate Compliance

Not applicable — plan type is `execute`, not `tdd`.

## Self-Check: PASSED

- Created files exist: events/__init__.py, base.py, market.py, signal.py, order.py, fill.py, error.py; rewritten test file exists
- Commits exist: ab7aa9e, bee9978, 5cef457
- No file deletions in any commit (`git diff --diff-filter=D` empty across all three)
- Oracle assertions untouched: `git diff` over `tests/integration/` empty
