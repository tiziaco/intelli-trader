---
phase: 05-incremental-indicators-fragile-oracle-gated-last
plan: 03
subsystem: strategy
tags: [per-tick-window-removal, update-isready-generate, pair-fit-once-frozen, z-bounded-window, fixture-migration, perf-05, byte-exact]

# Dependency graph
requires:
  - phase: 05-incremental-indicators-fragile-oracle-gated-last
    provides: "Plan A — BarFeed shared recent-bars seam (newest-bar provision), byte-exact plumbing"
  - phase: 05-incremental-indicators-fragile-oracle-gated-last
    provides: "Plan B — four O(1) stateful recurrences + update(ticker,bar)/is_ready(ticker)/reset() per-symbol fan-out surfaces"
provides:
  - "Restructured per-tick handler loop: update(ticker,bar) -> is_ready(ticker) gate -> generate_signal(ticker); feed.window() slice + len-gate removed ENTIRELY (single-leg + pair, P5-D13/D14)"
  - "Per-symbol fan-out via state-swap on the registration handles (P5-D10/D14) — self.short_sma reflects the active ticker without re-binding (author surface untouched, P5-D21)"
  - "Pair on β fit-once-frozen (oldest 250) + z bounded-window (30) + multi-input update_pair(bar_A,bar_B) + is_pair_ready (280); _buffers_as_windows renders the bounded buffers as the (win_A,win_B) the preserved β/z math reads (P5-D15/D09)"
  - "Count/date fixtures + multi-bar strategies migrated off self.bars onto bar_count/latest_bar/recent_closes (P5-D13a) — firing PRESERVED, golden guards green"
  - "SMA_MACD oracle stays BYTE-EXACT against the Plan-02 re-baselined reference (134 / 46189.87730727451); determinism byte-identical (P5-D18)"
affects: [stateful-indicators, perf-05-complete]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-tick update -> is_ready -> generate (Nautilus/LEAN handler idiom): per-INDICATOR readiness replaces window-width len-gate; the bar-is-None gap skip = no-update (state frozen, P5-D10c)"
    - "Per-symbol fan-out via STATE-SWAP on one registration handle-set: stash each ticker's (state,buffer) and swap it into self._handles before dispatch — the author-bound attrs (self.short_sma) always read the active ticker WITHOUT the base knowing their names (P5-D21)"
    - "Pair fit-once-frozen β over the oldest beta_warmup of a bounded buffer; z bounded-window over the last z_lookback; the buffer IS the trailing window the preserved window-based β/z helpers read (byte-identical to the removed feed.window(280))"
    - "recent_closes(ticker) read seam: a small per-ticker bounded close buffer for the indicator-free strategies that need a prior-bar compare / short rolling window after the master-frame slice is gone"

key-files:
  created:
    - .planning/phases/05-incremental-indicators-fragile-oracle-gated-last/05-03-SUMMARY.md
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/pair_base.py
    - itrader/strategy_handler/indicators/handle.py
    - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
    - itrader/strategy_handler/strategies/eth_btc_pair_strategy.py
    - tests/unit/strategy/test_pair_dispatch.py
    - tests/unit/strategy/test_causal_guard.py
    - tests/e2e/strategies/single_market_buy.py
    - tests/e2e/strategies/scripted_emitter.py
    - scripts/crossval/limit_entry_strategy.py
    - perf/strategies/a_bracketed_momentum.py
    - perf/strategies/b_limit_maker.py
    - perf/strategies/c_pyramiding_trend.py
    - perf/strategies/d_short_zscore.py
    - perf/runners/run_w2_sweep.py

key-decisions:
  - "self.now = bar.time (the dispatched bar's tz-aware Timestamp), NOT the literal event.time the plan body wrote: ~12 e2e scenario strategies call self.now.tz_convert('UTC'), and event.time is a plain datetime (no .tz_convert) while bar.time IS a pandas Timestamp byte-identical to the legacy window.index[-1]. Using event.time would have broken every tz_convert scenario; bar.time preserves the anchor contract AND the value."
  - "Per-symbol fan-out is implemented as a STATE-SWAP on the single registration handle-set, not separate per-ticker handle OBJECTS. The author binds self.short_sma to the registration handle (Plan B), and the base does not know that attr name (P5-D21) — so re-binding per ticker is impossible. Instead each ticker's (state,buffer) is stashed and swapped into the registration handles before update/generate. (Plan B's separate-handle-set design left self.short_sma pointing at an un-updated handle, which crashed read-before-warm — fixed here.)"
  - "The pair migration keeps the window-based β/z helpers (_fit_beta/_zscore/evaluate_pair) UNCHANGED and feeds them from bounded per-leg buffers via _buffers_as_windows(). A maxlen=(beta_warmup+z_lookback)=280 deque IS the trailing window feed.window(280) produced — byte-identical for the one-time β fit (oldest 250) and the z tail (last 30). β stays fit-once-frozen so the deque slide never re-reads dataset-start."
  - "recent_closes(ticker) seam added for the indicator-free multi-bar strategies (perf c/d/run_w2_sweep) that read self.bars['close'].iloc[-2] / a rolling window — depth max(max_window,2). Rule-3 scope expansion: these strategies broke once the slice was removed; migrating them was required for the full-suite phase gate, not optional."

patterns-established:
  - "Decoupled evaluate(): kept ONLY as a legacy window-driven test/back-compat seam (off the run path) — it replays the frame through update() (no master-frame stash, no window-replay handle rebuild). The run path is pure per-tick update->is_ready->generate."
  - "Fixture migration mechanism-only: len(self.bars) -> bar_count(ticker); self.bars.index[-1] -> latest_bar(ticker).time; self.bars['close'].iloc[-1] -> latest_bar(ticker).close — WHEN they fire is unchanged (P5-D13a), only the read source."

requirements-completed: [PERF-05]

# Metrics
duration: ~40min
completed: 2026-06-24
---

# Phase 5 Plan 03: Cut the Per-Tick Window Slice + Pair Migration (Plan C) Summary

**The per-tick `feed.window()` master-frame slice (the residual ~13% W2) is removed ENTIRELY for both the single-leg and pair paths — readiness is now per-indicator state (`is_ready`), not window width. The handler loop is `update(ticker,bar)` → `is_ready` gate → `generate_signal`; the pair runs on β fit-once-frozen (oldest 250) + z bounded-window (30) fed by a multi-input `update_pair(bar_A,bar_B)`. Plan C is byte-exact against the Plan-02 re-baselined reference — it removes the slice, it does not change values — so the SMA_MACD oracle stays GREEN (134 / 46189.87730727451) and the pair flagship snapshot matches byte-for-byte.**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-06-24
- **Tasks:** 3 (Task 1 single-leg loop + evaluate decouple, Task 2 pair migration, Task 3 fixture migration + phase gate)
- **Files modified:** 16 (1 created — this SUMMARY)

## Accomplishments

### Task 1 — Single-leg loop restructured + evaluate seam decoupled (`37f6a4e`)

- **`strategies_handler.py` single-leg loop (P5-D14):** the `data = self.feed.window(...)` slice and the `if len(data) < strategy.warmup: continue` gate are GONE. The per-tick path is now `strategy.update(ticker, bar)` → `if not strategy.is_ready(ticker): continue` → `strategy.generate_signal(ticker)`. The `bar = event.bars.get(ticker); if bar is None: continue` gap skip is KEPT — it now ALSO means "no indicator update this tick" (P5-D10c, state frozen). The `_emit_intent` + MARKET `to_money(bar.close)` price-stamp fan-out is byte-identical (untouched).
- **`base.py` per-symbol fan-out via state-swap (P5-D10/D14):** the registration handles (the author-bound `self.short_sma` etc.) are driven directly; each ticker's `(state, buffer)` is stashed in `_handle_state_store` and swapped into the registration handles before that ticker's `update`/`generate` (`_activate_ticker`). `IndicatorHandle` gained `snapshot_state`/`load_state`/`fresh_state`. This fixes the Plan-B design defect where separate per-ticker handle OBJECTS left `self.short_sma` pointing at an un-updated handle (see Deviations).
- **`base.py` per-ticker bookkeeping (P5-D13a):** `update(ticker,bar)` increments `_bar_counts[ticker]`, stashes `_latest_bar[ticker]`, sets `self.now = bar.time` (a tz-aware Timestamp) and `self.current_bar`. New read seams `bar_count(ticker)` / `latest_bar(ticker)` for the count/date fixtures.
- **`evaluate()` decoupled to a LEGACY test seam:** off the run path; it replays the frame through `update()` (value-identical to the old `repopulate`) — no master-frame stash, no window-replay handle rebuild.

### Task 2 — Pair onto β fit-once-frozen / z bounded-window + dispatch restructure (`44222bb`)

- **`pair_base.py` multi-input update (P5-D09/D15):** `update_pair(bar_A, bar_B)` pushes BOTH legs' closes into bounded `maxlen=(beta_warmup+z_lookback)=280` per-leg deques and stamps `self.now` from leg A. `is_pair_ready()` gates on the buffer fill (β fittable + z tail), folding the removed window-length short-circuit. `_buffers_as_windows()` renders the buffers as the `(win_A, win_B)` the PRESERVED window-based β/z math reads. `_run_init` re-inits the buffers (idempotent reconfigure).
- **`strategies_handler._dispatch_pair`:** the two `feed.window()` calls + the `beta_warmup + z_lookback` len-gate are REMOVED → `update_pair` → `is_pair_ready` gate → `evaluate_pair(_buffers_as_windows())`. The both-legs-present D-02 guard + per-leg `_emit_intent` fan-out are byte-identical.
- **`eth_btc_pair_strategy.py` UNTOUCHED (math):** β stays fit-once-frozen (`if self._beta is None`) over the oldest 250 of the buffer; the `_crosses_into`/`_crosses_inside` band logic, the `_in_pair` flag, the non-finite-z guard, and the β→Decimal fence (`to_money` only at `qty_B`, β stays float64) are all preserved.
- **Byte-exact proof:** `test_pair_flagship_snapshot` matches the committed `tests/golden/pair/{trades,equity}.csv` byte-for-byte AND the determinism double-run passes — the buffer-as-window migration is numerically identical to the removed `feed.window(280)`.

### Task 3 — Fixture + multi-bar strategy migration + phase gate (`094a345`)

- **Count/date fixtures (P5-D13a, firing PRESERVED):** `SingleMarketBuy` `len(self.bars) == fire_on_bar` → `self.bar_count(ticker) == fire_on_bar`; `ScriptedEmitter` `self.bars.empty/index[-1]/['close'].iloc[-1]` → `self.latest_bar(ticker)` `is None`/`.time`/`.close`. `BuyEachTickerOnce` never read `self.bars` (signature-only).
- **`recent_closes(ticker)` seam added** (a small per-ticker bounded close buffer, depth `max(max_window,2)`) for the indicator-free strategies that need a prior-bar compare / short rolling window once the slice is gone.
- **Rule-3 migrations** (broke once the slice was removed — required for the full-suite gate): `scripts/crossval/limit_entry_strategy` (→ `latest_bar`), `perf/strategies/a,b` (→ `latest_bar.close`), `perf/strategies/c` + `perf/runners/run_w2_sweep` (→ `recent_closes` `[-1]`/`[-2]`), `perf/strategies/d` (z over `recent_closes`).
- **PHASE GATE (correctness, gate (a)) GREEN:** full suite `poetry run pytest tests` **1287 passed**; oracle `test_oracle_behavioral_identity` + `test_oracle_numeric_values` byte-exact (134 / 46189.87730727451); `mypy --strict` clean (188 files); determinism **double-run BYTE-IDENTICAL** (SHA-256 of `trades.csv`/`equity.csv`/`summary.json` match across two `run_backtest.py` runs).

## Decisions Made

- **`self.now = bar.time`, not the literal `event.time`** — see the frontmatter key-decision: `event.time` is a plain `datetime` (no `.tz_convert`); `bar.time` is a tz-aware pandas Timestamp byte-identical to the legacy `window.index[-1]`, which ~12 e2e scenario strategies call `.tz_convert("UTC")` on. Using `event.time` would have broken every such scenario.
- **Per-symbol fan-out = state-swap on the registration handle-set** (not separate handle objects) — required because the author binds `self.short_sma` to the registration handle and the base does not know that attr name (P5-D21).
- **Pair buffer-as-window** keeps the β/z helpers unchanged and is byte-identical to `feed.window(280)` (β fit-once over the oldest 250, z over the last 30).
- **`recent_closes` seam** added for indicator-free multi-bar strategies (Rule-3 scope expansion, required for the gate).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Plan-B per-ticker fan-out left `self.short_sma` pointing at an un-updated handle (read-before-warm crash)**
- **Found during:** Task 1 (the oracle backtest crashed `RuntimeError: handle must be warmed before reading` at the first ready tick).
- **Issue:** Plan B's `_handle_set_for` minted SEPARATE `IndicatorHandle` OBJECTS per ticker and `update` drove those, but the author's `self.short_sma` was bound (in `init()`) to the REGISTRATION handle (`self._handles[i]`), which `update` never touched — so `generate_signal` read an empty buffer.
- **Fix:** Re-implemented the per-symbol fan-out as a STATE-SWAP on the single registration handle-set (`_activate_ticker` + `IndicatorHandle.snapshot_state`/`load_state`/`fresh_state`), so the author-bound attrs always reflect the active ticker without the base needing their names (P5-D21). `is_ready`/`reset` read/clear the per-ticker `_handle_state_store`.
- **Files modified:** `itrader/strategy_handler/base.py`, `itrader/strategy_handler/indicators/handle.py`.
- **Verification:** oracle byte-exact 134 / 46189.87730727451; per-symbol independence test (`test_causal_guard`) green.
- **Committed in:** `37f6a4e`

**2. [Rule 1/Deviation — anchor type] `self.now = bar.time`, not the literal `event.time`**
- **Found during:** Task 1 design (the e2e scenarios call `self.now.tz_convert("UTC")`).
- **Issue:** `event.time` is a plain `datetime` (no `.tz_convert`); the plan body wrote `self.now = event.time`. Using it would `AttributeError` in ~12 e2e scenario strategies.
- **Fix:** `self.now = bar.time` — a tz-aware pandas Timestamp byte-identical to the legacy `window.index[-1]`, preserving both the anchor value and the `.tz_convert` contract.
- **Files modified:** `itrader/strategy_handler/base.py`.
- **Verification:** all `self.now.tz_convert` e2e scenarios green.
- **Committed in:** `37f6a4e`

**3. [Rule 3 — Blocking] Multi-bar indicator-free strategies broke once the slice was removed**
- **Found during:** Task 3 (the e2e `limit_entry_crossval` scenario + the perf strategies read `self.bars`, which no longer exists).
- **Issue:** `scripts/crossval/limit_entry_strategy` + `perf/strategies/{a,b,c,d}` + `perf/runners/run_w2_sweep` read `self.bars` (the plan named only SingleMarketBuy/ScriptedEmitter/BuyEachTickerOnce). They break the full-suite gate.
- **Fix:** migrated them onto `latest_bar(ticker)` / the new `recent_closes(ticker)` seam, firing preserved.
- **Files modified:** `scripts/crossval/limit_entry_strategy.py`, `perf/strategies/a_bracketed_momentum.py`, `perf/strategies/b_limit_maker.py`, `perf/strategies/c_pyramiding_trend.py`, `perf/strategies/d_short_zscore.py`, `perf/runners/run_w2_sweep.py`.
- **Verification:** e2e/integration 97 passed; full suite 1287 passed.
- **Committed in:** `094a345`

**Total deviations:** 3 (1 Rule-1 fan-out bug, 1 anchor-type correction, 1 Rule-3 scope expansion). All three were required for the byte-exact gate; none changed the oracle numbers.

## Authentication Gates

None.

## Known Stubs

None. The per-tick `feed.window()` slice is fully removed (single-leg + pair); the pair runs on the bounded fit-once-frozen β + bounded-z buffers; all migrated strategies read the new `bar_count`/`latest_bar`/`recent_closes` seams. PERF-05 is complete on the correctness axis. (Gate (b) — the W1/W2 re-freeze on a cool machine — is the carried-over thermal todo, deferred per STATE.md, not a Plan-C deliverable.)

## Self-Check: PASSED

- Created file exists (this SUMMARY).
- All task commits exist (`37f6a4e`, `44222bb`, `094a345`).
- `grep -c "self.feed.window" itrader/strategy_handler/strategies_handler.py` == 0; `grep self.bars` in the migrated fixtures returns comments only (no code reads).
- Oracle byte-exact 134 / 46189.87730727451 (behavioral + numeric); pair flagship snapshot byte-for-byte; full suite 1287 passed; `mypy --strict` clean (188 files); determinism double-run byte-identical (SHA-256).

---
*Phase: 05-incremental-indicators-fragile-oracle-gated-last*
*Completed: 2026-06-24*
