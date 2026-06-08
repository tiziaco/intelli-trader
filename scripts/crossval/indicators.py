"""Shared `ta`-indicator precompute + golden-CSV loader for cross-validation.

Engine-agnostic layer (08-05 Task 1). This module computes SMA(50), SMA(100),
and the MACD histogram(6,12,3) ONCE using iTrader's EXACT `ta` calls (verbatim
from `itrader/strategy_handler/SMA_MACD_strategy.py`) so the two gating reference
engines (backtesting.py, backtrader) consume the IDENTICAL indicator arrays
rather than computing their own (D-03: indicator-library divergence collapses to
zero by construction; any remaining trade-timing gap is a genuine engine
finding, exactly what D-01 demands).

Loads the golden BTCUSD CSV in Binance format and normalizes to lowercase OHLCV
indexed by `Open time`, sliced to the force-match window.

Imports ONLY pandas + ta (+ the run_backtest force-match constants). It does NOT
import backtesting.py or backtrader — those live in the per-engine modules. Keep
this module out of `tests/` (D-10).

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd
from ta import trend

# Force-match config source of truth — reuse the run_backtest.py constants so
# the cross-validation window/dataset cannot drift from the oracle generator.
from scripts.run_backtest import DATASET, START_DATE, END_DATE


# --- Indicator parameters (single source for both engine modules) -----------
# Verbatim from SMA_MACD_strategy defaults (short=50, long=100, FAST=6,
# SLOW=12, WIN=3). MIN_BARS mirrors the strategy's warm-up gate
# `max(long_window, 100)` — the engines apply this gate themselves.
SHORT = 50
LONG = 100
FAST = 6
SLOW = 12
WIN = 3
MIN_BARS = max(LONG, 100)  # == 100


def load_golden_csv(
    path: str = DATASET,
    start_date: str = START_DATE,
    end_date: str = END_DATE,
) -> pd.DataFrame:
    """Load the Binance-format golden CSV, normalized to lowercase OHLCV.

    Reads `data/BTCUSD_1d_ohlcv_2018_2026.csv` (columns `Open time, Open, High,
    Low, Close, Volume, ...`), parses `Open time` as a UTC datetime, sets it as a
    sorted DatetimeIndex, slices to the inclusive [start_date, end_date] window,
    and returns a frame with lowercase columns `open, high, low, close, volume`.

    Defaults to the run_backtest.py constants so callers can invoke with no args.
    """
    raw = pd.read_csv(path)
    # `Open time` is the bar timestamp (UTC). Parse and index by it. Use the
    # underlying arrays (.to_numpy()) when building the frame so the source
    # RangeIndex of `raw` is replaced by the datetime index rather than
    # reindexed against it (which would yield all-NaN).
    index = pd.DatetimeIndex(pd.to_datetime(raw["Open time"], utc=True))
    frame = pd.DataFrame(
        {
            "open": raw["Open"].astype(float).to_numpy(),
            "high": raw["High"].astype(float).to_numpy(),
            "low": raw["Low"].astype(float).to_numpy(),
            "close": raw["Close"].astype(float).to_numpy(),
            "volume": raw["Volume"].astype(float).to_numpy(),
        },
        index=index,
    )
    frame.index.name = "open_time"
    frame = frame.sort_index()
    # Inclusive [start, end] window. Comparison is timezone-aware (UTC index).
    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC")
    # Cover the full end day (the golden window end is a calendar date, and bars
    # are stamped at midnight UTC) — slice inclusive on the day boundary.
    end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
    return frame


def compute_indicators(close: pd.Series) -> pd.DataFrame:
    """Compute SMA(50), SMA(100), MACD-hist(6,12,3) via iTrader's EXACT `ta` calls.

    Mirrors `SMA_MACD_strategy.generate_signal` verbatim:
      * `trend.SMAIndicator(close, window, True).sma_indicator()` for each SMA
        (positional `True` == fillna; same as the strategy).
      * `trend.MACD(close, window_fast=FAST, window_slow=SLOW, window_sign=WIN,
        fillna=False).macd_diff()` for the histogram.

    No hand-rolled SMA/MACD math — delegate entirely to `ta.trend`.

    Returns a frame index-aligned to `close` (same length) carrying columns
    `sma_short`, `sma_long`, `macd_hist`. Early warm-up rows stay NaN (the
    strategy `dropna()`s per-bar, but for cross-engine injection the arrays must
    remain index-aligned to the bars; the downstream engines apply the
    `MIN_BARS` warm-up gate themselves).
    """
    sma_short = trend.SMAIndicator(close, SHORT, True).sma_indicator()
    sma_long = trend.SMAIndicator(close, LONG, True).sma_indicator()
    macd_hist = trend.MACD(
        close,
        window_fast=FAST,
        window_slow=SLOW,
        window_sign=WIN,
        fillna=False,
    ).macd_diff()
    return pd.DataFrame(
        {
            "sma_short": sma_short,
            "sma_long": sma_long,
            "macd_hist": macd_hist,
        },
        index=close.index,
    )


def load_golden_with_indicators(
    path: str = DATASET,
    start_date: str = START_DATE,
    end_date: str = END_DATE,
) -> pd.DataFrame:
    """Load the windowed bar frame and attach the three injected indicator columns.

    The single frame the engine modules consume: lowercase OHLCV plus
    `sma_short`, `sma_long`, `macd_hist` (computed by iTrader's exact `ta` calls),
    all index-aligned to the bar timestamps.
    """
    bars = load_golden_csv(path, start_date, end_date)
    indicators = compute_indicators(bars["close"])
    return bars.join(indicators)


if __name__ == "__main__":
    df = load_golden_with_indicators()
    print(
        "OK",
        len(df),
        "bars |",
        "sma_long non-NaN:",
        int(df["sma_long"].notna().sum()),
    )
