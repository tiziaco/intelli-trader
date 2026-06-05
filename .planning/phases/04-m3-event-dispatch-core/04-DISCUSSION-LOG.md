# Phase 4: M3 — Event & Dispatch Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-05
**Phase:** 4-m3-event-dispatch-core
**Areas discussed:** Event schema shape, Linkage ID strictness, Dispatch registry design, Exceptions & logging posture, Event module organization, Typed pipeline-state shape, Oracle gate & test additions, Intra-phase sequencing

---

## Event schema shape

| Option | Description | Selected |
|--------|-------------|----------|
| Frozen dataclass base | frozen/slots/kw_only Event base with event_id/created_at/time/type; subclassed | ✓ |
| Protocol + per-event fields | runtime_checkable Protocol; fields duplicated per event | |
| Base class + Protocol | Base for concrete events + narrow Protocol at consumer seams | |

**User's choice:** Frozen dataclass base

| Option | Description | Selected |
|--------|-------------|----------|
| uuid7 + business time | event_id default_factory uuid7; created_at defaults to business time | ✓ |
| uuid7 + injected Clock | Clock threaded into every construction site | |
| uuid7 + wall clock | datetime.now(UTC) — contradicts M2-05 determinism | |

**User's choice:** uuid7 + business time

| Option | Description | Selected |
|--------|-------------|----------|
| Drop field, typed outcome | Remove verified; validator/risk return typed verdict | ✓ |
| dataclasses.replace copies | Keep verified as frozen field, copy per stage | |
| Verification wrapper | Mutable pipeline-local wrapper around pure signal | |

**User's choice:** Drop field, typed outcome (later refined by Order-entity-as-state decision)

| Option | Description | Selected |
|--------|-------------|----------|
| Stay float until M4 | Preserve Decimal→float boundary coercions exactly | ✓ |
| Retype to Decimal now | Pulls M4-07 forward; numeric-drift risk vs byte-exact gate | |

**User's choice:** Stay float until M4

| Option | Description | Selected |
|--------|-------------|----------|
| New Side/Action enum | Dedicated BUY/SELL enum in core/enums for signal→order→fill | ✓ |
| Reuse TransactionType | Couples events to portfolio-domain vocabulary | |
| You decide | | |

**User's choice:** New Side/Action enum

| Option | Description | Selected |
|--------|-------------|----------|
| One generic ErrorEvent | Single frozen ErrorEvent under EventType.ERROR | |
| Keep per-domain error events | PortfolioErrorEvent + siblings per domain | |
| Concrete base (hierarchy) | User-proposed: concrete ErrorEvent base + per-domain children, all type=ERROR | ✓ |

**User's choice:** User proposed a FastAPI-style hierarchy (ErrorEvent parent + PortfolioErrorEvent child); confirmed concrete/instantiable base over abstract-only.
**Notes:** User: "that's what I usually do when developing applications in FastAPI." Mirrors core/exceptions hierarchy shape.

| Option | Description | Selected |
|--------|-------------|----------|
| Type what's cheap | Tighten where a shape exists; no invented DTOs | ✓ |
| Full typed payloads | New frozen payload dataclasses for both dicts | |
| You decide | | |

**User's choice:** Type what's cheap

---

## Linkage ID strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Extend typed outcome | Resolved quantity rides typed pipeline state (Decimal) | ✓ |
| Replace-with-sized-copy | dataclasses.replace(signal, quantity=...) | |
| You decide | | |

**User's choice:** Extend typed outcome (later refined by Order-entity-as-state)
**Notes:** Discussion discovered the second in-place mutation: `_resolve_signal_quantity` patches `signal_event.quantity` (order_manager.py:276,289).

| Option | Description | Selected |
|--------|-------------|----------|
| Optional, None = size me | quantity: float \| None = None; kills 0-sentinel; M5b owns final fate | ✓ |
| Remove the field now | Pre-judges M5-06 policy design; breaks explicit-qty path | |
| Keep float 0-sentinel | Magic sentinel survives redesign | |

**User's choice:** Optional, None = size me
**Notes:** User asked whether full removal was already planned — it is not; M5-06 owns sizing-policy completion.

| Option | Description | Selected |
|--------|-------------|----------|
| Create-all-then-emit | Build parent+SL/TP entities first, populate child_order_ids, emit complete events parent-first | ✓ |
| Snapshot-at-emission | Parent event ships empty children; linkage via child events only | |
| You decide | | |

**User's choice:** Create-all-then-emit, after requesting a before/after code example.

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal conformance | Entities guarantee ids in-scope; trading_interface gets smallest fix (D-live) | ✓ |
| Strict: entities everywhere | Deep live-path rework in a deferred module | |
| You decide | | |

**User's choice:** Minimal conformance

---

## Dispatch registry design

| Option | Description | Selected |
|--------|-------------|----------|
| EventHandler-owned dict | Full registry literal in __init__; ordering is reviewable data | ✓ |
| Handler self-registration | subscribe() API; ordering implicit in wiring-call order | |

**User's choice:** EventHandler-owned dict, after requesting code examples of both.

| Option | Description | Selected |
|--------|-------------|----------|
| Fail-fast + log ERROR | No catch in loop; ERROR route logs | |
| Catch-and-publish | Handler exceptions become ErrorEvents; run continues | |
| Seam now, fail-fast default | _on_handler_error policy seam; backtest re-raises | ✓ |

**User's choice:** Seam with fail-fast default — user asked for future-proofing; clarified that business errors are data below the dispatcher (run continues) while handler exceptions are bugs (fail fast).

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit empty routes | SCREENER/UPDATE registered empty + deferral comment; unknown raises | ✓ |
| Debug-log consumer | logger.debug callback instead of empty list | |
| Unregistered → raise | Would crash screener-wired backtests | |

**User's choice:** Explicit empty routes
**Notes:** Discussion discovered a latent crash: PortfolioErrorEvent (type=UPDATE) is queued on failure but the chain has no UPDATE branch.

---

## Exceptions & logging posture

| Option | Description | Selected |
|--------|-------------|----------|
| Full in-scope adoption + prune | Replace bare raises in-scope; delete dead execution.py classes + ConcurrencyError family; fix KB24 | ✓ |
| Minimal: mandated fixes only | Only KB1/KB24/swallowed-None on engine path | |
| Adopt + keep execution.py | Wire 12 dead classes in — contradicts outcomes-as-data design | |

**User's choice:** Full in-scope adoption + prune, with base exception renamed.

| Option | Description | Selected |
|--------|-------------|----------|
| ITraderError | Package-named, Python convention | ✓ |
| TradingSystemError | Drops the I prefix only | |
| TradingError | Risks reading as business outcome | |

**User's choice:** ITraderError
**Notes:** User dislikes the C#-style I-interface prefix of ITradingSystemError.

| Option | Description | Selected |
|--------|-------------|----------|
| Full in-scope cleanup | Stragglers + json_logs config-driven + import-time guard + falsy checks | ✓ |
| Convention-only | Just swap stragglers | |
| You decide | | |

**User's choice:** Full in-scope cleanup

| Option | Description | Selected |
|--------|-------------|----------|
| Levels now, rendering later | Per-tick → DEBUG, lifecycle → INFO; rendering revamp deferred | ✓ |
| Levels + rendering now | Presentation work expansion | |
| Neither | Keep current verbosity | |

**User's choice:** Levels now, rendering later
**Notes:** User raised this as a free-text question ("I'm logging everything, even the ping events").

---

## Event module organization

| Option | Description | Selected |
|--------|-------------|----------|
| Events package | events_handler/events/ split with __init__ re-exports (D-11 precedent) | ✓ |
| Single event.py | One ~600-line module | |
| You decide | | |

**User's choice:** Events package

| Option | Description | Selected |
|--------|-------------|----------|
| TimeEvent family | TimeEvent / EventType.TIME / TimeGenerator / time_generator.py (Nautilus precedent) | ✓ |
| ClockEvent family | Zipline-style; name-adjacent to core/clock.py Clock | |
| Keep Ping family | Docstring fix only | |

**User's choice:** TimeEvent family
**Notes:** User asked what PingEvent does and whether it should be TICK; after industry-naming review (Nautilus TimeEvent, Zipline clock, QuantStart heartbeat) chose TimeEvent and reserved TICK for future live market-data ticks. Rename covers the generator file/class too.

---

## Typed pipeline-state shape

| Option | Description | Selected |
|--------|-------------|----------|
| Order entity as state | Entity born PENDING after sizing; validated as entity; rejection = audited REJECTED state change | ✓ |
| Ephemeral OrderSpec | Frozen internal dataclass, consumed and discarded | |
| You decide | | |

**User's choice:** Order entity as state
**Notes:** User challenged OrderSpec's value ("would I use it? would I log it for audit? what's the standard?"); FIX/Nautilus lifecycle comparison led to the entity-as-state decision.

---

## Oracle gate & test additions

| Option | Description | Selected |
|--------|-------------|----------|
| Ordering + immutability + error flow | Three targeted test groups locking the phase's invariants | ✓ |
| Minimal: ordering only | Single most load-bearing invariant | |
| You decide | | |

**User's choice:** Ordering + immutability + error flow
**Notes:** Oracle cadence carried forward as settled: byte-exact suite assertions green at every commit; no D-17-style reference capture needed.

---

## Intra-phase sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Planner discretion | Free ordering under suite+oracle-green-per-commit, bisectable commits | ✓ |
| Events first | Pin schema redesign first | |
| Dispatch first | Pin small isolated fix first | |

**User's choice:** Planner discretion

---

## Claude's Discretion

- Event base field mechanics (`type` field implementation), EventType class-enum details
- ErrorEvent field set / severity vocabulary / to_dict fate
- Module split details within events_handler/events/ and re-export surface
- New order/data exception module contents, error_code scheme, swallowed-None conversions
- Validator/risk-manager signature changes for entity-based validation; storage-count test impact
- FillEvent extras beyond requirement (e.g. exchange field)
- mypy override list adjustments

## Deferred Ideas

- TickEvent for live market-data ticks (D-live)
- Live dead-letter `_on_handler_error` override (D-live)
- SignalEvent.quantity → sizing-policy declaration (M5b, M5-06)
- Terminal-rendering redesign / structlog processors (≈M5b #38)
- engine_logger.py deletion (M5b, M5-07)
- Event money fields → Decimal + frozen execution DTOs (M4, M4-07)
- Bar struct + get_last_* removal (M5a, M5-02)
- FillEvent slippage-vs-price separation (M5a, M5-04)
