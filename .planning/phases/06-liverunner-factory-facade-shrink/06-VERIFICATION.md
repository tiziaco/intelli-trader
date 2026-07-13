---
phase: 06-liverunner-factory-facade-shrink
verified: 2026-07-13T14:03:14Z
status: passed
score: 6/6 success criteria verified (2 with decision-backed deviations from literal roadmap wording)
behavior_unverified: 0
overrides_applied: 0
re_verification: null
---

# Phase 6: LiveRunner + Factory + Facade Shrink Verification Report

**Phase Goal:** Make `build_live_system` the live composition root over a new `LiveRunner`,
shrinking `LiveTradingSystem` to a ~200-line facade — with the shared `UniverseWiring`
extracted byte-exact (the highest oracle-risk seam) and reused by both runners, and live
routes composed declaratively.

**Verified:** 2026-07-13T14:03:14Z
**Status:** passed
**Re-verification:** No — initial verification

## Independently Re-Run Gates (per instructions — NOT taken from SUMMARY claims)

All three gates were re-run in this session with `poetry run pytest` (not `make test`):

| Gate | Command | Result |
| --- | --- | --- |
| Backtest oracle byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | **3 passed** — `tests/golden/summary.json` confirms `trade_count: 134`, `final_equity: 46189.87730727451` |
| OKX inertness | `poetry run pytest tests/integration/test_okx_inertness.py -q` | **4 passed** |
| Paper parity | `poetry run pytest tests/integration/test_paper_parity.py -q` | **1 passed** |
| Replay-harness collection safety | `poetry run pytest tests/unit/test_replay_harness_collection.py -q` | **2 passed** |
| mypy --strict | `poetry run mypy itrader` | `Success: no issues found in 249 source files` |
| Full suite | `poetry run pytest tests -q` | **2128 passed, 6 skipped** (6 skips are OKX-demo-credential-gated, expected offline) |

All gate results match the SUMMARY claims exactly (byte-exact numbers, pass counts).

## Goal Achievement — Success Criteria

| # | Success Criterion | Status | Evidence |
| - | --- | --- | --- |
| 1 | Shared `UniverseWiring` extracted as ONE intact unit (incl. WR-03 desync assert), reused by BOTH `BacktestRunner` and live `SessionInitializer`; byte-exact oracle | ✓ VERIFIED | `itrader/trading_system/universe_wiring.py::wire_universe(engine)` is a single free function containing the full `derive_membership → derive_instruments → WR-03 assert → Universe → inject(exchange/order/portfolio/strategies) → feed.bind` chain (read in full). `backtest_runner.py` calls it (`grep -c "wire_universe(engine)"` = 1); `session_initializer.py:106` calls it as step (1) of `initialize()`. The WR-03 desync assert (`if set(membership) != set(instruments): raise ConfigurationError(...)`) is present and genuine (not tautological) — it compares two independently-derived sets. Oracle re-run independently: 134 trades / `46189.87730727451`, byte-exact. |
| 2 | `build_live_system(spec)` is the composition root; `LiveRunner` owns drain loop + injected `ErrorPolicy` + worker supervision, replacing `_event_processing_loop`; CONTROL routes NOT registered in P6; `LiveRouteRegistrar` registers BUSINESS/live routes | ✓ VERIFIED (1 documented, justified deviation) | `build_live_system` (`live_trading_system.py:1422`) is the sole live construction path, wires `PriorityEventBus` (`global_queue = PriorityEventBus()`, confirmed), composes `ErrorPolicy`/`WorkerSupervisor`/`LiveRunner` (`live_trading_system.py:1694-1712`, confirmed by direct read). `_event_processing_loop`/`_run_poll_timer`/`_publish_and_continue` method **definitions** no longer exist in the facade (only comment references remain — confirmed via grep). `route_registrar.py::LiveRouteRegistrar.install()` sets exactly `UNIVERSE_POLL`/`UNIVERSE_UPDATE`/`STRATEGY_COMMAND`/`BARS_LOADED`/`BARS_LOAD_FAILED` and appends to `FILL`; `grep -c "STREAM_STATE\|CONNECTOR_FATAL\|CONFIG_UPDATE"` on `route_registrar.py` = 0 (CONTROL routes correctly absent, matching D-23). **Documented deviation:** `build_live_system` does NOT call `compose_engine` — verified by grep (`compose_engine` appears only in comments/docstrings, never as a call). This is disclosed in the 06-06 SUMMARY and is a legitimate, justified deviation: `compose_engine` hardwires `BacktestBarFeed`, which is structurally incompatible with the live `LiveBarFeed` push-driven contract; forcing it through would either break the live feed or risk the backtest byte-exact oracle. The structural goal ("one composition root owning all live wiring") is still met — `build_live_system` is verified to be the actual sole construction path (all ~45 direct construction sites migrated to `.for_exchange()`, confirmed via grep = 0 residual `LiveTradingSystem(exchange=`). |
| 3 | `LiveTradingSystem` shrinks to a ~200-line facade; `print_status`/`get_statistics` dropped; `__init__` sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time` | ⚠️ PARTIALLY MET — numeric target explicitly deferred per locked decision D-03 | **Measured directly:** `itrader/trading_system/live_trading_system.py` is **1715 lines total** (class body ≈1287 lines, `134`–`1421`); this is NOT ~200 lines. `print_status`/`get_statistics` ARE deleted (`grep -n "def print_status\|def get_statistics"` = 0 matches). `__init__` signature is confirmed pure injection: `def __init__(self, components: "LiveSystemComponents", *, status_callback=None)` — sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time` exactly as required. The safety/reconcile/stream method BODIES (`halt`, `pause_submission`, `resume_submission`, `reset_halt`, `_update_status`, `_dispatch_live`, `_is_halted`, `_replay_deferred_protective`, `_run_session_baseline_guard`, `_link_venue_account_to_portfolios`, `_on_venue_stream_down`, `_maybe_resume_after_reconnect`, `_maybe_halt_after_connector_fatal`) are all confirmed STILL PRESENT and untouched in the facade (grep-confirmed line numbers 307–760) — this matches D-04's explicit mandate that P6 must NOT touch these bodies so P7 extracts from an unchurned baseline. **Assessment:** `06-CONTEXT.md` D-03 is a LOCKED decision, established during phase planning (not an after-the-fact excuse), stating literally: "Roadmap SC3 lists '~200-line facade' as a P6 criterion, but P7... owns extracting the ~500 lines... P6 physically can't finish P7's extraction... the literal `~200` is a milestone-exit gate verified at P7 close, NOT a P6-close gate." Every PLAN's `must_haves` (06-06) explicitly encodes this exception. Given the decision is locked pre-execution and the P7-dependency reasoning is structurally sound (the very method bodies that must be removed to reach ~200 lines are the ones D-04 forbids touching in P6), this is a legitimate, decision-backed deferral — not a gap requiring rework at this phase close. The **structural** RUN-03 requirements (pure injection, dropped legacy methods, shed constructor params) ARE fully met. |
| 4 | `LiveRouteRegistrar` composes routes declaratively (list order = execution order, no subclass, no runtime mutation); `UniverseHandler` first-class with zero OKX coupling; `StrategyWarmupConsumer` rehomed sized to `max(strategy.warmup)` with the CF-10 depth-hint seam shaped | ✓ VERIFIED | `route_registrar.py` read in full: single class, no subclassing, `install()` called once (verified call site — SessionInitializer step 5), no runtime mutation after. `UniverseHandler.__init__` confirmed exact literal signature `(*, bus, universe, feed, config)` (`universe_handler.py:209-216`) — zero `okx`/OKX identifiers anywhere in the class body (only in comments describing the absence of coupling). `set_venue_metadata(exchange)` collapses the two former setters (confirmed present, old ones absent). `cache_registration.py` confirmed to contain `class StrategyWarmupConsumer`, `def derive_warmup_depth`, `def register_strategy_warmup` — all present and wired into `session_initializer.py` (`register_strategy_warmup(engine.feed, ...)` called as step 2). `_LiveWarmupConsumer` confirmed removed from `live_trading_system.py` (grep = 0 definitions, only historical comments). **Note:** `.planning/REQUIREMENTS.md` still shows RUN-07's checkbox as unchecked (`- [ ] **RUN-07**`) and its traceability table row as "Pending" despite the artifact being complete and wired — this is a stale documentation marker (bookkeeping gap in REQUIREMENTS.md), not a code gap. Flagged as a WARNING for cleanup, does not affect the phase verdict. |
| 5 | `test_okx_inertness.py` stays green | ✓ VERIFIED | Re-run independently: 4 passed (extended from 3 in 06-06 to add the register-vs-build proof for `build_live_system`/`LiveRunner`/`WorkerSupervisor`/`ErrorPolicy`/`LiveRouteRegistrar`/`SessionInitializer`, then a 4th assertion added in 06-07 for the production-replay-free invariant). |
| 6 | TEST-01: replay harness moved OUT of `itrader` into `tests/`; production replay-free; paper re-points replay→OKX; `Test*` classes set `__test__=False`; `test_paper_parity` green | ✓ VERIFIED | `itrader/price_handler/providers/replay_provider.py` confirmed DELETED (file not found). `tests/support/replay_harness.py` confirmed present, containing `class TestLiveDataProvider`, `class TestDataPlugin`, `class TestRunner`, all with `__test__ = False` (grep-confirmed at lines 84/242/284). `grep -rn "run_paper_replay\|PAPER_PARITY_\|register('replay'\|ReplayDataProvider\|ReplayDataPlugin\|_replay_provider" itrader` → 0 matches (production fully replay-free). Data-provider map confirmed `{'okx': 'okx', 'paper': 'okx'}` at two sites (`for_exchange` + `build_live_system`). `TestRunner` never calls `.start()` (grep confirmed 0 matches in the harness file) — fail-fast by default per D-19. `test_paper_parity` re-run independently: 1 passed. Collection-safety test re-run independently: 2 passed. |

## Requirements Coverage

All 8 requirement IDs declared across the 7 plans (RUN-01, RUN-02, RUN-03, RUN-04 (×2 — extraction in 06-01, live-reuse in 06-05), RUN-05, RUN-06, RUN-07, TEST-01) map onto exactly one plan each (or two for RUN-04's extract-then-reuse split, which is expected). No orphaned requirements found for Phase 6 in `.planning/REQUIREMENTS.md`.

| Requirement | Plan | Status | Evidence |
| --- | --- | --- | --- |
| RUN-01 | 06-06 | ✓ SATISFIED | `build_live_system` is the sole construction path, confirmed |
| RUN-02 | 06-02, 06-06 | ✓ SATISFIED | `LiveRunner`/`WorkerSupervisor`/`ErrorPolicy` built (06-02) and wired (06-06) |
| RUN-03 | 06-06 | ⚠️ SATISFIED STRUCTURALLY, numeric target deferred per D-03 | See SC-3 above |
| RUN-04 | 06-01, 06-05 | ✓ SATISFIED | `wire_universe` extracted (06-01), reused by SessionInitializer (06-05) |
| RUN-05 | 06-05 | ✓ SATISFIED | `LiveRouteRegistrar` confirmed |
| RUN-06 | 06-04 | ✓ SATISFIED | `UniverseHandler` ctor confirmed |
| RUN-07 | 06-03 | ✓ SATISFIED (REQUIREMENTS.md checkbox stale — see note above) | `StrategyWarmupConsumer`/`derive_warmup_depth`/`register_strategy_warmup` confirmed |
| TEST-01 | 06-07 | ✓ SATISFIED | Replay harness relocation confirmed |

## Anti-Patterns Found

No debt markers (`TBD`/`FIXME`/`XXX`) found in any of the 11 files created/modified this phase (`universe_wiring.py`, `worker_supervisor.py`, `error_policy.py`, `live_runner.py`, `route_registrar.py`, `session_initializer.py`, `live_trading_system.py`, `universe_handler.py`, `cache_registration.py`, `replay_harness.py`, `paper_plugin.py`).

## Code Review Findings (06-REVIEW.md) — Assessed

Two WARNING-level findings from the prior code review were assessed against SC-1 per this task's instructions:

1. **WR-01 (tautological assert in `session_initializer.py:122-135`):** Confirmed by direct read — this guard derives `subscribed = list(members)` and then checks `subscribed` against `members`, which can never be false. **However, this is a SEPARATE, additional live-only guard in `SessionInitializer`, NOT the WR-03 desync assert that SC-1 requires.** The SC-1-required WR-03 assert lives inside the shared `wire_universe()` function (`universe_wiring.py`) and is genuine — it compares `set(membership)` (from `derive_membership`) against `set(instruments)` (from `derive_instruments`), two independently-computed sets that COULD diverge if either derivation function changes. That assert is confirmed present, shared, and non-tautological. **Verdict: SC-1 is satisfied** — the tautological guard is a documented, lower-value duplicate/forward-seam in a different location, correctly flagged in the review as a WARNING (fix recommended, not phase-blocking).
2. **WR-02 (`start()` dereferences possibly-`None` `_error_policy`/`_live_runner`):** Confirmed by direct read (lines 1030-1036). This is a real robustness gap if `LiveTradingSystem` is ever constructed outside `build_live_system`, but the class is documented factory-only and every construction site in the codebase and test suite goes through `build_live_system`/`for_exchange` (confirmed by grep — 0 residual direct constructions). Non-blocking quality issue, correctly scoped as a WARNING in the review.

Both findings are legitimate quality issues (worth a follow-up fix) but do not invalidate any of the six roadmap success criteria.

## Deviations Assessed (per task instructions)

| Deviation | Decision-backed? | Verdict |
| --- | --- | --- |
| 06-06: D-12 construction-time session-init flip deferred; facade lands ~1715 lines (not ~200) | Yes — D-03 (locked, pre-execution) explicitly defers the ~200-line target to P7 close | Accepted, not a gap |
| 06-06: `build_live_system` does not call `compose_engine` | Documented in SUMMARY with sound technical rationale (feed-type incompatibility); not contradicted by any locked decision | Accepted, not a gap — structural goal (one composition root) independently verified met |
| 06-REVIEW WR-01: tautological WR-03-labeled guard in `SessionInitializer` | Distinct from the SC-1-required assert (which is genuine); documented by executor as an intentional (if currently vacuous) forward-seam | Accepted as a non-blocking quality WARNING, not a gap against SC-1 |

## Human Verification Required

None. All must-have truths for this phase are structural/compositional claims (module/function existence, wiring, ordering, dead-code removal, byte-exact numeric oracle) that were verified directly by reading the code and independently re-running the gating tests — no runtime/UX/visual behavior requires human judgment for this phase.

## Gaps Summary

No blocking gaps. One documentation-only nit (REQUIREMENTS.md RUN-07 checkbox/traceability row not updated to reflect completion) is worth a quick fix but does not affect the phase verdict. SC-3's literal "~200-line facade" wording is not met at this phase close, but this is explicitly and correctly anticipated by the phase's own locked decision (D-03) as a P7-exit gate, not a P6-close gate — treating it as a gap would contradict the phase's own planning contract.

---

_Verified: 2026-07-13T14:03:14Z_
_Verifier: Claude (gsd-verifier)_
