---
phase: 02-event-bus
verified: 2026-07-09T16:00:00Z
status: passed
score: 12/12 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: Event Bus Verification Report

**Phase Goal:** Introduce a stdlib two-tier `EventBus` (CONTROL > BUSINESS) with FIFO and priority
implementations behind one `.put()` surface, add the new CONTROL `EventType` members, and settle the
`compose_engine` signature to its end-state `(ctx, spec)` form via a frozen `EngineContext` with
handler-owned storage — backtest wiring `FifoEventBus` at zero oracle risk. (Phase 2 D-03: CTX-01/CTX-02/CTX-03
pulled forward from P3 into P2; only SqlBackend→SqlEngine (CTX-04) stays in P3.)

**Verified:** 2026-07-09T16:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `EventBus` Protocol + `FifoEventBus` + `PriorityEventBus` both satisfy `isinstance(bus, EventBus)` (BUS-01) | ✓ VERIFIED | Ran independently: `isinstance(FifoEventBus(), EventBus)` → True, `isinstance(PriorityEventBus(), EventBus)` → True. `bus.py` inspected directly — Protocol has `put/get/get_nowait/qsize/empty/depth_by_tier`, `@runtime_checkable`. |
| 2 | `PriorityEventBus` dequeues CONTROL before BUSINESS, strict within-tier FIFO via `itertools.count()` seq, never dereferences `Event` in comparison (BUS-02) | ✓ VERIFIED | `bus.py` code inspected: `(tier, next(self._seq), event)` tuple keying. 18/18 unit tests pass incl. `test_priority_control_preempts_business_then_fifo`, `test_priority_never_compares_events`, `test_priority_stable_fifo_under_many_same_tier_puts`. |
| 3 | `EventType` gains `STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE`; `_CONTROL_EVENT_TYPES` frozenset assigns CONTROL tier to those 3 + `STRATEGY_COMMAND` (BUS-03) | ✓ VERIFIED | Ran independently: all 3 members present, `EventType('stream_state') is EventType.STREAM_STATE`. `_CONTROL_EVENT_TYPES` frozenset in `bus.py` contains exactly the 4 expected members. Tests `test_control_types_*` (4 tests) pass. |
| 4 | The 3 new CONTROL EventTypes are registered in `full_event_handler._routes` (no silent dispatch gap) | ✓ VERIFIED | `grep` confirms `EventType.STREAM_STATE/CONNECTOR_FATAL/CONFIG_UPDATE: []` explicit empty routes at lines 113-115. `tests/unit/events/test_dispatch_registry.py::test_registry_covers_every_event_type` passes (ran independently). Wave-1 post-merge fix commit `a7b4d9d9` confirmed in git log. |
| 5 | A frozen `EngineContext` dataclass carries exactly 4 fields `bus`/`config`/`environment`/`sql_engine` (BUS-04) | ✓ VERIFIED | `engine_context.py` read directly — `@dataclass(frozen=True)` with exactly `bus: EventBus`, `config: Any`, `environment: str`, `sql_engine: Optional[Any] = None`, in order. |
| 6 | `compose_engine(ctx, spec)` is the two-arg end-state signature; internal `queue.Queue()` deleted (CTX-01) | ✓ VERIFIED | `inspect.signature` not re-run but `grep -c 'queue.Queue()' compose.py` == 0 (ran independently). `def compose_engine(ctx: "EngineContext", spec: "SystemSpec") -> Engine:` confirmed in file. |
| 7 | `compose_engine` reads only `{spec.data, spec.start, spec.end, spec.timeframe, spec.exchange, spec.results_store}`, never `spec.ticker`/`spec.starting_cash`/`spec.strategies`/`spec.portfolios`; `order_config` stays handler-owned via `OrderConfig.default()` (D-04/A1) | ✓ VERIFIED | `grep -c 'spec.ticker\|spec.starting_cash\|spec.strategies\|spec.portfolios' compose.py` == 0 (ran independently). `resolved_order_config = OrderConfig.default()` confirmed at line 214. |
| 8 | Every in-scope handler's `global_queue` param retyped to `EventBus` (name unchanged); `EventHandler` drains via `bus.get_nowait()` catching `queue.Empty` (D-07/D-08) | ✓ VERIFIED | `mypy --strict` clean (237 source files, ran independently). No `.put()`/`.get_nowait()` call-site changes confirmed by mypy passing without adjusting call sites. |
| 9 | CTX-02: `OrderHandler`/`StrategiesHandler` own their storage init from `(environment, sql_engine)`, expose `.storage`/`.signal_store`, backtest yields in-memory concretes; `compose_engine` reads them back | ✓ VERIFIED | `tests/unit/order/test_order_handler_storage.py` + `tests/unit/strategy/test_strategies_handler_storage.py` (5 tests) pass independently, including identity check `.storage` == instance forwarded to `OrderManager`. `compose.py` confirmed reading `order_handler.storage` / `strategies_handler.signal_store` back. |
| 10 | Backtest wiring uses `FifoEventBus` at zero oracle risk — SMA_MACD stays byte-exact `134 / 46189.87730727451` (CTX-03) | ✓ VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed, `check_exact=True` against `tests/golden/summary.json` (`final_equity: 46189.87730727451`). Ran independently, not just SUMMARY claim. |
| 11 | D-11: `live_trading_system.py` unchanged in P2 | ✓ VERIFIED | `git diff --exit-code b3eb2d18 -- itrader/trading_system/live_trading_system.py` → exit code 0 (no diff), ran independently. |
| 12 | `poetry.lock` unchanged since phase start | ✓ VERIFIED | `git diff --stat b3eb2d18 -- poetry.lock` → empty, ran independently. |

**Score:** 12/12 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/events_handler/bus.py` | `EventBus` Protocol + `EventTier` + `_CONTROL_EVENT_TYPES` + `FifoEventBus` + `PriorityEventBus` | ✓ VERIFIED | 167 lines, all symbols present, matches PLAN spec exactly (read in full). |
| `itrader/core/enums/event.py` | 3 new CONTROL EventType members | ✓ VERIFIED | Members present, importable, case-insensitive parse round-trips. |
| `tests/unit/events/test_event_bus.py` | BUS-01/02/03 proof suite | ✓ VERIFIED | 18 tests, all pass independently. |
| `tests/unit/events/test_dispatch_registry.py` | Registry conformance (pre-existing, from Phase 4) | ✓ VERIFIED | `test_registry_covers_every_event_type` passes — the 3 new CONTROL types are covered by the wave-1 fix. |
| `itrader/order_handler/order_handler.py` | `.storage` attribute, `(environment, sql_engine)` kwargs | ✓ VERIFIED | Confirmed via independent test run + mypy. |
| `itrader/strategy_handler/strategies_handler.py` | `.signal_store` attribute, `(environment, sql_engine)` kwargs, optional `signal_store` | ✓ VERIFIED | Confirmed via independent test run + mypy. |
| `tests/unit/order/test_order_handler_storage.py` | Handler-storage unit cases | ✓ VERIFIED | 3 tests pass. |
| `tests/unit/strategy/test_strategies_handler_storage.py` | Handler-storage unit cases | ✓ VERIFIED | 2 tests pass. |
| `itrader/trading_system/engine_context.py` | Frozen `EngineContext` (4 fields) | ✓ VERIFIED | Read in full — matches spec exactly. |
| `itrader/trading_system/compose.py` | Two-arg `compose_engine(ctx, spec)`, queue deleted, storage read-back | ✓ VERIFIED | Confirmed via grep + code read. |
| `itrader/trading_system/backtest_trading_system.py` | Both call sites rewired to `(ctx, spec)` | ✓ VERIFIED | `grep -c 'compose_engine(ctx'` == 2. |
| `tests/integration/test_okx_inertness.py` | Extended register-vs-build assertion | ✓ VERIFIED | New assertion present (`FifoEventBus`/`EngineContext` construction, no sqlalchemy/ccxt pull); test passes independently. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_CONTROL_EVENT_TYPES` | 3 new members + `STRATEGY_COMMAND` | frozenset membership | ✓ WIRED | Verified by direct code read + `test_control_types_*` tests. |
| `PriorityEventBus.put` | `_tier(event.type)` | tier lookup + tuple enqueue | ✓ WIRED | Code confirms `tier = _tier(event.type)`, `self._pq.put((tier, next(self._seq), event))`. |
| `PriorityEventBus.get/get_nowait` | bare `Event` return | tuple unwrap `item[2]` | ✓ WIRED | Code confirms unwrap; test `test_priority_get_returns_bare_event_not_tuple` passes. |
| `OrderHandler.storage` | `compose_engine`'s `portfolio_handler.set_order_storage(...)` | back-read | ✓ WIRED | `compose.py:232-233` confirmed: `order_storage = order_handler.storage; portfolio_handler.set_order_storage(order_storage)`. |
| `StrategiesHandler.signal_store` | `Engine` holder | back-read | ✓ WIRED | `compose.py:252` confirmed: `signal_store=strategies_handler.signal_store`. |
| `EngineContext.bus` | 6 handler ctors + `Engine.global_queue` | `ctx.bus` injection | ✓ WIRED | `grep -c 'ctx.bus' compose.py` matches PLAN's ≥6 requirement (confirmed present across handler ctors). |
| Both backtest call sites | `compose_engine(ctx, spec)` | direct call | ✓ WIRED | `grep -c 'compose_engine(ctx' backtest_trading_system.py` == 2. |

### Data-Flow Trace (Level 4)

Not applicable — this phase is pure backend/infrastructure wiring (no UI, no dynamic-data rendering
components). Oracle byte-exactness (Truth #10) is the equivalent end-to-end data-flow proof: the full
component graph is exercised through `compose_engine` and produces the exact frozen golden numbers.

### Behavioral Spot-Checks / Probe Execution

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | 3 passed, `check_exact=True` against golden `134 / 46189.87730727451` | ✓ PASS |
| Inertness (register-vs-build) | `poetry run pytest tests/integration/test_okx_inertness.py -x` | 2 passed, incl. new `FifoEventBus`/`EngineContext` assertion | ✓ PASS |
| `mypy --strict` | `poetry run mypy itrader` | Success: no issues found in 237 source files | ✓ PASS |
| D-11 non-change | `git diff --exit-code b3eb2d18 -- itrader/trading_system/live_trading_system.py` | exit 0, no diff | ✓ PASS |
| `poetry.lock` unchanged | `git diff --stat b3eb2d18 -- poetry.lock` | empty | ✓ PASS |
| Structural: no internal queue | `grep -c 'queue.Queue()' itrader/trading_system/compose.py` | 0 | ✓ PASS |
| Structural: both arms folded | `grep -c 'compose_engine(ctx' itrader/trading_system/backtest_trading_system.py` | 2 | ✓ PASS |
| Both buses satisfy Protocol | `isinstance(bus, EventBus)` for both concretes | True, True | ✓ PASS |
| CONTROL types registered | `test_dispatch_registry.py::test_registry_covers_every_event_type` | passed | ✓ PASS |
| Bus substrate unit suite | `pytest tests/unit/events/test_event_bus.py -v` | 18/18 passed | ✓ PASS |
| Handler-storage unit suite | `pytest tests/unit/order/test_order_handler_storage.py tests/unit/strategy/test_strategies_handler_storage.py` | 5/5 passed | ✓ PASS |
| No regression in events/order/strategy suites | `pytest tests/unit/events tests/unit/order tests/unit/strategy -q` | 566 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| BUS-01 | 02-01, 02-03 | `EventBus` Protocol + FIFO/Priority implementations, shared `.put()` surface | ✓ SATISFIED | `isinstance` checks, mypy strict clean across retyped handlers. |
| BUS-02 | 02-01 | `PriorityEventBus` tier ordering + non-orderable-event guarantee | ✓ SATISFIED | 9 priority-marked unit tests pass. |
| BUS-03 | 02-01 | 3 new CONTROL EventTypes, backtest stays on `FifoEventBus` | ✓ SATISFIED | Members present + registered in dispatch routes. |
| BUS-04 | 02-03 | Minimal `EngineContext` skeleton settling `compose_engine` signature once | ✓ SATISFIED | `engine_context.py` — 4 fields, frozen, exactly as specified. |
| CTX-01 | 02-03 | `EngineContext` threaded once into `compose_engine(ctx, spec)` | ✓ SATISFIED | Signature confirmed; internal queue deleted. |
| CTX-02 | 02-02 | Order/Strategies handlers own storage init, expose concrete on `.storage`/`.signal_store` | ✓ SATISFIED | 5 handler-storage unit tests pass; back-read confirmed in compose.py. |
| CTX-03 | 02-03 | Backtest yields same in-memory instances; oracle byte-exact; inertness green | ✓ SATISFIED | Oracle + inertness tests pass independently. |

No orphaned requirements — REQUIREMENTS.md maps exactly these 7 IDs to Phase 2 (CTX-04 correctly deferred to P3, confirmed in REQUIREMENTS.md traceability table).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/order_handler/order_handler.py:2` | 2 | Dead `from queue import Queue` import (WR-02, advisory review) | ℹ️ Info | Hygiene only — no ruff/flake8 gate catches it; mypy doesn't flag unused imports. Does not affect correctness or the oracle. Non-blocking per emphasis note. |
| `itrader/strategy_handler/strategies_handler.py:2` | 2 | Same dead import | ℹ️ Info | Same as above. |
| `itrader/execution_handler/execution_handler.py:2` | 2 | Same dead import | ℹ️ Info | Same as above. |
| `itrader/portfolio_handler/portfolio_handler.py:9` | 9 | Same dead import | ℹ️ Info | Same as above. |
| `itrader/trading_system/compose.py:171` | 171 | `PortfolioHandler(ctx.bus)` omits `environment`/`sql_engine` threading (WR-01, advisory review) | ⚠️ Warning (deferred) | Backtest-dark today (in-memory only path used); a latent defect for a future live-mode `compose_engine` reuse (P3/P6 scope per project explicit note). Not a P2 requirement — P2 does not require `PortfolioHandler` mode-agnosticism. |

Both items were independently confirmed present in the current codebase (not just SUMMARY claims) and match the advisory `02-REVIEW.md` (0 blockers, 2 warnings) exactly. Per the phase's explicit verification-emphasis instructions, these are non-blocking and do not represent P2 goal failures — WR-01 is explicitly deferred scope (P3/P6), WR-02 is a hygiene nit with no automated gate and no behavioral impact.

### Human Verification Required

None. This phase is pure backend/infrastructure wiring with no UI, no user-facing behavior, and fully
mechanical/testable success criteria (byte-exact oracle, inertness assertions, mypy strict, structural
greps). All must-haves were verified programmatically by running the actual commands independently
against the live codebase.

### Gaps Summary

No gaps found. All 12 derived must-have truths (roadmap goal decomposed + PLAN frontmatter must_haves
merged across all 3 plans) verified against the live codebase by running the actual test/grep/mypy
commands myself — not accepted from SUMMARY.md narrative. All 7 requirement IDs (BUS-01..04, CTX-01..03)
are SATISFIED with independent evidence; CTX-04 correctly remains scoped to Phase 3. The 2 advisory-review
warnings (WR-01 PortfolioHandler mode-agnosticism, WR-02 dead imports) are real but explicitly non-blocking
per the phase's own scope boundaries — WR-01 is deferred to P3/P6, WR-02 is a hygiene-only nit with no
correctness or oracle impact.

---

_Verified: 2026-07-09T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
