# Phase 5: Venue Registry + Bundle - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 20 (11 NEW, 9 MODIFIED)
**Analogs found:** 20 / 20 (every new surface is a relocation/formalization of existing code)

> Indentation is BYTES-PER-FILE in this repo (see MEMORY + RESEARCH Drift 2). Every file below is tagged **[TABS]** or **[4-SPACE]**. Never transplant a body across styles — a mixed-indentation diff breaks the file under `filterwarnings=["error"]`/mypy.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `connectors/stream_supervisor.py` (NEW) | utility/service | event-driven (reconnect ladder) | `price_handler/providers/okx_provider.py:453-579` | exact (extract donor) | 4-SPACE |
| `connectors/provider.py` — `ConnectorProvider` (NEW) | provider/factory | request-response (memoized get) | `order_handler/storage/storage_factory.py` + LTS:541-573 | role-match | 4-SPACE |
| `connectors/provider.py` / `venues/bundle.py` — `ConnectorPlugin` Protocol (NEW) | Protocol | — | `connectors/base.py::LiveConnector` | exact (mirror) | 4-SPACE |
| `venues/registry.py` — `ExecutionVenueRegistry`/`DataProviderRegistry` (NEW) | registry | CRUD (register/get on a dict) | `order_handler/storage/storage_factory.py` | role-match | discretion |
| `venues/bundle.py` — `VenuePlugin`/`DataProviderPlugin` Protocols (NEW) | Protocol | — | `execution_handler/exchanges/base.py::AbstractExchange`, `connectors/base.py::LiveConnector` | exact (mirror) | 4-SPACE |
| `venues/bundle.py` — `VenueBundle` (NEW) | value object | — | `order_handler/brackets/bracket_book.py:35` (`@dataclass(frozen=True, slots=True, kw_only=True)`) | exact | 4-SPACE |
| `venues/lifecycle.py` — `VenueLifecycle` (NEW) | orchestrator | event-driven (start/stop) | LTS lifecycle guards :1378/:1751/:1778/:1817 | role-match | discretion |
| `venues/assemble.py` — `assemble_venue(ctx, spec, connectors)` (NEW) | composition seam | request-response | `trading_system/compose.py::compose_engine` | role-match | discretion (TABS if beside compose) |
| `venues/okx_plugin.py` — `OkxVenuePlugin`/`OkxDataPlugin` (NEW) | plugin | — | LTS:541-573 (`if exchange=='okx'` block) | exact (formalize) | 4-SPACE |
| `venues/paper_plugin.py` — `PaperVenuePlugin` (NEW) | plugin | — | LTS:625-643 (`elif=='paper'` reuse of `'simulated'`) | exact (formalize) | 4-SPACE |
| `price_handler/providers/base.py` — `LiveDataProvider`/`BaseLiveDataProvider` (NEW) | Protocol + base | — | `connectors/base.py::LiveConnector` | exact (mirror) | 4-SPACE |
| `execution_handler/exchanges/base.py` (MOD) | Protocol | — | self (`validate_symbol:68`) | exact | **TABS** |
| `execution_handler/exchanges/okx.py` (MOD) | exchange concretion | — | self (`validate_symbol:1007`, supervisor:699-841) | exact | **TABS** |
| `execution_handler/exchanges/simulated.py` (MOD) | exchange concretion | — | `AbstractExchange` default | role-match | **TABS** |
| `core/money.py` (MOD) — `_precision_to_scale` lands | utility | transform | self (`to_money`/`quantize`, `__all__:38`) | exact | 4-SPACE |
| `universe/universe_handler.py:100` (MOD) — rewire resolver | handler | request-response | self (`_PrecisionResolver` Protocol:100) | exact | 4-SPACE |
| `trading_system/system_spec.py:80` (MOD) — add selectors | config/dataclass | — | self (`SystemSpec`, append-LAST convention) | exact | **TABS** |
| `trading_system/live_trading_system.py` (MOD) — delete branches, delegate | composition root | — | self (:541/:625 branches) | exact | 4-SPACE |
| `portfolio_handler/account/venue.py:349` (MOD) — supervisor delegation | account concretion | event-driven | self (`_run_stream_supervisor:349-431`) | exact | **4-SPACE** (NOT tabs — Drift 2) |

## Pattern Assignments

### `connectors/stream_supervisor.py` — shared `StreamSupervisor` (NEW, 4-SPACE)

**Analog (canonical donor):** `price_handler/providers/okx_provider.py:453-579`. Extract this behavior verbatim into a composition class; the two forks (`okx.py:699-841` TABS, `venue.py:349-431` 4-SPACE) delete their body and add a one-line delegation in their OWN indentation. **The donors are NOT identical — parameterize** (`transient_exceptions`, `reconnect_on_clean_return`); see RESEARCH §StreamSupervisor Donor Diff.

**Core reconnect ladder + taxonomy** (`okx_provider.py:467-517`):
```python
import ccxt  # lazy: ccxt already transitively imported on the live path only
transient: tuple[type[BaseException], ...] = (
    ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection,
    aiohttp.ClientError, ConnectionError, asyncio.TimeoutError)   # provider = 6 types; okx/venue = first 3 only
fatal: tuple[type[BaseException], ...] = (ccxt.AuthenticationError, ccxt.PermissionDenied)
while True:
    try:
        await connect_and_consume(stream_name)
        drop_label = "socket closed by server"   # provider: clean-return -> reconnect; okx/venue: `return`
    except asyncio.CancelledError:
        raise                                     # cooperative teardown — never swallow
    except fatal as exc:
        self._escalate_connector_halt(stream_name, exc, "fatal auth/permission error"); return
    except transient as exc:
        drop_label = type(exc).__name__
    except Exception as exc:                      # UNCLASSIFIED -> fail-safe HALT + return (never fall to ladder)
        self._escalate_connector_halt(stream_name, exc, "unexpected error"); return
    attempt = self._reconnect_attempts.get(stream_name, 0) + 1
    self._reconnect_attempts[stream_name] = attempt
    if attempt > self._reconnect_ceiling:
        self._escalate_connector_halt(stream_name, RuntimeError(drop_label), "reconnect retry ceiling exhausted"); return
    await asyncio.sleep(self._reconnect_debounce_s)
    if attempt > 1:
        self._mark_stream_down(stream_name)
    backoff = min(self._reconnect_backoff_base_s * (2 ** (attempt - 1)), self._reconnect_backoff_cap_s)
    self.logger.warning("... %s stream dropped (%s) — reconnecting (attempt %d/%d, backoff %.1fs)",
        stream_name, drop_label, attempt, self._reconnect_ceiling, backoff)   # SCRUB: drop_label only, never str(exc)
    await asyncio.sleep(backoff)
```

**Escalate/halt scrub** (`okx_provider.py:519-532`) — log `type(exc).__name__` + fixed cause, call `halt_signal("connector-fatal")` (never `str(exc)`; T-05-27/V7):
```python
self.logger.error("... %s stream unrecoverable (%s: %s) — halting engine",
    stream_name, type(exc).__name__, cause)
if self._halt_signal is not None:
    self._halt_signal("connector-fatal")
```

**mark_down / mark_up / reset_budget** (`okx_provider.py:544-579`) — WR-03: only a POST-SNAPSHOT delivered payload resets `_reconnect_attempts`; a subscribe does NOT (`_on_stream_healthy` resumes but does not reset). Expose `reset_budget(name)`/`mark_up(name)` as **consume-loop-driven** methods. **PRESERVE venue.py's reduced surface** (it has no `mark_up`/`reset_budget`) — do not normalize inside the extraction (RESEARCH Open Q1, A2).

**Constructor signature (D-08):** `StreamSupervisor(config, halt_signal, on_down, on_up, logger)` with state `_reconnect_attempts`, `_streams_down`, tuning read from `config/stream.py::StreamSettings`. `_disconnect_ts_ms` (D-12 catch-up floor) stays in the okx.py arm fed via `on_down` — NOT supervisor state.

---

### `connectors/provider.py` — `ConnectorProvider` (NEW, 4-SPACE)

**Analogs:** `order_handler/storage/storage_factory.py` (env-keyed dispatch + lazy-import-inside-arm discipline) for the shape; LTS:541-573 for the "build ONCE, inject 3 ways" behavior being formalized.

**Memo shape (D-03/RESEARCH Pattern 2):**
```python
class ConnectorProvider:
    def __init__(self, plugins: dict[str, "ConnectorPlugin"]):
        self._plugins = plugins
        self._memo: dict[tuple[str, str], "LiveConnector"] = {}
    def get(self, venue: str, account_id: str, spec) -> "LiveConnector":
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = self._plugins[venue].build(spec)   # build() keeps lazy import + OkxSettings() inside
        return self._memo[key]
    def close_all(self) -> None:
        for c in self._memo.values(): c.disconnect()
```

**Lazy-import discipline to copy** (`storage_factory.py:53-63`) — imports live INSIDE the arm, keeping the backtest import graph clean (GATE-01). `ConnectorPlugin.build()` does the same for `ccxt.pro`/`OkxConnector(OkxSettings())` (D-04 triple-deferral).

---

### `venues/bundle.py` — `VenueBundle` + Protocols (NEW, 4-SPACE)

**`VenueBundle` analog:** `order_handler/brackets/bracket_book.py:35` — `@dataclass(frozen=True, slots=True, kw_only=True)`. Shape (D-02): mandatory `exchange: AbstractExchange` + `account_factory: Callable[[PortfolioRef, AccountConfig], Account]`; Optional `connector: LiveConnector | None = None`, `lifecycle: VenueLifecycle | None = None`. Data provider is NOT in the bundle.

**`VenuePlugin`/`ConnectorPlugin`/`DataProviderPlugin` Protocol analog:** `connectors/base.py::LiveConnector` (lines 43-94) — `@runtime_checkable class X(Protocol)`, method bodies `...`, rich docstrings, no ABC. Mirror exactly:
```python
@runtime_checkable
class LiveConnector(Protocol):
    def call(self, coro: Awaitable[_T]) -> _T: ...
    def spawn(self, coro: Awaitable[Any]) -> Any: ...
    @property
    def client(self) -> Any: ...
    def connect(self) -> Any: ...
    def disconnect(self) -> Any: ...
```
**CF-3:** add connector-contract docstrings ON `connectors/base.py` (this file already carries the model — extend it).

---

### `venues/okx_plugin.py` / `paper_plugin.py` (NEW, 4-SPACE)

**Okx plugin analog:** LTS:541-573 — the block to formalize (`OkxConnector(OkxSettings())` built once, injected into exchange/provider/account). **D-04: keep `import ccxt.pro`/`OkxExchange`/`OkxSettings()` INSIDE `build_bundle`/`build`/`build_provider`, never module-top** (RESEARCH Pattern 1). This silently reddens `test_okx_inertness.py` if hoisted.

**Paper plugin analog:** LTS:625-643 — reuses the compose-built `'simulated'` exchange AS-IS, `connector=None`, `SimulatedAccount`. `'simulated'` is NOT a registered venue (D-05). Lazy `import ReplayDataProvider` inside the arm (mirrors the OKX lazy imports).

---

### `execution_handler/exchanges/base.py` (MOD, **TABS**) + `okx.py`/`simulated.py` (MOD, **TABS**)

**Analog:** the existing `validate_symbol` on the same Protocol (base.py:68). Add `resolve_precision(symbol)` beside it, same one-line docstring style (TABS):
```python
	def validate_symbol(self, symbol: str) -> bool:
		"""Check if symbol is valid for trading on this exchange."""
		...
```
**okx.py `resolve_precision` impl analog:** relocate `_OkxPrecisionResolver.resolve` body (LTS:154-183) onto `OkxExchange` — it already reads `self._connector.client.markets[key]['precision']` and calls `_precision_to_scale`/`_to_symbol`. **simulated.py:** `resolve_precision` returns a sensible default when it holds no markets map (D-09).

**CF-9** — `okx.py::validate_symbol` (1007-1023, TABS) currently fail-opens (`return True` when `markets` isn't a dict). Close that window WITHOUT a second parallel drop (D-11); keep the single `validate_symbol -> delta.removed` path.

---

### `core/money.py` (MOD, 4-SPACE) — `_precision_to_scale` lands here

**Analog / source:** LTS:110-131 (verbatim function). Relocate as a shared util; add to `__all__` (currently `["ONE", "to_money", "quantize"]` at line 38). Keeps the D-04 string-entry discipline (`Decimal(str(value))`, never `Decimal(float)`) this module already owns.

---

### `universe/universe_handler.py:100` (MOD, 4-SPACE) — REWIRE (Drift 1)

**Source:** the `_PrecisionResolver` Protocol (`resolve(symbol) -> Instrument | None`) at :100, its `_precision_resolver` field (:222), `set_precision_resolver` (:253), and the `_resolve_added_instruments` call site. Note the sibling `_SymbolValidator` Protocol at :94 (`validate_symbol` bound) is the exact shape to reuse. Replace `_PrecisionResolver` with an `AbstractExchange`-bound (or narrow `_SupportsResolvePrecision` Protocol exposing `resolve_precision`), rename `.resolve()` -> `.resolve_precision()`, rewire LTS:1438-1445 (`set_precision_resolver(exchange)`). Missing this leaves a dangling `.resolve()` after the resolvers are deleted.

---

### `trading_system/system_spec.py:80` (MOD, **TABS**) — add selectors

**Analog:** the `SystemSpec` frozen dataclass itself + its documented "keep fields LAST so by-name/positional call-sites stay unbroken" convention (see the `results_store` field docstring at :93-98). Append `execution_venue` + `data_provider` (+ a single-default `account_id` seam) LAST, typed simply, defaulted so oracle/e2e call-sites stay byte-exact.

---

### `trading_system/live_trading_system.py` (MOD, 4-SPACE) — delete branches, delegate

**Source:** the `if self.exchange == 'okx'` (:541) and `elif == 'paper'` (:625) blocks + lifecycle guards (:1378/:1751/:1778/:1817). Replace with a single delegation: `bundle, lifecycle = assemble_venue(ctx, spec, connectors)` (D-06). The assembly LOGIC is authored once in `venues/assemble.py`; P6 only relocates the call site into `build_live_system`.

**`assemble_venue` seam analog:** `compose.py::compose_engine(ctx, spec)` (:114) — a `(ctx, spec)` composition function returning a wired object graph. `assemble_venue(ctx, spec, connectors) -> (VenueBundle, VenueLifecycle)` mirrors this seam and is independently unit-testable with fakes.

---

### `portfolio_handler/account/venue.py:349` (MOD, **4-SPACE — NOT tabs**)

**Source:** its `_run_stream_supervisor` fork (:349-431). Delete the body, add a 4-space delegation to the shared `StreamSupervisor`. **Drift 2:** CONTEXT.md D-08 mislabels this file TABS — byte check proves 4-SPACE (604 space lines, 0 tab). Edit in 4-space. This arm is the reduced-surface donor (3-type transient tuple, clean-return=`return`, no `mark_up`/`reset_budget`).

## Shared Patterns

### runtime_checkable Protocol = swap-a-fake seam
**Source:** `connectors/base.py:43` (`LiveConnector`), `execution_handler/exchanges/base.py:7` (`AbstractExchange`).
**Apply to:** every NEW Protocol (`VenuePlugin`, `ConnectorPlugin`, `DataProviderPlugin`, `LiveDataProvider`). `@runtime_checkable class X(Protocol)`, `...` bodies, no ABC. Tested against `FakeLiveConnector` (connectors conftest) — no `ccxt.pro`/creds needed.

### Lazy-import-inside-the-arm (inertness / GATE-01)
**Source:** `order_handler/storage/storage_factory.py:53-63`, LTS:542-546, `okx_provider.py:467`.
**Apply to:** every plugin `build*()` + `ConnectorPlugin.build()`. Concretion `import` AND `OkxSettings()` stay inside the method (D-04 triple-deferral). Extend `test_okx_inertness.py::_FORBIDDEN` (:38-82) with the new plugin concretion modules.

### Scrub discipline (T-05-27 / V7)
**Source:** `okx_provider.py:511-532`.
**Apply to:** `StreamSupervisor` + all delegating arms. Log `type(exc).__name__` / a fixed label, never `str(exc)`; halt reason is the fixed `'connector-fatal'`.

### Frozen value object
**Source:** `order_handler/brackets/bracket_book.py:35` — `@dataclass(frozen=True, slots=True, kw_only=True)`.
**Apply to:** `VenueBundle`.

### Bytes-per-file indentation
**Apply to:** every edit. TABS: `execution_handler/exchanges/{base,okx,simulated}.py`, `system_spec.py`, `compose.py`. 4-SPACE: `connectors/*`, `core/money.py`, `universe_handler.py`, `price_handler/providers/*`, `portfolio_handler/account/venue.py`, `live_trading_system.py`.

## No Analog Found

None — every new surface is a relocation/formalization of existing code. `VenueLifecycle` is the loosest (no single prior orchestrator), but its behavior is the existing lifecycle guards (LTS:1378/1751/1778/1817) gathered into one None-guarded class; RESEARCH Open Q3 recommends a small class with `start()`/`stop()`.

## Metadata

**Analog search scope:** `itrader/connectors/`, `itrader/execution_handler/exchanges/`, `itrader/order_handler/storage/`, `itrader/trading_system/`, `itrader/price_handler/providers/`, `itrader/portfolio_handler/account/`, `itrader/universe/`, `itrader/core/`.
**Files scanned:** ~14 read directly (all HIGH-confidence, line-verified against HEAD).
**Pattern extraction date:** 2026-07-10
</content>
</invoke>
