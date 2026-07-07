---
phase: 06-dynamic-universe-membership
reviewed: 2026-07-06T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - itrader/config/system.py
  - itrader/core/enums/event.py
  - itrader/core/enums/order.py
  - itrader/events_handler/events/__init__.py
  - itrader/events_handler/events/market.py
  - itrader/events_handler/full_event_handler.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/__init__.py
  - itrader/universe/membership.py
  - itrader/universe/universe.py
  - itrader/universe/universe_handler.py
  - tests/e2e/test_okx_dynamic_universe.py
  - tests/integration/conftest.py
  - tests/integration/test_okx_inertness.py
  - tests/integration/test_universe_force_close.py
  - tests/integration/test_universe_remove_policy.py
  - tests/unit/connectors/test_okx_data_provider.py
  - tests/unit/events/test_universe_update_event.py
  - tests/unit/order/test_leaving_symbol_admission.py
  - tests/unit/price/test_okx_dynamic_subscribe.py
  - tests/unit/price/test_warmup_on_add.py
  - tests/unit/universe/test_universe_apply.py
  - tests/unit/universe/test_universe_poll.py
  - tests/unit/universe/test_universe_selection.py
findings:
  critical: 1
  warning: 6
  info: 2
  total: 9
status: partially_resolved
resolved_by: "quick task 260706-l48 (CR-01, WR-03; commit e08424d2) + Phase 7 Live Dynamic-Universe Hardening (WR-01/02/04/05/06; PR #81 / af1ddb5a, 2026-07-07)"
resolution:
  resolved:
    - "CR-01 — fixed in quick task 260706-l48 (commit e08424d2, 2026-07-06); unsubscribe further marshaled onto the connector loop in Phase 7 07-09 (WR-03, PR #81 / af1ddb5a)"
    - "WR-03 — fixed in quick task 260706-l48 (commit e08424d2, 2026-07-06)"
    - "WR-01 — fixed in Phase 7 07-02 keep-until-flat (TrackedInstrument + _entries + discard_instrument; PR #81 / af1ddb5a)"
    - "WR-02 — fixed in Phase 7 07-02/03/04/06/08 async warmup + per-symbol isReady readiness gate + per-symbol isolation (PR #81 / af1ddb5a)"
    - "WR-04 — fixed in Phase 7 07-05/07 venue-precision resolver seam (set_precision_resolver; PR #81 / af1ddb5a)"
    - "WR-05 — fixed in Phase 7 07-05 on_poll HALT/pause freeze-gate (PR #81 / af1ddb5a)"
    - "WR-06 — fixed in Phase 7 07-05/07 dedicated EventType.UNIVERSE_POLL route + UniversePollEvent (PR #81 / af1ddb5a)"
  open_info:
    - "IN-01, IN-02 — still OPEN at HEAD (info severity, not actioned): IN-01 tautological dead check persists (live_trading_system.py:1378-1379); IN-02 universe_remove_policy still an unvalidated free str (system.py:72)"
---

# Phase 06: Code Review Report

**Reviewed:** 2026-07-06
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

> **RESOLUTION (2026-07-07):** CR-01 + WR-03 fixed in quick task `260706-l48` (commit `e08424d2`);
> the five routed WARNINGs (WR-01/02/04/05/06) were closed by **Phase 7 — Live Dynamic-Universe
> Hardening** (PR #81 / `af1ddb5a`), routed via `06-REVIEW-DECISIONS.md`. WR-01 → keep-until-flat
> instrument lifecycle (`TrackedInstrument` + `_entries` + `discard_instrument`, 07-02). WR-02 →
> async warmup on the connector substrate + per-symbol `isReady` readiness gate + per-symbol
> isolation with `mark_failed` on failure (07-02/03/04/06/08). WR-04 → injected venue-precision
> resolver seam (`set_precision_resolver`, `Universe` stays connector-free, 07-05/07). WR-05 →
> `on_poll` short-circuits while HALTED/submission-paused (07-05). WR-06 → dedicated
> `EventType.UNIVERSE_POLL` route + `UniversePollEvent`, off the shared TIME route (07-05/07).
> CR-01's `unsubscribe` was additionally marshaled onto the connector loop in 07-09. **Two INFO
> items remain OPEN** at HEAD (IN-01 dead check, IN-02 unvalidated remove-policy string) — hence
> `partially_resolved`.

## Summary

This phase adds dynamic universe membership: a lean `UniverseSelectionModel` poll seam,
`Universe.apply`/`UniverseDelta` in-place mutation, a live-only `UniverseHandler`
(poll + add/remove consumers + detach-on-flat), per-symbol OKX candle
subscribe/unsubscribe, a leaving-symbol admission gate, and the live poll-timer +
composition wiring in `LiveTradingSystem`.

The pure/derived seams (`membership.py`, `Universe.apply`, admission gate) are clean,
well-tested, and correctly connector-free. The defects concentrate at the
**stateful lifecycle boundaries** — where the new dynamic subscribe/unsubscribe and
the `apply`-then-consume ordering meet the existing reconnect-supervisor,
margin-read, and halt/pause machinery. Those seams share state (`_streams_down`,
`_reconnect_attempts`, the instrument map, membership) but the new remove/unsubscribe
paths do not fully reconcile it, and several are exercised only through hand-built
events in tests (bypassing the real `apply` → event → consume ordering), so the
coupling defects are not caught by the suite.

The single BLOCKER (CR-01) can permanently wedge the live submission-resume path.

## Critical Issues

### CR-01: `unsubscribe` leaves stale per-symbol supervisor state → live submission can wedge forever

**✅ RESOLVED — quick task 260706-l48 (commit `e08424d2`, 2026-07-06).** `unsubscribe` now clears
`self._streams_down.discard(symbol)` + `self._reconnect_attempts.pop(symbol, None)` after cancelling the
task (`okx_provider.py:341-342`). Verified green (161 passed). Additionally hardened in Phase 7 07-09
(WR-03, PR #81 / `af1ddb5a`): `unsubscribe` is now marshaled onto the connector loop for engine-thread
safety.

**File:** `itrader/price_handler/providers/okx_provider.py:259-272` (with `466-474`, `385-449`)
**Issue:**
`unsubscribe(symbol)` only pops `self._streams` and cancels the task. It does NOT
remove the symbol from `self._streams_down` nor from `self._reconnect_attempts`.

`is_streaming_healthy()` returns `not self._streams_down` (line 474). The engine's
compound resume gate `_all_venue_streams_healthy()`
(`live_trading_system.py:985-1001`) blocks resume of NEW order submission while any
arm reports unhealthy, and `_maybe_resume_after_reconnect` only resumes once that
gate is True.

Sequence: a symbol's candle stream drops past the debounce → `_mark_stream_down`
adds it to `_streams_down` → engine pauses submission. The poll then removes that
symbol from the universe → `_on_symbol_removed` → `unsubscribe(sym)`. The symbol is
gone from `_streams` but **remains in `_streams_down`** forever, so
`is_streaming_healthy()` is permanently `False`, `_all_venue_streams_healthy()` never
returns True, and the engine never resumes NEW submission even after every remaining
stream reconnects. The live engine is silently wedged in a paused state.

Stale `_reconnect_attempts[symbol]` is the same class of bug: a later
`subscribe(sym)` of the same symbol re-spawns a supervisor that reads the leftover
attempt count (`_run_stream_supervisor` line 429 `self._reconnect_attempts.get(stream_name, 0)`),
so a re-subscribed symbol can trip the D-20 retry ceiling prematurely if it does not
immediately stream a post-snapshot payload.

**Fix:**
```python
def unsubscribe(self, symbol: str) -> None:
    task = self._streams.pop(symbol, None)
    # Clear all per-symbol supervisor state so a stale down-flag can never
    # pin is_streaming_healthy() False, and a stale attempt count can never
    # trip the D-20 ceiling on a later re-subscribe.
    self._streams_down.discard(symbol)
    self._reconnect_attempts.pop(symbol, None)
    if task is not None:
        task.cancel()
```

## Warnings

### WR-01: `Universe.apply` drops the Instrument for a removed symbol that is still held (orphan-and-track)

**✓ FIXED** (Phase 7 07-02, PR #81 / `af1ddb5a`) — instrument lifetime decoupled from membership via the keep-until-flat invariant: `Universe` now holds a single `_entries: dict[str, TrackedInstrument]` map; `apply()` shrinks only the membership list and the removed symbol's record survives (`universe.py:208-266`), with teardown deferred to an explicit `discard_instrument` (`universe.py:292-300`) called at detach-on-flat. `instrument()` no longer `KeyError`s a still-held removed symbol. Original finding preserved below.

**File:** `itrader/universe/universe.py:155-156`; consumers `itrader/portfolio_handler/portfolio_handler.py:518`, `itrader/portfolio_handler/portfolio.py:865`
**Issue:**
`apply()` pops `self._instruments.pop(sym, None)` for every removed symbol
*immediately*, before the `UniverseUpdateEvent` is even emitted. Under
orphan-and-track the position is still open and being wound down, but its Instrument
is already gone. The exchange read is guarded (`simulated.py:172-179` try/except
KeyError → falls back to `_min_order_size`), but the margin-path reads at
`portfolio_handler.py:518` (liquidation fill-price quantize) and
`portfolio.py:865` (`universe.instrument(ticker).borrow_rate`) are **unguarded** —
a mark-to-market or carry pass over a still-open orphaned position after removal will
`KeyError`. Spot/paper masks it (those reads are margin/short-only); margin +
dynamic-universe does not. Note the unit tests (`test_universe_poll.py`) build the
`UniverseUpdateEvent` by hand and never exercise the real `apply`→pop→consume
ordering, so this is untested.

**Fix:** Defer instrument removal for a still-held symbol: keep the Instrument until
the position reaches flat (clear it alongside `clear_leaving` in the detach-on-flat
path), or have the margin-path reads fall back to a default Instrument like the
exchange already does.

### WR-02: `on_universe_update` add branch has no rollback / isolation on partial failure

**✓ FIXED** (Phase 7 07-02/03/04/06/08, PR #81 / `af1ddb5a`) — the synchronous batched warmup was replaced by an async warmup on the connector substrate plus a per-symbol `isReady` readiness gate (`Readiness.PENDING/READY/FAILED` on each `TrackedInstrument`): a symbol is marked `PENDING` on add and only `READY` once `spawn_warmup` completes (`BarsLoaded` → absorb → `mark_ready` → subscribe, `universe_handler.py:476-521`); a failed warmup marks it `FAILED` (`on_bars_load_failed`, `universe_handler.py:523-532`) rather than aborting the batch. Per-symbol isolation via try/except (`universe_handler.py:439-441`), so one flaky warmup neither poisons the batch nor blocks the remove branch. Original finding preserved below.

**File:** `itrader/universe/universe_handler.py:213-231`
**Issue:**
`apply()` has already mutated membership (and added instruments) by the time
`on_universe_update` runs. If `self._feed.warmup(sym, ...)` raises for any added
symbol, the loop aborts: that symbol is in membership but never warmed or subscribed,
every *subsequent* added symbol is skipped, and the entire `removed` loop
(`_on_symbol_removed`) never runs. Membership state and stream/warmup state diverge,
and a later `window(sym)` surfaces a `MissingPriceDataError` deep on the live path.
The live error policy (`_publish_and_continue`) will emit an ErrorEvent and keep
draining, so the divergence is not self-correcting.

**Fix:** Wrap each symbol's warmup+subscribe in its own try/except so one symbol's
failure neither aborts the batch nor blocks the remove branch; on a per-symbol
failure, roll that symbol back out of membership (or re-queue it) rather than leaving
a member with no data.

### WR-03: `universe_poll_cadence_s` has no lower bound → 0/negative busy-spins the queue

**✅ RESOLVED — quick task 260706-l48 (commit `e08424d2`, 2026-07-06).** Field now bounded fail-loud:
`universe_poll_cadence_s: float = Field(default=60.0, gt=0.0)`. Verified a `0.0` raises `ValidationError`.

**File:** `itrader/config/system.py:71`; `itrader/trading_system/live_trading_system.py:1789-1793`
**Issue:**
`universe_poll_cadence_s: float = 60.0` is an unvalidated Pydantic float. A
misconfigured `0` (or negative) makes `_run_poll_timer` loop with
`self._stop_event.wait(0)` returning immediately, flooding `global_queue` with
`TimeEvent`s and spinning a CPU core — each of which drives the full TIME route.

**Fix:** Constrain the field, e.g. `Field(default=60.0, gt=0.0)`, and/or clamp to a
sane minimum in `_run_poll_timer` before entering the loop.

### WR-04: Poll-added OKX symbols get default-ladder precision, not venue-correct precision

**✓ FIXED** (Phase 7 07-05/07, PR #81 / `af1ddb5a`) — a venue-precision resolver seam was injected into `UniverseHandler` (`set_precision_resolver`, `universe_handler.py:261-269`): `on_poll` now resolves each newly-added symbol to a venue-precision `Instrument` from the OKX markets map before `apply` (`_resolve_added_instruments`, `universe_handler.py:392-407`) and passes a real instruments map in. `Universe` stays connector-free (D-03/D-16) — it still just receives a dict; paper/replay wire no resolver and fall back to the `_DEFAULT_*` ladder by design. Original finding preserved below.

**File:** `itrader/universe/universe_handler.py:196` (`self._universe.apply(desired, None)`)
**Issue:**
The poll passes `instruments=None` to `apply`, so every dynamically-added symbol
resolves to the `_DEFAULT_*` ladder (2dp price / 8dp quantity) via
`Universe._default_instrument`. For a live OKX symbol whose real precision differs,
subsequent order quantization uses wrong scales — mis-sized/mis-priced orders on the
added symbol. The wiring-time members get venue-correct instruments via
`derive_instruments`, but poll-added members silently do not. The code comments
acknowledge this is deferred, but on the live OKX path it is a real correctness gap
for any operator-driven add.

**Fix:** Resolve precision from the OKX markets map at the composition root and pass a
real `instruments` map into `apply` for added symbols (or have `UniverseHandler`
resolve it through an injected markets-map seam, preserving `Universe`'s
connector-free contract).

### WR-05: Poll `on_time` (and thus remove/unsubscribe) is not gated by HALT/pause

**✓ FIXED** (Phase 7 07-05, PR #81 / `af1ddb5a`) — the poll consumer (`UniverseHandler.on_poll`, `universe_handler.py:301-317`) now short-circuits with an early-return via an injected freeze predicate (`live_trading_system.py:1433` wires `lambda: self._is_halted() or self._is_submission_paused()`), so while the engine is HALTED or submission-paused the whole poll is skipped and membership freezes in place — no delta churn, no stream teardown during a freeze. Original finding preserved below.

**File:** `itrader/trading_system/live_trading_system.py:1058-1083` (gate); `itrader/universe/universe_handler.py:168-209, 235-265`
**Issue:**
`_dispatch_live` gates only `SIGNAL`/`ORDER`. A control-plane `TimeEvent` (`TIME`)
passes straight through even while HALTED or paused, so `UniverseHandler.on_time`
still polls and applies membership deltas during a freeze. Under `force-close`, a
removal during a HALT emits a market-exit `SignalEvent` that the SIGNAL gate then
*suppresses*, yet `_on_symbol_removed` still `mark_leaving` + `unsubscribe`s the
symbol — leaving the position naked *and* blind (no stream), which contradicts the
"freeze in place, no auto-flatten, stay mirrored" halt contract.

**Fix:** Short-circuit `UniverseHandler.on_time` (or gate the TIME route) when the
engine is HALTED or submission-paused, so membership does not churn and streams are
not torn down while frozen.

### WR-06: Control-plane poll `TimeEvent` is indistinguishable from a business tick and drives the whole TIME route

**✓ FIXED** (Phase 7 07-05/07, PR #81 / `af1ddb5a`) — a dedicated control-plane discriminator was added: `EventType.UNIVERSE_POLL` (`core/enums/event.py:32`) + a payload-free `UniversePollEvent` (`events_handler/events/universe.py:82-91`). The poll timer now emits a `UniversePollEvent` (`live_trading_system.py:1880`) onto its own single-consumer route (`full_event_handler.py:108`; wired live-only to `UniverseHandler.on_poll` at `live_trading_system.py:1466`), so the poll cadence no longer touches `screen_markets`/`generate_bar_event` and the queue-only contract stays intact. Original finding preserved below.

**File:** `itrader/trading_system/live_trading_system.py:1790-1792`; routes at `itrader/events_handler/full_event_handler.py:89-92`
**Issue:**
The poll timer emits a plain `TimeEvent(time=datetime.now(UTC))` onto the SAME
`EventType.TIME` route that also fans to `screeners_handler.screen_markets` and
`feed.generate_bar_event`. Today both are dormant on the live path
(`generate_bar_event` returns `None`; `screeners` is empty), so it is inert — but the
poll is coupled to unrelated handlers by event type, and the moment a screener is
registered live, `screen_markets` will run against a wall-clock time and call
`self.feed.megaframe(event.time, ...)` on the `LiveBarFeed`, which is not what the
poll intends. The wall-clock `time` on this event is also the sole non-business-time
`TimeEvent` on the live path.

**Fix:** Route the poll through a dedicated control-plane discriminator (or invoke
`UniverseHandler.on_time` directly from the timer instead of via the shared TIME
route) so the poll cadence never drives the bar/screener handlers.

## Info

### IN-01: Tautological dead check — `mismatched` can never be non-empty

**⚠ OPEN** (unactioned at HEAD, `af1ddb5a`) — the dead check persists, now at `live_trading_system.py:1378-1379`: `subscribed = list(members)` then `mismatched = [s for s in subscribed if s not in members]` is still `[]` by construction, so the `ConfigurationError` branch (`:1380-1389`) remains unreachable. Info severity; not routed to Phase 7. Original finding preserved below.

**File:** `itrader/trading_system/live_trading_system.py:1282-1293`
**Issue:**
`subscribed = list(members)` then `mismatched = [s for s in subscribed if s not in members]`
is always `[]` by construction (subscribed is a copy of members), so the
`ConfigurationError` branch is unreachable. The intended "ring-key vs
window()-ticker" invariant is not actually being asserted — the check tests
`members` against itself.

**Fix:** Assert the real invariant (each subscribed symbol's provider-stamped
`ClosedBar["symbol"]` form equals the member/window ticker form), or remove the dead
branch to avoid a false sense of coverage.

### IN-02: `universe_remove_policy` is an unvalidated free string

**⚠ OPEN** (unactioned at HEAD, `af1ddb5a`) — `universe_remove_policy: str = "orphan-and-track"` is still a plain `str` at `system.py:72` (no `Literal`/enum constraint), so a typo still silently falls through to orphan-and-track. Info severity; not routed to Phase 7. Original finding preserved below.

**File:** `itrader/config/system.py:72`; consumed at `itrader/universe/universe_handler.py:99, 255`
**Issue:**
`universe_remove_policy: str = "orphan-and-track"` accepts any string. Only the exact
literal `"force-close"` selects force-close; any typo (e.g. `"orphan_and_track"`,
`"force_close"`) silently falls through to orphan-and-track with no error. A
misconfigured force-close intent would silently orphan positions instead.

**Fix:** Type the field as an enum (or `Literal["orphan-and-track", "force-close"]`)
so an invalid value fails loudly at config load.

---

_Reviewed: 2026-07-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
