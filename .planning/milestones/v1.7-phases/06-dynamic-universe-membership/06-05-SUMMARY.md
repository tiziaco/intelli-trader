---
phase: 06-dynamic-universe-membership
plan: 05
subsystem: trading-system
tags: [universe, live-wiring, composition-root, poll-timer, membership-driven-subscribe, milestone-gate, okx]

# Dependency graph
requires:
  - phase: 06-01
    provides: "UniverseUpdateEvent + EventType.UNIVERSE_UPDATE + explicit-empty _routes entry + Universe.apply/leaving-set"
  - phase: 06-02
    provides: "OkxDataProvider.subscribe/unsubscribe dynamic per-symbol seam + warmup-before-subscribe contract"
  - phase: 06-03
    provides: "UniverseHandler on_time poll + on_universe_update ADD branch + StaticUniverseSelectionModel"
  - phase: 06-04
    provides: "UniverseHandler remove-policy consumer + on_fill detach-on-flat + leaving-symbol admission gate"
provides:
  - "Membership-driven live subscribe: start() sources the subscription set from universe.members (warmup-BEFORE-subscribe per member), replacing the single hardcoded _OKX_STREAM_SYMBOL start_stream()"
  - "Generalized wiring-time ring-key assertion (every subscribed symbol is a member — ring-key vs window() ticker guard), ConfigurationError shape preserved"
  - "Live-only UniverseHandler construction + seam wiring (selection source seeded from membership, D-06 validate_symbol on OKX arm, provider, portfolio read model)"
  - "LIVE-ONLY _routes mutation on the live EventHandler's own dict (append on_time to TIME, set UNIVERSE_UPDATE, append on_fill to FILL) — backtest _routes literal UNTOUCHED"
  - "Live-only poll-timer daemon (configurable cadence, default 60s) putting a control-plane TimeEvent, started only on the daemon path, joined via _stop_event"
  - "universe_poll_cadence_s + universe_remove_policy on MonitoringSettings (NOT PerformanceSettings)"
  - "Gated live-demo e2e (tests/e2e/test_okx_dynamic_universe.py) — dynamic DATA subscribe/unsubscribe, human-observed on OKX demo"
affects: [phase-06-complete, live-trading, dynamic-universe]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Membership-driven subscription set: iterate universe.members, warmup-before-subscribe per member (Pitfall 6); a one-symbol universe subscribes exactly that symbol so the wiring default falls out naturally"
    - "LIVE-ONLY route mutation on the live instance's own event_handler.routes dict — the backtest TradingSystem builds a SEPARATE EventHandler so the _routes literal is provably unaffected (RESEARCH §11.1)"
    - "Control-plane wall-clock TimeEvent: datetime.now(UTC) stamps ONLY the poll cadence event, NEVER a bar/fill business time (Pitfall 3 / determinism)"
    - "Oracle-critical config isolation: live poll cadence + remove policy live on MonitoringSettings, never PerformanceSettings (§8/D-01)"

key-files:
  created:
    - tests/e2e/test_okx_dynamic_universe.py
  modified:
    - itrader/config/system.py
    - itrader/trading_system/live_trading_system.py
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "Tasks 1 and 2 both edit one contiguous region of the composition-root file (live_trading_system.py), so their live-wiring edits are committed together (351d0381); Task 1's cleanly-separable config half is a distinct commit (008766e0)"
  - "Generalized assertion asserts the subscription set (= universe.members) contains only members (ring-key vs window() ticker invariant), preserving the ConfigurationError shape; generalized away from the single _OKX_STREAM_SYMBOL hardcode"
  - "The gated e2e isolates the ETH/USDC dynamic seam on a dedicated provider (the plan-02 provider stamps a single self._symbol into every ClosedBar, so co-streaming BTC on one provider would pollute the stop-observation); 1m timeframe so a closed bar lands within a bounded human window"
  - "Poll timer + UniverseHandler constructed unconditionally on the live daemon path (all venues) — the selection source is seeded from current membership so the poll is a no-op until an operator drives set_symbols (lean poll seam, D-20)"

patterns-established:
  - "Un-hardcode via membership: the single wiring-time default is now the N=1 case of the membership loop"
  - "Live-only wiring lands in _initialize_live_session / start() with LAZY imports so the backtest import path never pulls universe_handler (inertness gate extended)"

requirements-completed: [UNIV-01]

# Metrics
duration: 35min
completed: 2026-07-06
---

# Phase 6 Plan 05: Live Composition Wiring + Milestone Gate Summary

**Un-hardcode `_OKX_STREAM_SYMBOL` (membership-driven warmup-before-subscribe per member), construct the live-only `UniverseHandler` + a configurable poll-timer daemon + a LIVE-ONLY `_routes` mutation that leaves the backtest literal untouched, and put the poll cadence + remove policy on `MonitoringSettings` — closing the phase against the recurring milestone gate (oracle byte-exact, determinism identical, no W1/W2 regression, inertness green) and a human-observed live-demo dynamic DATA subscribe/unsubscribe.**

## Performance

- **Duration:** ~35 min (incl. the blocking human live-observed checkpoint)
- **Completed:** 2026-07-06
- **Tasks:** 3 (2 auto + 1 checkpoint:human-verify)
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- **Task 1 — config fields + un-hardcode subscribe + generalized assertion:** added `universe_poll_cadence_s` (default 60.0) and `universe_remove_policy` (default `orphan-and-track`) to `MonitoringSettings` (NOT `PerformanceSettings` — oracle-critical `rng_seed` surface untouched, §8/D-01/D-02). Replaced the single `feed.warmup(_OKX_STREAM_SYMBOL) + start_stream()` block in `start()` with a membership-driven loop: `for sym in self.universe.members: feed.warmup(sym, tf); provider.subscribe(sym)` (warmup-BEFORE-subscribe per member, Pitfall 6). Generalized the wiring-time assertion from `_OKX_STREAM_SYMBOL not in universe.members` to a ring-key vs `window()` ticker guard asserting every subscribed symbol (= every member) is a member, preserving the `ConfigurationError` failure shape.
- **Task 2 — live UniverseHandler + poll timer + route mutation + milestone gate:** constructed `self._universe_handler = UniverseHandler(...)` in `_initialize_live_session` (LAZY import, live-only) with `remove_policy` from `config.monitoring.universe_remove_policy`; wired the seams (`set_selection_source(StaticUniverseSelectionModel(universe.members))` — seeded from current membership so the poll is a no-op until an operator drives `set_symbols`; `set_symbol_validator(self._okx_exchange)` on the OKX arm; `set_provider(self._okx_data_provider)`; `set_portfolio_read_model(self.portfolio_handler)`). Added the LIVE-ONLY `_routes` mutation on the live instance's own `event_handler.routes` dict (append `on_time` to TIME, set `UNIVERSE_UPDATE = [on_universe_update]`, append `on_fill` to FILL AFTER `PortfolioHandler.on_fill`) — the backtest `_routes` literal is untouched. Added the `_run_poll_timer` daemon (control-plane `TimeEvent(time=datetime.now(UTC))` on `universe_poll_cadence_s`, started only on the live daemon path in `start()`, joined via `_stop_event` in `stop()`; NOT started in `run_paper_replay` or backtest). Extended the inertness gate `_FORBIDDEN` with `itrader.universe.universe_handler`.
- **Task 3 (checkpoint:human-verify) — gated live-demo dynamic DATA subscribe/unsubscribe:** wrote `tests/e2e/test_okx_dynamic_universe.py` (`pytest.mark.live` + `slow` + creds-skipif), asserting `sandbox is True` before any subscribe, then dynamically subscribing ETH/USDC, observing closed (`confirm=='1'`) bars arrive, unsubscribing, and observing the stream stop — DATA-ONLY (touches no order/settlement path). Verified CI-fenced (`-m "not live"` → 1 deselected / 0 selected). **Human live-observed run PASSED** (see Verification).

## Task Commits

1. **Task 1 (config half):** `008766e0` (feat — `MonitoringSettings` poll cadence + remove policy)
2. **Tasks 1-2 (composition-root wiring, interleaved in one file region):** `351d0381` (feat — membership-driven subscribe + generalized assertion + UniverseHandler construction + seams + LIVE-ONLY route mutation + poll-timer daemon + inertness gate extension)
3. **Task 3 (gated e2e test):** `119b5e18` (test — live-demo dynamic DATA subscribe/unsubscribe)

_Task 1 and Task 2 both edit a single contiguous region of `live_trading_system.py` (the assertion sits adjacent to the handler construction), so their live-wiring edits could not be whole-hunk split by task and are committed together in `351d0381`; the cleanly-separable config-field half is `008766e0`._

## Files Created/Modified

- `itrader/config/system.py` — two live/control-plane fields on `MonitoringSettings` (`universe_poll_cadence_s`, `universe_remove_policy`), documented as never read on the backtest hot path.
- `itrader/trading_system/live_trading_system.py` — un-hardcoded membership-driven subscribe; generalized ring-key assertion; live-only `UniverseHandler` construction + seam wiring + LIVE-ONLY `_routes` mutation; `_run_poll_timer` daemon + `start()` spawn + `stop()` join; forward-attribute decls (`_universe_handler`, `_poll_timer_thread`); `TimeEvent` import.
- `tests/integration/test_okx_inertness.py` — `_FORBIDDEN` extended with `itrader.universe.universe_handler`.
- `tests/e2e/test_okx_dynamic_universe.py` — NEW. Gated live-demo dynamic DATA subscribe/unsubscribe e2e (sandbox-asserted, data-only, CI-fenced).

## Decisions Made

- **Config-half / wiring-half commit split:** Task 1 and Task 2 both modify a single contiguous region of the composition-root file, so whole-hunk staging cannot separate them; the config fields (cleanly separable) are their own commit and the entangled live wiring is committed together. Documented in the commit messages + here.
- **Generalized assertion form:** the subscription set is sourced 1:1 from `universe.members`, so the guard asserts every subscribed symbol is a member (the ring-key vs `window()` ticker invariant, RESEARCH §1 step 3), generalizing away from the single hardcoded symbol while preserving the `ConfigurationError` shape. It fails loudly at wiring if a future edit subscribes a non-member.
- **e2e isolation choice:** `OkxDataProvider` stamps a single `self._symbol` into every `ClosedBar['symbol']` (plan-02 shape), so the gated e2e drives a provider dedicated to ETH/USDC (clean stop-observation) rather than co-streaming BTC on one provider (which would stamp BTC bars as ETH). 1m timeframe so a closed bar lands within a bounded human window (~2.5 min).
- **Unconditional live construction:** the `UniverseHandler` + poll timer are constructed on the live daemon path for all venues; the selection source is seeded from current membership so the poll is a no-op (empty delta → no event) until an operator drives `set_symbols` — the lean poll seam (D-20), harmless on non-OKX/paper.

## Deviations from Plan

None — plan executed as written. The commit-boundary split (config half vs interleaved live-wiring half) is a mechanical consequence of Task 1 and Task 2 editing one contiguous file region, not a scope deviation; the end state matches the plan's Task 1 + Task 2 deliverables exactly.

## Milestone Gate Evidence

- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` 3 passed (134 / `46189.87730727451`, `check_exact=True`).
- **Determinism double-run:** `tests/e2e/robust/test_determinism.py` 9 passed (identical trades + equity).
- **Inertness (oracle-dark by construction):** `tests/integration/test_okx_inertness.py` 1 passed — the backtest import root pulls no `universe_handler`/poll-timer/ccxt/aiohttp; single-symbol SMA_MACD yields an empty delta so the subsystem never fires on the golden path.
- **Backtest `_routes` literal untouched:** `git diff --stat itrader/events_handler/full_event_handler.py` empty — the live route mutation is on the live EventHandler's own dict only.
- **No W1/W2 regression:** `make perf-w1 --check` → wall_clock **14.5s (Δ −7.4%** vs 15.7s baseline), peak_mem **144.4MB (Δ −5.5%** vs 152.8MB); regression guard passed.
- **Paper-parity:** `tests/integration/test_paper_parity.py` 1 passed.

## Verification

- `poetry run pytest tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py tests/integration/test_paper_parity.py` → **5 passed**
- `poetry run pytest tests/unit/universe tests/integration/test_universe_remove_policy.py tests/integration/test_universe_force_close.py` → **56 passed**
- `poetry run pytest tests/integration/test_live_paper_lifecycle.py tests/integration/test_live_system_okx_wiring.py tests/integration/test_live_portfolio_durable_wiring.py tests/unit/trading_system` → **21 passed**
- `poetry run mypy --strict itrader/config/system.py` → **Success: no issues found**
- CI-fence: `poetry run pytest -m "not live" tests/e2e/test_okx_dynamic_universe.py` → **1 deselected / 0 selected**
- **Human live-observed (checkpoint cleared):** `poetry run pytest tests/e2e/test_okx_dynamic_universe.py -x -q -m live` → **1 passed in 127.85s** (.env creds, OKX_REGION=eea; internal `sandbox is True` guard held before subscribe; dynamic ETH/USDC data subscribe → closed-bar → unsubscribe → stream-stop verified live on the OKX demo).

## Known Stubs

None. The membership-driven subscribe, live UniverseHandler wiring, poll timer, and route mutation are all fully wired. The provider's single-`self._symbol` ClosedBar stamp (plan-02 shape) is a pre-existing data-plane limitation documented as the reason the gated e2e isolates ETH/USDC on a dedicated provider — not a stub introduced by this plan; per-symbol ClosedBar stamping for N>1 co-streamed symbols on one provider is a deferred data-plane refinement (out of this phase's N=1-2 scope).

## Next Phase Readiness

- Phase 06 (dynamic-universe-membership) is COMPLETE (5/5 plans). UNIV-01 (mid-run add/remove, poll/consumer/wiring chain) and UNIV-02 (dynamic subscribe/unsubscribe + remove policy) are both satisfied and live-verified.
- The live trading pair is now membership-driven (the operator-next-step "make the live pair configurable" item is addressed: the subscription set derives from `universe.members`, no longer the hardcoded `_OKX_STREAM_SYMBOL`).
- No blockers.

## Self-Check: PASSED

All created files present on disk; all three task commits (`008766e0`, `351d0381`, `119b5e18`) present in git history.

---
*Phase: 06-dynamic-universe-membership*
*Completed: 2026-07-06*
