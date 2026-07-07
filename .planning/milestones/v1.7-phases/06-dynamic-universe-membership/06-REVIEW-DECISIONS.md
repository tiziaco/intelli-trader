---
phase: 06-dynamic-universe-membership
doc: review-decisions
created: 2026-07-06
source_review: 06-REVIEW.md
status: open
purpose: >
  Settle the five review findings that require a design/policy choice before
  any --fix pass. CR-01 and WR-03 are mechanical (handled separately) and are
  NOT in this doc.
decisions:
  CR-01: "decided — mechanical; apply now via gsd-quick"
  WR-03: "decided — Field(gt=0.0) fail-loud; apply now via gsd-quick"
  WR-01: "routed to Phase 7 — keep-until-flat invariant (design settled below)"
  WR-02: "routed to Phase 7 — async warmup + isReady readiness gate (centerpiece)"
  WR-04: "routed to Phase 7 — leaning markets-map resolver seam"
  WR-05: "routed to Phase 7 — leaning short-circuit on_time + skip"
  WR-06: "routed to Phase 7 — leaning dedicated UNIVERSE_POLL route"
resolution_routing:
  apply_now: [CR-01, WR-03]
  phase_7_live_dynamic_universe_hardening: [WR-01, WR-02, WR-04, WR-05, WR-06]
  note: >
    WR-04/05/06 detailed decisions deferred to the Phase 7 discuss session
    (they interact with each other and with WR-02's readiness gate; settle
    jointly). Leanings below are starting positions, not final decisions.
---

# Phase 06 — Code-Review Decisions

Five findings from `06-REVIEW.md` are not drop-in fixes: each names a fork the
reviewer left open. This doc frames each choice, the tradeoffs, and a
recommendation, so `--fix` (or a follow-up plan) executes a decision rather than
guessing.

**Out of scope here (mechanical, apply directly):**
- **CR-01** — `unsubscribe` must also `_streams_down.discard(sym)` + `_reconnect_attempts.pop(sym, None)`. Drop-in, no choice. *(Blocker — apply first.)*
- **WR-03** — bound `universe_poll_cadence_s` (`Field(gt=0.0)`). Only sub-choice = fail-loud vs clamp; folded into WR-05's config note below.

**Cross-cutting scope question (answer this first — it gates 3 of the 5):**
Four findings (WR-01, WR-04, WR-05, WR-06) only bite the **live + margin** path.
The current milestone is **backtest-correctness on `SMA_MACD` (spot/paper)**,
where every one of them is masked or inert. So for each, the real first question
is **fix-now vs track-and-defer**. That framing is called out per finding.

---

## WR-01 — Instrument dropped for a still-held removed symbol

**DECIDED: keep-until-flat, invariant-based (option A). Implement now.**

**What the code does now.** `Universe.apply` (`universe.py:155-156`) pops the
removed symbol's `Instrument` *immediately*, before the `UniverseUpdateEvent` is
even emitted — even under `orphan-and-track`, where the position is still open and
being wound down. Two consumers then read that instrument on a still-open orphan:
- `portfolio_handler.py:518` — **raw `self._universe.instrument(ticker)`** → bare `KeyError` mid margin-liquidation.
- `portfolio.py:865` — already guarded, but deliberately **raises `StateError`** ("universe carries Instrument for {ticker}") on the short-carry accrual.

So the position under-tracks: the moment a symbol is removed, any margin
mark-to-market / carry / liquidation over its still-open orphan crashes.

### Root cause

`apply()` ties the **Instrument's lifetime to membership**. But the Instrument
(precision, maintenance-margin rate, borrow rate) is not a *membership* attribute
— it is an *exposure* attribute, needed by mark-to-market, carry accrual, and
liquidation, all of which **outlive membership** under both remove policies
(orphan-and-track holds the position until flat; force-close's exit fills
asynchronously later). Deleting it at membership-removal time is a category error:
it destroys data that still-open positions depend on. The code already solves this
exact problem for the *stream* (orphan-and-track keeps the WS/ring alive and tears
it down in `on_fill` detach-on-flat, `universe_handler.py:288`) — the Instrument
simply is not following that same lifecycle.

### The invariant (the thing we are putting in place)

> An `Instrument` must exist for a symbol as long as it is **a member OR has any
> open exposure** (position / resting order / carry). It may be dropped only when
> *both* are false — i.e. at the exact moment the stream is finally torn down
> (flat). Instrument lifetime == stream lifetime == "kept alive until flat."

### Implementation

**1. Stop removing instruments in `apply()`.** Delete the loop at
`universe.py:155-156`:
```python
for sym in removed:
    self._instruments.pop(sym, None)   # ← delete
```
`apply()` mutates membership only. This is also the D-03-correct place to remove
it *from*: `Universe` is connector-free and holds no read-model, so it cannot know
whether a removed symbol is still held. That exposure decision belongs to
`UniverseHandler`, which owns the read-model and already orchestrates the remove
policy + detach-on-flat.

**2. Guard the add-branch against clobbering (`universe.py:159-160`).** A symbol
that leaves-but-is-held (instrument now retained) and is later re-desired reappears
as `added`; today the add loop overwrites its good instrument with a `_DEFAULT_*`
one (acute on the poll path where `instruments=None`). Preserve-then-resolve:
```python
for sym in added:
    if sym not in self._instruments:        # keep a still-tracked instrument
        self._instruments[sym] = resolved.get(sym) or self._default_instrument(sym)
```

**3. Move instrument teardown to where stream teardown already lives.** Add an
explicit `Universe.discard_instrument(sym)` and call it at the two final-teardown
points in `UniverseHandler`, co-located with the existing unsubscribe:
- `_on_symbol_removed` no-holder branch (`:252`) — after `_unsubscribe(sym)`, nothing references it → drop it.
- `on_fill` detach-on-flat (`:288`) — after `clear_leaving(sym)`, the orphan just went flat → drop it.

### Why not the alternatives

- **Default-instrument fallback (B).** Silences the crash but prices a live margin
  wind-down with wrong 2dp/8dp scales — under the Decimal/money-correctness policy
  that is strictly worse (silent wrong number vs. loud correct failure). It is also
  whack-a-mole: guards every current *and future* instrument-read site; the
  lifecycle fix closes them all at the source.
- **Track-only (C).** Leaves the invariant unstated and the crash latent.

### Scope / scheduling

The design above is the correct target regardless of timing. It only *fires* on the
live + margin + dynamic-universe path, which the current spot/paper `SMA_MACD`
milestone does not exercise — but the decision is to **put the invariant in place
now** (it is low-risk on the inert path and removes a latent crash + a silent
precision-clobber), not defer it.

**Decision:** **[x] A — keep-until-flat, invariant-based, implement now.**

---

## WR-02 — No rollback / isolation on partial add failure

**ROUTED TO PHASE 7 — escalated to the proper long-term design: async warmup +
per-symbol `isReady` readiness gate (this is Phase 7's centerpiece).**

The rollback option below (isolate + remove-from-membership) is the correct
*approximation within the current synchronous architecture*, and remains the
fallback if the readiness gate is descoped. But the decision is to build the real
thing: warmup runs on the connector's async substrate (already present — OKX
provider spawns aiohttp tasks); a symbol is marked `pending` on add and `ready`
only when warmup completes (then subscribe — Pitfall 6 ordering preserved); a
failed warmup marks `failed`/drops for next-poll retry. This turns today's implicit
"not ready = `window()` raises `MissingPriceDataError`" hard failure into a **soft
per-symbol gate**, which every membership consumer (strategies, screeners,
admission) then respects.

**Framework precedent (why this is the right target):**
- **QuantConnect LEAN** — same universe-selection seam (`OnSecuritiesChanged` with
  added/removed). Changes processed **per-security, independently** (no batch to
  poison); data readiness is a **per-security gate** (`IsReady`), not a membership
  fact; and LEAN **keeps a held security's subscription alive** rather than removing
  it — this codebase already borrowed that for orphan-and-track.
- **Nautilus Trader** — per-instrument subscribe/unsubscribe; warmup is an async
  request-response (`request_bars`); a failed request is isolated and never aborts
  other subscriptions.
- Common thread: **"activated & data-ready", not "selected", is what the engine
  keys on.** This codebase lacks that gate today (`member ⇒ has data` is assumed
  unconditionally) — Phase 7 introduces it.

**Interim stopgap decision:** see below (per-symbol isolation lands with the
mechanical fixes, or folds into Phase 7 — pending user call).

**What the code does now.** `on_universe_update` (`universe_handler.py:221-231`)
loops added symbols doing `warmup` then `subscribe`, with **no per-symbol
try/except**. `apply` has *already* mutated membership before this runs. So if
`warmup(sym)` raises: that symbol is a member with no data, every *later* added
symbol is skipped, and the entire `removed` loop never runs. Live error policy
(`_publish_and_continue`) emits an ErrorEvent and keeps draining → divergence is
permanent, not self-correcting. A later `window(sym)` surfaces
`MissingPriceDataError` deep on the live path.

**Why it's a decision.** The *isolation* half is mechanical (wrap each symbol in
try/except so one failure can't abort the batch or block the remove branch). The
*recovery* half is a policy fork — what happens to the symbol that failed:

**Options (recovery policy):**
- **A — Roll back out of membership (recommended).** On failure, remove the symbol from `Universe._members` again so membership and data/stream state stay consistent; it re-enters naturally on the next poll if still desired. Strongest invariant: "a member always has data." Cost: `apply` already emitted the delta with this symbol in `added`, so the rollback must also reconcile the emitted event's view — simplest is to mutate membership back and log; the next poll re-proposes it.
- **B — Re-queue / retry.** Keep it a member, retry warmup on the next poll tick. Simpler, but leaves a data-less member in the window between failure and next poll (the `MissingPriceDataError` window still exists, just bounded by cadence).
- **C — Leave + log only.** Isolation without rollback. Cheapest; keeps the "data-less member" hazard indefinitely. Not recommended.

**Recommendation:** **isolation always** + **A (rollback)**. Preserves the
"member ⇒ has data" invariant that the rest of the live path assumes. This one is
worth doing regardless of margin scope — it's a live-path robustness gap that a
single flaky OKX REST warmup can trigger.

**Decision:** _[ ]_ isolate + rollback (A) · _[ ]_ isolate + retry (B) · _[ ]_ isolate + log (C)

---

## WR-04 — Poll-added OKX symbols get default precision, not venue-correct

**What the code does now.** `on_time` calls `self._universe.apply(desired, None)`
(`universe_handler.py:196`), so every dynamically-added symbol resolves through
the `_DEFAULT_*` ladder (2dp price / 8dp qty). Wiring-time members get
venue-correct instruments via `derive_instruments`; poll-added members silently
do not. On live OKX, subsequent order quantization uses wrong scales →
mis-sized/mis-priced orders on the added symbol. The code comment
(`universe_handler.py:190-195`) explicitly defers this to "plan-05 composition-root
wiring."

**Why it's a decision.** It's genuine design work, not a patch — it needs a new
seam, and the seam's shape must preserve `Universe`'s connector-free contract (D-03).

**Options:**
- **A — Inject a markets-map resolver into `UniverseHandler` (recommended).** Give the handler a `MarketsMap`/precision-resolver seam (built at the composition root from the OKX markets map, same source as `derive_instruments`). In `on_time`, resolve instruments for `desired`'s added symbols and pass a real `instruments` dict into `apply`. `Universe` stays connector-free (it still just receives a dict). Testable with a fake resolver.
- **B — Resolve at the composition root, push into the event.** Have the timer/composition layer resolve and carry instruments on the `UniverseUpdateEvent`; `on_time` stays thin. More plumbing through the event payload; couples the event to precision.
- **C — Track-and-defer.** Backtest/paper is unaffected (default ladder is paper-correct); only live operator-driven adds are wrong. Defer until live OKX trading of dynamically-added symbols is a real workflow.

**Recommendation:** **A** when live-add is in scope; **C** for now if the milestone
is still spot/paper `SMA_MACD`. This is the clearest "defer unless live is active"
of the set — the comment already treats it as planned future work.

**Decision:** _[ ]_ A now · _[ ]_ B · _[ ]_ C-track

---

## WR-05 — Poll / remove not gated by HALT / pause

**What the code does now.** `_dispatch_live` (`live_trading_system.py:1058-1059`)
gates only `SIGNAL`/`ORDER` when halted/paused. A control-plane `TimeEvent` passes
straight through, so `UniverseHandler.on_time` still polls and applies membership
deltas during a freeze. Under `force-close`, a removal during HALT emits a
market-exit `SignalEvent` that the SIGNAL gate then *suppresses* — yet
`_on_symbol_removed` still `mark_leaving` + `unsubscribe`s the symbol → the
position is left **naked and blind** (no exit, no stream), contradicting the
"freeze in place, stay mirrored" halt contract.

**Why it's a decision.** Two sub-choices, and they interact with WR-06.

**Sub-choice 1 — where to gate:**
- **A — Short-circuit `UniverseHandler.on_time`** early-return when `is_halted or is_submission_paused` (needs the handler to see engine status via an injected predicate). Localized to the universe subsystem.
- **B — Gate the TIME route** in `_dispatch_live` (extend the existing gate to TIME). Broader — also silences screener/bar handlers on TIME, which are dormant now but may not stay so. Overlaps with WR-06's routing decision.

**Sub-choice 2 — deltas discovered during a freeze:**
- **Skip (recommended)** — don't poll at all while frozen; membership resumes churning on unfreeze from the then-current desired set. Simple, matches "freeze in place."
- **Replay** — buffer deltas seen during the freeze, apply on resume. More machinery; rarely worth it for a poll that will just re-observe current state next tick.

**Config note (WR-03 fold-in):** while here, bound `universe_poll_cadence_s`
with `Field(gt=0.0)` — recommend **fail-loud at config load** over silent clamp.

**Recommendation:** **A + Skip** — short-circuit `on_time` when halted/paused, no
replay. Keeps the fix inside the universe subsystem and honors the halt contract.
Worth doing before any live run with `force-close` enabled.

**Decision:** where = _[ ]_ A (on_time) · _[ ]_ B (TIME route)  |  deltas = _[ ]_ skip · _[ ]_ replay

---

## WR-06 — Control-plane `TimeEvent` reuses the shared TIME route

**What the code does now.** The poll timer emits a plain
`TimeEvent(time=datetime.now(UTC))` (`live_trading_system.py:1790-1792`) onto the
**same `EventType.TIME` route** (`full_event_handler.py:89-92`) that also fans to
`screeners_handler.screen_markets` and `feed.generate_bar_event`. Both are dormant
on the live path today (bar-gen returns `None`, screeners empty) → **currently
inert**. But the poll is coupled by event type to unrelated handlers: the moment a
screener is registered live, `screen_markets` runs against wall-clock time and
calls `feed.megaframe(...)` on the `LiveBarFeed` — not what the poll intends. This
is also the sole non-business-time `TimeEvent` on the live path.

**Why it's a decision.** Architectural fork with a queue-contract tradeoff.

**Options:**
- **A — Dedicated control-plane discriminator.** Add e.g. `EventType.UNIVERSE_POLL` with its own single-handler route → `UniverseHandler.on_time`. Keeps the queue-only contract intact and cleanly separates control-plane cadence from business TIME. Cost: new event type + route (the documented 3-step new-event flow). Cleanest long-term; also subsumes WR-05 sub-choice 1 (the poll route is trivially gate-able independently of business TIME).
- **B — Invoke `UniverseHandler.on_time` directly from the timer.** Timer calls the handler method instead of enqueuing an event. No new type, but **bypasses the queue-only contract** (the timer reaches across a domain boundary) and loses the single-writer ordering guarantee that routing through the queue gives.
- **C — Track-and-defer.** It's inert until a live screener is registered. Safe to leave until then.

**Recommendation:** **A** — a `UNIVERSE_POLL` discriminator. It's the contract-clean
option and it makes WR-05 fall out naturally (gate/skip a dedicated route, not the
shared one). If we're deferring the live-path cluster, **C** is fine short-term
since it's provably inert today. Do NOT pick B — it re-introduces a cross-domain
direct call the architecture explicitly forbids.

**Decision:** _[ ]_ A (new discriminator) · _[ ]_ B (direct call) · _[ ]_ C-track

---

## Suggested batch resolution

If the milestone is still **spot/paper `SMA_MACD` backtest-correctness**, a
coherent default is:

| Finding | Default call | Rationale |
|---|---|---|
| WR-01 | **A, deferred** | margin-only; wrong-scale fallback (B) is worse than a loud crash |
| WR-02 | **isolate + rollback, now** | live-path robustness; one flaky warmup triggers it regardless of margin |
| WR-04 | **C-track** (A when live-add lands) | comment already treats as planned; paper unaffected |
| WR-05 | **A + skip, now** | cheap, honors halt contract; needed before any `force-close` live run |
| WR-06 | **A** (or C-track) | contract-clean; pairs with WR-05 gating |

Net: **two fix-now** (WR-02, WR-05) that harden the live path without touching the
oracle, plus **CR-01 + WR-03** mechanical — and **three tracked** (WR-01, WR-04,
WR-06) that only matter once margin / live-add / live-screener paths are exercised.
Adjust the calls above and I'll turn the "now" set into a `--fix` scope or a
follow-up plan.
