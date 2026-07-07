# Phase 2: OKX Connector - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-01
**Phase:** 2-okx-connector
**Areas discussed:** Data/execution architecture (data-boundary → full decomposition), Native `confirm` escape hatch, Order-arm build depth, Offline test strategy, Sandbox usage, Secrets/env

---

## Data-arm ↔ LiveBarFeed boundary → escalated to a milestone-architecture decision

The discussion opened on where `BarEvent` is constructed, but the user pushed the
question deeper: *"can't we open the transport directly from a live feed? is the connector
supposed to stream data?"* then *"shouldn't the connector handle auth/account, used by an
okx_exchange and a price_handler data provider? I might use a 3rd-party data provider one
day."*

| Option | Description | Selected |
|--------|-------------|----------|
| Monolithic `LiveConnector` (data arm + order arm) — as LX-05 | One venue object streams data and places orders | |
| Responsibility-based decomposition | Connector = session; separate exchange (orders) + data provider (candles) + venue account (balances) as domain adapters | ✓ |

**User's choice:** Adopt the decomposition (revises LX-05). Then further refined it twice:
(1) order I/O should live in the **exchange**, not the connector; (2) the connector should
be **injected**, not imported, into the arms.
**Notes:** Driven by the principle that **data source and execution venue are independent
axes of variation**. Verified against `nautilus-trader` (installed dependency): OKX adapter
splits `OKXDataClient` / `OKXExecutionClient`. Verified OKX streams candles on a separate
`/ws/v5/business` endpoint. Net model: `OkxConnector` = shared authenticated
session/transport primitive; `OkxExchange` (execution) owns order I/O + `FillEvent`;
`OkxDataProvider` (price_handler) owns candle I/O; `VenueAccount` (portfolio) owns balances;
all injected from the `LiveTradingSystem` composition root, typed against the `LiveConnector`
session Protocol. Revises LX-05, D-10, CONN-01/02/04.

---

## Native `confirm` escape-hatch approach

| Option | Description | Selected |
|--------|-------------|----------|
| Subclass ccxt.pro okx | Override the okx handler to preserve `confirm` from the raw message | |
| Own native `business`-endpoint candle subscription | `OkxDataProvider` subscribes raw to `candle{tf}` on `/business`, full 9-field payload with `confirm` | ✓ |
| Defer to plan-time research | Lock nothing now | |

**User's choice:** Own native business-endpoint subscription.
**Notes:** Cleaner now that the data provider is its own independent client. Verified ccxt
drops `confirm` (parse_ohlcv → 6-tuple). ccxt.pro still serves the order arm. Plan-time
research confirms exact channel/field cadence.

---

## Order-arm build depth

| Option | Description | Selected |
|--------|-------------|----------|
| Fully implement now, mocked-ccxt tests | Order I/O complete in Phase 2; real sandbox in Phase 5 | ✓ |
| Thin scaffold now, complete in Phase 5 | Signatures + happy path only | |

**User's choice:** Fully implement now.
**Notes:** Order I/O lives in `OkxExchange`; the exchange emits `FillEvent` (connector emits
nothing). Formal sandbox validation stays Phase 5.

---

## Offline test strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Mocked ccxt.pro objects | Async mocks + small recorded demo fixture for `confirm` realism | ✓ |
| Recorded/replayed OKX demo fixtures | Full capture/replay | (partial — used for fixtures) |
| Hand-written fake LiveConnector | Pure in-memory fake | |

**User's choice:** Mocked ccxt primary + recorded demo fixture. `pytest-asyncio` configured
(must be added as a dependency).
**Notes:** Deterministic, CI-runnable, `filterwarnings=["error"]` green.

---

## Sandbox usage (user-initiated)

The user offered their OKX demo keys (in `.env`) and asked whether to use them for online
testing.

| Option | Description | Selected |
|--------|-------------|----------|
| Use as gating online tests | Live network in the default suite | |
| Fixture capture + opt-in `skipif` smoke test | Record real payloads; smoke test auto-skips without creds | ✓ |
| Don't use at all in Phase 2 | Defer all live use to Phase 5 | |

**User's choice:** Fixture capture + opt-in smoke test; formal validation stays Phase 5.
**Notes:** Secrets never in code/logs/fixtures; gating suite stays credential-free.

---

## Secrets / env

**User's decisions (free-text):** Added `OKX_API_PASSPHRASE` to `.env` / `.env.example`.
**No env prefix** on OKX keys — plain `OKX_API_*` (revises CONN-06's `ITRADER_OKX_*`). A real
secret manager is deferred to after this milestone.

---

## Claude's Discretion

- Exact coroutine-scheduling mechanism between adapters and the connector loop.
- Exact shape of the new `price_handler` data-provider seam that `LiveBarFeed` consumes.
- Whether the business-candle socket is fully separate vs multiplexed on the connector loop.

## Deferred Ideas

- Formal sandbox validation of the order path (reconciliation, partial fills, restart) — Phase 5.
- 3rd-party market-data provider (non-OKX candles) — enabled by the split, not built now.
- Real secret manager — post-milestone.
- `LiveBarFeed` / `BarEvent` construction / ring buffer — Phase 3.
- `VenueAccount` reconciliation logic — Phase 5.
