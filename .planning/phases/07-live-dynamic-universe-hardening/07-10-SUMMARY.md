---
phase: 07-live-dynamic-universe-hardening
plan: 10
subsystem: live-trading
tags: [live, warmup, readiness, idempotency, retry, indicators, ring, WR-02, CR-02, CR-01, monotonic-cursor]

# Dependency graph
requires:
  - phase: 07-live-dynamic-universe-hardening (07-03/07-06)
    provides: "LiveBarFeed.absorb_warmup + StrategiesHandler.on_bars_loaded warmup pipeline + UniverseHandler CR-02 FAILED-retry seam"
provides:
  - "CR-01-feed: absorb_warmup idempotent by bar.time via the reused _last_delivered cursor (== silent, < warns)"
  - "CR-01-strategy: Strategy.update per-symbol _last_bar_time monotonic cursor (rejects bar.time <= last before any state mutation)"
  - "CR-01-retry (Level 2): UniverseHandler cadence gate (one re-warm per bar interval) + 3-strike consecutive-failure warn, never auto-drop"
  - "RED-first headline regression proving the garbage-warmed-tradeable path is unreachable after the fix"
affects: [live-trading, universe-membership, warmup, reconnect-resend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Unified monotonic idempotency (Option B): bar.time IS the ts_event key; reject bar.time <= cursor at every re-warm seam (no new timestamp field)"
    - "Drop semantics: == duplicate = silent drop, strict < out-of-order = warning + drop, reject is <="
    - "Level-2 retry hygiene: cadence-gate + warn-after-N, NEVER auto-drop (Level 3 quarantine stays OUT)"

key-files:
  created:
    - tests/unit/universe/test_warmup_retry_idempotency_cr01.py
    - tests/unit/price/test_absorb_warmup_idempotency_cr01.py
    - tests/unit/strategy/test_update_idempotency_cr01.py
    - tests/unit/universe/test_retry_policy_cr01.py
  modified:
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/strategy_handler/base.py
    - itrader/universe/universe_handler.py
    - tests/unit/strategy/test_causal_guard.py

key-decisions:
  - "Feed cursor stays pd.Timestamp (de-pandas migration deferred); strategy cursor is raw stdlib datetime — no conversion"
  - "reset()/_reset_ticker() must clear the strategy cursor so evaluate() window replay still works (load-bearing)"
  - "3-strike streak reset does NOT clear _last_rewarm_at (a later failure passes the cadence gate immediately — correct)"

patterns-established:
  - "Reuse an EXISTING guard cursor instead of adding state: absorb_warmup now honors the _last_delivered cursor _deliver already advances"
  - "Backtest-inertness by construction: monotonic backtest bars never take the reject branch; UniverseHandler is live-only (oracle-dark)"

requirements-completed: [CR-01, CR-01-feed, CR-01-strategy, CR-01-retry]

# Metrics
duration: 11min
completed: 2026-07-07
---

# Phase 7 Plan 10: CR-01 Warmup Re-delivery Idempotency Summary

**Unified monotonic idempotency (Option B, Level 2): warmup re-delivery is now idempotent by `bar.time` at BOTH the feed (`absorb_warmup`) and strategy (`update`) seams, so a CR-02 FAILED-retry re-warm can no longer duplicate the ring, inflate indicators, or flip a symbol tradeable on corrupted state — plus a Level-2 cadence-gate + 3-strike retry policy, proven by a RED-first headline regression.**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-07-07T10:34:48Z
- **Completed:** 2026-07-07T10:45:57Z
- **Tasks:** 4 (+ 1 auto-fixed test collision)
- **Files modified:** 8 (3 production, 5 test)

## Accomplishments

- **CR-01 closed (BLOCKER from 07-09-REVIEW).** The garbage-warmed-tradeable failure mode is unreachable: a short-first-warmup → FAILED → CR-02 retry re-warm can no longer double-count off duplicates.
- **Feed seam (CR-01-feed):** `absorb_warmup` reuses the existing `_last_delivered` cursor — a re-delivered bar whose `pd.Timestamp(bar.time) <= cursor` is dropped BEFORE `ring.append` (== silent, `<` warns). `_deliver` untouched; cursor stays `pd.Timestamp`.
- **Strategy seam (CR-01-strategy):** a new per-symbol `_last_bar_time` cursor rejects `bar.time <= last` before touching `_bar_counts`/`_recent_closes`/the O(1) indicator handles; cleared in `reset()` + `_reset_ticker()` so `evaluate()` replay still works. Also hardens the live per-tick reconnect-resend path.
- **Retry policy (CR-01-retry, Level 2):** `on_poll` cadence-gates FAILED re-warms to one per bar interval; a warning fires after 3 consecutive failed re-warms; the symbol is NEVER auto-dropped.
- **RED→GREEN discipline:** the headline regression FAILED on the pre-fix code (ring len 4/6 with duplicate timestamps, `is_warm` flips True off duplicates) and is GREEN after the three seams landed.
- **Backtest oracle byte-exact throughout** (134 / 46189.87730727451, `check_exact`); `mypy --strict` clean on all three modules; full unit suite 1752 + integration/e2e 228 green under `filterwarnings=["error"]`.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED headline regression (CR-01)** — `e9a10502` (test) — proven RED on the unfixed code
2. **Task 2: Feed `absorb_warmup` `_last_delivered` guard (CR-01-feed)** — `738644f4` (feat)
3. **Task 3: Strategy `_last_bar_time` cursor (CR-01-strategy)** — `794e50ee` (feat)
4. **Deviation: causal-guard test `_Bar` tick auto-increment** — `ee6af412` (test, Rule 1)
5. **Task 4: UniverseHandler Level-2 retry (CR-01-retry) + GREEN headline** — `1647ba99` (feat)

_Task 1 is the standalone RED-first proof; Tasks 2-4 are the GREEN implementations each with dedicated unit coverage._

## Files Created/Modified

- `itrader/price_handler/feed/live_bar_feed.py` — `absorb_warmup` monotonic guard reusing `_last_delivered` (reject `bar.time <= cursor` before `ring.append`).
- `itrader/strategy_handler/base.py` — `_last_bar_time` per-symbol cursor + guard in `update()` before state mutation; cleared in `reset()`/`_reset_ticker()`; module-level bound logger added (base had no `self.logger`).
- `itrader/universe/universe_handler.py` — `_last_rewarm_at` cadence gate in `on_poll`; `_rewarm_fail_streak` 3-strike warn via `_record_rewarm_failure`/`_reset_rewarm_streak` at both failure sites + the mark_ready success.
- `tests/unit/universe/test_warmup_retry_idempotency_cr01.py` — the RED-first headline regression (real LiveBarFeed + real StrategiesHandler.is_warm over a real SMA(3) Strategy).
- `tests/unit/price/test_absorb_warmup_idempotency_cr01.py` — feed idempotency unit coverage (overlap dedup, strict-older warn, dup silent, clean-first unchanged).
- `tests/unit/strategy/test_update_idempotency_cr01.py` — strategy cursor unit coverage (dup silent no-op, strict-older warn, monotonic advance, evaluate double-replay, reset+refeed).
- `tests/unit/universe/test_retry_policy_cr01.py` — Level-2 retry coverage (cadence gate, 3-strike warn, streak reset, never auto-drop).
- `tests/unit/strategy/test_causal_guard.py` — `_Bar` stub auto-increments its tick (deviation; see below).

## Decisions Made

- The feed cursor STAYS `pd.Timestamp` (the ring/`window()` model is pandas-native); the de-pandas migration remains the deferred `livebarfeed-depandas-time-model-datetime` todo, out of scope here.
- The strategy cursor stores the RAW `bar.time` (stdlib datetime) with no conversion; a None-check guards a never-seen ticker (`bar.time <= None` would TypeError).
- The 3-strike streak reset (`_reset_rewarm_streak`) deliberately does NOT clear `_last_rewarm_at` — a later failure then compares against an old poll time and passes the cadence gate immediately, which is correct.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Constant sentinel `time=0` in causal-guard tests broke under the new monotonic strategy cursor**
- **Found during:** Task 4 full-suite verification (after Task 3 landed)
- **Issue:** `tests/unit/strategy/test_causal_guard.py`'s `_Bar` stub defaulted `time=0` (a documented don't-care sentinel). The new `Strategy.update` monotonic guard (Task 3) rejected every bar after the first as a duplicate (`bar.time == last`), so `is_ready` never became True — 2 pre-existing fan-out/readiness tests failed.
- **Fix:** Made `_Bar` auto-assign a strictly-increasing tick (`itertools.count`) when no explicit time is given — faithful to the stub's stated intent (only monotonicity matters, the anchor value is don't-care).
- **Files modified:** `tests/unit/strategy/test_causal_guard.py`
- **Verification:** `poetry run pytest tests/unit/strategy/test_causal_guard.py` 6 passed; full unit suite 1752 passed.
- **Committed in:** `ee6af412` (separate test-fix commit)

---

**Total deviations:** 1 auto-fixed (1 bug directly caused by the Task 3 monotonic guard)
**Impact on plan:** The fix is a test-only adjustment reflecting the new monotonic contract — no production scope creep. All plan gates (oracle byte-exact, mypy strict, indentation) held.

## Issues Encountered

- The base `Strategy` had no per-instance `self.logger`; the CR-01-strategy out-of-order warning needed a logger, so a module-level `logger = get_itrader_logger().bind(component="Strategy")` was added (mirroring `SMA_MACD_strategy.py`). Resolved within Task 3.

## Threat Flags

None — no new security surface introduced (timestamp guards + retry hygiene only; no network endpoints, auth paths, or schema changes).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CR-01 is closed; Phase 07's last outstanding BLOCKER is resolved. The `warmup-retry-nonidempotent-tradeable-corrupted-cr01.md` todo can be moved to completed.
- Explicitly still deferred (unchanged): the LiveBarFeed de-pandas time-model migration; OKX markets-map freshness / delisting detection; Level-3 hard-ceiling / quarantine-drop.

## Self-Check: PASSED

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-07*
