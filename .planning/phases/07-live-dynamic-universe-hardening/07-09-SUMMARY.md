---
phase: 07-live-dynamic-universe-hardening
plan: 09
subsystem: live-trading
tags: [okx, threading, threading-local, pair-strategy, universe, readiness-gate, race-condition, structlog]

# Dependency graph
requires:
  - phase: 07-live-dynamic-universe-hardening
    provides: "live dynamic-universe surface (07-01..07-08): StrategiesHandler live seams, UniverseHandler poll/warmup consumers, LiveBarFeed loop-native backfill, OKX dynamic subscribe/unsubscribe, AdmissionManager readiness backstop, CR-02 FAILED-retry"
provides:
  - "CR-01: PairStrategy ticker-mutation refusal guard in on_strategy_command (forward-compatible with the deferred atomic ordered-pair reconfiguration path)"
  - "IN-02: mutation-gated UniversePollEvent emit (no control-plane churn on idempotent no-ops)"
  - "WR-01: per-leg universe-readiness gate in _dispatch_pair"
  - "WR-02: StrategiesHandler.is_warm producer + UniverseHandler _StrategyWarmthReadModel seam + warm-verify-before-mark_ready gate (MISS -> FAILED, composes with CR-02 retry)"
  - "WR-03: OKX unsubscribe marshals cancel + supervisor-dict cleanup onto the connector loop (single-writer, no new lock)"
  - "WR-04: LiveBarFeed._replaying_backfill per-thread scoped via threading.local (property over the 3 unchanged call sites)"
  - "WR-05: LiveBarFeed._find_ring honors the base timeframe (normalized match), no first-match ambiguity"
  - "IN-01: force-close removal log reworded (no longer implies teardown already completed)"
affects: [live-trading, pair-strategy-live-reconfiguration, okx-provider, universe-warmup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-thread re-entrancy guard: expose a threading.local flag through a same-named property so existing call sites stay unchanged"
    - "Injected warmth read-model Protocol seam (mirrors PortfolioReadModel) — None-default keeps backtest/paper inert"
    - "Cross-thread state mutation marshaled onto the owning event loop via connector.spawn instead of a lock (single-writer discipline)"

key-files:
  created:
    - tests/unit/strategy/test_strategies_handler_remediation.py
    - tests/unit/universe/test_universe_warm_verify_gate.py
    - tests/unit/price/test_live_bar_feed_remediation.py
    - tests/unit/price/test_okx_unsubscribe_marshal.py
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/universe/universe_handler.py
    - itrader/trading_system/live_trading_system.py
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/price_handler/providers/okx_provider.py
    - tests/unit/strategy/test_strategies_live_membership.py
    - tests/unit/price/test_okx_dynamic_subscribe.py

key-decisions:
  - "WR-05: keyed _find_ring lookup uses a normalized-timeframe match (not the plan's literal .get((ticker, self._base_alias))) because the raw delivered ring key ('1d') is not byte-equal to the offset alias ('1D') — the literal would break the live feed"
  - "WR-03: chose marshaling cleanup onto the connector loop over adding a threading.Lock — connector loop becomes the single writer for the supervisor dicts"
  - "CR-01: ship only the forward-compatible refusal guard; the correct atomic ordered-pair reconfiguration remains deferred (todos/pair-strategy-live-reconfiguration.md)"

patterns-established:
  - "Property-over-threading.local: per-thread flag with unchanged call sites"
  - "Warm-verify read-model gate: re-verify aggregate strategy warmth before flipping universe readiness"

requirements-completed: [CR-01, WR-01, WR-02, WR-03, WR-04, WR-05, IN-01, IN-02]

# Metrics
duration: ~55min
completed: 2026-07-07
---

# Phase 7 Plan 09: Live Dynamic-Universe Post-Review Remediation Summary

**Closes the 8 in-scope Phase-7-review findings — eliminating the PairStrategy control-plane crash-storm (CR-01) and the half-warmed-tradeable symbol (WR-02), plus the OKX unsubscribe thread race (WR-03), the replay-guard cross-thread poison (WR-04), the timeframe-ambiguous ring lookup (WR-05), and two info items (IN-01/IN-02) — all live-only and backtest byte-exact.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-07T06:55Z (approx)
- **Completed:** 2026-07-07T07:50Z (approx)
- **Tasks:** 4
- **Files modified:** 7 (5 source + 2 existing tests) + 4 new test files

## Accomplishments
- **CR-01 (critical):** a STRATEGY_COMMAND add/remove_ticker addressed to a PairStrategy is now refused as a loud no-op before the verb branches — no ticker mutation, no follow-on poll — so the exact-2-ticker contract cannot be broken and the next BAR's `_dispatch_pair` never enters an unbounded ErrorEvent storm (proven by a no-raise-next-bar test).
- **WR-02:** a partially-warmed symbol can no longer become tradeable — `UniverseHandler.on_bars_loaded` re-verifies `StrategiesHandler.is_warm(symbol)` before `mark_ready`; a MISS marks the symbol FAILED (skip mark_ready/subscribe), composing with the CR-02 next-poll FAILED-retry.
- **WR-03:** the OKX unsubscribe engine/connector-thread data race on `_streams_down` / `_reconnect_attempts` is removed by marshaling `task.cancel()` + the supervisor-dict cleanup onto the connector loop (single-writer, no new lock).
- **WR-04/WR-05:** the LiveBarFeed replay re-entrancy guard is now per-thread scoped (threading.local via a property; 3 call sites unchanged), and `_find_ring` honors the base timeframe instead of returning the first symbol match.
- **IN-01/IN-02:** the force-close removal log no longer implies teardown already happened; a follow-on UniversePollEvent is emitted only on a genuine ticker mutation.
- Backtest oracle byte-exact throughout (134 / 46189.87730727451, check_exact); mypy --strict clean on all 5 touched modules; 333 unit tests green across strategy/universe/price under filterwarnings=["error"].

## Task Commits

Each task was committed atomically:

1. **Task 1: strategy_handler control-plane + pair-readiness hardening (CR-01, IN-02, WR-01, WR-02 producer)** - `cf05091a` (fix)
2. **Task 2: UniverseHandler warm-verify gate + wiring + force-close log reword (WR-02, IN-01)** - `992dbad3` (fix)
3. **Task 3: LiveBarFeed per-thread replay guard + timeframe-honoring _find_ring (WR-04, WR-05)** - `e0af4da6` (fix)
4. **Task 4: marshal OKX unsubscribe state-cleanup onto the connector loop (WR-03)** - `061cf7cd` (fix)

_Plan metadata (this SUMMARY) committed separately in worktree mode._

## Files Created/Modified
- `itrader/strategy_handler/strategies_handler.py` - CR-01 PairStrategy refusal guard + IN-02 mutation-tracked emit in on_strategy_command; WR-01 per-leg readiness gate in _dispatch_pair; WR-02 `is_warm` warmth producer.
- `itrader/universe/universe_handler.py` - `_StrategyWarmthReadModel` Protocol + `set_strategy_warmth` seam + warm-verify-before-mark_ready gate (MISS -> FAILED) in on_bars_loaded; IN-01 force-close log reword.
- `itrader/trading_system/live_trading_system.py` - live-only `set_strategy_warmth(strategies_handler)` wiring.
- `itrader/price_handler/feed/live_bar_feed.py` - `import threading`; `_replay_local = threading.local()` + `_replaying_backfill` property (WR-04); timeframe-normalized `_find_ring` (WR-05).
- `itrader/price_handler/providers/okx_provider.py` - unsubscribe marshals `_cleanup()` (cancel + discard + pop) onto the connector loop via `connector.spawn` (WR-03).
- `tests/unit/strategy/test_strategies_handler_remediation.py` (new) - CR-01/IN-02/WR-01/is_warm behavioral tests.
- `tests/unit/universe/test_universe_warm_verify_gate.py` (new) - WR-02 MISS/HIT/none-wired + IN-01 log wording.
- `tests/unit/price/test_live_bar_feed_remediation.py` (new) - WR-04 cross-thread + WR-05 timeframe-keyed lookup.
- `tests/unit/price/test_okx_unsubscribe_marshal.py` (new) - WR-03 marshaled cleanup + absent-symbol no-op.
- `tests/unit/strategy/test_strategies_live_membership.py` (modified) - updated two idempotent-no-op tests to the new IN-02 emits-nothing contract.
- `tests/unit/price/test_okx_dynamic_subscribe.py` (modified) - recording connector now drives the awaitless WR-03 cleanup coroutine (stream coros stay closed-unrun).

## Decisions Made
- **WR-05 keyed lookup mechanics** (see Deviations): the plan's literal `self._ring.get((ticker, self._base_alias))` never matches the raw delivered ring key (`"1d"` vs offset alias `"1D"`), so `_find_ring` normalizes each ring's timeframe via `_offset_alias(to_timedelta(tf))` and compares to `_base_alias`. Fully satisfies WR-05's intent (no cross-timeframe first-match ambiguity) while being robust to string-format differences.
- **WR-03** marshals cleanup onto the connector loop rather than introducing a `threading.Lock`, making the connector loop the single writer for the supervisor dicts.
- **CR-01** ships only the forward-compatible refusal guard; the atomic ordered-pair reconfiguration remains deferred to the next milestone.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] WR-05 `_find_ring` keyed lookup did not match the actual ring key**
- **Found during:** Task 3 (LiveBarFeed WR-05)
- **Issue:** The plan specified `ring = self._ring.get((ticker, self._base_alias))`. But rings are keyed by the RAW delivered timeframe string (`"1d"`, from the stream/warmup `ClosedBar`, confirmed `_OKX_STREAM_TIMEFRAME = "1d"` in production), while `self._base_alias = _offset_alias(to_timedelta("1d"))` = `"1D"`. The literal `.get((ticker, "1D"))` therefore NEVER matches a `(ticker, "1d")` ring — it would raise `MissingPriceDataError` on every `window()`/`_base_frame` call, breaking the live feed entirely (and two existing unit tests failed immediately).
- **Fix:** Replaced the direct `.get` with a normalized-timeframe match — iterate `self._ring.items()` and return the ring where `sym == ticker AND _offset_alias(to_timedelta(tf)) == self._base_alias`. This honors the base timeframe (a same-symbol ring at another timeframe is not returned), removes the first-match ambiguity WR-05 targets, and is robust to `"1d"`/`"1D"` format differences; a miss still raises `MissingPriceDataError`.
- **Files modified:** itrader/price_handler/feed/live_bar_feed.py
- **Verification:** All 89 pre-existing price tests + 7 new WR-04/WR-05 tests pass; oracle byte-exact.
- **Committed in:** `e0af4da6` (Task 3 commit)

**2. [Rule 3 - Blocking] Existing OKX subscribe/strategy-membership tests asserted pre-change behavior**
- **Found during:** Task 1 (IN-02) and Task 4 (WR-03)
- **Issue:** (a) `test_strategies_live_membership.py` had two tests asserting an idempotent no-op command STILL emits one UniversePollEvent — the exact behavior IN-02 removes. (b) `test_okx_dynamic_subscribe.py`'s recording connector `close()`s every spawned coroutine without running it, so the WR-03 marshaled `task.cancel()` inside the `_cleanup` coroutine would never execute, and unsubscribe's new `spawn` call would shift the stream-spawn indices.
- **Fix:** (a) Updated the two idempotent-no-op tests to assert ZERO emissions (the new IN-02 contract). (b) Updated the recording connector to DRIVE the awaitless `_cleanup` coroutine to completion (a single `send(None)`) while still closing-unrun the socket-opening `_stream_candles` coros, and to NOT record cleanup spawns into `spawn_args`/`tasks` so the stream-spawn indices the sibling tests assert on stay stable.
- **Files modified:** tests/unit/strategy/test_strategies_live_membership.py, tests/unit/price/test_okx_dynamic_subscribe.py
- **Verification:** Full strategy + price suites green (333 tests) under filterwarnings=["error"].
- **Committed in:** `cf05091a` (Task 1), `061cf7cd` (Task 4)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking test-reconciliation)
**Impact on plan:** The WR-05 fix was essential for correctness — the literal plan instruction would have broken the live feed. The test reconciliations are mechanical consequences of the intended behavior changes (IN-02 no-op-silence and WR-03 marshaling). No scope creep; every change stays live-only and backtest-inert.

## Issues Encountered
- None beyond the WR-05 key-mismatch, resolved as a Rule 1 auto-fix above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 8 in-scope Phase-7-review findings closed with live-only, backtest byte-exact, tested changes; the completion record for Phase 7 is honest.
- CR-02 remains excluded (already fixed in 9cd5dd8d). The correct atomic ordered-pair reconfiguration path stays deferred (`.planning/todos/pair-strategy-live-reconfiguration.md`) — CR-01's refusal guard is forward-compatible with it.
- Live wiring for the WR-02 warmth seam is in place (`LiveTradingSystem.set_strategy_warmth`); an end-to-end online-settlement proof still depends on a flat/non-EEA OKX account (see project memory).

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-07*
