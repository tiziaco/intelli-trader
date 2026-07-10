# Phase 5: Venue Registry + Bundle - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Parametrize every execution venue + data provider behind two registries and a
`VenuePlugin`/`VenueBundle` system — **killing every `if exchange=='okx'` /
`elif=='paper'` branch** — with lazy plugins (inertness-safe), connector memoization by
`(venue, account_id)`, precision/validate as `AbstractExchange` capabilities, a
per-portfolio account factory, and one shared `StreamSupervisor`. **Live-only machinery**
layered on top of the mode-agnostic `compose_engine` base graph; the backtest oracle
stays byte-exact (`46189.87730727451`) and `test_okx_inertness.py` (the P5 acceptance
gate) stays green.

**Locked by ROADMAP success criteria + REQUIREMENTS — NOT up for discussion:**
- Two independent registries (`ExecutionVenueRegistry` + `DataProviderRegistry`) selected
  via `SystemSpec` (VENUE-01); `VenuePlugin` builds a `VenueBundle` with concretions
  lazy-imported inside `build_bundle` (VENUE-02).
- Connectors memoized by `(venue, account_id)`; credentials env-sourced, never persisted (VENUE-03).
- Precision + validation as `AbstractExchange` capabilities; `_OkxPrecisionResolver` /
  `_PrecisionResolver` deleted; `_precision_to_scale` → shared money util (VENUE-04).
- `LiveDataProvider` Protocol + `BaseLiveDataProvider` no-op defaults (no `hasattr`) (VENUE-05).
- `VenueLifecycle` orchestrator None-guards absent members; every venue-string branch removed (VENUE-06).
- Shared `StreamSupervisor` replaces the triplicated `_run_stream_supervisor` + `_STREAM_RECONNECT_*`
  (CF-4); connector-contract docstrings on `connectors/base.py` (CF-3); OKX markets-map freshness
  closes the fail-open-before-load window via `validate_symbol` → removal path (CF-9) (VENUE-07).
- Backtest oracle byte-exact (per-PLAN gate); `test_okx_inertness.py` green (register-vs-build).

**Explicitly NOT in this phase (deferred to consumers — downstream must NOT pull forward):**
- The `build_live_system` factory + facade shrink to ~200 lines + `UniverseWiring` extraction — **P6**.
- Multi-account: per-account env-credential naming scheme + per-`PortfolioSpec` account_id + per-portfolio
  account fan-out — **P11** (P5 only *shapes* the `(venue, account_id)` seam with a single default account).
- Post-connect venue-account-UID-vs-intent reconciliation assertion — **P7 reconcile / P11**.

</domain>

<decisions>
## Implementation Decisions

### Area 1 — Registry, bundle & connector shape

- **D-01 (Explicit-map registration — no import side effects):** Both registries are plain
  `dict[name -> plugin]` populated by explicit `register("okx", OkxVenuePlugin())` calls at the
  composition root. Rejected decorator self-registration (inverts inertness — the registry module
  would have to import every plugin module, one careless top-level `import ccxt.pro` reddens the gate)
  and entry-points/`importlib.metadata` (extensibility machinery no consumer needs). Rationale:
  registration-as-explicit-call makes "register ≠ import concretion" **greppable and structurally
  obvious**, matching the codebase's no-import-side-effects ethos (only `config`/`logger`/`idgen`
  construct at import) and the explicit-injection Protocol seams (`LiveConnector`, `AbstractExchange`).

- **D-02 (Execution-only `VenueBundle`; data provider built by the separate registry):**
  `VenueBundle` is a `@dataclass(frozen=True, slots=True)` carrying **only the execution arm** —
  `exchange: AbstractExchange` + `account_factory: Callable[[PortfolioRef, AccountConfig], Account]`
  (both mandatory), `connector: LiveConnector | None = None` and `lifecycle: VenueLifecycle | None = None`
  (Optional). The data provider is built by `DataProviderRegistry`, **not** carried in the bundle.
  Rejected one-combined-bundle (collapses VENUE-01's independent selection — e.g. OKX exec + a
  different data feed) and bundle-owns-connector-providers-borrow (couples data-provider build to
  execution-bundle build order). Mirrors today's structure (exchange/provider/account each injected
  the same session separately).

- **D-03 (Shared `ConnectorProvider` — one build recipe per venue, memoized by `(venue, account_id)`):**
  A dedicated `ConnectorProvider` owns *both* the per-venue build recipe (via a `ConnectorPlugin.build(spec)`
  per venue) *and* the `(venue, account_id)` memo, plus `close_all()` for stop(). Both the execution
  `build_bundle` and the data `build_provider` call `connectors.get(venue, account_id, spec)` and receive
  the **same** connector instance. Chosen over a bare memo-dict-with-per-plugin-lambda because the dict
  variant duplicates the connector build recipe across the exec AND data plugin for the same venue; the
  provider gives a single source of truth and puts VENUE-03 memoization in the one place responsible for
  connector lifetime (beside the `connectors/` package + `LiveConnector` Protocol). **Why a memo at all**
  (not "build once, inject"): the two independent registries are two separate builders — without a shared
  memo each would lazily construct its own `OkxConnector` → two `ccxt.pro` clients / loops / WS sessions
  for one `(venue, account_id)`; "build once at the root and inject" would force the root to `import
  OkxConnector` (reintroducing the `if venue=='okx'` branch this phase deletes).

- **D-04 (Triple-deferral laziness — correctness-critical for the inertness gate AND cred-less machines):**
  `ConnectorPlugin.build()` MUST keep BOTH the concretion `import` and the `OkxSettings()` construction
  **inside** `build()` — never at module top, never at register time. Three deferral layers:
  (1) `register(OkxConnectorPlugin())` is inert (stores an object); (2) lazy `import` inside `build()`
  guards the backtest import graph (`ccxt.pro` never loads → inertness gate green); (3) `OkxConnector(OkxSettings())`
  construction inside `build()` guards **missing `OKX_API_*` creds** (backtest / non-OKX machines never
  reach it); (4) `connector.connect()` network I/O stays deferred to `start()` (connect-fail → `SystemStatus.ERROR`,
  not a raise). Backtest is safer than merely "lazy": it selects paper/simulated whose plugin has
  `connector=None` and never touches `ConnectorProvider`, so `OkxSettings()` is never reached at all.
  **Planner/executor MUST NOT hoist the plugin's imports to module top** — that silently reddens `test_okx_inertness.py`.

### Area 2 — Kill-scope & P5/P6 boundary

- **D-05 (Registry is a LIVE-ONLY overlay; backtest firewall):** `compose_engine(ctx, spec)`
  (`trading_system/compose.py:175-181`) builds the shared base graph — **including the `'simulated'`
  `SimulatedExchange`** — for BOTH modes. Backtest (`build_backtest_system`) uses that `'simulated'`
  exchange **directly** and **never invokes the venue registry** → zero new byte-exact risk surface.
  Live (`LiveTradingSystem` → P6 `build_live_system`) resolves venue plugins and **layers** OKX/paper
  wiring on top. `okx` + `paper` become live execution plugins (+ `okx`/`replay` data plugins);
  `PaperVenuePlugin.build_bundle` **reuses the compose-built `'simulated'` exchange** (today's
  `elif=='paper'` at `live_trading_system.py:625` already does this — `connector=None`, `SimulatedAccount`).
  `'simulated'` is therefore **not** a registered venue (it's the shared base every mode gets from compose).
  Rejected routing backtest through a `'simulated'` plugin (puts the registry on the byte-exact hot path)
  and okx-only (leaves the `elif=='paper'` branch SC3 charters us to kill).

- **D-06 (P5 removes both branches via a `assemble_venue` helper seam; P6 promotes the call):** P5 lands
  the registries/plugins/`ConnectorProvider`/`VenueLifecycle` AND a venue-assembly seam
  `assemble_venue(ctx, spec, connectors) -> (VenueBundle, VenueLifecycle)` that `LiveTradingSystem.__init__`
  **delegates to** — the `if exchange==` branches are gone in P5 (satisfies SC3). P6 then relocates the
  **call site** from `__init__` into `build_live_system` and shrinks the facade — the assembly *logic* is
  written once, only the call moves. Rejected inline-in-`__init__` (same ~40 lines authored inline in P5
  then moved wholesale in P6 = two diffs over the milestone's highest-oracle-risk boundary) and
  machinery-only-defer-to-P6 (violates SC3). The seam is independently unit-testable in P5 (assemble against
  okx/paper specs without standing up a full `LiveTradingSystem`).

### Area 3 — Connector memoization & credentials

- **D-07 (`account_id` = config-known STABLE NAME resolved pre-`connect()`; single default in P5):**
  The memo key `account_id` is a chosen, config-sourced **name** (`"default"`/`"main"`/…) known **before**
  `connect()` — it MUST be, because the dedup happens at build time before any connect (a connect-time-
  generated value couldn't key the memo before the connector it dedupes exists). This aligns with Phase-4
  D-06 (durable/keying identity is a stable name, never an ephemeral generated value). P5 uses a **single
  default** `account_id` (`spec.account_id or "default"`); credentials come from `OkxSettings()` reading
  today's `OKX_API_*`. The per-account env-naming scheme (`OKX_<ACCOUNT>_*`), a real `PortfolioSpec.account_id`
  field, and per-account credential dispatch are **deferred to P11** against the real multi-account consumer
  (YAGNI — mirrors P4 D-01/D-02/D-09 "finalize surfaces against the real consumer"). The venue-provided
  account **UID** (exchange truth, discovered post-connect) is a *different* identifier for reconciliation,
  **not** the memo key — deferred to P7/P11 (see Deferred Ideas).

### Area 4 — StreamSupervisor & provider Protocol

- **D-08 (Shared `StreamSupervisor` = composition class in `connectors/stream_supervisor.py`):** A standalone
  `StreamSupervisor(config, halt_signal, on_down, on_up, logger)` with `async run(connect_and_consume, name)`,
  `reset_budget(name)`, `mark_down`/`mark_up` — owning `_reconnect_attempts` / `_streams_down` + the **WR-03
  payload-only-budget-reset** rule. **New 4-space file beside `LiveConnector`.** Each of the three donor arms
  (`price_handler/providers/okx_provider.py`, `portfolio_handler/account/venue.py` [TABS],
  `execution_handler/exchanges/okx.py` [TABS]) **HAS-A** supervisor and delegates; the tab files just delete
  their `_run_stream_supervisor` method and add one tab-indented delegation call. Composition (not a
  mixin/base) — matches the `MatchingEngine`/`Portfolio`-manager ethos, quarantines the security-critical
  reconnect state in one tested home, and **dodges the tab/space transplant hazard** (the 80 lines live in one
  4-space file; no security-critical body ever lands *inside* a tab file via MRO). Behavior to preserve
  **exactly**: transient/fatal exception classification, clean-return = socket-closed → reconnect,
  **unclassified → fail-safe halt** (never fall through to the reconnect ladder), retry-ceiling → halt,
  debounce + capped exponential backoff, scrub discipline (log the exception TYPE / fixed label, **never
  `str(exc)`** — T-05-27), `CancelledError` re-raise, subscribe ≠ health (WR-03: only a delivered payload
  resets the budget).

- **D-09 (Precision/validate as `AbstractExchange` capabilities — VENUE-04, largely SC-locked):**
  `resolve_precision(symbol)` joins the existing `validate_symbol(symbol)` on the `AbstractExchange` Protocol
  (`execution_handler/exchanges/base.py`); `_OkxPrecisionResolver` + `_PrecisionResolver`
  (`live_trading_system.py:110-174`) are deleted; `_precision_to_scale` becomes a shared **money util**
  (`core/money.py`). Low-gray (SC fully pins it) — noted for completeness. Simulated exchange's
  `resolve_precision` returns a sensible default when it holds no markets map.

- **D-10 (Provider uniformity rule — no-op default for present-optional methods; None-guard for absent
  components):** VENUE-05 and VENUE-06 are complementary at **different granularities**, reconciled as one
  rule: an **optional METHOD on a PRESENT object** (a data provider that doesn't stream) → **no-op default**
  on `BaseLiveDataProvider` (call unconditionally, kills `hasattr`); an **entirely ABSENT component** (paper's
  connector/account) → **explicit `None`-guard** in `VenueLifecycle` (`bundle.connector`/`account` are
  `Optional`, `None` for paper). Rejected the Null-Object pattern for absent components (invents `NullConnector`/
  `NullAccount` classes no requirement asked for, contradicts the `Optional=None` bundle shape from D-02, and
  **silently masks** a component that failed to build vs. a guard that lets an unexpected `None` fail loud).
  "Branch-free" is NOT the goal — killing `if exchange==` **venue-type** branches is; a few
  `if component is not None` structural guards are categorically different.

- **D-11 (CF-9 OKX markets-map freshness — reuse the existing removal path, no parallel drop):** Keep the
  OKX `markets` map fresh so the existing `validate_symbol` → `delta.removed` → unsubscribe/force-close path
  catches **mid-session delistings**, and close the **fail-open-before-load** window (`validate_symbol`
  returning True when `markets` isn't yet a dict). Do **NOT** add a second, parallel "drop" mechanism inside
  the warmup retry loop. Folds the `okx-markets-map-freshness-delisting-detection.md` todo (`resolves_phase:
  P5`). See canonical refs for the two staleness holes and `okx.py:1016-1032`.

### Claude's Discretion
- Plan/wave slicing across VENUE-01..07 (planner's call, subject to the byte-exact + inertness gates).
- Exact module paths (`execution_handler/venues/` vs a new top-level `venues/` package), precise
  `StreamSupervisor` / `ConnectorProvider` / registry method names and signatures, the default `account_id`
  literal, and whether `VenueLifecycle` is a class or a small ordered helper — planner/researcher's call
  within the decisions above.
- `resolve_precision` return shape and where exactly `_precision_to_scale` lands in `core/money.py`.

### Folded Todos
- **`okx-markets-map-freshness-delisting-detection.md`** (`resolves_phase: P5`, `folded_into: CF-9`) — the
  mid-session-delisting / fail-open-before-load design detail behind VENUE-07's CF-9 clause. Captured as D-11.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase framing & locked scope
- `.planning/ROADMAP.md` § "Phase 5: Venue Registry + Bundle" — goal + the 5 success criteria; the P5/P6/P11
  dependency notes.
- `.planning/REQUIREMENTS.md` § "Venue Registry + Bundle (P5)" (VENUE-01..07, lines ~127-155) — authoritative
  requirement text incl. the §8a-f / LR-17 / CF-3/4/9 citations.
- `.planning/phases/04-storage-schema-migrations-relocation-new-durable-stores/04-CONTEXT.md` — the YAGNI /
  defer-to-real-consumer ethos (D-01/D-02/D-09) and the natural-name-identity principle (D-06) this phase reuses.

### The compose seam + backtest firewall (D-05)
- `itrader/trading_system/compose.py:114` `compose_engine(ctx, spec)` + `:175-181` — the mode-agnostic base
  graph that builds the `'simulated'` exchange for BOTH modes; the registry layers on top for live only.
- `itrader/trading_system/backtest_trading_system.py:374-378` — backtest reads the `'simulated'` exchange
  off the composed graph directly (never touches the registry).

### The branches to kill + resolvers to delete
- `itrader/trading_system/live_trading_system.py:541` (`if self.exchange == 'okx'`), `:625`
  (`elif self.exchange == 'paper'`), and the lifecycle guards at `:1378/:1751/:1778/:1817` — every
  venue-string branch VENUE-06 removes.
- `itrader/trading_system/live_trading_system.py:110-174` — `_precision_to_scale` + `_OkxPrecisionResolver`
  (+ the `_PrecisionResolver` Protocol) to delete/relocate (VENUE-04 / D-09).

### Plugin/connector seams (Area 1)
- `itrader/connectors/base.py` — the `LiveConnector` `runtime_checkable` Protocol (session/transport
  primitive: `call`/`spawn`/`client`/`sandbox`/`ws_hostname`/`connect`/`disconnect`); **CF-3 adds
  connector-contract docstrings here.** The `VenuePlugin`/`ConnectorPlugin` Protocols follow this shape.
- `itrader/execution_handler/exchanges/base.py` — `AbstractExchange` Protocol; `validate_symbol` already
  present, `resolve_precision` joins it (VENUE-04).
- `itrader/config/okx_settings.py` — `OkxSettings(BaseSettings)`: plain `OKX_API_*` env names (no `ITRADER_`
  prefix), `SecretStr` end-to-end, region-derives-both-hosts. Constructed **only inside** `build()` (D-04).
- `itrader/trading_system/system_spec.py:80` `SystemSpec` — gains `execution_venue` + `data_provider`
  selectors (VENUE-01); a single default `account_id` seam (D-07).

### StreamSupervisor donors (Area 4 / VENUE-07)
- `itrader/price_handler/providers/okx_provider.py:453-575` — the **canonical donor**: `_run_stream_supervisor`
  + `_escalate_connector_halt` + `_mark_stream_down` + `_on_stream_healthy` + `_reset_reconnect_budget`
  (WR-03 payload-only reset). Extract this behavior verbatim into `StreamSupervisor`.
- `itrader/portfolio_handler/account/venue.py:349` (TABS — "mirrors the OkxExchange donor") and
  `itrader/execution_handler/exchanges/okx.py:699` (TABS) — the two hand-copied forks to replace with delegation.
- `itrader/config/stream.py:33` `StreamSettings` — the reconnect-supervisor tuning (ceiling/debounce/backoff
  base/cap) the shared supervisor reads (folds the old `_STREAM_RECONNECT_*`, CF-4).

### CF-9 markets-map freshness (D-11)
- `itrader/execution_handler/exchanges/okx.py:1007-1032` `validate_symbol` (`_to_symbol(symbol) in
  client.markets`) — the D-06 removal path + the two staleness holes (stale cache; fail-open-before-load).
- `itrader/universe/universe_handler.py:20-97` — the `validate_symbol` → `delta.removed` removal contract.

### Gate references
- `tests/integration/test_okx_inertness.py` — the **P5 acceptance gate** (register-vs-build; registering
  `'okx'` pulls no `ccxt.pro`). Extend the register-vs-build assertion for the plugin/registry surface.
- `tests/integration/test_backtest_oracle.py` — byte-exact oracle (`46189.87730727451`); per-PLAN gate.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `okx_provider._run_stream_supervisor` (+ helpers) is the **near-complete `StreamSupervisor` body** — extract,
  don't rewrite. The other two donors are copies to delete.
- The `LiveConnector` / `AbstractExchange` `runtime_checkable` Protocols are the established swap-a-fake seam
  the new `VenuePlugin`/`ConnectorPlugin` Protocols mirror.
- Today's `if exchange=='okx'` block already constructs one `OkxConnector` and injects it into
  exchange/provider/account — the `ConnectorProvider` formalizes exactly this sharing.

### Established Patterns
- **Composition over inheritance:** `MatchingEngine`→`SimulatedExchange`, four managers→`Portfolio`. The
  `StreamSupervisor` is a has-a collaborator, not a mixin.
- **Lazy-import / inertness discipline:** the whole live stack lazy-imports inside its build arm; `test_okx_inertness.py`
  proves the backtest graph is `ccxt.pro`/async/SQL-free. Plugins keep imports inside `build()` (D-04).
- **Indentation hazard (bytes-per-file):** `connectors/base.py` is 4-space (new supervisor file is 4-space);
  `portfolio_handler/account/venue.py` + `execution_handler/exchanges/okx.py` are TABS. Delegation edits stay
  in each file's own indentation — never transplant a body across styles.
- **Scrub discipline (T-05-27 / V7):** connector logs carry the exception TYPE / a fixed label, never `str(exc)`
  (may carry request context / a secret); halt reason is the fixed `'connector-fatal'`.

### Integration Points
- The venue registry is invoked **only** by the live composition (`LiveTradingSystem.__init__` in P5 →
  `build_live_system` in P6), never by `build_backtest_system` — the byte-exact firewall.
- `assemble_venue(...)` is the single delegation seam `__init__` calls in P5 and `build_live_system` calls in P6.
- `ExecutionHandler.on_order` already routes by `event.exchange` and fans `on_market_data` over
  `self.exchanges.items()` — a plugin-built exchange registered under its venue name plugs in unchanged.

</code_context>

<specifics>
## Specific Ideas

- The discussion consistently favored the **most architecturally sound end-state over minimalism where the
  seam is load-bearing**, and **YAGNI-defer-to-the-real-consumer where it isn't**: explicit registration (not
  decorator magic), a dedicated `ConnectorProvider` (single recipe source, not duplicated lambdas), composition
  (not inheritance) for the security-critical supervisor — but single-account creds now with the multi-account
  scheme deferred to P11, and the venue-UID reconciliation deferred to P7/P11.
- The owner surfaced the **two-identifier insight** (logical config-name `account_id` for the memo key vs the
  venue-provided UID for reconciliation), which sharpened D-07 and produced a P7/P11 deferred idea.
- The **triple-deferral laziness** (D-04) is treated as correctness-critical, not stylistic — it's the single
  discipline that keeps both the inertness gate green and cred-less/backtest machines runnable.

</specifics>

<deferred>
## Deferred Ideas

- **Multi-account credential scheme + per-`PortfolioSpec` account_id (→ P11):** the `OKX_<ACCOUNT>_*` env-naming
  convention, a real `PortfolioSpec.account_id` field, and per-account credential dispatch land against the real
  multi-account consumer (MPORT-01/06). P5 only shapes the `(venue, account_id)` memo seam with one default account.
- **Venue-provided account-UID reconciliation (→ P7 / P11):** capture the exchange's own account UID post-`connect()`
  and assert it matches the intended logical `account_id` (a reconciliation safety check, distinct from the memo key).
- **Null-Object pattern for absent components — considered, rejected (D-10):** a branch-free `VenueLifecycle` via
  `NullConnector`/`NullAccount` was weighed and set aside in favor of explicit `None`-guards (fail-loud + matches the
  `Optional=None` bundle shape). Noted so it isn't re-litigated.

### Reviewed Todos (not folded)
- 14 generic keyword matches (shared-bar-history, multi-timeframe consolidator, synthetic-spread, single-pass
  portfolio valuation, mutable-instrument refactor, margin-equity WR-01, etc.) matched only on generic tokens
  (`open`/`phase`/`gate`) and are out of the venue-registry domain — reviewed, not folded.

</deferred>

---

*Phase: 5-Venue Registry + Bundle*
*Context gathered: 2026-07-10*
