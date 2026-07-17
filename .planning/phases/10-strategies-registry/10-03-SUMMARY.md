---
phase: 10-strategies-registry
plan: 03
subsystem: price-feed + strategy-handler
tags: [D-07, F-1, D-15, D-16, live-path, oracle-gated]
requires:
  - "itrader/price_handler/feed/cache_registration.py::derive_warmup_depth (the D-17/CF-10 seam)"
  - "itrader/strategy_handler/base.py::is_active (base.py:193, inert before P10)"
provides:
  - "required_base_depth — the shared warmability boundary for D-10 add (Plan 07) and D-15 reconfigure (Plan 08)"
  - "UnwarmableTimeframeError — the loud-reject type for an unservable strategy cadence"
  - "LiveBarFeed.base_timeframe — public read-only accessor"
  - "the wired D-07 is_active gate on calculate_signals (unblocks Plan 06 enable/disable)"
affects:
  - "Plan 06 (enable/disable command — now has a live gate to flip)"
  - "Plan 07 (D-10 runtime add — calls required_base_depth)"
  - "Plan 08 (D-15 reconfigure — calls required_base_depth)"
tech-stack:
  added: []
  patterns:
    - "timedelta // timedelta + timedelta % timedelta for exact whole-multiple checks (no float artifact)"
    - "opt-in keyword arg defaulting to the historical body — keeps every existing caller byte-identical"
key-files:
  created:
    - tests/unit/strategy/test_is_active_gate.py
    - tests/unit/price_handler/test_cache_registration.py
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/price_handler/feed/cache_registration.py
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/trading_system/session_initializer.py
    - tests/unit/strategy/test_strategies_live_membership.py
    - .gitignore
decisions:
  - "D-07 guard placed FIRST in the calculate_signals loop (per plan), which means a disabled strategy's indicator state FREEZES rather than continuing to advance — see Deviations."
  - "session_initializer reads base_timeframe via the in-file cast(\"LiveBarFeed\", ...) precedent, NOT a defensive getattr — a silent fallback to the unscaled path would reintroduce the exact never-warms bug F-1 removes."
metrics:
  duration: ~8 min
  completed: 2026-07-17
status: complete
---

# Phase 10 Plan 03: D-07 is_active gate + F-1 timeframe-aware ring depth Summary

Wired the inert `is_active` flag into the shared `calculate_signals` hot path (D-07) and made the
live feed's warmup ring depth timeframe-aware (F-1), exporting `required_base_depth` as the shared
warmability boundary Plans 07/08 depend on — with the SMA_MACD backtest oracle byte-exact throughout.

## What shipped

**Task 1 — D-07 (`4ba50f27`).** One `if not strategy.is_active: continue` guard at the top of the
`calculate_signals` loop, placed before the `PairStrategy` branch so it covers pairs too (D-16).
14 added lines (criterion: <15). Five behaviors locked in `tests/unit/strategy/test_is_active_gate.py`:
inactive emits nothing, an active sibling is unaffected, a disabled strategy stays in `self.strategies`
and trades the next bar on re-enable with no re-warmup, `is_active` defaults True, and an inactive
`PairStrategy` is skipped.

**Task 2 — F-1 (`0f736504`, `4c0b3326`).** `required_base_depth(warmup, strategy_timeframe,
base_timeframe)` is now the single place the two bar units are reconciled: the ring holds BASE bars
while `strategy.warmup` counts STRATEGY-TIMEFRAME bars. Returns `warmup * multiple`; raises
`UnwarmableTimeframeError` (naming both timeframes) on a finer-than-base or non-multiple cadence
rather than returning a depth that can never be met. `derive_warmup_depth` gained an opt-in
`base_timeframe` kwarg — omitted, the body is byte-identical to the prior `max(s.warmup)`.
`LiveBarFeed.base_timeframe` is now a real read-only property. Nine behaviors locked.

**Task 3 — wiring (`5b2175a2`).** `session_initializer.py:133` threads
`base_timeframe=cast("LiveBarFeed", engine.feed).base_timeframe` through. The load-bearing
`wire_universe` (:119) → `register_strategy_warmup` (:133) order is unchanged.

## Verification

| Gate | Result |
|------|--------|
| **Backtest oracle (MANDATORY, byte-exact 134 / 46189.87730727451)** | **PASS** (3 passed) — re-run after every task |
| OKX inertness gate | PASS (4 passed) |
| `tests/unit/strategy/test_is_active_gate.py` | PASS (5 tests) |
| `tests/unit/price_handler/test_cache_registration.py` | PASS (9 tests) |
| Full suite `tests/unit tests/integration` | PASS (2249 passed, 2 skipped — OKX creds absent) |
| `mypy --strict` (whole package) | PASS (239 files, clean) |
| Indentation (tabs/spaces per file) | PASS — 0 violations in all four edited source files |

All tests run with `PYTHONPATH="$PWD"` to defeat worktree `.venv` shadowing (the editable install
otherwise resolves `itrader` to the main checkout and the oracle gate would false-green).

## Deviations from Plan

### 1. [Rule 1 — Blocking bug] `_SpyStrategy` lacked `is_active`

- **Found during:** Task 1 (full-suite run).
- **Issue:** 4 tests in `tests/unit/strategy/test_strategies_live_membership.py` failed with
  `AttributeError: '_SpyStrategy' object has no attribute 'is_active'`. `_SpyStrategy` is a
  duck-typed double that does NOT subclass `Strategy`, so it never got `is_active` from
  `Strategy.__init__` (base.py:193). Confirmed caused by my change, not pre-existing.
- **Fix:** Added `self.is_active = True` to the stub. Its own docstring commits to carrying "only
  the surface `calculate_signals` reads", so extending that surface means extending the stub.
  Deliberately did **not** add a `getattr(strategy, "is_active", True)` fallback to the hot path —
  that would be defensive cruft masking a real bug, since every real strategy has the flag.
- **Files:** `tests/unit/strategy/test_strategies_live_membership.py` · **Commit:** `4ba50f27`

### 2. [Rule 3 — Blocking issue] The mandated test file was silently gitignored

- **Found during:** Task 2 (commit).
- **Issue:** `.gitignore:32` carries a broad `**cache**` rule that matches any path containing
  "cache" — including the plan-mandated `tests/unit/price_handler/test_cache_registration.py`. The
  first commit (`0f736504`) went through **without** the test file; git only printed a hint. Left
  unfixed, the F-1 gate would not have been regression-locked and the file would have been lost when
  the worktree was removed.
- **Fix:** Added a `!` negation entry, following the repo's existing documented convention for this
  exact collision (there is already a block of them — `cache_registration.py` itself, plus
  `test_position_cache.py` and the `cached_sql_storage` family). Chose this over `git add -f`
  because it is the established in-repo pattern and keeps the exemption visible.
- **Files:** `.gitignore` · **Commit:** `4c0b3326`

### 3. [Judgment call — reported per plan request] `cast` over defensive `getattr` in Task 3

The plan asked me to check whether any feed type other than `LiveBarFeed` can reach the
`register_strategy_warmup` call site, and to report the choice.

**Finding: no.** `SessionInitializer` is live-only, constructed from exactly two places —
`live_trading_system.py:593` (whose feed is built at :1304 as `LiveBarFeed`) and
`tests/support/replay_harness.py` (the paper-replay harness, also `LiveBarFeed`). The static type on
`Engine.feed` is the *widened* base `BarFeed` (compose.py:99, deliberate per D-04/D-01), which has no
`base_timeframe` — so mypy needs help, and `session_initializer.py` is **not** in the mypy
`ignore_errors` list.

**Chose `cast("LiveBarFeed", engine.feed).base_timeframe`**, matching the interim cast the
`UniverseHandler` ctor 15 lines below already uses (`session_initializer.py:151`). Rejected the
`getattr(..., "base_timeframe", None)` fallback: it would silently route an unexpected feed back to
the **unscaled** path — reinstating precisely the silent-permanent-no-warm failure F-1 exists to
eliminate. A wiring-time `AttributeError` is strictly better than a system that looks healthy and
never trades.

## Note for Plan 06 (enable/disable) — indicator freeze semantics

The plan's `<action>` directed the D-07 guard be placed **first** in the loop, and its Test 3 rationale
described the disabled strategy's indicators as continuing to "keep updating". These two are in
tension: placing the guard first means `strategy.update(ticker, bar)` is **not** called while
disabled, so the per-symbol O(1) indicator state **freezes** at its current count rather than
advancing.

I implemented the placement as directed (it is normative, covers pairs cleanly, and satisfies the
plan's `<done>` — warmth is monotone, so a strategy warm before disable is still warm after, and
re-enable trades the next bar with no re-warmup, which Test 3 verifies). This also matches an
established precedent in the very same loop: the P5-D10c/D14 gap skip already documents "a missing bar
this tick means no indicator update — the per-symbol O(1) state stays frozen (count does NOT advance)".

**The consequence worth Plan 06's attention:** an indicator that skipped N bars while disabled holds
values computed over a window with an N-bar hole. On re-enable it fires immediately from that stale
state. That is correct under "disable = freeze" semantics and consistent with how the engine already
treats data gaps, but if Plan 06 intends "disable = keep tracking the market, just don't trade", the
guard must move below `strategy.update` (and the pair branch needs an equivalent). Flagging rather
than deciding — it is a D-07 semantic question, not an implementation detail of this plan.

## Threat Flags

None. No new network, auth, file-access, or trust-boundary surface — the two edits are an in-process
boolean guard and an arithmetic unit reconciliation. `UnwarmableTimeframeError` names only timeframes
(T-10-17, accepted).

## Self-Check: PASSED

- All 6 claimed files verified present on disk.
- All 4 claimed commits verified in `git log`.
- Both new test files verified **tracked** in git (`git ls-files`) — the gitignore trap above.
- Working tree clean; no unintended deletions in any commit (`git diff --diff-filter=D` empty).
