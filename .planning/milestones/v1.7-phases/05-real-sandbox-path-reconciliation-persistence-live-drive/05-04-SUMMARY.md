---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 04
subsystem: reconciliation
tags: [drift, halt, reconciliation, venue-account, alert, engine-thread, RECON-01, RECON-03, RES-01]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 01
    provides: "is_within_single_unit_tolerance (D-01) + SystemStatus.HALTED (D-07) + AlertSink/LogAlertSink CRITICAL egress (D-06)"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 03
    provides: "VenueAccount cached balance/available/positions + snapshot() + start_streaming() seam"
provides:
  - "Engine-thread per-symbol drift compare + halt DECISION in PortfolioHandler (on_fill immediate + BAR-route periodic backstop, D-15) — within-band adopt / external-adopt / unexplained-halt"
  - "PortfolioHandler.set_halt_signal + set_drift_reconciler injected seams (halt callback + external-event reconciler)"
  - "LiveTradingSystem.halt(reason) freeze-in-place entrypoint: SystemStatus.HALTED + halt_reason on get_status (D-07) + CRITICAL alert (D-06) + new-submission suppression (D-02), no auto-flatten/cancel"
  - "Composition-root wiring: LogAlertSink injected into EventHandler; PortfolioHandler halt signal wired to LiveTradingSystem.halt; VenueAccount stream-start + snapshot + Portfolio link on okx start() (D-14)"
affects: [05-08-resilience, VenueAccount, restart-reconcile, live-drive]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Drift COMPARE + halt DECISION on the ENGINE thread (D-15) — async writer only writes the VenueAccount cache; compare runs after the fill drains, defeating the phantom-drift race (Pitfall 8) structurally (no compare reachable from a spawned coroutine)"
    - "Position-based per-symbol drift (nautilus _check_position_discrepancy analog) keyed to instrument quantity precision via is_within_single_unit_tolerance — account-independent, so it works whether the live account computes or caches cash"
    - "Freeze-in-place halt (D-02): suppress SIGNAL/ORDER routes while BAR/FILL/ERROR continue; no auto-flatten/auto-cancel (the engine declared its own state untrustworthy, so it must not act on it)"

key-files:
  created:
    - tests/unit/portfolio/test_venue_account_drift.py
  modified:
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/execution/test_drift_halt_policy.py

key-decisions:
  - "Drift is POSITION-based (per-symbol quantity), not balance-based: it compares the engine's fill-applied position tally against VenueAccount cached positions. This is the nautilus _check_position_discrepancy / RESEARCH Pattern-1 approach and is account-independent, sidestepping the VenueAccount-lacks-cash-settlement gap. Balance/fee drift is spot-only-named (Pitfall 12), deferred."
  - "External-adopt (D-04) is gated by an INJECTED reconciler seam (set_drift_reconciler) that answers whether a beyond-band drift maps to a known venue event; default None → conservative money-first (any beyond-band drift is unexplained → halt). The real reconciler (consuming venue order/fill events + stored intent) is a restart/resilience follow-on (D-03/D-05)."
  - "The halt CRITICAL ErrorEvent is emitted ONCE, by LiveTradingSystem.halt (source='live_trading_system'), not by the PortfolioHandler drift compare — the compare only calls the halt signal. Keeps emission DRY and lets a non-drift halt (connector-fatal) reuse the same egress."

requirements-completed: [RECON-01, RECON-03, RES-01]

# Metrics
duration: ~40min
completed: 2026-07-02
---

# Phase 05 Plan 04: Drift/Halt Policy Summary

**A per-symbol engine-thread drift compare (on fill + on a per-closed-bar backstop, D-15) that adopts venue truth within the precision-epsilon band, adopts-and-continues on a reconciled external event (D-04), and freezes the WHOLE engine in place on unexplained beyond-band drift (D-01/D-02) — surfacing a distinct `SystemStatus.HALTED` + machine-readable `halt_reason` (D-07) and a CRITICAL alert through the injected sink (D-06), with the VenueAccount linked into the live Portfolio and its stream started at the composition root (D-14).**

## Performance
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- **Task 1 — engine-thread drift compare (D-15/D-01/D-04):** `PortfolioHandler._compare_symbol_drift` compares the engine's fill-applied position quantity against `VenueAccount.positions` per symbol via `is_within_single_unit_tolerance` keyed to the instrument quantity precision (`_drift_precision`, Universe-resolved, default 8). Within band → adopt silently; beyond band + reconciled to a known venue event → adopt-and-continue (D-04); beyond band + unexplained → `self._halt_signal("drift")` (freeze-in-place). Wired into `on_fill` (immediate, after the fill drains) and a BAR-route `_run_drift_sweep` (periodic backstop). Guarded on `isinstance(account, VenueAccount)`, so backtest/paper `SimulatedAccount` portfolios skip cleanly — the SMA_MACD oracle stays byte-exact (134 / 46189.87730727451).
- **Task 2 — freeze-in-place halt + observability + wiring (D-02/D-07/D-06/D-14):** `LiveTradingSystem.halt(reason)` sets `SystemStatus.HALTED` + a machine-readable `halt_reason` (surfaced on `get_status()`), suppresses new order submission via `_dispatch_live` (SIGNAL/ORDER frozen while BAR/FILL/ERROR continue), emits ONE CRITICAL `ErrorEvent` through the injected `LogAlertSink`, and NEVER auto-flattens/auto-cancels; idempotent (first reason wins). Composition root injects `LogAlertSink` into the `EventHandler`, wires `PortfolioHandler.set_halt_signal(self.halt)`, and on okx `start()` snapshots + starts the `VenueAccount` stream before RUNNING and links it into active portfolios (D-14).

## Task Commits
1. **Task 1: engine-thread drift compare + halt signal** — `99c2f2b0` (feat)
2. **Task 2: freeze-in-place halt + HALTED status + alert + VenueAccount wiring** — `9eebbd9b` (feat)

## Files Created/Modified
- `itrader/portfolio_handler/portfolio_handler.py` (modified) — `set_halt_signal` / `set_drift_reconciler` seams, `_drift_precision`, `_compare_symbol_drift`, `_run_drift_sweep`; `on_fill` + `update_portfolios_market_value` hooks. 4-space indent; mypy `--strict` clean.
- `itrader/trading_system/live_trading_system.py` (modified) — `halt` / `_is_halted` / `_dispatch_live`; `_halt_reason` field; `halt_reason` on `get_status`; `LogAlertSink` + halt-signal wiring; okx `start()` VenueAccount snapshot/stream/link (D-14). 4-space indent; mypy-deferred (D-live), no new errors.
- `tests/unit/portfolio/test_venue_account_drift.py` (created, 10 tests) — within-band no-halt (exact + epsilon-dust), beyond-band unexplained halt, external-fill adopt, SimulatedAccount skip, BAR-sweep halt/no-op.
- `tests/unit/execution/test_drift_halt_policy.py` (modified, +8 tests) — HALTED status + reason, CRITICAL alert to sink, submission suppression, no-flatten/cancel, idempotency, drift-signal wired.

## Decisions Made
- **Position-based drift, not balance-based.** The compare is per-symbol quantity (nautilus `_check_position_discrepancy` / RESEARCH Pattern-1), which is account-independent and matches the D-01 precision-epsilon design. Balance/fee drift is spot-only-named (Pitfall 12) and deferred.
- **Single CRITICAL emission point.** `LiveTradingSystem.halt` owns the CRITICAL `ErrorEvent`; the PortfolioHandler compare only fires the halt signal. DRY, and reusable for non-drift halts.
- **Conservative external-adopt default.** `set_drift_reconciler` is `None` by default → any beyond-band drift is unexplained → halt (money-first). The real venue-event reconciler is a restart/resilience follow-on (D-03/D-05).

## Deviations from Plan
### Auto-fixed / design resolutions

**1. [Rule 3 - Blocking design] Drift compare made position-based (account-independent) rather than "position/cash tally"**
- **Found during:** Task 1 (implementing the compare against a live `VenueAccount`).
- **Issue:** The plan action says "compare the engine's fill-applied position/cash tally … after `portfolio.transact_shares`", and Task 2(a) links `portfolio.account = VenueAccount`. But `VenueAccount` (05-03) has no cash-settlement surface (`apply_fill_cash_flow` / `assert_funds_invariant`), so a live `transact_shares` cannot settle cash through it — the "cash tally" comparison has no engine-side cash operand under a VenueAccount, and full live fill-settlement-with-VenueAccount is out of this plan's stated files.
- **Fix:** Implemented the compare as **per-symbol position** drift (engine `get_open_position(...).net_quantity` vs `VenueAccount.positions`), which is the nautilus `_check_position_discrepancy` / RESEARCH Pattern-1 design, is account-independent, and fully realizes D-01/D-04/D-15. Documented the live cash-settlement path (dual-account or a VenueAccount settlement surface) as a follow-on.
- **Files:** `itrader/portfolio_handler/portfolio_handler.py`
- **Committed in:** `99c2f2b0`

**2. [Rule 3 - Blocking design] External-adopt (D-04) exposed as an injected reconciler seam**
- **Found during:** Task 1 (distinguishing "external fill adopt" from "unexplained halt").
- **Issue:** Steady-state external-fill-vs-unexplained cannot be told apart from a single position snapshot, and `VenueAccount` (unmodifiable this plan) exposes no venue fill/order event log. The plan's files exclude the order-store intent integration.
- **Fix:** Added `set_drift_reconciler((portfolio, ticker, engine_qty, venue_qty) -> bool)` — the injected predicate that answers "does this beyond-band drift map to a known venue event?" Default `None` → conservative halt. The external-adopt branch is exercised by the test; the production reconciler (venue order/fill events + stored intent) lands with the restart/resilience work (D-03/D-05).
- **Files:** `itrader/portfolio_handler/portfolio_handler.py`
- **Committed in:** `99c2f2b0`

## Known Stubs / Follow-ons
- **Live fill-settlement with a VenueAccount** — linking `portfolio.account = VenueAccount` at okx `start()` (D-14) satisfies the drift-compare read path, but a live EXECUTED fill's cash settlement through `transact_shares` requires a VenueAccount settlement surface (or a dual-account split). Out of scope here (this plan delivers the drift/halt policy); flagged for the live-drive / restart follow-on. Not exercised by any offline gate (the halt tests drive the entrypoint directly; the drift tests seed the VenueAccount cache).
- **Production drift reconciler** — the `set_drift_reconciler` seam is wired empty this plan (conservative halt). The real venue-event/stored-intent reconciler is a restart/resilience (05-08) concern.

## Verification Results
- `tests/unit/portfolio/test_venue_account_drift.py` — **10 passed**.
- `tests/unit/execution/test_drift_halt_policy.py` — **15 passed** (7 from 05-01 + 8 new).
- `tests/integration/test_live_system_okx_wiring.py` (5) + `tests/integration/test_okx_inertness.py` (1) — **6 passed** (inertness + composition-root wiring intact).
- `tests/integration/test_backtest_oracle.py` — **3 passed** (byte-exact 134 / 46189.87730727451 — drift compare inert on backtest/paper).
- `mypy --strict itrader/portfolio_handler/portfolio_handler.py itrader/trading_system/live_trading_system.py` — **Success: no issues found**.
- Broader regression: `tests/unit/portfolio tests/unit/execution` — **508 passed** (no regressions).
- Acceptance greps: `is_within_single_unit_tolerance` = 4, `async def` = 0 (portfolio_handler); `HALTED` = 10, `halt_reason` = 4, `VenueAccount` = 5 (live_trading_system).

## Threat Flags
None found — no new network endpoints, auth paths, or trust-boundary surface beyond the plan's `<threat_model>`. The CRITICAL halt egress reuses the 05-01 secret-scrubbed sink (only declared ErrorEvent fields — T-05-15/Pitfall 16); the compare runs engine-thread-only (T-05-13/Pitfall 8); unexplained beyond-band drift halts before trading on untrusted state (T-05-14); HALTED + halt_reason make the halt observable (T-05-16).

## Self-Check: PASSED
- `itrader/portfolio_handler/portfolio_handler.py` — FOUND
- `itrader/trading_system/live_trading_system.py` — FOUND
- `tests/unit/portfolio/test_venue_account_drift.py` — FOUND
- `tests/unit/execution/test_drift_halt_policy.py` — FOUND
- Commit `99c2f2b0` — FOUND
- Commit `9eebbd9b` — FOUND

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*
