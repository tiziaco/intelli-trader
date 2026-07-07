---
phase: 07-live-dynamic-universe-hardening
plan: 09
reviewed: 2026-07-07T07:32:25Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - itrader/strategy_handler/strategies_handler.py
  - itrader/universe/universe_handler.py
  - itrader/trading_system/live_trading_system.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/price_handler/feed/live_bar_feed.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: issues_found
---

# Phase 7 (plan 07-09): Code Review Report

**Reviewed:** 2026-07-07T07:32:25Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Plan 07-09 is a post-review remediation closing 8 findings (CR-01, WR-01..05, IN-01,
IN-02) from the original Phase 7 review. I reviewed only the 07-09 diff against base
`605ba398`. Most changes are correct and appropriately live-only / backtest-inert:

- **CR-01** (PairStrategy command refusal) — correct: `isinstance` guard placed after the
  `strategy is None` check and before the verb branches, loud no-op, no mutation, no poll.
- **IN-02** (mutation-gated poll emit) — correct: `mutated` flag set only on real
  append/remove, emit guarded.
- **WR-01** (per-leg pair readiness gate) — correct and None-guarded (`self._universe is
  None` short-circuits on the backtest path → byte-exact oracle preserved).
- **WR-04** (per-thread replay guard via `threading.local` property) — correct; the three
  call sites are unchanged and `_replay_local` is initialized in `__init__` before any use.
- **WR-05** (timeframe-honoring `_find_ring`) — the deliberate normalized-timeframe match
  (`_offset_alias(to_timedelta(tf)) == self._base_alias`) is correct: ring keys carry the
  RAW delivered string (e.g. `"1d"`) which is not byte-equal to `self._base_alias` (`"1D"`),
  so the plan's literal `.get((ticker, self._base_alias))` would have always MISSED. The
  deviation reasoning holds — not flagged.
- **IN-01** (force-close log reword) — correct, keeps the `%s` placeholder for the `sym`
  arg (avoids the structlog `PositionalArgumentsFormatter` TypeError).

However, **WR-02's remediation is incomplete and reachable-on-retry**, and **WR-03's
unconditional `spawn()` regresses the documented "safe no-op" contract**. Details below.

## Critical Issues

### CR-01: WR-02 retry re-warm is non-idempotent — a warm-verify MISS can flip a symbol tradeable on CORRUPTED indicator/ring state

**File:** `itrader/universe/universe_handler.py:477-490` (compose with
`itrader/strategy_handler/strategies_handler.py:417-423`)

**Issue:**
WR-02 marks a symbol `FAILED` on an `is_warm` MISS *after* `self._feed.absorb_warmup(...)`
has already run, and the plan explicitly composes this with the CR-02 next-poll
FAILED-retry ("retried next poll"). Neither of the two re-warm paths is idempotent against
re-delivery of an overlapping warmup window:

- `absorb_warmup` (`live_bar_feed.py:321-333`) does an unconditional `ring.append(bar)` with
  **no timestamp dedup** (it is the "controlled single-purpose absorb" that deliberately
  bypasses `_deliver`'s duplicate/stale guard).
- `StrategiesHandler.on_bars_loaded` (`strategies_handler.py:417-423`) calls
  `strategy.update(symbol, bar)` per bar, and `Strategy.update` (`base.py:479-512`) is **not
  timestamp-guarded** — it unconditionally increments `_bar_counts`, appends to
  `_recent_closes`, and pushes into the stateful indicator handles.

Sequence: a symbol reaches the WR-02 MISS branch (the target scenario is a *swallowed*
partial strategy warmup — `strategies_handler.on_bars_loaded` raised and was caught by the
per-handler route isolation, so the strategy is partially/not warm while the ring absorb
succeeded). The symbol is marked FAILED and retried on the next poll. Warmup re-spawns and
re-fetches a largely-overlapping REST window, which is fed AGAIN:

1. `absorb_warmup` re-appends the same bars → duplicate-timestamp bars in the bounded ring →
   `window()` returns a corrupted trailing window.
2. `strategy.update` re-feeds the overlapping bars → `_bar_counts` inflates past `min_period`
   even off duplicates, and the O(1) recurrence state (SMA/MACD etc.) is advanced over
   duplicated values → **garbage indicator state**.
3. On this retry `is_warm` now returns True (count crossed warmup depth) → `mark_ready` +
   `subscribe` → the symbol becomes **tradeable in LIVE with corrupted indicators**.

This is the exact "half-warmed tradeable" defect class WR-02 was meant to eliminate — the
remediation converts it into a *garbage-warmed* tradeable, reached automatically via the
CR-02 auto-retry with no operator intervention, and drives live order decisions off
corrupted state (money-path incorrect behavior). If `update`/`absorb` instead silently
never re-cross warmup depth (in a variant where duplicates don't inflate the count), the
same path degenerates into an unbounded FAILED↔retry churn with no backoff.

**Fix:**
Make re-warm idempotent, or verify warmth BEFORE the destructive absorb + reset on retry.
Two concrete options:

```python
# universe_handler.on_bars_loaded — reset feed+strategy warm state before re-absorbing,
# so a retried warmup is a clean re-warm rather than an append-on-top:
def on_bars_loaded(self, event: BarsLoaded) -> None:
    # If this symbol is being re-warmed (was FAILED / already has a ring), reset the
    # ring and the concerned strategies' per-symbol state first so absorb is idempotent.
    self._feed.reset_symbol(event.symbol, event.timeframe)   # clear ring + L
    self._feed.absorb_warmup(event.symbol, event.timeframe, event.bars)
    if self._warmth is not None and not self._warmth.is_warm(event.symbol):
        self._universe.mark_failed(event.symbol)
        ...
        return
    ...
```
plus a matching per-symbol reset on the strategy side (a `reset_symbol(symbol)` that clears
`_bar_counts[symbol]`, `_recent_closes[symbol]`, and that symbol's handle state) invoked at
the top of `StrategiesHandler.on_bars_loaded` for each concerned strategy.

Alternatively, make `absorb_warmup` and `strategy.update` reject bars with
`bar.time <= last_delivered` (monotonic dedup) so an overlapping re-fetch is a no-op. Either
way, add a retry ceiling / backoff so a permanently-unwarmable symbol cannot churn forever.

## Warnings

### WR-01: WR-03 `unsubscribe` now calls `self._connector.spawn(...)` unconditionally — breaks the "safe no-op if absent" contract and raises before `connect()`

**File:** `itrader/price_handler/providers/okx_provider.py:312-325`

**Issue:**
The pre-07-09 `unsubscribe` for an absent symbol was a pure, side-effect-free no-op (pop
returns `None`, `discard`/`pop` are no-ops, no connector interaction), and its docstring
still promises "a safe no-op if absent." The new code unconditionally executes
`self._connector.spawn(_cleanup())` for every call, including when `task is None`. Two
regressions:

- **Pre-connect crash:** `LiveConnector.spawn` asserts `self._loop is not None`
  (`connectors/okx.py:188`, "connect() must run before spawn()"). If `unsubscribe` is ever
  reached before the connector loop is running (e.g. a universe removal during teardown /
  early lifecycle), it now raises `AssertionError` (or `AttributeError` on `None.call_soon_
  threadsafe` under `-O`) where it was previously a guaranteed safe no-op.
- **Wasteful marshaling:** an absent-symbol unsubscribe now schedules a connector-loop task
  that only performs two no-op set/dict operations, contradicting the "no-op" docstring and
  blocking the engine thread on `spawn`'s `ready.wait(...)` for a call that does nothing.

**Fix:** only marshal when there is real work to do:

```python
task = self._streams.pop(symbol, None)
if task is None and symbol not in self._streams_down and symbol not in self._reconnect_attempts:
    return  # true safe no-op, no connector interaction

async def _cleanup() -> None:
    if task is not None:
        task.cancel()
    self._streams_down.discard(symbol)
    self._reconnect_attempts.pop(symbol, None)

self._connector.spawn(_cleanup())
```
(Reading `_streams_down` / `_reconnect_attempts` membership on the engine thread here is a
GIL-atomic point-read, consistent with the existing `is_streaming_healthy` lock-free read.)

### WR-02: WR-03 leaks a never-awaited coroutine when `spawn()` raises

**File:** `itrader/price_handler/providers/okx_provider.py:314-325`

**Issue:**
`self._connector.spawn(_cleanup())` constructs the `_cleanup()` coroutine object *before*
`spawn` runs. `spawn` can raise before it ever calls `loop.create_task(coro)` — an
`AssertionError` when the loop is unset (`connectors/okx.py:188`) or a `TimeoutError` when
the loop fails to schedule in time (`connectors/okx.py:204-206`). In those cases the
`_cleanup()` coroutine is never awaited, emitting a `RuntimeWarning: coroutine '_cleanup'
was never awaited`. Under the project's `filterwarnings = ["error"]` test policy this
becomes a test-fatal error, and in production it is noise masking the real "loop not
scheduling" failure.

**Fix:** gate the coroutine construction on loop availability (see WR-01's guard, which also
removes the pre-connect path), or wrap the `spawn` in try/except that closes the coroutine
on failure:

```python
coro = _cleanup()
try:
    self._connector.spawn(coro)
except BaseException:
    coro.close()
    raise
```

## Info

### IN-01: `is_warm` vacuous-True lets a symbol not-yet-in-any-strategy pass the WR-02 gate

**File:** `itrader/strategy_handler/strategies_handler.py:120-125`

**Issue:**
`is_warm` returns `all(... for strategy in self.strategies if symbol in strategy.tickers)`,
which is vacuously `True` when no strategy currently lists the symbol in `.tickers`. In that
case the WR-02 re-verify passes and `on_bars_loaded` flips the symbol READY + subscribes it
even though nothing warmed it. This is documented as intended (a symbol no strategy is
concerned with cannot generate signals, and AdmissionManager is the backstop), so it is a
residual limitation rather than a defect — but it does narrow the WR-02 guarantee: it only
protects symbols already present in a concerned strategy's ticker set at absorb time, not a
symbol whose ticker-add races behind the warmup. Worth a one-line note in the `is_warm`
docstring so a future reader does not assume the gate covers the ticker-add race.

**Fix:** none required; optionally document the race window, or have the WR-02 gate treat a
"no concerned strategy" result as a skip-subscribe (leave PENDING) rather than READY.

---

_Reviewed: 2026-07-07T07:32:25Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
