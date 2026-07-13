---
phase: 06-liverunner-factory-facade-shrink
plan: 07
subsystem: trading_system
status: complete
tags: [TEST-01, replay-harness-relocation, D-16, D-18, D-19, D-20, D-21, D-22, paper-parity, code-motion]
requires:
  - "06-06: build_live_system + LiveSystemComponents + the deferred idempotency-guarded _initialize_live_session (this plan drops run_paper_replay's residual init call and relocates the driver)"
  - "venues/paper_plugin.py::PaperVenuePlugin (execution, D-20 — STAYS untouched) + venues/assemble.py + venues/registry.py (the data-provider injection seam)"
  - "tests/support/ (existing package: __init__ + fake_venue_connector + schema — the collision-safe home for the relocated harness)"
provides:
  - "tests/support/replay_harness.py — the WHOLE replay test-harness: TestLiveDataProvider / TestDataPlugin / TestRunner / PAPER_PARITY_* + build_paper_replay_system() helper (all Test* classes __test__=False)"
  - "build_live_system(spec, *, status_callback=None, data_plugins=None) — a generic, production-inert DATA-provider injection seam (a test fixture registers TestDataPlugin; production never does)"
  - "production paper re-points to the OKX live data feed ({'okx':'okx','paper':'okx'}) — the paper↔replay pairing survives ONLY in the test fixture (D-21)"
affects:
  - "P7 (SafetyController): consumes the now-replay-free ~facade baseline; the D-04 safety/reconcile/stream bodies stay untouched"
  - "any future OANDA/forex data provider: production paper could re-point to it (D-21 is not a deferred choice — today it is OKX)"
tech-stack:
  added: []
  patterns:
    - "Test-harness relocation as PURE code-motion, sliced LAST (after the RUN-04 extraction + factory/facade decomposition locked) so test_paper_parity is the continuous safety net (D-18)"
    - "Production-inert test-injection seam (data_plugins default None) — the paper↔replay pairing lives ONLY in a test fixture; production stays replay-free and greppable"
    - "pytest-collection opt-out via __test__ = False on every Test*-named NON-test class (D-22), proven by a fresh-subprocess --collect-only == 0-items guard under filterwarnings=['error']"
    - "Green-preserving commit resequencing: relocate+rewire-consumers BEFORE production-symbol removal, so paper-parity stays green after EACH commit (the SACRED gate)"
key-files:
  created:
    - tests/support/replay_harness.py
    - tests/unit/test_replay_harness_collection.py
  modified:
    - itrader/trading_system/live_trading_system.py
    - itrader/venues/paper_plugin.py
    - itrader/price_handler/providers/live_provider.py
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/trading_system/error_policy.py
    - itrader/trading_system/worker_supervisor.py
    - tests/integration/test_paper_parity.py
    - tests/integration/test_okx_inertness.py
    - tests/integration/conftest.py
    - tests/integration/test_halt_latch.py
    - tests/integration/test_live_paper_lifecycle.py
    - tests/integration/test_durable_halt.py
    - tests/integration/test_live_portfolio_durable_wiring.py
    - tests/integration/test_paper_restart_restore.py
    - tests/unit/venues/test_paper_plugin.py
    - tests/unit/venues/test_assemble.py
    - tests/unit/price/test_replay_provider.py
    - scripts/run_live_paper.py
  deleted:
    - itrader/price_handler/providers/replay_provider.py
decisions:
  - "TEST-01/D-18: the ENTIRE replay harness left itrader/ for tests/support/replay_harness.py — ReplayDataProvider→TestLiveDataProvider, ReplayDataPlugin→TestDataPlugin, run_paper_replay→TestRunner, PAPER_PARITY_* relocated; production is replay-free (greps clean)"
  - "D-20: paper EXECUTION venue (PaperVenuePlugin + SimulatedExchange + SimulatedAccount) UNTOUCHED — paper_plugin.py SPLIT: PaperVenuePlugin stays, the replay DATA plugin leaves"
  - "D-21: production paper re-points to the OKX live data feed ({'okx':'okx','paper':'okx'}); register('replay',...) dropped from production; the paper↔replay pairing survives ONLY in the test fixture via the data_plugins injection seam"
  - "D-19: TestRunner is fail-fast BY DEFAULT — it drives event_handler.process_events() directly and NEVER calls start()/installs the publish-and-continue policy (grep '.start()' in the harness == 0)"
  - "D-22: every Test*-named class (TestRunner/TestLiveDataProvider/TestDataPlugin) sets __test__=False; a fresh-subprocess --collect-only guard proves 0 items collected under filterwarnings=['error']"
  - "DEVIATION (D-16/D-12): TestRunner is BEHAVIOR-PRESERVING — it calls system._initialize_live_session() before its per-bar drive rather than 'dropping the session-init line', because 06-06 kept the D-12 construction-time flip DEFERRED (completing it breaks the add-strategy-after-construction contract across the paper test fleet). The idempotency guard is retained"
  - "DEVIATION (D-21 blast radius, Rule 3): flipping paper→okx makes bare for_exchange('paper') require OKX creds, breaking ~8 offline paper test sites; added a generic data_plugins seam + build_paper_replay_system() helper and rewired ALL offline paper consumers (conftest, halt_latch, live_paper_lifecycle, durable_halt, live_portfolio_durable_wiring, paper_restart_restore, run_live_paper.py) — files the plan did not enumerate"
metrics:
  duration: "~70 min"
  completed: "2026-07-13"
  tasks: 3
  files: 21
---

# Phase 6 Plan 07: Replay-Harness Relocation to tests/ (TEST-01) Summary

Relocated the ENTIRE replay test-harness out of the `itrader` production package into `tests/support/replay_harness.py` (TEST-01, pulled forward from P12) as PURE code-motion, with `test_paper_parity` green CONTINUOUSLY. The offline replay DATA apparatus — `ReplayDataProvider` → **`TestLiveDataProvider`**, `ReplayDataPlugin` → **`TestDataPlugin`**, `run_paper_replay` → **`TestRunner`**, plus the `PAPER_PARITY_*` window anchor — now lives in `tests/`; every `Test*`-named class carries `__test__ = False` (D-22). Production `paper` re-points from the replay feed to the **OKX live data feed** (`{'okx':'okx','paper':'okx'}`, D-21); the paper↔replay pairing survives ONLY in the test fixture via a new generic, production-inert **`data_plugins` injection seam**. The paper EXECUTION venue (`PaperVenuePlugin` + `SimulatedExchange` + `SimulatedAccount`) is a REAL live production mode and stays UNTOUCHED (D-20). **Every milestone gate held CONTINUOUSLY: paper-parity green after each commit, backtest oracle byte-exact `134 / 46189.87730727451`, OKX inertness green (re-authored to assert production registers no `'replay'` provider), collection-safety proven, full suite 2128 passed / 6 skipped, `mypy --strict` clean.**

## What Was Built (3 green-preserving commits)

### Commit 1 (`aded9733`) — relocate harness + injection seam + rewire consumers
- **`tests/support/replay_harness.py`** (NEW): `TestLiveDataProvider` (verbatim `ReplayDataProvider` body, renamed, `__test__=False`), `TestDataPlugin` (verbatim `ReplayDataPlugin`, `__test__=False`, `build_provider` stashes `self.provider` for Landmine-2 handle capture), `TestRunner` (verbatim `run_paper_replay` drive — drift asserts + session-init + steps 2-3, fail-fast by default, `__test__=False`), the four `PAPER_PARITY_*` constants, and a `build_paper_replay_system()` helper returning `(system, provider)`.
- **`build_live_system(spec, *, status_callback=None, data_plugins=None)`**: added a generic DATA-provider injection seam (registers injected plugins AFTER the production ones). `for_exchange` threads `data_plugins` + flipped its default map to `paper→okx`.
- **Rewired all offline paper consumers** to `build_paper_replay_system` (+ `TestRunner` for the parity test): `test_paper_parity`, `test_halt_latch`, `test_live_paper_lifecycle`, `test_durable_halt`, `test_live_portfolio_durable_wiring`, `test_paper_restart_restore`, the `conftest` remove-policy factory, and `scripts/run_live_paper.py`. Repointed `test_replay_provider.py` to `TestLiveDataProvider`.

### Commit 2 (`8b58747c`) — make production replay-free (D-18/D-20/D-21)
- **DELETED** `itrader/price_handler/providers/replay_provider.py`.
- **`paper_plugin.py` SPLIT**: `PaperVenuePlugin` (execution) stays UNTOUCHED; `ReplayDataPlugin` + `PAPER_PARITY_*` REMOVED; docstring updated.
- **`build_live_system`**: dropped `ReplayDataPlugin` import + `register('replay', ...)`; flipped the internal venue_spec map to `{'okx':'okx','paper':'okx'}` (D-21).
- **`live_trading_system.py`**: removed `run_paper_replay`, the `PAPER_PARITY_*` constants block, `self._replay_provider`, `LiveSystemComponents.replay_provider` + its else-branch. Kept `_initialize_live_session` + the idempotency guard (both `start()` and `TestRunner` call it).
- **Softened doc refs** in `live_provider.py` / `live_bar_feed.py` / `error_policy.py` / `worker_supervisor.py` so NO production module names the relocated replay concretion (grep clean).
- **Repointed** `test_paper_plugin.py` (drop replay-plugin assertions, assert `paper_plugin` now defines ONLY `PaperVenuePlugin`) + `test_assemble.py` (paper registry uses the relocated `TestDataPlugin`); **re-authored** `test_okx_inertness.py` with the stronger post-D-21 invariant (production `build_live_system` registers NO `'replay'` provider, source-inspected + CI-safe).

### Commit 3 (`1df82e3d`) — collection-safety guard (D-22 / Wave 0)
- **`tests/unit/test_replay_harness_collection.py`** (NEW): asserts every `Test*` harness class sets `__test__=False` AND a fresh-subprocess `pytest --collect-only` over the harness collects ZERO items (exit 5, no `PytestCollectionWarning`) — proving the opt-out holds under `filterwarnings=["error"]`.

## Milestone Gate Results (recorded per critical_gate)

- **Paper-parity:** `tests/integration/test_paper_parity.py` — **1 passed** after EACH of the 3 commits (verified per-commit; pure code-motion, byte-identical diff, driven by `TestRunner` + the `TestDataPlugin` fixture).
- **Backtest oracle byte-exact:** `tests/integration/test_backtest_oracle.py` — **3 passed**, byte-exact **134 / `46189.87730727451`** (final_equity/final_cash per `tests/golden/REFREEZE-M5C-DECIMAL.md`).
- **OKX import-inertness:** `tests/integration/test_okx_inertness.py` — **4 passed** (was 3; +1 new invariant test asserting production registers no `'replay'` data provider + paper→okx). The re-authored assertion is STRONGER, not weaker.
- **Collection-safety:** `tests/unit/test_replay_harness_collection.py` — **2 passed** (0 items collected from the harness under `filterwarnings=["error"]`).
- **Full suite:** `poetry run pytest tests` — **2128 passed, 6 skipped** (the 6 skips are OKX-demo-credential-gated live/e2e suites, expected without creds); `filterwarnings=["error"]` green.
- **mypy --strict:** clean — `Success: no issues found in 249 source files` (one file fewer — replay_provider.py deleted).
- **Zero new dependencies.**
- **Indentation:** all edited files matched per-file (harness 4-SPACE matching the price_handler/venues donors; live_trading_system.py 4-SPACE; test files 4-SPACE) — never normalized.

## Grep / Structural Acceptance

- `grep -rn "run_paper_replay|PAPER_PARITY_|register('replay'|ReplayDataProvider|ReplayDataPlugin|_replay_provider" itrader` → **0** (production fully replay-free).
- `class PaperVenuePlugin` in `paper_plugin.py` → **1** (D-20 intact); `PAPER_PARITY_`/`ReplayDataPlugin` in it → **0**.
- `'paper': 'okx'` in `live_trading_system.py` → **2** (for_exchange + build_live_system maps, D-21).
- `.start()` in `tests/support/replay_harness.py` → **0** (TestRunner fail-fast by default, D-19).
- No test imports a relocated production symbol (`from ...replay_provider` / `import ReplayDataProvider|ReplayDataPlugin`) → **0**.

## Deviations from Plan

### 1. [D-16/D-12 — architectural, gate-preserving] TestRunner is behavior-preserving; the construction-time session-init flip NOT completed
- **Found during:** Task 2 design (the plan's D-16 says "drop the session-init line 1490 — the factory already inits the session at construction, D-12").
- **Issue:** 06-06 explicitly DEFERRED the D-12 construction-time session-init flip (its Deviation 1): completing it runs `wire_universe` with zero strategies (the paper tests add strategies AFTER construction → empty universe → zero paper trades → paper-parity vacuous-fail) and breaks the pervasive monkeypatch-`_initialize_live_session`-before-`start()` contracts across ≥6 integration tests. So the factory does NOT init at construction — dropping TestRunner's session-init call would leave the session uninitialized (zero trades, parity RED).
- **Decision:** `TestRunner.run()` KEEPS the session-init step — it calls `system._initialize_live_session()` before the per-bar drive (behavior-identical to the old `run_paper_replay`), and the idempotency guard is RETAINED (both `start()` and `TestRunner` call it). This is PURE behavior-preserving code-motion (the critical_gate's explicit escape: "if the plan is purely code-motion, keep it behavior-preserving and do NOT introduce the flip"). The D-12 construction-time flip stays deferred.
- **Files:** `tests/support/replay_harness.py`, `itrader/trading_system/live_trading_system.py`. **Commits:** `aded9733`, `8b58747c`.

### 2. [Rule 3 — blocking] D-21 blast radius: rewired ~8 offline paper test sites the plan did not enumerate
- **Found during:** Task 1/2 (grep of `for_exchange("paper")` call sites + empirical build check).
- **Issue:** Flipping production `paper→okx` (D-21) makes a bare `LiveTradingSystem.for_exchange("paper")` build the OKX data provider → `OkxSettings()` raises `ValidationError` (missing `OKX_API_*`) offline. ~8 offline paper test sites (conftest remove-policy factory, `test_halt_latch`, `test_live_paper_lifecycle`, `test_durable_halt`, `test_live_portfolio_durable_wiring`, `test_paper_restart_restore`) + `scripts/run_live_paper.py` build paper bare and would have reddened — but the plan's `files_modified` did not list them.
- **Fix:** Added a GENERIC, production-inert `data_plugins` injection seam to `build_live_system`/`for_exchange` + a `build_paper_replay_system()` helper, and rewired ALL offline paper consumers to it (they now inject the `TestDataPlugin` and select `data_provider="replay"`). Production stays replay-free; the paper↔replay pairing lives ONLY in the fixture. Full suite green.
- **Files:** `tests/integration/conftest.py`, `test_halt_latch.py`, `test_live_paper_lifecycle.py`, `test_durable_halt.py`, `test_live_portfolio_durable_wiring.py`, `test_paper_restart_restore.py`, `scripts/run_live_paper.py`, `itrader/trading_system/live_trading_system.py`. **Commit:** `aded9733`.

### 3. [Process] Task→commit resequencing to preserve continuous paper-parity green
- **Found during:** Commit planning.
- **Issue:** The plan's Task 1 deletes production replay BEFORE Task 2 rewires the tests — which would redden paper-parity between commits, violating the SACRED "green after EACH commit" gate.
- **Fix:** Resequenced into 3 green-preserving commits: (1) relocate harness + seam + rewire ALL consumers (production replay still present as a safety net), (2) remove production replay symbols (tests already point at the harness), (3) collection-safety. The FINAL state satisfies every per-task acceptance criterion; each intermediate commit is green.
- **Files:** all. **Commits:** `aded9733`, `8b58747c`, `1df82e3d`.

### 4. [Rule 3 — blocking] Softened replay doc refs in error_policy.py + worker_supervisor.py
- **Found during:** Task 2 acceptance grep (`run_paper_replay` in `itrader` must be 0).
- **Issue:** `error_policy.py` and `worker_supervisor.py` docstrings named `run_paper_replay` — not in the plan's `files_modified`, but they trip the production-replay-free grep.
- **Fix:** Reworded both to reference the offline test driver (`TestRunner`, never calls `start()`) instead. Behavior untouched (docstrings only).
- **Files:** `itrader/trading_system/error_policy.py`, `itrader/trading_system/worker_supervisor.py`. **Commit:** `8b58747c`.

## Known Stubs

None. The relocated harness is verbatim code-motion of live production code; `build_paper_replay_system` + `data_plugins` are a real, exercised injection seam (proven by the full paper test fleet + parity gate). Production paper→okx wiring: the OKX data provider is BUILT and wired to the feed for a real paper run; `start()`'s warmup/subscribe stays gated on the exec-venue discriminator (`bundle.connector`), so a real paper→okx streaming run is unchanged from the prior paper wiring shape (D-20 — data-provider SELECTION only, not execution logic). No behavioral stub.

## Threat Flags

None new. The plan threat register held: T-06-17 (code-motion silently changing the parity comparand) — drift asserts + steps 2-3 moved VERBATIM into `TestRunner`, paper-parity byte-identical + green CONTINUOUSLY; T-06-18 (Test*-class auto-collection DoS) — `__test__=False` + the 0-items collection-safety guard; T-06-19 (TestRunner reading a facade attr that no longer exists) — the handle is a constructor arg from the fixture's `TestDataPlugin.provider` (Landmine 2), never `system._replay_provider` (which is deleted); T-06-20 (editing paper EXECUTION logic while removing DATA) — `PaperVenuePlugin` untouched, grep-asserted; T-06-SC — zero new dependencies.

## Notes for Downstream (P7+)

- Production is now replay-free — the P7 SafetyController inherits a clean facade with no dead replay apparatus.
- The D-12 construction-time session-init flip remains DEFERRED (06-06 + this plan): a future plan that reworks the paper test-flow to pass strategies via the spec (mirroring `build_backtest_system`) can complete it. `TestRunner`/`build_paper_replay_system` are the natural seam to add spec-strategies before session init.
- `build_live_system`'s `data_plugins` seam is a reusable, production-inert test-injection point for any future offline data-provider double.

## Self-Check: PASSED
