---
phase: 05-venue-registry-bundle
plan: 04
subsystem: venue-registry
tags: [registry, venue-bundle, connector-memo, runtime_checkable, protocol, inertness, system-spec]

# Dependency graph
requires:
  - phase: 05-venue-registry-bundle
    provides: "LiveDataProvider @runtime_checkable Protocol (05-03) — the DataProviderPlugin.build_provider return type"
provides:
  - "ExecutionVenueRegistry + DataProviderRegistry — two independent explicit-map dict registries (register/get/__contains__/names), fail-loud on unknown venue (D-01)"
  - "VenueBundle @dataclass(frozen, slots) — execution-only arm (exchange + account_factory mandatory; connector/lifecycle Optional None) (D-02)"
  - "VenuePlugin / DataProviderPlugin runtime_checkable lazy-build Protocols (VENUE-02/D-04)"
  - "ConnectorProvider — (venue, account_id) build-once memo + close_all(); ConnectorPlugin runtime_checkable Protocol (D-03/VENUE-03)"
  - "SystemSpec.execution_venue / data_provider / account_id — defaulted-None trailing selectors (VENUE-01/D-07)"
affects: [05-05, 05-06, venue-plugins, assemble_venue, paper-path-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Explicit-map registration (D-01): plain dict[name -> plugin] populated by register() calls — no decorator/entry-point self-registration, so register ≠ import concretion stays greppable"
    - "Triple-deferral lazy-build seam (D-04): plugin build_bundle/build_provider/build keep the concretion import + credential construction INSIDE the body, never at module/register time"
    - "Shared (venue, account_id) connector memo (D-03): two independent builders borrow ONE connector per key instead of each opening a ccxt.pro client"
    - "Import-inert substrate: from __future__ import annotations + TYPE_CHECKING-only heavy annotations keep new modules ccxt/sqlalchemy-free"

key-files:
  created:
    - itrader/venues/__init__.py
    - itrader/venues/bundle.py
    - itrader/venues/registry.py
    - itrader/connectors/provider.py
    - tests/unit/venues/test_registry.py
    - tests/unit/connectors/test_provider.py
  modified:
    - itrader/trading_system/system_spec.py

key-decisions:
  - "VenueBundle.lifecycle is typed Any (not VenueLifecycle | None): VenueLifecycle does not exist until 05-06, and a TYPE_CHECKING forward-import of a non-existent module would break mypy --strict. Any mirrors SystemSpec's Any-typed forward seams (results_store) and keeps the substrate import-inert; the annotation is a documented placeholder for the 05-06 VenueLifecycle."
  - "Consumers import from itrader.connectors.provider DIRECTLY; connectors/__init__.py is left untouched (its pre-existing OkxConnector re-export already pulls ccxt on the LIVE path only). The backtest hot path never imports the connectors package, so the inertness gate stays green."
  - "ConnectorProvider.get uses `key not in self._memo` (not a value-is-None probe) so build-once holds regardless of the built value; close_all disconnects each once then clears the memo."

requirements-completed: [VENUE-01, VENUE-02, VENUE-03]

coverage:
  - id: D1
    description: "Two independent registries (ExecutionVenueRegistry + DataProviderRegistry) — explicit-map register/get/__contains__/names, fail-loud KeyError on unknown venue (D-01)"
    requirement: "VENUE-01"
    verification:
      - kind: unit
        ref: "tests/unit/venues/test_registry.py (register/get identity, unknown fails loud, independent instances)"
        status: pass
    human_judgment: false
  - id: D2
    description: "VenueBundle execution-only frozen+slots shape (connector/lifecycle Optional None; no data_provider field) + VenuePlugin/DataProviderPlugin runtime_checkable Protocols (D-02/VENUE-02)"
    requirement: "VENUE-02"
    verification:
      - kind: unit
        ref: "tests/unit/venues/test_registry.py (default-None arm, frozen, no data field, runtime_checkable structural)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py + standalone `import itrader.venues` pulls no ccxt/sqlalchemy"
        status: pass
    human_judgment: false
  - id: D3
    description: "ConnectorProvider (venue, account_id) build-once memo + close_all(); ConnectorPlugin runtime_checkable Protocol (D-03/VENUE-03)"
    requirement: "VENUE-03"
    verification:
      - kind: unit
        ref: "tests/unit/connectors/test_provider.py (same key -> same instance + one build; different account_id -> new; close_all -> disconnect each; unknown fails loud)"
        status: pass
    human_judgment: false
  - id: D4
    description: "SystemSpec gains execution_venue/data_provider/account_id as defaulted-None trailing selectors; compose_engine reads only its six A1 fields; oracle byte-exact (VENUE-01/D-07)"
    requirement: "VENUE-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (byte-exact 46189.87730727451) + grep compose.py reads no new field"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-07-12
status: complete
---

# Phase 5 Plan 04: Venue-Parametrization Substrate Summary

**The venue-parametrization substrate — two independent explicit-map registries, the execution-only `VenueBundle` + `VenuePlugin`/`DataProviderPlugin` runtime_checkable seams, the shared `(venue, account_id)` `ConnectorProvider` memo + `ConnectorPlugin`, and the `SystemSpec` venue/provider/account selectors — all import-inert, mypy --strict clean, and tested; both standing gates (oracle byte-exact + OKX register-vs-build inertness) hold.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-07-12T22:37:34Z
- **Completed:** 2026-07-12T22:42:48Z
- **Tasks:** 3 (2 TDD)
- **Files:** 7 (6 created, 1 modified)

## Accomplishments
- `ExecutionVenueRegistry` + `DataProviderRegistry` (`itrader/venues/registry.py`): two SEPARATE explicit-map `dict[name -> plugin]` types over their respective plugin Protocols. `register(name, plugin)` stores, `get(name)` is a bare `self._plugins[name]` (fail-loud `KeyError`), plus `__contains__` and a `names()` view. No decorator/entry-point self-registration — register ≠ import a concretion stays greppable (D-01).
- `VenueBundle` (`itrader/venues/bundle.py`): `@dataclass(frozen=True, slots=True)` carrying ONLY the execution arm — mandatory `exchange: AbstractExchange` + `account_factory: Callable[..., Account]`; Optional `connector: LiveConnector | None = None` and `lifecycle: Any = None`. The data provider is deliberately NOT a field (built by `DataProviderRegistry`) so execution-venue and data-provider selection stay independent (D-02).
- `VenuePlugin` / `DataProviderPlugin` `@runtime_checkable` Protocols mirroring the `LiveConnector` shape: `build_bundle` / `build_provider` are the D-04 lazy-import seams (concretions imported inside the body by 05-05 plugins, not here).
- `ConnectorProvider` + `ConnectorPlugin` (`itrader/connectors/provider.py`): the provider owns the per-venue `build(spec)` recipe AND the `(venue, account_id)` build-once memo; two `get(venue, account_id, spec)` calls for the same key return the SAME connector (one `build`), a different `account_id` builds a new one, and `close_all()` disconnects each memoized connector once then clears the memo (D-03 — stops two independent builders each opening a `ccxt.pro` client).
- `SystemSpec` (`itrader/trading_system/system_spec.py`): three `Any`-typed selectors — `execution_venue` / `data_provider` / `account_id` — appended LAST after `results_store`, all defaulted `None`, so existing positional/by-name oracle + e2e call-sites stay valid and `compose_engine` (which reads only its six A1 fields) never touches them (byte-exact, D-07).
- Both standing gates hold: backtest oracle byte-exact (`46189.87730727451`) and OKX import-inertness / register-vs-build green. All new modules use `from __future__ import annotations` + `TYPE_CHECKING`-only heavy annotations — `grep import ccxt|import sqlalchemy` returns 0 on `venues/bundle.py`, `venues/registry.py`, `connectors/provider.py`; `mypy --strict` clean across all five source files.

## Task Commits

Each task was committed atomically:

1. **Task 1: VenueBundle + plugin Protocols + the two registries** (TDD)
   - `d3c2faab` (test — RED gate)
   - `bf5d6c77` (feat — GREEN gate)
2. **Task 2: ConnectorProvider memo + ConnectorPlugin Protocol** (TDD)
   - `6fa4e299` (test — RED gate)
   - `f85f7088` (feat — GREEN gate)
3. **Task 3: SystemSpec execution_venue/data_provider/account_id selectors** - `18451870` (feat)

_TDD note: Tasks 1 and 2 each followed RED → GREEN (no REFACTOR needed). Task 3 is a defaulted-field append (no behavior change), verified by the byte-exact oracle._

## Files Created/Modified
- `itrader/venues/__init__.py` - NEW. Inert barrel re-exporting only the value objects / Protocols / registry classes (no concretion import).
- `itrader/venues/bundle.py` - NEW (4-space). `VenueBundle` frozen+slots + `VenuePlugin`/`DataProviderPlugin` runtime_checkable seams; TYPE_CHECKING-only heavy annotations.
- `itrader/venues/registry.py` - NEW (4-space). `ExecutionVenueRegistry` + `DataProviderRegistry` explicit-map registries.
- `itrader/connectors/provider.py` - NEW (4-space, beside `base.py`). `ConnectorProvider` `(venue, account_id)` memo + `close_all()`; `ConnectorPlugin` Protocol. `connectors/__init__.py` untouched.
- `itrader/trading_system/system_spec.py` - MODIFIED (TABS). Three defaulted-None trailing selector fields + docstring note.
- `tests/unit/venues/test_registry.py` - NEW (package-less dir). Registry contract, VenueBundle shape/frozen, plugin runtime_checkable.
- `tests/unit/connectors/test_provider.py` - NEW. Memo identity, per-account_id distinctness, single build per key, close_all → disconnect, unknown fails loud.

## Decisions Made
- **`VenueBundle.lifecycle` typed `Any`, not `VenueLifecycle | None`.** `VenueLifecycle` is a 05-06 symbol that does not yet exist; a `TYPE_CHECKING` forward-import of its (non-existent) module would break `mypy --strict` (`Cannot find module`), and a bare undefined forward-ref in the annotation would too. `Any` is the same pattern `SystemSpec` already uses for its not-yet/heavy forward seams (`results_store: Any`), keeps the substrate import-inert, and is documented in-code as the placeholder the 05-06 `VenueLifecycle` fills. This is a faithful realization of the D-02 shape (Optional live arm defaulting to `None`), narrowing only the static type name that cannot yet be resolved.
- **`connectors/__init__.py` left untouched; consumers import `itrader.connectors.provider` directly.** The pre-existing barrel re-exports `OkxConnector` (pulls ccxt), but only the LIVE path imports the connectors package; the backtest hot path imports neither the barrel nor `provider.py`, so the inertness gate stays green (verified). `provider.py` itself is inert (only a `TYPE_CHECKING` `LiveConnector` import).

## Deviations from Plan

**1. [Rule 3 - Blocking] `VenueBundle.lifecycle` typed `Any` instead of the literal `VenueLifecycle | None`**
- **Found during:** Task 1 (mypy --strict on the new `venues/` package, which is not in any mypy override).
- **Issue:** The plan's D-02 field shape names `lifecycle: VenueLifecycle | None = None`, but `VenueLifecycle` is a 05-06 symbol that does not exist yet — referencing it (even under `TYPE_CHECKING`) fails `mypy --strict`.
- **Fix:** Typed `lifecycle: Any = None` with an in-code comment noting it will carry the 05-06 `VenueLifecycle`. Preserves the D-02 semantics (Optional live arm, default `None`); mirrors the codebase's established `Any` forward-seam pattern (`SystemSpec.results_store`).
- **Files modified:** `itrader/venues/bundle.py`
- **Commit:** `bf5d6c77`

## Known Stubs
None. All symbols are the intended value objects / Protocols / registries / memo — no placeholder data flows to any UI or run path. The concrete plugins that populate the registries are the explicit scope of 05-05.

## Threat Flags
None. No new network endpoint, auth path, file access, or schema surface is introduced — the substrate is pure value objects, Protocols, and an in-memory dict memo. The threat register's `mitigate` items (T-05-08 register-vs-build inertness, T-05-09 duplicate-connector exhaustion) are satisfied: explicit-map registration + TYPE_CHECKING-only annotations (inertness gate green every task) and the `(venue, account_id)` memo + `close_all()` (unit-tested).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 05-05 registers concrete plugins (`OkxVenuePlugin`, `PaperVenuePlugin`, `OkxDataProviderPlugin`, `ReplayDataProviderPlugin`, `OkxConnectorPlugin`) into these registries via explicit `register(...)` calls, keeping every concretion import + `OkxSettings()` construction INSIDE `build_bundle`/`build_provider`/`build` (D-04 triple-deferral) so the inertness gate stays green.
- 05-06's `assemble_venue(ctx, spec, connectors)` resolves `ExecutionVenueRegistry.get(spec.execution_venue or "default")` / `DataProviderRegistry.get(spec.data_provider or "default")` and shares one connector per `(venue, spec.account_id or "default")` via `ConnectorProvider`, and defines the real `VenueLifecycle` that `VenueBundle.lifecycle` will carry (retype `Any` → `VenueLifecycle | None` at that point).

## Self-Check: PASSED

- FOUND: `itrader/venues/__init__.py`, `itrader/venues/bundle.py`, `itrader/venues/registry.py`
- FOUND: `itrader/connectors/provider.py`
- FOUND: `tests/unit/venues/test_registry.py`, `tests/unit/connectors/test_provider.py`
- FOUND commits: `d3c2faab` (test), `bf5d6c77` (feat), `6fa4e299` (test), `f85f7088` (feat), `18451870` (feat)
- GATES: oracle byte-exact `46189.87730727451` + OKX inertness/register-vs-build both green; mypy --strict clean (5 files); inertness grep 0 on all new venue/provider modules.

---
*Phase: 05-venue-registry-bundle*
*Completed: 2026-07-12*
