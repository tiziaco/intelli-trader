---
phase: 02-event-bus
reviewed: 2026-07-09T13:39:19Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - itrader/core/enums/event.py
  - itrader/events_handler/bus.py
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/execution_handler.py
  - itrader/order_handler/order_handler.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/engine_context.py
  - tests/integration/test_okx_inertness.py
  - tests/unit/events/test_event_bus.py
  - tests/unit/order/test_order_handler_storage.py
  - tests/unit/strategy/test_strategies_handler_storage.py
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-09T13:39:19Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 2 introduced the two-tier `EventBus` substrate (`bus.py`), a frozen `EngineContext`
infra bundle, folded `compose_engine` to the `(ctx, spec)` seam, added three CONTROL
`EventType` members wired to explicit-empty routes, and retyped the `global_queue`
constructor param from `queue.Queue[Any]` to `EventBus` across seven handler modules
(D-08 retype-not-rename).

The changes are largely mechanical (type retype + additive keyword-only ctor params +
new pure substrate module) and the byte-exact oracle is reported green, so no correctness
BLOCKERs were found. Adversarial tracing surfaced **two WARNINGs**: (1) the mode-agnostic
`compose_engine` seam threads `ctx.environment`/`ctx.sql_engine` into two of the three
storage-owning handlers but silently omits `PortfolioHandler` — a latent live-path
storage defect that contradicts the seam's stated D-14a mode-agnosticism goal; and
(2) the `EventBus` retype left dead `from queue import Queue` imports in four modules
that no automated gate (mypy-strict-only, no ruff/flake8) will catch. The remaining four
INFO items are documentation drift and latent inconsistencies in the not-yet-wired
`PriorityEventBus` monitoring surface.

Positive notes: `bus.py` correctly keeps `Event` as a `TYPE_CHECKING`-only import
(inertness preserved), `bar_feed.py` correctly dropped its now-unused `import queue`,
the inertness subprocess gate was extended for the P2 register-vs-build assertion, and
the `PriorityEventBus` `(tier, seq, event)` keying correctly guarantees the non-orderable
`Event` is never dereferenced by the heap.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `compose_engine` does not thread `ctx.environment`/`ctx.sql_engine` into `PortfolioHandler`

**File:** `itrader/trading_system/compose.py:171`
**Issue:** `compose_engine` is documented as "the SHARED, mode-agnostic wiring seam both
`build_backtest_system` (now) and a future `build_live_system` (fast-follow) consume"
and the CTX-02/D-02 design has each storage-owning handler own its backend selection from
`(environment, sql_engine)`. The seam correctly threads these into two handlers:

```python
strategies_handler = StrategiesHandler(..., environment=ctx.environment, sql_engine=ctx.sql_engine)
order_handler = OrderHandler(..., environment=ctx.environment, sql_engine=ctx.sql_engine)
```

but constructs the third with neither:

```python
portfolio_handler = PortfolioHandler(ctx.bus)
```

`PortfolioHandler.__init__` accepts `environment="backtest"` and `backend=None` and threads
them into each `Portfolio`'s durable state storage (`portfolio_handler.py:81-82`, `:230-231`).
Because compose passes neither, the portfolio handler is pinned to the in-memory backtest
backend regardless of `ctx.environment`. This is oracle-dark today (backtest only, and
`LiveTradingSystem` still wires `PortfolioHandler` directly rather than via `compose_engine`),
but it is a real latent defect: when `build_live_system` reuses this seam with
`environment="live"` + a `sql_engine`, portfolio state would silently stay in-memory —
no durable persistence, no restart rehydrate — while orders and signals persist correctly.
The asymmetry directly undercuts the mode-agnosticism the fold exists to deliver.
**Fix:**
```python
portfolio_handler = PortfolioHandler(
    ctx.bus,
    environment=ctx.environment,
    backend=ctx.sql_engine,
)
```

### WR-02: Dead `from queue import Queue` imports left behind by the `EventBus` retype

**File:** `itrader/order_handler/order_handler.py:2`, `itrader/strategy_handler/strategies_handler.py:2`, `itrader/execution_handler/execution_handler.py:2`, `itrader/portfolio_handler/portfolio_handler.py:9`
**Issue:** The D-08 retype changed every `global_queue` annotation from `"Queue[Any]"` to
`"EventBus"`, removing the only real use of the imported `Queue` name in these four modules.
The `from queue import Queue` import is now dead in all four (verified: no remaining code
reference — only docstring prose mentions "Queue"). `bar_feed.py` correctly dropped its
`import queue` in the same change, but these four were missed. The project has no ruff/flake8
gate and `mypy --strict` does not flag unused imports, so this dead code will persist
silently and accrete. This is a hygiene regression introduced by this phase, not pre-existing.
**Fix:** Remove the `from queue import Queue` line from each of the four modules (mirror the
`bar_feed.py` cleanup already done in this phase).

## Info

### IN-01: Stale docstrings still reference `Queue` after the `EventBus` retype

**File:** `itrader/price_handler/feed/bar_feed.py:439`, `itrader/order_handler/order_handler.py:57`, `itrader/execution_handler/execution_handler.py:35`, `itrader/strategy_handler/strategies_handler.py:54`
**Issue:** Several parameter docstrings still describe `global_queue` as
"`Queue object`" / "`Optional[queue.Queue]`" after the field was retyped to `EventBus`.
Example: `bar_feed.py:439` documents `global_queue : Optional[queue.Queue]`. Documentation
now drifts from the retyped signature.
**Fix:** Update the docstrings to reference `EventBus` (or `Optional[EventBus]`) to match
the new type.

### IN-02: `PriorityEventBus.depth_by_tier` counter update is not atomic with the queue operation

**File:** `itrader/events_handler/bus.py:137-153`
**Issue:** `put` calls `self._pq.put(...)` and then, under a separate `_depth_lock`,
increments the tier counter; `get`/`get_nowait` decrement after the queue pop. The per-tier
`Counter` is thread-safe in isolation, but it is not atomic with the underlying
`PriorityQueue` state, so a concurrent consumer that pops between another thread's `put` and
its increment can momentarily observe a counter that disagrees with `qsize()` (transient
off-by-one / brief negative). This is documented monitoring-only and `PriorityEventBus` is
not yet wired into any run path, so there is no live impact today.
**Fix:** Acknowledge in the docstring that `depth_by_tier` is best-effort/eventually-consistent,
or fold the counter update inside a lock that also brackets the queue op if a strict invariant
is ever needed.

### IN-03: `depth_by_tier` returns an inconsistent dict shape across the two bus implementations

**File:** `itrader/events_handler/bus.py:116-118` (Fifo) vs `:161-166` (Priority)
**Issue:** `FifoEventBus.depth_by_tier` returns a single-key dict `{EventTier.BUSINESS: n}`
(no CONTROL key), while `PriorityEventBus.depth_by_tier` always returns both keys. A generic
monitoring consumer written against the Protocol that does `depth[EventTier.CONTROL]` would
`KeyError` on a `FifoEventBus`. Both behaviors are individually documented, but the
`EventBus` Protocol offers no uniform contract for the returned key set.
**Fix:** Have `FifoEventBus` return `{EventTier.CONTROL: 0, EventTier.BUSINESS: n}` for a
uniform shape, or document on the Protocol that consumers must use `.get(tier, 0)`.

### IN-04: `UNIVERSE_POLL` documented as "control-plane" but tiered BUSINESS

**File:** `itrader/core/enums/event.py:32` vs `itrader/events_handler/bus.py:48-53`
**Issue:** `EventType.UNIVERSE_POLL` carries the comment `# D-06: control-plane poll tick`,
yet it is not a member of `_CONTROL_EVENT_TYPES`, so `_tier(UNIVERSE_POLL)` resolves to
`BUSINESS`. `STRATEGY_COMMAND` (also a control-plane command) IS enumerated as CONTROL.
When `PriorityEventBus` is eventually wired, a `UNIVERSE_POLL` follow-on emitted by a
CONTROL-tier `STRATEGY_COMMAND` (see `strategies_handler.on_strategy_command`) would sit at
BUSINESS tier behind all pending business events. This is plausibly intentional (only
connector-lifecycle + operator commands preempt; routine poll ticks do not), but the enum
comment and the tier set disagree. Latent — the priority bus is defined and unit-tested this
phase but wired into no path.
**Fix:** Either add `UNIVERSE_POLL` to `_CONTROL_EVENT_TYPES` if it should preempt, or update
the enum comment to clarify it is a BUSINESS-tier control-plane event, so the classification
intent is unambiguous when the priority bus lands.

---

_Reviewed: 2026-07-09T13:39:19Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
