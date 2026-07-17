# Phase 10: Strategies Registry ★ - Context

**Gathered:** 2026-07-17
**Status:** Ready for planning

> **Phase-resolution note (for the researcher/planner):** GSD `init.phase-op` returns
> `phase_found: false` for Phase 10 — the starred header (`### Phase 10 ★: Strategies Registry`)
> breaks `roadmap.get-phase`. Ground truth was injected manually: phase 10, name **Strategies
> Registry**, working dir `.planning/phases/10-strategies-registry/` (created this session),
> requirements **STRAT-01, STRAT-02, STRAT-03**, depends on Phase 4 + Phase 6. Ignore any null /
> `has_context:false` flags from init — they reflect the failed lookup, not this phase.

<domain>
## Phase Boundary

Make the live strategy roster **durable and runtime-mutable** (STRAT-01..03): wire the P4-built
`StrategyRegistryStore` into `build_live_system`, rehydrate the configured strategy **instances** on
restart, drive runtime add / remove / enable / disable / reconfigure / portfolio-subscribe via
`STRATEGY_COMMAND` (CONTROL), and persist every mutation.

**Live-only, backtest-dark.** Per-phase gates: the backtest oracle stays byte-exact
(`134 / 46189.87730727451`) and `tests/integration/test_okx_inertness.py` stays green.

**The load-bearing reframe of this phase (D-01):** the discussion converted "persist the strategy
roster" into an explicit **type-vs-instance split**. Strategy **types** are code (the owner's
proprietary strategies live in a **separate private repo, imported as a git submodule** by the future
FastAPI app); strategy **instances** are DATA and **the store is their source of truth**. Rehydrate
therefore *instantiates* instances from `store × catalog × codec` — it does NOT re-apply state onto a
roster hardcoded in composition code (that would make code, not the store, the source of truth — the
owner's decisive objection). This is a deliberate move to what an early draft called the "class
registry" model, reframed: the catalog holds **types**, not a runtime class-upload feature.

**Most of the surface already exists and is UNWIRED** — `StrategyRegistryStore` (P4, full persistence
API, constructed only in tests), `StrategyCommandEvent` (ticker verbs only), the `STRATEGY_COMMAND`
route slot + CONTROL bus tier, `reconfigure()`, `is_active`, `subscribe_portfolio`, `to_dict()`. P10 is
mostly **wiring + extending** these, not building from scratch. The P9 `ConfigRouter`/`VenueStore`
construct-in-factory + `_layer_persisted_overrides` restart-layering pattern is the template.

**Scope carved OUT by owner decision:** all `PairStrategy` runtime reconfiguration (D-17) and
finer-than-base timeframe changes (D-15) — both deferred to pending todos.

</domain>

<decisions>
## Implementation Decisions

### Rehydrate & instance reconstruction (Area 1 — the load-bearing decisions)

- **D-01 (Type catalog + instance store — the store is the source of truth for instances):** Strategy
  **types** come from code (the owner's private IP submodule); strategy **instances** live in the store
  and ARE the source of truth for what trades. A `strategy_catalog: dict[str, type[Strategy]]` is
  **INJECTED by the app** into the framework — `itrader` NEVER imports concrete strategy classes, so the
  IP stays in the owner's repo. Rehydrate = `for rec in store.list_active(): cls = catalog[rec.config["strategy_type"]]; add_strategy(cls(name=rec.strategy_name, **params))`. Runtime `add` uses the IDENTICAL
  path from a command payload. **Explicitly rejected:** the "state-only re-apply onto a code-declared
  roster" model (composition code would build the instances and the store would only toggle flags —
  making code the source of truth for instances). **Explicitly NOT in scope:** a UI/upload-python-file
  feature that adds new *types* to the catalog at runtime (a different axis — see Deferred).
- **D-02 (`strategy_name` is the per-instance durable identity — no new id field, store PK unchanged):**
  `name` is a per-instance kwarg (`base.py:186`, applied by `_apply_params`); a subclass pins a default
  (`"SMA_MACD"`) but each instance overrides it (`SMAMACDStrategy(name="sma_fast_btc", ...)`).
  `add_strategy` MUST **loud-reject a duplicate name** (a collision would silently overwrite another
  instance's persisted state). The existing `base.py:192` `strategy_id` (fresh UUIDv7 minted **per
  construction**) is **NOT restart-stable** and stays an ephemeral runtime/telemetry handle — keying
  durability on it would corrupt rehydrate (P4 D-06 already locked the natural name PK). **Instance = the
  unit of divergence:** different params, tickers, or policies → a distinct instance/row; only tickers
  sharing byte-identical params AND policies ride one instance's `tickers` list.
- **D-03 (Build a structured tagged-union serializer/deserializer NOW — separate from `to_dict()`):**
  `to_dict()` is a ONE-WAY observability snapshot — it serializes policies as `repr()`
  (`"FractionOfCash(Decimal('0.95'))"`), which is not reconstruction-safe (would need `eval`). The codec
  is its own contract. Sizing/SLTP policies are frozen dataclasses with Decimal/None fields, so use a
  **generic dataclass codec** (introspect `dataclasses.fields()`, coerce by declared type) plus an
  **injectable `kind → class` registry** — no per-class hand-written serializers; `__post_init__`
  re-validates on the way back. Polymorphic values self-describe: `{"kind": "FractionOfCash",
  "fraction": "0.95", "step_size": null}`. **Decimal fields round-trip AS STRINGS** via `to_money` /
  `Decimal(str)` — NEVER `Decimal(float)` (locked money policy; JSON has no Decimal). The policy-kind
  registry is injectable exactly like the catalog, so the app can register custom IP policies.
- **D-04 (`config_json` = the flat AUTHORING param set — not base-vs-strategy-specific):** The blob holds
  everything `cls(**config)` needs: `strategy_type` + ALL constructor-settable declared params
  (`tickers`, `timeframe` alias, `direction` `.value`, windows, tagged policy blobs, `allow_increase`,
  `max_positions`). The schema split that matters is **authoring vs derived vs runtime**, NOT
  base-vs-subclass: **derived** fields (`warmup`/`max_window` — D-08 auto-derives them; needs a
  `_DERIVED_FIELDS` exclusion marker) and **runtime** state (`is_active` → the `enabled` column;
  portfolio fan-out → its child table; `strategy_id` → regenerated) are EXCLUDED. Coercion on load is
  driven by the **class annotation** resolved via the catalog — `_declared_hints` merges base+subclass via
  MRO and `_apply_params`/`_COERCE` already coerce `timeframe`/`direction` from strings and reject
  unknown/missing loudly, so the codec never needs a base-vs-specific distinction. That split is
  presentation-only (derivable via `Strategy.__annotations__` vs the subclass's) and is NEVER stored.
- **D-05 (Placement — codec in `core/`, reconstruction in a `strategy_handler/` collaborator):** The
  **policy codec** lives in `core/` (next to `core/sizing.py` — it serializes core value objects, depends
  on nothing in `itrader`, obeys the money policy). The **instance reconstruction** (`build_strategy`:
  catalog × row × codec → `Strategy`) lives in a `strategy_handler/` collaborator (mirroring
  `order_handler/`'s `admission/`, `reconcile/` subdirs). It goes **NOT** in the `Strategy` base (pure-alpha
  #24 boundary — the base must not know about catalogs/stores) and **NOT** in `StrategyRegistryStore`
  (persistence-only; must not import strategy classes — also keeps inertness clean). The serialize side
  (`to_config()` on the base vs codec-side introspection) is planner's choice; the contract is that
  serialize/deserialize are symmetric and share the codec.

### Data model, verbs & enable/disable (Area 2)

- **D-06 (Data model — named instance table + portfolio-subscription child; two tables):** (1)
  **`strategy_registry`** (name kept, D-18): `strategy_name` PK · `strategy_type` · `config_json` (D-04
  blob) · `enabled` · `updated_at`. `enabled` stays **its own column, NOT inside `config_json`** — it is
  **runtime state** with a different lifecycle from authoring params (honours D-04) and keeps
  `list_active()` a `WHERE enabled=True` query instead of a JSON scan. (2) **`strategy_portfolio_subscriptions`**:
  `(strategy_name FK, portfolio_id)` composite PK — the fan-out edge. **Cardinality:** the engine runs ONE
  strategy object with `subscribed_portfolios` fanning out to N portfolios (NOT N objects — that would
  triple-compute and emit duplicate signals), so "same params on 3 portfolios" = **1 instance row + 3
  portfolio rows**; "different tickers" = a NEW instance row. Two granularities of off: whole-instance =
  the `enabled` column; per-portfolio = **row presence** in the child table. **`tickers` stay IN
  `config_json`** (an authoring param); symbol→strategy routing is derived **in-memory** at rehydrate.
  **DROP the P4 `strategy_subscriptions` (venue, symbol, timeframe) table** — premature/redundant: its
  columns are derivable from (the live venue, `config_json.tickers`, `config_json.timeframe`), a strategy
  has ONE timeframe and no per-ticker venue, its only unique job (a symbol→strategies reverse index) is an
  in-memory dict, and it is currently unwired (near-zero blast radius). Revisit only if per-symbol venue
  divergence (multi-venue strategies) is ever modelled. **Rejected:** per-`(instance, portfolio)` `enabled`
  (per-portfolio off = row presence; would need the fan-out to skip disabled portfolios) and a flat
  denormalized single table (config duplicated per portfolio + dedup-on-load + fuzzy addressing).
- **D-07 (enable/disable = the `is_active` gate, keep warm):** `calculate_signals` does **NOT** check
  `is_active` today — the flag is inert and P10 must wire it (`if not strategy.is_active: continue`).
  `disable` = `is_active=False` + persist `enabled=False`; the object STAYS in `self.strategies` and its
  indicators stay **WARM**, so `enable` trades the next bar with **no re-warmup**. Existing open positions
  and resting brackets keep running (managed to natural exit) — disable stops NEW entries only.
  **Rejected:** remove-from-list on disable (loses warm state; re-enable would pay a full 100/280-bar
  re-warm). **NOTE (oracle-gated):** this guard sits on the shared `calculate_signals` hot path — it is
  behaviour-preserving (`is_active` defaults True → never skips in backtest) but MUST be oracle-verified.
- **D-08 (Payload — extend `StrategyCommandEvent`, one CONTROL event type):** Add an optional
  `config: dict | None` payload field + a factory classmethod per verb. The event is a `msgspec.Struct`, so
  an optional field is backward-compatible. This is exactly what its own docstring anticipates ("the
  vocabulary grows to enable/disable/reconfigure later"). **Rejected:** separate typed events per command
  family (2–3 new event types + route slots + bus tiers for marginal typing gain).
- **D-09 (Verb set):** `add`, `remove`, `enable`, `disable`, `reconfigure`, **`subscribe_portfolio`**,
  **`unsubscribe_portfolio`** — plus the existing `add_ticker`/`remove_ticker`. Portfolio fan-out IS
  runtime-mutable (symmetric with the first-class edge in D-06): subscribe/unsubscribe mutate
  `strategy.subscribed_portfolios` live AND upsert/delete the child row. **Consequence:**
  `add_ticker`/`remove_ticker` must now ALSO persist `config_json` (a ticker change IS a reconfigure of the
  `tickers` authoring param) in addition to their existing `UniversePollEvent` follow-on; their
  `PairStrategy` CR-01 refusal stays. **Every verb persists.**
- **D-10 (`add` = catalog-gate, then add-dark and warm via the P7 gate):** `add` resolves
  `cls = catalog[strategy_type]` (**loud-reject** an unknown type or a duplicate name, D-02), registers,
  persists, then drives the EXISTING P7 pipeline: `spawn_warmup(symbol, tf, limit)` (async REST backfill)
  → returns immediately; the instance is registered but **DARK** (WR-02 gate, `is_ready` False) → `BarsLoaded`
  feeds the indicators → mark READY → trades. `BarsLoadFailed` → FAILED → CR-02 retry next poll. This works
  on a **cold** symbol and reuses `spawn_warmup → on_bars_loaded → WR-02 warm-verify` rather than inventing
  warmup code. **Rejected:** add-only-if-already-warm (would reject any genuinely new symbol — the common case).
- **D-11 (Lifecycle position semantics — three distinct behaviours):** `disable` → stop NEW entries, KEEP
  open positions + brackets (D-07). `remove` → **force-flat first** (reuse the P7 universe force-close →
  detach-on-flat machinery, `_on_symbol_removed`/`on_fill`), wait flat, THEN drop the object + delete the
  instance and portfolio-sub rows. `reconfigure` → apply live, KEEP positions (D-12). **Rejected:**
  orphaning positions on remove (a removed strategy's positions would become unmanaged).

### Atomic reconfiguration (Area 3 — STRAT-03)

- **D-12 (`reconfigure` applies live and KEEPS open positions):** No force-flat. The new config applies
  between cycles + re-warms; any open position's subsequent exits are governed by the **NEW** params —
  explicitly the operator's responsibility. **Rejected:** always-flatten (disruptive — a harmless sizing
  tweak would close positions) and param-classified flatten (policy-live / window-flatten).
- **D-13 (Ordering — validate → persist → apply → re-warm; adopts P9 `ConfigRouter` D-15):**
  **Trial-validate the FULL new config FIRST** (today `reconfigure` does `_apply_params` (setattr) →
  `validate()` → `_run_init()`, so a cross-field validation failure leaves a LIVE strategy **torn**;
  P10 tightens this so a bad reconfigure never half-mutates a trading strategy — this is what makes it
  *atomic*). Then **persist**, then apply + re-warm. Persist fails → reject, live untouched (DB and live
  never diverge in the applied-but-unpersisted direction). Persist OK but apply throws → log CRITICAL; the
  DB is correct and restart heals. Applied **between event cycles** (D-11 of the config work), never
  mid-cycle — in the single-writer engine-thread model that IS the "quiesce" (no in-flight signal mid-apply).
  **Rejected:** apply-then-persist (a persist failure would silently lose the change on restart).
- **D-14 (Re-warm semantics — reuse the `add` dark-then-warm path):** `_run_init` re-derives the new warmup
  depth. Window **grew** (needs more history than buffered) → the instance goes **DARK** and re-warms via P7
  `spawn_warmup` (same as D-10). Window **shrank or unchanged** (e.g. only `sizing_policy` changed) → still
  warm → trades immediately. **Documented consequence (not a blocker):** during a window-grow dark re-warm
  the instance cannot emit STRATEGY-driven exits, so an open position rides on its **resting exchange SL/TP
  brackets** until warm.
- **D-15 (Reconfigure allowlist — parallels P9 RTCFG-04):** **IMMUTABLE at runtime (loud reject):**
  `strategy_type` (changing the class IS a different strategy → `remove` + `add`). **Via dedicated verbs
  only:** `tickers` (`add_ticker`/`remove_ticker`, not `reconfigure` — one path per concern). **`timeframe`
  is CONSTRAINED-MUTABLE** (owner override of an initial immutable recommendation): reconfigurable to any
  value that is a **multiple of / coarser than** the feed's `base_timeframe` — mechanism is a plain re-warm
  on the new grid, no feed re-subscribe, no `min_timeframe` ripple (the stream is already up and streaming
  finer-than-needed is harmless). A change **FINER than the base cadence** (or a non-multiple) is
  **REJECTED** — it needs re-subscribing the SHARED live stream (see Deferred).
  **MUTABLE via `reconfigure`:** windows, `sizing_policy`, `sltp_policy`, `direction` (`validate()` re-runs
  the SHORT-01/D-07 registration gate), `allow_increase`, `max_positions`.

### Pair strategies (Area 4)

- **D-16 (Pairs ARE full registry instances):** A `PairStrategy` lives in `strategy_registry` like any
  other instance — the codec serializes its params (dataclass-agnostic), the catalog holds its class, `add`
  works (P7 warmup × 2 legs, 280 bars each, dark until `is_pair_ready()`), `remove` force-flats BOTH legs,
  `enable`/`disable` use the `is_active` gate, and it **REHYDRATES on restart**. Nearly free (the
  codec/catalog/lifecycle are type-agnostic) and load-bearing: pairs go live soon, so excluding them would
  mean pairs don't survive restart — gutting STRAT-01 for the pair case.
- **D-17 (ALL `PairStrategy` runtime reconfiguration is REFUSED in P10 — params AND leg-swap):** Extend the
  v1.7 CR-01 `isinstance(PairStrategy)` guard to the new `reconfigure` verb (loud, documented no-op). The
  owner initially preferred "allow pair params fully, same as single-leg"; **code evidence disproved that
  premise** and the owner revised to the total guard. **THE EVIDENCE — do not re-litigate without re-reading
  it (captured in the todo):** (1) `pair_base.py::_entry` sets **NO `stop_loss`/`take_profit`** — unlike the
  single-leg `base.py::_intent` — so an open spread has **no resting exchange bracket**; its ONLY exit path
  is `evaluate_pair()`, gated on `is_pair_ready()`. (2) `PairStrategy._run_init` **unconditionally**
  re-creates `_buf_A`/`_buf_B` and resets `_pair_bar_count = 0` (β re-fits from scratch), and `reconfigure()`
  ALWAYS calls `_run_init()` — so even a `sizing_policy` change (which leaves a single-leg strategy warm and
  trading) blanks a pair. (3) `is_pair_ready()` needs **280 bars**. **Net:** reconfiguring a pair holding an
  open spread would strand an unhedged, bracket-less spread with no reachable exit for 280 bars (~12 days on
  1h; 280 days on 1d). **Rejected:** a flat-gated allowance (safe but a half-capability) and auto-force-flat
  on reconfigure (that IS the deferred B2 flatten→wait→apply state machine). All pair reconfiguration lands
  next milestone as ONE unit — see Deferred.

### Naming (Area 5)

- **D-18 (Keep `strategy_registry` / `StrategyRegistryStore`; the code-side type set is `strategy_catalog`):**
  The rename case collapsed once the code side was named **`strategy_catalog` / `StrategyCatalog`** (owner's
  pick) — "registry" is no longer overloaded: **catalog = types (code)**, **registry = registered instances
  (DB)**. Keeping the name costs **no migration**, matches STRAT-01 + ROADMAP wording verbatim (no
  requirement-vs-code mismatch for downstream agents to flag), and keeps the phase name coherent.
  **Rejected:** `strategy` (off-convention — row-collection tables are plural: `halt_records`,
  `equity_snapshots`) and **`strategy_store`** (`*Store` is the CLASS convention — `VenueStore`,
  `SystemStore`, `HaltRecordStore`; no table is named `*_store`, and it would blur the table/class layers).
  New child table: **`strategy_portfolio_subscriptions`**. Dropped: `strategy_subscriptions` (D-06).

### Rehydrate failure semantics & schema evolution (Area 6)

- **D-19 (Per-instance QUARANTINE, not halt — fail-loud is reserved for wiring errors):** The owner's IP
  submodule evolves independently of persisted rows, so drift is a certainty. A **per-instance** failure —
  `strategy_type` missing from the catalog (class retired), or `config_json` won't deserialize
  (`UnknownParamError`/`MissingParamError` from param drift) — must **NOT** halt the engine: one stale row
  would block every healthy strategy (a self-inflicted outage from a data problem). Instead: **skip that
  instance, boot continues with the healthy ones, fire a CRITICAL alert via the existing `alert_sink`** (P8's
  CRITICAL/halt egress — the same channel a halt uses, NOT a buried warning) and surface it in the read-model
  (`state.last_error` / a quarantine list). "Skip" and "loud" are orthogonal — loudness comes from the alert
  channel, not from halting. **Do NOT mutate the row to `enabled=False`** — that would destroy the operator's
  declared intent (fix the class, restart, and it would stay dark until manually re-enabled); the DB holds
  INTENT, the runtime reports "couldn't load it", so fixing the class + restart brings it back on its own.
  **Infrastructure failure** (catalog not injected at all, store unreadable) → **fail loud** — that is a
  wiring bug, and booting with silently zero strategies would be worse.
- **D-20 (Stamp a `config_version` in `config_json` NOW; do NOT build a migration framework):** The classic
  cheap-now/impossible-later case — a version cannot be added retroactively to existing rows, and independent
  repo evolution makes drift certain. Stamp the version; when drift bites, it tells you what you are looking
  at and gives a migration somewhere to hang. The migration mechanism itself is out of scope for P10.

### Bootstrap & required test surface (Area 7)

- **D-21 (An empty registry is a VALID first-start state — no seed mechanism):** A fresh DB = zero strategies
  = the engine boots, trades nothing, and waits for instances. This is expected and accepted (owner: "I am ok
  to have 0 strategies in the db at the very first start"). No seed-from-config, no manual-DB-insert path.
- **D-22 (P10 MUST test the external add path as the FastAPI stand-in — P9 D-23 precedent):** With no FastAPI
  layer yet (LR-01) this surface would otherwise ship **untested** — exactly the gap P9 D-23 called out
  ("P9's own tests must drive the external `CONFIG_UPDATE` path directly so it isn't untested surface").
  `add_event`'s D-10 fail-closed allowlist **already admits `STRATEGY_COMMAND`**, so P10's tests drive
  precisely the path FastAPI will: `add_event(StrategyCommandEvent.add(...))` → admitted → catalog lookup →
  instantiate → persist → `spawn_warmup` → dark → `BarsLoaded` → ready → trades → **RESTART** → rehydrate from
  `store × catalog` → the same instance resumes. This full lifecycle is a **phase test requirement**.

### Claude's Discretion
- Exact codec module location/API and whether the `kind → class` policy registry auto-derives from the
  catalog or is a separate injected map (D-03/D-05).
- Whether the serialize side is a `to_config()` on the base or codec-side introspection (D-05).
- The exact `_DERIVED_FIELDS` marker mechanism for excluding `warmup`/`max_window` (D-04).
- Exact method names/signatures added to `StrategyRegistryStore` for the portfolio-sub child table, and the
  migration shape for dropping `strategy_subscriptions` + adding `strategy_portfolio_subscriptions` (D-06).
- Where `build_live_system` receives the injected `strategy_catalog` (new param vs a `SystemSpec` field).
- The `config_version` value/format (D-20) and the quarantine-list representation in the read-model (D-19).
- Wave/plan/commit granularity — P10 is large and likely wants decomposition (store wiring + rehydrate →
  codec + catalog → verb surface → reconfigure).

### Folded Todos
- **`.planning/todos/pending/pair-strategy-live-reconfiguration.md`** — **PARTIALLY folded, then
  re-targeted this session.** P10 builds the atomic-reconfiguration FOUNDATION (D-12..D-15) for single-leg
  strategies; the pair-specific work (params + B2 leg-swap) is DEFERRED to the next milestone (D-17). The
  todo's `resolves_phase` was changed `P10 → next-milestone` and its body now carries the P10 evidence.
  Supersedes the 2026-07-09 owner decision that brought it fully in-scope for P10.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **STRAT-01..03** (lines 268–279) + the milestone-wide gates (§15).
- `.planning/ROADMAP.md` → "Phase 10 ★: Strategies Registry" (goal + 4 success criteria, lines 387–399).

### Design source
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` **§9** (Strategies registry,
  lines 396–401 — the whole section is 6 lines; note it says subscriptions = "which **portfolios**" while the
  P4-built `strategy_subscriptions` table is `(venue, symbol, timeframe)`. **D-06 resolves this**: portfolio
  fan-out gets its own child table; the market-data table is dropped). **§4a** (CONTROL tier —
  `STRATEGY_COMMAND` is a CONTROL member), **§13c** (`LiveRouteRegistrar`).

### Prior-phase context this phase depends on / cashes forward
- `.planning/phases/09-runtime-config-platform/09-CONTEXT.md` — **D-24** (strategy config is OUT of
  `ConfigUpdateEvent`; STRAT-03 is driven by `STRATEGY_COMMAND` — the transport is already locked, do NOT
  re-route it), **D-15** (validate → persist → apply ordering, adopted by D-13), **D-23** (the
  no-FastAPI-driver test-the-external-path precedent, adopted by D-22), **D-25** (`config_json` JSONB per
  owning store), **D-21** (scope → owning store).
- `.planning/phases/04-storage-schema-migrations-relocation-new-durable-stores/04-CONTEXT.md` — the
  `HaltRecordStore` store template + the migration chain (`d10_halt_records → system_store → venue_config →
  strategy_registry`; P10's changes chain after), **D-06** (natural name PK — the basis of D-02).
- `.planning/phases/07-safety-reconciliation-stream-recovery/07-CONTEXT.md` — the warm-readiness pipeline
  (WR-02 gate, CR-02 FAILED-retry) that D-10/D-14 reuse.

### Existing code P10 wires / extends
- `itrader/storage/strategy_registry_store.py` — the P4 store: `build_strategy_registry_tables`,
  `upsert`/`set_subscriptions`/`get`/`delete`/`list_active`/`strategies_subscribed_to`/`read_all`. **Fully
  built, UNWIRED** (constructed only in `tests/unit/storage/test_strategy_registry_store.py`).
- `itrader/strategy_handler/strategies_handler.py` — `calculate_signals:141` (needs the D-07 `is_active`
  guard; `_dispatch_pair` branch at :166), `on_strategy_command:438` (ticker verbs only; CR-01 pair refusal
  at :491), `add_strategy:555` (SHORT-01/D-07 registration gate; `min_timeframe` at :603), `update_config:615`
  (the `{name: kwargs}` → `reconfigure(**kwargs)` surface), `_emit_intent` (per-portfolio fan-out).
- `itrader/strategy_handler/base.py` — `_COERCE:138` (`timeframe`/`direction`), `name:186`,
  `strategy_id:192` (ephemeral UUIDv7), `is_active`/`subscribed_portfolios:193-194`, `_apply_params:215`
  (resolve-into-local-dict then setattr; unknown/missing rejection), `validate:325`, `init:334`,
  `reconfigure:695`, `to_dict:713` + `_build_to_dict_snapshot:760` (the repr-based one-way snapshot — D-03),
  `subscribe_portfolio:974`, `activate_strategy:988`.
- `itrader/strategy_handler/pair_base.py` — `_run_init:144` (unconditional `_buf_A`/`_buf_B`/
  `_pair_bar_count` reset), `is_pair_ready:185`, `_entry:247` (**no sl/tp** — the D-17 evidence).
- `itrader/core/sizing.py` — `FractionOfCash:94`, `FixedQuantity:118`, `RiskPercent:138`,
  `LeveredFraction:162`, `PercentFromFill:209` — the frozen dataclasses the D-03 codec round-trips.
- `itrader/events_handler/events/universe.py:100` — `StrategyCommandEvent` (msgspec Struct; `add_ticker`/
  `remove_ticker` factories; its docstring already anticipates the D-08 vocabulary growth).
- `itrader/trading_system/live_trading_system.py` — `build_live_system:1260` (the composition root;
  `system_store` gate at :1386, the `ConfigRouter` + `VenueStore` + `_layer_persisted_overrides` block at
  :1510–1555 — **the template for D-01 rehydrate wiring**), `add_event:967` + the D-10 fail-closed allowlist
  at :57 (already admits `STRATEGY_COMMAND` — the D-22 ingress).
- `itrader/trading_system/route_registrar.py:106` — the `STRATEGY_COMMAND` → `on_strategy_command` route.
- `itrader/universe/universe_handler.py` — `spawn_warmup:508`, `on_bars_loaded:516`, the WR-02 warm-verify
  gate + CR-02 FAILED-retry (:383–394) — the D-10/D-14 pipeline.
- `itrader/price_handler/feed/live_bar_feed.py` — `base_timeframe:80-89`, the off-grid bar rejection
  (:263) — the D-15 timeframe constraint.
- `itrader/outils/time_parser.py:173` — `check_timeframe` (the strategy's timeframe alignment gate).

### Gates (must stay green — restated, not re-decided)
- `tests/integration/test_backtest_oracle.py` — byte-exact `134 / 46189.87730727451`. **Per-plan gate on the
  D-07 `calculate_signals` `is_active` guard** (the one shared-hot-path edit).
- `tests/integration/test_okx_inertness.py` — import inertness; the codec in `core/` and the catalog seam must
  stay SQL/ccxt-free, and `strategy_registry_store` imports must stay LAZY inside the live gate.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`StrategyRegistryStore` is complete and unwired** — full persistence API + the two-table registrar
  already exist (P4). P10 mostly **wires** it (plus the D-06 schema change), not builds it.
- **The P9 `ConfigRouter`/`VenueStore` block in `build_live_system`** (gated on `system_store is not None`,
  lazy imports inside the gate, degrades cleanly to no-op on the in-memory fallback) is the **exact template**
  for constructing `StrategyRegistryStore` + running rehydrate.
- **The P7 warmup pipeline** (`spawn_warmup` → `BarsLoaded`/`BarsLoadFailed` → `on_bars_loaded` → WR-02 gate
  → CR-02 FAILED-retry) is complete — D-10/D-14 wire it into `add`/`reconfigure` rather than inventing warmup.
- **The P7 force-close → detach-on-flat machinery** (`_on_symbol_removed`/`on_fill`) is the D-11 `remove` path.
- **`reconfigure()` + `_apply_params`/`_COERCE`/`validate()`/`_run_init()`** already give idempotent
  re-apply + re-validate + warmup re-derivation — D-13 only tightens the ordering (trial-validate first).
- **`add_event`'s allowlist already admits `STRATEGY_COMMAND`** — the D-22 external ingress needs no change.
- **`alert_sink` (P8 CRITICAL/halt egress) + the `state.*` read-model (RTCFG-06)** — the D-19 quarantine
  surfacing needs no new channel.
- **Sizing/SLTP policies are frozen dataclasses with typed Decimal fields** — a generic introspective codec
  (D-03) works without per-class serializers.

### Established Patterns
- **Indentation is SPLIT per file — measure bytes, never generalize the package.** `strategy_handler/` and
  `universe/` are **tabs**; `itrader/storage/` and `core/` are **4-space**; `trading_system/` is mixed
  (`live_trading_system.py` is 4-space but `compose.py`/`engine_context.py` are tabs).
- **Registrar = single source of truth** (`build_*_tables` feeds both the test `create_all` and Alembic
  `target_metadata`); schema-pure stores (WR-03/D-14 — never `create_all` at runtime); parameterized Core
  only (SEC-01); caller-supplied `at` via `UtcIsoText` (clock-free).
- **Loud rejection over silent no-op** — `UnknownParamError`/`MissingParamError`, the CR-01 pair guard, the
  D-10 fail-closed ingress. D-02/D-10/D-15/D-17/D-19 all follow it.
- **Import inertness (GATE-01)** — live/SQL imports stay LAZY inside `build_live_system` gates; never
  barrel-export the store.
- **Events are `msgspec.Struct`** (NOT the frozen `@dataclass` CLAUDE.md describes) — D-08's optional field
  follows the Struct rules.
- **Money is Decimal end-to-end**; enter via `to_money` (string path) — never `Decimal(float)`. D-03's codec
  is a money boundary.

### Integration Points
- `build_live_system` — construct `StrategyRegistryStore` (gated on the SQL spine, lazy import), receive the
  injected `strategy_catalog`, run rehydrate (D-01). **ORDERING CONSTRAINT: portfolios must rehydrate BEFORE
  strategies re-subscribe to them** (portfolio_ids are restart-stable, persisted by P4/P9).
- **RESEARCH RISK — `build_live_system` D-12 tension:** live session wiring is currently DEFERRED to `start()`
  because of "the pervasive add-strategy-after-construction + monkeypatch-`_initialize_live_session`-before-
  `start()` contracts across the live test suite." D-01's rehydrate CREATES strategies — the researcher must
  resolve **where** rehydrate runs against those existing contracts.
- `StrategiesHandler.calculate_signals` — the D-07 `is_active` guard (oracle-gated hot path).
- `on_strategy_command` — grows the D-09 verb branches; each persists.
- `add_event` → `STRATEGY_COMMAND` → `route_registrar` → `on_strategy_command` — the D-22 external path.

### Research Items (must resolve)
1. **The live feed's multi-timeframe model** — does `LiveBarFeed` aggregate base bars up to a strategy's
   coarser timeframe, or does each timeframe need its own subscribed stream? This pins the D-15 timeframe
   re-warm mechanism and the base-cadence constraint (and the shape of the deferred finer-than-base todo).
2. **Where rehydrate runs** vs the `build_live_system` D-12 deferred-session-wiring contracts (above).
3. **The `config_json` round-trip contract** — confirm `cls(**authoring_params)` is lossless for every shipped
   strategy, and pin the `_DERIVED_FIELDS` exclusion set.

</code_context>

<specifics>
## Specific Ideas

- **The owner's driving architecture:** proprietary strategies live in a **separate private repo, imported as
  a git submodule** by the future FastAPI app — so the IP never enters `itrader`. This drove D-01's injected
  catalog (the framework receives `dict[str, type[Strategy]]`; it never imports concrete classes) and D-03's
  injectable policy-kind registry (custom IP policies register the same way).
- **The owner's decisive catch (D-01):** *"if I do `handler.add_strategy(SMAMACDStrategy(name=..., ...))`
  from the FastAPI app at startup, doesn't this mean the strategies I have in my db are no longer the source
  of truth?"* — this killed the state-only model and forced the type-vs-instance split: *"we need to
  differentiate between the strategies available to trade (coming from my other repo with IP) and the
  instances of these strategies (the strategies I was already trading)."*
- **The owner chose to build the serializer/deserializer NOW** rather than defer non-scalar policy round-trip
  to class-attr defaults ("I'd rather build a serializer-deserializer logic now").
- **The owner challenged the `enabled`-vs-`config_json` split and the table count**, which produced the
  explicit authoring/runtime/relational split (D-04/D-06) and the deletion of the redundant
  `strategy_subscriptions` table.
- **The owner overrode the initial "timeframe immutable" recommendation** (D-15) — *"we already re-warm up
  when changing any other parameter anyway"* — correctly; the recommendation was refined to
  constrained-mutable rather than defended.
- **The owner's instinct to fail-loud-and-halt on rehydrate failure was self-checked** (*"isn't it too
  drastic?"*) and resolved to D-19's quarantine — loudness via the CRITICAL alert channel, not via halting.

</specifics>

<deferred>
## Deferred Ideas

- **All `PairStrategy` runtime reconfiguration — params AND the B2 ordered leg-swap** → next milestone.
  `.planning/todos/pending/pair-strategy-live-reconfiguration.md` (re-targeted this session:
  `resolves_phase: next-milestone`; body now carries the D-17 evidence). Deferred because P10 is already
  multi-wave and B2's flatten → **wait-until-flat** → swap sequencing spans event cycles (needs a pending-swap
  state machine, like pending-bracket / reconnect-resume) plus 280-bar × 2-leg fixtures ≈ 1–2 waves — better
  built ON the shipped P10 foundation, in the milestone where pairs actually go live.
- **Runtime timeframe change FINER than the feed's base cadence** → future.
  `.planning/todos/pending/strategy-timeframe-finer-than-base-resubscribe.md` (created this session).
  Requires re-subscribing the SHARED live stream + re-warming ALL affected instances + a `min_timeframe`-driven
  base recompute — a feed-lifecycle operation, not a single-instance reconfigure. P10 rejects it loudly (D-15).
- **Runtime addition of new strategy TYPES to the catalog** (a UI "upload a Python file" / operator-composes-a-
  strategy-class feature) — a **different axis** from P10's instance work. The owner explicitly deferred it
  ("I do not plan to have a UI create new strategies, at least not anytime soon"). When it lands it needs
  per-type param schemas to validate payloads. See [[fastapi-application-layer-plan]].
- **A `config_json` migration framework** — D-20 stamps a `config_version` now but builds no migration
  mechanism; revisit when class-vs-row drift actually bites.
- **DB-queryable "which instances trade symbol X"** — D-06 keeps `tickers` in `config_json` and derives
  symbol→strategy routing in-memory. If DB-level symbol queries are ever needed, promote `tickers` to a small
  `strategy_symbols` child table.
- **Persisted market-data subscriptions with per-symbol venue divergence** (multi-venue strategies) — the
  dropped `strategy_subscriptions` table's only real justification; revisit if a strategy ever needs
  per-ticker venue/timeframe.
- **Cross-restart signal analytics continuity** — a rehydrated instance mints a NEW ephemeral `strategy_id`
  (D-02), so signal records keyed on `strategy_id` won't group across restarts (`strategy_name` is the stable
  key). Pre-existing, not introduced by P10, but P10 makes restart a first-class flow — worth revisiting if
  signal analytics matter.

</deferred>

---

*Phase: 10-Strategies Registry ★*
*Context gathered: 2026-07-17*
