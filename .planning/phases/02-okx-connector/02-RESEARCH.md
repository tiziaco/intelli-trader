# Phase 2: OKX Connector - Research

**Researched:** 2026-07-01
**Domain:** Live crypto-venue integration (OKX v5 over ccxt.pro + a native business-channel WebSocket), async-on-daemon-thread containment, Decimal-edge conversion
**Confidence:** HIGH (every load-bearing claim verified against the INSTALLED `ccxt 4.5.56` / `nautilus-trader 1.227.0` source in `.venv`; OKX externals cross-checked against OKX v5 docs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Split data from execution (not one venue object).** Market data and order execution are independent axes of variation. Separate clients with separate lifecycles — NOT a single `LiveConnector` with a data arm + order arm. Validated against nautilus-trader's OKX adapter (`OKXDataClient` / `OKXExecutionClient` are separate classes/modules/factories). Candles stream on a third `business` WS endpoint (`/ws/v5/business`). Revises LX-05.
- **D-02 — The connector is a shared authenticated session/transport primitive, not an operations owner.** `OkxConnector` (`itrader/connectors/okx.py`) owns: auth (key/secret/passphrase), single `sandbox: bool` routing (`set_sandbox_mode` + native `x-simulated-trading` header — no split-brain), the one `ccxt.pro` client instance, the asyncio loop + daemon thread, rate-limit/connection budget, `connect`/`disconnect` lifecycle. Knows nothing about orders-vs-candles-vs-balances; imports/constructs no domain events. `LiveConnector` (`connectors/base.py`) shrinks to a session/transport contract.
- **D-03 — Each arm is a domain adapter owning its own venue I/O in its home domain:** Orders → `OkxExchange` (impl `AbstractExchange`, `execution_handler/exchanges/`); Data → `OkxDataProvider` (`price_handler/providers/`); Account → `VenueAccount` (`portfolio_handler/account/`).
- **D-04 — Injection, not cross-domain import.** `OkxConnector` constructed once at `LiveTradingSystem.__init__`, injected into each adapter. Adapters type their param against the `LiveConnector` session Protocol, never the concretion. Only the connector authenticates; the three arms share one authenticated session.
- **D-05 — `OkxDataProvider` owns a native `business`-endpoint candle subscription** for the closed-bar `confirm` flag, rather than subclassing ccxt.pro internals. ccxt routes candles to `/ws/v5/business` and `parse_ohlcv` drops OKX's `confirm` (9th field). ccxt.pro still serves the order arm.
- **D-06 — Order arm fully implemented in Phase 2** (`create_order`/cancel/`watch_orders`/`watch_fills` + Decimal-edge + lot/tick rounding), verified with mocked-ccxt. Real sandbox exercise stays Phase 5.
- **D-07 — The exchange emits `FillEvent`, not the connector.** `OkxExchange` translates raw fills → frozen `FillEvent` and puts them on `global_queue`. `put()` may fire from the connector's asyncio thread (thread-safe `queue.Queue`; D-19 single-writer preserved).
- **D-08 — Offline-first, deterministic.** Primary = mocked `ccxt.pro` objects + a recorded OKX-demo payload fixture to pin `confirm`-flag realism. `pytest-asyncio` configured (`asyncio_mode`, `asyncio_default_fixture_loop_scope`) so `filterwarnings=["error"]` stays green. pytest-asyncio not yet a dependency — the plan must add + configure it.
- **D-09 — Sandbox demo account used, bounded.** Demo keys (in `.env`) for (1) fixture capture and (2) opt-in `skipif(no creds)` live smoke test that auto-skips in CI. Formal sandbox validation stays Phase 5.
- **D-10 — `OkxSettings(BaseSettings)` reads plain `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE` with NO env prefix.** Passphrase required. Secrets never in code, logs, commits, or fixtures; backtest path stays credential-free. Real secret manager deferred post-milestone.

### Claude's Discretion
- Exact coroutine-scheduling mechanism between adapters and the connector loop (`run_coroutine_threadsafe` vs a spawn-task API on the session Protocol) — plan-time.
- Exact shape of the new data-provider seam in `price_handler` that `LiveBarFeed` consumes — plan-time (Phase 3 co-shapes it).
- Whether `OkxDataProvider`'s business-candle socket is fully separate vs multiplexed on the connector's loop — plan-time; ownership model (D-03) is fixed.

### Deferred Ideas (OUT OF SCOPE)
- Formal sandbox validation of the order path (reconciliation, partial-fill correctness, restart) — Phase 5.
- 3rd-party market-data provider (non-OKX candles) — enabled by D-01 split, not built now.
- Real secret manager — post-milestone.
- `LiveBarFeed` + `BarEvent` construction, ring buffer, monotonic delivery — Phase 3.
- `VenueAccount` reconciliation logic — Phase 5.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONN-01 | Data arm `OkxDataProvider` streams candles via native `business`-endpoint subscription carrying `confirm`, with REST `fetch_ohlcv` backfill; feeds closed bars to Phase-3 `LiveBarFeed` | §Data arm — native confirm; §Code Examples; confirm cadence VERIFIED |
| CONN-02 | Order arm `OkxExchange` (impl `AbstractExchange`) implements async `create_order` + cancel + `watch_orders`/`watch_fills`; translates raw fills → `FillEvent` | §ccxt native-vs-unified gap; order-arm unified surface VERIFIED (`watch_my_trades` = the fill stream) |
| CONN-03 | Single `sandbox: bool` routes both ccxt (`set_sandbox_mode`) and native (`x-simulated-trading`) to OKX demo + selects demo-vs-live keys — no split-brain | §Sandbox routing (CRITICAL FINDING — D-02 header framing corrected) |
| CONN-04 | `OkxConnector` runs own asyncio loop on own daemon thread; owns no venue ops / emits no domain events; injected, never cross-domain-imported; D-19 preserved | §Async containment; §Architecture Patterns |
| CONN-05 | Every ccxt float crosses Decimal boundary via `to_money`; outbound quantities round to OKX lot/tick via ccxt string-precision helpers (no `Decimal(float)`) | §Don't Hand-Roll; §Decimal edge; `amount_to_precision`/`price_to_precision` VERIFIED |
| CONN-06 | Secrets (apiKey + secret + passphrase) via `OkxSettings(BaseSettings)` reading plain `OKX_API_*`; never in code/logs/fixtures; backtest credential-free | §Secrets; nautilus uses identical env var names |
</phase_requirements>

## Summary

Every technical unknown the ROADMAP flagged as design-blocking is now resolved against installed source, and **one locked-decision detail (D-02) needs correction** before the planner encodes it. The headline: the repo's **installed `ccxt 4.5.56` already ships the entire surface Phase 2 needs** — `watch_ohlcv` (routed to `/ws/v5/business`), the full order-arm unified API (`watch_orders`, `watch_my_trades`, `watch_balance`, `watch_positions`, `create_order`/`create_order_ws`, `cancel_order`/`cancel_order_ws`), and `set_sandbox_mode` with the `x-simulated-trading` header logic. **No ccxt version bump is required** (this refutes the 2026-06-30 SUMMARY's `^4.5.62` suggestion). The only new dependency is `pytest-asyncio 1.4.0` (dev group), which is slopcheck-clean and compatible with the repo's `pytest 9.0.3`.

The `confirm` flag is confirmed dropped by ccxt's `parse_ohlcv` (returns a 6-tuple `[ts,o,h,l,c,v]`; source comment shows the full 9-field OKX layout with "candlestick state" at index 8). OKX pushes the in-progress bar repeatedly (fastest 1 push/sec) with `confirm="0"` and a final push with `confirm="1"` at bar close — so the data arm's native business-channel socket must **gate on `confirm=="1"`** to hand a closed bar to Phase-3's `LiveBarFeed`. This is exactly why D-05's native escape hatch is mandatory.

**The one correction:** D-02 states the single `sandbox: bool` drives both paths via `set_sandbox_mode` **+ a native `x-simulated-trading` header**. Verified reality: `x-simulated-trading` is a **REST-only** header — ccxt's WS client reads `self.options['headers']` (built from `self.streaming` + `self.options['ws']`), **not** `self.headers`, so the header never reaches any WebSocket. OKX demo trading over WS is selected by a **different host** (`wss://wspap.okx.com:8443/...` vs `wss://ws.okx.com:8443/...`), confirmed both in ccxt's `set_sandbox_mode` URL swap and independently in nautilus's Rust URL helpers. A single `sandbox: bool` **can** still drive everything, but the native data socket keys off the **demo WS URL**, not a header. The planner must encode: `sandbox=True` → (a) `ccxt.set_sandbox_mode(True)` for REST-header + ccxt-WS-URL, AND (b) point the native business socket at `wspap.okx.com` + select demo keys.

**Primary recommendation:** Build `OkxConnector` as a shared-transport primitive owning one `ccxt.pro.okx` client (constructed *inside* the loop thread — ccxt.pro clients bind to their creating loop) plus one native `aiohttp`/`websockets` business-candle socket; drive both from `sandbox: bool` via URL/host selection (native) + `set_sandbox_mode` (ccxt); expose a spawn-task API for long-running streams and `run_coroutine_threadsafe` for request/response RPC; convert every float at the adapter edge with `to_money` and round outbound with `amount_to_precision`/`price_to_precision`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Authentication (key/secret/passphrase) | Connector (session primitive) | — | Only the connector authenticates (D-04); arms never see keys |
| Async loop + daemon thread | Connector | — | Async bottled at the connector edge (CONN-04); engine stays synchronous |
| `sandbox: bool` routing | Connector | — | Single knob drives REST header + ccxt WS URL + native WS host + key selection (CONN-03) |
| Rate-limit / connection budget | Connector | — | Coordinates across the one ccxt client + one native socket (RES-01) |
| Candle stream + `confirm` read | Data arm (`OkxDataProvider`, `price_handler/providers/`) | Connector (transport) | Native business-channel socket for `confirm`; connector supplies loop/lifecycle (CONN-01) |
| REST `fetch_ohlcv` backfill | Data arm | Connector (ccxt client) | Backfill is a data concern; uses the shared ccxt REST client (CONN-01) |
| Order create/cancel + order/fill streams | Order arm (`OkxExchange`, `execution_handler/exchanges/`) | Connector (ccxt client) | Order I/O is an exchange concern (matches nautilus exec client); connector = transport (CONN-02) |
| Raw fill → `FillEvent` + `global_queue.put` | Order arm | — | The exchange emits, not the connector (D-07); D-19 preserved |
| Decimal-edge conversion + lot/tick rounding | Each arm (at its own edge) | — | ccxt floats crossed via `to_money` where they enter the domain (CONN-05) |
| Balance/margin/position caching | Account arm (`VenueAccount`) | Connector (streams) | Interface-only this phase; body is Phase 5 (RECON-01) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ccxt` (incl. `ccxt.pro`) | `^4.5.56` (INSTALLED — no bump) | Unified OKX REST + WS: `watch_ohlcv`, order-arm `watch_*`/`create_order*`/`cancel_order*`, `set_sandbox_mode`, `load_markets` precision | Already the repo's crypto interface; ccxt.pro is in-package and free; full needed surface present in the installed version [VERIFIED: `.venv` source] |
| Python stdlib `asyncio` | 3.13.1 | Connector event loop on daemon thread; `run_coroutine_threadsafe` bridge | Zero new dependency; canonical async-on-thread containment [VERIFIED] |
| stdlib `queue.Queue` | 3.13.1 | `global_queue` — thread-safe MPSC put from the connector thread | Already the engine's queue; D-19 single-writer preserved [CITED: CLAUDE.md] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` | `1.4.0` | Async test driver for mocked-ccxt unit tests (D-08) | Dev group ONLY; required to test `async def` connector/adapter methods [VERIFIED: PyPI + slopcheck OK, compatible with installed pytest 9.0.3] |
| `aiohttp` | transitive via ccxt async | Native business-channel WebSocket (ccxt already depends on it) | Data arm's raw `/business` socket (D-05); do NOT pin explicitly — inherit ccxt's resolved version [VERIFIED: ccxt WS client uses aiohttp] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native aiohttp business socket | `python-okx` / `okx-sdk` | Adds a whole SDK for one channel; ccxt already ships aiohttp and the URL helpers — a raw socket is smaller surface and avoids a second auth stack. Do NOT add. |
| One shared `ccxt.pro` client (D-02) | Two ccxt clients (data + order) | Nautilus shares HTTP transport but gives each arm its own WS sockets. iTrader's D-02 (one client) is fine because ccxt.pro's `client(url)` internally keys sockets by URL — one instance holds multiple sockets. Keep D-02. |
| `run_coroutine_threadsafe` + spawn API | `janus` sync/async queue | `janus` is unneeded — `queue.Queue.put` is already thread-safe from the loop thread. Do NOT add. |

**Installation:**
```bash
poetry add --group dev "pytest-asyncio@^1.4.0"
# ccxt already present at ^4.5.56 — no change
```

**Version verification (run at plan time):**
```bash
poetry run python -c "import ccxt; print(ccxt.__version__)"   # expect 4.5.56 (surface already sufficient)
pip index versions pytest-asyncio                             # 1.4.0 latest; requires pytest <10,>=8.4
```

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `pytest-asyncio` | PyPI | ~10 yrs (0.1 → 1.4.0) | ~30M+/mo | github.com/pytest-dev/pytest-asyncio | [OK] | Approved (dev group) |
| `ccxt` | PyPI | already installed `4.5.56` | very high | github.com/ccxt/ccxt | n/a (existing pin) | No change |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

`pytest-asyncio 1.4.0` verified clean via `slopcheck install` (verdict `[OK]`, pypi ecosystem) and confirmed compatible with the repo's installed `pytest 9.0.3` (`Requires-Dist: pytest<10,>=8.4`). The `pip install` triggered by slopcheck placed it in `.venv` but NOT in `poetry.lock` — the plan must add it via `poetry add --group dev` so the lockfile is authoritative.

## Architecture Patterns

### System Architecture Diagram

```
                        LiveTradingSystem.__init__  (composition root, engine thread)
                                     │  constructs ONCE, injects the session
                                     ▼
                        ┌──────────────────────────────────┐
                        │  OkxConnector (session/transport)  │
                        │  - auth (key/secret/passphrase)    │
                        │  - sandbox: bool → URL/header/keys │
                        │  - 1 ccxt.pro.okx client           │
                        │  - 1 native /business WS socket    │
                        │  - asyncio loop on DAEMON THREAD   │
                        │  - rate-limit budget               │
                        └───────┬───────────┬───────────┬────┘
              injected session  │           │           │  injected session
        ┌────────────────────── ▼ ──┐  ┌────▼─────────┐ └──▼───────────────────┐
        │ OkxDataProvider (data arm)│  │ OkxExchange  │   │ VenueAccount        │
        │ price_handler/providers/  │  │ (order arm)  │   │ (account arm — P5   │
        │                           │  │ execution_.. │   │  body; iface only)  │
        │ native /business candle → │  │ create/cancel│   │                     │
        │   gate confirm=="1"       │  │ watch_orders │   │                     │
        │ REST fetch_ohlcv backfill │  │ watch_my_trades (fills)               │
        └───────────┬──────────────┘  └──────┬───────┘   └─────────────────────┘
     closed bars    │                        │  raw fill → FillEvent
   (to Phase-3      ▼                         ▼
    LiveBarFeed)  [Phase 3]            global_queue.put(FillEvent)  ── thread-safe MPSC ──▶ engine thread
                                       (D-07: the EXCHANGE emits; D-19 single-writer: portfolio
                                        state still mutates only on the engine thread via on_fill)
```

Data flow to trace: OKX `/business` socket → data provider filters `confirm=="1"` → hands closed bar to Phase-3 feed. OKX order WS → `OkxExchange.watch_my_trades` coroutine (on connector loop) → builds `FillEvent` → `global_queue.put` → engine dispatch thread drains → `portfolio_handler.on_fill`.

### Recommended Project Structure
```
itrader/connectors/
├── base.py            # LiveConnector Protocol — RESHAPE to session/transport contract (D-02)
├── okx.py             # NEW: OkxConnector (session primitive)
└── __init__.py        # export OkxConnector alongside LiveConnector

itrader/config/
└── okx_settings.py    # NEW: OkxSettings(BaseSettings), plain OKX_API_* (D-10)

itrader/price_handler/providers/
└── okx_provider.py    # NEW: OkxDataProvider (data arm, native /business socket) (D-03)

itrader/execution_handler/exchanges/
└── okx.py             # NEW: OkxExchange(AbstractExchange) (order arm) (D-03)
```

### Pattern 1: Shared-transport, per-arm clients (nautilus-validated)
**What:** One authenticated transport primitive; each domain arm owns its own venue I/O against the shared session.
**When to use:** Always for this phase — it is D-01..D-04.
**Nautilus reference (VERIFIED in `.venv`):** `nautilus_trader/adapters/okx/factories.py` builds a single `get_cached_okx_http_client(...)` (an `@lru_cache(1)` keyed on auth+environment) and passes that ONE http client into BOTH `OKXLiveDataClientFactory.create` and `OKXLiveExecClientFactory.create`. Each client then constructs its OWN WS sockets:
```python
# nautilus_trader/adapters/okx/data.py (VERIFIED, lines 163–184) — the data client
self._ws_client = nautilus_pyo3.OKXWebSocketClient(
    url=config.base_url_ws or nautilus_pyo3.get_okx_ws_url_public(self._environment),  # public
    api_key=None, api_secret=None, api_passphrase=None, ...)
# a SEPARATE socket for candles/bars on the business endpoint:
_public_url = config.base_url_ws or nautilus_pyo3.get_okx_ws_url_public(self._environment)
self._ws_business_client = nautilus_pyo3.OKXWebSocketClient(
    url=nautilus_pyo3.derive_okx_ws_url(_public_url, "business"),   # ← candle channel host
    api_key=config.api_key, api_secret=config.api_secret, api_passphrase=config.api_passphrase, ...)
```
**Takeaways for iTrader:**
- The business/candle socket is a **separate socket** from the public socket in nautilus — informs the Claude's-Discretion item: the native candle socket can legitimately be its own socket (not multiplexed).
- `environment: OKXEnvironment (LIVE|DEMO)` is the single enum that drives URL derivation for HTTP and WS — this is nautilus's `sandbox: bool` analog; map iTrader's bool onto the same idea.
- Env var names are **identical to D-10**: `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE` [VERIFIED: `config.py` docstrings].

### Pattern 2: Async event loop on a daemon thread (containment)
**What:** Connector owns `asyncio.new_event_loop()` run on a `threading.Thread(daemon=True)`; all ccxt.pro calls happen ON that loop.
**When to use:** The connector's `connect()` starts the thread; `disconnect()` stops the loop.
**Critical:** ccxt.pro clients bind to the loop that creates their sockets (`client(url)` calls `self.open()` to set `self.asyncio_loop`). **Create the `ccxt.pro.okx` instance inside the loop thread**, and route every call through it via the loop — ccxt.pro is not thread-safe.
```python
# Sketch — connector loop containment
import asyncio, threading

class OkxConnector:
    def connect(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="okx-connector")
        self._thread.start()
        # build the ccxt.pro client ON the loop:
        fut = asyncio.run_coroutine_threadsafe(self._build_client(), self._loop)
        fut.result(timeout=30)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # request/response RPC (create_order, cancel, fetch_ohlcv):
    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=30)

    # long-running stream (watch_my_trades loop, native candle loop):
    def spawn(self, coro) -> asyncio.Task:
        # schedule an infinite consume-loop task on the connector loop
        return asyncio.run_coroutine_threadsafe(self._spawn(coro), self._loop).result()
    async def _spawn(self, coro):
        return self._loop.create_task(coro)
```
**Recommendation on the Claude's-Discretion scheduling item:** expose BOTH on the session Protocol — a `call(coro)` for RPC (returns the result, blocks the engine thread briefly) and a `spawn(coro)` for the streaming subscriptions (the stream task calls `global_queue.put` on each closed bar/fill). Streams must be spawned, not `.result()`-awaited, because `watch_*` never returns.

### Pattern 3: Decimal edge + string precision rounding (CONN-05)
**What:** Convert inbound ccxt floats with `to_money(str(x))`; round outbound quantities with ccxt's string helpers, never `Decimal(float)`.
```python
from itrader.core.money import to_money
# inbound (a fill): every numeric field is a float from ccxt
price = to_money(str(raw["price"]))     # to_money already does Decimal(str(x)); pass through str is safe
amount = to_money(str(raw["amount"]))
# outbound (submitting): round to OKX lot/tick using ccxt precision (returns a STRING)
amount_str = client.amount_to_precision(symbol, float(qty))   # str, lot-rounded
price_str  = client.price_to_precision(symbol, float(px))     # str, tick-rounded
```
**Note:** `to_money(x)` = `Decimal(str(x))` already (verified in `core/money.py`), so `to_money(raw_float)` is safe — the `str()` normalization happens inside. `amount_to_precision`/`price_to_precision` are base-`Exchange` methods available on the okx instance and require `load_markets()` first to populate per-symbol precision.

### Anti-Patterns to Avoid
- **Reading `confirm` off ccxt `watch_ohlcv`:** it is dropped by `parse_ohlcv` — you will get a 6-tuple with no state field. Use the native business socket (D-05).
- **Setting `x-simulated-trading` on the WebSocket:** it does nothing on WS (REST-only header). Use the demo host URL instead (see Sandbox routing below).
- **Calling ccxt.pro from the engine thread directly:** clients bind to the connector loop; cross-thread calls corrupt socket state. Always bridge via `run_coroutine_threadsafe`.
- **`Decimal(some_ccxt_float)`:** binary-float poison (locked money defect). Always `to_money`.
- **Awaiting a `watch_*` coroutine to completion:** it loops forever; spawn it as a task.

## Sandbox Routing — CRITICAL FINDING (CONN-03 / D-02 correction)

> **This partially refutes D-02's stated mechanism.** The single `sandbox: bool` design is sound, but the `x-simulated-trading` header is **REST-only** and does NOT reach any WebSocket. The planner must encode URL/host selection for the WS paths.

**What `ccxt.okx.set_sandbox_mode(enable)` actually does** [VERIFIED: `ccxt/okx.py:7558`, `ccxt/base/exchange.py:3223`]:
1. `super().set_sandbox_mode()` swaps `self.urls['api']` → `self.urls['test']`. For ccxt.pro OKX this changes the WS host: `wss://ws.okx.com:8443/ws/v5` → `wss://wspap.okx.com:8443/ws/v5` [VERIFIED: `ccxt/pro/okx.py:52-58`].
2. Sets `self.options['sandboxMode'] = True` → `get_url()` appends `?brokerId=9999` to the WS URL [VERIFIED: `ccxt/pro/okx.py:119-130`].
3. Sets `self.headers['x-simulated-trading'] = '1'` — used ONLY by REST `prepare_request_headers`.

**Why the header never reaches WS** [VERIFIED: `ccxt/async_support/base/exchange.py:447-458` + `ccxt/async_support/base/ws/client.py:300-301`]: the WS `Client` is constructed with `options = extend(self.streaming, {...}, self.options['ws'])` and connects with `headers=self.options.get('headers')`. That is `self.options['headers']`, **not** `self.headers`. `set_sandbox_mode` writes to `self.headers`, so the demo header is never in the WS client's options. **OKX WS demo is selected purely by the `wspap.okx.com` host.**

**Independently corroborated by nautilus's Rust URL helpers** [VERIFIED — executed in `.venv`]:
```
LIVE  → public  wss://ws.okx.com:8443/ws/v5/public    | business wss://ws.okx.com:8443/ws/v5/business
DEMO  → public  wss://wspap.okx.com:8443/ws/v5/public  | business wss://wspap.okx.com:8443/ws/v5/business
```
And OKX v5 docs [CITED: okx.com/docs-v5]: *"The `x-simulated-trading: 1` header applies to REST requests only, not WebSocket connections. Demo Public WebSocket: `wss://wspap.okx.com:8443/ws/v5/public`."*

**The corrected single-bool routing the planner must implement:**

| Path | Transport | `sandbox=True` mechanism |
|------|-----------|--------------------------|
| ccxt REST (`fetch_ohlcv`, `create_order` REST fallback) | REST | `set_sandbox_mode(True)` → `x-simulated-trading: 1` header (correct here) |
| ccxt.pro WS (order arm: `watch_orders`, `watch_my_trades`, `create_order_ws`, `cancel_order_ws`) | WS | `set_sandbox_mode(True)` → host swap to `wspap.okx.com` (the base URL swap; NOT the header) |
| Native `/business` candle socket (data arm, D-05) | WS | **The data provider must itself pick `wss://wspap.okx.com:8443/ws/v5/business`** — `set_sandbox_mode` does not touch the native socket at all |
| Key selection | both | `OkxSettings` supplies demo keys when `sandbox=True` (demo keys ≠ live keys — see below) |

So: `OkxConnector.sandbox=True` → call `client.set_sandbox_mode(True)` (drives REST header + ccxt WS host) **and** construct the native business socket against the `wspap` host **and** load demo credentials. One bool, three coordinated effects. There is no header knob to forget — the native side keys off URL. **"No split-brain" holds, but only if the native socket's URL is driven from the same bool.** [ASSUMED → now VERIFIED where source-checkable; the D-02 header framing for WS is refuted.]

**`brokerId=9999` nuance:** ccxt appends `?brokerId=9999` to the demo WS URL; nautilus does not. The query param is historically associated with demo WS and is harmless. For the native socket, matching ccxt's `wspap` host is the essential part; append `?brokerId=9999` to be safe. [MEDIUM — confirm during fixture capture (D-09).]

## OKX `confirm` Flag — VERIFIED behavior (CONN-01)

**Field layout on the business candle channel** (trading candlesticks) [CITED: OKX v5 candlesticks channel docs; VERIFIED against `ccxt/okx.py:2529-2542` parse comment]:
```
[ ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm ]
   0   1  2  3  4   5      6         7          8      ← confirm is index 8 (the 9th field)
```
ccxt's `parse_ohlcv` returns only `[ts, o, h, l, c, vol]` (a 6-tuple) — `volCcy`, `volCcyQuote`, and **`confirm` are dropped** [VERIFIED: `ccxt/okx.py:2546-2553`]. This is exactly the gap D-05 addresses.

**`confirm` values** [CITED: OKX docs]:
- `"0"` — candle is **uncompleted** (in-progress / forming bar)
- `"1"` — candle is **completed** (closed / final)

**Push cadence** [CITED: OKX docs "fastest push frequency is 1 push per second" + VERIFIED design implication]: OKX pushes the in-progress bar repeatedly (up to ~1/sec) with `confirm="0"`, then a final push with `confirm="1"` when the bar closes. The same `ts` (bar-open timestamp) recurs across the `confirm="0"` pushes and the terminal `confirm="1"` push. **Design consequence:** `OkxDataProvider` must gate on `confirm=="1"` and hand ONLY that terminal bar to Phase-3's `LiveBarFeed`. The forming-bar pushes are discarded (or used only for a live "current price" if ever needed — not this phase).

**Subscription arg shape** [VERIFIED: `ccxt/pro/okx.py:974-983,126-127`]:
```json
{ "op": "subscribe", "args": [ { "channel": "candle1m", "instId": "BTC-USDT" } ] }
```
sent on the business endpoint: `wss://ws.okx.com:8443/ws/v5/business` (live) / `wss://wspap.okx.com:8443/ws/v5/business` (demo). The channel name is `"candle" + interval` (e.g. `candle1m`, `candle1D`). ccxt maps its unified timeframe to the OKX interval via `self.timeframes`; the native path should mirror OKX's interval tokens (`1m`, `5m`, `1H`, `1D`, ...). The push envelope: `{"arg":{"channel":"candle1m","instId":"BTC-USDT"},"data":[[...9 fields...]]}` [VERIFIED: `ccxt/pro/okx.py:1026-1039`].

## ccxt.pro Native-vs-Unified Gap List (CONN-01 / CONN-02)

**Order arm — CAN use the unified ccxt.pro API** [VERIFIED by instance introspection on `ccxt.pro.okx()`]:

| Need | ccxt.pro method | Notes |
|------|-----------------|-------|
| Submit order (WS) | `create_order_ws` | `ccxt/pro/okx.py:1966` |
| Submit order (REST) | `create_order` | inherited REST; `ccxt/okx.py:3267` |
| Cancel (WS / REST) | `cancel_order_ws` / `cancel_order` | `ccxt/pro/okx.py:2072` |
| Order status stream | `watch_orders` | `ccxt/pro/okx.py:1750` |
| **Fill stream** | **`watch_my_trades`** | `ccxt/pro/okx.py:1573` — **NOTE: there is NO `watch_fills` method**; CONTEXT's "watch_fills" is conceptual. The fill stream is `watch_my_trades`. |
| Balance stream | `watch_balance` | `ccxt/pro/okx.py:1436` |
| Position stream | `watch_positions` | `ccxt/pro/okx.py:1619` (account arm, Phase 5) |
| Lot/tick precision | `load_markets` + `amount_to_precision` / `price_to_precision` | base-`Exchange` helpers; require `load_markets()` first |

**Data arm — needs NATIVE access for exactly one thing:** the `confirm` field. Everything else the data arm needs (REST `fetch_ohlcv` backfill) works through unified ccxt. Only the streaming closed-bar detection requires the raw business socket, because unified `watch_ohlcv` drops `confirm`.

**Summary:** the only unified-API gap in Phase 2 is `confirm` on streamed candles. The order arm is fully served by unified ccxt.pro; the account arm (Phase 5) is fully served by `watch_balance`/`watch_positions`.

## OKX Demo-Key Requirements (CONN-03 / CONN-06)

[CITED: OKX v5 docs; VERIFIED: nautilus `config.py` uses the same auth triple + env var names]
- **Auth triple:** `apiKey` + `secret` + **`passphrase`** — all three required for OKX (the passphrase is set by the user at API-key creation). ccxt's okx requires `password` (its field name for the passphrase). Missing passphrase → auth failure.
- **Demo keys are SEPARATE from live keys** — generated inside the OKX demo-trading environment, not the live account. A live key will not authenticate against the demo host and vice-versa.
- **Passphrase is required for demo too.**
- **Single-bool key selection:** `sandbox=True` must select the demo key set. D-10 uses plain `OKX_API_*` with no prefix, and D-09 says `.env` holds the **demo** keys for this phase. So for Phase 2, `OkxSettings` reads the demo keys from `OKX_API_*`; production dual-key handling (holding both live and demo) is a post-milestone secret-manager concern (deferred). The planner should NOT build a dual-key scheme now — one key set (demo) driven by `sandbox=True`.

**ccxt client construction** (for reference):
```python
import ccxt.pro as ccxtpro
client = ccxtpro.okx({
    "apiKey": settings.api_key.get_secret_value(),
    "secret": settings.api_secret.get_secret_value(),
    "password": settings.api_passphrase.get_secret_value(),   # ← passphrase goes in "password"
    "enableRateLimit": True,                                    # built-in throttler (RES-01)
})
if sandbox:
    client.set_sandbox_mode(True)   # REST header + WS host swap to wspap
```

## Async Containment (Claude's Discretion resolution)

**Recommendation:** connector owns `asyncio.new_event_loop()` on a daemon thread; the session Protocol exposes **two** scheduling primitives:
- `call(coro) -> T` — `run_coroutine_threadsafe(coro, loop).result(timeout)` for request/response RPC (`create_order`, `cancel_order`, `fetch_ohlcv`). Blocks the calling (engine) thread briefly; that is acceptable for order submission.
- `spawn(coro) -> handle` — schedules a long-running consume-loop task on the connector loop for streaming subscriptions (`watch_my_trades`, `watch_orders`, native candle loop). The task body calls `global_queue.put(event)` per closed bar / fill. It must NOT be `.result()`-awaited because `watch_*` loops forever.

**Why both:** `run_coroutine_threadsafe` alone cannot host the infinite stream loops without blocking; a spawn API alone forces awkward future-plumbing for simple RPC. Nautilus tracks stream tasks in a `set[asyncio.Future]` per client and cancels them on disconnect [VERIFIED: `data.py:171,185` / `execution.py:213`] — mirror this (`self._stream_tasks: set[asyncio.Task]`, cancel-all in `disconnect()`).

**Determinism / business-time:** all emitted events (fills) stamp `time` from the **venue** timestamp (fill/order timestamp), never `datetime.now`. This is the same discipline the SUMMARY flagged (wall-clock is contagious). Bars carry the OKX bar-open `ts` (Phase 3 owns `BarEvent` construction).

## OKX Rate Limits (RES-01 — begins here, home Phase 5)

[CITED: OKX v5 docs, verified via WebFetch]
- **3 connection requests per second per IP.** With one ccxt.pro client (one private WS socket, one REST) + one native business socket = ~2 sockets → comfortably under budget. Do not churn reconnects.
- **480 subscribe/unsubscribe/login requests per hour PER connection.** Phase 2 subscribes a handful of channels once → trivially under budget. Avoid resubscribe storms on reconnect.
- **Order rate limits:** REST + WS order-management operations share per-instrument buckets (e.g. spot ~60 orders / 2s per instrument). ccxt's built-in `enableRateLimit` throttler (`tokenBucket`) handles pacing [VERIFIED: throttler wired in `client()`]. Leave `enableRateLimit=True`.
- **Phase 2 RES-01 scope is light:** own the connection budget (one ccxt client + one native socket), leave ccxt rate-limiting on, don't churn subscriptions. The heavy resilience work (reconnect + gap recovery) is Phase 3/5.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Lot/tick rounding of outbound qty/price | Custom Decimal quantize to venue steps | `client.amount_to_precision(sym, x)` / `price_to_precision` | ccxt reads OKX `load_markets` precision; returns venue-correct STRING; avoids `Decimal(float)` |
| REST/WS rate limiting | Manual token bucket | ccxt `enableRateLimit=True` (built-in throttler) | Already wired per exchange; OKX-tuned buckets |
| Sandbox REST header | Manual header injection | `client.set_sandbox_mode(True)` | Handles REST header + ccxt WS host swap in one call |
| Symbol/market metadata | Hard-coded instrument specs | `client.load_markets()` | Source of truth for precision, contract size, limits |
| Float→Decimal at edge | `Decimal(x)` | `to_money(str(x))` (`core/money.py`) | Locked money defect otherwise; `to_money` already normalizes |
| sync↔async queue bridge | `janus` / custom | stdlib `queue.Queue.put` (already thread-safe) + `run_coroutine_threadsafe` | Zero new dep; D-19 MPSC-safe |

**Key insight:** almost everything Phase 2 needs already exists — in ccxt (precision, rate limit, sandbox REST, market metadata), in stdlib (asyncio bridge, thread-safe queue), and in the repo (`to_money`, `AbstractExchange`, `LiveConnector` Protocol). The genuinely new code is small: the connector loop-on-thread + the native business-candle socket for `confirm`.

## Common Pitfalls

### Pitfall 1: Reading `confirm` off unified `watch_ohlcv`
**What goes wrong:** you get `[ts,o,h,l,c,v]` with no state field; the forming-bar/closed-bar distinction is impossible; paper-parity later fails silently.
**Why:** ccxt `parse_ohlcv` drops index 8 [VERIFIED].
**How to avoid:** native business socket (D-05); gate on `confirm=="1"`.
**Warning sign:** any code path that decides bar-closed without reading `confirm`.

### Pitfall 2: Expecting `x-simulated-trading` to route WS demo
**What goes wrong:** you set the header, connect to `ws.okx.com` (live host), and unknowingly stream/trade against LIVE while believing it is demo.
**Why:** the WS client reads `self.options['headers']`, not `self.headers` [VERIFIED]; demo WS is host-based (`wspap.okx.com`).
**How to avoid:** drive the native socket host from `sandbox: bool`; rely on `set_sandbox_mode` for the ccxt WS host swap; assert the connected URL contains `wspap` when `sandbox=True`.
**Warning sign:** a native socket URL hard-coded to `ws.okx.com`.

### Pitfall 3: Calling ccxt.pro from the engine thread
**What goes wrong:** socket state corruption / "attached to a different loop" errors.
**Why:** ccxt.pro clients bind to their creating loop and are not thread-safe.
**How to avoid:** build the client inside the loop thread; bridge every call via `run_coroutine_threadsafe`.

### Pitfall 4: Unclosed async sessions fail the strict suite
**What goes wrong:** an aiohttp/ccxt session left open at test teardown raises `ResourceWarning: unclosed` → escalates to an error; an un-awaited coroutine raises `RuntimeWarning` → error.
**Why:** repo `filterwarnings` starts with `"error"` and does NOT ignore `ResourceWarning`/`RuntimeWarning` (it only ignores `UserWarning`/`DeprecationWarning`). See §Validation Architecture for the exact filter.
**How to avoid:** mocked ccxt.pro objects in unit tests (no real sockets); `await client.close()` in teardown for any real session; never leave a `watch_*` task un-cancelled.

### Pitfall 5: `Decimal(float)` on a ccxt field
**What goes wrong:** binary-float artifact enters money math → oracle/reconciliation drift.
**How to avoid:** `to_money(str(x))` at every adapter edge; `amount_to_precision`/`price_to_precision` (string) for outbound.

### Pitfall 6: Assuming a ccxt version bump is needed
**What goes wrong:** wasted churn / lockfile risk chasing `^4.5.62`.
**Reality:** installed `4.5.56` already has the full surface [VERIFIED]. Do NOT bump unless a concrete missing method is proven.

## Code Examples

### Native business-channel closed-bar loop (data arm, CONN-01)
```python
# Source: OKX v5 candlesticks channel docs + ccxt/pro/okx.py subscription shape (VERIFIED)
import json, aiohttp
from itrader.core.money import to_money

async def _stream_candles(self, symbol_okx: str, channel: str):   # channel e.g. "candle1D"
    host = "wspap.okx.com" if self._sandbox else "ws.okx.com"     # ← sandbox = host, not header
    url = f"wss://{host}:8443/ws/v5/business"
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(url, autoping=False) as ws:
            await ws.send_json({"op": "subscribe",
                                "args": [{"channel": channel, "instId": symbol_okx}]})
            async for msg in ws:
                payload = json.loads(msg.data)
                for row in payload.get("data", []):
                    # row = [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
                    if row[8] != "1":        # gate: only completed bars (index 8)
                        continue
                    closed_bar = {
                        "ts": int(row[0]),   # bar-open ms (business time, NOT wall clock)
                        "open":  to_money(row[1]), "high": to_money(row[2]),
                        "low":   to_money(row[3]), "close": to_money(row[4]),
                        "volume": to_money(row[5]),
                    }
                    self._hand_closed_bar_to_feed(closed_bar)   # Phase-3 LiveBarFeed consumes
```
*(`to_money` accepts the raw string directly — OKX sends numeric strings, so no float ever forms.)*

### Order arm fill stream → FillEvent (order arm, CONN-02 / D-07)
```python
# Source: ccxt/pro/okx.py watch_my_trades (VERIFIED — this is the fill stream, NOT "watch_fills")
async def _stream_fills(self):
    while True:
        trades = await self._connector.client.watch_my_trades()   # unified; on connector loop
        for t in trades:
            fill = FillEvent.new_fill(
                time=_ms_to_dt(t["timestamp"]),          # venue time, never wall-clock
                price=to_money(str(t["price"])),
                quantity=to_money(str(t["amount"])),
                # ... map fee via to_money(str(t["fee"]["cost"])), side, symbol ...
            )
            self.global_queue.put(fill)                  # the EXCHANGE emits (D-07); MPSC-safe (D-19)
```

### OkxSettings (CONN-06 / D-10)
```python
# Source: itrader/config/settings.py pattern + nautilus OKX env var names (VERIFIED identical)
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class OkxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")   # NO prefix (D-10)
    api_key: SecretStr        # OKX_API_KEY
    api_secret: SecretStr     # OKX_API_SECRET
    api_passphrase: SecretStr # OKX_API_PASSPHRASE  (required — OKX auth triple)
```
*(`SecretStr` keeps credentials out of logs/reprs/fixtures — CONN-06. `env_prefix=""` maps fields to plain `OKX_API_*`.)*

## Runtime State Inventory

> Greenfield adapter phase — no rename/migration. Included only where a live artifact touches runtime state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the connector is stateless transport; no datastore keys created this phase. Verified by scope (D-02). | none |
| Live service config | OKX demo account API keys must exist in the OKX demo environment (separate from live). User confirms keys are in `.env` (D-09). | User provides demo keys; not code |
| OS-registered state | None — no OS registration; the daemon thread is process-local. | none |
| Secrets/env vars | `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE` added to `.env` / `.env.example` (already present in `.env.example`, verified). Read only by the connector. | Ensure `.env` has DEMO keys before fixture capture |
| Build artifacts | `pytest-asyncio` must be added to `poetry.lock` via `poetry add --group dev` (slopcheck's `pip install` did not update the lockfile). | `poetry add --group dev pytest-asyncio@^1.4.0` |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OKX candles on `/public` WS | Candles migrated to `/business` WS (`candle{tf}`) | OKX v5 WS URL change notice | ccxt routes candle channels to `/business` automatically [VERIFIED: `get_url` line 126] |
| ccxt.pro as a paid add-on | ccxt.pro free + in-package (`import ccxt.pro`) | ccxt v1.95+ | No license, no extra install; already in the repo |
| SUMMARY suggested `ccxt ^4.5.62` bump | Installed `4.5.56` already sufficient | this research | No bump needed — refutes SUMMARY line |

**Deprecated/outdated:**
- The 2026-06-30 SUMMARY's `filterwarnings=["error"]` shorthand: the repo's actual filter also ignores `UserWarning`/`DeprecationWarning` — see Validation Architecture. The pytest-asyncio deprecation-warning concern is therefore smaller than framed; the real strict risks are `ResourceWarning`/`RuntimeWarning`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OKX pushes forming bars repeatedly with `confirm="0"` then a terminal `confirm="1"` (docs state field values + "1 push/sec" but not literally the repeated-then-final sequence) | confirm behavior | LOW — gating on `confirm=="1"` is correct regardless of intermediate cadence; fixture capture (D-09) will confirm exact sequence |
| A2 | `?brokerId=9999` on the demo WS URL is harmless/optional for the native socket | Sandbox routing | LOW — matching the `wspap` host is the essential part; confirm during fixture capture |
| A3 | For Phase 2, `.env` holds DEMO keys and a single key set suffices (no live/demo dual-key scheme) | Demo keys | LOW — per D-09/D-10; production dual-key is deferred post-milestone |
| A4 | One shared ccxt.pro client can host both the private order WS and REST without contention (D-02) | Standard Stack | LOW — ccxt.pro keys sockets by URL internally; nautilus shares HTTP similarly |

## Open Questions

1. **Exact `confirm="0"` push count/frequency for daily (`candle1D`) bars on the golden dataset timeframe.**
   - What we know: field values + "fastest 1 push/sec".
   - What's unclear: whether a `1D` bar pushes every second or only on trade activity.
   - Recommendation: capture a real demo business-channel payload (D-09) and pin it as the fixture; the closed-bar gate (`confirm=="1"`) is correct either way.

2. **Whether the native business socket should share the connector's single `aiohttp` session or open its own.**
   - What we know: nautilus uses a separate socket for business.
   - Recommendation (Claude's Discretion, plan-time): a separate socket owned by the data provider but running on the connector's loop — matches nautilus and keeps the order-arm ccxt client independent of candle-stream lifecycle.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `ccxt` (+ `ccxt.pro`) | data + order arms | ✓ | 4.5.56 | — |
| `nautilus-trader` (reference only) | D-01 structural pattern | ✓ | 1.227.0 | — (read-only reference) |
| `aiohttp` (via ccxt) | native business socket | ✓ | transitive | — |
| `pytest-asyncio` | async tests (D-08) | ✗ (not in lock) | 1.4.0 target | none — must add via poetry |
| Python `asyncio` | connector loop | ✓ | 3.13.1 | — |
| OKX demo API keys | fixture capture + smoke test (D-09) | user-supplied in `.env` | — | tests `skipif(no creds)` auto-skip |

**Missing dependencies with no fallback:** `pytest-asyncio` — the plan MUST add it (`poetry add --group dev pytest-asyncio@^1.4.0`) before async tests can run.
**Missing dependencies with fallback:** OKX demo keys — the offline mocked-ccxt suite runs credential-free; only fixture capture + the opt-in smoke test need real keys, and those auto-skip without `.env` (D-09).

## Validation Architecture

> nyquist_validation treated as enabled (no `workflow.nyquist_validation: false` found).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.4.0 (to add) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/connectors -x` (new dir) |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree — see MEMORY: make test aborts on missing `.env`) |

**Exact `filterwarnings` in the repo (VERIFIED — correcting the SUMMARY shorthand):**
```toml
filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]
addopts = ["-ra", "--strict-markers", "--strict-config", "--disable-warnings", "-v"]
```
Implication: pytest-asyncio's `PytestDeprecationWarning` (a `DeprecationWarning` subclass) is already ignored, so the loop-scope warning will NOT fail the suite. BUT `--strict-config` turns config warnings into errors, and `ResourceWarning`/`RuntimeWarning` are NOT ignored → both fail. So still set the two asyncio config keys (avoids the config-warning path) AND always close async sessions / cancel stream tasks.

**Required pyproject additions (D-08):**
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"                              # no per-test @pytest.mark.asyncio needed
asyncio_default_fixture_loop_scope = "function"    # silences the unset-scope config warning
```
`--strict-markers` note: pytest-asyncio registers its own `asyncio` marker via the plugin (plugin-registered markers are exempt from `--strict-markers`), and `asyncio_mode="auto"` means you don't apply it manually. No change to the `markers` list needed.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONN-01 | Native business socket gates on `confirm=="1"`; forming bars dropped | unit (mocked ws + recorded fixture) | `pytest tests/unit/connectors/test_okx_data_provider.py -x` | ❌ Wave 0 |
| CONN-01 | REST `fetch_ohlcv` backfill returns Decimal-edge bars | unit (mocked ccxt) | `pytest tests/unit/connectors/test_okx_data_provider.py -k backfill -x` | ❌ Wave 0 |
| CONN-02 | `create_order`/cancel round via `amount_to_precision`; raw fill → `FillEvent` on queue | unit (mocked ccxt) | `pytest tests/unit/execution/test_okx_exchange.py -x` | ❌ Wave 0 |
| CONN-03 | `sandbox=True` selects `wspap` host for native socket + `set_sandbox_mode` called | unit | `pytest tests/unit/connectors/test_okx_connector.py -k sandbox -x` | ❌ Wave 0 |
| CONN-04 | Connector loop on daemon thread; `spawn`/`call` bridge; no domain import in connector | unit | `pytest tests/unit/connectors/test_okx_connector.py -k loop -x` | ❌ Wave 0 |
| CONN-05 | Every ccxt float crosses `to_money`; no `Decimal(float)` in adapters | unit + grep guard | `pytest tests/unit/connectors -k decimal -x` | ❌ Wave 0 |
| CONN-06 | `OkxSettings` reads plain `OKX_API_*`; `SecretStr`; secrets absent from logs/repr | unit | `pytest tests/unit/config/test_okx_settings.py -x` | ❌ Wave 0 |
| (gate) | Backtest oracle byte-exact; connector inert on hot path | integration | existing `tests/integration/test_backtest_oracle.py` (MEMORY: oracle lives here) | ✅ |
| D-09 | Opt-in live smoke test (connect demo, subscribe candle, tiny create/cancel) | integration, skipif no creds | `pytest tests/integration/test_okx_smoke.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/connectors tests/unit/execution/test_okx_exchange.py -x`
- **Per wave merge:** `poetry run pytest tests` (full suite green)
- **Phase gate:** full suite green + backtest oracle byte-exact (`134 / 46189.87730727451`) + no W1/W2 regression before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `poetry add --group dev pytest-asyncio@^1.4.0` + add `asyncio_mode`/`asyncio_default_fixture_loop_scope` to `pyproject.toml`
- [ ] `tests/unit/connectors/` dir (NOTE MEMORY: keep `tests/unit/<x>` package-less — no `__init__.py` — to avoid the top-level package collision)
- [ ] `tests/unit/connectors/conftest.py` — shared async mocked-ccxt fixtures (`AsyncMock` over `watch_ohlcv`/`watch_my_trades`/`watch_orders`/`create_order`/`cancel_order`; ensure sessions closed in teardown)
- [ ] Recorded OKX-demo business-channel candle payload fixture (with `confirm`) + a full order→ack→fill payload fixture (captured once via D-09, sanitized, committed)
- [ ] `tests/integration/test_okx_smoke.py` — `pytest.mark.skipif(no creds)` opt-in live smoke

## Security Domain

> `security_enforcement` treated as enabled (no explicit `false`).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | OKX apiKey/secret/passphrase via `OkxSettings` `SecretStr`; only the connector authenticates (D-04) |
| V3 Session Management | yes | Single authenticated ccxt.pro client + native socket; sandbox isolation via `sandbox: bool` (demo keys ≠ live) |
| V6 Cryptography | yes (secret handling) | Never hand-roll signing — ccxt handles OKX HMAC request signing; `SecretStr` prevents secret leakage in logs/repr/fixtures (CONN-06) |
| V7 Error Handling / Logging | yes | Secrets never logged; live error policy is publish-and-continue (`ErrorEvent`); mask keys in any diagnostic (nautilus uses `mask_api_key`) |
| V5 Input Validation | partial | Validate venue payloads at the edge (missing `confirm`, malformed rows) before Decimal conversion |

### Known Threat Patterns for OKX/ccxt live integration
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leakage via logs/repr/committed fixtures | Information Disclosure | `SecretStr`; sanitize captured fixtures; no keys in commits (CONN-06) |
| Accidental LIVE trading believing it is demo | Tampering / Elevation | Assert connected WS URL contains `wspap` when `sandbox=True`; drive native host from the single bool (Pitfall 2) |
| Float-money corruption from ccxt edge | Tampering (data integrity) | `to_money` at every edge; string precision helpers outbound (CONN-05) |
| Unbounded reconnect / subscription storm | Denial of Service (self-inflicted, IP ban) | Respect 3 conn/s + 480 sub/hr; `enableRateLimit=True`; debounce reconnect (Phase 3/5) |

## Sources

### Primary (HIGH confidence — installed source in `.venv`)
- `ccxt/pro/okx.py` (4.5.56) — `get_url` business routing (126-127), `watch_ohlcv` (922-939), `handle_ohlcv`/subscription shape (974-983, 1024-1065), order-arm methods (`watch_orders` 1750, `watch_my_trades` 1573, `watch_balance` 1436, `watch_positions` 1619, `create_order_ws` 1966, `cancel_order_ws` 2072), test/ws urls (52-58)
- `ccxt/okx.py` (4.5.56) — `parse_ohlcv` 6-tuple drop (2529-2553), `set_sandbox_mode` header (7558-7564), urls incl. `test` (199-217)
- `ccxt/base/exchange.py` — base `set_sandbox_mode` URL swap (3223-3248)
- `ccxt/async_support/base/exchange.py` — WS `client()` options build (438-463)
- `ccxt/async_support/base/ws/client.py` — WS connect `headers=self.options.get('headers')` (300-301)
- `nautilus_trader/adapters/okx/{data.py,execution.py,factories.py,config.py}` (1.227.0) — data/exec client split, shared http client, business socket, `OKXEnvironment` LIVE/DEMO URL derivation (executed the pyo3 URL helpers)
- `itrader/connectors/base.py`, `portfolio_handler/account/{base,venue}.py`, `config/settings.py`, `core/money.py` — Phase-1 seams
- PyPI `pytest-asyncio` 1.4.0 (`Requires-Dist: pytest<10,>=8.4`); slopcheck `[OK]`

### Secondary (MEDIUM confidence — OKX docs)
- OKX v5 docs (docs-v5/en): candlesticks channel field layout + `confirm` 0/1 semantics + "1 push/sec"; demo WS `wspap.okx.com`; `x-simulated-trading` REST-only; passphrase requirement; 3 conn/s + 480 sub/hr rate limits
- OKX v5 WS URL change notice (candles → `/business`)

### Tertiary (LOW — cross-reference)
- ccxt issue #21885 (watchOHLCV drops confirm) — corroborates the source reading

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — installed ccxt 4.5.56 surface directly introspected; pytest-asyncio verified compatible + slopcheck-clean
- Architecture (D-01 split, containment): HIGH — nautilus adapter read from source; async pattern is canonical stdlib
- confirm flag behavior: HIGH on values/drop (source + docs); MEDIUM on exact intermediate push cadence (A1 — fixture will pin)
- Sandbox routing: HIGH — the D-02 header refutation is triple-verified (ccxt source + nautilus URL helpers + OKX docs)
- Pitfalls: HIGH — all engine-internal + ccxt-internal verified against source

**Research date:** 2026-07-01
**Valid until:** 2026-07-31 (ccxt moves fast; re-verify method names if the pin changes)
