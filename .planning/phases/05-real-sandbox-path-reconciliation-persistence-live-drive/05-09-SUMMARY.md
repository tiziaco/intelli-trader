---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 09
subsystem: phase-close
tags: [error-policy-split, fail-fast, publish-and-continue, shared-parity-config, inertness, doc-sync, milestone-gate, D-17, D-18, RECON-06, RECON-04, RES-01]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 04
    provides: "Halt-aware LiveTradingSystem (HALTED status, _dispatch_live gate) + freeze-in-place halt"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 06
    provides: "Live store drive / split write paths (D-10/D-11) + run_paper_replay parity driver context"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 08
    provides: "Reconnect supervisor / hardened publish-and-continue live error policy (RES-01)"
provides:
  - "Error-policy SPLIT (D-17/WR-04): run_paper_replay runs FAIL-FAST (base EventHandler._on_handler_error re-raise) so a swallowed handler error can never false-green the parity gate; the live daemon path (start()) KEEPS publish-and-continue"
  - "Shared-parity-config (D-18 structural): PAPER_PARITY_START_DATE/END/SYMBOL is the SINGLE source — the paper replay store is constructed explicitly from it AND the backtest comparand (test_paper_parity.py) imports it, so paper/backtest can never silently desync (WR-02 coincidental parity removed)"
  - "Extended inertness gate: itrader.portfolio_handler.reconcile.venue_reconciler forbidden on the backtest import path (new Phase-5 live-arm reconcile module)"
  - "Doc-sync (D-18): REQUIREMENTS RUN-01 deferred PAST Phase 5 to the app-layer plan; RECON-03 concretized by D-01; RECON-04 realized via split write paths (D-10/D-11)"
affects: [phase-close, parity-gate, inertness-gate, live-error-policy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Error-policy bind moved from __init__ to start() (D-17): the daemon/live path installs _publish_and_continue; run_paper_replay never calls start(), so the deterministic parity driver inherits the base fail-fast re-raise — fail-fast for the diffed replay, publish-and-continue for the live session, from ONE class"
    - "Single-source parity literal (D-18): the replay store is constructed CsvPriceStore(start_date=PAPER_PARITY_START_DATE, end_date=PAPER_PARITY_END_DATE) instead of relying on the class defaults coinciding with the test literals; the parity test imports the same module constants"

key-files:
  created: []
  modified:
    - itrader/trading_system/live_trading_system.py
    - tests/integration/test_paper_parity.py
    - .planning/REQUIREMENTS.md
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "The error-policy split is realized by MOVING the _on_handler_error bind out of __init__ into start() (the daemon entrypoint), rather than adding a replay-specific override flag. run_paper_replay() calls _initialize_live_session() directly and never start(), so it uses the base fail-fast re-raise by construction — the smallest, most auditable split (grep: the single _publish_and_continue bind now lives only in start())."
  - "D-18 structural half was completed by making PAPER_PARITY_* module constants the single source AND wiring both sides to it. This required editing test_paper_parity.py (not in the plan's files_modified) to import the shared constants — a Rule-3 necessary change to satisfy the acceptance 'single grep-locatable source'. The replay store is now constructed explicitly from the window, so it no longer depends on CsvPriceStore class defaults coinciding with the test literals (WR-02 coincidental parity structurally removed)."
  - "account.venue (VenueAccount) and trading_system.alert_sink are deliberately NOT added to the inertness _FORBIDDEN set: both keep their live deps TYPE_CHECKING-only (LiveConnector) and pull no async/connector/SQLAlchemy, so they are inert-by-construction even when transitively imported on the backtest path. Only venue_reconciler (the live-drive reconcile surface, lazy inside start()'s OKX arm) is forbidden — matching the task's guidance and the concrete acceptance grep."
  - "ROADMAP.md doc-sync (the RUN-01 'to Phase 5' -> 'past Phase 5' text corrections) was NOT committed from this worktree: the orchestrator owns ROADMAP writes centrally after the wave merges. The exact corrections are specified below under 'Deferred to orchestrator' so the central write can apply them."

requirements-completed: [RECON-04, RECON-06, RES-01]

# Metrics
duration: ~55min
completed: 2026-07-02
---

# Phase 05 Plan 09: Error-Policy Split + Phase Close Summary

**Closed Phase 5 by splitting the handler-error policy so the deterministic `run_paper_replay` parity driver runs FAIL-FAST (base re-raise — a swallowed error can never false-green the parity gate) while the live daemon path keeps publish-and-continue (D-17/WR-04); folding in the D-18 structural cleanup so the paper replay store window/symbol and the backtest comparand both derive from ONE `PAPER_PARITY_*` source (WR-02 coincidental parity removed); syncing the stale RUN-01/RECON REQUIREMENTS text (D-18 doc-sync); extending the inertness probe to forbid `venue_reconciler` on the backtest import path; and passing the terminal recurring milestone gate — oracle byte-exact 134 / 46189.87730727451, determinism-identical, inertness green, parity green.**

## Performance
- **Tasks:** 3
- **Files modified:** 4 (0 created, 4 modified)

## Accomplishments
- **Task 1 — error-policy split (D-17) + shared-parity-config (D-18 structural).** Moved the `self.event_handler._on_handler_error = self._publish_and_continue` bind out of `__init__` (where it applied unconditionally to both okx AND paper systems) into `start()` — the live-daemon entrypoint ONLY. `run_paper_replay()` calls `_initialize_live_session()` directly and never `start()`, so it now inherits the base `EventHandler._on_handler_error` re-raise (fail-fast): a handler failure aborts the replay loudly and the 04-04 parity gate can never pass on a swallowed error (T-05-28). Then folded in the D-18 structural half: introduced `PAPER_PARITY_START_DATE`/`PAPER_PARITY_END_DATE`/`PAPER_PARITY_SYMBOL` as the single source, constructed the replay store EXPLICITLY as `CsvPriceStore(start_date=..., end_date=...)` from those constants (instead of relying on the CsvPriceStore class defaults happening to equal the test literals), and pointed the parity test's backtest comparand at the same constants — so paper and backtest can never silently desync (WR-02 coincidental parity removed). No numbers changed: parity + oracle stay byte-exact 134 / 46189.87730727451.
- **Task 2 — doc-sync REQUIREMENTS (D-18).** Corrected RUN-01 so the Postgres `LISTEN/NOTIFY` command/status channel + FastAPI wrapper are stated as **deferred PAST Phase 5** to the FastAPI application-layer plan (Phase-5 D-08 re-defers the earlier "to Phase 5" target — they did NOT land in Phase 5); the standalone worker runs without them (HALTED status D-07 + persisted store carry what a future controller needs). Reflected that RECON-03 is concretized by D-01 (precision-epsilon auto-correct band + whole-engine halt) and RECON-04 by D-10/D-11 (split write paths). Requirement IDs unchanged. The equivalent ROADMAP.md corrections are deferred to the orchestrator's central write (see below).
- **Task 3 — extended inertness + terminal milestone gate (D-09).** Added `itrader.portfolio_handler.reconcile.venue_reconciler` to the inertness probe `_FORBIDDEN` set (the new Phase-5 live-drive reconcile module, lazy inside `start()`'s OKX arm — must never load on the backtest import path). Documented why `account.venue` (VenueAccount) and `alert_sink` are deliberately NOT forbidden (LiveConnector TYPE_CHECKING-only; no async/connector/SQL pulled — inert by construction). Ran the terminal gate: extended inertness green (no ccxt/ccxt.pro/connectors.okx/live_bar_feed/replay_provider/venue_reconciler on the backtest path), oracle byte-exact 134 / 46189.87730727451 determinism-identical, parity green, and the affected-domain suites green.

## Task Commits
1. **Task 1: split error policy (replay fail-fast) + shared parity config** — `32fa995c` (feat)
2. **Task 2: doc-sync REQUIREMENTS — RUN-01 defer past Phase 5 + RECON refine** — `5b962e38` (docs)
3. **Task 3: extend inertness probe to forbid venue_reconciler** — `3737c643` (test)

## Files Modified
- `itrader/trading_system/live_trading_system.py` (4-space, mypy-deferred but `--strict` clean on this file) — `PAPER_PARITY_*` single-source constants; `_PAPER_STREAM_SYMBOL`/`_PAPER_EXPECTED_*` aliased to them; replay store constructed explicitly from the shared window; `_on_handler_error` bind removed from `__init__` and installed in `start()` (daemon path only).
- `tests/integration/test_paper_parity.py` — backtest comparand window/symbol (`_START_DATE`/`_END_DATE`/`_TICKER`) now imported from `live_trading_system`'s `PAPER_PARITY_*` constants (D-18 single source).
- `.planning/REQUIREMENTS.md` — RUN-01 deferred past Phase 5 (D-08); RECON-03 concretized by D-01; RECON-04 realized via split write paths (D-10/D-11).
- `tests/integration/test_okx_inertness.py` — `_FORBIDDEN` extended with `venue_reconciler`; comment documents the deliberate NON-forbidding of `account.venue` + `alert_sink`.

## Decisions Made
See frontmatter `key-decisions`. Load-bearing: (1) the split is a bind-relocation (`__init__` → `start()`), not a flag — smallest auditable change; (2) the replay store is now constructed from the shared window literal, structurally removing WR-02 coincidental parity; (3) only `venue_reconciler` is forbidden — `account.venue`/`alert_sink` are inert-by-construction (TYPE_CHECKING-only deps); (4) ROADMAP doc-sync deferred to the orchestrator's central write.

## Deviations from Plan

### Auto-fixed / scope resolutions

**1. [Rule 3 - Blocking] Edited test_paper_parity.py (not in the plan's files_modified) to complete the D-18 structural half.**
- **Found during:** Task 1. The D-18 acceptance requires "the paper replay window/symbol AND the backtest window derive from one shared literal (single grep-locatable source)". The backtest comparand window (`_START_DATE`/`_END_DATE`/`_TICKER`) lives in `test_paper_parity.py`, which the plan's `files_modified` did not list.
- **Fix:** Promoted the window/symbol to `PAPER_PARITY_*` module constants in `live_trading_system.py` (the single source), constructed the replay store explicitly from them, and imported them into `test_paper_parity.py` for the backtest side. This is the only way to make BOTH sides derive from one source per the acceptance.
- **Files modified:** `itrader/trading_system/live_trading_system.py`, `tests/integration/test_paper_parity.py`
- **Committed in:** `32fa995c`

**2. [Orchestrator directive] ROADMAP.md doc-sync deferred to the central write (NOT committed from this worktree).**
- **Found during:** Task 2. The plan's `files_modified` lists `.planning/ROADMAP.md`, but the executor's orchestrator directive is explicit: "leave ROADMAP.md alone even if listed — the orchestrator marks the phase complete centrally" (ROADMAP writes are owned centrally to avoid parallel-wave merge conflicts).
- **Resolution:** Applied the REQUIREMENTS.md doc-sync (explicitly allowed in worktree mode) and reverted ROADMAP.md to pristine. The equivalent ROADMAP corrections are specified below for the orchestrator to apply during the central ROADMAP write.

### Deferred to orchestrator (ROADMAP.md central write)
The following stale "to/defer to Phase 5" channel/FastAPI mentions should be corrected to "past Phase 5 to the FastAPI application-layer plan (D-08)" during the central ROADMAP update:
- Phase 4 revised-note (~line 203): "the Postgres `LISTEN/NOTIFY` channel + FastAPI move to Phase 5 (D-08: revises RUN-01)" → defer **past Phase 5** to the app-layer plan.
- Phase 4 goal (~line 212): "the channel/FastAPI defer to Phase 5." → defer **past Phase 5** (D-08).
- Phase 4 research-flag (~line 235): "channel/FastAPI deferred to Phase 5 (D-08)." → deferred **past Phase 5** to the app-layer plan (D-08).
(ROADMAP PAPER-01/02/04 text is already anchored to the fresh-backtest parity, not a byte-exact-vs-46189 gate — no change needed there.)

## Verification Results
- `tests/integration/test_paper_parity.py` + `tests/integration/test_backtest_oracle.py` — **4 passed** (parity == fresh backtest; oracle byte-exact 134 / 46189.87730727451, `check_exact`, determinism-identical).
- `tests/integration/test_okx_inertness.py` — **1 passed** (extended `_FORBIDDEN` green — no ccxt/ccxt.pro/connectors.okx/live_bar_feed/replay_provider/venue_reconciler on the backtest import path).
- `mypy --strict itrader/trading_system/live_trading_system.py` — **Success: no issues found**.
- Live/integration surface exercising the changes: `test_live_system_okx_wiring.py` (5) + `test_live_paper_lifecycle.py` (3) + `test_live_bar_metrics.py` (2) + `test_live_bar_feed_route_order.py` (2) + `test_live_bar_feed_warmup.py` (6) + `test_drift_halt_policy.py` (15) — **33 passed**.
- Unit domains: `portfolio` + `order` + `events` — **653 passed**; `execution` — **212 passed** (incl. reconnect resilience); `core` + `config` + `strategy` — **276 passed**; `connectors/test_fake_venue_connector.py` — **7 passed**.
- Acceptance greps: `venue_reconciler` in `test_okx_inertness.py` = **1**; the single `_publish_and_continue` bind now lives only in `start()` (not reachable from `run_paper_replay`); `PAPER_PARITY_*` is a single source read by both `live_trading_system.py` and `test_paper_parity.py`; no ROADMAP/REQUIREMENTS text asserts the channel lands in Phase 4 (RUN-01 states deferred past Phase 5).

### Full-suite note (environment)
`make test` / full `poetry run pytest tests` could NOT complete in this sandbox: `tests/unit/connectors/test_okx_connector.py` + `test_okx_data_provider.py` HANG (they make real OKX-host network round-trips that cannot complete in the network-blocked worktree sandbox — a pre-existing environment condition, NOT a regression from this plan; `test_fake_venue_connector.py` passes fast). This plan's changes are confined to `live_trading_system.py` (paper/daemon paths), the parity test, REQUIREMENTS, and the inertness probe — none touch the OKX connector. All affected domains are green (above). Recommend the final full-suite `make test` run in the main checkout (per memory: worktree `make test` aborts on missing `.env`).

### W1/W2 perf
No W1/W2 regression is attributable to this plan: the backtest import path pulls NO new async/connector/SQL code (extended inertness probe green — ccxt/ccxt.pro/connectors.okx/live_bar_feed/replay_provider/venue_reconciler all absent from the backtest import graph). The Task-1 edit added no module-scope heavy import to the backtest path (it reused the already-imported `CsvPriceStore` inside the lazy paper arm, which is off the backtest hot path). The oracle stays byte-exact (the W-relevant hot path). Baseline anchor: v1.5 15.7 s / 152.8 MB.

### RECON-06 sandbox evidence (D-09)
The RECON-06 "validated" evidence is the opt-in slow sandbox suite `tests/e2e/test_okx_sandbox_recon.py` (`-m slow`, `e2e`) — a real order → fill → reconcile → restart loop against the OKX **demo** host, `skipif` unless `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE` are present. It stays OUT of `make test` / CI (network-gated, run locally with OKX demo creds); in this credential-free sandbox it is skipped by design. Real-money execution stays gated (not in the DoD).

## Known Stubs
None introduced. No hardcoded/placeholder values or unwired data sources in this plan's changes.

## Threat Flags
None beyond the plan's `<threat_model>`. T-05-28 (parity gate false-green on a swallowed error) — mitigated: `run_paper_replay` is now fail-fast (base re-raise), so a handler failure aborts the replay loudly. T-05-29 (live import leaking onto the backtest path) — mitigated: extended inertness probe forbids `venue_reconciler` and the pre-existing OKX/async set; oracle byte-exact + no W1/W2 regression. T-05-30 (sandbox credential handling) — the RECON-06 suite is opt-in skipif-no-creds, creds env-only, real-money gated. No new network endpoint, auth path, or schema surface at a trust boundary.

## Self-Check: PASSED
- `itrader/trading_system/live_trading_system.py` — FOUND
- `tests/integration/test_paper_parity.py` — FOUND
- `.planning/REQUIREMENTS.md` — FOUND
- `tests/integration/test_okx_inertness.py` — FOUND
- Commit `32fa995c` — FOUND
- Commit `5b962e38` — FOUND
- Commit `3737c643` — FOUND
- `.planning/ROADMAP.md` — pristine (deferred to orchestrator central write)

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*
