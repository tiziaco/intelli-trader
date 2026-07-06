---
phase: 07-live-dynamic-universe-hardening
reviewed: 2026-07-06T12:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - itrader/core/enums/__init__.py
  - itrader/core/enums/event.py
  - itrader/core/enums/order.py
  - itrader/core/enums/universe.py
  - itrader/events_handler/events/__init__.py
  - itrader/events_handler/events/universe.py
  - itrader/events_handler/full_event_handler.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/membership.py
  - itrader/universe/universe_handler.py
  - itrader/universe/universe.py
findings:
  critical: 2
  warning: 5
  info: 2
  total: 9
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-07-06T12:00:00Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Reviewed the live dynamic-universe hardening surface: the universe read-model
(`universe.py`, `membership.py`), the live-only poll/add/remove consumer
(`universe_handler.py`), the OKX data-plane provider and its reconnect
supervisor (`okx_provider.py`), the live push-driven bar feed
(`live_bar_feed.py`), the strategy-command / warmup consumers
(`strategies_handler.py`), the live composition root
(`live_trading_system.py`), the admission gates that read universe state
(`admission_manager.py`), and the supporting enums/events/dispatcher.

Money-boundary discipline (`to_money`, no `Decimal(float)`), queue-only
cross-domain writes, and the backtest-inertness pattern (explicit-empty
`_routes` entries, `Universe`/`LiveBarFeed` imports lazy/TYPE_CHECKING-guarded
on the backtest hot path) are followed consistently and no violations of those
invariants were found.

Two genuine correctness defects were found that are reachable via normal live
operation (an operator `STRATEGY_COMMAND`, and an ordinary transient warmup
failure), both capable of permanently degrading a running live system with no
automatic recovery. Several further defense-in-depth / concurrency gaps are
flagged as warnings.

## Critical Issues

### CR-01: `STRATEGY_COMMAND` ticker mutation does not enforce `PairStrategy`'s fixed 2-ticker invariant, permanently crashing signal generation every bar

**File:** `itrader/strategy_handler/strategies_handler.py:391-450` (mutation), `itrader/strategy_handler/strategies_handler.py:301-330` (the invariant that later breaks)

**Issue:**
`on_strategy_command` (the live control-plane consumer of `StrategyCommandEvent`,
wired on the `STRATEGY_COMMAND` route in `live_trading_system.py:1458-1459` and
externally reachable via `LiveTradingSystem.add_event` — `STRATEGY_COMMAND` is
one of only two types in `_EXTERNALLY_ADMISSIBLE`) only guards against emptying
a strategy's ticker list:

```python
elif event.verb == "remove_ticker":
    if symbol in strategy.tickers:
        if len(strategy.tickers) == 1:
            # refuse — would empty the ticker set
            ...
            return
        strategy.tickers.remove(symbol)   # line 441
```
and
```python
if event.verb == "add_ticker":
    if symbol not in strategy.tickers:
        strategy.tickers.append(symbol)   # line 429
```

Neither branch checks whether `strategy` is a `PairStrategy`, which has a
**hard, structurally-enforced 2-ticker contract**. `_dispatch_pair` (called
every `calculate_signals`/BAR tick for any `PairStrategy`) raises:

```python
if len(strategy.tickers) != 2:
    raise ValueError(
        f"_dispatch_pair requires a two-ticker pair contract: ..."
    )
```

A single `remove_ticker` command on either leg of a live `PairStrategy`
(`len == 2 → 1`, which passes the "would empty" guard) or a single
`add_ticker` command (`len == 2 → 3`) silently succeeds in
`on_strategy_command`, and the very next `BAR` tick's `calculate_signals` call
raises `ValueError` out of `_dispatch_pair` with **no local try/except**. This
exception:

1. Aborts the **entire** `calculate_signals` call mid-iteration over
   `self.strategies` — every strategy processed *after* the broken pair
   strategy in the list silently gets **no signal generation that bar** (and
   every subsequent bar, forever), because
   `EventHandler._dispatch` only isolates failures *per registered handler*,
   not per strategy inside one handler.
2. Recurs on **every single BAR event** from then on (the mutation is never
   reverted), producing an unbounded stream of `ErrorEvent`s via the live
   `_publish_and_continue` policy — a permanent, self-inflicted error storm
   with no automatic recovery.

There is no way back except another `STRATEGY_COMMAND` that happens to restore
exactly 2 tickers — the system gives no feedback that this is required.

**Fix:**
```python
def on_strategy_command(self, event: StrategyCommandEvent) -> None:
    ...
    strategy = by_name.get(event.strategy_name)
    if strategy is None:
        ...
        return
    if isinstance(strategy, PairStrategy):
        # PairStrategy enforces an exact 2-ticker contract (_dispatch_pair) —
        # any add/remove would break it structurally. Refuse loudly instead of
        # silently corrupting a running pair strategy.
        self.logger.warning(
            'StrategyCommandEvent verb=%s refused for pair strategy %s — '
            'PairStrategy requires exactly 2 tickers and cannot be mutated '
            'via add/remove_ticker', event.verb, event.strategy_name)
        return
    symbol = event.symbol
    ...
```
(`PairStrategy` is already imported in this module for `_dispatch_pair`.)

---

### CR-02: A symbol whose warmup backfill fails once is permanently stuck at `Readiness.FAILED` — the documented "retried next poll" behavior does not exist

**File:** `itrader/universe/universe_handler.py:422-435` (`on_bars_load_failed`), `itrader/universe/universe_handler.py:254-309` (`on_poll`), `itrader/universe/universe.py:183-249` (`Universe.apply`)

**Issue:**
`on_bars_load_failed`'s docstring explicitly claims:

> "the symbol is retried on the next poll (which re-spawns warmup)"

and `mark_failed`'s caller comment repeats "kept in membership, retried next
poll". This is not implemented. `_begin_warmup` (the only call site that
spawns warmup) is invoked exclusively from `on_universe_update`'s **added**
loop (`universe_handler.py:360-370`), which only fires for symbols
`Universe.apply` classifies as newly `added`:

```python
current = set(self._members)
added = tuple(sorted(desired - current))     # universe.py:222
```

A symbol that failed warmup is **never removed from `self._members`** (it
stays a current member with `readiness=FAILED`), so on every subsequent poll
`desired - current` no longer contains it (it is present in both sets) — it
can never again appear in `added`, so `_begin_warmup`/`spawn_warmup` is never
re-invoked for it. The symbol is permanently dark: the readiness gate in both
`StrategiesHandler.calculate_signals` (`is_ready` short-circuit) and
`AdmissionManager._enforce_readiness_admission` will forever reject it, and
nothing in the poll path re-attempts the backfill. Recovery requires an
operator to explicitly `remove_ticker` then `add_ticker` it back (which
happens to work only because the remove path fully `discard_instrument`s the
record once flat) — nothing in the system surfaces this as the required
remediation.

Given transient network conditions are the expected trigger for
`BarsLoadFailed` (per the module's own docs — a REST backfill error), this is
a realistic, not merely theoretical, failure mode that silently and
permanently removes a symbol from live trading.

**Fix:**
Either (a) make `on_poll` re-derive `added` to include current members whose
`Universe` readiness is `FAILED` (requires a `Universe.failed_symbols()`
accessor mirroring `leaving_symbols()`, and re-driving `_begin_warmup` for
them, guarded by a retry backoff/cap to avoid a hot-retry loop on a
permanently-invalid symbol), or (b) explicitly remove the "retried next poll"
claim from the docstrings and add an operator-facing alert/metric so a FAILED
symbol is visibly surfaced instead of silently going dark.

## Warnings

### WR-01: `_dispatch_pair` does not apply the WR-02 per-symbol readiness gate that the single-leg loop enforces

**File:** `itrader/strategy_handler/strategies_handler.py:301-360` (`_dispatch_pair`), compare `itrader/strategy_handler/strategies_handler.py:179-180` (single-leg gate)

**Issue:** The single-leg loop in `calculate_signals` gates each ticker on
`self._universe.is_ready(ticker)` before calling `generate_signal`. `_dispatch_pair`
(the two-leg `PairStrategy` path) has no equivalent check before
`strategy.update_pair(...)` / `evaluate_pair(...)` — a `PairStrategy` will
happily compute a live signal against a leg that is still `PENDING`/`FAILED`
warmup. This is currently backstopped by `AdmissionManager._enforce_readiness_admission`
(the documented "primary" readiness gate), so an unsized signal will still be
rejected before an order reaches the venue — but the strategy-loop "cheap
defensive check" (documented as the secondary layer) simply does not exist for
pair strategies, and the pair strategy still burns cycles evaluating/betting
on an unwarmed leg.

**Fix:** Add the same `self._universe is not None and not self._universe.is_ready(ticker)`
short-circuit for both legs in `_dispatch_pair` before `update_pair`/`evaluate_pair`,
mirroring the single-leg loop.

### WR-02: `BARS_LOADED` per-handler exception isolation lets `Universe.mark_ready` + subscribe proceed even when strategy warmup only partially completed

**File:** `itrader/trading_system/live_trading_system.py:1460-1462` (route wiring), `itrader/events_handler/full_event_handler.py:132-150` (`_dispatch`), `itrader/strategy_handler/strategies_handler.py:362-390` (`on_bars_loaded`), `itrader/universe/universe_handler.py:398-420` (`on_bars_loaded`)

**Issue:** The `BARS_LOADED` route is wired as
`[strategies_handler.on_bars_loaded, universe_handler.on_bars_loaded]` — "list
order = execution order," with the strategy warm-up intentionally running
first. However, `EventHandler._dispatch` wraps **each handler in the list in
its own try/except**, so if `strategies_handler.on_bars_loaded` raises partway
through its per-bar `strategy.update(...)` loop (e.g. a malformed `Bar`, an
indicator arithmetic error), the exception is swallowed by
`_on_handler_error`/`_publish_and_continue` and **`universe_handler.on_bars_loaded`
still runs**, calling `feed.absorb_warmup` → `universe.mark_ready(symbol)` →
`provider.subscribe(symbol)` regardless. The symbol becomes tradeable
(readiness gate open) even though its indicator state may be only partially
warmed. The documented ordering guarantee ("indicators are warm before this
flip") is only true on the happy path; a failure silently breaks the intended
invariant instead of blocking readiness.

**Fix:** Either have `universe_handler.on_bars_loaded` re-verify indicator
warm state before flipping readiness (requires a cross-handler read-model), or
compose the two steps into one route entry (a small coordinating function)
so a strategy-warmup failure prevents the `mark_ready`/`subscribe` step from
running at all.

### WR-03: `_reconnect_attempts` / `_streams_down` are mutated from both the engine thread and the connector-loop thread with no lock

**File:** `itrader/price_handler/providers/okx_provider.py:296-304` (`unsubscribe`, engine thread), `itrader/price_handler/providers/okx_provider.py:461-543` (`_run_stream_supervisor`, `_mark_stream_down`, `_on_stream_healthy`, `_reset_reconnect_budget`, connector-loop thread)

**Issue:** `OkxDataProvider.unsubscribe` (called from the engine thread via
`universe_handler._unsubscribe` → `provider.unsubscribe`) does
`self._streams_down.discard(symbol)` and `self._reconnect_attempts.pop(symbol, None)`
with no synchronization, while the connector-loop thread concurrently mutates
the same two dicts (`_mark_stream_down`, `_reset_reconnect_budget`,
`_reconnect_attempts[stream_name] = attempt`) inside
`_run_stream_supervisor`/`_connect_and_consume_candles`. CPython's GIL makes
each individual dict method call atomic (no corruption), but the *sequence* is
not: an unsubscribe racing a concurrent reconnect-supervisor iteration for the
same symbol can leave `_streams_down`/`_reconnect_attempts` in a state neither
side intended (e.g. a stale "down" mark reappearing right after the clearing
`unsubscribe` ran, or a reconnect attempt counter surviving an unsubscribe
meant to reset it), which can affect `is_streaming_healthy()` /
`_all_venue_streams_healthy()` and thus the resume gate.

**Fix:** Guard the shared dicts with a small `threading.Lock` (all mutation
paths are cheap flag/counter updates, so lock contention is negligible), or
marshal `unsubscribe`'s state cleanup onto the connector loop via
`connector.spawn`/`call_soon_threadsafe` the same way `subscribe` already does
for task creation.

### WR-04: `_replaying_backfill` re-entrancy guard relies on an unenforced single-thread assumption

**File:** `itrader/price_handler/feed/live_bar_feed.py:107-113`, `196-225`

**Issue:** `self._replaying_backfill` is a plain instance `bool` with no lock,
documented (accurately, in the code's own comments) as correct "ONLY while
replay and its nested `update()` calls stay on the single connector-loop
thread." The same docstring notes `update()` is *also* reachable from the
engine thread (`warmup()` / `backfill_on_resume()`), and that this is a
structurally deferred (D-14) gap: a legitimate engine-thread gap arriving
while a connector-loop replay is in flight would be misclassified as a nested
in-replay gap and would spuriously raise `MalformedDataError`, escalating to a
connector halt. This is explicitly flagged as future/deferred work in the
comments, but nothing in the current code prevents the two call paths from
actually overlapping today — it is a live, exploitable ordering hazard, not
just a documented TODO.

**Fix:** At minimum, scope `_replaying_backfill` per calling thread
(`threading.local` or a thread-id check) now, rather than deferring the fix to
"before [concurrent-bar path] is enabled" — the hazard already exists on any
timing where `warmup`/`backfill_on_resume` (engine thread) overlaps a
loop-native gap replay (connector-loop thread) for the same feed instance.

### WR-05: `LiveBarFeed._find_ring` ignores the requested timeframe

**File:** `itrader/price_handler/feed/live_bar_feed.py:652-658`

**Issue:** `_find_ring(ticker)` returns the **first** ring matching `sym ==
ticker` in `self._ring.items()`, ignoring the `(sym, tf)` key's timeframe
component entirely. `_base_frame`/`window`/`megaframe` all rely on this to find
"the ticker's base ring." Today this is safe only because the live system is
wired with exactly one timeframe end-to-end (`_OKX_STREAM_TIMEFRAME = "1d"`,
one `base_timeframe` per feed instance), so at most one `(symbol, tf)` ring can
ever exist per symbol. If a future change ever pushes bars for the same symbol
at two different base timeframes into the same `LiveBarFeed` instance, this
method will silently return whichever ring happens to iterate first —
data-source confusion with no error.

**Fix:** Accept (or derive from `self._base_alias`) the expected timeframe key
and look it up directly: `self._ring.get((ticker, self._base_alias))`, raising
`MissingPriceDataError` on a miss as today.

## Info

### IN-01: Force-close removal logs "detached" before the position is actually flat

**File:** `itrader/universe/universe_handler.py:463-469`

**Issue:** `_on_symbol_removed`'s force-close branch logs `"Force-close
removal: exit emitted + detached %s"` immediately after emitting the exit
`SignalEvent` and calling `_unsubscribe` — but the position is not actually
flat yet (the market-exit order hasn't filled), and the record teardown
(`discard_instrument`) only happens later, in `on_fill`'s detach-on-flat path,
once the fill confirms flat. The log message overstates what has happened at
that point (only "unsubscribed", not "detached/torn down").

**Fix:** Reword to `"Force-close removal: exit order emitted, unsubscribed; detach completes on flat fill"` to avoid implying full teardown already happened.

### IN-02: `on_strategy_command` emits a follow-on poll even for true no-ops

**File:** `itrader/strategy_handler/strategies_handler.py:426-450`

**Issue:** Both `add_ticker` (symbol already present) and `remove_ticker`
(symbol absent) fall through to `self.global_queue.put(UniversePollEvent(...))`
even though nothing was mutated — only the "would empty the ticker list"
refusal path early-returns before the poll emit. Harmless (the poll will find
an empty delta and emit nothing further) but generates avoidable control-plane
churn on every idempotent no-op command.

**Fix:** Track whether the verb branch actually mutated `strategy.tickers` and
only emit `UniversePollEvent` when it did.

---

_Reviewed: 2026-07-06T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
