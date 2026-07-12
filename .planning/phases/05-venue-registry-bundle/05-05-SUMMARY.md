---
phase: 05-venue-registry-bundle
plan: 05
subsystem: venue-plugins
tags: [venue-plugin, okx, paper, triple-deferral, d-04, d-05, d-07, inertness, register-vs-build]

# Dependency graph
requires:
  - phase: 05-venue-registry-bundle
    provides: "VenueBundle + VenuePlugin/DataProviderPlugin/ConnectorPlugin Protocols + the two registries + ConnectorProvider memo (05-04)"
  - phase: 05-venue-registry-bundle
    provides: "LiveDataProvider surface / ReplayDataProvider (05-03); OkxConnector/StreamSupervisor shape (05-01)"
provides:
  - "OkxConnectorPlugin — the OKX ConnectorPlugin build recipe (OkxConnector(OkxSettings()) constructed INSIDE build, D-04)"
  - "OkxVenuePlugin — builds an OkxExchange VenueBundle over the shared (venue, account_id) connector + a single default VenueAccount factory (D-03/D-07)"
  - "OkxDataPlugin — builds an OkxDataProvider bound to the SAME memoized connector (D-03)"
  - "PaperVenuePlugin — reuses the compose-built 'simulated' exchange AS-IS (connector=None), never touches the ConnectorProvider (D-05)"
  - "ReplayDataPlugin — builds the ReplayDataProvider over the shared PAPER_PARITY_* window (concretions lazy inside build_provider, D-04/D-12)"
affects: [05-06, assemble_venue, venue-lifecycle, build_live_system]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Triple-deferral lazy-build (D-04): every plugin build*() keeps the OKX concretion import AND OkxSettings() credential construction INSIDE the method body — module scope + register time pull nothing heavy (register != build)"
    - "Shared (venue, account_id) connector borrow (D-03): OkxVenuePlugin + OkxDataPlugin both call connectors.get('okx', account_id, spec) so one ccxt.pro client serves the exec + data arms"
    - "Satisfied-by-reuse (D-05): PaperVenuePlugin wraps the compose-built 'simulated' exchange by identity — no new exchange/adapter, connector=None, ConnectorProvider untouched"
    - "Import-scope AST scan test: the plugin unit tests parse the module body and assert no ccxt/concretion import is a direct child of the Module (a hoist guard complementing the subprocess inertness gate)"

key-files:
  created:
    - itrader/venues/okx_plugin.py
    - itrader/venues/paper_plugin.py
    - tests/unit/venues/test_okx_plugin.py
    - tests/unit/venues/test_paper_plugin.py
  modified:
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "The P5 register-vs-build assertion proves the VENUE PLUGIN surface is import/register-inert (okx_plugin + paper_plugin + registries), and DELIBERATELY EXCLUDES the ConnectorProvider from the ccxt-absent window: importing anything under itrader.connectors runs connectors/__init__.py, which eagerly re-exports OkxConnector (pulls ccxt) — a pre-existing 05-04 barrel decision, not a plugin hoist. Folding it in would mask the real guard. OkxConnectorPlugin's recipe laziness is covered by its module staying inert to import + its build-body unit contract."
  - "OKX account_factory is *args/**kwargs-absorbing and mints a single default VenueAccount (D-07); paper account_factory takes (portfolio, initial_cash) and mirrors the portfolio.py leaf selection (margin superset vs spot cash leaf). Loosely typed Callable[..., Account] so 05-06 assemble_venue calls both uniformly."
  - "OkxSettings() carries `# type: ignore[call-arg]` (env-populated validation_alias fields look required to mypy) — matches the established connectors/okx.py:81 convention."

requirements-completed: [VENUE-02]

coverage:
  - id: D1
    description: "OKX venue/data/connector plugins are triple-deferral-lazy (D-04): every OKX concretion import + OkxSettings() inside build*; module scope pulls no ccxt"
    requirement: "VENUE-02"
    verification:
      - kind: unit
        ref: "tests/unit/venues/test_okx_plugin.py (bundle shape, module-scope AST import scan, Protocol conformance)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (_FORBIDDEN + register-vs-build block: register != build pulls no ccxt)"
        status: pass
    human_judgment: false
  - id: D2
    description: "OkxVenuePlugin + OkxDataPlugin borrow the SAME memoized connector per (venue, account_id) (D-03/D-07)"
    requirement: "VENUE-02"
    verification:
      - kind: unit
        ref: "tests/unit/venues/test_okx_plugin.py#test_okx_data_plugin_shares_the_same_connector + honor_explicit_account_id"
        status: pass
    human_judgment: false
  - id: D3
    description: "PaperVenuePlugin reuses the compose-built 'simulated' exchange by identity (connector=None, ConnectorProvider untouched, D-05); ReplayDataPlugin builds the replay provider lazily"
    requirement: "VENUE-02"
    verification:
      - kind: unit
        ref: "tests/unit/venues/test_paper_plugin.py (identity reuse, exploding ConnectorProvider never called, compute account_factory, lazy replay import)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (byte-exact 46189.87730727451) + test_okx_inertness.py"
        status: pass
    human_judgment: false

# Metrics
duration: 7min
completed: 2026-07-12
status: complete
---

# Phase 5 Plan 05: Concrete Venue/Data/Connector Plugins Summary

**The concrete OKX + paper venue/data/connector plugins — `OkxConnectorPlugin` / `OkxVenuePlugin` / `OkxDataPlugin` (all triple-deferral-lazy, D-04, sharing one memoized connector per `(venue, account_id)`, D-03) and `PaperVenuePlugin` / `ReplayDataPlugin` (paper reuses the compose-built `'simulated'` exchange AS-IS, connector-free, D-05) — landed and unit-tested with fakes; the P5 acceptance gate is extended with the two new plugin modules in `_FORBIDDEN` plus a register-vs-build assertion proving register ≠ build. Both standing gates hold (oracle byte-exact + OKX inertness), mypy --strict clean.**

## Performance
- **Duration:** ~7 min
- **Started:** 2026-07-12T22:49:33Z
- **Completed:** 2026-07-12T22:56:32Z
- **Tasks:** 3 (2 TDD)
- **Files:** 5 (4 created, 1 modified)

## Accomplishments
- `OkxConnectorPlugin` (`itrader/venues/okx_plugin.py`): the OKX `ConnectorPlugin` recipe — `build(spec)` is the ONLY place `OkxSettings()` (the `OKX_API_*` `SecretStr` triple) is constructed and `OkxConnector` is imported; both live inside the method body (D-04 layer 1+3), so registering it needs no creds and pulls no ccxt.
- `OkxVenuePlugin.build_bundle`: borrows the shared `(venue, account_id)` connector (`connectors.get("okx", spec.account_id or "default", spec)`, D-03), wraps it in an `OkxExchange(ctx.bus, connector)`, and supplies a single default `VenueAccount` factory (spot, quote = wired pair's right leg, D-07). Returns a `VenueBundle(exchange, account_factory, connector)` with `lifecycle=None` (05-06 builds it).
- `OkxDataPlugin.build_provider`: same memoized connector key → `OkxDataProvider(connector, symbol, timeframe)` from a default `StreamSettings` read inside the body. The exec + data arms provably share ONE connector (unit-asserted).
- `PaperVenuePlugin(simulated_exchange).build_bundle`: reuses the injected compose-built `'simulated'` `SimulatedExchange` **by identity** (D-05 satisfied-by-reuse — no new exchange/adapter), `connector=None`, and never touches the `ConnectorProvider` (proven by an *exploding* fake provider). Its `account_factory` mints the compute account leaf (margin superset vs spot cash leaf, mirroring `portfolio.py:136-140`).
- `ReplayDataPlugin.build_provider`: lazy-imports `ReplayDataProvider` + `CsvPriceStore` inside the body and wires them from the shared `PAPER_PARITY_*` window (D-04/D-12/WR-02).
- Extended `tests/integration/test_okx_inertness.py`: `_FORBIDDEN` now forbids `itrader.venues.okx_plugin` + `itrader.venues.paper_plugin` on the backtest path, and a new Phase-5 register-vs-build block imports + registers the OKX/paper venue/data plugins and asserts `ccxt.pro`/`ccxt`/`itrader.connectors.okx` stay absent (register ≠ build).
- Both standing gates hold: oracle byte-exact `46189.87730727451`; OKX inertness/register-vs-build green. `mypy --strict` clean (full 242-file gate); both new modules 4-space, zero tab lines; module-scope AST scans confirm no ccxt/concretion import escapes a `build*` body.

## Task Commits
1. **Task 1: OKX plugins (venue + data + connector recipe), triple-deferral lazy** (TDD)
   - `c39d4fea` (test — RED gate)
   - `a26dea98` (feat — GREEN gate)
2. **Task 2: Paper plugins (reuse compose-built 'simulated' exchange + replay data)** (TDD)
   - `e1c29d7f` (test — RED gate)
   - `9ee8cb1f` (feat — GREEN gate)
3. **Task 3: Extend the OKX inertness gate — _FORBIDDEN + register-vs-build** - `8e95cb38` (test)

_TDD note: Tasks 1 and 2 each followed RED → GREEN (no REFACTOR needed). Task 3 is a test-only gate extension._

## Files Created/Modified
- `itrader/venues/okx_plugin.py` - NEW (4-space). `OkxConnectorPlugin` / `OkxVenuePlugin` / `OkxDataPlugin`; every OKX concretion import + `OkxSettings()` inside `build*`; TYPE_CHECKING-only annotations.
- `itrader/venues/paper_plugin.py` - NEW (4-space). `PaperVenuePlugin` (reuse-by-identity, connector=None) + `ReplayDataPlugin` (lazy replay import); re-homes the `PAPER_PARITY_*` string anchors for the replay window.
- `tests/unit/venues/test_okx_plugin.py` - NEW (package-less dir). Bundle shape, shared-connector identity, per-account_id keying, module-scope AST import scan, Protocol conformance.
- `tests/unit/venues/test_paper_plugin.py` - NEW. Identity reuse, exploding-ConnectorProvider guard, compute account_factory, lazy replay import, Protocol conformance.
- `tests/integration/test_okx_inertness.py` - MODIFIED. `_FORBIDDEN` += the two plugin modules; new Phase-5 register-vs-build block.

## Decisions Made
- **Register-vs-build assertion proves the VENUE PLUGIN surface, excludes the ConnectorProvider (see Deviations).** The plan's literal instruction to import `itrader.connectors.provider` inside the ccxt-absent window can never pass because the `connectors/__init__.py` barrel eagerly re-exports `OkxConnector` (pulls ccxt) — a deliberate 05-04 decision. The assertion instead proves importing + registering the okx/paper venue/data plugins is inert (the true D-04 hoist guard); the ConnectorProvider is documented-excluded.
- **`account_factory` signatures.** OKX = `*args/**kwargs`-absorbing, mints a single default `VenueAccount` (D-07). Paper = `(portfolio, initial_cash=0.0)`, mirrors the portfolio leaf selection. Both typed `Callable[..., Account]` so 05-06's `assemble_venue` invokes them uniformly.
- **`OkxSettings()  # type: ignore[call-arg]`** — env-populated `validation_alias` fields look required to mypy; matches the established `connectors/okx.py:81` convention.

## Deviations from Plan

**1. [Rule 1 - Bug] The register-vs-build assertion excludes the ConnectorProvider from the ccxt-absent window.**
- **Found during:** Task 3 (the block failed with `['ccxt.pro', 'ccxt', 'itrader.connectors.okx']` leaked).
- **Issue:** The plan's Task-3 `<action>` says to `import itrader.connectors.provider` (ConnectorProvider) inside the register-vs-build block and then assert ccxt/OkxConnector absent. That assertion can NEVER pass: importing any submodule under `itrader.connectors` first runs `connectors/__init__.py`, which does `from .okx import OkxConnector` — eagerly pulling ccxt. This is the pre-existing barrel behavior 05-04 deliberately left untouched (consumers import `itrader.connectors.provider` on the LIVE path only; the backtest root never imports the connectors package, which is exactly why it stays inert).
- **Fix:** The register-vs-build block imports + registers the okx/paper VENUE/DATA plugins (`OkxVenuePlugin`/`OkxDataPlugin`/`PaperVenuePlugin`/`ReplayDataPlugin`) and constructs `OkxConnectorPlugin()` (an inert object), then asserts the OKX/ccxt stack stays absent. This is the faithful VENUE-02 / T-05-10 invariant — a plugin hoisting `import ccxt.pro`/`OkxConnector`/`OkxSettings()` to module top would redden it. The `ConnectorProvider` is documented-excluded in an in-test NOTE; the connector recipe's laziness is covered by (a) `okx_plugin` staying inert to import and (b) the `test_okx_plugin.py` build-body unit contract.
- **Files modified:** `tests/integration/test_okx_inertness.py`
- **Commit:** `8e95cb38`

## Known Stubs
None. All symbols are the intended concrete plugins; every `build*` returns a real concretion (OkxExchange/OkxDataProvider/VenueAccount/SimulatedExchange-reuse/ReplayDataProvider). No placeholder data flows anywhere. `lifecycle=None` on the bundles is the documented 05-06 seam, not a stub.

## Threat Flags
None. No new network endpoint, auth path, file access, or schema surface. The threat register's `mitigate` items are satisfied: T-05-10 (inertness regression) — extended `_FORBIDDEN` + register-vs-build assertion + module-scope AST scans fail loudly on a hoist; T-05-11 (cred-less startup crash) — `OkxSettings()` constructed only inside `build()`, paper never touches the ConnectorProvider (connector=None); T-05-12 (credential disclosure) — creds env-sourced via `OkxSettings` `SecretStr` inside `build`, memo key is the logical `account_id`, never a credential; T-05-SC — zero new dependencies.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 05-06's `assemble_venue(ctx, spec, connectors)` resolves `ExecutionVenueRegistry.get(spec.execution_venue or ...)` / `DataProviderRegistry.get(spec.data_provider or ...)`, calls `plugin.build_bundle` / `plugin.build_provider` (which share one connector per `(venue, spec.account_id or "default")` via the `ConnectorProvider`), and defines the real `VenueLifecycle` that `VenueBundle.lifecycle` will carry (retype `Any` → `VenueLifecycle | None`).
- The LTS root registers these at composition (P6, `build_live_system`): `exec_registry.register('okx', OkxVenuePlugin())`, `exec_registry.register('paper', PaperVenuePlugin(simulated_exchange))`, `data_registry.register('okx', OkxDataPlugin())`, `data_registry.register('paper', ReplayDataPlugin())`, `ConnectorProvider({'okx': OkxConnectorPlugin()})` — keeping the `if exchange=='okx' … elif =='paper'` block deletable.

## Self-Check: PASSED
- FOUND: `itrader/venues/okx_plugin.py`, `itrader/venues/paper_plugin.py`
- FOUND: `tests/unit/venues/test_okx_plugin.py`, `tests/unit/venues/test_paper_plugin.py`
- FOUND commits: `c39d4fea` (test), `a26dea98` (feat), `e1c29d7f` (test), `9ee8cb1f` (feat), `8e95cb38` (test)
- GATES: oracle byte-exact `46189.87730727451` + OKX inertness/register-vs-build both green; mypy --strict clean (242 files); 0 tab lines in both new modules; 463-test cross-domain sweep green.

---
*Phase: 05-venue-registry-bundle*
*Completed: 2026-07-12*
