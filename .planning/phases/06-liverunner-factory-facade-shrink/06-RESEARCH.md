# Phase 6: LiveRunner + Factory + Facade Shrink - Research

**Researched:** 2026-07-13
**Domain:** Brownfield structural refactor (Python 3.13) — live composition-root extraction + byte-exact universe-wiring seam + test-harness relocation
**Confidence:** HIGH (all findings are direct code reads / greps of the current tree; zero external dependencies in scope)

## Summary

This is a **brownfield structural refactor**, not a feature. Every design decision (form, home, names,
cut-lines, sequencing) is already locked in `06-CONTEXT.md` as D-01..D-23. This research is **additive and
planner-facing**: it (1) verifies the donor line numbers CONTEXT cites against the live tree, (2) surfaces
the one large piece of hidden coupling the donor-line survey did not enumerate — **the ~45 direct
`LiveTradingSystem(exchange=...)` construction sites** that D-09's "pure-injection `__init__`" will break —
and (3) specifies the exact validation gates + safe plan ordering.

**Code-state verdict:** the CONTEXT donor citations are **accurate**. All method/line ranges verified within
±10 lines; the two minor drifts (`__init__` starts at `:144` not `~:135`; the D-23 `bus=self.global_queue`
wiring is at `:525` not `:236`, where `:236` is the raw `queue.Queue()` it threads) are cosmetic and do not
change any task. `cache_registration.py` (RUN-07's target module) and `assemble_venue` (D-09's promoted call)
**already exist** — P5 built the seams and their docstrings explicitly name `build_live_system` /
`SessionInitializer` as the P6 consumer. None of the P6 target symbols (`build_live_system`, `LiveRunner`,
`SessionInitializer`, `LiveRouteRegistrar`, `WorkerSupervisor`, `wire_universe`) exist yet — clean greenfield
inside a wired codebase.

**Primary recommendation:** Slice RUN-04 (`wire_universe` extraction) as its OWN oracle-gated plan FIRST;
then RUN-01/02/03/05/06/07 (the live factory/runner/facade/routes/handler decomposition, including the
`LiveTradingSystem(exchange=...)` → factory call-site migration) as a middle group; then TEST-01 (replay
relocation) LAST as pure code-motion with `test_paper_parity` green continuously. Do not remake the ruler
(RUN-04) and the measured thing (TEST-01) in one step.

<user_constraints>
## User Constraints (from CONTEXT.md — reference by tag, NOT reproduced)

Per orchestrator directive, the 23 locked decisions are NOT reproduced here. The planner MUST read
`06-CONTEXT.md` in full and honor every D-NN. Compact index:

### Locked Decisions (planner MUST honor)
| Tag | Locks | Oracle risk |
|-----|-------|-------------|
| D-01 | `wire_universe` INCLUDES `strategies_handler.set_universe` (adds a call to backtest path — inert by construction via `Universe` construction-time `Readiness.READY`) | **HIGH — per-PLAN gated** |
| D-02 | Form = free function `wire_universe(engine) -> Universe` in `trading_system/universe_wiring.py` (NOT `universe/`) | — |
| D-03 | `~200-line facade` is a **milestone-EXIT gate verified at P7 close**, NOT a P6-close gate; P6 lands a ~600-700 line interim facade. **Planner/verifier MUST NOT mark RUN-03 incomplete for a ~650-line facade.** | — |
| D-04 | P6 does NOT touch safety/reconcile/stream method BODIES (P7 extracts from unchurned baseline) | — |
| D-05 | `WorkerSupervisor` extracted as its own class in P6; `LiveRunner` composes it | — |
| D-06 | `LiveRunner` owns the drain loop (replaces `_event_processing_loop`); `queue_timeout`/`max_idle_time` from config/spec | — |
| D-07 | Minimal injected `ErrorPolicy` = `_publish_and_continue` moved verbatim (WR-06 guard kept); full formalization is P8 | — |
| D-08 | `LiveRunner` takes an injected dispatch-gate callback → facade `_dispatch_live` in P6 (body untouched); P7 repoints to SafetyController | — |
| D-09 | `build_live_system(spec)` is the ONLY construction path; facade `__init__` = pure injection | **surface risk — see Hidden Coupling** |
| D-10 | `LiveRouteRegistrar` = one central declarative route table at construction; P6 registers BUSINESS routes only | — |
| D-11 | `UniverseHandler.__init__(bus, universe, feed, config)`; `set_venue_metadata` collapses `set_symbol_validator`+`set_precision_resolver`; `set_freeze_gate` interim callable; 4 read-model setters stay | — |
| D-12 | `SessionInitializer` is a distinct class run at CONSTRUCTION time | ordering — see OQ-1 |
| D-16 | `run_paper_replay` → `TestRunner`: drop line 1490, steps 2-3 (`:1499-1524`) verbatim | — |
| D-17 | Shape a NAMED depth-computation boundary in `cache_registration.py`; K-computation deferred | — |
| D-18/D-20/D-21/D-22 | TEST-01 relocation: whole replay harness → `tests/`; paper EXECUTION venue stays production; paper data feed re-points to OKX (`{'okx':'okx','paper':'okx'}`); `__test__ = False` on `Test*` classes | **parity gate must stay green** |
| D-19 | `TestRunner` is fail-fast BY DEFAULT (drives `process_events()` directly, never installs the live policy) | — |
| D-23 | P6 wires live onto `PriorityEventBus`; CONTROL routes populate in P7/P9 (NOT registered in P6) | inert (no oracle) |

### Deferred / OUT OF SCOPE (downstream must NOT pull forward)
- SafetyController / ReconciliationCoordinator / StreamRecoveryHandler + CONTROL routes + pre-trade throttle → **P7**
- Full ErrorPolicy formalization (EventHandler-construction injection, fail-fast/publish split, CF-1 breaker) → **P8**
- CF-10 K-computation + per-symbol ring sizing → **future roster**
- TEST-02/03/04 (live-smoke, config-restart, multi-portfolio attribution) → **P12**

### Claude's Discretion
- Plan/wave slicing across RUN-01..07 (subject to the byte-exact + inertness gates); RUN-04 isolated on its own.
- Exact module paths / class names / signatures beyond the pins; `error_policy` object shape; the
  "components bundle" shape the facade `__init__` receives; whether `set_venue_metadata` takes the exchange
  or a metadata view; the warmup-depth function's exact name/home within `cache_registration.py`.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support (verified) |
|----|-------------|------------------------------|
| RUN-01 | `build_live_system(spec)` live factory/composition root | `assemble_venue` (`venues/assemble.py`) + `EngineContext` (`:491`) + `compose_engine` (`compose.py:114`) already exist and are called from `__init__` today (`:524-546`); factory relocates the CALL. `build_live_system` does not exist yet. |
| RUN-02 | `LiveRunner` owns drain loop + injected `ErrorPolicy` + worker supervision | `_event_processing_loop` (`:1526-1608`) + `_publish_and_continue` (`:622`, WR-06 guard) + `_run_poll_timer` (`:1852-1873`) are the intact donors. |
| RUN-03 | Facade shrink; drop `print_status`/`get_statistics`; shed `exchange`/`to_sql`/`queue_timeout`/`max_idle_time` | Confirmed: all 4 params live at `__init__` `:146-149`; `get_statistics` `:2086`, `print_status` `:2101`. **~200-line = P7-exit gate (D-03), not P6.** |
| RUN-04 | Shared `UniverseWiring` extracted byte-exact, incl. WR-03 assert | Donor `backtest_runner._initialise_backtest_session` `:50-131` verified verbatim; WR-03 assert `:84-90`. **Oracle-gated PLAN.** |
| RUN-05 | `LiveRouteRegistrar` declarative routes; backtest base-only | `EventHandler` single `_routes` literal is the pattern; live routes composed at `_initialize_live_session:1401-1413`. |
| RUN-06 | `UniverseHandler` first-class, explicit deps, zero OKX coupling | ctor `:160-227` + 7 `set_*` seams (`:231-289`) verified; `set_symbol_validator:248`/`set_precision_resolver:252` collapse to `set_venue_metadata`. |
| RUN-07 | `_LiveWarmupConsumer` → `StrategyWarmupConsumer` in `cache_registration.py`; depth-hint seam shaped | `_LiveWarmupConsumer` = `@dataclass(frozen=True)` `:120-132`; registration `:1289-1292` computes `max(s.warmup, default=1)` — the exact depth to extract. **`cache_registration.py` already exists.** |
| TEST-01 | Whole replay harness → `tests/`; production replay-free; paper→OKX feed | `run_paper_replay:1422-1524`; `ReplayDataProvider` (`replay_provider.py`, 213 lines); `ReplayDataPlugin` (`paper_plugin.py:90`); `data_provider` map `:535`; `register('replay')` `:517`. All verified. |

</phase_requirements>

## Code-State Verification (donor line drift audit)

All ranges read directly from the current tree on branch `v1.8/phase-6-live-runner`.
Legend: ✅ = matches CONTEXT within tolerance; ⚠ = drift worth a corrected pin.

| Donor | CONTEXT cite | Actual | Status |
|-------|--------------|--------|--------|
| `backtest_runner._initialise_backtest_session` | `:50-131` | `:50-131` (method body `50→131`) | ✅ exact |
| — WR-03 desync assert | `:84-90` | `:84-90` | ✅ exact |
| — set_universe exchange/order/portfolio | `:96-98`/`:103`/`:110` | `:96-98`/`:103`/`:110` | ✅ exact |
| — feed.bind | `:113` | `:113` | ✅ exact |
| — ping-grid / precompute (backtest's own post-step) | `:119-127`/`:130-131` | `:119-127`/`:130-131` | ✅ exact |
| `compose.py` `Engine` holder + `compose_engine` | `:81-114` | `@dataclass Engine :81`, `def compose_engine :114` | ✅ exact |
| `universe.py` `Universe.__init__` / `is_ready` | `:99-177` | `__init__ :99`, `is_ready :165` | ✅ |
| — construction-time `Readiness.READY` | `:106/:127` | docstring `:106`, code `:127` | ✅ exact (the D-01 inertness lever) |
| `strategies_handler.set_universe` + readiness gate | `:109-117` + `:214` | `:109-117` + `:214` | ✅ exact |
| `universe_handler` ctor + 7 `set_*` seams | `:160-278` | ctor `:160-227`; seams `:231/235/248/252/263/267/278` | ✅ (7 seams confirmed) |
| `live` `__init__` | `~:135-620` | `def __init__ :144`; ends `:620` | ⚠ **starts `:144`, not `:135`** |
| — shed params `exchange`/`to_sql`/`queue_timeout`/`max_idle_time` | — | `:146`/`:147`/`:148`/`:149` (all present; `status_callback :150` STAYS) | ✅ |
| `_publish_and_continue` (D-07 donor) | `:622` | `:622` | ✅ exact |
| `halt`/`_is_halted`/`reset_halt`/`pause_submission` (D-04 untouched) | ~`:749-1073` | `749`/`815`/`820`/`868` | ✅ (bodies stay put) |
| `_dispatch_live` (D-08 gate) | `:1073` | `:1073` | ✅ exact |
| `_update_status` (D-04 untouched) | ~region | `:1117` | ✅ |
| `_initialize_live_session` (live donor) | `:1246-1420` | `:1246`→`:1421` | ✅ exact |
| — warmup register / UniverseHandler / routes | `:1289`/`:1348`/`:1401-1413` | `:1289`/`:1349`/`:1401-1413` | ✅ (UniverseHandler `:1349`, off-by-1) |
| `run_paper_replay` (TEST-01) | `:1422-1524`, drop `:1490`, steps 2-3 `:1499-1524` | `:1422`; `:1490` = `self._initialize_live_session()`; loop `:1499-1500` | ✅ exact |
| `_event_processing_loop` → LiveRunner | `:1526-1608` | `:1526`→`:1608` | ✅ exact |
| `start()` monkeypatch (D-19 boundary) | `:1665` | `event_handler._on_handler_error = self._publish_and_continue` at ~`:1665` | ✅ (the fail-fast-vs-live boundary is here) |
| `_run_poll_timer` → WorkerSupervisor | `:1852-1873` | `:1852` | ✅ exact |
| `get_statistics`/`print_status` (dropped) | `:2086`/`:2101` | `:2086`/`:2101` | ✅ exact |
| `_LiveWarmupConsumer` | `:121-133` | `@dataclass(frozen=True) :120`, class `:121-132` | ✅ |
| data-provider map + `register('replay')` (D-21) | `:517`/`:535` | `:517` register, `:535` `{'okx':'okx','paper':'replay'}` | ✅ exact |
| D-23: live on raw queue (not PriorityEventBus) | `bus=self.global_queue` `:236` | `self.global_queue = queue.Queue()` at **`:236`**; `bus=self.global_queue` threaded into `EngineContext` at **`:525`** | ⚠ **two distinct lines** — substance correct (live never migrated off raw `queue.Queue`); the `bus=` wiring is `:525`, the raw-Queue construction is `:236` |
| `full_event_handler._on_handler_error` default fail-fast | `:156-171` | `def _on_handler_error :156`, bare `raise :171` | ✅ exact |

**Bottom line:** the donor survey is trustworthy. Build tasks against these pins; adjust only the two ⚠ rows.

## Hidden Coupling & Landmines (NOT in the CONTEXT donor survey)

### LANDMINE 1 (HIGH) — ~45 direct `LiveTradingSystem(exchange=...)` construction sites
D-09 makes the facade `__init__` **pure injection** (takes pre-built collaborators / a components bundle) and
RUN-03 **sheds the `exchange` param**. Every existing construction of the form `LiveTradingSystem(exchange="paper"|"okx"|"binance")`
therefore breaks. Verified surface:
- **22 test files, 43 call sites** (`grep -rE "LiveTradingSystem\(exchange" tests` → 43).
  Heaviest: `test_live_system_okx_wiring.py` (12), `test_live_portfolio_durable_wiring.py` (3),
  `test_store_live_drive.py` (3), plus `integration/conftest.py:358` (the shared `paper` fixture reused
  by many integration tests).
- **2 production script sites:** `scripts/run_live_paper.py:93` (paper), `:126` (okx).
- **1 barrel export:** `trading_system/__init__.py:5` (import only — re-export the facade + add `build_live_system`).
- **1 doc string** referencing the idiom: `live_trading_system.py:1445`.

**Implication for the planner:** this is the single largest task-surface in the phase and it is NOT in the
CONTEXT donor list. The planner must explicitly choose ONE migration strategy and scope it:
1. Migrate all 45 sites to `build_live_system(spec)` (large but honest to D-09), OR
2. Keep a thin back-compat classmethod (e.g. `LiveTradingSystem.for_exchange(exchange)` delegating to the
   factory) so tests change minimally — but note RUN-03 explicitly removes the `exchange` **`__init__` param**,
   so any shim lives on the factory/classmethod, not `__init__`.

Whichever is chosen, `integration/conftest.py:358` (the `paper` fixture) is the highest-leverage single
edit — fixing it repairs the widest swath of integration tests. Recommend the factory-migration touches
land in the SAME plan(s) that shrink the facade, and that this call-site sweep be sized as its own
sub-task with its own green-suite gate.

### LANDMINE 2 (MEDIUM) — `_replay_provider` handle threads through `run_paper_replay`
`run_paper_replay` reads `self._replay_provider._store` / `._symbol` / `._timeframe` /
`.iter_closed_bars()` / `.replay_bar()` (`:1454-1500`). The attribute is set at `:571`
(`self._replay_provider = provider`) inside the data-provider wiring, default `None` at `:470`.
Since D-21 removes the replay provider from production (`paper`→OKX), **the relocated `TestRunner` must
obtain this handle from the test fixture's `TestDataPlugin`, not from a facade attribute.** The planner's
TEST-01 plan must carry this handle explicitly (constructor arg to `TestRunner`) rather than assume
`system._replay_provider` still exists.

### LANDMINE 3 (LOW, de-risked) — `wire_universe` (feed.bind) vs warmup-register ordering
`wire_universe` ends with `feed.bind` (backtest `:113`; live `:1291`). In the current live donor the
warmup consumer is registered (`:1289`) BEFORE `feed.bind` (`:1291`). D-12 sequences SessionInitializer as
`wire_universe` (which does bind) → THEN register warmup — inverting that order. **This is SAFE:**
`LiveBarFeed` creates rings LAZILY at first `_deliver` (`deque(maxlen=self.cache_capacity())`,
`live_bar_feed.py:383/625`), and `cache_capacity()` reads `derive(self._raw_bar_consumers)` at CALL time
(`base.py:125`) — `bind` does NOT snapshot capacity. Warmup FETCH depth is also read at warmup time
(`:283`), which runs in `start()` I/O AFTER construction. So as long as `register_strategy_warmup` runs at
construction (it does, per D-12), the capacity is correct by the time any bar is delivered. Flagged so the
planner does not "fix" the order back and does not treat it as a byte-exact risk (it is live-only, oracle-dark).

### LANDMINE 4 (LOW) — RUN-07 concept collision in `cache_registration.py`
`cache_registration.py` ALREADY exposes `derive`/`derive_required_depths`/`RawBarConsumer`/`NEWEST_BAR_ONLY`
— but its docstring is emphatic that capacity keys off **raw-bar history consumers, NOT indicator warmup**
(indicators self-buffer under Model B). RUN-07's `StrategyWarmupConsumer` + `register_strategy_warmup`
computes `max(strategy.warmup)` — a **warmup** concern layered into the same file. `_LiveWarmupConsumer`
already implements the `RawBarConsumer` Protocol (declares `required_history_depth`), so the two coexist by
construction, but the planner should name the new depth function distinctly (e.g.
`derive_warmup_depth`) so it is not conflated with `derive` (the raw-history ladder). D-17's "named,
replaceable warmup-depth function" is exactly this new function.

### Established P5 groundwork the planner can lean on (verified)
- `venues/assemble.py` docstring: *"...used by build_live_system — the logic does not move again."* — the
  `assemble_venue(ctx, spec, connectors)` seam is ready; `build_live_system` relocates the call from
  `__init__:546`.
- `venues/lifecycle.py:15,73`: comments already mark where `SessionInitializer` steps hook after connector connect.
- `test_okx_inertness.py:84,155`: already carries a comment anticipating `build_live_system` (P6) and
  imports `PaperVenuePlugin, ReplayDataPlugin` — the gate is pre-shaped for the new surface.

## Runtime State Inventory (relocation/refactor phase)

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys/collections embed the relocated class names. `TestRunner`/`TestLiveDataProvider`/`TestDataPlugin` are pure in-process test infra. | none |
| Live service config | None — no external UI/DB config references `run_paper_replay`/`ReplayData*`. Production `paper`↔`replay` pairing is code-level only (`:535`), retargeted to OKX in-code (D-21). | code edit only |
| OS-registered state | None. | none |
| Secrets/env vars | None new. OKX demo creds (`OKX_API_*`) already used by the live feed the `paper` mode re-points to (D-21) — key names unchanged. | none |
| Build artifacts | Stale `__pycache__` for relocated modules: `tests/integration/__pycache__/test_paper_parity.*.pyc`, `tests/unit/price/__pycache__/test_replay_provider.*.pyc`, and any `itrader/price_handler/providers/__pycache__/replay_provider.*.pyc` after the source leaves `itrader/`. | delete stale `.pyc` after moving files (else import shadows the moved module) |
| Import/reference coupling | `paper_plugin.py:103` (lazy import of `ReplayDataProvider`), `paper_plugin.py:498` in live (`from ...paper_plugin import PaperVenuePlugin, ReplayDataPlugin`), doc refs `live_provider.py:15`, `live_bar_feed.py` replay comments; test refs in `test_assemble.py`, `test_paper_plugin.py`, `test_replay_provider.py`, `test_paper_parity.py`, `test_okx_inertness.py:155` | repoint all imports to the relocated `tests/` classes; `test_okx_inertness.py:155` import of `ReplayDataPlugin` must move to whatever the fixture exposes (it currently asserts inertness over that plugin) |

## Validation Architecture

> Nyquist validation is ENABLED. This phase is oracle-sensitive; the gates below are load-bearing.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (installed 9.0.3 per `.pyc` names); `testpaths=["tests"]`; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run (per task) | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` |
| Full suite | `make test` (⚠ aborts in worktrees on missing `.env`; use `poetry run pytest tests` there — MEMORY: worktree-make-test-env-abort) |

### Phase Requirements → Verifying Signal
| Req | Verifying signal(s) | Command | Kind |
|-----|--------------------|---------|------|
| RUN-04 | **Byte-exact oracle** `134 / 46189.87730727451` (`check_exact=True`) + determinism double-run | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` run **twice**, assert identical | **per-PLAN gate ON the `wire_universe` plan** |
| RUN-01/02/03/05/06 | **Inertness** — live decomposition imports no `ccxt.pro` on backtest path | `poetry run pytest tests/integration/test_okx_inertness.py -x -q`; extend register-vs-build to cover the new `build_live_system`/`LiveRunner`/registrar surface | continuous gate |
| RUN-01..07 (live behavior) | **Paper-parity** — must stay green CONTINUOUSLY | `poetry run pytest tests/integration/test_paper_parity.py -x -q` | continuous gate |
| TEST-01 | Paper-parity green through relocation (pure code-motion) + `Test*` classes not collected | parity command above + `poetry run pytest tests/unit/price -q` (relocated provider tests) | gate on the LAST plan |
| all | `mypy --strict` on new modules in strict scope | `poetry run mypy itrader` | per-plan |
| all | `filterwarnings=["error"]` green (esp. `PytestCollectionWarning` for `Test*` classes → set `__test__ = False`, D-22) | full/targeted suite | per-plan |

### Structural-only requirements (verified at P6 close, NOT by a numeric gate)
- **RUN-03 `~200-line facade`** is a **milestone-EXIT gate verified at P7 close** (D-03). At P6 close verify
  STRUCTURE: `build_live_system` owns the wiring; `LiveRunner` owns the loop; `__init__` sheds the 4 params;
  `print_status`/`get_statistics` deleted; session-init → `wire_universe`/`SessionInitializer`; routes →
  `LiveRouteRegistrar`. **The planner/verifier MUST NOT fail RUN-03 for a ~600-700 line interim facade.**
- **D-23 PriorityEventBus** is inert without CONTROL events (BUSINESS tier + monotonic `seq` = strict FIFO);
  no oracle/behavior signal at P6 — verify only that live constructs `PriorityEventBus` and CONTROL routes
  are NOT registered.

### Determinism / oracle mechanics (RUN-04 plan)
- The oracle is `check_exact=True` on final equity `46189.87730727451` over 134 trades.
- D-01 adds `strategies_handler.set_universe(universe)` to the backtest path. Inertness is **structural**
  (`Universe.__init__` sets `Readiness.READY` for all members at construction, `universe.py:127`; backtest
  membership is derived from strategy tickers so every signalled ticker is a member → `is_ready`=True → the
  gate at `strategies_handler.py:214` never skips). The plan must still PROVE it: run the oracle twice,
  assert byte-identical, on the `wire_universe` plan in isolation.

### Wave 0 Gaps
- [ ] Extend `test_okx_inertness.py` register-vs-build assertions to the new factory/runner/registrar surface
      (the file already anticipates `build_live_system` at `:84`).
- [ ] Relocated `Test*` classes need `__test__ = False` — add a targeted collection-safety assertion
      (a test that imports the fixture module and asserts pytest collected 0 items from it).
- [ ] `tests/unit/price/test_replay_provider.py` follows `ReplayDataProvider` → `tests/` (rename import).

## Sequencing (planner-actionable)

**Safe order (from D-18 guardrail + verified coupling):**
1. **RUN-04 FIRST, isolated** — extract `wire_universe(engine)` into `trading_system/universe_wiring.py`;
   repoint `backtest_runner` to call it; add the live-gaining WR-03 assert. **Gate: oracle byte-exact
   double-run + inertness green.** This is the milestone's highest oracle risk — lock it green ALONE before
   anything else touches the live tree.
2. **RUN-01/02/03/05/06/07 (middle group)** — `build_live_system` + `LiveRunner` + `WorkerSupervisor` +
   `SessionInitializer` + `LiveRouteRegistrar` + first-class `UniverseHandler` + `StrategyWarmupConsumer`
   rehome, **including the ~45 `LiveTradingSystem(exchange=...)` → factory call-site migration** (LANDMINE 1).
   Gate each plan: inertness + paper-parity green, `mypy --strict`, full suite. The planner may sub-slice;
   RUN-06 (`UniverseHandler` at root) must precede RUN-05 (`LiveRouteRegistrar` references its methods) per D-10.
3. **TEST-01 LAST, own plan** — relocate the whole replay harness to `tests/` as PURE code-motion with
   `test_paper_parity` green CONTINUOUSLY; re-point production `paper`→OKX (`:535`); drop `register('replay')`
   (`:517`); `__test__ = False` on `Test*` classes. Do NOT combine with RUN-04 (don't remake the ruler and
   the measured thing at once).

**Indentation hazard (bytes-per-file — MEMORY: live-trading-system-is-space-indented):**
`trading_system/` is SPLIT. Verified this session:
- `live_trading_system.py` → **4 spaces**
- `backtest_runner.py`, `compose.py`, `engine_context.py` → **TABS** (each header declares `Indentation: TABS`)
- `universe/universe.py`, `universe/universe_handler.py`, `price_handler/feed/cache_registration.py`,
  `price_handler/feed/base.py` → **4 spaces**
New files (`universe_wiring.py`, the runner/factory/registrar): the shared `wire_universe` body relocates
FROM `backtest_runner.py` (TABS) — a verbatim TAB-indented block. If `universe_wiring.py` is authored
4-space, the transplanted block must be RE-INDENTED to match, or the file kept TABS. **Measure bytes per
file every edit; never generalize the package.**

## Don't Hand-Roll / Established Patterns (brief — all already in the tree)

| Concern | Reuse, don't rebuild | Location |
|---------|---------------------|----------|
| Venue assembly | `assemble_venue(ctx, spec, connectors)` | `venues/assemble.py` (P5) |
| Base graph | `compose_engine(ctx, spec) -> Engine` | `compose.py:114` |
| Depth ladder | `cache_registration.derive` / `derive_required_depths` | `price_handler/feed/cache_registration.py` |
| Publish-and-continue (D-07) | `_publish_and_continue` moved verbatim (WR-06 guard) | `live_trading_system.py:622` |
| Route pattern | single `_routes` literal, list order = execution order | `full_event_handler.py` |
| Composition-over-inheritance | `compose_engine → Engine → BacktestRunner` analog | — |

**Zero new third-party dependencies** — milestone gate forbids any poetry change (REQUIREMENTS §2). No
Package Legitimacy Audit needed (nothing installed).

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | The 43 test call sites all break under D-09's param-shedding (assumes no other `LiveTradingSystem` overload path) | Landmine 1 | If a back-compat shim is kept, fewer sites change — LOW (the planner picks the strategy) |
| A2 | `feed.bind` never snapshots `cache_capacity` (rings lazy at `_deliver`) → D-12 order safe | Landmine 3 | Verified via `base.py:125` + `live_bar_feed.py:383/625`; risk ~nil, but the live warmup path is not oracle-covered, so a runtime-only regression would surface in paper-parity, not the oracle |

## Open Questions

1. **Facade `__init__` "components bundle" shape (D-09 discretion) drives the call-site migration ergonomics.**
   - Known: `__init__` becomes pure injection; tests currently pass `exchange="..."`.
   - Unclear: whether the planner exposes a `build_live_system(spec)` that tests call directly, or a
     `LiveTradingSystem.for_exchange(...)` convenience over the factory (minimizes the 43-site churn).
   - Recommendation: decide this in the first middle-group plan; it determines whether Landmine 1 is a
     mechanical sweep or a few fixture edits. Fix `integration/conftest.py:358` first (widest leverage).

2. **`test_okx_inertness.py:155` currently imports `ReplayDataPlugin` from `itrader.venues.paper_plugin`.**
   - After D-18 that plugin leaves `itrader/` → `TestDataPlugin` in `tests/`. The inertness gate's
     assertion over that symbol must be re-authored to assert the PRODUCTION path no longer registers
     `replay` at all (the stronger post-D-21 invariant), rather than importing a now-relocated plugin.

## Sources

### Primary (HIGH confidence — direct reads/greps this session, 2026-07-13)
- `itrader/trading_system/backtest_runner.py` (full) — `wire_universe` donor
- `itrader/trading_system/compose.py` (full) — `Engine` + `compose_engine`
- `itrader/trading_system/live_trading_system.py` (`:118-183`, `:598-602`, `:1660-1672`, greps) — all live donors, shed params, monkeypatch boundary
- `itrader/universe/universe.py` (`:90-189`) — construction-time READY inertness
- `itrader/universe/universe_handler.py` (`:150-289`) — ctor + 7 seams
- `itrader/strategy_handler/strategies_handler.py` (`:100-229`) — set_universe + readiness gate `:214`
- `itrader/price_handler/feed/cache_registration.py` (full) — RUN-07 target
- `itrader/price_handler/feed/base.py` / `live_bar_feed.py` (greps) — lazy capacity (Landmine 3)
- `itrader/venues/paper_plugin.py`, `itrader/price_handler/providers/replay_provider.py` (greps) — TEST-01 surface
- `itrader/events_handler/full_event_handler.py` (`:136-171`) — default fail-fast seam
- Cross-tree greps: 43 test + 2 script `LiveTradingSystem(exchange=...)` sites; gate-file existence
- `.planning/phases/06-liverunner-factory-facade-shrink/06-CONTEXT.md`, `.planning/REQUIREMENTS.md`

### Secondary
- CLAUDE.md project instructions; MEMORY entries (worktree/.env, indentation-split)

## Metadata

**Confidence breakdown:**
- Code-state verification: HIGH — every pin read directly; only 2 cosmetic drifts
- Hidden coupling (Landmine 1): HIGH — 43+2 sites enumerated by grep
- Validation architecture: HIGH — all 3 gate files confirmed present; commands runnable
- Sequencing: HIGH — follows D-18 guardrail + verified dependency (RUN-06 before RUN-05)

**Research date:** 2026-07-13
**Valid until:** ~2026-07-27 (stable brownfield tree; re-verify line pins if the branch advances materially)
