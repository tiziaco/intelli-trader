# Phase 7: Live Dynamic-Universe Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-06
**Phase:** 7-live-dynamic-universe-hardening
**Areas discussed:** Readiness-gate shape, Async warmup threading, Warmup-failure recovery,
Poll routing + HALT gate, Strategy add/remove-ticker seam, Warmup success/failure signaling,
is_ready consumers + indicator-ready composition, Admissible-event allowlist + D-18, WR-01 ×
TrackedInstrument

---

## Readiness-gate: enforcement point

| Option | Description | Selected |
|--------|-------------|----------|
| Data-layer (window soft-returns empty) | Every consumer inherits the gate; but "empty" vs "not ready" ambiguous, masks real gaps | |
| Membership-layer (consumers check is_ready) | Explicit first-class fact (LEAN IsReady); window() keeps raising | ✓ |
| You decide | — | |

**User's choice:** Membership-layer explicit `is_ready`, keep `window()` raising.
**Notes:** User asked "what's best / what do frameworks do." Answered: LEAN (`HasData`/`IsReady`
explicit + slice-absence skip) and Nautilus (`indicator.initialized`) both make readiness explicit,
never a silent empty. Softening `window()` = silent-wrong-number (the trap WR-01 rejected). Admission
is the primary gate consumer; strategy loop already protected by data-absence.

## Readiness-gate: state home

| Option | Description | Selected |
|--------|-------------|----------|
| On Universe (separate _ready map) | Second symbol-keyed map — desync hazard | (superseded) |
| Separate ReadinessRegistry | Extra object + wiring | |
| ONE record map on Universe (TrackedInstrument) | Mutable record wraps frozen Instrument + readiness + leaving; one map | ✓ |

**User's choice:** ONE `dict[str, TrackedInstrument]` on `Universe` (LEAN `Security` model).
**Notes:** User pushed back on the separate-map option ("I'll have to manage two lists on every
insert/delete") — correct; improved to a single mutable record. Then asked whether readiness could go
on `Instrument` itself — answered no (frozen/immutable; category + lifetime mismatch; cross-domain
precision reads). LEAN (`SymbolProperties` vs `Security`) + Nautilus (Cache `Instrument` vs runtime
`initialized`) both separate immutable metadata from mutable readiness. User audited `Instrument`
fields and correctly flagged `borrow_rate`/`maintenance_margin_rate`/`max_leverage`/
`liquidation_fee_rate` as conceptually time-varying → captured as a deferred refactor todo. User
chose name `TrackedInstrument` as a placeholder pending the mutable-Instrument refactor.

## Async warmup threading

| Option | Description | Selected |
|--------|-------------|----------|
| Async fetch → event → engine replays | I/O off-thread, state mutation on engine thread (Nautilus request_bars) | ✓ |
| Fetch + replay on loop, update() locked | Second writer on the ring + lock contention — breaks D-19 | |
| You decide | — | |

**User's choice:** Async fetch → event → engine-thread replay. Then refined heavily (see below).
**Notes:** User questioned the K-BarEvent flood and proposed a strategy-owned provider fetch.
Reconciled: keep provider feed-side (strategies stay pure consumers), but replay fetched bars via the
identical `strategy.update()` path with NO signal emission. User then proposed a **single `BarsLoaded`
event carrying all bars** consumed by `StrategiesHandler` — agreed (bulk transport); clarified the
per-bar loop is intrinsic to stateful indicators (bulk = LX-09 divergence trap), which is exactly
what LEAN (`WarmUpIndicator`) and Nautilus (`on_historical_data`) do. Ready-flip simplified to
"warm → mark_ready → subscribe" (no "first live bar" trick needed once warmup emits no tradeable
events).

## Warmup-failure recovery + retry bound

| Option | Description | Selected |
|--------|-------------|----------|
| Stay pending → retry next poll | Gate keeps it dark; re-attempt next poll (Nautilus isolate) | ✓ |
| Roll back out of membership | 06-REVIEW stopgap; redundant churn once the gate exists | |
| Leave + log only | Strands the symbol | |
| — retry: unbounded, validate_symbol-filtered | Delisted drops at source; no cap state | ✓ |
| — retry: capped + backoff | Failure-count state for an edge case | |

**User's choice:** Isolate + `BarsLoadFailed` → mark `failed` → unbounded retry; `validate_symbol`
filters delisted at the source.

## Poll routing (WR-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated EventType.UNIVERSE_POLL route | Contract-clean; gate-able independently (Nautilus/LEAN separate control-plane) | ✓ |
| Keep shared TIME route | Leaves the screener/bar-gen coupling WR-06 flags | |

**User's choice:** Dedicated `UNIVERSE_POLL` discriminator.

## Freeze deltas (WR-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Skip during freeze | Level-triggered membership self-heals next tick; freeze-in-place | ✓ |
| Replay buffered deltas | Edge-triggered thinking on a level-triggered signal | |

**User's choice:** Skip (early-return in `on_poll`). WR-03 fold-in: `Field(gt=0.0)` fail-loud.
**Notes:** Both settled jointly after framework grounding (Nautilus/LEAN reconcile against current
state on resume, never replay a backlog). Membership is level-triggered — the decisive point.

## Strategy add/remove-ticker seam (new)

| Option | Description | Selected |
|--------|-------------|----------|
| Defer to its own phase | Keeps Phase 7 pure hardening | |
| Minimal opt-in engine seam now | Static tickers stay; operator edit propagates via WR-02 path | ✓ |
| Full dynamic (LEAN) binding now | Reshapes strategy-authoring + oracle path | |

**User's choice:** Engine-side seam in Phase 7 (UI transport deferred). Refined across several turns:
- **Event name:** `StrategyCommandEvent` (user's — strategy-subject, extensible to enable/disable/
  reconfigure), not `UniverseCommandEvent`.
- **Ingress:** user proposed a generic `queue_event(event)` with an allowlist; discovered the existing
  `add_event` (D-18) is a denylist → inverted to a fail-closed allowlist `{SIGNAL, STRATEGY_COMMAND}`.
- **Wrappers:** user asked to keep `add_ticker`/`remove_ticker` off `LiveTradingSystem` → resolved via
  event factory classmethods + handling in `StrategiesHandler`.
- **Propagation:** user asked "shouldn't strategy_handler emit an event for the universe?" → yes;
  chose emit-`UNIVERSE_POLL` (causal cascade) over route fan-out. Matches Nautilus `subscribe_bars`
  command + LEAN `AddCrypto → OnSecuritiesChanged`.
- **Apply timing:** immediate (emit `UNIVERSE_POLL` now) over defer-to-next-poll.
- **Selection source:** swap frozen `StaticUniverseSelectionModel` for a strategy-derived one.

## Warmup success/failure signaling

**User's choice:** Two distinct events — `BarsLoaded(sym, tf, bars)` (success) / `BarsLoadFailed(sym,
reason)` (failure) — so neither consumer branches on a status field.

## is_ready consumers + indicator-ready composition

**User's choice:** Both gates checked in the strategy loop (`update` always → `universe.is_ready`
warm-but-don't-trade → `strategy.is_ready` indicator warmth → `generate_signal`). Membership-ready ⇒
indicator-ready by construction (warmup depth ≥ deepest declared warmup). `is_ready` gate's real job:
admission + external orders + defensive strategy-loop check.
**Notes:** Investigation found warmup replay emits `BarEvent`s through the pipeline (`_deliver`→
`_emit`), which drove the redesign to direct `strategy.update()` (no signals) — removing the
trading-on-warmup-bars hazard entirely.

## Admissible-event allowlist + D-18

**User's choice:** Invert existing `add_event` from denylist (reject ORDER, admit rest — fail-open) to
allowlist `_EXTERNALLY_ADMISSIBLE = {SIGNAL, STRATEGY_COMMAND}` (fail-closed). Internal facts
(`FillEvent`, `BarEvent`, `UniverseUpdateEvent`, `BarsLoaded/Failed`, etc.) rejected by default.
Strengthens D-18 (ASVS V4/V5 default-deny). User asked to keep wrappers off `LiveTradingSystem` →
factory + domain-handler handling.

## WR-01 keep-until-flat × TrackedInstrument

**User's choice:** `apply()` stops popping removed-but-held records; teardown = single atomic
`_entries.pop()` (`discard_instrument`) at no-holder-removal + detach-on-flat; add-branch guard
(fresh→PENDING / re-add-of-held→clear-leaving-keep-ready-no-rewarmup); `_leaving` folds into the
record; readiness ⟂ leaving. The single-record model eliminates the WR-01 desync bug class by
construction.

## Claude's Discretion
- `TrackedInstrument` field/method layout + `Readiness` enum home.
- `BarsLoaded`/`BarsLoadFailed` field shapes; whether `BarsLoaded` fans out to the feed ring
  (ring-consumer research flag).
- Whether the ticker edit rides `update_config` D-11 vs the new `StrategyCommandEvent`.
- Warmup fetch depth across multiple strategies sharing a symbol.
- Markets-map resolver interface + composition-root wiring.
- `UNIVERSE_POLL` timer mechanism + default cadence.

## Deferred Ideas
- UI/FastAPI transport for `StrategyCommandEvent` (app-layer plan).
- Full universe-driven strategy scope (LEAN `OnSecuritiesChanged`) — arrives with the screener.
- Mutable-`Instrument` refactor + `TrackedInstrument` rename (`.planning/todos/
  mutable-instrument-refactor.md`).
- Warmup-failure retry cap/backoff (only if REST budget is a problem).
