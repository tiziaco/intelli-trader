---
status: scheduled
created: "2026-07-13"
source: brainstorming session 2026-07-13 (ForceCloseEvent design spec, §8 draft) — operator emergency shutdown, surfaced as the fan-out consumer of the force-close primitive
tags: [live, operator-command, force-close, emergency-shutdown, halt, control-plane, order-handler, live-lifecycle, follow-up, next-milestone]
---

# Operator emergency-shutdown command — flatten ALL positions + latch HALTED (consumer of ForceCloseEvent)

**Origin:** Brainstorming session 2026-07-13 that produced
[[docs/superpowers/specs/2026-07-13-force-close-event-design]] (the `ForceCloseEvent` primitive +
honest strategy attribution). The user flagged an intent to add a human-triggered **emergency
shutdown** "in case of emergency." This is deliberately **out of scope** of the primitive spec; this
todo (lifted from the spec's former §8 DRAFT) captures the shutdown as the fan-out consumer to build
**on top of** the primitive once it lands.

**MUST BE CONCLUDED** into its own promoted spec (open questions below) before any implementation.

## What this is (and is NOT)

A human-triggered emergency: **flatten every open position and freeze the system.**

- **Ingress** — an operator command reaches the live system.
- **Fan-out** — for every open position across active portfolios, emit
  `ForceCloseEvent(origin=ForceCloseOrigin.OPERATOR)` (the primitive; side/size derived per spec
  **FC-05**, so a position that closes mid-fan-out is a clean no-op).
- **Halt** — latch `HALTED` (existing `halt(reason)` latch + CRITICAL alert + durable
  `HaltRecordStore`; `HALTED` has no legal exit except operator `reset_halt()`).

It is **distinct from** the targeted single-position operator close
([[operator-force-close-position-command]] — one `ForceCloseEvent`, no halt). That command is the
**simpler precursor**; this one adds the fan-out + lifecycle freeze.

## Why it's a clean fit on the primitive

Once the spec's `ForceCloseEvent` + `OrderHandler.on_force_close` land, the shutdown is a
higher-level orchestration sitting **above** the primitive: it emits N `ForceCloseEvent(origin=OPERATOR)`
and drives the existing halt machinery. Honest attribution (no `strategy_id`,
`OrderTriggerSource.OPERATOR_FORCE_CLOSE` on each order's state change) comes for free from the
primitive. Each exit bypasses admission adjudication but still gets a real venue fill (spec **FC-04**).

## Open questions to conclude (do NOT implement until answered)

1. **Ingress shape** — reuse the D-10 `STRATEGY_COMMAND` external-ingress path vs. a dedicated
   `LiveTradingSystem.emergency_shutdown(reason)` method. Thread-safety: connector-loop callbacks
   only flip thread-safe flags; blocking venue I/O runs on the engine thread, never the asyncio loop.
2. **Ordering** — halt-then-flatten (freeze new intake first, then flatten) or flatten-then-halt (get
   out, then freeze)? Interaction of `pause_submission(reason)` (reversible quiesce) vs the `halt`
   latch during the flatten window.
3. **Idempotency / re-entrancy** — behavior if pressed twice, or while a prior shutdown is in flight.
4. **Resting & in-flight orders** — cancel resting protective/bracket orders as part of the flatten?
   What about orders already submitted to the venue but unfilled?
5. **Partial failure** — if a venue exit is rejected (e.g. venue min-notional on a dust position),
   what is the operator-visible outcome and the resulting halt semantics?
6. **Un-refusability** — confirm the tier-2 path (venue still validates at execution — spec FC-04) is
   acceptable, or whether a panic path needs different handling for the dust/min-notional edge.

## Definition of done for concluding this todo

The six questions above resolved and promoted into a dedicated spec, then planned. Until then this is
informational only.

## When to schedule

After the `ForceCloseEvent` primitive lands and locks, and ideally after (or alongside) the targeted
single-position command — this shutdown reuses that command's `ForceCloseOrigin.OPERATOR` ingress
decisions.

## Tie-in / related

- **Depends on:** the `ForceCloseEvent` primitive —
  [[docs/superpowers/specs/2026-07-13-force-close-event-design]] (FC-01…FC-07).
- **Precursor (simpler):** the targeted single-position operator close —
  [[operator-force-close-position-command]]. Settle its ingress questions first; this shutdown fans
  the same origin out.
- **Reuses:** `OrderHandler.on_force_close`, the D-10 command-ingress seam, the `PortfolioReadModel`
  position lookup, and the live lifecycle `halt`/`pause_submission`/`HaltRecordStore` machinery.
