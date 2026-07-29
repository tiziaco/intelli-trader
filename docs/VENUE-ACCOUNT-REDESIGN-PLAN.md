# Venue / Account / Composition Redesign — Implementation Plan

> **For agentic workers:** execute stage-by-stage. Each stage is a coherent unit of
> work with its own verification gates and commit boundary. Do not start stage N+1
> until stage N's full gate battery is green and committed. Within a stage, the
> executor owns line-level decisions; the design doc (§ references below) is the
> authority on shape, this plan is the authority on sequencing and gating.

**Goal:** Implement `docs/VENUE-ACCOUNT-REDESIGN-DESIGN.md` (v2, HEAD `297cee06`):
two composition roots, adapter-owned venue truth, catalogue + pool + recipes, the
ferrying layer deleted — with both oracles byte-exact throughout and net source
strictly below the frozen baseline (27 files / 9,243 raw / 3,886 code).

**Architecture:** Stages follow the design's §9.1 spine exactly: gates first
(Stage 0), then boundary + bootstrap extraction, pool + catalogue, adapter-owned
snapshot + reconcile re-keying, bring-online inversion, data-adapter + binder
deletion, root/facade rewrite, and finally deletion of the old shape + the
baseline re-measurement. New shape and old shape co-exist transitionally between
Stages 2 and 6; Stage 7 removes the old shape entirely.

**Tech stack:** Python 3.13 / Poetry; pytest (strict markers/config,
`filterwarnings=["error"]`); mypy `--strict` over `itrader`; msgspec events;
Decimal money; SQLAlchemy live spine.

---

## Global constraints (apply to every stage)

- **Settled decisions D-1..D-10 (design §1) are not re-litigated.** Vocabulary is
  Factory + Catalog only (D-2); `Authority`/`Plugin`/callable-`*_factory` names are
  retired in all new code.
- **Money is Decimal end-to-end** — `AccountSnapshot` carries `Decimal`; this
  refactor touches no arithmetic.
- **Determinism seams untouched**: `EngineContext.rng`, injected clock, one seeded
  RNG reaching `SimulatedExchange`.
- **Queue-only writes / single-writer contract untouched**: connector callbacks
  flip flags only; venue I/O (incl. `snapshot()`) runs on the engine thread via
  `connector.call`.
- **Indentation is per file — measure, never infer** (`grep -c $'^\t' <file>`).
  Known: `trading_system/compose.py`, `trading_system/backtest_trading_system.py`,
  `trading_system/engine_context.py`, `execution_handler/exchanges/okx.py` are
  TAB-indented; `trading_system/live_trading_system.py` and everything under
  `venues/`, `connectors/`, `portfolio_handler/account/`, `storage/` is 4-space.
  All NEW modules use 4 spaces. A pure `git mv` preserves bytes and is always safe.
- **Comments state what is true now** — no changelog narration, no bare `D-NN`
  citations (per-phase counters do not resolve globally; cite design §-numbers
  like `design §4.4` instead).
- **New halt call sites use `HaltReason` members** — no new free-string reasons
  (design §9, SafetyController guardrail). `SafetyController` internals are out of
  scope; only its *callers* are rewired.
- **No new module enters the mypy `ignore_errors` list** (`pyproject.toml:102-111`).
  Every new module under `trading_system/live/`, `venues/`, `connectors/` is
  strict-clean from its first commit.
- **`.planning/` and GSD artifacts are not touched by this plan** (explicit bypass
  session).
- **Design open item 2 is settled here as: `connectors/` KEEPS its top-level
  directory** inside the import-graph boundary — the D-7 layout diagram already
  shows it top-level, the boundary is enforced by the inertness test rather than
  by directory nesting, and a physical move is pure churn against the deletion
  gate.

## The gate battery (referenced by every stage as "GATES")

Run from the repo root, in this order. **Never `make test`** (it exports
`ITRADER_DISABLE_LOGS=true` and aborts in worktrees on a missing `.env`).

| # | gate | command |
|---|---|---|
| G1 | Backtest oracle, legacy construction arm | `poetry run pytest tests/integration/test_backtest_oracle.py -q` |
| G2 | Backtest oracle, factory arm | `poetry run pytest tests/integration/test_backtest_oracle_factory_arm.py -q` |
| G3 | Inertness (extended from Stage 1 on) | `poetry run pytest tests/integration/test_okx_inertness.py -q` |
| G4 | Offline live-composition test (from Stage 0 on) | `poetry run pytest tests/integration/test_live_composition_offline.py -q` |
| G5 | mypy strict (whole `itrader` tree — `files = ["itrader"]` in pyproject) | `poetry run mypy` |
| G6 | Full suite | `poetry run pytest tests` |

Both oracle gates are required because `test_backtest_oracle.py` drives the legacy
construction arm and `test_backtest_oracle_factory_arm.py` the factory arm — an
edit to only one arm goes false-green against the other.

## CR xfail ledger (Stage 0 creates; later stages flip)

The Stage-0 composition test carries four `@pytest.mark.xfail(strict=True)`
probes, one per Critical from `11.2-REVIEW.md`. `strict=True` + the repo's
`filterwarnings=["error"]` discipline means the fix stage MUST remove the mark in
the same commit that lands the fix — a passing xfail fails the suite loudly.

| probe | asserted invariant (post-fix) | flips in |
|---|---|---|
| CR-01 | the facade exposes the venue-account manager as a required, reachable operator surface (`system.venue_accounts`) | Stage 6 |
| CR-02 | the live data feed's provider is owned by a data adapter on its own session; retiring an execution account leaves the feed fully wired | Stage 5 |
| CR-03 | the recovery handler's account enumeration is non-empty when an account is online (no mirrored container) | Stage 3 |
| CR-04 | an injected raising `connect()` during bring-up ⇒ the `(venue, account_id)` routing map stays EMPTY | Stage 4 |

---

## Stage 0 — Gates before surgery (fixed by prior agreement)

**Goal:** land the offline live-composition test against CURRENT code (wiring
assertions green where current code is correct, `xfail(strict=True)` on
CR-01..CR-04), plus the baseline-measurement script implementing the design-§2.3
counting rule. No production code changes.

**Files:**
- Create: `tests/integration/test_live_composition_offline.py`
- Create: `scripts/measure_redesign_baseline.py`
- Modify: nothing under `itrader/`

**Content, at stage granularity:**

1. **Composition test** (design §7.1): build the complete live system offline —
   paper venue, no credentials, no network, no Postgres. Two proven patterns to
   build on: `tests/support/replay_harness.py::build_paper_replay_system()`
   (builds a full paper `LiveTradingSystem` via `LiveTradingSystem.for_exchange`,
   offline, in-memory arm) and
   `tests/integration/test_account_provisioning_loop.py` (drives
   `VenueAccountStore` → `VenueAccountManager` → `bring_online` over a SQLite
   `SqlEngine` via `tests/support/schema.py::provision_schema`). The test asserts
   the wiring, not the units: provision → bring_online → a portfolio materializes
   over the account → an order routes only after bring-up completes → recovery
   enumeration → teardown closes exactly the built sessions. The four CR probes
   from the ledger above are `xfail(strict=True)` against current behaviour.
2. **Baseline script**: code lines = non-blank lines that are neither comments
   nor inside ANY docstring (module, class, or function); raw lines = `grep -c ''`
   equivalent. Implement docstring detection with `ast` (docstring node line
   ranges) + `tokenize` (comments), not regex. Hard-code the 27-file baseline
   manifest (the 19 requirements-Scope paths + `venues/venue_account_manager.py`,
   `venues/venue_uid_guard.py`, `connectors/okx.py`,
   `connectors/stream_supervisor.py`,
   `portfolio_handler/account/{base,conformance,simulated,venue}.py`) and accept
   `--manifest <file>` for the successor set. Acceptance: at HEAD it must print
   exactly **27 files / 9,243 raw / 3,886 code** (raw total re-verified against
   HEAD during planning).

**Deletions:** none.

**Gates:** GATES (G4 runs the new test: wiring assertions pass, 4 xfails
xfail) + `poetry run python scripts/measure_redesign_baseline.py` reproduces
27/9,243/3,886.

**Commit boundary:** one commit — `test: offline live-composition gate (CR-01..04 xfail) + baseline script`.

---

## Stage 1 — Draw the boundary, extract the bootstrap (behaviour-preserving)

**Goal:** the two-roots package layout exists (D-7), the restart bootstrap is a
module (design §4.8) rather than a region of `live_trading_system.py`, and
GATE-01 becomes a named import-graph boundary — all with zero behaviour change.

**Files:**
- Create: `itrader/trading_system/backtest/__init__.py` (barrel re-exporting
  `BacktestTradingSystem` / `build_backtest_system`)
- Move (`git mv`): `itrader/trading_system/backtest_trading_system.py` →
  `itrader/trading_system/backtest/backtest_trading_system.py`;
  `itrader/trading_system/backtest_runner.py` →
  `itrader/trading_system/backtest/backtest_runner.py`
- Create: `itrader/trading_system/live/__init__.py`,
  `itrader/trading_system/live/bootstrap.py`
- Modify: `itrader/trading_system/live_trading_system.py` (extract the
  requirements-§3 boot sequence — table probe → `assert_distinct_accounts` →
  per-enabled-row `bring_online` loop → `rehydrate_portfolios`; the sequence sits
  inline in `build_live_system` at `live_trading_system.py:1326-1358` — plus the
  `_layer_persisted_overrides` config-layering pass (defined at `:919`) — into
  `bootstrap.py::bootstrap_session(...)`, called from where the logic used to
  live; a MOVE, not a redesign — the ordering and the CURRENT failure behaviour
  are preserved exactly. NOTE: the `bring_online` loop today has NO per-row
  quarantine — a row's fault propagates loud; the design-§4.8 per-row quarantine
  is NEW behaviour and lands in Stage 4, not here)
- Modify: `itrader/trading_system/session_initializer.py` (hoist its two body
  imports at `:111-112` — `StrategyDerivedSelectionModel`, `UniverseHandler` — to
  module top; design §4.1 says these are vestigial, and the universe handler is
  live-only by graph, not by laziness)
- Modify: `tests/integration/test_okx_inertness.py` — extend the probe with a
  **prefix-matched** boundary-root assertion (a leaked `itrader.trading_system.live.x`
  submodule must trip it, so exact-name matching is insufficient) over the roots
  already enforceable today: `itrader.trading_system.live`,
  `itrader.execution_handler.exchanges.okx`,
  `itrader.price_handler.providers.okx_provider`. The full §3.2 set
  (`itrader.connectors`, `itrader.venues.accounts`) CANNOT land yet — the backtest
  root deliberately wires a real empty `ConnectorProvider` today (11.1 D-04) —
  those roots join in Stage 6. `itrader.storage` is already covered by the
  probe's SQL-roots assertion plus named store modules.
- Modify: import sites of the moved backtest modules —
  `tests/integration/test_backtest_oracle.py`, `_oracle_harness.py`,
  `test_backtest_oracle_factory_arm.py`, `test_okx_inertness.py` (probe line 36),
  `scripts/run_backtest.py`, and every other
  `trading_system.backtest_trading_system` / `backtest_runner` importer
  (`grep -rln "backtest_trading_system\|backtest_runner" itrader tests scripts`).

**Deletions:** none (old modules move; nothing dies yet).

**Notes:** `backtest_trading_system.py` and `compose.py` are TAB files —
`git mv` + import-line edits only, no re-indentation. `bootstrap.py` is new →
4-space, strict-typed, NOT added to the mypy override list (the
`live_trading_system` override stays until the module dies in Stage 7).

**Gates:** GATES. G1/G2 prove the moved backtest root is byte-exact (oracle
assertion travels with the move in the SAME commit). G4 unchanged (4 xfails).

**Commit boundary:** two commits — (1) `refactor: backtest root moves under
trading_system/backtest/ (oracle-locked)`, (2) `refactor: extract
bootstrap_session + extend inertness boundary`.

---

## Stage 2 — Pool + catalogue (new shape appears; old shape untouched)

**Goal:** the inert venue catalogue, the `ConnectorPool`, the connector-recipe
function, and the D-5/D-6 contract changes exist and are unit-tested. No
production consumer is re-pointed yet — `ConnectorProvider`, the registries and
the plugins keep working untouched until Stages 4–6.

**Files:**
- Create: `itrader/venues/catalog.py` — `VenueCapability` enum
  (`EXECUTION`/`PUBLIC_DATA`/`PRIVATE_DATA`), frozen `VenueDescriptor`
  (`name`, `credential_model: type | None`, `capabilities`,
  `data_requires_auth: bool`, `default_data_provider: str`), and the module-level
  `CATALOG` dict with `okx` + `paper` descriptors (design §4.3). Import-inert:
  pulls pydantic-settings at most (`OkxSettings` from
  `itrader/config/okx_settings.py`), never ccxt/SQL.
- Create: `itrader/connectors/pool.py` — `ConnectorPool`: the
  `(venue, account_id)` memo, the session-identity conflict guard
  (`secret_ref`/`sandbox`/`region` — semantics carried over from
  `connectors/provider.py` unchanged), `close_all()`, and
  `public_session(venue)` (unauthenticated loop+client, memoized per venue, no
  identity to conflict; design §4.2). Takes the catalogue and a
  `CredentialResolver` (`itrader/config/credential_resolver.py` — already built,
  design §2.2.2).
- Modify: `itrader/connectors/base.py` — `LiveConnector` Protocol gains
  `set_halt_signal` (D-5); the declared surface becomes the whole surface.
- Modify: `itrader/connectors/okx.py` — add the module-level recipe
  `build_okx_connector(...)` (the construction knowledge currently inside
  `OkxConnectorPlugin.build` in `venues/okx_plugin.py:104-162`, incl. the
  `secret_ref` resolution + completeness gate against `OkxSettings.model_fields`).
  The plugin itself is NOT deleted yet (Stage 7).
- Modify: `itrader/config/okx_settings.py` — D-6 field metadata:
  `json_schema_extra={"kind": "secret" | "routing"}` on every `OkxSettings` field.
- Create: `tests/unit/venues/test_catalog.py`,
  `tests/unit/connectors/test_pool.py` (incl. one generic threading-contract test
  for the `call`/`spawn` idiom, design §4.2), plus a catalog-inertness assertion
  (importing `itrader.venues.catalog` in a clean interpreter pulls no
  ccxt/SQL — same subprocess-probe technique as `test_okx_inertness.py`).

**Deletions:** none (transitional co-existence, closed in Stage 7).

**Gates:** GATES. G4 unchanged (4 xfails).

**Commit boundary:** one commit — `feat: venue catalogue + ConnectorPool +
connector recipe (new shape, no consumers yet)`.

---

## Stage 3 — Adapter-owned snapshot + reconcile re-keying (D-10)

**Goal:** venue account truth lives on the execution adapter; reconciliation and
recovery consume adapters/records, not accounts; the entire
`VenueAccount`-as-`Portfolio.account` premise and its guard scaffolding are gone.
This deletes real modules — safe because the venue-truth layer is fully inert in
live today (design §2.1: nothing ever assigns a `VenueAccount` onto
`Portfolio.account`; `is_venue_truth` is `False` on every live portfolio).

**Files:**
- Modify: `itrader/execution_handler/exchanges/base.py` — `AbstractExchange`
  gains the `snapshot() -> AccountSnapshot` surface; define frozen
  `AccountSnapshot` (balances, positions, all `Decimal`) beside it (TAB/space:
  measure the file first).
- Modify: `itrader/execution_handler/exchanges/okx.py` — `OkxExchange` (class at
  `:72`) implements `snapshot()` by moving `account/venue.py`'s REST fetch logic
  (~60 lines) onto the adapter's own connector via `connector.call`. The
  RLock-guarded cache and the balance/position websocket streams are NOT carried
  over (design §4.4 — their only consumers were the inert layer). Also add the
  module-level recipe `build_okx_exchange(...)` (absorbing
  `OkxVenuePlugin.build_bundle`'s exchange-construction knowledge incl. the
  mismatched-`account_id` refusal from `okx_plugin.py:356-369`, design §2.2.5) —
  consumed in Stage 4.
- Modify: `itrader/execution_handler/exchanges/simulated.py` — trivial
  `snapshot()` (compute-derived/empty; the reconcile path only iterates online
  live records, but the adapter contract is uniform — design §5 adapter
  contracts).
- Modify: `itrader/portfolio_handler/reconcile/venue_reconciler.py` —
  `VenueReconciler` (class at `:76`) takes an adapter + snapshot instead of a
  `VenueAccount`.
- Modify: `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` —
  iterate the venue-account manager's online records instead of
  `is_venue_truth`-gated portfolio accounts (the two gates at `:127` and `:212`
  die); portfolios found via the definition store's `(venue_name, account_id)`;
  the startup-reconcile identity-dedup loop (`:124-134`, the
  `id(account) in reconciled` list) is deleted — record iteration is
  distinct-by-construction. (The baseline guard at `:212` filters on
  `is_venue_truth` but never had its own dedup — there is ONE dedup loop today,
  not two; the requirements-§7.3 "both loops" claim overstates.) Factor the
  snapshot-compare so a future periodic caller reuses it (design §3.4 deferral).
- `itrader/portfolio_handler/reconcile/drift.py` — NO code change: it is a pure
  Decimal-tolerance function (`is_within_single_unit_tolerance`) with zero
  `VenueAccount` type coupling; only its docstring prose mentions the deleted
  leaf — update the prose.
- Modify: `itrader/trading_system/safety/stream_recovery_handler.py` —
  constructed with the manager's record enumeration (kills the CR-03
  mirrored-container class); reconnect snapshot goes through
  `adapter.snapshot()`; a failed reconnect snapshot raises a CRITICAL alert and
  stays paused (D-4 — reversible pause, retry on next stream-up, no auto-halt).
- Modify: `itrader/portfolio_handler/portfolio.py` — delete the
  `getattr(..., "is_venue_truth", ...)` guard at `:220`.
- Modify: `itrader/portfolio_handler/account/base.py` — delete `is_venue_truth`
  (`:119`). The four venue-only members
  (`snapshot`/`start_streaming`/`connector`/`positions`, design §2.2.3) are NOT
  declared on the ABC — they live only on the concrete `VenueAccount` leaf and
  die with `venue.py`; the call-site type guards that fence them die with the
  predicate. The ABC is compute-shaped once the predicate goes.
- Modify: `itrader/portfolio_handler/account/conformance.py` — rewritten (its
  docstring describes the deleted `_attach_venue_accounts` as if it runs, design
  §2.2.8).
- Modify: `itrader/portfolio_handler/portfolio_handler.py` — delete the
  `getattr(..., "drop_pending", None)` probe at `:475` (same type-test in
  disguise, design §2.2.3).
- Modify: `itrader/core/exceptions/portfolio.py` — the one user-facing
  `is_venue_truth` error message (`:264`/`:294` region) reworded to the new
  model.
- Modify: `itrader/config/stream.py:9`, `itrader/connectors/stream_supervisor.py:6`
  — docstring-prose mentions of `account.venue`/`VenueAccount` only (no type
  coupling in either file); update the prose.

**Deletions (exact):**
- `itrader/portfolio_handler/account/venue.py` (616 raw lines)
- The `is_venue_truth` predicate and every guard/scar listed above

**Affected tests (delete or re-target — rule: behaviour that survives per design
§4.4 gets a re-targeted test; behaviour that dies with the websocket
streams/cache loses its test):**
`tests/unit/portfolio/test_account_venue.py`, `test_venue_account_cache.py`,
`test_venue_account_drift.py`, `test_venue_account_drop_pending.py`,
`test_venue_account_wiring.py`, `test_venue_cash_no_double_count.py`,
`test_spot_base_fee_drift_absorber.py`, `test_spot_drift_guard.py`,
`test_spot_stream_no_clobber.py`, `test_account_conformance.py`,
`test_reconciliation_coordinator.py`, `reconcile/test_venue_reconciler_fetch.py`,
`tests/unit/trading_system/test_stream_recovery_handler.py`, plus integration
re-targets in `test_two_sided_restart.py`, `test_venue_account_restart_restore.py`,
`test_live_system_okx_wiring.py`, `tests/e2e/test_okx_sandbox_recon.py`.
New: adapter `snapshot()` unit tests (OKX via fake connector; simulated trivially),
D-4 alert-and-stay-paused test.

**xfail flip:** CR-03 (recovery enumeration non-empty) — remove the mark in the
same commit that re-keys `StreamRecoveryHandler`.

**Gates:** GATES. G4 remaining xfails after this stage: CR-01, CR-02, CR-04.

**Commit boundary:** two commits — (1) `feat: adapter-owned AccountSnapshot +
snapshot() on both exchanges`, (2) `refactor: reconcile/recovery re-keyed onto
adapters; delete account/venue.py + is_venue_truth scaffolding (CR-03 fixed)`.

---

## Stage 4 — Bring-online inversion: `venues/accounts.py`, registration-last (CR-04)

**Goal:** the venue-account domain collapses to one module — `AccountSpec`, the
`VenueAccountManager` (absorbing `assemble_venue` + `VenueLifecycle` + the TOFU
identity check), one routing map with one writer — and `bring_online` becomes
registration-LAST.

**Files:**
- Create: `itrader/venues/accounts.py` (design §4.5):
  - `AccountSpec` — frozen record of one `venue_accounts` row (`venue_name`,
    `account_id`, `secret_ref`, `sandbox`, `region`, `market_type`, config
    overrides). The typed in-memory row form, nothing more (D-8).
  - `VenueAccountManager` — `provision` / `set_enabled` / `bring_online` /
    `bring_offline` / record enumeration over the stores, the `ConnectorPool`
    and the catalogue recipes. Lifecycle verbs act on the manager's own
    `OnlineAccount` records; each `bring_offline` tears down ITS OWN connector
    only (WR-06). `provision()` runs the config allowlist/value checks BEFORE
    persisting (WR-01/WR-02); `set_enabled` asserts the row exists.
  - The TOFU identity-check function (collapsed from `venue_uid_guard.py`;
    reasons-taxonomy kept verbatim, keyed off the descriptor's
    `credential_model`; module scaffolding dropped — design §4.4).
  - **`bring_online` order (CR-04):** resolve `AccountSpec` → validated config
    merge → `pool.session(...)` → `build_okx_exchange(...)` /
    paper recipe → `adapter.connect()` (spawns fill/order streams) → TOFU check
    → wire halt + stream-state → ONLY THEN write the routing map + online
    record. The routing map is the existing
    `(venue, account_id) → adapter` dict `ExecutionHandler.on_order` routes by
    (`bring_online` already writes that same dict object — design §2.2.7); the
    manager stays its only writer; `VenueBundles`' second memo is bypassed here
    and deleted in Stage 7.
- Modify: `itrader/trading_system/live/bootstrap.py` — the per-row boot loop
  calls `accounts.bring_online(row)` with per-row quarantine (skip + CRITICAL
  alert); boot-time and runtime bring-up become the same path.
- Modify: `itrader/trading_system/live_trading_system.py` — `start()` stops
  re-doing per-account bring-up (connect/guard/wiring) for lifecycles the boot
  registered; construction re-pointed from
  `venues/venue_account_manager.py` to `venues/accounts.py`.
- Modify: re-point remaining `VenueAccountManager` importers:
  `itrader/portfolio_handler/portfolio_factory.py`,
  `itrader/trading_system/compose.py` (type refs),
  `itrader/execution_handler/execution_handler.py` (comment/type refs),
  `itrader/storage/venue_account_store.py`,
  `itrader/storage/portfolio_definition_store.py`,
  `itrader/core/exceptions/portfolio.py`.
- Create: ordering-gate tests (design §7.5): raising `connect` ⇒ routing map
  EMPTY; identity-check mismatch ⇒ unroutable + alert.

**Deletions (exact):**
- `itrader/venues/venue_account_manager.py` (670 raw — content moves/shrinks
  into `accounts.py`)
- `itrader/venues/assemble.py` (129 raw)
- `itrader/venues/lifecycle.py` (193 raw)
- `itrader/venues/venue_uid_guard.py` (334 raw)

**Affected tests:** `tests/unit/venues/test_venue_account_manager.py`,
`test_assemble.py`, `test_lifecycle.py`, `test_venue_uid_guard.py` →
consolidated into `tests/unit/venues/test_accounts.py` (manager + TOFU + spec);
`tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py` re-targeted
to record-based teardown; integration `test_account_provisioning_loop.py`,
`test_multi_account_composition.py`, `test_distinct_account_invariant.py`,
`test_multi_portfolio_lifecycle.py` re-pointed at `venues/accounts.py`.

**xfail flip:** CR-04 (raising connect ⇒ empty routing map) — same commit as the
inversion.

**Gates:** GATES. G4 remaining xfails: CR-01, CR-02.

**Commit boundary:** two commits — (1) `feat: venues/accounts.py — AccountSpec +
manager absorbing assemble/lifecycle/TOFU`, (2) `refactor: bring_online
registration-last; boot and runtime share one path (CR-04 fixed)`.

---

## Stage 5 — Data adapter + public session; the binder dies (D-9, CR-02)

**Goal:** the data side follows the same connector → adapter pattern; the live
feed's provider is built by a venue recipe over its OWN (usually public)
session; the borrow/re-borrow scenario becomes unrepresentable.

**Files:**
- Modify: `itrader/price_handler/providers/okx_provider.py` — add the
  module-level recipe `build_okx_data_provider(...)` (absorbing
  `OkxDataPlugin.build_provider` knowledge); the adapter is halt-wired and
  stream-state-wired at build, bound to the one `LiveBarFeed`.
- Modify: `itrader/trading_system/live_trading_system.py` — the live root reads
  the configured data venue, consults its `VenueDescriptor`, and builds ONE data
  adapter: `pool.public_session(venue)` when `data_requires_auth=False` (OKX
  candles are public), an authenticated session when `True`. Subscription by
  `start()` unchanged.
- Modify: `itrader/trading_system/safety/stream_recovery_handler.py` — re-point
  its `feed_provider` callable seam (constructor param at `:75`;
  `FeedConnectionBinder` appears only in its docstring prose, never as an import)
  at the data adapter (data-session failover on disconnect remains
  `StreamSupervisor`'s reconnect job — design §4.6).
- Modify: `tests/support/replay_harness.py`, `tests/support/live_okx.py` — the
  replay/test data provider attaches through the new data-adapter seam instead
  of the binder hand-wiring.

**Deletions (exact):**
- `itrader/venues/feed_binder.py` (149 raw)

**Affected tests:** `tests/unit/venues/test_feed_binder.py` deleted;
`tests/integration/test_live_system_okx_wiring.py`,
`test_multi_account_composition.py` re-targeted;
`tests/unit/price/test_replay_provider.py` re-pointed if it names the binder.
New: a test that retiring an execution account leaves the feed's provider wired
(the CR-02 invariant, now structural).

**xfail flip:** CR-02 — the probe is REWRITTEN to the new invariant (the old
"re-borrow keeps the feed wired" scenario no longer exists to assert; the new
assertion is adapter-owned-session independence) and un-xfailed in the same
commit.

**Gates:** GATES (G6 includes `tests/integration/test_paper_parity.py` — the
replay harness edit must keep the parity gate byte-exact). G4 remaining xfail:
CR-01.

**Commit boundary:** one commit — `refactor: data adapter over its own session;
delete feed_binder (CR-02 unrepresentable)`.

---

## Stage 6 — Root and facade rewrite (design §4.9); pure graph; full boundary

**Goal:** `trading_system/live/` holds `build.py` + `bootstrap.py` + `system.py`;
`compose_engine` is demoted to a pure, mode-blind `build_handler_graph`; the
backtest root drops the venue-plugin wiring; every facade collaborator is a
required constructor parameter; the FULL §3.2 import boundary is asserted.

**Files:**
- Create: `itrader/trading_system/graph.py` — `build_handler_graph(ctx, …)`
  demoted from `compose.py::compose_engine` (`compose.py:90`): required, real
  arguments; no `Optional` mode-selectors (`venue_bundles` /
  `route_orders_by_account` / `Optional[Any]` params die); no knowledge that
  live exists; `Engine` holder survives as the return type.
- Create: `itrader/trading_system/live/build.py` — `build_live_system(config)`
  as the eight-step linear function of design §4.9: stores (REFUSES to build
  without a SQL spine — deletes WR-07's silent in-memory degradation at
  `live_trading_system.py:1086-1098` and the `definition_store`
  `None`-then-assign shape) → `ConnectorPool` + routing dict +
  `VenueAccountManager` → `build_handler_graph` → safety plane → data plane →
  session wiring → `bootstrap_session` → facade with EVERY collaborator a
  required ctor arg (CR-01 dead by `TypeError`).
- Create: `itrader/trading_system/live/system.py` — the facade
  (`LiveTradingSystem`): status/safety delegation, `add_event` ingress
  (fail-closed `_EXTERNALLY_ADMISSIBLE` semantics preserved verbatim), operator
  surface `venue_accounts` (the manager); no composition knowledge.
  `start()`/`stop()` shrink to engine-level I/O per design §4.9 (stop: drain →
  per-record `bring_offline` → `pool.close_all()`).
- Modify: `itrader/portfolio_handler/portfolio_factory.py` — the two authority
  classes (`ComputeAccountAuthority:62`, `VenueValidatedComputeAuthority:107`)
  merge into `AccountFactory` with an injected optional `validate` callable
  (design §4.7); live passes `manager.assert_available`, backtest passes none;
  `add_portfolio` validates/materializes BEFORE the durable insert (WR-03);
  `build_compute_account(...)` lands in `portfolio_handler/account/` as the one
  compute-leaf constructor.
- Modify: `itrader/trading_system/backtest/backtest_trading_system.py` — drops
  the `ExecutionVenueRegistry`/`PaperVenuePlugin`/`ConnectorProvider`/
  `VenueBundles` wiring; builds the `SimulatedExchange` + registry dict +
  `AccountFactory` directly and calls `build_handler_graph`. Byte-exact oracle
  asserted in the SAME commit.
- Modify: `itrader/trading_system/system_spec.py`,
  `itrader/trading_system/venue_spec.py` consumers — the surviving "which venue
  / which data provider" configuration moves onto `ITraderConfig`-adjacent
  config or `build_live_system` arguments; `for_exchange` callers
  (`tests/support/replay_harness.py:371` etc.) re-pointed at the new builder.
- Modify: `tests/integration/test_okx_inertness.py` — (a) boundary roots gain
  `itrader.connectors` and `itrader.venues.accounts` (legal now: the backtest
  graph no longer touches them); (b) the register-vs-build probe blocks that
  import `paper_plugin`/`okx_plugin`/`VenueBundles`/`ConnectorProvider`/
  `build_live_system` are rewritten against the new shape;
  (c) `test_production_build_live_system_registers_no_replay_data_provider`
  re-targeted at the new builder source.
- Modify: `tests/integration/test_live_composition_offline.py` — builds through
  `trading_system/live/build.py` with a SQLite spine + fake resolver; the
  production-builder checklist assertions (design §7.2: record enumerations,
  halt wiring, subscribed symbols, snapshot plumbing all produced by the REAL
  builder) land here.
- Create: rehydrate-ordering gate test (design §7.5): rehydrate before bring-up
  ⇒ loud failure at the first portfolio (via `AccountFactory.validate`
  consulting online records).

**Deletions in this stage:** none yet — `live_trading_system.py`, `compose.py`
and the plugin/registry/bundle modules become UNREFERENCED here and are deleted
in Stage 7 (one-stage lag keeps this diff reviewable and the gates attributable).

**xfail flip:** CR-01 (`system.venue_accounts` reachable; required ctor args) —
same commit as `system.py`.

**Gates:** GATES — G1/G2 byte-exact on the rewritten backtest root; G3 with the
FULL boundary; G4 with ZERO xfails remaining; G5 note: new modules strict-clean
(`live_trading_system` override still present but now covers a dead module).
Plus `poetry run pytest tests/integration/test_paper_parity.py -q` explicitly.

**Commit boundary:** three commits — (1) `refactor: compose_engine →
build_handler_graph; backtest root wires venues directly (oracle-locked)`,
(2) `feat: trading_system/live/{build,system}.py — linear root, required-arg
facade (CR-01 fixed)`, (3) `refactor: AccountFactory replaces the two
authorities; WR-03/WR-07 closed; full import boundary asserted`.

---

## Stage 7 — Delete the old shape; re-measure; close the gate

**Goal:** every superseded module is gone, the mypy override for the dead live
module is removed, orphaned tests are deleted or already re-targeted, and the
§2.3 successor measurement lands BELOW 3,886 code lines.

**Deletions (exact — everything here must have zero references first;
`grep -rn` each name before `git rm`):**
- `itrader/trading_system/live_trading_system.py` (1,577 raw)
- `itrader/trading_system/compose.py` (303 raw)
- `itrader/trading_system/venue_spec.py` (124 raw)
- `itrader/venues/bundle.py` (199 raw)
- `itrader/venues/bundles.py` (146 raw)
- `itrader/venues/registry.py` (115 raw — `COMPUTE_VENUE`/`DEFAULT_ACCOUNT_ID`
  constants re-homed first, e.g. into `venues/accounts.py`/`catalog.py`)
- `itrader/venues/paper_plugin.py` (170 raw — paper recipe functions live on,
  beside `SimulatedExchange` per D-7, keyed from the catalogue)
- `itrader/venues/okx_plugin.py` (417 raw)
- `itrader/connectors/provider.py` (154 raw)

**Files:**
- Modify: `pyproject.toml` — remove
  `"itrader.trading_system.live_trading_system"` from the `ignore_errors`
  override list (`:104`). No replacement entry.
- Modify: the four `*StorageFactory` classes → module-level functions selecting
  from data (D-1 rule 2): `itrader/order_handler/storage/storage_factory.py`,
  `itrader/portfolio_handler/storage/storage_factory.py`,
  `itrader/strategy_handler/storage/storage_factory.py`,
  `itrader/strategy_handler/storage/registry_storage_factory.py` (the last is
  not a pure switch — design §2.2.8 — so it keeps whatever held state justifies,
  per the D-1 rule, and only the ceremonial class wrapper dies where rule 2
  actually applies).
- Modify: `itrader/venues/__init__.py`, `itrader/connectors/__init__.py`,
  `itrader/trading_system/__init__.py` barrels — export the new surface only;
  the pool is never barrel-exported (D-5 boundary rule).
- Modify: sweep vestigial body-imports in every file this refactor touched
  (`grep -n "^    from \|^    import \|^\tfrom \|^\timport " <file>`) — the
  lazy imports are deleted, not relocated (design §3.2); genuinely-optional ones
  stay as the documented exception. (Memory note: dead imports in previously
  `ignore_errors`-covered modules pass mypy silently — sweep by hand.)
- Delete orphaned tests: `tests/unit/venues/test_venue_bundles.py`,
  `test_registry.py`, `test_okx_plugin.py`, `test_paper_plugin.py`,
  `tests/unit/connectors/test_provider.py`,
  `tests/unit/trading_system/test_venue_spec.py`; re-point
  `tests/support/venue_wiring.py` and any remaining `compose_engine` /
  `VenueBundles` / `ConnectorProvider` referencers
  (`grep -rln "compose_engine\|VenueBundles\|ConnectorProvider\|paper_plugin\|okx_plugin" tests/ itrader/ scripts/`).
- Create: successor manifest for the measurement script (every file that
  replaces, absorbs or renames the 27, plus every new module the redesign
  introduced: `catalog.py`, `pool.py`, `accounts.py`, `graph.py`,
  `live/{build,bootstrap,system}.py`, recipes in situ, `backtest/` root files).

**Final gates:** GATES, all green, zero xfails — PLUS:
- `poetry run python scripts/measure_redesign_baseline.py --manifest <successor>`
  → code lines **strictly < 3,886** (the must-have). If any mid-stage
  re-measurement ever puts the sign at risk, that is a STOP-AND-REPORT event
  (design §8), not a judgment call.
- Prose-to-code ratio re-measure over the successor set (design §9 open item 3) —
  reported, not gated.
- `grep -rn "import yaml" itrader/` unchanged-empty; `import itrader` still
  SQL-free (G3 covers it).

**Commit boundary:** two commits — (1) `refactor: delete the superseded
venue/composition modules; storage factories → functions`, (2) `chore: mypy
override removal + successor measurement (gate: −N code lines vs 3,886)`.

---

## Stage → design traceability

| stage | design sections delivered | criticals/WRs closed |
|---|---|---|
| 0 | §7.1 (gate exists first), §2.3 (yardstick) | — (xfail records) |
| 1 | §3.2 boundary (partial), §4.8 extraction, D-7 layout | — |
| 2 | §4.2, §4.3 (catalogue+pool halves), D-5, D-6 | — |
| 3 | §4.4, D-10, D-4 | CR-03 |
| 4 | §4.5, TOFU collapse | CR-04, WR-01, WR-02, WR-06 |
| 5 | §4.6, D-9 | CR-02 |
| 6 | §3.3, §4.7, §4.9, §3.2 boundary (full) | CR-01, WR-03, WR-07 |
| 7 | §5 doctrine table, §8 ledger settlement | must-have gate |

## Known risks, stated up front

1. **The inertness probe co-evolves with the refactor.** Its register-vs-build
   blocks import `paper_plugin`/`okx_plugin`/`VenueBundles`/`ConnectorProvider`/
   `build_live_system` by name — Stages 6–7 must rewrite those blocks in the same
   commits that change the shape, or G3 reddens for the wrong reason.
2. **The replay/parity harness is a consumer.** `build_paper_replay_system`
   builds through `for_exchange` → `build_live_system`; Stages 5–6 must carry it
   (and `test_paper_parity` byte-exactness) across the seam change.
3. **Largest single uncertainty is the live-root split** (design §8): if the
   Stage-6 diff trends the deletion gate's sign positive, stop and report before
   Stage 7.
4. **`tests/unit/trading_system/test_deleted_boot_helpers_gone.py`** asserts
   deleted helpers stay deleted — extend it (don't fight it) as Stages 3–7 delete
   more names.
5. **Tab files:** `compose.py` and the backtest root are TAB-indented; Stage 6
   rewrites replace them with new 4-space modules, which is legal only because
   the FILES are new — never mix within a surviving file.
