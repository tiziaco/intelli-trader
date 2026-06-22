"""Hardened ONE-SHOT Binance 5m OHLCV fetch (PERF-BASELINE spike, Step 1, §7).

This is a documented one-shot kept in-repo (re-runnable), NOT on the engine run
path. Its OUTPUT is the durable artifact: four committed ``data/{SYMBOL}_5m.csv``
files in the EXACT Binance-kline schema ``CsvPriceStore`` parses.

Why not ``ccxt_provider.download_data`` (RECON §8 / spike §7 — confirmed defects):
- ``end_date`` is ignored (always start->now),
- ``resample().ffill()`` fabricates flat O=H=L=C bars over gaps,
- the unclosed last candle is appended,
- no rate-limit / backoff and download exceptions are uncaught,
- output schema (5-col) != CsvPriceStore input (12-col Binance-kline).

This script instead uses ``ccxt`` directly with: ``enableRateLimit=True`` +
try/except exponential backoff; explicit ``since``->``end`` bound; dedup by
timestamp (keep first, strictly-monotonic index); DROP the last (unclosed)
candle; NO ffill / NO resample (real gaps are preserved as missing rows); and
writes the exact kline header the existing ``data/BTCUSD_1d_ohlcv_2018_2026.csv``
uses (so ``pd.to_datetime(..., utc=True)`` parses ``Open time`` / ``Close time``).

The six load-bearing columns (``Open time, Open, High, Low, Close, Volume``)
carry the real ccxt values; the columns the store discards (``Close time``,
``Quote asset volume``, ``Number of trades``, ``Taker buy *``, ``Ignore``) are
filled with derived/zero placeholders.

Usage (run on the MAIN tree — live network I/O):

    poetry run python evals/tools/fetch_binance_5m.py --days 180
"""

import argparse
import time
from pathlib import Path

import ccxt
import pandas as pd

# Symbol -> output filename stem (strip the slash; USDT pairs throughout, kept
# distinct from the golden BTCUSD oracle set which stays untouched).
_SYMBOLS: dict[str, str] = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "SOL/USDT": "SOLUSDT",
    "BNB/USDT": "BNBUSDT",
}

_TIMEFRAME = "5m"
_TIMEFRAME_MS = 5 * 60 * 1000
_PAGE_LIMIT = 1000

# The exact 12-column Binance-kline header the existing golden CSV uses.
_KLINE_HEADER = [
    "Open time", "Open", "High", "Low", "Close", "Volume",
    "Close time", "Quote asset volume", "Number of trades",
    "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore",
]

# Datetime format matching the existing file: "2018-01-01 00:00:00.000000 UTC".
_DT_FORMAT = "%Y-%m-%d %H:%M:%S.%f UTC"

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _fmt_time(ms: int) -> str:
    """Format a ms-epoch timestamp as the '... UTC' string the store parses."""
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime(_DT_FORMAT)


def _fetch_one(exchange: ccxt.Exchange, symbol: str, since: int, end: int,
               max_retries: int = 5) -> list[list[float]]:
    """Page ``fetch_ohlcv`` from ``since`` to ``end`` with backoff (spike §7).

    Advances the cursor to ``last_ts + timeframe`` each page. Each network call
    is wrapped in try/except with exponential backoff so a transient error does
    not crash a long pull. Stops on an empty page or when the cursor passes
    ``end``.
    """
    rows: list[list[float]] = []
    cursor = since
    while cursor < end:
        page: list[list[float]] | None = None
        for attempt in range(max_retries):
            try:
                page = exchange.fetch_ohlcv(
                    symbol, _TIMEFRAME, since=cursor, limit=_PAGE_LIMIT)
                break
            except Exception as exc:  # noqa: BLE001 — transient network errors
                backoff = 2 ** attempt
                print(f"  [{symbol}] fetch error (attempt {attempt + 1}/"
                      f"{max_retries}): {exc!r} — retrying in {backoff}s")
                time.sleep(backoff)
        if page is None:
            raise RuntimeError(
                f"[{symbol}] exhausted {max_retries} retries at cursor {cursor}")
        if not page:
            break
        rows.extend(page)
        last_ts = int(page[-1][0])
        # Advance past the last returned candle; guard against a non-advancing
        # cursor (a page that only returns the boundary candle) -> infinite loop.
        next_cursor = last_ts + _TIMEFRAME_MS
        if next_cursor <= cursor:
            next_cursor = cursor + _TIMEFRAME_MS
        cursor = next_cursor
        print(f"  [{symbol}] {len(rows)} bars, cursor -> {_fmt_time(cursor)}")
    return rows


def _to_kline_frame(rows: list[list[float]], now_ms: int) -> pd.DataFrame:
    """Build the 12-column kline frame: dedup, monotonic, drop unclosed last.

    ccxt rows are ``[ms, open, high, low, close, volume]``. We dedup by the
    open-time ms (keep first), sort strictly ascending, drop the final candle
    whose close-time has not elapsed (unclosed), and synthesize the store-ignored
    columns. NO ffill / NO resample — real gaps remain as missing rows.
    """
    if not rows:
        raise RuntimeError("no rows fetched — refusing to write an empty CSV")

    df = pd.DataFrame(
        rows, columns=["ms", "open", "high", "low", "close", "volume"])
    df["ms"] = df["ms"].astype("int64")
    # Dedup by open-time ms (keep first), strictly-monotonic ascending index.
    df = df.drop_duplicates(subset="ms", keep="first").sort_values("ms")
    df = df.reset_index(drop=True)

    # Drop the last (unclosed) candle: its close-time = open_ms + timeframe; if
    # that close-time has not elapsed vs now, the candle is still forming.
    if len(df) > 0:
        last_open_ms = int(df.iloc[-1]["ms"])
        last_close_ms = last_open_ms + _TIMEFRAME_MS
        if last_close_ms > now_ms:
            df = df.iloc[:-1].reset_index(drop=True)

    if df.empty:
        raise RuntimeError("frame empty after dropping the unclosed candle")

    out = pd.DataFrame()
    out["Open time"] = df["ms"].map(_fmt_time)
    out["Open"] = df["open"]
    out["High"] = df["high"]
    out["Low"] = df["low"]
    out["Close"] = df["close"]
    out["Volume"] = df["volume"]
    # Close time = open + timeframe - 1ms (matches Binance kline close-time repr).
    out["Close time"] = (df["ms"] + _TIMEFRAME_MS - 1).map(_fmt_time)
    # Store-ignored columns: best-effort derived / zero placeholders.
    out["Quote asset volume"] = df["close"] * df["volume"]
    out["Number of trades"] = 0
    out["Taker buy base asset volume"] = 0.0
    out["Taker buy quote asset volume"] = 0.0
    out["Ignore"] = 0

    return out[_KLINE_HEADER]


def fetch_all(days: int) -> None:
    """Fetch all configured symbols and write the kline-schema CSVs."""
    exchange = ccxt.binance({"enableRateLimit": True})
    now_ms = exchange.milliseconds()
    since = now_ms - days * 24 * 60 * 60 * 1000
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    for symbol, stem in _SYMBOLS.items():
        print(f"Fetching {symbol} ({days} days @ {_TIMEFRAME})...")
        rows = _fetch_one(exchange, symbol, since, now_ms)
        frame = _to_kline_frame(rows, now_ms)
        path = _DATA_DIR / f"{stem}_5m.csv"
        frame.to_csv(path, index=False)
        print(f"  wrote {len(frame)} bars -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=180,
        help="span in days to fetch (default 180 ~= 6 months)")
    args = parser.parse_args()
    fetch_all(args.days)


if __name__ == "__main__":
    main()
