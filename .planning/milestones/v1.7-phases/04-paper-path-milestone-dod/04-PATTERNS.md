# Phase 04: paper-path-milestone-dod - Pattern Map

**Mapped:** 2026-07-02
**Files analyzed:** 4 (2 NEW, 1 NEW test, 1 MODIFIED wiring)
**Analogs found:** 4 / 4

> This phase is a brownfield REUSE phase: the paper exchange is `SimulatedExchange`
> as-is (D-04), so there is NO new exchange/adapter class. The genuinely new surface
> is (1) a replay/fake data provider, (2) a runnable worker entrypoint, (3) a
> paper-parity integration test, and (4) a small amount of paper-path wiring inside
> the already-half-wired `LiveTradingSystem`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/price_handler/providers/replay_provider.py` (NEW, name at discretion) | provider | streaming / file-I/O (CSV → confirm-gated `ClosedBar` push) | `itrader/price_handler/providers/okx_provider.py` | role+flow exact (mimics the same `set_bar_sink`/`ClosedBar` seam) |
| `scripts/run_live_paper.py` (NEW, name at discretion — D-08) | entrypoint / composition-root driver | request-response (start/stop/status lifecycle) | `scripts/run_backtest.py` + `LiveTradingSystem.start/stop/get_status` | role-match (driver script) |
| `tests/integration/test_paper_parity.py` (NEW) | test | batch / transform (run both paths, frame-equal diff) | `tests/integration/test_backtest_oracle.py` + `tests/integration/_oracle_harness.py` | role+flow exact (same no-tolerance frame diff) |
| `itrader/trading_system/live_trading_system.py` (MODIFIED — paper wiring, D-02/D-09) | composition root | event-driven wiring | itself (existing OKX arm at 268-305; `'simulated'` at 198/414-416; `LiveBarFeed` at 143-144) | in-file extension |

## Pattern Assignments

### `itrader/price_handler/providers/replay_provider.py` (provider, streaming/file-I/O) — NEW

**Analog:** `itrader/price_handler/providers/okx_provider.py`

**Indentation:** 4 SPACES (match the analog — the whole `providers/`+`feed/` tree is 4-space; the note at okx_provider.py:41-42 is explicit).

**Why this analog:** D-02 requires an object that produces "the same `BarEvent`s an `OkxDataProvider` would" by pushing golden-CSV rows as confirm-gated `ClosedBar` dicts through the SAME `set_bar_sink` → `LiveBarFeed.update()` seam. The replay provider must be a drop-in for `OkxDataProvider` on the two methods `LiveTradingSystem` and `LiveBarFeed` actually call: `set_bar_sink(sink)` and (for warmup) `fetch_ohlcv_backfill(...)`.

**Contract to reproduce (the seam `LiveBarFeed`/`LiveTradingSystem` depend on):**
- `set_bar_sink(sink: Callable[[ClosedBar], None]) -> None` — okx_provider.py:160-166. The feed registers `self.feed.update` as the sink (live_trading_system.py:305).
- `fetch_ohlcv_backfill(symbol, timeframe, since=None, limit=...) -> list[ClosedBar]` — okx_provider.py:263-307. `LiveBarFeed.warmup()` (live_bar_feed.py:187-213) calls this and replays each bar one-by-one through `update()`. The replay provider must return golden bars here too (warmup is what makes indicators warm — RESEARCH Pitfall 1).
- The confirm gate is ALREADY satisfied by construction: the replay provider only ever emits completed rows, so it hands each row straight to the sink (no `confirm != "1"` drop needed). This is the analog of okx_provider.py `_hand_closed_bar` (168-174).

**The `ClosedBar` TypedDict to build** (okx_provider.py:61-77 — reuse this exact type, do not redefine):
```python
class ClosedBar(TypedDict):
    ts: int            # venue bar-OPEN ms (business time — NEVER wall-clock)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    symbol: str        # routing key — stamp from provider config, not the row
    timeframe: str     # routing key
```

**Decimal-edge pattern to copy verbatim** (okx_provider.py:242-254) — every numeric CSV cell crosses via `to_money(str(x))`, NEVER `Decimal(float)` and NEVER a bulk float cast of the frame:
```python
from itrader.core.money import to_money
closed: ClosedBar = {
    "ts": int(row_ts_ms),
    "open": to_money(str(row_open)),
    "high": to_money(str(row_high)),
    "low": to_money(str(row_low)),
    "close": to_money(str(row_close)),
    "volume": to_money(str(row_volume)),
    "symbol": self._symbol,       # D-12: from trusted provider config, not the CSV cell
    "timeframe": self._timeframe,
}
```

**Business-time stamping (D-09):** `ts` MUST be the CSV bar-OPEN timestamp in ms, kept verbatim — never `datetime.now()`. The golden CSV index is a tz-aware `DatetimeIndex` named `date` (csv_store.py:82-83, 126-127); convert each index value to epoch-ms for `ts`. `LiveBarFeed.update()` rebuilds `pd.Timestamp(closed_bar["ts"], unit="ms", tz="UTC")` (live_bar_feed.py:163), so the ms round-trip must land exactly on the backtest bar-open grid for parity to hold.

**CSV source:** load `data/BTCUSD_1d_ohlcv_2018_2026.csv` the SAME way the backtest does — reuse `CsvPriceStore` (`store.read_bars("BTCUSD")` → canonical tz-aware float64 OHLCV frame, csv_store.py:71-94) rather than re-parsing the raw Binance-kline header. Iterating that frame's rows guarantees identical row set/order/values to the backtest (the parity anchor, D-01). The float64 store values re-cross the Decimal edge via `to_money(str(...))` at push time (matching how the backtest's `Bar.from_row` enters Decimal).

**Constructor / DI pattern** (okx_provider.py:113-137) — bind config in `__init__`, register no sink there; keep symbol/timeframe as the trusted stamping source:
```python
def __init__(self, store_or_frame, symbol: str, timeframe: str) -> None:
    self.logger = get_itrader_logger().bind(component="ReplayDataProvider")
    self._symbol = symbol
    self._timeframe = timeframe
    self._bar_sink: Callable[[ClosedBar], None] | None = None
```

**Drive method (NEW, no OKX analog — replaces the async `_stream_candles` loop):** a SYNCHRONOUS in-thread for-loop (D-03) that iterates the golden rows and calls `self._bar_sink(closed_bar)` for each — no asyncio, no `connector.spawn`, no aiohttp. This is the deliberate divergence from okx_provider.py:191-217 (`_stream_candles`). Keep the drop-and-log guard for an unregistered sink (okx_provider.py:168-174).

---

### `scripts/run_live_paper.py` (entrypoint driver, request-response) — NEW (D-08)

**Analog:** `scripts/run_backtest.py::main` (the composition + run + read-result-state shape) and `LiveTradingSystem.start/stop/get_status` (the lifecycle surface).

**Indentation:** 4 SPACES (match `run_backtest.py`).

**Why this analog:** D-08 asks for a standalone bootstrap that constructs `LiveTradingSystem`, runs the live-paper engine with clean start/stop/status, and is runnable two ways (replay provider offline; real `OkxDataProvider` manual smoke). `run_backtest.py::main` is the reference "construct system → add strategy → add portfolio → run → read result state after the run" driver.

**Module-docstring + pinned-config pattern to copy** (run_backtest.py:1-62): open with a triple-quoted docstring citing the decisions it pins (D-02/D-08/D-09), then module-level constants for dataset/window/cash/ticker/timeframe. Reuse the SAME golden literals so the smoke run is comparable:
```python
DATASET = "data/BTCUSD_1d_ohlcv_2018_2026.csv"
CASH = 10_000
TICKER = "BTCUSD"          # NOTE the symbol-form gotcha below
TIMEFRAME = "1d"
```

**Strategy + portfolio construction pattern** (run_backtest.py:80-95) — copy verbatim (the parity anchor requires identical strategy params):
```python
strategy = SMAMACDStrategy(
    timeframe=TIMEFRAME,
    tickers=[TICKER],
    sizing_policy=FractionOfCash(Decimal("0.95")),
    direction=TradingDirection.LONG_ONLY,
    allow_increase=False,
)
system.strategies_handler.add_strategy(strategy)
portfolio_id = system.portfolio_handler.add_portfolio(name="paper_pf", exchange="simulated", cash=CASH)
strategy.subscribe_portfolio(portfolio_id)
```

**Lifecycle surface to drive** (live_trading_system.py:528-682): `system.start()` (528) → drive bars → `system.stop(timeout=...)` (582) → `system.get_status()` (651). `start()` returns `True`/`False` (not raising); `stop()` returns `True`/`False` and joins the daemon thread. For the OFFLINE replay run, the worker pushes bars synchronously (D-03); for the real-OKX smoke run it lets the daemon-thread stream drive (live_trading_system.py:558-560).

**Read-result-state-after-run pattern** (run_backtest.py:102-119, queue-only rule): after the run, read `system.portfolio_handler.get_portfolio(portfolio_id)` and build frames with `build_trade_log(portfolio)` / `build_equity_curve(portfolio)` from `itrader.reporting.frames`. `LiveTradingSystem` exposes the SAME `portfolio_handler` accessor, so this transfers directly.

**Symbol-form gotcha (load-bearing):** `LiveTradingSystem` hard-codes `_OKX_STREAM_SYMBOL = "BTC/USDT"` / `_OKX_STREAM_TIMEFRAME = "1d"` (live_trading_system.py:44-45) and asserts the streamed symbol is a universe member at wiring time (live_trading_system.py:445-454, OKX arm only). The golden universe ticker is `BTCUSD` (run_backtest.py:58). For the paper replay path the replay provider must stamp the SAME ticker string the strategy's `window()` queries (`BTCUSD`) into `ClosedBar["symbol"]`, or `LiveBarFeed._find_ring` raises `MissingPriceDataError` at the first `window()` (live_bar_feed.py:437-443). The replay provider's stream symbol is plan-time config — align it to the universe member, do NOT reuse `_OKX_STREAM_SYMBOL="BTC/USDT"`.

---

### `tests/integration/test_paper_parity.py` (test, batch/transform) — NEW (D-01/D-03)

**Analog:** `tests/integration/test_backtest_oracle.py` + `tests/integration/_oracle_harness.py`

**Indentation:** 4 SPACES (tests house style — `_oracle_harness.py:9`).

**Why this analog:** D-01 re-anchors the gate to "paper output == a FRESH backtest run on the same data, frame-equal, no tolerance" — NOT pinned to the frozen `46189…` artifact. `test_backtest_oracle.py` already implements the exact no-tolerance frame-diff mechanic; the parity test swaps "committed golden CSVs" for "a fresh live-paper run's output" as the comparand. Both sides run in the same test (D-01).

**Markers:** NONE hand-added — the `tests/integration/` path auto-applies `integration` + type marker via root conftest (test_backtest_oracle.py:15-17). If made network/opt-in for the real-OKX smoke, use `@pytest.mark.slow` (D-11) — `slow` is one of the four declared markers.

**Frame-equal no-tolerance diff pattern to copy** (test_backtest_oracle.py:146-163) — this is the load-bearing mechanic:
```python
import pandas.testing as pdt
pdt.assert_frame_equal(
    paper_trades_sorted[_TRADE_IDENTITY_COLUMNS],
    backtest_trades_sorted[_TRADE_IDENTITY_COLUMNS],
    check_exact=True,      # D-01: no tolerance
    check_like=True,
)
```
Sort both frames on the trade key before comparing (test_backtest_oracle.py:117-123):
```python
_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]
_EQUITY_KEY_COLUMNS = ["timestamp", "total_equity"]
# .sort_values(...).reset_index(drop=True) on BOTH sides
```

**Fresh-backtest comparand** (test_backtest_oracle.py:76-84 + `_oracle_harness.load_run_backtest_module`): the analog imports `scripts/run_backtest.py::main` via the shared importlib loader and runs it in-process. The parity test's Claude's-discretion choice (D-01 note): either (a) reuse `_oracle_harness.load_run_backtest_module` to run the backtest side and diff its `output/` against the live-paper output, or (b) construct both `BacktestTradingSystem` and the paper `LiveTradingSystem` in-test and diff their post-run frames directly. Option (b) avoids the `output/` file round-trip and is cleaner for "both in the same test"; either compares live-paper vs a fresh backtest.

**Frame-building for BOTH sides:** build `trades`/`equity` from each system's portfolio via `build_trade_log` / `build_equity_curve` (run_backtest.py:104-105) so the two DataFrames share columns and the `pdt.assert_frame_equal` diff is apples-to-apples.

**Do NOT diff against `tests/golden/`** (the key D-01 change vs the analog): the analog loads `golden_dir / "trades.csv"` (test_backtest_oracle.py:110-113); the parity test replaces that comparand with a fresh live-paper run so it survives a future backtest-loop rework without a re-freeze.

---

### `itrader/trading_system/live_trading_system.py` (composition root) — MODIFIED (D-02/D-04/D-06/D-09)

**Analog:** the file itself — the OKX arm (lines 268-305) is the template for wiring a provider into the feed; the `'simulated'` exchange (198, 414-416) and `LiveBarFeed` (143-144) are already present.

**Indentation:** 4 SPACES (this file is spaces, confirmed — match it).

**Already wired (REUSE as-is, D-04/D-06):**
- `'simulated'` exchange constructed inside `ExecutionHandler` and fetched at live_trading_system.py:198; universe injected at 414-416 (`simulated_exchange.set_universe(universe)`). `ExecutionHandler.on_order` routes by `event.exchange` and fans `on_market_data` over `self.exchanges.items()` — feed-agnostic, so `LiveBarFeed`'s `BarEvent`s already reach it. No change needed to make the paper exchange fill.
- `LiveBarFeed` constructed provider-less at 143-144; `set_provider` + `set_bar_sink` seam wired for OKX at 302-305.
- Account-free exchange (D-06): the paper exchange holds no `Account`; fills flow `FillEvent → PortfolioHandler.on_fill`. No change.

**Pattern to copy for the replay arm** (mirror the OKX arm at live_trading_system.py:291-305, but synchronous/offline): construct the replay provider, inject it into the feed via the PUBLIC setter, and wire its sink to `self.feed.update`:
```python
self.feed.set_provider(replay_provider)          # writes self._provider (warmup path reads it)
replay_provider.set_bar_sink(self.feed.update)   # each ClosedBar → feed.update() → BarEvent
```
Note the setter discipline (live_bar_feed.py:106-115): use `set_provider(...)`, NEVER `self.feed.provider = ...` (a bare attr leaves `self._provider` None → AttributeError at warmup).

**Determinism threading (D-09):** the seeded `random.Random` already lives inside `ExecutionHandler` (`_rng_seed` from `config.performance.rng_seed` default 42, execution_handler.py:56-63) and is injected into `SimulatedExchange(rng=...)`. Because the paper path reuses the SAME `ExecutionHandler`/`SimulatedExchange`, the RNG is threaded identically to backtest by construction — no new seam. The `BacktestClock` on the backtest side is staged-but-domain-inert (compose.py:166-169: "no domain consumer yet — result determinism comes from passing bar time explicitly"), and `LiveBarFeed` stamps bar-open `time` from the venue/CSV `ts` (live_bar_feed.py:163), never wall-clock — so paper reproduces backtest time by construction. Exact clock-injection point is plan-time detail (D-09).

**Inertness constraint (D-12):** keep the replay-provider import LAZY inside `__init__` (mirror the OKX lazy-import block at live_trading_system.py:273-277 and the LiveBarFeed lazy import at 143) so the BACKTEST import path never pulls it — the recurring milestone inertness gate (`tests/integration/test_okx_inertness.py`).

## Shared Patterns

### Decimal edge (money correctness)
**Source:** `itrader/core/money.py::to_money`; canonical usage okx_provider.py:242-254
**Apply to:** the replay provider (every CSV numeric cell)
Enter Decimal ONLY via `to_money(str(x))`. Never `Decimal(float)`, never a bulk float cast of the frame. `ClosedBar` OHLCV are already Decimal when they reach `LiveBarFeed._build_bar` (live_bar_feed.py:128-135) — the feed does NOT re-cast.

### Business-time stamping (determinism, D-09)
**Source:** okx_provider.py:29-30, 243; `Bar` (core/bar.py:30-50, `time: datetime` = bar-open); live_bar_feed.py:163
**Apply to:** replay provider (`ts` = CSV bar-open ms), worker entrypoint
`ts` is the venue/CSV bar-OPEN timestamp in ms, verbatim — never `datetime.now()`. The whole parity chain (D-01) depends on paper bars landing on the same open-time grid as backtest bars.

### Provider→feed seam (D-02)
**Source:** okx_provider.py:160-174 (`set_bar_sink`/`_hand_closed_bar`); live_bar_feed.py:106-115 (`set_provider`), :139-183 (`update`)
**Apply to:** replay provider, live_trading_system wiring
The provider hands raw `ClosedBar` dicts; the feed owns `BarEvent` construction, the ring, and the monotonic guard. Wire `set_bar_sink(self.feed.update)` and inject via `set_provider(...)`.

### Composition-root DI + lazy inert imports (D-12)
**Source:** live_trading_system.py:143 (lazy LiveBarFeed), :273-305 (lazy OKX arm); CLAUDE.md queue-only + DI-at-root convention
**Apply to:** live_trading_system paper wiring, worker entrypoint
Construct with `global_queue`; wire at the root; keep live/replay imports lazy so the backtest hot path stays inert. Components emit events, never call across domains.

### No-tolerance frame diff (parity assertion, D-01)
**Source:** test_backtest_oracle.py:146-163, 197-213; sort keys :39-40
**Apply to:** the paper-parity test
`pdt.assert_frame_equal(..., check_exact=True, check_like=True)` on identity columns after `.sort_values(...).reset_index(drop=True)` on both sides.

### Read-result-state-after-run (queue-only rule)
**Source:** run_backtest.py:102-119; live_trading_system.py:695-710 (`get_signal_records`/`get_signal_store`)
**Apply to:** worker entrypoint, parity test
Read `portfolio_handler.get_portfolio(id)` AFTER the run and build frames via `itrader.reporting.frames`. Never call handler methods across domains during the run.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Every new file has a strong existing analog. The only piece with NO analog is the replay provider's *synchronous in-thread drive loop* (D-03) — it deliberately DIVERGES from okx_provider.py's async `_stream_candles` (191-217); the rest of that provider (seam, Decimal edge, `ClosedBar`, DI) is copied. |

## Metadata

**Analog search scope:** `itrader/price_handler/providers/`, `itrader/price_handler/feed/`, `itrader/trading_system/`, `itrader/execution_handler/exchanges/`, `scripts/`, `tests/integration/`, `itrader/core/`
**Files scanned:** ~12 (okx_provider, run_backtest, test_backtest_oracle, _oracle_harness, live_bar_feed, live_trading_system, simulated exchange, execution_handler, compose, backtest_trading_system, csv_store, core/bar, core/clock)
**Pattern extraction date:** 2026-07-02
