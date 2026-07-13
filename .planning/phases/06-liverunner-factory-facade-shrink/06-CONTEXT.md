# Phase 6: LiveRunner + Factory + Facade Shrink - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Make `build_live_system(spec)` the live composition root over a new `LiveRunner`,
shrinking the 2,127-line `LiveTradingSystem` God object toward a thin facade — with
the **shared `UniverseWiring` helper extracted byte-exact** (the milestone's highest
oracle risk) and reused by both `BacktestRunner` and a new live `SessionInitializer`,
live + CONTROL routes composed declaratively via `LiveRouteRegistrar`, `UniverseHandler`
promoted to a first-class handler, and `StrategyWarmupConsumer` rehomed with the CF-10
depth-hint seam shaped. **Live-only decomposition** layered on the mode-agnostic
`compose_engine` base graph; `BacktestRunner` stays byte-exact `134 / 46189.87730727451`
(per-PLAN gate on the `UniverseWiring` extraction) and `test_okx_inertness.py` stays green.

**Locked by ROADMAP success criteria + REQUIREMENTS — NOT up for discussion:**
- `build_live_system(spec)` is the live factory / composition root (RUN-01); `LiveRunner`
  owns the drain loop + injected `ErrorPolicy` + worker supervision, replacing
  `_event_processing_loop` (RUN-02).
- `LiveTradingSystem` shrinks to a facade (lifecycle, status/read-model, `add_event`);
  legacy `print_status`/`get_statistics` dropped; `__init__` sheds
  `exchange`/`to_sql`/`queue_timeout`/`max_idle_time` (from config/spec) (RUN-03).
- Shared `UniverseWiring` (`derive_membership → build Universe → inject exchange/order/
  portfolio/strategies → feed.bind`, incl. WR-03 desync assert) extracted as ONE intact
  unit, reused by both runners — oracle byte-exact (RUN-04).
- `LiveRouteRegistrar` composes live + CONTROL routes declaratively (list order = execution
  order); no subclass, no runtime mutation; backtest gets base routes only (RUN-05, LR-16).
- `UniverseHandler` constructed at the live composition root as a first-class handler with
  explicit deps; zero OKX coupling (RUN-06).
- `_LiveWarmupConsumer` → reusable `StrategyWarmupConsumer` in
  `price_handler/feed/cache_registration.py`, sized `max(strategy.warmup)`; CF-10 depth-hint
  seam shaped (K-computation deferred) (RUN-07).
- Backtest oracle byte-exact (per-PLAN gate on `UniverseWiring`); `test_okx_inertness.py` green.

**Explicitly NOT in this phase (deferred to later phases — downstream must NOT pull forward):**
- `SafetyController` / `ReconciliationCoordinator` / `StreamRecoveryHandler` extraction +
  CONTROL routes + pre-trade throttle — **P7** (the facade's halt/pause/dispatch/reconcile/
  stream method bodies stay UNTOUCHED in P6; see D-04).
- Full `ErrorPolicy` formalization: EventHandler-construction injection (removing the
  monkeypatch), backtest fail-fast / live publish-and-continue split, CF-1 circuit breaker —
  **P8** (P6 only shapes the minimal injected seam; see D-07).
- `run_paper_replay` → `tests/` `ReplayRunner` + replay-free production — **P12** (TEST-01);
  P6 keeps it a thin facade method with the minimal adaptation (see D-16).
- CF-10 K-computation (per-symbol `max(warmup for concerned strategies)` + per-symbol ring
  sizing) — deferred until a deeper-warmup roster lands; P6 shapes only the seam (see D-17).

</domain>

<decisions>
## Implementation Decisions

### Area 1 — UniverseWiring cut line (ORACLE-SENSITIVE, highest risk)

- **D-01 (Shared helper INCLUDES the strategies injection — byte-exact-safe by construction):**
  The shared helper is the FULL RUN-04 unit — `derive_membership → derive_instruments →
  WR-03 desync assert → Universe → engine.universe → set_universe on exchange/order/portfolio
  → strategies_handler.set_universe → feed.bind`. This ADDS a `strategies_handler.set_universe`
  call to the backtest path (backtest today injects exchange/order/portfolio only, NOT
  strategies — `backtest_runner.py:96-110`). **The addition is inert by construction, not
  fragile:** `Universe.__init__` marks ALL members `Readiness.READY` at construction
  (`universe/universe.py:106/127`, explicitly commented *"construction-time READY is
  oracle-inert"*), and backtest membership is derived FROM strategy tickers, so every ticker a
  strategy signals on is a member → `is_ready(ticker)` returns True → the WR-02 readiness gate
  at `strategies_handler.py:214` (`if self._universe is not None and not
  self._universe.is_ready(ticker)`) never skips. Chosen over "byte-exact backtest block only
  (strategies injection stays live-only)" because the owner wants the truly-shared unit matching
  RUN-04's literal text, and the inertness is structural (documented, not coincidental). **Still
  per-PLAN oracle-gated** — the byte-exact + determinism double-run gate PROVES the inertness on
  the `UniverseWiring` extraction PLAN (the milestone's highest oracle risk). Live GAINS the
  WR-03 desync assert (live `_initialize_live_session` lacks it today — a safety upgrade, no
  oracle impact since it's live-only).

- **D-02 (Form = free function `wire_universe(engine) -> Universe` in
  `itrader/trading_system/universe_wiring.py`):** A pure module-level function taking the
  `Engine` holder (both modes have one post-P6 — `build_live_system` calls `compose_engine`),
  returning the built `Universe`. The backtest block relocates VERBATIM; each caller keeps its
  own pre/post (backtest: ping-grid union + per-strategy `feed.precompute`; live: warmup-consumer
  register, `UniverseHandler` construction, `LiveRouteRegistrar` routes). **Home = `trading_system/`,
  NOT `universe/`** — the decisive constraint is that `universe/membership.py` + `instruments.py`
  are documented as *"no class, no state, no queue, no feed/store import"* (pure derivation), but
  the helper does `feed.bind(global_queue, ...)` + injects into exchange/order/portfolio/strategies
  handlers (composition wiring with feed + handler coupling). Homing it in `universe/` would drag
  queue/feed/handler deps into a package deliberately kept clean of them. The helper CALLS the pure
  `universe/` derivations and orchestrates + injects — orchestration is `trading_system`'s job.
  Rejected a class / shared-runner-base (heavier, tab/space transplant hazard, violates the
  composition-over-inheritance ethos). Called at DIFFERENT lifecycle points by the two callers
  (backtest at `run()`-init unchanged; live at construction — see D-14/D-15) — fine, it's a pure
  function of registered-strategy state.

### Area 2 — P6/P7 facade boundary

- **D-03 (`~200 lines` = milestone-EXIT gate verified at P7 close; P6 lands an interim facade):**
  Roadmap SC3 lists *"~200-line facade"* as a P6 criterion, but P7 (Safety + Reconciliation +
  Stream Recovery) owns extracting the ~500 lines of `halt`/`pause_submission`/`resume_submission`/
  `reset_halt`/`_update_status`/`_dispatch_live`/`_is_halted`/`_replay_deferred_protective`
  (`~749-1073`) + the reconcile/stream methods still in the facade today — P6 physically can't
  finish P7's extraction (P7 depends on P6). **P6 acceptance is STRUCTURAL** (verifiable at P6
  close): `build_live_system` owns the ~700-line `__init__` wiring; `LiveRunner` owns the drain
  loop; `__init__` sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time`;
  `print_status`/`get_statistics` deleted; session-init → `wire_universe`/`SessionInitializer`;
  routes → `LiveRouteRegistrar`. The facade lands ~600-700 lines interim; the literal `~200` is a
  **milestone-exit gate verified at P7 close**, NOT a P6-close gate. Rejected forcing ~200 at P6
  via interim relocation of safety/reconcile/stream (double-work + churn over the milestone's most
  fragile seams) and pulling `SafetyController` into P6 (re-scopes P7, violates the dependency-graph
  split). The P6 planner/verifier MUST NOT mark RUN-03 incomplete for a ~650-line facade, nor force
  relocation to hit a number the graph doesn't allow yet.

- **D-04 (P6 does NOT touch the safety/reconcile/stream method BODIES):** Leave `halt`/`pause`/
  `reset_halt`/`_update_status`/`_dispatch_live`/`_run_session_baseline_guard`/
  `_link_venue_account_to_portfolios`/`_on_venue_stream_down`/`_maybe_resume_after_reconnect`/etc.
  exactly where they are so P7 extracts from a known, UNCHURNED baseline (the two-phase diff stays
  clean over fragile seams). P6 only REMOVES the wiring/loop/stats AROUND them. LiveRunner reaches
  the still-in-facade dispatch gate via an injected callback (see D-08).

### Area 3 — LiveRunner scope

- **D-05 (WorkerSupervisor extracted as its OWN class in P6):** `_run_poll_timer`'s timer-worker
  management becomes a standalone `WorkerSupervisor` collaborator (§5 lists it); `LiveRunner`
  COMPOSES it. Chosen over "LiveRunner owns worker supervision directly (defer WorkerSupervisor
  until a 2nd worker)" — the owner wants the §5 collaborator built now rather than folded into
  LiveRunner and re-extracted later. RUN-02's "worker supervision" is satisfied by LiveRunner
  owning the WorkerSupervisor instance.

- **D-06 (LiveRunner owns the drain loop, replacing `_event_processing_loop`):** `LiveRunner` owns
  the daemon-thread drain loop (`_event_processing_loop` gone from the facade). `queue_timeout`/
  `max_idle_time` come from config/spec (RUN-03), not `__init__` params. `run_paper_replay`'s
  SEPARATE synchronous drive (D-16) does NOT route through LiveRunner and is unaffected.

- **D-07 (Minimal injected `ErrorPolicy` seam — publish-and-continue moved verbatim; P8 formalizes):**
  `LiveRunner` is constructed WITH an injected `error_policy` (RUN-02 says "injected ErrorPolicy").
  In P6 that policy is MINIMAL: today's `_publish_and_continue` (`live_trading_system.py:622`) moved
  verbatim into it, WR-06 source guard preserved. The full formalization — EventHandler-construction
  injection (removing the `event_handler._on_handler_error = ...` monkeypatch), the backtest
  fail-fast / live publish-and-continue split, and the CF-1 aggregate circuit breaker — stays in P8
  (§12a). Gives LiveRunner a stable constructor P8 fills in; matches RUN-02's literal wording and
  avoids P8 re-touching LiveRunner's ctor. Chosen over "leave the error seam as-is / defer all to
  P8" (would defer RUN-02's explicit "injected ErrorPolicy" clause and force P8 to re-touch
  LiveRunner).

- **D-08 (LiveRunner takes an injected dispatch-gate callback → facade `_dispatch_live` in P6,
  SafetyController in P7):** The live loop's `_dispatch_live` safety gate is P7's `SafetyController`.
  Per D-04, LiveRunner takes an injected dispatch-gate callback wired in P6 to the facade's existing
  `_dispatch_live` (body untouched); P7 repoints it at `SafetyController.dispatch_gate`. Mirrors the
  D-11 `freeze_gate` interim-callback pattern.

### Area 4 — Factory handoff & route registration

- **D-09 (`build_live_system(spec) -> LiveTradingSystem` is the ONLY construction path; facade
  `__init__` = pure injection):** `build_live_system` reads centralized config, builds the ONE
  `sql_engine` (live only), resolves venue plugin(s), assembles `EngineContext`, calls
  `compose_engine`, builds bundle(s) (promoting the P5 D-06 `assemble_venue` call site from
  `__init__` into the factory) + `LiveRunner` + `WorkerSupervisor` + controllers + `UniverseHandler`,
  composes routes, and RETURNS the wired facade. `LiveTradingSystem.__init__` becomes pure injection
  (takes the pre-built collaborators / a components bundle), holds NO wiring logic. Mirrors
  `compose_engine → Engine → BacktestRunner`. Chosen over "facade `__init__` takes a spec +
  orchestrates internally" (blurs the factory/facade split, leaves wiring in the facade). Existing
  direct `LiveTradingSystem(...)` constructions (tests, the `run_paper_replay` caller) migrate to the
  factory; `run_paper_replay` itself relocates to `tests/` in P12.

- **D-10 (`LiveRouteRegistrar` = ONE central declarative route table, installed at construction):**
  `LiveRouteRegistrar` holds a single central live + CONTROL route composition (mirrors today's
  single `EventHandler._routes` literal where list order IS execution order), referencing the built
  handlers'/controllers' methods, installed into the single `EventHandler` ONCE at construction — no
  runtime mutation, no subclass (LR-16). Keeps the correctness-load-bearing cross-handler ordering
  greppable in ONE place: `FILL` = portfolio → order → universe; `BARS_LOADED` = strategies →
  universe. The live route set (§13c): `UNIVERSE_POLL`, `UNIVERSE_UPDATE`, `STRATEGY_COMMAND`,
  `BARS_LOADED`, `BARS_LOAD_FAILED`, `FILL` (appended), + CONTROL (`STREAM_STATE`, `CONNECTOR_FATAL`,
  `CONFIG_UPDATE`). Backtest's `EventHandler` keeps the untouched base literal (empty `UNIVERSE_*`
  routes) — inertness, proven by `test_okx_inertness.py`. Chosen over distributed per-handler
  `owned_routes()` declaration (§5's literal wording) because cross-handler execution ordering can't
  be expressed cleanly when spread across files. Requires `UniverseHandler` built at the root FIRST
  (D-12/RUN-06) so the table can reference its methods at construction.

### Area 5 — UniverseHandler first-class init (RUN-06)

- **D-11 (Ctor deps = `bus`/`universe`/`feed`/`config` (RUN-06 literal); read-model seams stay as
  setters; freeze_gate is an interim callable):** `UniverseHandler.__init__` takes exactly
  `bus`/`universe`/`feed`/`config` (timeframe + `remove_policy` read from config — RUN-06's literal
  dep list). `set_venue_metadata(exchange)` becomes ONE unconditional call collapsing the two
  currently-OKX-guarded seams `set_symbol_validator` + `set_precision_resolver` (both now abstract
  `AbstractExchange` capabilities `validate_symbol`/`resolve_precision` since P5 VENUE-04; paper/replay's
  simulated exchange returns permissive defaults per P5 D-09 → NO OKX `None`-guard = "zero OKX coupling").
  `set_freeze_gate` stays an injected callable — it references `halt`/`pause` which P7's
  `SafetyController` owns — wired interim to the facade's `_is_halted`/`_is_submission_paused`,
  repointed to `SafetyController` in P7 (mirrors D-08). The 4 cross-domain read-model seams
  (`set_selection_source`, `set_provider`, `set_portfolio_read_model`, `set_strategy_warmth`) stay as
  explicit setters — preserves the tested swap-a-fake seams, keeps the ctor small, low churn;
  provider/selection are now uniform (P5 VENUE-05 no-op defaults) so their old okx-guards are gone.
  Chosen over "maximal ctor (fold the 4 read-models in)" (large ctor, more churn, drops the setter
  seams, exceeds RUN-06's literal dep list).

### Area 6 — SessionInitializer scope

- **D-12 (SessionInitializer is a DISTINCT class, run at CONSTRUCTION time):** A named class
  (RUN-04/§13a name it), constructed and invoked by `build_live_system` at construction time. It owns
  the live session wiring: call `wire_universe(engine)` → register `StrategyWarmupConsumer` on the feed
  → build + wire `UniverseHandler` (the D-11 shape) → compose routes via `LiveRouteRegistrar`. **Running
  at construction is what makes RUN-05 (routes declarative-at-construction) and RUN-06 (UniverseHandler
  first-class at root) possible.** The `start()` lifecycle then does ONLY I/O (connect / subscribe /
  reconcile — the last being P7). Independently testable without standing up a full facade. Chosen over
  "inline in `build_live_system` (no separate class)" (RUN-04 explicitly names the SessionInitializer;
  factory would grow a large inline block) and "distinct class run at `start()`" (conflicts with
  RUN-05/RUN-06 by building routes + UniverseHandler at `start()`, leaving the facade half-wired between
  `__init__` and `start()`).

### Area 7 — run_paper_replay integrity (parity gate)

- **D-16 (Minimal P6 adaptation — drop line 1490, preserve steps 2-3 verbatim):** `run_paper_replay`
  (`live_trading_system.py:1422`) NEVER used `_event_processing_loop`/the daemon/LiveRunner — it has
  its own synchronous per-bar drive calling `event_handler.process_events()` directly (steps 2-3,
  `:1499-1524`). Its ONLY touchpoint with the decomposed code is line 1490
  `self._initialize_live_session()`. Since D-12 makes `SessionInitializer` run at construction, the
  replay instance (built via `build_live_system(paper_spec)`) already has its session initialized — so
  P6's ONLY change is to **DROP line 1490**; steps 2-3 stay VERBATIM. **Fail-fast enforcement for replay
  is NOT P6 work** — spec §12a assigns "backtest/replay → fail-fast" (via the injected `ErrorPolicy`) to
  **P8**; P6 preserves current behavior. **Relocation to `tests/` `ReplayRunner` + replay-free
  production is P12** (TEST-01). Chosen over "keep an explicit repointed init call" (adds a second init
  path — construction + explicit — that has to stay consistent). This corrects an over-scoped proposal
  (inject fail-fast ErrorPolicy / construct-via-factory-with-replay-logic) that pulled P8 + P12 work
  into P6.

### Area 8 — CF-10 depth-hint seam shape (RUN-07)

- **D-17 (Shape a NAMED depth-computation boundary; K-computation + per-symbol rings deferred):**
  `price_handler/feed/cache_registration.py` exposes `register_strategy_warmup(feed, strategies)`
  (called by `SessionInitializer`) that computes the ring depth via a NAMED, replaceable warmup-depth
  function — today returns the global `max(s.warmup for strategies)`; CF-10 generalizes THAT function
  to per-concerned-strategy `max(warmup for strategies concerned with symbol)`. The rehomed
  `StrategyWarmupConsumer` stays a frozen scalar `required_history_depth` (ONE global ring) for now.
  **The seam shaped = the depth-computation function boundary**, so CF-10 changes only that function
  body — NOT the registration wiring or `SessionInitializer`. Per-symbol RING sizing stays deferred
  WITH the K-computation (RUN-07: "the K-computation change itself stays deferred"). Chosen over
  "minimal rehome, inline the `max()`" (CF-10 would re-touch the registration wiring — exactly what
  RUN-07's "shape the seam so it is not re-touched" forbids). No roster needs per-symbol depth today
  (SMA_MACD `cache_capacity()=100` ≥ deepest declared warmup).

### Claude's Discretion
- Plan/wave slicing across RUN-01..07 (planner's call, subject to the byte-exact + inertness gates).
  The `UniverseWiring` extraction (RUN-04) is the oracle-gated PLAN and should be isolated/verified
  on its own.
- Exact module paths, class/function names, and signatures beyond the pins above: the `LiveRunner` /
  `WorkerSupervisor` / `SessionInitializer` / `LiveRouteRegistrar` / `build_live_system` /
  `wire_universe` / `register_strategy_warmup` surfaces; the `error_policy` object shape; the
  "components bundle" shape the facade `__init__` receives (D-09); whether `set_venue_metadata` takes
  the exchange or a small metadata view.
- The named warmup-depth function's exact name/home within `cache_registration.py` (D-17).

### Folded Todos
- **`warmup-depth-max-concerned-strategy.md`** (folds as **CF-10**, `resolves_phase: P6`) — the
  per-symbol depth-hint design detail behind RUN-07. Captured as D-17 (seam shaped now; K-computation
  deferred).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase framing & locked scope
- `.planning/ROADMAP.md` § "Phase 6: LiveRunner + Factory + Facade Shrink" — goal + the 5 success
  criteria; the P6/P7/P8/P12 dependency notes.
- `.planning/REQUIREMENTS.md` § "LiveRunner + Factory + Facade Shrink (P6)" (RUN-01..07, lines ~157-186)
  — authoritative requirement text incl. the §5/§13a-d / LR-10/LR-16 / CF-10 citations.
- `.planning/phases/05-venue-registry-bundle/05-CONTEXT.md` — the P5 `assemble_venue` seam (D-06) that
  P6 promotes into `build_live_system`; the venue firewall (D-05); `set_venue_metadata` precursors
  (VENUE-04 precision/validate capabilities, D-09).

### Design source (v1.8 spec — note P6/P7 numbering offset)
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §5 (module topology,
  build_live_system → compose_engine → LiveRunner → facade), §11e (facade cleanup — points 8/25),
  §12a (ErrorPolicy — P8, NOT P6), §13a (SessionInitializer + shared UniverseWiring), §13b
  (UniverseHandler proper init), §13c (LiveRouteRegistrar), §13d (StrategyWarmupConsumer rehome),
  §15 (oracle constraint). **NOTE:** the spec's internal numbering is offset — its "P7" == current
  ROADMAP Phase 6 (LiveRunner), its "P6" == current Phase 5 (venue registry).

### The UniverseWiring extraction (RUN-04, oracle-sensitive)
- `itrader/trading_system/backtest_runner.py:50-131` `_initialise_backtest_session` — the byte-exact
  donor block; membership → instruments → WR-03 assert (`:84-90`) → Universe → set_universe on
  exchange (`:96-98`)/order (`:103`)/portfolio (`:110`) → feed.bind (`:113`). Backtest keeps
  ping-grid (`:119-127`) + precompute (`:130-131`) as its own post-step.
- `itrader/trading_system/live_trading_system.py:1246-1420` `_initialize_live_session` — the live
  donor; the shared middle collapses into `wire_universe`, the rest becomes `SessionInitializer`
  (warmup register `:1289`, UniverseHandler `:1348`, routes `:1401-1413`).
- `itrader/universe/universe.py:99-177` `Universe.__init__`/`is_ready` — the construction-time
  `Readiness.READY` default (`:106/127`) that makes D-01's strategies injection oracle-inert.
- `itrader/strategy_handler/strategies_handler.py:109-117` `set_universe` + `:214` the readiness gate
  (`if self._universe is not None and not self._universe.is_ready(ticker)`) — the inertness site.
- `itrader/universe/membership.py` / `instruments.py` — the pure `derive_membership`/`derive_instruments`
  the helper CALLS ("no class, no state, no queue, no feed/store import" — the purity constraint that
  keeps the helper OUT of `universe/`, D-02).

### The facade / factory / runner seams
- `itrader/trading_system/compose.py:81-114` `Engine` holder + `compose_engine(ctx, spec)` — the
  mode-agnostic base graph `build_live_system` calls; `Engine` is the holder `wire_universe(engine)` takes.
- `itrader/trading_system/live_trading_system.py:135-620` `LiveTradingSystem.__init__` — the ~700-line
  wiring that moves to `build_live_system`; `:1526-1608` `_event_processing_loop` → `LiveRunner`;
  `:1852-1873` `_run_poll_timer` → `WorkerSupervisor`; `:622` `_publish_and_continue` → the minimal
  `ErrorPolicy` (D-07); `:1073` `_dispatch_live` (P7 gate, D-08); `:2086`/`:2101`
  `get_statistics`/`print_status` (dropped, RUN-03).
- `itrader/events_handler/full_event_handler.py` — the single data-driven `EventHandler` +
  `routes` dict (`LiveRouteRegistrar` installs into it at construction, no subclass, LR-16).

### UniverseHandler (RUN-06)
- `itrader/universe/universe_handler.py:160-278` — ctor + the 7 `set_*` seams; `set_symbol_validator`
  (`:248`) + `set_precision_resolver` (`:252`) collapse into the new `set_venue_metadata(exchange)`
  (D-11); `set_freeze_gate` (`:235`) stays an interim callable.

### run_paper_replay (RUN — parity gate; D-16)
- `itrader/trading_system/live_trading_system.py:1422-1524` `run_paper_replay` — line 1490
  (`_initialize_live_session()`) is the ONLY P6 change (dropped); steps 2-3 (`:1499-1524`) verbatim.
  Relocation to `tests/` `ReplayRunner` is P12.

### CF-10 warmup seam (RUN-07 / D-17)
- `itrader/trading_system/live_trading_system.py:121-133` `_LiveWarmupConsumer` + `:1289-1292`
  registration — rehome to `price_handler/feed/cache_registration.py` as `StrategyWarmupConsumer`
  with the named depth-computation boundary.

### Gate references
- `tests/integration/test_okx_inertness.py` — inertness gate (live decomposition imports no
  `ccxt.pro` on the backtest path); extend register-vs-build for the new factory/runner surface.
- `tests/integration/test_backtest_oracle.py` — byte-exact oracle (`46189.87730727451`); the per-PLAN
  gate ON the `UniverseWiring` extraction PLAN (RUN-04).
- `tests/**/test_paper_parity.py` — the paper-replay parity gate that `run_paper_replay` feeds
  (`PAPER_PARITY_*` constants; must stay green through the D-16 minimal adaptation).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backtest_runner._initialise_backtest_session` middle block IS the near-complete `wire_universe`
  body — extract, don't rewrite (D-02). The live `_initialize_live_session` middle mirrors it.
- The P5 `assemble_venue(ctx, spec, connectors)` seam already exists and is called from `__init__`
  today — `build_live_system` just relocates the CALL (P5 D-06), no re-authoring.
- `_publish_and_continue` (`:622`, incl. WR-06 source guard) is the minimal `ErrorPolicy` body to
  move verbatim (D-07); the full policy is P8.
- The `Universe` construction-time `Readiness.READY` default is the structural guarantee behind D-01's
  oracle-inertness — not a coincidence to be re-verified by hand.

### Established Patterns
- **Composition over inheritance:** `MatchingEngine`→`SimulatedExchange`, four managers→`Portfolio`,
  `compose_engine → Engine → BacktestRunner`. `build_live_system → …→ LiveRunner → facade` is the live
  analog; `wire_universe` is a free function, `SessionInitializer`/`WorkerSupervisor`/`LiveRunner` are
  has-a collaborators, never a shared runner base.
- **Single central `_routes` literal, list order = execution order** (CLAUDE.md) — `LiveRouteRegistrar`
  is the live analog (D-10), NOT distributed per-handler declaration.
- **Interim-callback for P7-owned gates:** both the LiveRunner dispatch gate (D-08) and the
  UniverseHandler freeze_gate (D-11) wire to the facade's existing `_dispatch_live`/`_is_halted` in P6
  and repoint to `SafetyController` in P7 — leaves the P7 bodies untouched (D-04).
- **Lazy-import / inertness discipline:** the live stack lazy-imports inside its build arm; the
  decomposition must keep the backtest `EventHandler` base-routes-only and `ccxt.pro`-free.
- **Indentation hazard (bytes-per-file):** `trading_system/` is SPLIT — `live_trading_system.py` is
  4-space; `compose.py`/`backtest_runner.py`/`backtest_trading_system.py`/`engine_context.py` are TABS.
  New files (`universe_wiring.py`, the runner/factory/registrar) — match the file each edit touches,
  measure bytes per file, never generalize the package.

### Integration Points
- `build_live_system` is the sole live construction path (D-09); `build_backtest_system`/`BacktestRunner`
  never touch it (the byte-exact firewall — P5 D-05).
- `wire_universe(engine)` is called by BOTH `BacktestRunner._initialise_backtest_session` (run-init,
  verbatim) and `SessionInitializer` (construction) — the shared oracle-critical ordering lives once.
- `ExecutionHandler.on_order` routes by `event.exchange`; `LiveRouteRegistrar` installs into the same
  single `EventHandler` the backtest builds base-only.
- `run_paper_replay` drives `event_handler.process_events()` synchronously — bypasses LiveRunner
  entirely (D-16), so LiveRunner's daemon loop + publish-and-continue don't affect the parity gate.

</code_context>

<specifics>
## Specific Ideas

- The owner consistently favored the **truly-shared / most-complete unit where a seam is load-bearing**
  (include the strategies injection in `wire_universe` matching RUN-04's literal text; extract
  `WorkerSupervisor` as its own class now; shape the CF-10 depth-computation boundary now) — but
  **rejected pulling adjacent-phase work into P6** (they caught the `run_paper_replay` over-scope,
  correctly identifying it as P8 fail-fast + P12 relocation, and cut it to the one-line minimal).
- The **oracle-inertness of D-01's added backtest call is structural** (construction-time `READY`),
  which de-risked the owner's choice of the harder "include strategies injection" path — still
  per-PLAN oracle-gated.
- The **P6/P7 boundary honesty** (D-03) is treated as the phase's defining constraint: `~200 lines`
  is a milestone-exit gate, not a P6-close gate, because P7 depends on P6 — the planner/verifier must
  not force it early.
- Two examples (Option-A vs Option-B ctor shapes) were requested and shown for the UniverseHandler dep
  collapse; the owner picked the literal-RUN-06-ctor + read-model-setters shape (D-11).

</specifics>

<deferred>
## Deferred Ideas

- **SafetyController / ReconciliationCoordinator / StreamRecoveryHandler extraction + CONTROL routes +
  pre-trade throttle (→ P7):** the facade's halt/pause/dispatch/reconcile/stream method bodies stay
  untouched in P6 (D-04); P7 extracts them from the unchurned baseline. The LiveRunner dispatch gate
  (D-08) and UniverseHandler freeze_gate (D-11) repoint to `SafetyController` there.
- **Full ErrorPolicy formalization (→ P8):** EventHandler-construction injection (remove the
  monkeypatch), backtest fail-fast / live publish-and-continue split, CF-1 aggregate circuit breaker,
  and replay's fail-fast enforcement (§12a). P6 ships only the minimal injected seam (D-07).
- **run_paper_replay → `tests/` `ReplayRunner` + replay-free production (→ P12 / TEST-01):** P6 keeps
  it a thin facade method with the one-line adaptation (D-16).
- **CF-10 K-computation + per-symbol ring sizing (→ future, deeper-warmup roster):** P6 shapes the
  named depth-computation boundary (D-17); the per-symbol `max(warmup for concerned strategies)`
  computation + per-symbol rings stay deferred until a roster needs them.

### Reviewed Todos (not folded)
- Generic keyword matches from `todo.match-phase 6` (`04-storage-review-warnings.md`,
  `deep-shared-bar-history.md`, `livebarfeed-depandas-time-model-datetime.md`,
  `margin-equity-double-counts-notional-wr01.md`, et al.) matched only on generic tokens
  (`status`/`phase`/`gate`/`feed`) and are out of the LiveRunner/factory/facade domain — reviewed,
  not folded. `margin-equity-double-counts-notional-wr01` remains the owner-gated, oracle-dark
  standing item (adjudicate before any live margin/leverage consumer).

</deferred>

---

*Phase: 6-LiveRunner + Factory + Facade Shrink*
*Context gathered: 2026-07-13*
