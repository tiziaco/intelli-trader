# Stack Research

> ## ⚠ Superseded framing — read `phases/02-okx-connector/02-CONTEXT.md` first
>
> The Phase-2 discussion (2026-07-01) revised the live architecture; this snapshot
> predates it and still describes the **two-arm `LiveConnector`** model. **Superseded
> framings** (everything else here remains valid):
> - Connector is a **session/transport primitive**, not a two-arm venue object; the data/order/account arms are **domain adapters** (`OkxDataProvider` / `OkxExchange` / `VenueAccount`), **injected** with the session, never cross-domain-imported.
> - The **`OkxExchange` adapter emits `FillEvent`** — the connector owns no operations and emits no domain events.
> - Paper needs **no connector**: the paper execution adapter implements **`AbstractExchange`** (not `LiveConnector`).
> - `OkxSettings` reads **plain `OKX_API_*` (no env prefix)** — not `ITRADER_OKX_*`; secret manager deferred post-milestone.
>
> See design-doc LX-05/LX-06 revision notes and `02-CONTEXT.md` D-01..D-10.

**Domain:** Live crypto trading (OKX, paper-first) — additions to an event-driven backtest engine
**Researched:** 2026-06-30
**Confidence:** HIGH (ccxt packaging/versions, OKX demo mechanics, asyncio bridge verified against current sources; MEDIUM on native-escape-hatch choice — a plan-time gap-list decision)

> Scope: **only the NEW stack surface for v1.7 live OKX paper-first trading.** The existing
> validated stack (Python 3.13, Poetry, `ccxt ^4.5.56` read-only providers, `websocket-client`,
> `sqlalchemy`+`psycopg2-binary`+Postgres, `msgspec`, `structlog`, `pydantic`+`pydantic-settings`,
> `uuid-utils`, Decimal money) is NOT re-researched. The headline: **almost nothing new is
> strictly required** — the live capability is mostly *activating async ccxt that you already ship*
> plus stdlib asyncio glue. Resist scope creep (libSQL-rejection precedent applies).

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `ccxt` (already pinned) | bump `^4.5.56` → `^4.5.62` (latest 4.5.62, Feb–Mar 2026) | **Live data arm + order arm** via its built-in WebSocket layer (ccxt.pro) and async REST | **ccxt.pro is already inside the free `ccxt` package** (merged at v1.95, 2022) — no separate license, no separate install, no new dependency. You already depend on ccxt for read-only providers; v1.7 just *uses its async + watch\* surface*. OKX is a first-class ccxt venue. This is the LX-05 default. |
| Python stdlib `asyncio` | stdlib (3.13) | **Async/sync bridge** — run the connector's event loop on its own daemon thread; marshal across the boundary | `asyncio.run_coroutine_threadsafe()` (sync→async commands) + `loop.call_soon_threadsafe()` (loop control) is the canonical, dependency-free pattern. Outbound (async→sync `global_queue`) is just `queue.Queue.put()` — already thread-safe. **No new library needed for the bridge.** |
| `aiohttp` | transitive via ccxt async (verify resolved ≥ 3.10) | HTTP transport for `ccxt.async_support` / `ccxt.pro` | Ships as a ccxt dependency for the async layer; confirm it resolves in `poetry.lock` rather than adding it explicitly. No direct use in our code. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` | `^1.4.0` (requires py ≥3.10 ✓) | Test `async def` connector coroutines (watch-loop parsing, ack handling, reconnect) | **Add to dev group.** Needed the moment you unit-test the connector's async edge in isolation. Configure explicitly (see "Version Compatibility" — interacts with `filterwarnings=["error"]`). |
| `python-okx` (native escape hatch candidate) | `0.4.1` (okxapi/python-okx, last upload 2026-01-08, py ≥3.7) | LX-05 native OKX v5 escape hatch for *proven* ccxt gaps only | **Do NOT add up front.** Candidate only if a concrete gap is found at Phase 2/3 plan time. Version `0.4.1` is low and the wrapper is community-maintained — treat with the **libSQL-beta caution**. Preferred escape hatch is raw `aiohttp`/`websockets` against OKX v5 (see below). |
| `janus` | `2.0.0` (py ≥3.9) | Purpose-built mixed sync↔async queue | **Probably NOT needed.** Only reach for it if you discover you need *async-side consumption* of a queue that the *sync side produces into* (the rare reverse direction). The forward path (`queue.Queue` out, `run_coroutine_threadsafe` in) covers the connector design in the sketch. Flag, don't add. |
| `redis` (py client) | `^5.x` if chosen | LX-15 inter-process command/status channel (option) | Only if the topology decision picks Redis over Postgres LISTEN/NOTIFY. **Topology is an architecture decision (out of scope here)** — inventoried below, not selected. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest-asyncio` | Async test driver | Set `asyncio_mode = "auto"` (or `"strict"`) AND `asyncio_default_fixture_loop_scope = "function"` in `[tool.pytest.ini_options]` — otherwise it emits a `PytestDeprecationWarning` that the `error` filter can escalate. Do NOT redefine the `event_loop` fixture (deprecated → future error). |
| ccxt verbose / `exchange.verbose = True` | Inspect raw OKX WS frames during connector bring-up | Use to confirm the kline **confirm flag** payload shape (LX-08) and demo-header routing without writing throwaway scripts. |

## Installation

```bash
# Core: bump the existing ccxt pin (NO new runtime dependency — ccxt.pro is in-package)
poetry add "ccxt@^4.5.62"

# Dev: async test driver
poetry add --group dev "pytest-asyncio@^1.4.0"

# DO NOT add up front (evaluate at plan time only):
#   poetry add "python-okx@0.4.1"     # native escape hatch — only on a proven gap
#   poetry add "janus@^2.0.0"         # only if reverse sync->async queue consumption is needed
#   poetry add "redis@^5"             # only if LX-15 topology picks Redis
```

`aiohttp` is pulled transitively by ccxt's async layer — verify it lands in `poetry.lock`; do not pin it directly.

---

## The six questions, answered

### 1. ccxt.pro packaging + OKX surface (LX-05)
- **Packaging: definitively merged.** ccxt.pro is a **free part of the unified `ccxt` package** since v1.95 (2022). There is **no separate package, no separate install, no license key.** Confirmed against ccxt issue #15171 and the PyPI/docs current pages. The CLAUDE.md note that ccxt is "used today only as read-only providers" is an *internal usage* fact, not a packaging limit — the async + WS surface is already shipped in the wheel you have.
- **Import structure (Python):**
  - `import ccxt.pro as ccxtpro` — the **WebSocket** layer (`watch_*` streaming methods).
  - `import ccxt.async_support as ccxt` — **async REST** (awaitable `create_order`, `fetch_ohlcv`, `fetch_balance`).
  - `import ccxt` — the legacy **sync REST** layer (what `ccxt_provider.py` uses today).
- **OKX WS method support (LX-05 data + order arms):** OKX supports `watch_ohlcv` (data arm), and the private streams `watch_orders`, `watch_balance`, `watch_my_trades`, `watch_positions`. Order placement: `create_order` (async REST) and `create_order_ws` (`createOrderWs`, same signature, over WS). `create_order_ws` is an optional optimization — start with async-REST `create_order` + `watch_orders` for the fill stream.
- **Native escape hatch (LX-05):** the leanest escape hatch is **raw `aiohttp` (REST) + `websockets`/the ccxt-bundled WS client against the OKX v5 API directly** — both transports already ride in via ccxt, so no new dep. The packaged `python-okx 0.4.1` SDK is a *candidate* but is low-version + community-maintained (libSQL-caution); `okx-sdk` (burakoner, 5.5.812) is more complete but is a second third-party surface. **Recommendation: keep the escape hatch as thin hand-rolled v5 calls behind `LiveConnector`, add a native SDK only if a concrete, proven gap justifies it** at Phase 2/3 plan time.

### 2. asyncio bridge
- **Best practice (verified, dependency-free):** connector owns a `loop = asyncio.new_event_loop()` on a **daemon thread**; `run_coroutine_threadsafe(coro, loop)` to submit work *into* the loop from the sync engine; `loop.call_soon_threadsafe(loop.stop)` for graceful shutdown, then `thread.join()`. Outbound async→sync is `global_queue.put(event)` (stdlib `queue.Queue` is thread-safe). This keeps the async boundary "bottled at the connector edge" exactly as the sketch requires.
- **No version-pinned dep required.** `janus 2.0.0` exists for the harder sync↔async-queue case but is **not needed** for this topology — flag it, don't add it.

### 3. OKX sandbox/demo (single `sandbox: bool`)
- **ccxt path:** `exchange.set_sandbox_mode(True)` routes OKX to demo endpoints. For OKX, demo also requires the **`x-simulated-trading: 1` HTTP header**; modern ccxt sets this for OKX when sandbox mode is on, but the header is the underlying mechanism — confirm it is applied on **both REST and WS** during bring-up (historical ccxt issues show drift here).
- **Native path:** set `headers = {"x-simulated-trading": "1"}` and use the demo base URLs / WS URLs.
- **Demo requires demo-specific API keys** (created in OKX → Demo Trading), distinct from live keys.
- **Single-flag routing (LX-05):** one `sandbox: bool` on the connector config should (a) call `set_sandbox_mode(sandbox)` on the ccxt instance AND (b) inject the `x-simulated-trading` header on any native call AND (c) select the sandbox-vs-live **key set**. No split-brain — one flag, three effects.

### 4. Secrets (OKX needs THREE)
- **OKX auth = apiKey + secret + passphrase** (the "password" in ccxt's config is the OKX **passphrase**). Confirmed. This is unlike key+secret-only venues — the passphrase is mandatory.
- **Best practice: env-only via the existing `pydantic-settings` `ITRADER_` pattern.** Add a dedicated `OkxSettings(BaseSettings)` mirroring `SqlSettings` (`itrader/config/sql.py`): `env_prefix="ITRADER_OKX_"`, all three credentials as `SecretStr | None`, a `sandbox: bool` field, and a `model_validator` that **fails loud** when live (sandbox=False) is selected without all three creds — the exact "no working secret defaults" discipline already proven in `sql.py`. Keys never in code; sandbox vs live keys separated by the single `sandbox` flag (LX-05 cross-cutting §5).

### 5. Runtime topology IPC channels (LX-15) — INVENTORY ONLY (do not pick)
| Channel | New dep? | Pros | Cons |
|---------|----------|------|------|
| **Postgres `LISTEN/NOTIFY`** (via existing `psycopg2`) | **None** — you already ship `psycopg2-binary` + Postgres (v1.6 store) | Reuses the v1.6 system-of-record as the shared truth; zero new infra; transactional with the state writes; "exactly what v1.6's durable store was built to enable" | NOTIFY payload ≤ 8 KB; not a durable queue (missed while disconnected unless paired with a polled table); LISTEN needs a dedicated connection/poll loop |
| **Redis** (pub/sub or streams) | `redis` py client + a Redis server | Low-latency; mature pub/sub + durable Streams; natural fit for fan-out | New infra component + new dep + new ops surface; second source of truth alongside Postgres |
| **Message broker** (RabbitMQ / NATS) | heavy client + broker | Strong delivery semantics, routing | Heaviest ops/dep footprint; overkill for a single-venue, few-process deployment |
- **Lean read:** the Postgres LISTEN/NOTIFY option adds **zero dependencies** and reuses v1.6 — it is the obvious low-cost default *if* a separate-process topology (LX-15 option b/c) is chosen. **But the topology choice itself is an architecture decision and is out of scope here.**

### 6. Testing libs + `filterwarnings=["error"]` interaction
- **`pytest-asyncio ^1.4.0`** (py ≥3.10 ✓ for 3.13) is the standard async test driver.
- **Strictness interaction (the gotcha):** the existing `[tool.pytest.ini_options]` has `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`. pytest-asyncio emits a `PytestDeprecationWarning` if `asyncio_default_fixture_loop_scope` is unset. `PytestDeprecationWarning` subclasses `pytest.PytestWarning` (→ `UserWarning`) **and** `DeprecationWarning` — your current ignores *may* absorb it, but **do not rely on that.** Set both config knobs explicitly:
  ```toml
  asyncio_mode = "auto"                          # or "strict"
  asyncio_default_fixture_loop_scope = "function"
  ```
- **Do NOT redefine the `event_loop` fixture** — that override path is deprecated and slated to become a hard error; use the `scope=` arg on the asyncio marker or the `event_loop_policy` fixture instead.
- Async network code tends to leak `ResourceWarning`/unclosed-session warnings; under `error` these fail the suite. Ensure connector teardown `await exchange.close()` in fixtures, and prefer **mocked transports** for unit tests (real OKX sandbox I/O belongs in `integration`/`e2e`, not unit).

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| ccxt.pro (in-package) for OKX | `python-okx 0.4.1` native SDK | Only if a concrete OKX-fidelity gap in ccxt is proven at plan time (e.g. kline confirm-flag unreliability, order-status field loss). Wrap behind `LiveConnector` either way. |
| Hand-rolled v5 native escape hatch (`aiohttp`/`websockets`) | `okx-sdk 5.5.812` (burakoner) | If the native surface needed is large enough that hand-rolling is more error-prone than a maintained SDK — but that adds a third-party trust + dep surface; bias toward thin hand-rolled. |
| stdlib `run_coroutine_threadsafe` bridge | `janus 2.0.0` | Only if you need the async side to *consume* from a queue the sync side *produces into* (reverse of the sketch's flow). |
| Postgres LISTEN/NOTIFY (no dep) | Redis / broker | If/when a separate-process topology needs durable fan-out beyond NOTIFY's 8 KB transient payload, or sub-ms latency. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| A separate "ccxtpro" package install or license | ccxt.pro merged into free `ccxt` in 2022 — a separate package is stale/wrong | `import ccxt.pro as ccxtpro` from the `ccxt` you already have |
| `python-okx 0.4.1` as a *default* dependency | Low version + community-maintained; mirrors the libSQL beta-driver rejection (v1.6 Q2) — adds risk for capability you mostly already have in ccxt | ccxt.pro by default; native escape hatch only on a proven, documented gap |
| `websocket-client` (the v1.6 Binance streamer) for OKX | Sync, callback-style, quarantined D-live module; mixing it with the async connector splits the transport model | ccxt.pro async `watch_*` on the connector's asyncio loop |
| `asyncio.get_event_loop()` / redefining `event_loop` test fixture | Deprecated patterns; will hard-error in future asyncio/pytest-asyncio | `asyncio.new_event_loop()` on the daemon thread; `asyncio_default_fixture_loop_scope` config |
| Adding `aiohttp` explicitly | It arrives transitively with ccxt async; an explicit pin risks version drift against ccxt's expectation | Let ccxt resolve it; just verify the lockfile |

## Stack Patterns by Variant

**If staying paper-first (the DoD, Phases 1–4):**
- You need **only the ccxt bump + the asyncio-bridge (stdlib) + pytest-asyncio**. The `PaperConnector` reuses the pure `MatchingEngine` (LX-06); it consumes the connector's **data arm** (`watch_ohlcv`) only. No order-arm creds, no secrets module strictly required until Phase 5.

**If advancing to the real/sandbox path (Phase 5):**
- Add the **OkxSettings secrets module** (3 creds + sandbox flag) and exercise the **order arm** (`create_order` + `watch_orders`/`watch_balance`/`watch_positions`) against OKX **demo** first.

**If a separate-process runtime topology is chosen (LX-15, b/c):**
- Default to **Postgres LISTEN/NOTIFY** (zero new dep, reuses v1.6) before reaching for Redis/broker.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `ccxt 4.5.62` | Python 3.13 ✓ | ccxt does not pin `requires_python`; 4.5.x supports 3.13. Bump is a minor within your existing `^4.5` range — low risk. |
| `ccxt.pro` (in-package) | `aiohttp` (transitive) | The async/WS layer needs aiohttp; verify it's resolved in `poetry.lock` after the bump. |
| `pytest-asyncio 1.4.0` | pytest `^9.0.3` (dev), Python 3.13 ✓ | requires py ≥3.10. **Requires** explicit `asyncio_mode` + `asyncio_default_fixture_loop_scope` to coexist with `filterwarnings=["error"]`. |
| `python-okx 0.4.1` (if added) | py ≥3.7 | Low version; community wrapper — libSQL-caution. Pin exact, behind `LiveConnector`. |
| `janus 2.0.0` (if added) | py ≥3.9 | `aclose()` required on shutdown or it emits errors. |

## Integration Points With Existing Code

- **`itrader/price_handler/providers/ccxt_provider.py`** — the symbol-formatting (`BTC/USDT` ↔ `BTCUSDT`), market loading, and OHLCV→Decimal `Bar` conversion logic is reusable. The new live connector is a *new seam* (data arm + order arm), not an edit of this read-only provider; mine it for symbol/format helpers and the `fetch_ohlcv` warmup-backfill call (LX-09 REST `fetch_ohlcv` for warmup).
- **`itrader/price_handler/providers/binance_stream.py`** — the **quarantined D-live** sync `websocket-client` streamer. Its `msg['k']['x']` closed-bar gate is the *concept* mirror for OKX's confirm flag (LX-08), but **replace it, don't extend it** — OKX uses async ccxt.pro, not the sync callback model.
- **`itrader/config/sql.py`** (`SqlSettings`) — the **template for the new `OkxSettings`**: `env_prefix`, `SecretStr` fields, driver-conditional fail-loud `model_validator`, `extra="forbid"`. Clone this pattern for `ITRADER_OKX_*` (key/secret/passphrase/sandbox).
- **`itrader/config/settings.py`** — keep OKX creds OUT of the general `Settings` (mirror how DB creds moved to their own `SqlSettings`); a dedicated `OkxSettings` keeps the backtest path credential-free and env-tolerant.
- **`pyproject.toml [tool.mypy]`** — `ccxt.*` is already `ignore_missing_imports`; `live_trading_system`/`trading_interface`/`binance_stream` are already `ignore_errors`. New live code should target **strict-clean** (DoD §4); add per-module overrides only where a third-party stubless surface forces it, not as a blanket.

## Sources

- https://github.com/ccxt/ccxt/issues/15171 — "CCXT Pro Websockets merged with CCXT" (packaging, free, in-package) — HIGH
- https://docs.ccxt.com/ and https://docs.ccxt.com/docs/pro-manual — ccxt.pro manual, `watch_*` + `createOrderWs`, `import ccxt.pro as ccxtpro` — HIGH
- https://pypi.org/project/ccxt/ — ccxt 4.5.62 latest (verified via PyPI JSON API) — HIGH
- https://www.okx.com/en-us/help/api-faq + https://app.okx.com/docs-v5/en/ — OKX demo trading, `x-simulated-trading: 1` header, passphrase requirement — HIGH
- https://github.com/ccxt/ccxt/issues/11923, /11855, /17295 — OKX `set_sandbox_mode` + demo header + WS demo caveats — MEDIUM (issue threads, version-drift cautions)
- https://docs.python.org/3/library/asyncio-task.html#asyncio.run_coroutine_threadsafe + https://github.com/aio-libs/janus — asyncio cross-thread bridge + janus — HIGH
- https://pypi.org/project/python-okx/ (0.4.1, 2026-01-08), https://github.com/burakoner/okx-sdk (5.5.812) — native escape-hatch candidates — MEDIUM
- https://pypi.org/project/pytest-asyncio/ (1.4.0) + https://pytest-asyncio.readthedocs.io/ — async test driver + loop-scope/event_loop deprecation under strict warnings — HIGH
- https://pypi.org/project/janus/ (2.0.0) — sync↔async queue (flagged, not recommended) — HIGH

---
*Stack research for: live crypto trading (OKX, paper-first) additions to the iTrader backtest engine*
*Researched: 2026-06-30*
