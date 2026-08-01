# Venue / Account / Composition Redesign — Design (v2)

**Status:** design document, v2 of 2026-07-29 against HEAD `297cee06`. Not a plan.
v2 incorporates the owner's review of v1 (package layout, and the removal of
`VenueMirror`, `VenueBundle`/`VenueBundles`/`VenueSpec`, and `FeedConnectionBinder`)
and re-grounds the venue-truth design on the adapter pattern used by NautilusTrader
and QuantConnect LEAN.
**Input:** `docs/VENUE-ACCOUNT-REDESIGN-REQUIREMENTS.md` (corrected in §2),
`11.2-REVIEW.md` (CR-01..CR-04 re-verified at HEAD, all four still present), the
comment-campaign todos, and the owner's decisions in §1.

Every factual claim about this codebase was verified against source at HEAD
`297cee06` during the design session.

---

## 1. Settled decisions (owner, 2026-07-29)

| # | question | decision |
|---|---|---|
| D-1 | §8.4 construction doctrine | **Adopt the three-part rule as stated**: (1) needs held state / injected collaborators → an object; (2) selects an implementation by key → a catalogue, and the selection is data, not a class; (3) only rearranges constructor arguments → delete it and call the constructor. Applies to everything in scope, including the four `*StorageFactory` classes. |
| D-2 | §8.4 vocabulary | **Factory + Catalog only.** `Authority`, `Plugin`, and callable `*_factory` fields are retired as names. A validating factory is a factory whose injected policy validates. |
| D-3 | §9.2 venue count | **Design for N venues/brokers.** The per-venue extension point and the catalogue are core product direction. |
| D-4 | §9.4 reconnect-resume escalation | **Alert, stay paused.** A reconnect snapshot failure raises a CRITICAL alert and keeps the reversible pause; retry on next stream-up; no automatic halt. |
| D-5 | §9.5 connector boundary | **Wiring-seam enforcement.** The raw `client` + `call`/`spawn` idiom stays; enforcement is structural at composition (only venue-substrate arms are ever handed a connector). `set_halt_signal` joins the Protocol. |
| D-6 | §8.3(b) credential model | **One model per venue, fields marked** secret vs. session-routing via field metadata. |
| D-7 | package layout (v2) | The two composition roots live in **`itrader/trading_system/backtest/` and `itrader/trading_system/live/`**. Domain code lives in its domain package, close to its consumer (adapters beside the handlers that use them, compute accounts in `portfolio_handler/account/`, factories beside what they build). No catch-all `itrader/live/` package. |
| D-8 | bundle / bundles / spec (v2) | **`VenueBundle`, `VenueBundles`, and `VenueSpec` are deleted.** What survives of the spec is a slim typed record of the `venue_accounts` row (§4.5). |
| D-9 | data-side pattern (v2) | The data feed follows the **same connector → adapter pattern as execution**, and lives in `price_handler/`. `FeedConnectionBinder` is deleted (§4.6). |
| D-10 | venue truth (v2, approved 2026-07-29) | **Adapter-owned account truth** (the Nautilus/LEAN pattern, §3.1): no `VenueAccount` leaf, no `VenueMirror` object — the per-account execution adapter serves venue snapshots. |

Pre-settled by the requirements document and carried forward: two composition roots,
SQL as restart truth, the must-have deletion gate, and all §4 hard constraints
(oracle, GATE-01, Decimal, determinism, queue-only writes).

---

## 2. Findings that reshape the problem

### 2.1 §9.1 answered: the venue-truth layer is fully inert in live today

Verified chain at HEAD:

1. `VenueValidatedComputeAuthority.account_for` **always** builds a compute leaf
   (`portfolio_factory.py:134-141`, the COMP-07 deferral).
2. Nothing performs the deferred swap. `_attach_venue_accounts` — the only mechanism
   that ever assigned a `VenueAccount` onto `Portfolio.account` — is deleted, and
   `tests/unit/trading_system/test_deleted_boot_helpers_gone.py:33` asserts it stays
   deleted. No runtime `portfolio.account = …` assignment exists anywhere.
3. The one seam that could mint a live `VenueAccount`
   (`VenueAccountManager.account_for`) has zero production callers.

Therefore `is_venue_truth` is `False` on every live portfolio, and everything gated
on it is skipped: the startup venue reconcile and `VenueReconciler`
(`reconciliation_coordinator.py:127`), the baseline-residual drift halt (`:212` —
`HaltReason.BASELINE_RESIDUAL` is unreachable), and the reconnect snapshot (doubly
inert: CR-03's never-written dict *and* no venue-truth account exists to iterate).

What still works in live: the durable ledger rehydrate, the exchange fill/order
streams, missed-fill catch-up, and the D-04 UID guard (lifecycle-level).

**Design consequence:** the venue-truth account behaviour exists only in unit tests.
There is nothing to migrate — venue truth is designed fresh (§4.4), and the
`VenueAccount`-as-`Portfolio.account` premise is dropped rather than completed.

### 2.2 Corrections to the requirements document

All verified at HEAD `297cee06` (the same HEAD the document's *(verified)* marks were
checked against — these are errors, not drift).

1. **The §1.1 baseline is not reproducible.** No coherent 27-file set yields
   8,781 raw / 3,968 code. The metric's label is also wrong — the §1 per-module table
   reproduces only when **all** docstrings are stripped, not just module docstrings.
   Re-frozen in §2.3.
2. **§8.3(c) per-account credential resolution is already built.** The
   `CredentialResolver` Protocol + `EnvCredentialResolver` (`env:<PREFIX>` scheme,
   fail-loud on zero matches, `SecretStr` end-to-end, delimiter-anchored matching)
   exist in `config/credential_resolver.py`; `OkxConnectorPlugin.build` consumes
   `spec.secret_ref`, completeness-gates the resolved mapping against
   `OkxSettings.model_fields`, and constructs per-account settings via
   `populate_by_name` (`venues/okx_plugin.py:98-162`). One of the three additions the
   deletion gate feared does not exist.
3. **§7.1's collapse is overstated.** A no-op `snapshot()` on the ABC does not delete
   the guards: four `VenueAccount`-only members sit behind them (`snapshot`,
   `start_streaming`, `connector`, `positions`). §4.4 dissolves the problem instead.
   Counts: 1 user-facing error message (not 2), 13 test references (not 12).
   `portfolio_handler.py:475`'s `getattr(..., "drop_pending", None)` is the same
   type-test in another disguise.
4. **§7.2's archaeology resolves to nothing.** The defensive `getattr` was born in
   the same commit as the ABC property; no caller ever handed that seam a
   non-`Account`. Delete without ceremony.
5. **§7.4 is only half-true.** The OKX `account_factory` closure is not a pure
   delegate: it closes over the per-account `VenueAccountConfig` and enforces a
   mismatched-`account_id` refusal (`okx_plugin.py:357-369`). §4.4's consolidation
   keeps that refusal in the adapter build.
6. **§4.2's circular-import suspicion is refuted.** `validators.py`'s lazy imports
   re-import a module already imported at top level; the three
   `portfolio_handler/*/manager.py` modules have no cycle. All are hoistable as-is.
   Census corrections: **115** body-imports (not 116), `live_trading_system.py`
   **49** (not 50), the OKX family **22** (not 18), and "the four
   `*/storage/storage_factory.py`" is three files of that name plus
   `registry_storage_factory.py`.
7. **CR-01..CR-04 all still present**, with nuances: CR-02 and CR-04 are *latent*
   (no runtime `bring_online`/`rebind` caller exists; boot-time invocations are
   covered by `start()` running afterwards), and CR-01's manager is not entirely
   dead (`assert_available` is reached via portfolio construction) — it is dead as
   an operator surface. CR-04's registry-identity claim is confirmed: `bring_online`
   writes the same dict object `ExecutionHandler.on_order` routes by.
8. Smaller: §8.4 says "three `*StorageFactory` classes", §8.1 lists four.
   `ConnectorPlugin` lives in `connectors/provider.py`, not `venues/bundle.py`.
   `StrategyRegistryStorageFactory` is not a pure switch. The §2.5 store-method
   lists omit the `dispose`/`get`/`delete`/`upsert` CRUD completions. The Scope list
   omits five files its own metrics include. `account/conformance.py`'s docstring
   describes the deleted `_attach_venue_accounts` as if it runs.

### 2.3 The re-frozen baseline (the must-have's yardstick)

Counting rule: **code lines = non-blank lines that are not comments and not inside
any docstring** (module, class, or function — the rule that reproduces the
requirements document's own per-module table). Raw lines = `grep -c ''`.

File set: the 19 paths the requirements Scope names explicitly, plus the eight files
its own metrics include — `venues/venue_account_manager.py`,
`venues/venue_uid_guard.py`, `connectors/okx.py`, `connectors/stream_supervisor.py`,
and `portfolio_handler/account/{base,conformance,simulated,venue}.py`. 27 files.

| metric | value at HEAD `297cee06` |
|---|---:|
| files | 27 |
| raw lines | **9,243** |
| code lines | **3,886** |

The gate: at the end of the refactor, the same measurement over the successor files
(everything that replaces, absorbs, or renames these 27, plus any new module the
redesign introduces) must be **lower**. Tests excluded, and expected to grow.

---

## 3. Architecture

### 3.1 The organizing pattern: two adapters per venue, truth on the adapter

This is how the reference systems structure the same problem. NautilusTrader gives
each venue an integration made of a **data client** and an **execution client** over
one session; the execution client is the venue-truth source — it emits order-status,
fill, and account reports, and the execution engine coordinates startup and
continuous **reconciliation across execution clients**. LEAN's `IBrokerage` carries
both order operations and `GetAccountHoldings()` / `GetCashBalance()`, and the
`BrokerageSetupHandler` seeds the live portfolio from the brokerage at startup. In
neither system is venue account truth a separate account object, a mirror object, or
a portfolio leaf — **it lives on the venue adapter, and flows from there**.

iTrader already has both adapters; they just aren't named or completed as such:

- **execution adapter** = `execution_handler/exchanges/okx.py::OkxExchange` — one per
  `(venue, account_id)`, holds the connector, spawns the fill/order streams, owns the
  correlation index. It gains the account-truth surface (§4.4).
- **data adapter** = `price_handler/providers/okx_provider.py::OkxDataProvider` — one
  per data source, holds a session, streams bars into the one live feed (§4.6).
- backtest/paper: `SimulatedExchange` is the execution adapter; the CSV/replay feed
  is the data side. Same seams, no session.

Everything v1 still carried between the connector and the adapters —
`VenueBundle`, `VenueBundles`, `assemble_venue`, `VenueLifecycle`, `VenueSpec`,
`FeedConnectionBinder`, `VenueAccount`/`VenueMirror` — existed to ferry build outputs
and account truth *around* the adapters. With truth and lifecycle **on** the
adapters, the ferrying layer has no cargo. All seven are deleted (§4, §8).

### 3.2 Package layout (D-7): roots under `trading_system/`, domain code at home

```
itrader/trading_system/
    backtest/                      # backtest composition root (+ runner); oracle-locked
    live/                          #   live composition root: build, bootstrap, facade
    graph.py                       # build_handler_graph — pure, mode-blind (§4.8)
itrader/connectors/                # LiveConnector Protocol, ConnectorPool, okx.py,
                                   #   stream_supervisor  (live-only by import graph)
itrader/venues/                    # catalog.py — VenueCatalog descriptors (inert data)
                                   # accounts.py — VenueAccountManager + AccountSpec
                                   #   + the TOFU identity check  (live-only)
itrader/execution_handler/exchanges/
    simulated.py                   # unchanged
    okx.py                         # execution adapter + its build recipe + account truth
itrader/price_handler/providers/
    okx_provider.py                # data adapter + its build recipe (§4.6)
itrader/portfolio_handler/account/ # compute leaves ONLY + build_compute_account()
                                   #   (venue.py deleted; conformance.py rewritten)
```

**GATE-01 becomes a named import-graph boundary, not one package.** The inertness
test is extended to assert the backtest graph imports **none of**:
`itrader.trading_system.live`, `itrader.connectors`, `itrader.venues.accounts`,
`itrader.execution_handler.exchanges.okx`, `itrader.price_handler.providers.okx_*`,
`itrader.storage`. Inside those modules every import sits at the top of its file —
the lazy imports are deleted, not relocated (per §2.2.6: GATE-01 body-imports die
via the boundary; vestigial ones are hoisted; genuinely-optional ones stay as the
documented exception). `itrader/venues/catalog.py` stays inert (descriptors pull
only pydantic-settings) so a web layer or CLI can read it with zero ccxt/SQL cost.

Because live modules name real types at the top of real files, the `Any`-typed
wiring seam dies with the lazy imports: the live root is written strict-clean from
its first commit, the `live_trading_system` `ignore_errors` override is removed, and
no new module enters the override list.

### 3.3 Two roots, one pure graph builder

`compose_engine` is demoted to `trading_system/graph.py::build_handler_graph(ctx, …)`:
it constructs the handler graph from required, real arguments — no `Optional`
mode-selectors, no mode branching, no knowledge that live exists. Each root calls it
with concretions it chose itself. The backtest root carries the byte-exact oracle
assertion from its first restructured commit; the `Engine` holder survives as the
return type.

### 3.4 Reference-system patterns: adopted, deferred, deliberately rejected

Surveyed against NautilusTrader and LEAN so each borrowing (and each refusal) is a
decision, not an accident:

**Adopted by this design:** per-venue data + execution adapters over one session
(§3.1); account truth on the execution adapter, snapshot-based (§4.4, D-10); adapter
factories as per-venue recipes selected from a catalogue (§4.3 — LEAN's
`IBrokerage`/`IBrokerageFactory` pairing, Nautilus's client factories); startup
reconciliation coordinated centrally across adapters (§4.4 — Nautilus's execution
engine role, already iTrader's `ReconciliationCoordinator`).

**Deferred, with the seam left ready:**

- **Continuous reconciliation** (Nautilus: periodic open-order polls, in-flight-order
  age checks, interval position checks — not just startup). iTrader has startup
  reconcile + reconnect catch-up only. Not built now (no requirement names it, and it
  adds source against the gate), but the v2 shape makes it cheap later: a periodic
  re-run of the §4.4 snapshot-compare over the manager's records, riding the existing
  poll timer. Leave `run_startup_reconcile`'s compare logic factored so a future
  periodic caller reuses it rather than duplicating it.
- **A `REDUCING` trading state** (Nautilus's risk engine supports reduce-only mode:
  new exposure blocked, position-reducing orders pass). iTrader has halt (total) and
  pause-submission (total, reversible); a degraded middle state is a plausible future
  operator affordance after drift or during recovery. Deferred: no current consumer,
  and it belongs to a `SafetyController` phase, not this one (§9).

**Deliberately rejected:**

- **Seeding the live portfolio from the venue at startup** (LEAN's
  `BrokerageSetupHandler` pulls holdings/cash from the brokerage and adopts them).
  iTrader's model is the opposite by design: SQL is restart truth, the engine trades
  only exposure it can explain, and the baseline-residual guard **halts** on
  unexplained venue holdings rather than adopting them (ACCT-10). This divergence is
  intentional and stays — recorded here so LEAN familiarity doesn't re-import it.
- **A central cache as the data spine** (Nautilus's message-bus + cache). iTrader's
  read-model seams and durable stores fill that role; introducing a cache layer would
  be a second source of truth, the exact defect class §5.2 of the requirements bans.

---

## 4. Components

Vocabulary (D-2): a **Factory** holds real dependencies and builds a non-trivial
object graph; a **Catalog** is keyed data you select from. §5 names every
constructing object against the D-1 rule.

### 4.1 What survives untouched

Handlers, events, the queue, the matching engine, fee/slippage models, the feeds,
the stores' internals, `SafetyController`, `StreamSupervisor`, `SessionInitializer`
(its two lazy imports hoisted), the migration chain, and the `CredentialResolver`
seam (§2.2.2 — already correct).

### 4.2 Connector layer: Protocol + ConnectorPool

`LiveConnector` keeps its seven members and gains `set_halt_signal` (D-5) — the
declared surface becomes the whole surface. The boundary contract (D-5) is a rule of
the composition root, not a wrapper: *connectors are handed only to adapters and the
identity check, at build time; the pool is never attached to the facade and never
barrel-exported.* The idiom — name coroutines off `client`, execute only through
`call`/`spawn` — is the threading contract, tested once generically.

`ConnectorProvider` splits along its three fused roles: the catalogue half (name →
build recipe) moves to `VenueCatalog`; the one-line factory half dissolves into the
pool's miss path; the stateful part becomes **`ConnectorPool`** — the
`(venue, account_id)` memo, the session-identity conflict guard
(`secret_ref`/`sandbox`/`region`, unchanged), and `close_all()` as the run-scoped
teardown owned by the composition root (fixing WR-06: per-account teardown
disconnects only its own connector).

New: `pool.public_session(venue)` — an unauthenticated session (loop + client, no
credentials) for data adapters that declare they need none (§4.6). Public sessions
are memoized per venue and carry no identity to conflict.

### 4.3 The catalogue: inert descriptors, recipes beside their adapters

`itrader/venues/catalog.py` holds **`VenueDescriptor`** — a frozen dataclass:
`name`, `credential_model: type | None`, `capabilities:
frozenset[{EXECUTION, PUBLIC_DATA, PRIVATE_DATA}]`, `data_requires_auth: bool`,
`default_data_provider: str`. It answers "what venues exist, what can each do, what
does each need?" as data, without constructing anything, importable anywhere. The
UID-check's model/`None`/raised triple survives verbatim, keyed off the descriptor.
Credential marking (D-6) is field metadata on the one settings class per venue
(`json_schema_extra={"kind": "secret" | "routing"}` on `OkxSettings` fields).

**Recipes are plain module-level build functions living beside what they build**
(D-7): `build_okx_exchange(...)` in `execution_handler/exchanges/okx.py`,
`build_okx_data_provider(...)` in `price_handler/providers/okx_provider.py`,
`build_okx_connector(...)` in `connectors/okx.py`, `build_compute_account(...)` in
`portfolio_handler/account/`. The catalogue maps venue name → recipe set; the three
`*Plugin` Protocols, both `*Registry` classes, and `paper_plugin.py`/`okx_plugin.py`
as modules are deleted — per D-1 rule 2 the selection is a dict lookup, and the
plugins' lazy-import ceremony was only ever the missing boundary (§3.2).

### 4.4 Venue account truth lives on the execution adapter (D-10)

The Nautilus/LEAN answer to "do I really need a `VenueMirror`?" is **no — and no
`VenueAccount` either**. The per-account execution adapter already holds the
authenticated session, the halt wiring, and the fill/order streams; account truth is
one more read on the same session:

- `OkxExchange` gains **`snapshot() -> AccountSnapshot`** — a frozen value object
  (balances, positions as `Decimal`) fetched via `connector.call(fetch_balance /
  fetch_positions)`. This is `account/venue.py`'s REST logic moving ~60 lines into
  the adapter that already owns its connector; the RLock-guarded cache and the
  balance/position **websocket streams are not carried over** — their only consumers
  were the inert venue-truth layer (§2.1), and LEAN's brokerage seeding is
  snapshot-based too. If a streaming-balance consumer ever exists, it is added to
  the adapter then, as an event producer.
- `Portfolio.account` is **always a compute leaf**, in both modes — which is what
  production already does (§2.1). The `Account` ABC stays compute-shaped;
  `is_venue_truth`, both guards, the `getattr` scar, `drop_pending` probing, the
  COMP-07 deferral machinery, and `account/venue.py` are deleted.
- **Reconciliation consumes adapters, not accounts.** `ReconciliationCoordinator`
  and the baseline-residual guard iterate the venue-account manager's online records
  (§4.5) — per record: `adapter.snapshot()`, reconcile the order mirror, then
  compare engine positions (portfolios found via the definition store's
  `(venue_name, account_id)`) against the snapshot. Distinct-by-construction — both
  identity-dedup loops (§7.3 of the requirements) are deleted. `VenueReconciler`
  takes an adapter + snapshot instead of a `VenueAccount`.
- `StreamRecoveryHandler` is constructed with the manager's record enumeration —
  the CR-03 defect class (a mirrored container nothing writes) becomes unwritable.
  Per D-4, a failed reconnect snapshot raises a CRITICAL alert and stays paused.

**The TOFU identity check survives; the module does not.** `venue_uid_guard.py`'s
job — on first connect, fetch the venue's account UID, record it; on later connects,
refuse a mismatch (wrong-account protection) — is real safety and is kept, collapsed
to a function in `venues/accounts.py` invoked from `bring_online` between connect
and registration. Its reasons-taxonomy stays (it distinguishes a credential-less
venue's legitimate missing UID from a credentialed venue's broken endpoint, keyed
off the descriptor's `credential_model`); its standalone-module scaffolding does not.

### 4.5 The venue-account domain: one manager, one routing map, a slim record

`itrader/venues/accounts.py` holds:

- **`AccountSpec`** — a frozen record of one `venue_accounts` row: `venue_name`,
  `account_id`, `secret_ref`, `sandbox`, `region`, `market_type`, config overrides.
  This is what remains of `VenueSpec` (D-8): the typed in-memory form of the durable
  row, nothing more. The execution-venue/data-provider axis fusion is gone — the
  data side is configured per venue via the catalogue, not per account (§4.6).
- **`VenueAccountManager`** — the domain owner: `provision` / `set_enabled` /
  `bring_online` / `bring_offline` / record enumeration, over the stores, the pool,
  and the catalogue recipes. It absorbs `assemble_venue` and the `VenueLifecycle`
  object — lifecycle verbs act on the manager's own `OnlineAccount` records
  (`AccountSpec` + adapter + UID outcome), each tearing down **its own** connector
  only (WR-06).

**`bring_online` is registration-last** (CR-04): resolve `AccountSpec` → validated
config merge → `pool.session(...)` → build execution adapter via recipe →
`adapter.connect()` (spawns fill/order streams) → TOFU identity check → wire halt +
stream-state → **only then** write the routing map and the online record. A failure
at any earlier step leaves the pair unroutable; a test injects a raising connect and
asserts the routing map is empty. Boot-time and runtime bring-up are the same path —
`start()` stops re-doing per-account bring-up and performs engine-level I/O only.

The routing map is the **execution registry that already exists** (the
`(venue, account_id) → adapter` dict `ExecutionHandler.on_order` reads). The manager
is its only writer; `VenueBundles`' second memo is deleted (D-8) — one map, one
writer, one reader.

Write-time validation (WR-01/WR-02): `provision()` runs the config allowlist/value
checks before persisting; `set_enabled` asserts the row exists. The boot loop
quarantines a row whose bring-up fails (skip + CRITICAL alert) rather than aborting.

**Reachability (CR-01):** `LiveTradingSystem.__init__` takes every collaborator —
the manager included — as a required, really-typed constructor parameter. No
post-construction attach, no `Optional` collaborator. The facade exposes
`venue_accounts` (the manager) — the operator surface the refusal messages promise.

### 4.6 The data side follows the same pattern (D-9) — and the binder dies

Symmetry with §4.4: connector → adapter, chosen from the catalogue, wired at
composition, living in `price_handler/`.

The live root reads the configured data venue, consults its descriptor, and builds
**one data adapter** via the venue's recipe: with `pool.public_session(venue)` when
`data_requires_auth=False` (OKX candles are public — fetching them no longer
requires naming a credentialed account, which also decouples research/backtest data
acquisition from the credential path), or with an authenticated session when the
descriptor declares `True`. The adapter is halt-wired and stream-state-wired at
build, bound to the one `LiveBarFeed`, and subscribed by `start()` as today.

`FeedConnectionBinder` existed for exactly one scenario: the feed *borrowing* some
account's authenticated connection, and re-borrowing another when that account
retires. With the data adapter on its own (usually public) session, there is nothing
to borrow and nothing to re-borrow: an account retiring affects order routing only,
never the bar feed. **CR-02 (the half-wired re-borrowed provider) becomes
unrepresentable rather than fixed.** Data-session failover on disconnect remains
what it already is — `StreamSupervisor`'s reconnect job. A future private-data
stream (`PRIVATE_DATA` capability) attaches to that account's adapter, not to the
shared feed.

### 4.7 Portfolio construction: one factory, one account function

The two `*Authority` classes merge into the injected policy of **`AccountFactory`**
(D-1/D-2): it holds `build_compute_account` (the one compute-leaf constructor in
`portfolio_handler/account/`) and an optional `validate` callable; the live root
passes `manager.assert_available`, the backtest root passes none. `PortfolioFactory`
is unchanged in role and keeps its real mapping; with `VenueBundles` gone it no
longer routes leaf construction through a venue memo at all — the compute leaf is
built directly. `add_portfolio` validates/materializes **before** the durable
insert (WR-03).

### 4.8 The restart bootstrap: extracted, ordered, per-row isolated

`trading_system/live/bootstrap.py::bootstrap_session(...)` is the single home of the
requirements-§3 sequence, preserved exactly:

1. Probe the `portfolios` table (absent = first start, warn not fault; any other
   store fault propagates loud).
2. `assert_distinct_accounts(persisted=definition_store.read_all())` — before any
   account object exists.
3. Venue assembly: per enabled row, `manager.bring_online(row)` (§4.5,
   registration-last) with per-row quarantine; a zero-streaming boot logs its cause.
4. `rehydrate_portfolios(...)` with persisted ids — **after** step 3, and checkable:
   the live `AccountFactory.validate` consults the manager's online records, so
   rehydrating before bring-up fails loudly at the first portfolio. A single
   unmaterializable row is quarantined (skip + CRITICAL) rather than aborting boot.

Per-entry failure isolation keeps today's granularity (the acquisition guard and the
per-entry guards stay separate); the config-layering pass moves here intact. **Live
requires the SQL spine** — the live root refuses to build without one, which deletes
WR-07's silent-degradation configuration and the `definition_store`
`None`-then-assign shape: the live `PortfolioHandler` holds a real store at
construction; the backtest handler's type has none.

### 4.9 The live root and facade: initialisation as one readable page

`trading_system/live/` holds three modules — `build.py` (the composition function),
`bootstrap.py` (§4.8), `system.py` (the facade) — and the whole initialisation is
one linear function whose body reads as the architecture diagram. Illustrative
shape, not final code:

```python
# trading_system/live/build.py
def build_live_system(config: ITraderConfig) -> LiveTradingSystem:
    # 1. Durable spine — REFUSES to build without SQL (§4.8; kills WR-07).
    stores = build_stores(config.sql)

    # 2. Sessions + venue domain. One pool, one manager, one routing map.
    pool     = ConnectorPool(CATALOG, resolver=EnvCredentialResolver())
    routing  = {}                                   # (venue, account_id) -> adapter
    accounts = VenueAccountManager(CATALOG, pool, stores, routing=routing)

    # 3. The mode-blind handler graph (§3.3) — real args, no Optionals.
    engine = build_handler_graph(ctx, portfolio_factory=..., exchange_registry=routing, ...)

    # 4. Safety plane. Recovery enumerates the manager — no mirrored dicts (CR-03 dead).
    safety   = SafetyController(halt_store=stores.halt, ...)
    recovery = StreamRecoveryHandler(safety, accounts=accounts.online_records, ...)

    # 5. Data plane (§4.6): one adapter, its own (usually public) session,
    #    halt-wired at build. No binder, no borrowing (CR-02 dead).
    feed_adapter = build_data_feed(config, CATALOG, pool, engine.feed, halt=safety.halt)

    # 6. Session wiring (universe, routes) — construction-time, as today.
    universe = SessionInitializer(engine, safety=safety, stream_recovery=recovery,
                                  data_provider=feed_adapter, ...).initialize()

    # 7. Restart truth (§4.8): probe → distinct-accounts → bring_online loop
    #    (connect, TOFU check, wire, register LAST — CR-04 dead) → rehydrate.
    bootstrap_session(stores=stores, accounts=accounts,
                      portfolios=engine.portfolio_handler, config=config)

    # 8. The facade. EVERY collaborator is a required ctor arg — a built-but-unattached
    #    collaborator is a TypeError, not a silent success (CR-01 dead).
    return LiveTradingSystem(engine=engine, accounts=accounts, pool=pool,
                             safety=safety, recovery=recovery,
                             feed_adapter=feed_adapter, universe=universe,
                             stores=stores)
```

What makes this simpler than today's `build_live_system`, structurally rather than
cosmetically:

- **Linear and typed.** Eight steps, each building one thing with real types at
  top-of-file imports (the boundary makes that legal). No lazy-import blocks, no
  `Optional` collaborators, no locals that exist only to be captured by lambdas, no
  post-construction `facade._x = …` attach loop — today's ~15 late attachments are
  what made CR-01 possible.
- **One bring-up path.** The bootstrap's per-row loop and runtime provisioning call
  the same `accounts.bring_online(row)` (§4.5). `start()` therefore stops re-doing
  per-account work — today it performs connect/guard/wiring for every lifecycle
  *after* boot registered them, which is exactly the boot-masks-the-unsafe-ordering
  arrangement CR-04 exposed.
- **Lifecycle verbs shrink to engine-level I/O.** `start()`: spawn the processing
  thread → warm + subscribe universe members → run the startup reconcile on the
  engine thread → status RUNNING. `stop()`: drain → `accounts.bring_offline(...)`
  per record (each tears down only its own connector, WR-06) → `pool.close_all()`
  (the one run-scoped teardown) → status STOPPED.
- **The facade is a facade again.** `system.py` keeps status/safety delegation,
  `add_event` ingress, and the operator surfaces (`venue_accounts` = the manager),
  and holds no composition knowledge at all.

---

## 5. Doctrine inventory (D-1 applied to every constructing object)

| current | rule applied | becomes |
|---|---|---|
| `PortfolioFactory` | rule 1: holds real deps, real mapping | **stays** |
| `ComputeAccountAuthority` + `VenueValidatedComputeAuthority` | rule 1, pair differs by one call | **`AccountFactory`** with injected `validate` (§4.7) |
| four `*StorageFactory` classes | rule 2: stateless key-switches | **functions** selecting from data |
| `VenuePlugin` / `DataProviderPlugin` / `ConnectorPlugin` + both `*Registry` classes | rule 2 | **catalogue**: descriptors + recipe functions beside their adapters (§4.3) |
| `ConnectorProvider` | three-way split | catalogue → `VenueCatalog`; factory → pool miss-path; state → **`ConnectorPool`** |
| `VenueBundle.account_factory` field | rule 3 | **deleted** with the bundle itself (D-8) |
| `VenueBundle` / `VenueBundles` | ferrying layer, no cargo (§3.1) | **deleted**; the execution registry is the one map (§4.5) |
| `assemble_venue` + `VenueLifecycle` | rule 3 + lifecycle-on-record | **absorbed** into `VenueAccountManager` |
| `FeedConnectionBinder` | scenario deleted (§4.6) | **deleted** |
| `build_live_system`, backtest root | composition roots, stateless | **functions**, exempt from object-ification |

### Adapter contracts (the N-venue extension point, D-3)

Adding venue N+1 means: one descriptor, one connector recipe, one execution adapter
(implementing `AbstractExchange` + `snapshot()`), one data adapter (implementing the
provider seam), one settings class with marked fields. Nothing else changes — no
registry class to touch, no bundle to define, no plugin Protocol to satisfy.

---

## 6. Failure modes → structural properties

| requirements §5 | structural answer |
|---|---|
| 5.1 built-but-unreachable (CR-01) | every facade collaborator is a required constructor parameter; reachability asserted by the §7 composition test |
| 5.2 mirrored container nothing writes (CR-03) | no mirrored containers exist; recovery and reconcile enumerate the manager's records at use time (§4.4) |
| 5.3 routable-before-connected (CR-04) | routing-map write is the last statement of `bring_online`, after connect + identity check + wiring + streams (§4.5) |
| 5.4 abandoned resource (CR-02) | the borrow scenario itself is deleted (§4.6) — a data adapter owns its own session for its whole life |

Hard constraints: the oracle is asserted on the restructured backtest root from its
first commit; GATE-01 is the named import-graph boundary (§3.2) enforced by the
extended inertness test; money stays Decimal (`AccountSnapshot` carries `Decimal`;
this design touches no arithmetic); determinism seams are untouched
(`EngineContext.rng`, injected clock, one seeded RNG reaching `SimulatedExchange`);
queue-only writes and the single-writer contract are untouched (connector callbacks
still flip flags only; venue I/O stays on the engine thread — `snapshot()` is called
from the engine thread through `connector.call`, exactly as the fill catch-up is
today).

---

## 7. Test strategy — the root cause gets the fix, not just the design

The four Criticals shared one cause: the assembled system is never built in a test.
Gates, present from the first commit of the new shape:

1. **Offline live-composition test.** Build the complete live system end-to-end with
   the paper venue, an in-memory/SQLite SQL spine, and a fake resolver; no
   credentials, no network. Assert the wiring, not the units:
   `system.venue_accounts.provision(...)` → `bring_online` → a portfolio
   materializes over it → an order routes only after bring-up completes → the
   recovery handler's enumeration is **non-empty** → teardown closes exactly the
   built sessions.
2. **The production-builder question as a checklist.** For each value a safety path
   consumes (record enumerations, halt wiring, subscribed symbols, snapshot
   plumbing), one assertion that the *production builder* produces it — the shared
   lesson of `liquidation_fee_rate`, `venue_accounts`, and CR-01..04.
3. **Oracle gates**: both existing oracle tests stay green throughout; the backtest
   root's restructure lands with the byte-exact assertion in the same commit; a
   third construction path, if one ever appears, gets its own assertion on day one.
4. **Boundary gates.** The extended inertness test (no live-set module on the
   backtest graph, §3.2); `mypy --strict` over the live modules with the old
   override removed.
5. **Ordering gates.** Raising connect ⇒ empty routing map; rehydrate before
   bring-up ⇒ loud failure; identity-check mismatch ⇒ unroutable + alert.

---

## 8. The deletion ledger

Against the re-frozen baseline (27 files, **3,886 code lines**, §2.3). Estimates are
code lines by the §2.3 rule; the gate is settled by re-measurement, not this table.
v2 deletes substantially more than v1 because the ferrying layer goes entirely.

**Deleted outright (measured today):**

| module | code lines |
|---|---:|
| `venues/bundle.py` | 41 |
| `venues/bundles.py` | 39 |
| `venues/assemble.py` | 41 |
| `venues/lifecycle.py` | 79 |
| `venues/feed_binder.py` | 66 |
| `venues/registry.py` | 29 |
| `trading_system/venue_spec.py` (→ ~15-line `AccountSpec`) | 32 |
| `venues/paper_plugin.py` (→ small recipe functions) | 63 |
| subtotal | **390**, of which ~40 return as `AccountSpec` + paper recipes |

**Reduced (estimates):**

| item | est. Δ |
|---|---:|
| `live_trading_system.py` → `trading_system/live/` (facade keeps lifecycle; composition + bootstrap move and shrink; layering moves intact) | **−350** |
| `account/venue.py` deleted; ~60 lines of snapshot logic move into the OKX adapter; websocket balance/position streams not carried (§4.4) | **−200** |
| `venues/okx_plugin.py` → recipe functions beside the adapters (plugin-class + lazy-import ceremony gone) | **−80** |
| `venue_uid_guard.py` → identity-check function in `venues/accounts.py` (reasons kept, module scaffolding gone) | **−80** |
| `compose.py` → `graph.py` (Optional selectors and mode knowledge out) | **−47** |
| `is_venue_truth` + guards + dedup loops + `getattr` scars + error-message prose | **−45** |
| 4 storage-factory classes → functions | **−30** |
| `None`-then-assign `definition_store` + WR-07 gating | **−17** |
| ~99 GATE-01/vestigial body-imports hoisted or deleted | **−40** |

**Additions (estimates):**

| item | est. Δ |
|---|---:|
| `venues/catalog.py` — descriptors + capability enum + lookup | **+85** |
| `pool.public_session` + auth-declaration handling | **+30** |
| `AccountSnapshot` value object + adapter `snapshot()` beyond the moved logic | **+25** |
| D-4 alert-on-snapshot-failure path | **+10** |
| bootstrap extraction overhead (module frame; the logic moves) | **+20** |

Estimated net: **≈ −1,240 +170 → roughly −1,050 code lines, a ~27% reduction** —
about 2.5× v1's estimate, because deleting the ferrying layer (D-8/D-9/D-10) removes
whole modules instead of slimming them. The live-root split remains the largest
single uncertainty; if mid-refactor re-measurement ever puts the sign at risk, that
is a stop-and-report event.

---

## 9. Out of scope, and open items

**Out of scope** (tracked elsewhere): the comment-campaign defects outside this
subsystem (`liquidation_fee_rate` wiring, the `Portfolio` margin dead assignments),
and the untested-safety-claims backlog.

**`SafetyController` stays out of scope — internals, not seams (settled
2026-07-29).** The refactor rewires everything that *calls* it (halt/stream-state
wiring in `bring_online`, `StreamRecoveryHandler`'s enumeration, the D-4 alert, the
bootstrap) but does not touch its body: it is individually sound and well-tested, its
known defects (comment-campaign items 2–4: the off-vocabulary
`deferred-protective-overflow` reason, the dead `dispatch_fn` parameter,
`deferred_maxlen` not operator-tunable) are internal cleanups with no bearing on the
composition seams, and pulling them in adds churn the deletion gate must absorb for
no structural gain. Two guardrails so the debt doesn't grow through this refactor:
every halt call site written fresh here uses `HaltReason` members (no new free
strings), and the `halt(reason: str) → HaltReason` signature migration + items 2–4
are scheduled as their own small phase **immediately after** this refactor — that
ordering means the migration touches the final call sites exactly once, instead of
retouching wiring this refactor is about to move. The Nautilus-inspired `REDUCING`
state (§3.4) belongs to that phase too, if it is ever wanted.

**Open items for the planning phase:**

1. Sequencing. Natural spine: draw the boundary + extract bootstrap
   (behaviour-preserving, oracle-locked) → pool + catalogue → adapter-owned
   snapshot + reconcile re-keying → bring-online inversion → data-adapter/public
   session + binder deletion → root/facade rewrite → delete the old shape. Each
   stage keeps both oracle tests and the composition test green.
2. Whether `connectors/` physically moves under `trading_system/live/` or keeps its
   top-level directory inside the import-graph boundary — churn-vs-clarity call.
3. Re-measure prose-to-code ratios after the redesign (the requirements' cheap
   sanity check).
