# Phase 2: OKX Connector - Pattern Map

**Mapped:** 2026-07-01
**Files analyzed:** 10 (5 new source, 3 modified source, 1 config/build, 1 test tree)
**Analogs found:** 9 / 10 (1 no-analog: native `/business` WS candle socket)

> **Read this with `02-CONTEXT.md` + `02-RESEARCH.md` open.** D-01..D-10 are the locked
> architecture; the RESEARCH D-02 correction (WS demo via `wspap` host, NOT the
> `x-simulated-trading` header; fill stream is `watch_my_trades`, NOT `watch_fills`) governs
> the order/data arms. This file says *which existing code each new file copies from* — the
> planner references these analogs + line ranges directly in each plan's action section.

## File Classification

| New/Modified File | New/Mod | Role | Data Flow | Closest Analog | Match | Indent |
|-------------------|---------|------|-----------|----------------|-------|--------|
| `itrader/connectors/base.py` | MOD | protocol/seam | request-response + streaming | *(self — reshape existing Protocol)* | exact | **4-space** |
| `itrader/connectors/okx.py` | NEW | connector/transport | event-driven (async loop on daemon thread) | `connectors/base.py` (Protocol shape) + RESEARCH Pattern 2 sketch | role-match | **4-space** |
| `itrader/connectors/__init__.py` | MOD | barrel | — | *(self — existing barrel)* | exact | **4-space** |
| `itrader/execution_handler/exchanges/okx.py` | NEW | exchange (order arm) | request-response (create/cancel) + streaming (fills→queue) | `execution_handler/exchanges/simulated.py` + `base.py` (`AbstractExchange`) | exact (same seam) | **TABS** |
| `itrader/price_handler/providers/okx_provider.py` | NEW | data provider (data arm) | streaming (native candle) + request-response (REST backfill) | `price_handler/providers/base.py` (`PriceProvider`) + `binance_stream.py` (WS loop) + `ccxt_provider.py` (`fetch_ohlcv`) | role-match | **4-space** |
| `itrader/config/okx_settings.py` | NEW | config | — | `config/settings.py` + `config/sql.py` (`SecretStr`) | exact | **4-space** |
| `itrader/portfolio_handler/account/venue.py` | MOD | account leaf (account arm) | pub-sub (cache; body Phase 5) | *(self — existing stub leaf)* | exact | **4-space** |
| `itrader/trading_system/live_trading_system.py` | MOD | composition root | wiring/DI | *(self — existing `__init__` wiring block)* | exact | **4-space** |
| `pyproject.toml` | MOD | build/test config | — | existing `[tool.pytest.ini_options]` | exact | (toml) |
| `tests/unit/connectors/*`, `tests/unit/execution/test_okx_exchange.py`, `tests/unit/config/test_okx_settings.py` | NEW | test | mocked async I/O | RESEARCH §Validation Architecture (test map) | role-match | (per test-file) |

**Indentation is load-bearing (CLAUDE.md hazard).** The `execution_handler/exchanges/` tree is
**tabs** (`base.py`, `simulated.py`, `execution_handler.py` all tab-indented — verified). Every
other target lives in a **4-space** tree (`connectors/`, `config/`, `portfolio_handler/account/`,
`trading_system/`, and the new-seam `price_handler/providers/base.py`). A mixed-indent diff in the
tab tree breaks the file — `OkxExchange` MUST be tabs; everything else MUST be 4-space.

---

## Pattern Assignments

### `itrader/connectors/base.py` (protocol/seam — MODIFY, 4-space)

**Analog:** self (reshape the existing `LiveConnector` Protocol per D-02) + `execution_handler/exchanges/base.py::AbstractExchange` (the sibling `runtime_checkable` Protocol seam).

**Current shape (lines 25-59):** a `@runtime_checkable class LiveConnector(Protocol)` with placeholder slots `watch_data` / `submit_order` / `cancel_order` / `connect` / `disconnect`. The module docstring (lines 1-23) explicitly says the real signatures are "shaped against OKX reality in Phase 2 (CONN-*)" — **this phase is that reshape.**

**Reshape target (D-02):** shrink from a "two-arm marker" to a **session/transport contract**. Per RESEARCH §Async Containment, the contract the three arms type against is the scheduling seam, not order/candle ops. Keep the `@runtime_checkable Protocol` form (swap-a-fake seam, D-04/D-08). New slots to name:
```python
@runtime_checkable
class LiveConnector(Protocol):
    def call(self, coro: "Awaitable[T]") -> T: ...        # RPC: run_coroutine_threadsafe(...).result()
    def spawn(self, coro: "Awaitable[Any]") -> Any: ...    # long-running stream task (watch_*/native candle)
    @property
    def client(self) -> Any: ...                           # the shared ccxt.pro client (arms call through it)
    @property
    def sandbox(self) -> bool: ...                         # native data socket keys its host off this
    def connect(self) -> Any: ...                          # start loop-on-daemon-thread + build client
    def disconnect(self) -> Any: ...                        # cancel stream tasks + stop loop
```
Remove `watch_data`/`submit_order`/`cancel_order` — those become **arm** concerns (D-02: the connector "imports/constructs no domain events" and "knows nothing about orders-vs-candles-vs-balances"). **Preserve the docstring's decision-tag style** (D-02/D-04 anchors).

**Copy the Protocol idiom from `AbstractExchange`** (`exchanges/base.py:1-16`): `from typing import ... Protocol, runtime_checkable`; `@runtime_checkable` decorator; method bodies `...`; class docstring naming the swap-a-fake seam.

---

### `itrader/connectors/okx.py` (connector/transport — NEW, 4-space)

**Analog:** `connectors/base.py` (the Protocol it satisfies) + **RESEARCH §Architecture Pattern 2** (the loop-on-daemon-thread sketch, lines 195-223 of RESEARCH) + `SimulatedExchange.connect/disconnect` (`exchanges/simulated.py:380-432`) for the lifecycle-result shape and logger bind.

**Logger + lifecycle pattern** (from `simulated.py:67`, `380-432`):
```python
self.logger = get_itrader_logger().bind(component="OkxConnector")
```
`connect()`/`disconnect()` return-shape can stay simple (D-02 lifecycle), but mirror the try/except + status logging discipline of `SimulatedExchange.connect` (lines 380-417): `self.logger.info('Connected ...')` on success, `self.logger.error(..., exc_info=True)`-style on failure.

**Async containment (the genuinely new code — RESEARCH Pattern 2, lines 199-222):**
```python
def connect(self):
    self._loop = asyncio.new_event_loop()
    self._thread = threading.Thread(target=self._run_loop, daemon=True, name="okx-connector")
    self._thread.start()
    fut = asyncio.run_coroutine_threadsafe(self._build_client(), self._loop)  # build ccxt.pro ON the loop
    fut.result(timeout=30)
def _run_loop(self):
    asyncio.set_event_loop(self._loop); self._loop.run_forever()
def call(self, coro):  # RPC
    return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=30)
def spawn(self, coro):  # infinite stream — never .result()
    return asyncio.run_coroutine_threadsafe(self._spawn(coro), self._loop).result()
```
**Critical (RESEARCH Pitfall 3):** build the `ccxt.pro.okx` client *inside* the loop thread — ccxt.pro binds sockets to the creating loop. Track stream tasks in `self._stream_tasks: set[asyncio.Task]` and cancel-all in `disconnect()` (nautilus-mirrored, RESEARCH lines 343).

**ccxt client construction + sandbox (RESEARCH §Demo-Key, lines 324-335):**
```python
client = ccxtpro.okx({
    "apiKey": settings.api_key.get_secret_value(),
    "secret": settings.api_secret.get_secret_value(),
    "password": settings.api_passphrase.get_secret_value(),  # passphrase → "password" field
    "enableRateLimit": True,                                   # RES-01: leave ON
})
if self.sandbox:
    client.set_sandbox_mode(True)   # REST header + ccxt WS host swap to wspap
```

**D-02 constraint:** this file imports **no** `events_handler.events` — grep-guard it. It owns auth, the one client, the loop/thread, `sandbox: bool`, rate-limit budget, lifecycle. Nothing domain-shaped.

---

### `itrader/connectors/__init__.py` (barrel — MODIFY, 4-space)

**Analog:** self (current 12-line barrel, exports `LiveConnector` only).

**Change:** add `OkxConnector` to the re-export + `__all__`, matching the existing form:
```python
from .base import LiveConnector
from .okx import OkxConnector
__all__ = ["LiveConnector", "OkxConnector"]
```
The docstring (lines 1-8) already anticipates this: *"Phase 2 adds `connectors/okx.py` (`OkxConnector`)"* — update it to past tense.

---

### `itrader/execution_handler/exchanges/okx.py` (exchange / order arm — NEW, **TABS**)

**Analog:** `execution_handler/exchanges/simulated.py` (the live sibling — same `AbstractExchange` seam) + `exchanges/base.py::AbstractExchange` (the contract to implement).

**This is the strongest analog in the phase — `OkxExchange` is a sibling class of `SimulatedExchange`.** `ExecutionHandler.on_order` already routes to it by `event.exchange` key (`execution_handler.py:102-113`) — no routing change needed, just register `'okx'` in `init_exchanges` (see composition-root note).

**Imports/constructor pattern** (`simulated.py:1-24, 49-71`) — copy tab-indented, and add the injected session:
```python
def __init__(self, global_queue: "Queue[Any]", connector: "LiveConnector") -> None:
    self.logger = get_itrader_logger().bind(component="OkxExchange")
    self.global_queue = global_queue
    self._connector = connector   # D-04: injected session Protocol, NOT the concretion
```
Note `SimulatedExchange` takes `global_queue` first (`simulated.py:49`) — keep that positional convention. Import `LiveConnector` from the top-level `itrader.connectors` (dependency-safe, D-04 — same way `AbstractExchange` is imported).

**`AbstractExchange` methods to implement** (`base.py:19-69`): `on_order`, `on_market_data`, `connect`, `disconnect`, `is_connected`, `health_check`, `configure`, `validate_order`, `validate_symbol`. Per CONTEXT §Reusable Assets: **`on_market_data` becomes a no-op for live** (the venue matches, not us).

**Order I/O (D-06, RESEARCH order-arm table lines 299-310):** `create_order`/`cancel_order` route through `self._connector.call(...)` (RPC); `watch_orders`/`watch_my_trades` (the fill stream — **NOT `watch_fills`**) are spawned via `self._connector.spawn(...)`.

**Fill emission (D-07 — copy the `_emit_fill` shape from `simulated.py:247-298`):** the exchange builds the `FillEvent` and puts it on the queue. Reuse `FillEvent.new_fill` exactly as `simulated.py:291-295` does:
```python
# RESEARCH §Order arm fill stream (lines 434-444) — the connector-loop-thread put
async def _stream_fills(self):
    while True:
        trades = await self._connector.client.watch_my_trades()
        for t in trades:
            fill = FillEvent.new_fill('EXECUTED', order,
                price=to_money(str(t["price"])), quantity=to_money(str(t["amount"])),
                commission=to_money(str(t["fee"]["cost"])), time=_ms_to_dt(t["timestamp"]))
            self.global_queue.put(fill)   # D-07 exchange emits; D-19 MPSC-safe from the async thread
```
`FillEvent.new_fill` signature (`fill.py:79-83`): `(status: str, order: OrderEvent, *, price, quantity, commission, time=None)` — it accepts `Decimal | float` and normalizes via `to_money` internally (`fill.py:138-140`), but per CONN-05 still pass `to_money(str(x))` at *this* edge so no raw ccxt float ever touches the constructor.

**Decimal edge (CONN-05, RESEARCH Pattern 3 lines 227-236):** inbound `to_money(str(raw))`; outbound `client.amount_to_precision(sym, float(qty))` / `price_to_precision` (returns venue-rounded STRING) after `load_markets()`. NEVER `Decimal(float)` (RESEARCH Pitfall 5).

**Venue time (RESEARCH lines 345):** stamp `FillEvent.time` from the venue fill timestamp, never `datetime.now`.

---

### `itrader/price_handler/providers/okx_provider.py` (data provider / data arm — NEW, 4-space)

**Analog:** `price_handler/providers/base.py::PriceProvider` (the 4-space seam, `fetch_ohlcv`/`get_symbols` abstract methods) + `binance_stream.py` (the WS message-loop + `global_queue.put` + logger idiom) + `ccxt_provider.py::download_data` (the `fetch_ohlcv` pagination for REST backfill).

> **Indentation note:** the *sibling* quarantined adapters are mixed — `ccxt_provider.py` is TABS, `binance_stream.py` is 4-space, and the new-seam `providers/base.py` is 4-space. Match the **seam (`base.py`, 4-space)** and the Phase-3 `LiveBarFeed` consumer (`feed/` is 4-space per CLAUDE.md). **New file → 4-space.** Do NOT copy `ccxt_provider.py`'s tabs.

**Logger + queue idiom** (`binance_stream.py:11-12, 25-36`):
```python
from itrader.logger import get_itrader_logger
logger = get_itrader_logger().bind(component="OkxDataProvider")
# stream loop puts closed bars downstream (Phase-3 LiveBarFeed consumes)
```

**Native closed-bar loop (the ONE no-analog piece — RESEARCH §Code Examples lines 402-428):**
```python
async def _stream_candles(self, symbol_okx, channel):   # channel e.g. "candle1D"
    host = "wspap.okx.com" if self._sandbox else "ws.okx.com"     # D-02 correction: host, NOT header
    url = f"wss://{host}:8443/ws/v5/business"                      # candles live on /business
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(url, autoping=False) as ws:
            await ws.send_json({"op": "subscribe",
                                "args": [{"channel": channel, "instId": symbol_okx}]})
            async for msg in ws:
                for row in json.loads(msg.data).get("data", []):
                    if row[8] != "1":   # CONN-01: gate on confirm==1 (index 8) — drop forming bars
                        continue
                    closed = {"ts": int(row[0]), "open": to_money(row[1]), ...}  # to_money(str) edge
                    self._hand_closed_bar_to_feed(closed)
```
This socket is spawned on the connector loop via `self._connector.spawn(...)` (Claude's-Discretion resolved: separate socket, connector loop — RESEARCH Open Q2). The `sandbox` bool is read off the injected `LiveConnector` (D-04).

**REST backfill** — reuse the ccxt `fetch_ohlcv` + 1000-row pagination loop from `ccxt_provider.py:110-118` (adapt to the shared `self._connector.client`, and cross every numeric field with `to_money(str(...))`, replacing `ccxt_provider`'s `data.astype(float)`).

**Shape the new data-provider seam (Claude's Discretion, D-03):** `OkxDataProvider` implements a data-provider contract in `price_handler/providers/`. `providers/base.py::PriceProvider` is offline-ingestion-only (never on the run path) — the *live* streaming seam is new and Phase 3 co-shapes it with `LiveBarFeed`. Define the minimal method the provider exposes to the feed at plan time.

---

### `itrader/config/okx_settings.py` (config — NEW, 4-space)

**Analog:** `config/settings.py::Settings(BaseSettings)` (the `SettingsConfigDict(env_prefix=..., extra="ignore")` idiom) + `config/sql.py::SqlSettings` (the `SecretStr` + `get_secret_value()` pattern, lines 33-34, 59-89, 165-176).

**Exact target (RESEARCH §OkxSettings lines 447-459, D-10):**
```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class OkxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")   # NO prefix (D-10)
    api_key: SecretStr        # OKX_API_KEY
    api_secret: SecretStr     # OKX_API_SECRET
    api_passphrase: SecretStr # OKX_API_PASSPHRASE  (required — OKX auth triple)
    sandbox: bool = True      # (optional) single-bool demo routing default
```
**Copy the `env_prefix`/`extra` idiom from `settings.py:20`** (`SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")`) but **override to `env_prefix=""`** (D-10 revises CONN-06 — plain `OKX_API_*`, verified present in `.env.example:34-36`). **Copy `SecretStr` + `.get_secret_value()` from `sql.py:88-89, 165-176`** — keeps secrets out of logs/reprs/fixtures (CONN-06). No YAML layer needed (unlike domain configs).

**Barrel:** `config/__init__.py` re-exports `Settings` (line 22) and lists it in `__all__` (line 70) — mirror that for `OkxSettings` if it should be package-public (planner's call; it may stay import-by-path since only the connector reads it).

---

### `itrader/portfolio_handler/account/venue.py` (account leaf / account arm — MODIFY, 4-space)

**Analog:** self (existing interface-only stub leaf) + `account/base.py::Account` (the ABC contract).

**Scope this phase is thin (CONTEXT §Deferred + D-03):** the `VenueAccount` *body* (balance/margin/position caching, reconciliation) is **deferred to Phase 5 (RECON-01)** — the current file (lines 27-63) is `NotImplementedError` stubs and the docstring (lines 11-17) says the connector→VenueAccount data flow is "explicitly Phase 2 (CONN-*) / Phase 5 (RECON-01)". For Phase 2 the only change is the **wiring seam**: a constructor accepting the injected `LiveConnector` session (D-04), so the composition root can wire it. The abstract methods stay `NotImplementedError` (do NOT implement caching now — that's Phase 5).

**Preserve** the existing decision-tag docstring style and the `raise NotImplementedError("... deferred to Phase 5 (RECON-01) ...")` message form (lines 38-63) for any method left unimplemented.

---

### `itrader/trading_system/live_trading_system.py` (composition root — MODIFY, 4-space)

**Analog:** self — the existing `__init__` component-wiring block (lines 100-184), which already constructs `ExecutionHandler`, `PortfolioHandler`, `StrategiesHandler`, `OrderHandler` around one `self.global_queue`.

**This is the ONLY place the concrete `OkxConnector` is constructed (D-04).** Follow the existing wiring order + comment discipline (e.g. the "Execution handler constructed BEFORE the order handler" rationale, lines 152-155). Add:
```python
from itrader.connectors import OkxConnector          # concretion — composition root ONLY
from itrader.config.okx_settings import OkxSettings

self._okx_connector = OkxConnector(OkxSettings())    # constructed once
self._okx_connector.connect()                        # start loop-on-daemon-thread
# inject the SESSION (typed LiveConnector) into the three arms:
#   OkxExchange(self.global_queue, self._okx_connector)      → register 'okx' in ExecutionHandler
#   OkxDataProvider(self._okx_connector, ...)
#   VenueAccount(self._okx_connector)
```
**Exchange registration:** `ExecutionHandler.init_exchanges` (`execution_handler.py:132`) currently builds the `'simulated'` exchange; the `on_order` router already dispatches by `event.exchange` (lines 105-110). Add an `'okx'` entry (planner decides whether via a new `init_exchanges` branch or an injected-exchange constructor arg on `ExecutionHandler`). **Lazy-import** the OKX stack inside the live path only, mirroring the existing lazy SQL import (`live_trading_system.py:141-144`) so the backtest path stays credential-free / async-free (GATE-01 inertness).

**Cross-domain-import rule:** only this file imports the `OkxConnector` concretion. The three arms import the `LiveConnector` *Protocol* from `itrader.connectors` (D-04) — never `connectors.okx`.

---

### `pyproject.toml` (build/test — MODIFY, toml)

**Analog:** existing `[tool.pytest.ini_options]` block (RESEARCH §Validation lines 530-543).

- `poetry add --group dev "pytest-asyncio@^1.4.0"` (D-08; the slopcheck `pip install` did NOT update the lockfile — must go through poetry so `poetry.lock` is authoritative, RESEARCH line 117).
- Add to `[tool.pytest.ini_options]`: `asyncio_mode = "auto"` and `asyncio_default_fixture_loop_scope = "function"` (silences the config-warning that `--strict-config` would turn into an error).
- **Do NOT touch `filterwarnings` or `markers`** — the plugin registers its own `asyncio` marker (exempt from `--strict-markers`), and `PytestDeprecationWarning` is already ignored (`filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`, RESEARCH line 532). The live strict risks are `ResourceWarning`/`RuntimeWarning` (unclosed session / un-awaited coroutine) — handled in tests, not config.

---

### Test files (NEW — RESEARCH §Phase Requirements→Test Map, lines 546-556)

**Analog:** the offline-mocked-ccxt strategy (D-08) + existing `tests/unit/<domain>/` layout.

| File | Covers | Pattern |
|------|--------|---------|
| `tests/unit/connectors/test_okx_connector.py` | CONN-03 (sandbox→`wspap`), CONN-04 (loop/spawn/call, no domain import) | mocked ccxt.pro; assert connected URL contains `wspap` when sandbox |
| `tests/unit/connectors/test_okx_data_provider.py` | CONN-01 (`confirm=="1"` gate, forming bars dropped; REST backfill Decimal-edge) | recorded business-channel payload fixture + `AsyncMock` |
| `tests/unit/execution/test_okx_exchange.py` | CONN-02/CONN-05 (`amount_to_precision` rounding; raw fill→`FillEvent` on queue) | `AsyncMock` over `create_order`/`watch_my_trades`; drain `global_queue` |
| `tests/unit/config/test_okx_settings.py` | CONN-06 (plain `OKX_API_*`, `SecretStr`, no leak in repr/logs) | env-var monkeypatch; assert `repr` masks secrets |
| `tests/unit/connectors/conftest.py` | shared async mocked-ccxt fixtures | `AsyncMock` over the `watch_*`/`create_order`/`cancel_order` surface; **close sessions / cancel tasks in teardown** (Pitfall 4) |
| `tests/integration/test_okx_smoke.py` | D-09 opt-in live smoke | `@pytest.mark.skipif(no creds)` — auto-skips credential-free |

**MEMORY gotchas the planner must honor:** keep `tests/unit/connectors/` **package-less** (no `__init__.py`) to avoid the top-level package collision; the SMA_MACD oracle gate lives at `tests/integration/test_backtest_oracle.py` (byte-exact `134 / 46189.87730727451`); `make test` aborts in worktrees on missing `.env` → gate with `poetry run pytest tests`.

---

## Shared Patterns

### Decimal edge (CONN-05 — applies to `OkxExchange` + `OkxDataProvider`)
**Source:** `itrader/core/money.py::to_money` (lines 59-73) + `quantize` (76-93).
`to_money(x)` = `Decimal(str(x))` with a Decimal fast-path (line 71-73) — so `to_money(str(raw_ccxt_float))` is the canonical inbound crossing; `to_money` already normalizes but passing `str()` at the edge guarantees no float ever forms. Outbound, use ccxt `amount_to_precision`/`price_to_precision` (venue-rounded STRING) — NOT `quantize` (that's for the internal ledger, per-instrument scales). NEVER `Decimal(float)` (money.py D-04 note, lines 20-23; RESEARCH Pitfall 5).
```python
price  = to_money(str(raw["price"]))      # inbound edge
amount = client.amount_to_precision(sym, float(qty))  # outbound (string, lot-rounded)
```

### Queue-only cross-domain writes / D-19 single-writer (applies to `OkxExchange`)
**Source:** `SimulatedExchange` fill emission (`exchanges/simulated.py:243, 295, 316, 344`) — every fill is `self.global_queue.put(FillEvent.new_fill(...))`. `OkxExchange` copies this exactly; the only delta is the `put()` may fire from the connector's asyncio thread (D-07). `queue.Queue` is MPSC-safe (D-19); portfolio state still mutates only on the engine thread via `on_fill`. The connector itself emits **nothing** (D-02).

### DI-over-cross-domain-import (applies to all three arms + composition root)
**Source:** `ExecutionHandler.__init__` injecting a seeded `random.Random` into `SimulatedExchange` (`execution_handler.py:62-66`) + the `PortfolioReadModel` Protocol seam. Arms receive the `LiveConnector` **Protocol** in their constructor and never import `connectors.okx`; only `LiveTradingSystem.__init__` constructs the concretion (D-04). Same shape as `AbstractExchange`/`Account` being imported as contracts, concretions wired at the root.

### `runtime_checkable Protocol` swap-a-fake seam (applies to `connectors/base.py`)
**Source:** `execution_handler/exchanges/base.py::AbstractExchange` (lines 7-16) — `@runtime_checkable class X(Protocol)` with `...` bodies and a docstring naming the swap-a-fake boundary. `LiveConnector` already follows this (base.py:28-36); the reshape keeps the form, changes the slots. Enables the fake-session test strategy (D-08).

### Logger bind idiom (applies to `OkxConnector`, `OkxExchange`, `OkxDataProvider`)
**Source:** ubiquitous — `simulated.py:67`, `binance_stream.py:12`, `execution_handler.py:51`:
```python
self.logger = get_itrader_logger().bind(component="OkxConnector")
```
`info` for connect/init success, `warning` for non-fatal (skipped/unknown), `error` with `exc_info=True` for caught exceptions. **Secrets never logged** (CONN-06) — `SecretStr` guards this at the source.

### `FillEvent.new_fill` construction (applies to `OkxExchange`)
**Source:** `events/fill.py:79-149` (the factory) + call sites `simulated.py:243-245, 291-295`. Signature: `new_fill(status: str, order: OrderEvent, *, price, quantity, commission, time=None)`. Pass venue timestamp as `time=` (never `datetime.now`); it carries `order_id`/`strategy_id`/`portfolio_id` from the order for the audit chain automatically (fill.py:141-148).

---

## No Analog Found

| File / component | Role | Data Flow | Reason |
|------------------|------|-----------|--------|
| Native `/business` WS candle socket inside `okx_provider.py` | data provider | streaming | No native (non-ccxt) websocket subscription exists in the codebase. `binance_stream.py` uses the sync `websocket-client` lib with callbacks; the OKX socket is **async `aiohttp`** on the connector loop with a `confirm=="1"` gate. This is the genuinely new code (RESEARCH §Code Examples lines 402-428 is the reference sketch, not a codebase analog). |
| `OkxConnector` async-loop-on-daemon-thread | connector | event-driven | `LiveTradingSystem` runs a daemon *event-processing* thread (`live_trading_system.py`), but no component owns an `asyncio` loop on a thread with `run_coroutine_threadsafe` bridging. Reference is RESEARCH Pattern 2 (lines 195-223) + nautilus `adapters/okx/` (read-only, in `.venv`), not iTrader code. |

---

## Metadata

**Analog search scope:** `itrader/connectors/`, `itrader/execution_handler/exchanges/` + `execution_handler.py`, `itrader/price_handler/providers/`, `itrader/config/`, `itrader/portfolio_handler/account/`, `itrader/trading_system/`, `itrader/core/money.py`, `itrader/events_handler/events/fill.py`.
**Files scanned (read in full or targeted):** 13 source files + `.env.example` + `pyproject.toml` test config.
**Indentation verified:** per-file `grep -P '^\t'` — tabs in `execution_handler/exchanges/`; 4-space everywhere else.
**Pattern extraction date:** 2026-07-01
