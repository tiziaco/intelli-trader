# Phase 5: Venue Registry + Bundle - Research

**Researched:** 2026-07-10
**Domain:** Internal architecture refactor — venue parametrization (registries + plugins + shared connector/stream infra) on the live overlay of an event-driven trading engine
**Confidence:** HIGH (every claim below is verified by reading current code; no external-dependency research applies — milestone gate forbids new deps)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (Explicit-map registration — no import side effects):** Both registries are plain `dict[name -> plugin]` populated by explicit `register("okx", OkxVenuePlugin())` calls at the composition root. No decorator self-registration, no entry-points/`importlib.metadata`. Registration-as-explicit-call keeps "register ≠ import concretion" greppable.
- **D-02 (Execution-only `VenueBundle`; data provider built by the separate registry):** `VenueBundle` is `@dataclass(frozen=True, slots=True)` carrying only the execution arm — `exchange: AbstractExchange` + `account_factory: Callable[[PortfolioRef, AccountConfig], Account]` (both mandatory), `connector: LiveConnector | None = None`, `lifecycle: VenueLifecycle | None = None` (Optional). Data provider built by `DataProviderRegistry`, not carried in the bundle.
- **D-03 (Shared `ConnectorProvider` — one build recipe per venue, memoized by `(venue, account_id)`):** A dedicated `ConnectorProvider` owns the per-venue build recipe (`ConnectorPlugin.build(spec)`) AND the `(venue, account_id)` memo + `close_all()`. Both exec `build_bundle` and data `build_provider` call `connectors.get(venue, account_id, spec)` and receive the same instance.
- **D-04 (Triple-deferral laziness — correctness-critical):** `ConnectorPlugin.build()` MUST keep BOTH the concretion `import` and the `OkxSettings()` construction inside `build()`. Layers: (1) register is inert; (2) lazy import guards the backtest import graph; (3) `OkxSettings()` construction inside `build()` guards missing creds; (4) `connector.connect()` I/O deferred to `start()`. Backtest selects paper/simulated (`connector=None`) and never touches `ConnectorProvider`. **Planner/executor MUST NOT hoist plugin imports to module top.**
- **D-05 (Registry is a LIVE-ONLY overlay; backtest firewall):** `compose_engine(ctx, spec)` builds the shared base graph — including the `'simulated'` `SimulatedExchange` — for BOTH modes. Backtest uses `'simulated'` directly and never invokes the venue registry. `PaperVenuePlugin.build_bundle` reuses the compose-built `'simulated'` exchange (`connector=None`, `SimulatedAccount`). `'simulated'` is NOT a registered venue.
- **D-06 (P5 removes both branches via an `assemble_venue` helper seam; P6 promotes the call):** P5 lands the registries/plugins/`ConnectorProvider`/`VenueLifecycle` AND `assemble_venue(ctx, spec, connectors) -> (VenueBundle, VenueLifecycle)` that `LiveTradingSystem.__init__` delegates to — the `if exchange==` branches are gone in P5. P6 relocates the call site into `build_live_system`. The seam is independently unit-testable in P5.
- **D-07 (`account_id` = config-known STABLE NAME resolved pre-`connect()`; single default in P5):** Memo key `account_id` is a config-sourced name known before `connect()`. P5 uses a single default `spec.account_id or "default"`; creds from `OkxSettings()` reading `OKX_API_*`. Per-account env-naming scheme deferred to P11. Venue-provided UID (post-connect) is a different identifier deferred to P7/P11.
- **D-08 (Shared `StreamSupervisor` = composition class in `connectors/stream_supervisor.py`):** Standalone `StreamSupervisor(config, halt_signal, on_down, on_up, logger)` with `async run(connect_and_consume, name)`, `reset_budget(name)`, `mark_down`/`mark_up` — owning `_reconnect_attempts`/`_streams_down` + WR-03 payload-only reset. New 4-space file. Each of the three donor arms HAS-A supervisor and delegates. Composition, not mixin/base. Behavior to preserve exactly: transient/fatal classification, clean-return→reconnect, unclassified→fail-safe halt, retry-ceiling→halt, debounce+capped-backoff, scrub discipline (never `str(exc)` — T-05-27), `CancelledError` re-raise, WR-03 payload-only budget reset.
- **D-09 (Precision/validate as `AbstractExchange` capabilities — VENUE-04):** `resolve_precision(symbol)` joins `validate_symbol(symbol)` on `AbstractExchange`; `_OkxPrecisionResolver` + `_PrecisionResolver` deleted; `_precision_to_scale` → shared money util (`core/money.py`). Simulated exchange's `resolve_precision` returns a sensible default with no markets map.
- **D-10 (Provider uniformity rule):** Optional METHOD on a PRESENT object → no-op default on `BaseLiveDataProvider` (call unconditionally, kills `hasattr`); entirely ABSENT component → explicit `None`-guard in `VenueLifecycle`. Null-Object rejected. "Branch-free" is NOT the goal — killing `if exchange==` venue-type branches is.
- **D-11 (CF-9 OKX markets-map freshness — reuse the existing removal path, no parallel drop):** Keep the OKX `markets` map fresh so the existing `validate_symbol → delta.removed → unsubscribe/force-close` path catches mid-session delistings; close the fail-open-before-load window (`validate_symbol` returning True when `markets` isn't yet a dict). Do NOT add a second parallel drop mechanism.

### Claude's Discretion
- Plan/wave slicing across VENUE-01..07 (subject to the byte-exact + inertness gates).
- Exact module paths (`execution_handler/venues/` vs a new top-level `venues/`), precise `StreamSupervisor`/`ConnectorProvider`/registry method names + signatures, the default `account_id` literal, and whether `VenueLifecycle` is a class or small ordered helper.
- `resolve_precision` return shape and where exactly `_precision_to_scale` lands in `core/money.py`.

### Deferred Ideas (OUT OF SCOPE)
- Multi-account credential scheme (`OKX_<ACCOUNT>_*`) + per-`PortfolioSpec` account_id + per-account credential dispatch → **P11**.
- Venue-provided account-UID reconciliation → **P7 / P11**.
- Null-Object pattern for absent components — considered, rejected (D-10). Do not re-litigate.
- `build_live_system` factory + facade shrink + `UniverseWiring` extraction → **P6**.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VENUE-01 | Two registries (`ExecutionVenueRegistry` + `DataProviderRegistry`) select via `SystemSpec` (`execution_venue` + `data_provider`) | `system_spec.py` shape verified (§Standard Stack); append selector fields LAST to preserve by-name callsites. Registry is a plain dict (D-01). |
| VENUE-02 | `VenuePlugin` builds `VenueBundle` with concretions lazy-imported inside `build_bundle`; `test_okx_inertness.py` is the P5 gate | Inertness gate mechanics fully mapped (§Inertness Gate); `LiveConnector`/`AbstractExchange` `runtime_checkable` Protocols are the mirror shape. |
| VENUE-03 | Connectors memoized by `(venue, account_id)`; creds per-`account_id`, env-sourced, never persisted | Today's `if exchange=='okx'` block already builds ONE `OkxConnector` and injects it 3 ways (LTS:549-573) — `ConnectorProvider` formalizes this. |
| VENUE-04 | Precision + validation as `AbstractExchange` capabilities; `_OkxPrecisionResolver`/`_PrecisionResolver` deleted; `_precision_to_scale` → money util | **Drift found** (§Line-Number Drift): `_PrecisionResolver` Protocol is in `universe_handler.py:100`, NOT `live_trading_system.py`. Rewire the universe handler's resolver seam too. |
| VENUE-05 | `LiveDataProvider` Protocol + `BaseLiveDataProvider` no-op defaults — no `hasattr` | Mirror the `LiveConnector` Protocol pattern; no-op defaults per D-10. |
| VENUE-06 | `VenueLifecycle` orchestrator None-guards absent members; every venue-string branch removed | 6 venue-string branches verified (LTS:541/625/1378/1751/1778/1817); `assemble_venue` seam (D-06). |
| VENUE-07 | Shared `StreamSupervisor` replaces triplicated supervisors (CF-4); connector-contract docstrings on `connectors/base.py` (CF-3); CF-9 markets-map freshness | Full 3-way donor diff (§StreamSupervisor Donor Diff) — the donors are NOT identical; supervisor must be parameterized. |
</phase_requirements>

## Summary

This is a high-risk internal refactor on the **live overlay** of the engine; the design is fully locked in CONTEXT.md (D-01..D-11). The single highest-value output of this research is a **codebase-verified map with the drifts called out**, so the planner can trust the canonical refs rather than re-deriving. Two milestone gates bracket every plan: the **byte-exact oracle** (`46189.87730727451`, 134 trades, `check_exact=True`) and the **OKX import-inertness** subprocess probe (register-vs-build). The backtest path is firewalled from the registry by construction (D-05) — verified: `build_backtest_system` reads `execution_handler.exchanges.get('simulated')` directly and never touches a registry.

I verified all six venue-string branches, the two resolvers, the compose seam, the backtest reader, and the three `StreamSupervisor` donors against current code. **Two drifts from CONTEXT.md matter:** (1) the `_PrecisionResolver` Protocol lives in `universe/universe_handler.py:100`, not `live_trading_system.py:110-174` (the file only holds `_precision_to_scale` + the `_OkxPrecisionResolver` *impl*); (2) **`portfolio_handler/account/venue.py` is 4-SPACE indented, not TABS** as CONTEXT.md D-08 and the code-context section both claim — this is a repeat of the exact tab/space hazard that bit a prior planner. The three stream supervisors are also **not behaviorally identical** — they diverge on the transient tuple breadth, clean-return policy, ladder placement, and the WR-03 payload-reset surface — so the shared `StreamSupervisor` must be **parameterized**, not a verbatim single body.

**Primary recommendation:** Slice P5 as VENUE-04 + VENUE-07 (mechanical, low-oracle-risk, independently testable) first, then the registry/plugin/`ConnectorProvider`/`assemble_venue` core (VENUE-01/02/03/06), with VENUE-05 folded into the data-registry plan and CF-9 folded into the VENUE-07 plan. Gate every plan on the oracle + inertness subprocess probe. Treat the `StreamSupervisor` extraction as a behavior-preserving move of the **canonical donor** (`okx_provider`), parameterized to re-cover the two forks exactly.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Venue selection (exec + data) | Composition root (live) | `SystemSpec` (declarative) | Registries are populated + resolved only at the live root; backtest never selects (D-05) |
| Connector lifetime + memo | `ConnectorProvider` (connectors/) | `LiveConnector` Protocol | VENUE-03 memoization belongs beside the connector package (D-03) |
| Stream reconnect/halt state | `StreamSupervisor` (connectors/) | each donor arm HAS-A | Security-critical reconnect state quarantined in one 4-space home (D-08) |
| Symbol precision/validation | `AbstractExchange` concretion | `core/money.py` util | Venue is the source of truth for its markets map (D-09) |
| Lifecycle orchestration (start/stop order) | `VenueLifecycle` | `assemble_venue` seam | None-guards absent members; kills venue-string branches (D-06/D-10) |
| Account minting | `account_factory` in `VenueBundle` | per-portfolio (P11) | Mandatory bundle member; single default account in P5 (D-02/D-07) |

## Standard Stack

**No new libraries.** Milestone gate: "Zero new third-party dependency, no poetry change anywhere in P1–P12" (REQUIREMENTS.md line 25, line 349). Everything is stdlib + already-pinned packages already imported on the live path.

| Facility | Source | Purpose | Provenance |
|----------|--------|---------|-----------|
| `Protocol` + `runtime_checkable` | `typing` (stdlib) | The swap-a-fake seam for `VenuePlugin`/`ConnectorPlugin`/`LiveDataProvider` | [VERIFIED: connectors/base.py:38, execution_handler/exchanges/base.py:1] |
| `@dataclass(frozen=True, slots=True)` | `dataclasses` (stdlib) | `VenueBundle` shape (D-02) | [VERIFIED: codebase convention — events, `_PendingBracket`] |
| `Decimal` + `to_money`/`quantize` | `core/money.py` | `_precision_to_scale` lands here (D-09) | [VERIFIED: core/money.py:38 `__all__ = ["ONE","to_money","quantize"]`] |
| `pydantic` `BaseModel` | `config/stream.py::StreamSettings` | reconnect tuning the supervisor reads | [VERIFIED: config/stream.py:33-56] |
| `pydantic-settings` `BaseSettings` | `config/okx_settings.py::OkxSettings` | env creds, `SecretStr`, constructed only inside `build()` | [VERIFIED: config/okx_settings.py:54-84] |
| `ccxt` / `ccxt.pro` | lazy-imported inside supervisor/`build()` | transient/fatal exception taxonomy | [VERIFIED: okx_provider.py:467, okx.py:718 — `import ccxt` INSIDE method] |

**Installation:** None. Any poetry change fails the milestone gate.

## Package Legitimacy Audit

**Not applicable** — this phase installs no external packages. All facilities are stdlib or already-pinned dependencies (`pydantic`, `pydantic-settings`, `ccxt`) already present in `poetry.lock` and already imported on the live path. No `npm view` / `pip index` verification required.

## Line-Number Drift Report

Verified every canonical ref in CONTEXT.md against current `HEAD`. Results:

| CONTEXT.md ref | Claimed | Actual | Status |
|----------------|---------|--------|--------|
| `if self.exchange == 'okx'` | LTS:541 | LTS:541 | ✅ exact |
| `elif self.exchange == 'paper'` | LTS:625 | LTS:625 | ✅ exact |
| Lifecycle guards | LTS:1378/1751/1778/1817 | LTS:1378/1751/1778/1817 | ✅ all four exact |
| `_precision_to_scale` | LTS:110-174 | LTS:110-131 | ✅ (function at :110) |
| `_OkxPrecisionResolver` (impl) | LTS:110-174 | LTS:134-183 | ✅ (class at :134) |
| **`_PrecisionResolver` Protocol** | LTS:110-174 | **`universe/universe_handler.py:100`** | ⚠️ **DRIFT** — Protocol + `set_precision_resolver` (:253) + `_precision_resolver` field (:222) live in the universe handler, NOT LTS. LTS:146 only *references* it in a docstring. |
| compose seam | compose.py:114 + 175-181 | compose.py:114 (`compose_engine`), :181 (`exchanges.get('simulated')`) | ✅ |
| backtest reads `'simulated'` | backtest_trading_system.py:374-378 | :375 `self.execution_handler.exchanges.get('simulated')` | ✅ (reporting/curate path, NOT hot path — firewall confirmed) |
| okx `validate_symbol` | okx.py:1007-1032 | okx.py:1007-1023 | ✅ (method body 1007-1023) |
| StreamSupervisor canonical donor | okx_provider.py:453-575 | :453-579 (`_reset_reconnect_budget` ends :579) | ✅ |
| okx.py fork | okx.py:699 | okx.py:699-841 | ✅ |
| venue.py fork | venue.py:349 | venue.py:349-431 | ✅ location; ⚠️ **see indentation + missing-methods drift below** |
| `_OkxPrecisionResolver` wiring | (not pinned) | LTS:1438-1445 via `set_precision_resolver` | ✅ found for completeness |

### ⚠️ Drift 1 — `_PrecisionResolver` Protocol is in the universe handler
VENUE-04 is **not** just "add `resolve_precision` to `AbstractExchange` + delete the two resolvers in LTS." The universe handler owns:
- `class _PrecisionResolver(Protocol)` with method `resolve(symbol) -> Instrument | None` (`universe_handler.py:100`)
- `self._precision_resolver: _PrecisionResolver | None` field (:222)
- `set_precision_resolver(resolver)` seam (:253)
- `_resolve_added_instruments(...)` call site that invokes `resolver.resolve(sym)`

After VENUE-04, the exchange capability is named `resolve_precision(symbol)` (per D-09), **not** `resolve(symbol)`. So the planner MUST rewire the universe handler: replace the `_PrecisionResolver` Protocol with a bound to `AbstractExchange` (or a narrow `_SupportsResolvePrecision` Protocol exposing `resolve_precision`), rename the call, and rewire the LTS wiring at :1438-1445 (`set_precision_resolver(exchange)` where exchange now carries `resolve_precision`). Missing this leaves a dangling `resolve` call after the resolvers are deleted.

### ⚠️ Drift 2 — `venue.py` is 4-SPACE, not TABS (repeat of a known hazard)
CONTEXT.md D-08 (line 133) and the code-context section (lines 225, 258) both label `portfolio_handler/account/venue.py` as **[TABS]**. **This is wrong.** Byte check:
- `portfolio_handler/account/venue.py`: **0 tab-indented lines, 604 space-indented** → **4-SPACE**
- `execution_handler/exchanges/okx.py`: **860 tab-indented, 0 space** → **TABS** (CONTEXT correct here)
- `price_handler/providers/okx_provider.py`: 4-SPACE (canonical donor); `connectors/base.py`, `config/stream.py`, `core/money.py`, `universe/universe_handler.py`: all 4-SPACE; `trading_system/compose.py`, `system_spec.py`, `execution_handler/exchanges/base.py`: TABS.

This is the exact trap flagged in prior-session memory ("trading_system/ indentation is split per file... measure bytes per file, never generalize"). The delegation edit in `venue.py` must be **4-space**, and only the delegation edit in `okx.py` must be tabs. Do not transplant a body across styles.

## StreamSupervisor Donor Diff (D-08 / VENUE-07)

The three donors are **NOT behaviorally identical** — extracting one verbatim and pointing all three at it would silently change behavior for two of them. The shared class must be **parameterized**. Verified diff:

| Aspect | `okx_provider.py` (canonical, 4-space) | `okx.py` (exec, TABS) | `venue.py` (account, **4-SPACE**) |
|--------|----------------------------------------|-----------------------|-----------------------------------|
| Entry | `_run_stream_supervisor(connect_and_consume, name)` :453 | `_run_stream_supervisor(consume, name)` :699 | `_run_stream_supervisor(consume, name)` :349 |
| Transient tuple | **6 types**: `ccxt.NetworkError, RequestTimeout, DDoSProtection, aiohttp.ClientError, ConnectionError, asyncio.TimeoutError` :468-470 | **3 types**: `ccxt.NetworkError, RequestTimeout, DDoSProtection` :719-720 | **3 types**: same as okx.py :367-368 |
| Clean return of consume | → **reconnect** (`drop_label="socket closed by server"`, falls to ladder) :476-478 | → **`return`** (stop; "forever-loop returning cleanly is not expected") :726 | → **`return`** (stop) :374 |
| Reconnect ladder placement | **shared bottom** (handles {transient, clean-return}) :496-517 | **inside `except transient`** :732-754 | **inside `except transient`** :382-400 |
| Fatal → escalate + return | yes :481-484 | yes :729-731 | yes :377-380 |
| Unclassified → fail-safe halt + return | yes :487-495 | yes :755-765 | yes :401-406 |
| `CancelledError` re-raise | yes :479-480 | yes :727-728 | yes :375-376 |
| Retry-ceiling → escalate halt | yes :499-503 | yes :735-738 | yes :384-387 |
| debounce + capped backoff | yes :504-517 | yes :740-754 | yes :388-400 |
| `mark_down` (pause on sustained drop) | `_mark_stream_down` :544 | `_mark_stream_down` :798 (+ `_disconnect_ts_ms` catch-up floor D-12 :807) | `_mark_stream_down` :423 |
| `mark_up` / on-healthy resume | `_on_stream_healthy` :554 | `_on_stream_healthy` :814 | **ABSENT** — no `_on_stream_healthy` |
| WR-03 payload budget reset | `_reset_reconnect_budget` :569, gated post-SNAPSHOT (`payload_seen`) :421-423 | `_reset_reconnect_budget` :833, gated on any payload | **ABSENT** — no `_reset_reconnect_budget` |
| scrub (`type(exc).__name__`, never `str(exc)`) | yes :511-516 | yes :747-753 | yes :394-399 |
| State fields | `_reconnect_attempts`, `_streams_down`, 4 tuning fields, 3 callbacks (`_halt_signal`/`_on_stream_down`/`_on_stream_up`) :167-182 | same + `_disconnect_ts_ms` :141-170 | same MINUS `_on_stream_up` (venue never resumes-up) |

### Implications for the shared `StreamSupervisor`
1. **`transient_exceptions` must be a constructor parameter.** The provider needs the wider aiohttp/ConnectionError/TimeoutError set; the exec/account arms use ccxt-only. Using a union would change okx.py/venue.py behavior (an `aiohttp.ClientError` would go transient→reconnect instead of unclassified→HALT). To "preserve exactly" (D-08), pass each arm's exact tuple.
2. **`reconnect_on_clean_return: bool` must be a parameter.** Provider=True (socket-close is a normal reconnect), exec/account=False (a forever-loop returning cleanly is a stop). This is coupled to the consume-loop shape: the provider's `_connect_and_consume_candles` returns when the server closes; the exec/account consumes are `while True: await watch_*()`.
3. **`reset_budget(name)` and `mark_up(name)` are methods the CONSUME loop calls, not the supervisor loop.** The provider gates `reset_budget` on a post-snapshot payload (WR-03 `payload_seen`); okx.py gates on any payload. The supervisor loop only owns the classification ladder + `mark_down` + budget/escalation.
4. **`venue.py` currently has NO `mark_up`/`reset_budget`** — its account/positions streams pause-down but never resume-up nor reset the budget. See Open Question 1 — the planner must decide whether the refactor **normalizes** venue.py to the full WR-03 surface (a behavior change) or **preserves** its reduced behavior (consume loop simply never calls `reset_budget`/`mark_up`). D-08 says "preserve exactly" → default to preserve, and flag the venue gap as a separate todo, do not silently normalize inside the extraction.
5. **`_disconnect_ts_ms` (D-12 catch-up floor) stays in the okx.py arm**, fed via the `on_down` callback — it is NOT supervisor state (only the exec arm has it).

## Architecture Patterns

### System Architecture Diagram

```
                        SystemSpec(execution_venue, data_provider, account_id?)
                                 │  (declarative WHAT-to-run; live root reads it)
                                 ▼
   ┌──────────────────────── LIVE COMPOSITION ROOT (P5: LiveTradingSystem.__init__ → P6: build_live_system)
   │
   │   register("okx", OkxVenuePlugin())          register("okx", OkxDataPlugin())
   │   register("paper", PaperVenuePlugin())       register("replay", ReplayDataPlugin())  ← test-only (P12)
   │        │  (inert: stores objects, D-01)              │
   │        ▼                                             ▼
   │   ExecutionVenueRegistry                        DataProviderRegistry
   │        │  .get(spec.execution_venue)                │ .get(spec.data_provider)
   │        ▼                                             ▼
   │   assemble_venue(ctx, spec, connectors) ─────────────────────────►  (single delegation seam, D-06)
   │        │                                             │
   │        │  plugin.build_bundle(ctx, spec, connectors) │ plugin.build_provider(ctx, spec, connectors)
   │        │   └─ LAZY import ccxt.pro/OkxExchange        │   └─ LAZY import OkxDataProvider
   │        │   └─ connectors.get("okx","default",spec) ◄──┴───── SAME connector instance (D-03 memo)
   │        ▼                                                          │
   │   VenueBundle(exchange, account_factory,                         │
   │       connector?, lifecycle?)                          ConnectorProvider
   │        │                                               (memo (venue,account_id) → LiveConnector,
   │        ▼                                                 ConnectorPlugin.build(spec), close_all())
   │   VenueLifecycle.start/stop  ── None-guards absent members (paper: connector=None, D-10)
   │        │                              │
   │        ▼                              ▼
   │   exchange.on_order / on_market_data  StreamSupervisor.run(connect_and_consume, name)  (shared, D-08)
   │   (routed by event.exchange in           ▲            ▲
   │    ExecutionHandler, unchanged)          │ HAS-A      │ HAS-A
   │                                    OkxExchange   OkxDataProvider / VenueAccount
   │
   └── compose_engine(ctx, spec) builds the SHARED base graph incl. 'simulated' SimulatedExchange
       for BOTH modes ─────────────────────► backtest reads exchanges.get('simulated') DIRECTLY
                                              (NEVER the registry — D-05 byte-exact firewall)
```

### Recommended Project Structure
Discretion (D-08/CONTEXT): the supervisor is pinned to `connectors/` (4-space, beside `LiveConnector`). For the registry/plugin/provider surface, recommend a new home that keeps the exec/data plugin concretions lazy and greppable:

```
itrader/connectors/
├── base.py                 # LiveConnector Protocol (+ CF-3 connector-contract docstrings)
├── okx.py                  # OkxConnector (existing)
├── stream_supervisor.py    # NEW 4-space — shared StreamSupervisor (D-08)
└── provider.py             # NEW — ConnectorProvider (memo (venue,account_id), ConnectorPlugin Protocol)

itrader/venues/             # RECOMMENDED new top-level package (parallels connectors/; both registries live here)
├── registry.py             # ExecutionVenueRegistry + DataProviderRegistry (plain dict, D-01)
├── bundle.py               # VenueBundle frozen dataclass (D-02); VenuePlugin/DataProviderPlugin Protocols
├── lifecycle.py            # VenueLifecycle (class or helper — discretion)
├── assemble.py             # assemble_venue(ctx, spec, connectors) seam (D-06)
├── okx_plugin.py           # OkxVenuePlugin + OkxDataPlugin (LAZY imports inside build_bundle/build_provider)
└── paper_plugin.py         # PaperVenuePlugin (reuses compose-built 'simulated', connector=None)

itrader/price_handler/providers/
└── base.py (or live_provider.py)   # NEW — LiveDataProvider Protocol + BaseLiveDataProvider no-op defaults (VENUE-05)
```
Rationale for a top-level `venues/` over `execution_handler/venues/`: the data-provider registry is NOT an execution concern, so nesting both registries under `execution_handler/` mis-tiers the data half. A sibling of `connectors/` keeps the two-registry decoupling (VENUE-01) structurally obvious. **This is a discretion call — the planner may choose `execution_handler/venues/` if it prefers; the inertness gate is agnostic to the path as long as imports stay lazy.**

### Pattern 1: Lazy-import-inside-`build()` plugin (D-04, correctness-critical)
```python
# venues/okx_plugin.py — Source: mirrors LTS:541-549 (today's if exchange=='okx' block)
class OkxVenuePlugin:                      # satisfies VenuePlugin Protocol structurally
    def build_bundle(self, ctx, spec, connectors) -> "VenueBundle":
        # (2) lazy import guards the backtest import graph — ccxt.pro never loads
        from itrader.execution_handler.exchanges.okx import OkxExchange
        from itrader.portfolio_handler.account import VenueAccount
        # (3) OkxSettings() constructed HERE, never at module top / register time —
        #     guards missing OKX_API_* on cred-less/backtest machines
        connector = connectors.get("okx", spec.account_id or "default", spec)  # (D-03 memo)
        exchange = OkxExchange(ctx.bus, connector)
        return VenueBundle(exchange=exchange,
                           account_factory=lambda ref, cfg: VenueAccount(connector, ...),
                           connector=connector,
                           lifecycle=...)
```

### Pattern 2: ConnectorProvider memo (D-03/VENUE-03)
```python
# connectors/provider.py
class ConnectorProvider:
    def __init__(self, plugins: dict[str, "ConnectorPlugin"]):
        self._plugins = plugins
        self._memo: dict[tuple[str, str], "LiveConnector"] = {}
    def get(self, venue: str, account_id: str, spec) -> "LiveConnector":
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = self._plugins[venue].build(spec)   # build() = (2)+(3) lazy layers
        return self._memo[key]
    def close_all(self) -> None:
        for c in self._memo.values(): c.disconnect()
```
`ConnectorPlugin.build(spec)` keeps `import ccxt.pro`/`OkxConnector(OkxSettings())` inside — the memo dedups the SAME `(venue, account_id)` so exec + data arms share one `ccxt.pro` client/loop (the reason a memo exists at all, per D-03).

### Anti-Patterns to Avoid
- **Hoisting a plugin's concretion import to module top** — silently reddens `test_okx_inertness.py` (D-04). The `_FORBIDDEN` probe list at `test_okx_inertness.py:38-82` will catch `ccxt.pro`, `itrader.connectors.okx`, etc.
- **Constructing `OkxSettings()` at register/module time** — breaks cred-less/backtest machines (D-04 layer 3). It must be inside `build()`.
- **Routing backtest through a `'simulated'` plugin** — puts the registry on the byte-exact hot path (rejected in D-05). `'simulated'` is the compose base, not a registered venue.
- **Extracting one supervisor body verbatim for all three arms** — changes behavior for the two forks (see donor diff). Parameterize instead.
- **Transplanting the supervisor body into a tab file** — `okx.py` is TABS, but the shared class lives in a 4-space file; only a one-line tab-indented *delegation call* lands in `okx.py`. `venue.py` is 4-SPACE (not TABS — Drift 2).
- **Adding a second parallel "drop" mechanism for CF-9** — D-11 forbids it; reuse `validate_symbol → delta.removed`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Plugin discovery/registration | Decorator self-registration or entry-points | Explicit `register(name, plugin())` dict (D-01) | Decorator inverts inertness (registry imports every plugin module → one careless top-level `import ccxt.pro` reddens the gate) |
| Connector dedup | Per-plugin lambda memo duplicated across exec+data | Shared `ConnectorProvider` (D-03) | Single build recipe; one `ccxt.pro` client per `(venue, account_id)` |
| Reconnect/halt state | A 4th hand-copied supervisor | Shared `StreamSupervisor` (D-08) | Security-critical reconnect ladder quarantined + tested once |
| Precision → Decimal scale | New precision helper | `_precision_to_scale` relocated to `core/money.py` (D-09) | Money stays Decimal end-to-end; string-entry discipline already lives there |
| Absent-component branching | `NullConnector`/`NullAccount` classes | `Optional=None` bundle + `None`-guards in `VenueLifecycle` (D-10) | Fail-loud on unexpected `None`; matches D-02 bundle shape |
| Async→sync bridge | New threadsafe wrapper | `LiveConnector.call`/`spawn` (existing) | Already the established scheduling seam (connectors/base.py:53-67) |

**Key insight:** Every "new" surface in this phase is a **relocation/formalization of code that already exists** — the `if exchange=='okx'` block already builds one connector and injects it three ways (LTS:549-573); the three supervisors already exist; the resolvers already exist. The risk is not writing new logic, it is **moving security-critical/oracle-critical logic without behavior drift**.

## Runtime State Inventory

This phase is a code refactor of the **live overlay**, not a rename or a data migration. There is no stored-data/OS-registered/secret-key renaming.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore key/collection/user_id is renamed by this phase. `VenueStore` (P4) already exists and is untouched here. | None |
| Live service config | None — OKX venue config is env-sourced (`OKX_API_*`), read only inside `build()`; no external UI/DB config carries a renamed string. | None |
| OS-registered state | None — no Task Scheduler/pm2/systemd registration involves venue names. | None |
| Secrets/env vars | `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE`/`OKX_SANDBOX`/`OKX_REGION` — **names unchanged** (P5 uses the single default `account_id`; per-account `OKX_<ACCOUNT>_*` scheme is deferred to P11). Code reads them via `OkxSettings()` only inside `build()`. | None (P5); rename scheme is P11 |
| Build artifacts | None — no package rename; `pyproject.toml` unchanged (zero-dep gate). | None |

**Nothing found in any category requiring migration** — verified: the only `account_id` in P5 is the literal `"default"` (D-07), and no persisted record keys on a venue string that this phase changes.

## Common Pitfalls

### Pitfall 1: Silently reddening the inertness gate
**What goes wrong:** A plugin's `import ccxt.pro` (or `OkxExchange`) at module top, or `OkxSettings()` at register time, pulls the OKX stack onto the backtest import graph.
**Why it happens:** Natural instinct to put imports at the top of the file.
**How to avoid:** Keep imports + `OkxSettings()` inside `build_bundle`/`build`/`build_provider` (D-04). Extend `test_okx_inertness.py::_FORBIDDEN` (line 38-82) to name the new plugin concretion modules so a hoist fails loudly.
**Warning signs:** `test_okx_inertness.py` returncode != 0 with a `_FORBIDDEN` leak in stderr.

### Pitfall 2: Tab/space transplant in the supervisor delegation
**What goes wrong:** Pasting a 4-space delegation line into tab-indented `okx.py`, or (per Drift 2) assuming `venue.py` is tabs when it is 4-space → a mixed-indentation diff breaks the file, and `filterwarnings=["error"]` / mypy fails.
**How to avoid:** Measure bytes per file (this research did). `okx.py`=TABS; `venue.py`=4-SPACE; `okx_provider.py`=4-space; `connectors/stream_supervisor.py` (new)=4-space. Never generalize the package.
**Warning signs:** `IndentationError` / `TabError` at import; a diff that shows whitespace-only churn.

### Pitfall 3: Behavior drift when unifying the three supervisors
**What goes wrong:** A single verbatim body changes the transient tuple / clean-return policy for two arms; or normalizing venue.py to add `reset_budget`/`mark_up` changes when its budget resets.
**How to avoid:** Parameterize (`transient_exceptions`, `reconnect_on_clean_return`); keep `reset_budget`/`mark_up` as consume-loop-driven methods; preserve venue.py's reduced surface unless the planner explicitly decides to normalize (Open Question 1).
**Warning signs:** A stream test that asserts on the D-20 ceiling behavior or WR-03 payload-gating flips.

### Pitfall 4: Dangling `resolve()` after deleting the resolvers (Drift 1)
**What goes wrong:** Deleting `_OkxPrecisionResolver`/`_PrecisionResolver` without rewiring `universe_handler.py`'s `set_precision_resolver`/`_resolve_added_instruments`/Protocol leaves a call to `.resolve(sym)` on a now-absent surface, or a name mismatch (`resolve` vs `resolve_precision`).
**How to avoid:** VENUE-04 plan must include the universe-handler rewire (Protocol→`AbstractExchange` bound, `resolve`→`resolve_precision`, LTS:1438-1445 wiring).
**Warning signs:** mypy error on `_PrecisionResolver`; `AttributeError: resolve` at live poll.

### Pitfall 5: CF-9 fail-open-before-load closed with a parallel drop
**What goes wrong:** Adding a second delisting-drop mechanism inside the warmup retry loop (D-11 explicitly forbids this) → two code paths that can diverge.
**How to avoid:** Close the fail-open window inside `validate_symbol` itself (okx.py:1020-1023 currently returns `True` when `markets` isn't a dict). Options: gate readiness on a loaded markets map, or return `False`/defer until markets is a dict so an unvalidated symbol never enters membership. Keep the single `validate_symbol → delta.removed → unsubscribe` path for stale-cache delistings. See Open Question 2.
**Warning signs:** Two places that call `unsubscribe`/`force_close` on a removed symbol.

### Pitfall 6: Secret leakage in connector logs (T-05-27 / V7)
**What goes wrong:** Logging `str(exc)` from a connector error — it may carry request context / a secret.
**How to avoid:** The supervisor logs `type(exc).__name__` + a fixed label only; the halt reason is the fixed `'connector-fatal'` string (never exception text). The shared class must preserve this scrub (verified present in all three donors).
**Warning signs:** A log line interpolating a raw exception message in the reconnect/halt path.

## Code Examples

### Verified transient/fatal taxonomy (canonical donor)
```python
# Source: itrader/price_handler/providers/okx_provider.py:467-495 (VERIFIED, 4-space)
import ccxt  # lazy: ccxt already transitively imported on the live path only
transient = (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection,
             aiohttp.ClientError, ConnectionError, asyncio.TimeoutError)   # 6 types (provider only)
fatal = (ccxt.AuthenticationError, ccxt.PermissionDenied)
while True:
    try:
        await connect_and_consume(stream_name)
        drop_label = "socket closed by server"      # provider: clean return → reconnect
    except asyncio.CancelledError:
        raise                                        # cooperative teardown — never swallow
    except fatal as exc:
        self._escalate_connector_halt(stream_name, exc, "fatal auth/permission error"); return
    except transient as exc:
        drop_label = type(exc).__name__
    except Exception as exc:                         # unclassified → fail-safe HALT + return
        self._escalate_connector_halt(stream_name, exc, "unexpected error"); return
    # shared bottom ladder: ceiling → halt; else debounce + capped backoff (scrub: drop_label only)
```

### Verified backtest firewall (D-05)
```python
# Source: itrader/trading_system/backtest_trading_system.py:375 (VERIFIED)
exchange = self.execution_handler.exchanges.get('simulated')   # reads compose base DIRECTLY
# ... no registry, no plugin, no ConnectorProvider anywhere on this path
```

### Verified plugin-built exchange plugs into ExecutionHandler unchanged
```python
# Source: itrader/execution_handler/execution_handler.py:105,121 (VERIFIED)
exchange = self.exchanges.get(event.exchange)          # on_order routes by venue name
for name, exchange in self.exchanges.items(): ...       # on_market_data fans over all
# A plugin-built exchange registered under its venue name (e.g. exchanges['okx']) works as-is
```

### Verified precision → Decimal scale util (relocation target)
```python
# Source: itrader/trading_system/live_trading_system.py:110-131 (VERIFIED) — relocate to core/money.py
def _precision_to_scale(value):   # ccxt tick-size / DECIMAL_PLACES → Decimal scale
    if value is None: return None
    dec = Decimal(str(value))     # D-04 string entry — never Decimal(float)
    if dec <= 0: return None
    if dec == dec.to_integral_value() and dec >= 1:
        return Decimal(1).scaleb(-int(dec))            # e.g. 8 → 1e-8
    return dec
# core/money.py __all__ is currently ["ONE","to_money","quantize"] — add the new export
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `if exchange=='okx' / elif=='paper'` inline wiring (LTS:541/625) | Registry + `VenuePlugin` + `assemble_venue` seam | P5 (this phase) | Kills 6 venue-string branches; new venues register without editing LTS |
| Three hand-copied `_run_stream_supervisor` bodies | One parameterized `StreamSupervisor` (connectors/) | P5 (CF-4) | Security-critical reconnect state tested once |
| `_OkxPrecisionResolver` + `_PrecisionResolver` Protocol | `AbstractExchange.resolve_precision` capability | P5 (VENUE-04) | Venue owns its precision; universe handler rewired |
| `hasattr(provider, 'stream')` sprinkling | `BaseLiveDataProvider` no-op defaults + `LiveDataProvider` Protocol | P5 (VENUE-05) | Uniform provider wiring |
| `validate_symbol` returns True when markets unloaded (fail-open) | CF-9 fresh markets map + closed fail-open window | P5 (D-11) | Mid-session delistings caught via existing removal path |

**Deprecated/outdated after this phase:**
- `live_trading_system.py:110-183` (`_precision_to_scale`, `_OkxPrecisionResolver`) — deleted/relocated.
- `universe_handler.py:100` `_PrecisionResolver` Protocol — replaced by `AbstractExchange` bound.
- `_run_stream_supervisor` in all three donors — replaced by delegation to shared `StreamSupervisor`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended top-level `venues/` package path (vs `execution_handler/venues/`) | Recommended Project Structure | Low — explicitly a discretion area (CONTEXT); inertness gate is path-agnostic. Planner may choose either. |
| A2 | `venue.py`'s missing `mark_up`/`reset_budget` should be preserved (not normalized) during extraction | StreamSupervisor Donor Diff #4 | Medium — if the venue account stream is *meant* to reset/resume like the others, preserving the gap carries a latent stream-health bug forward. Flagged as Open Question 1 for the planner/owner. |
| A3 | CF-9 fail-open closes inside `validate_symbol` by gating on a loaded markets map | Pitfall 5 / Open Question 2 | Medium — the exact mechanism (block vs defer) is a design choice the planner must pin; D-11 only forbids a *parallel* drop. |

## Open Questions

1. **Does the `StreamSupervisor` extraction normalize `venue.py` to the full WR-03 surface?**
   - What we know: `venue.py` (account/positions streams) has `_mark_stream_down` + `_on_stream_down` but NO `_on_stream_healthy`/`_reset_reconnect_budget`/`_on_stream_up` (verified). The exec + provider arms have all three.
   - What's unclear: whether venue's reduced surface is intentional (spot account stream health is inferred from the exec/provider arms' compound `_all_venue_streams_healthy` gate) or a latent gap.
   - Recommendation: **Preserve exactly** (D-08) — the shared supervisor exposes `reset_budget`/`mark_up` as opt-in methods; venue's consume loops keep not calling them. Add a separate todo to evaluate whether venue's account stream should participate in WR-03 payload-gating. Do NOT normalize inside the behavior-preserving extraction.

2. **What is the exact CF-9 fail-open-before-load closure mechanism (D-11)?**
   - What we know: `okx.py:1020-1023` returns `True` when `client.markets` isn't a dict (fail-open); D-11 forbids a parallel drop mechanism.
   - What's unclear: whether to (a) return `False` until markets loads (fail-closed — a symbol can't enter membership until the map is present), or (b) defer the poll's validate step until markets is a dict, or (c) gate readiness at the connector level.
   - Recommendation: Pin this in the VENUE-07 plan as an explicit design step. Option (a) is the smallest change and keeps the single `validate_symbol` path (D-11-compliant), but must be checked against the startup ordering (markets load happens in `connect()`, which is deferred to `start()`) so it doesn't dark-out the initial universe. Route through a `checkpoint:human-verify` if the owner wants to confirm the fail-closed posture.

3. **`VenueLifecycle`: class or ordered helper?** (Explicit discretion.)
   - Recommendation: a small **class** with `start()`/`stop()` methods holding the bundle + provider refs, so the None-guards (D-10) and fixed start/stop order live in one testable unit that `assemble_venue` returns. A bare function makes the P6 call-site relocation (D-06) and unit testing harder.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | all | ✓ | 3.13 (`.python-version`) | — |
| Poetry `.venv` | tests | ✓ | in-project | — |
| `ccxt`/`ccxt.pro` | live plugin `build()` only (lazy) | ✓ | ^4.5.56 (pinned) | — (never on backtest path) |
| `pydantic`/`pydantic-settings` | `StreamSettings`/`OkxSettings` | ✓ | ^2.13 / ^2.14 | — |
| OKX `OKX_API_*` creds | live OKX plugin `build()` only | N/A for P5 tests | — | P5 tests use fakes against `LiveConnector` Protocol; no live creds needed (D-04 defers `OkxSettings()` into `build()`) |
| PostgreSQL | not touched by P5 | — | — | — |

**Missing dependencies with no fallback:** None — P5 is unit-testable with fakes; no live OKX connection or creds are needed for any P5 test (the inertness gate proves the OKX stack never loads on the tested backtest path, and the plugin/registry seams are tested with `FakeLiveConnector`).

## Validation Architecture

> Nyquist enabled (`workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`minversion="8.0"`, `testpaths=["tests"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Markers | `unit`/`integration`/`e2e`/`slow` (folder-derived) + `smoke`/`live` (hand-applied) |
| Quick run command | `poetry run pytest tests/unit/<domain>/test_x.py -x` |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree — see MEMORY: `make test` aborts in worktrees on missing `.env`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| VENUE-01 | Registry selects exec + data independently via `SystemSpec` | unit | `poetry run pytest tests/unit/venues/test_registry.py -x` | ❌ Wave 0 |
| VENUE-02 | `build_bundle` lazy-imports; register pulls no `ccxt.pro` | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ (extend `_FORBIDDEN` + add register-vs-build assertion) |
| VENUE-03 | `ConnectorProvider.get` memoizes `(venue,account_id)` → same instance | unit | `poetry run pytest tests/unit/connectors/test_provider.py -x` | ❌ Wave 0 |
| VENUE-04 | `resolve_precision`/`validate_symbol` on `AbstractExchange`; `_precision_to_scale` in money | unit | `poetry run pytest tests/unit/execution/test_precision.py tests/unit/core/test_money.py -x` | ❌ Wave 0 (money test exists; add precision cases) |
| VENUE-05 | `BaseLiveDataProvider` no-op defaults; no `hasattr` | unit | `poetry run pytest tests/unit/price_handler/test_live_provider.py -x` | ❌ Wave 0 |
| VENUE-06 | `VenueLifecycle` None-guards; `assemble_venue` returns bundle for okx/paper without a full `LiveTradingSystem` | unit | `poetry run pytest tests/unit/venues/test_assemble.py test_lifecycle.py -x` | ❌ Wave 0 |
| VENUE-07 | Shared `StreamSupervisor` preserves transient/fatal/unclassified/ceiling/WR-03 behavior for all 3 arms | unit | `poetry run pytest tests/unit/connectors/test_stream_supervisor.py -x` | ❌ Wave 0 (mine assertions from existing okx_provider/okx stream tests) |
| CF-9 | markets-map freshness closes fail-open-before-load | unit | `poetry run pytest tests/unit/execution/test_validate_symbol.py -x` | ❌ Wave 0 |
| **Gate** | Oracle byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ (`test_oracle_behavioral_identity`, `test_oracle_numeric_values`, `check_exact=True`, `46189.87730727451`/134) |
| **Gate** | Inertness register-vs-build | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ |

### Seam-in-isolation testing strategy (fakes against `runtime_checkable` Protocols)
- **`LiveConnector`** — the connectors conftest already ships `FakeLiveConnector` (base.py:31 note). Reuse it for `ConnectorProvider`/`assemble_venue`/plugin tests so no `ccxt.pro`/creds are needed.
- **`AbstractExchange`** — `runtime_checkable`; build a fake exposing `on_order`/`on_market_data`/`validate_symbol`/`resolve_precision` to test `VenueLifecycle`/`assemble_venue` without a real exchange.
- **`StreamSupervisor`** — inject a fake `connect_and_consume` coroutine that raises a scripted sequence (transient×N → fatal, or clean-return, or unclassified) and assert on: reconnect count vs ceiling, `on_down`/`on_up` calls, `halt_signal("connector-fatal")` invocation, and that `str(exc)` never appears in captured logs (scrub). Parameterize the test over each arm's `transient_exceptions` + `reconnect_on_clean_return` to prove behavior preservation for all three donors.
- **`ConnectorProvider`** — assert `get("okx","default",spec)` twice returns the *same* object (`is`), and `get` for a different `account_id` builds a new one; assert `close_all()` calls `disconnect()` on each.

### Sampling Rate
- **Per task commit:** the relevant `tests/unit/...` quick run for the seam touched (< 30s).
- **Per wave merge:** the full `tests/unit` + both standing gates (`test_okx_inertness.py`, `test_backtest_oracle.py`).
- **Phase gate:** `make test` green (or worktree `poetry run pytest tests`) + both gates green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/venues/test_registry.py` — VENUE-01 (dict registry select exec + data)
- [ ] `tests/unit/venues/test_assemble.py` + `test_lifecycle.py` — VENUE-06 (assemble okx/paper specs standalone; None-guards)
- [ ] `tests/unit/connectors/test_provider.py` — VENUE-03 (memo identity + close_all)
- [ ] `tests/unit/connectors/test_stream_supervisor.py` — VENUE-07 (behavior-preservation matrix over 3 arms)
- [ ] `tests/unit/price_handler/test_live_provider.py` — VENUE-05 (no-op defaults)
- [ ] `tests/unit/execution/test_precision.py` + `test_validate_symbol.py` — VENUE-04 / CF-9
- [ ] Extend `tests/integration/test_okx_inertness.py::_FORBIDDEN` with the new plugin concretion modules + add a plugin register-vs-build assertion
- [ ] Framework install: none needed (pytest present)

## Security Domain

> `security_enforcement` not explicitly false → enabled. This phase touches credentials + a reconnect/halt safety path, so security is load-bearing.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | yes | OKX auth triple via `OkxSettings` `SecretStr`; constructed only inside `build()` (D-04), never persisted (VENUE-03) |
| V6 Cryptography / Secrets | yes | `SecretStr` end-to-end (masked in repr/str/logs); `.get_secret_value()` only at the ccxt client edge; creds env-sourced, never written to a store |
| V7 Error/Logging | yes | Scrub discipline (T-05-27): log `type(exc).__name__` + fixed label, never `str(exc)`; halt reason fixed `'connector-fatal'` |
| V5 Input Validation | yes | `validate_symbol` filters proposed universe before apply (T-06-03-SPOOF); CF-9 closes the fail-open window |
| V4 Access Control | no | No new authz surface in P5 |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leaked via connector exception text | Information Disclosure | Scrub — never `str(exc)`; fixed halt reason (verified in all 3 donors) |
| Credential persisted to a store | Information Disclosure | VENUE-03: env-sourced, never persisted; `VenueStore` "never stores secrets" (STORE-02) |
| Spoofed/delisted symbol enters membership | Tampering | `validate_symbol → delta.removed` path (D-11) + CF-9 fail-open closure |
| Import-time cred construction on cred-less machine | Denial of Service (startup crash) | D-04 layer 3: `OkxSettings()` inside `build()` only |
| Reconnect ladder spins forever (no halt) | Denial of Service | D-20 retry ceiling → `connector-fatal` halt; WR-03 payload-only budget reset prevents subscribe-storm defeating the ceiling |

## Sources

### Primary (HIGH confidence — read directly this session)
- `itrader/trading_system/live_trading_system.py` :110-183 (resolvers), :541/625/1378/1751/1778/1817 (branches), :1438-1445 (resolver wiring)
- `itrader/price_handler/providers/okx_provider.py` :167-182, :453-579 (canonical StreamSupervisor donor)
- `itrader/execution_handler/exchanges/okx.py` :141-170, :699-841 (exec fork, TABS), :1007-1023 (`validate_symbol`)
- `itrader/portfolio_handler/account/venue.py` :167-176, :349-431 (account fork, 4-SPACE, missing mark_up/reset_budget)
- `itrader/connectors/base.py` (LiveConnector Protocol), `itrader/execution_handler/exchanges/base.py` (AbstractExchange, validate_symbol:68)
- `itrader/trading_system/compose.py` :114-189, `itrader/trading_system/backtest_trading_system.py` :375, `itrader/trading_system/system_spec.py`, `itrader/execution_handler/execution_handler.py` :66-217
- `itrader/config/stream.py`, `itrader/config/okx_settings.py`, `itrader/core/money.py` :38-93
- `itrader/universe/universe_handler.py` :1-110 (`_PrecisionResolver` Protocol:100), :253-374 (poll/validate/resolve path)
- `tests/integration/test_okx_inertness.py` (full), `tests/integration/test_backtest_oracle.py` (:57/128/149/173/200)
- Byte-level indentation check across all 10 target files (grep `^\t` vs `^    `)

### Secondary (MEDIUM confidence)
- `.planning/phases/05-venue-registry-bundle/05-CONTEXT.md` (locked decisions D-01..D-11), `.planning/REQUIREMENTS.md` (VENUE-01..07, milestone gates)

### Tertiary (LOW confidence)
- None — every claim is codebase-verified.

## Metadata

**Confidence breakdown:**
- Line-number verification: HIGH — read actual code at every canonical ref; two drifts precisely located.
- StreamSupervisor donor diff: HIGH — read all three bodies + constructors; divergences confirmed line-by-line.
- Standard stack: HIGH — zero-dep gate; all facilities already in-tree.
- CF-9 closure mechanism: MEDIUM — the two staleness holes are confirmed; the exact fix mechanism is a pinned design choice (Open Question 2).
- venue.py normalize-vs-preserve: MEDIUM — the gap is confirmed; the intended posture needs owner/planner confirmation (Open Question 1).

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (stable internal codebase; re-verify line numbers if `live_trading_system.py` / the three donors are edited before planning)
