---
phase: 04-m3-event-dispatch-core
verified: 2026-06-05T18:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification: null
gaps: null
deferred: null
human_verification: null
---

# Phase 4: M3 Event & Dispatch Core — Verification Report

**Phase Goal:** Make events immutable facts with linkage IDs and `event_id`, replace the racy/fused dispatch loop with a race-free routing registry, and apply the domain-exception hierarchy and unified logging consistently — all behavior-preserving against the post-M2 oracle.
**Verified:** 2026-06-05T18:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Events are `frozen=True` facts carrying a unique `event_id` + `created_at`, required (non-`Optional`) linkage IDs, enum-typed `action`/`order_type`, `type` as a real field, and a dedicated error `EventType` | ✓ VERIFIED | `itrader/events_handler/events/base.py` declares `@dataclass(frozen=True, slots=True, kw_only=True)` with `event_id: uuid.UUID = field(default_factory=uuid_compat.uuid7)` and `created_at` defaulting to business time. `OrderEvent.order_id: OrderId` (required), `FillEvent.fill_id: uuid.UUID` and `order_id: OrderId` (both required). `action: Side` and `order_type: OrderType` on Signal/Order/Fill events. `type` is a real `init=False` field per subclass. `EventType.ERROR` exists in `core/enums/event.py`. `ErrorEvent` and `PortfolioErrorEvent` carry `type=EventType.ERROR`. `itrader/events_handler/event.py` is deleted — single `events/` package serves the runtime. `test_event_immutability.py` has 42 FrozenInstanceError assertions. |
| 2  | The dispatch loop is race-free — `get_nowait()`+`queue.Empty` replaces the `empty()`/`get(False)` TOCTOU; routing is separated from ordering via a `dict[EventType, list[Callable]]` registry; unknown types raise `NotImplementedError` | ✓ VERIFIED | `full_event_handler.py:100` uses `self.global_queue.get_nowait()` with `except queue.Empty: break`. Zero `global_queue.empty()` calls remain. `self._routes: dict[EventType, list[Callable[[Any], Any]]]` built as one literal in `__init__`. BAR route = `[update_portfolios_market_value, on_market_data, calculate_signals]`; FILL route = `[portfolio.on_fill, order.on_fill]`. SCREENER/UPDATE are explicit empty lists. Unknown types raise `NotImplementedError(f"EventHandler: unsupported event type {event.type!r}")`. 14 D-23 group 1+3 tests lock this (`test_dispatch_registry.py`, `test_error_flow.py`). Both oracle tests pass unmodified. |
| 3  | The domain-exception hierarchy is used consistently (no bare `ValueError`/`NotImplemented`/swallowed `None`), logging is unified, and portfolio exceptions are constructed with correct-typed arguments | ✓ VERIFIED | `ITraderError` is the root in `core/exceptions/base.py` (zero `ITradingSystemError` or `ConcurrencyError` references). `core/exceptions/execution.py` deleted. New `order.py` (`OrderError`/`UnsizedSignalError`) and `data.py` (`DataError`/`MalformedDataError`/`MissingPriceDataError`) modules exist. `data_provider.py` raises `MalformedDataError`/`MissingPriceDataError` (zero bare `ValueError`). `storage_factory.py` raises `ConfigurationError` (zero bare `ValueError`). KB24 fixed: `portfolio_handler.py:156` constructs `PortfolioConfigurationError("max_portfolios", self.max_portfolios, ...)` and `:191` `PortfolioNotFoundError(portfolio_id)` to real signatures. `logger.py` reads `ITRADER_LOG_LEVEL`/`ITRADER_JSON_LOGS` from `os.environ` (zero `Settings()` constructions). SMA_MACD and sltp_models bind through `get_itrader_logger()`. Per-signal/per-fill logs demoted to DEBUG. 12 hierarchy regression tests in `test_exceptions.py`, 6 env-wiring tests in `test_logger_config.py`. |
| 4  | Golden-master gate: the behavioral oracle is unchanged and the post-M2 numerical oracle is reproduced exactly after the event/dispatch refactor | ✓ VERIFIED | `tests/integration/test_backtest_oracle.py` — both `test_oracle_behavioral_identity` and `test_oracle_numeric_values` PASS with unmodified assertions. Full suite: **429 passed** (includes all oracle tests, event wiring, dispatch registry, error flow, immutability, exception hierarchy, and logging regression tests). |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/enums/event.py` | Class-based EventType (8 members) + Side enum with `_missing_` | ✓ VERIFIED | 8 members (TIME/BAR/UPDATE/SIGNAL/ORDER/FILL/SCREENER/ERROR), case-insensitive `_missing_` raises `ValueError(f"Unknown EventType: {value!r}")`. Side (BUY/SELL) with same pattern. |
| `itrader/core/ids.py` | FillId and EventId NewType aliases | ✓ VERIFIED | `FillId = NewType("FillId", uuid.UUID)` and `EventId = NewType("EventId", uuid.UUID)` at lines 23-24, both in `__all__`. |
| `itrader/trading_system/simulation/time_generator.py` | TimeGenerator (history-preserving git mv of ping_generator.py) | ✓ VERIFIED | File exists. `ping_generator.py` is absent. Zero PingEvent/PingGenerator/ping_generator references repo-wide. |
| `itrader/events_handler/events/base.py` | Frozen Event base with `kw_only=True`, uuid7 `event_id`, `created_at` defaulting to business time | ✓ VERIFIED | `@dataclass(frozen=True, slots=True, kw_only=True)`, `event_id: uuid.UUID = field(default_factory=uuid_compat.uuid7)`, `created_at` filled via `object.__setattr__` in `__post_init__`. |
| `itrader/events_handler/events/error.py` | ErrorEvent hierarchy with `type=EventType.ERROR`, PortfolioErrorEvent child | ✓ VERIFIED | `class ErrorEvent(Event)` with `type=EventType.ERROR`; `class PortfolioErrorEvent(ErrorEvent)` narrows `source="portfolio"`. Both frozen. |
| `itrader/events_handler/events/__init__.py` | Re-export surface with `__all__` | ✓ VERIFIED | Grouped re-exports with commented `__all__` per core/enums house pattern. |
| `tests/unit/events/test_event_immutability.py` | Inverted contract — FrozenInstanceError for ALL events, required linkage IDs | ✓ VERIFIED | 42 tests including FrozenInstanceError parametrized assertions, TypeError for missing order_id/fill_id, uuid7 event_id, created_at default, per-class EventType, enum-typed action/order_type. Zero old-path imports. |
| `itrader/events_handler/full_event_handler.py` | Race-free registry dispatcher with `_on_handler_error` seam + `_log_error_event` consumer | ✓ VERIFIED | `get_nowait`, `_routes`, `_on_handler_error` (bare `raise`), `_log_error_event` (severity-mapped structlog sink). Zero `empty()` prechecks. |
| `tests/unit/events/test_dispatch_registry.py` | D-23 group 1 — route lists asserted as data | ✓ VERIFIED | Exists, contains `_routes`, asserts BAR/FILL route lists as literals, NotImplementedError on unknown types, FIFO drain semantics. |
| `tests/unit/events/test_error_flow.py` | D-23 group 3 — ERROR routing, seam re-raise, unknown-type raise | ✓ VERIFIED | Exists, contains `NotImplementedError`, asserts ErrorEvent→consumer routing, fail-fast seam re-raise, Pitfall-5 PortfolioErrorEvent regression, empty-route UPDATE handling. |
| `itrader/core/exceptions/base.py` | ITraderError root (renamed), no ConcurrencyError | ✓ VERIFIED | `class ITraderError(Exception)`. No ConcurrencyError. |
| `itrader/core/exceptions/order.py` | Order-domain exceptions | ✓ VERIFIED | `class OrderError(ITraderError)` + `class UnsizedSignalError(OrderError)`. |
| `itrader/core/exceptions/data.py` | Data-domain exceptions | ✓ VERIFIED | `class DataError(ITraderError)` + `MalformedDataError` + `MissingPriceDataError`. |
| `tests/unit/core/test_exceptions.py` | Hierarchy + KB24 regression tests | ✓ VERIFIED | Exists, contains `ITraderError`, asserts hierarchy, execution-module deletion, KB24 signatures. |
| `itrader/logger.py` | Env-driven log_level/json_logs + guarded handler setup | ✓ VERIFIED | `ITRADER_LOG_LEVEL` read via `os.environ`. Zero `Settings()` constructions. Sentinel-guarded idempotent handler setup. |
| `tests/unit/core/test_logger_config.py` | Env-wiring regression tests | ✓ VERIFIED | Exists, contains `ITRADER_LOG_LEVEL`, 6 tests covering defaults, env overrides, import safety, idempotency. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/events_handler/events/base.py` | `itrader/core/enums` | `from itrader.core.enums import EventType` | ✓ WIRED | Single EventType definition, imported in base.py |
| `itrader/events_handler/events/fill.py` | `uuid_utils.compat` | `uuid7` for event_id default_factory and fill_id | ✓ WIRED | `import uuid_utils.compat as uuid_compat`; `field(default_factory=uuid_compat.uuid7)` in base; `fill_id=uuid_compat.uuid7()` in `new_fill` |
| `itrader/events_handler/full_event_handler.py` | `queue.Queue` | `get_nowait` drain | ✓ WIRED | `self.global_queue.get_nowait()` at line 100; `except queue.Empty: break` |
| `itrader/events_handler/full_event_handler.py` | `itrader/events_handler/events/error.py` | ERROR route → `_log_error_event` structlog consumer | ✓ WIRED | `EventType.ERROR: [self._log_error_event]` in `_routes`; `_log_error_event` binds ErrorEvent fields via structlog |
| `itrader/strategy_handler/base.py` | `itrader/events_handler/events` | SignalEvent keyword construction with Side/OrderType parse | ✓ WIRED | `from itrader.events_handler.events import` present; `action=Side(action)`, `order_type=OrderType(self.order_type)` at boundary |
| `itrader/portfolio_handler/portfolio_handler.py` | `itrader/core/enums` | Side→TransactionType mapping at fill boundary | ✓ WIRED | `TransactionType.BUY if fill_event.action is Side.BUY else TransactionType.SELL` |
| `itrader/portfolio_handler/portfolio_handler.py` | `itrader/core/exceptions/portfolio.py` | Correct-typed PortfolioNotFoundError/PortfolioConfigurationError | ✓ WIRED | `:156` `PortfolioConfigurationError("max_portfolios", self.max_portfolios, "maximum portfolios limit reached")`; `:191` `PortfolioNotFoundError(portfolio_id)` |
| `itrader/logger.py` | `os.environ` | ITRADER_LOG_LEVEL / ITRADER_JSON_LOGS reads | ✓ WIRED | `os.environ.get("ITRADER_LOG_LEVEL", "INFO")` at line 34 |

### Data-Flow Trace (Level 4)

Not applicable — this phase builds infrastructure (event schema, dispatch, exceptions, logging), not data-rendering components. The oracle integration tests constitute the real end-to-end data-flow verification.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green (429 tests) | `make test` | 429 passed in 11.58s | ✓ PASS |
| Oracle behavioral + numerical identity | `pytest tests/integration/test_backtest_oracle.py tests/integration/test_event_wiring.py` | 4 passed in 4.56s | ✓ PASS |
| event.py deleted, events package serves runtime | `test ! -f itrader/events_handler/event.py` | File does not exist | ✓ PASS |
| Zero TOCTOU precheck | `grep global_queue.empty() full_event_handler.py` | 0 matches | ✓ PASS |
| Zero old-path event imports in itrader/ (excl. my_strategies OUT) | grep old-path import | 0 matches in itrader/ (1 in out-of-scope my_strategies/) | ✓ PASS (my_strategies is OUT) |
| Zero PingEvent/PingGenerator/ping_generator refs | grep | 0 matches | ✓ PASS |
| Zero EventType.PING refs | grep | 0 matches | ✓ PASS |
| Zero ITradingSystemError/ConcurrencyError refs | grep | 0 matches (regression test assertions only) | ✓ PASS |
| Zero bare ValueError in data_provider/storage_factory | grep | 0 matches | ✓ PASS |

### Probe Execution

No declared probes for this phase.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| M3-01 | 04-01, 04-02, 04-03, 04-04, 04-05 | Events are immutable facts with event_id, linkage IDs, enum-typed action/order_type, type as real field, ERROR EventType | ✓ SATISFIED | Frozen events package fully operational on runtime; old event.py deleted; 42 immutability tests green |
| M3-02 | 04-06 | Race-free dispatch loop with get_nowait, registry, NotImplementedError on unknown | ✓ SATISFIED | Registry literal in full_event_handler; get_nowait drain; NotImplementedError; 14 D-23 tests green |
| M3-03 | 04-07, 04-08 | Consistent domain exceptions, unified logging, correct portfolio exception args | ✓ SATISFIED | ITraderError root; order/data modules; KB24 fixed; env-driven logging; stdlib loggers swapped; per-flow DEBUG |
| M3-04 | All plans | Behavioral + numerical oracle byte-exact throughout | ✓ SATISFIED | test_backtest_oracle.py: 2 passed with unmodified assertions; test_event_wiring.py: 2 passed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/strategy_handler/my_strategies/trend_following/SuperSmoothing_strategy.py` | 5 | `from itrader.events_handler.event import SignalEvent, EventType` — old-path import pointing at deleted module | ℹ️ Info | File is in `my_strategies/` which is explicitly OUT of scope per REQUIREMENTS.md. Would cause ImportError at runtime only if this strategy is loaded. Not blocking for this phase. |
| `itrader/strategy_handler/my_strategies/` (5 files) | 9 | `logging.getLogger('TradingSystem')` stdlib logger | ℹ️ Info | All in out-of-scope `my_strategies/`. D-21 explicitly excluded `my_strategies/` from the logging sweep. |

No TBD/FIXME/XXX debt markers found in any phase-modified file.

### Human Verification Required

None — all must-haves are verifiable programmatically and all checks passed.

### Gaps Summary

No gaps. All four phase-level success criteria are verified in the codebase:

1. **M3-01 (Events as immutable facts)** — complete: frozen events package on the live runtime, all 10 event classes frozen with required linkage IDs, enum-typed fields, and real `type` field; `event.py` deleted; 42-test immutability contract locked.
2. **M3-02 (Race-free dispatch)** — complete: `get_nowait`+`queue.Empty` drain, `_routes` registry literal, `NotImplementedError` on unknown types, `_on_handler_error` fail-fast seam, ERROR consumer; 14 D-23 tests lock the routing order and error flow.
3. **M3-03 (Exception hierarchy + logging)** — complete: `ITraderError` root, dead execution/concurrency families deleted, KB24 portfolio exceptions fixed to real signatures, new order/data modules adopted, env-driven logging, stdlib loggers swapped, per-flow logs at DEBUG; 12 hierarchy tests + 6 logger tests lock the behavior.
4. **M3-04 (Golden-master gate)** — complete: `test_backtest_oracle.py` passes with unmodified behavioral + numerical assertions; full suite 429 passed.

---

_Verified: 2026-06-05T18:00:00Z_
_Verifier: Claude (gsd-verifier)_
