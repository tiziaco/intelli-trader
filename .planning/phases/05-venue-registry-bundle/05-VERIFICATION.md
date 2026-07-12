---
phase: 05-venue-registry-bundle
verified: 2026-07-12T23:32:45Z
status: passed
score: 10/10 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 5: Venue Registry + Bundle Verification Report

**Phase Goal:** Build two independent registries (execution venue + data provider) plus a `VenuePlugin`/`VenueBundle` system with lazy plugins that parametrize every venue — killing every `if exchange==` — with connector memoization by `(venue, account_id)`, precision/validate as exchange capabilities, and a shared `StreamSupervisor`.
**Verified:** 2026-07-12T23:32:45Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ExecutionVenueRegistry` + `DataProviderRegistry` are two independent, explicit-map registries that select execution venue and data provider independently via `SystemSpec` selectors | ✓ VERIFIED | `itrader/venues/registry.py` — two plain-dict classes, `register`/`get`(KeyError fail-loud)/`__contains__`/`names`; `SystemSpec.execution_venue`/`data_provider`/`account_id` (trailing, defaulted `None`) confirmed at `itrader/trading_system/system_spec.py:119-121`; `tests/unit/venues/test_registry.py` passes (10 tests) |
| 2 | Registering `'okx'` lazy-imports its concretions only inside `build_bundle`/`build_provider`/`build` — never at module scope or register time | ✓ VERIFIED | `itrader/venues/okx_plugin.py` — `import ccxt`/`OkxConnector`/`OkxSettings`/`OkxExchange`/`OkxDataProvider` all live inside method bodies; module top only has `TYPE_CHECKING` imports; `test_okx_inertness.py`'s P5 register-vs-build block (registers OKX plugins + builds a `ConnectorProvider`, asserts `ccxt.pro`/`ccxt`/`itrader.connectors.okx` absent from `sys.modules`) — ran independently, **passed** (3/3 in `test_okx_inertness.py`) |
| 3 | `test_okx_inertness.py` (P5 acceptance gate) stays green | ✓ VERIFIED | Ran independently: `poetry run pytest tests/integration/test_okx_inertness.py -q` → 3 passed. `_FORBIDDEN` list contains `itrader.venues.okx_plugin` + `itrader.venues.paper_plugin` (grep-confirmed at lines 91-92) |
| 4 | Precision + validation are `AbstractExchange` capabilities (`resolve_precision(symbol)`, `validate_symbol(symbol)`) | ✓ VERIFIED | `def resolve_precision` present on `execution_handler/exchanges/{base,okx,simulated}.py` (grep-confirmed, lines 78/934/591); `validate_symbol` pre-existing, now CF-9 fail-closed (see #6) |
| 5 | `_OkxPrecisionResolver`/`_PrecisionResolver` are DELETED and `precision_to_scale` is a shared money util in `core/money.py` | ✓ VERIFIED | `grep "_OkxPrecisionResolver\|_precision_to_scale" live_trading_system.py` → 0 matches; `grep "_PrecisionResolver\b" universe_handler.py` → 0 matches; no dangling `.resolve(` call; `core/money.py::precision_to_scale` public via `__all__` (line 39) |
| 6 | A `LiveDataProvider` Protocol (+ `BaseLiveDataProvider` no-op defaults) wires every provider uniformly (no `hasattr` sprinkling); `VenueLifecycle` None-guards absent members so every `if exchange=='okx'`/`elif=='paper'` branch is REMOVED from `LiveTradingSystem` | ✓ VERIFIED | `itrader/price_handler/providers/live_provider.py` (`LiveDataProvider` runtime_checkable + `BaseLiveDataProvider`); `ReplayDataProvider` inherits it; `grep "self.exchange == 'okx'\|self.exchange == 'paper'" live_trading_system.py` → **0 matches** (the single grep hit at line 1488 is a descriptive comment, not code — confirmed by direct read); `VenueLifecycle` structural None-guards on `bundle.connector` (`itrader/venues/lifecycle.py`) |
| 7 | A shared `StreamSupervisor` replaces the triplicated `_run_stream_supervisor` + `_STREAM_RECONNECT_*` (CF-4); connector-contract docstrings added to `connectors/base.py` (CF-3); OKX markets-map freshness closes the fail-open-before-load window via `validate_symbol` (CF-9) | ✓ VERIFIED | `grep "_run_stream_supervisor"` on all 3 donor arms → 0 matches each; `itrader/connectors/stream_supervisor.py` exists, 0 tab-indented lines, 0 `import ccxt`; `connectors/base.py::LiveConnector` docstring documents the CF-3 session/transport contract (auth ownership, single client/loop, thread seam, session routing, lifecycle); `okx.py::validate_symbol` returns `False` on non-dict `markets` (fail-closed, CF-9/D-11) |
| 8 | Connectors are memoized by `(venue, account_id)` with per-`account_id` env-sourced credentials never persisted | ✓ VERIFIED | `itrader/connectors/provider.py::ConnectorProvider.get` — `key = (venue, account_id)`; `if key not in self._memo: self._memo[key] = self._plugins[venue].build(spec)`; `tests/unit/connectors/test_provider.py` proves identity-on-same-key + distinct-on-different-account_id + build-once; `OkxSettings()` is a local var constructed fresh inside `OkxConnectorPlugin.build` — never stored on the bundle/registry/memo |
| 9 | The backtest oracle stays byte-exact | ✓ VERIFIED | Ran independently: `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (46189.87730727451 unchanged) |
| 10 | `mypy --strict` clean on all new/modified venue substrate + `LiveTradingSystem` | ✓ VERIFIED | Ran independently: `poetry run mypy --strict itrader/trading_system/live_trading_system.py itrader/venues/assemble.py itrader/venues/lifecycle.py itrader/venues/bundle.py itrader/venues/registry.py itrader/venues/okx_plugin.py itrader/venues/paper_plugin.py itrader/connectors/provider.py itrader/connectors/stream_supervisor.py` → "Success: no issues found in 9 source files" |

**Score:** 10/10 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/venues/registry.py` | Two independent registries | ✓ VERIFIED | Exists, 4-SPACE, no ccxt/sqlalchemy import |
| `itrader/venues/bundle.py` | `VenueBundle` + `VenuePlugin`/`DataProviderPlugin` Protocols | ✓ VERIFIED | Frozen+slots dataclass, D-02 shape (exchange/account_factory mandatory, connector/lifecycle Optional None) |
| `itrader/venues/okx_plugin.py` | OKX venue/data/connector plugins, triple-deferral-lazy | ✓ VERIFIED | All concretion imports inside method bodies |
| `itrader/venues/paper_plugin.py` | Paper venue reusing `'simulated'` exchange | ✓ VERIFIED | `PaperVenuePlugin.__init__` takes the injected simulated exchange; no `register("simulated"` anywhere |
| `itrader/venues/lifecycle.py` | `VenueLifecycle` start/stop None-guards | ✓ VERIFIED | Structural `if self._bundle.connector is not None` guards, no venue-string comparisons |
| `itrader/venues/assemble.py` | `assemble_venue` delegation seam | ✓ VERIFIED | Resolves both registries, shares one `ConnectorProvider`, returns `(bundle, lifecycle)` |
| `itrader/connectors/provider.py` | `ConnectorProvider` `(venue, account_id)` memo | ✓ VERIFIED | Build-once-memoize, `close_all()` disconnects all |
| `itrader/connectors/stream_supervisor.py` | Shared `StreamSupervisor` | ✓ VERIFIED | 14.5KB, 0 tabs, ccxt-free, parameterized over 3 donor configs |
| `itrader/price_handler/providers/live_provider.py` | `LiveDataProvider` Protocol + `BaseLiveDataProvider` | ✓ VERIFIED | runtime_checkable, no-op defaults for optional seams |
| `itrader/core/money.py::precision_to_scale` | Shared money util | ✓ VERIFIED | Public via `__all__`, `Decimal(str(value))` string-entry discipline |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `LiveTradingSystem.__init__` | `assemble_venue` | delegation call, registry membership gate | ✓ WIRED | `if self.exchange in exec_registry: bundle, self._venue_lifecycle = assemble_venue(...)` (line 545-548) |
| `assemble_venue` | `ExecutionVenueRegistry`/`DataProviderRegistry` | `.get(spec.execution_venue)` / `.get(spec.data_provider)` | ✓ WIRED | Confirmed in `itrader/venues/assemble.py:71,75` |
| `OkxVenuePlugin.build_bundle` + `OkxDataPlugin.build_provider` | `ConnectorProvider.get("okx", account_id, spec)` | shared memoized connector | ✓ WIRED | Both call `connectors.get("okx", account_id, spec)` with the same key |
| `LiveTradingSystem._okx_exchange`/`_okx_data_provider`/`_venue_account` | `bundle.connector is not None` | structural None-guard | ✓ WIRED | Lines 556-594 — replaces the old venue-string branch |
| `universe_handler._resolve_added_instruments` | `resolver.resolve_precision(sym)` | rewired capability call | ✓ WIRED | No dangling `.resolve(` call remains |
| `okx.py::_supervisor.run` | `StreamSupervisor` | delegation from all 3 donor arms | ✓ WIRED | `_run_stream_supervisor` grep-clean on all 3 arms; `venue.py` preserves reduced surface (no mark_up/reset_budget calls) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| VENUE-01 | 05-04 | Two registries select execution venue and data provider independently | ✓ SATISFIED | `ExecutionVenueRegistry`/`DataProviderRegistry` + `SystemSpec` selectors |
| VENUE-02 | 05-04, 05-05 | `VenuePlugin` Protocol builds a `VenueBundle` | ✓ SATISFIED | `VenuePlugin`/`DataProviderPlugin` Protocols + OKX/paper concretions |
| VENUE-03 | 05-04, 05-05 | Connectors memoized by `(venue, account_id)`; credentials never persisted | ✓ SATISFIED | `ConnectorProvider` memo; `OkxSettings()` local to `build()` |
| VENUE-04 | 05-02 | Precision + validation become exchange capabilities | ✓ SATISFIED | `resolve_precision`/`validate_symbol` on `AbstractExchange` |
| VENUE-05 | 05-03 | `LiveDataProvider` Protocol with optional streaming seams via a no-op base | ✓ SATISFIED | `live_provider.py`; `ReplayDataProvider` inherits `BaseLiveDataProvider` |
| VENUE-06 | 05-06 | `VenueLifecycle` orchestrator encodes fixed start/stop order, None-guards | ✓ SATISFIED | `VenueLifecycle`; 0 `if exchange==` matches in `live_trading_system.py` |
| VENUE-07 | 05-01 | Shared `StreamSupervisor` replaces triplicated reconnect logic | ✓ SATISFIED | `stream_supervisor.py`; all 3 donor arms delegate |

All 7 phase requirement IDs (VENUE-01..07) are declared in plan frontmatter, mapped to REQUIREMENTS.md, and marked Complete. No orphaned requirements found for Phase 5.

### Behavioral Spot-Checks / Independent Test Runs

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backtest oracle byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | ✓ PASS |
| OKX inertness register-vs-build | `poetry run pytest tests/integration/test_okx_inertness.py -q` | 3 passed | ✓ PASS |
| Live venue wiring / paper lifecycle / paper parity / restart restore / reservation inertness | `poetry run pytest tests/integration/test_live_system_okx_wiring.py tests/integration/test_live_paper_lifecycle.py tests/integration/test_paper_parity.py tests/integration/test_paper_restart_restore.py tests/integration/test_reservation_inertness.py -q` | 20 passed | ✓ PASS |
| Unit coverage (venues, connectors, price_handler, execution, universe, core) | `poetry run pytest tests/unit/venues tests/unit/connectors tests/unit/price_handler tests/unit/execution tests/unit/universe tests/unit/core -q` | 602 passed | ✓ PASS |
| mypy --strict on all new/modified venue substrate | `poetry run mypy --strict <9 files>` | Success: no issues found | ✓ PASS |
| Full suite | `poetry run pytest tests -q` | 2130 passed, 6 skipped (OKX-demo-credential-gated) | ✓ PASS |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/venues/paper_plugin.py:36-39` + `itrader/trading_system/live_trading_system.py:86-93` | PAPER_PARITY_* constants | Duplicated literal constants across two modules (WR-01, advisory) | ℹ️ Info | Silent-desync risk if one copy is edited without the other; flagged by 05-REVIEW.md, non-blocking per verification scope, does not affect goal achievement — both copies currently hold identical values and the paper-parity test passes |
| `itrader/connectors/provider.py:79-83` | `ConnectorProvider.close_all` | Loop aborts + skips `self._memo.clear()` if one `disconnect()` raises (WR-02, advisory) | ℹ️ Info | A raising disconnect during teardown could strand later-keyed connectors undisconnected and leave them in the memo; flagged by 05-REVIEW.md, non-blocking — no test currently exercises a raising disconnect path |

No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers found in any of the 21 files touched by this phase (grep-verified). No stub patterns (`return null`/`return {}`/hardcoded empty data flowing to consumers) found.

### Human Verification Required

None. All must-haves were verifiable via grep, direct code read, and independently-executed automated tests (not SUMMARY.md claims). No visual/UX/external-service/real-time behaviors are part of this phase's scope (pure backend registry/plugin substrate).

### Gaps Summary

No gaps. All 10 derived truths (roadmap success criteria + PLAN frontmatter must-haves, merged and deduplicated) verified against the actual codebase, not SUMMARY.md narrative. Both standing gates (backtest oracle byte-exact, OKX inertness register-vs-build) were re-run independently in this verification and passed. mypy --strict clean. Full test suite (2130 passed, 6 skipped — all OKX-demo-credential-gated) matches the claimed count exactly. Two advisory (non-blocking) code-quality observations from 05-REVIEW.md are carried forward as Info-level anti-patterns for awareness; they do not block phase completion or affect goal achievement.

---

_Verified: 2026-07-12T23:32:45Z_
_Verifier: Claude (gsd-verifier)_
