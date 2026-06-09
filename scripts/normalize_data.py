#!/usr/bin/env python
"""Normalize provider OHLCV CSVs into the golden Binance-kline schema (INGEST-01).

This committed driver pins every ingestion-defining decision so a run is
bit-reproducible and the produced files drop straight into the frozen E2E
golden fixtures (no run-path loader change — INGEST-03):

  * D-01  schema   : emit ONLY the 6-column subset Open time,Open,High,Low,Close,Volume
                     (BTC's trailing kline columns and the provider trade_count are dropped)
  * D-02  timestamp: Open time in the byte-exact golden format
                     "%Y-%m-%d %H:%M:%S.%f UTC" (6-digit microseconds, literal " UTC")
  * D-03  layout   : provider inputs preserved under data/raw/, normalized outputs in data/
  * D-04  naming    : data/{TICKER}_1d_ohlcv.csv (no date-range suffix — that suffix is
                     unique to the pinned BTCUSD golden name, which is NOT renamed)
  * D-05  driver    : one committed, importable, all-tickers-by-default script with an
                     internal ticker->raw-path registry (no CLI ticker selection)
  * D-06  validation: validate-and-RAISE before each write (monotonic+unique dates,
                     OHLC consistency, non-negative+non-NaN volume, no NaN) — never
                     silently-wrong
  * D-07  determinism: fixed column order + rows sorted ascending by Open time +
                     float_format="%.10f" -> byte-identical re-runs (sha256 stable)

Dependency-light: the transform path imports ONLY pathlib + pandas. Importing
``itrader`` would fire process-wide singleton init (config/logger/idgen in
itrader/__init__.py); the script produces UTC and lets the loader's
``tz_convert(TIMEZONE)`` handle the zone. The optional CsvPriceStore round-trip
acceptance check (which DOES import ``itrader``) is isolated behind the
``--verify`` flag, off the hot transform path.

Run via ``make normalize-data`` or ``poetry run python scripts/normalize_data.py``.
"""

import pathlib
import sys

import pandas as pd


# --- Pinned normalization configuration ------------------------------------

RAW_DIR = pathlib.Path("data/raw")        # D-03 (inputs preserved here)
OUT_DIR = pathlib.Path("data")            # D-03 (normalized outputs)
FLOAT_FORMAT = "%.10f"                     # D-07 (reuse the repo pin, run_backtest.py:63)

# D-01: the exact golden 6-column header, in this order.
GOLDEN_COLUMNS = ["Open time", "Open", "High", "Low", "Close", "Volume"]
# D-02: byte-exact golden Open time format ("2018-01-01 00:00:00.000000 UTC").
OPEN_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f UTC"

# D-05: internal ticker -> (raw_filename, out_filename) registry. All tickers
# are normalized by default; there is no CLI ticker selection (hardcoded literal,
# so the registry is not a path-traversal surface — threat T-02-02).
REGISTRY = {
    "ETHUSD":  ("ETHUSD_1d.csv",  "ETHUSD_1d_ohlcv.csv"),
    "SOLUSD":  ("SOLUSD_1d.csv",  "SOLUSD_1d_ohlcv.csv"),
    "AAVEUSD": ("AAVEUSD_1d.csv", "AAVEUSD_1d_ohlcv.csv"),
}


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Transform a provider frame into the golden 6-column schema (D-01/D-02/D-07).

    The provider header is ``time,date,open,high,low,close,volume,trade_count``
    with a split ``date`` (2021-01-01) and ``time`` (00:00:00+00:00). Join and
    parse to a tz-aware UTC instant, render the D-02 Open time string, select and
    rename the OHLCV columns to the capitalized golden header (dropping
    ``trade_count``), and sort ascending by the parsed timestamp (D-07).

    Parameters
    ----------
    df : pd.DataFrame
        The raw provider frame.

    Returns
    -------
    pd.DataFrame
        A frame with exactly ``GOLDEN_COLUMNS``, rows sorted ascending by time.
    """
    # Join provider date + time -> tz-aware UTC instant (D-02). The provider time
    # already carries a +00:00 offset; utc=True normalizes to UTC regardless.
    timestamp = pd.to_datetime(df["date"] + " " + df["time"], utc=True)

    out = pd.DataFrame(
        {
            "Open time": timestamp.dt.strftime(OPEN_TIME_FORMAT),  # D-02 byte-exact
            "Open": df["open"],
            "High": df["high"],
            "Low": df["low"],
            "Close": df["close"],
            "Volume": df["volume"],
        }
    )
    # D-07: rows sorted ascending by the parsed timestamp, fixed column order.
    out = out.assign(_sort_key=timestamp.values)
    out = out.sort_values("_sort_key", kind="stable").drop(columns="_sort_key")
    out = out.reset_index(drop=True)
    return out[GOLDEN_COLUMNS]


def validate_frame(out: pd.DataFrame, ticker: str) -> None:
    """Validate a normalized frame and RAISE on any violation (D-06).

    Trusted-but-verify, mirroring ``CsvPriceStore._load_csv``: a malformed bar must
    abort the run rather than silently enter a frozen golden fixture (threat
    T-02-01). Checks: dates monotonic-increasing AND unique; OHLC consistency
    (low <= min(open,close) and max(open,close) <= high per row); volume
    non-negative AND non-NaN; no NaN in any of the 6 columns.

    Volume check — non-negative, not strictly-positive (user decision, Option 1).
    The provider data contains zero-volume bars (SOLUSD 11, AAVEUSD 35; ETHUSD 0,
    BTCUSD golden 0). These are NOT genuine no-trade days: the OHLC on those dates
    shows real intraday movement (e.g. SOLUSD 2024-08-27 open 157.15 / high 159.69
    / low 145.14 / close 146.85, ~9% range) — price cannot move that far with zero
    trades, so ``volume == 0`` here is a provider MISSING-DATA SENTINEL, not a true
    zero. The OHLC prices are real and internally consistent and are the only thing
    the v1.1 run path consumes: SMA_MACD_strategy.py reads no volume; the
    execution/slippage/fee models track only ``_total_volume`` (executed-fill
    notional), never the input bar volume; sizing/risk read no volume. The bar
    volume field is therefore INERT on the v1.1 run path. Relaxing to ``>= 0``
    preserves the real price data and the pinned row counts while keeping volume
    guarded so genuinely-corrupt bars still raise: volume must be non-negative AND
    non-NaN (negative or NaN volume still aborts the run). CAVEAT: volume on those
    specific SOL/AAVE dates is KNOWN-UNRELIABLE — any future phase building a
    volume-using scenario on SOL/AAVE must treat those dates as suspect and
    re-verify before freezing.

    Parameters
    ----------
    out : pd.DataFrame
        A normalized frame with ``GOLDEN_COLUMNS``.
    ticker : str
        The ticker, for error messages.

    Raises
    ------
    ValueError
        If any validation check fails.
    """
    # Parse the Open time back to a tz-aware instant for the date checks.
    timestamp = pd.to_datetime(out["Open time"], utc=True)
    if not timestamp.is_monotonic_increasing:
        raise ValueError(f"{ticker}: Open time is not monotonic-increasing")
    if not timestamp.is_unique:
        raise ValueError(f"{ticker}: Open time has duplicate timestamps")

    open_close_min = out[["Open", "Close"]].min(axis=1)
    open_close_max = out[["Open", "Close"]].max(axis=1)
    if not (out["Low"] <= open_close_min).all():
        raise ValueError(f"{ticker}: OHLC inconsistency — Low > min(Open, Close)")
    if not (open_close_max <= out["High"]).all():
        raise ValueError(f"{ticker}: OHLC inconsistency — max(Open, Close) > High")

    # Volume non-negative AND non-NaN (user decision Option 1). Zero-volume bars
    # are a provider missing-data sentinel, not a true zero, and volume is inert on
    # the v1.1 run path (see docstring). Negative or NaN volume still raises.
    if out["Volume"].isna().any():
        raise ValueError(f"{ticker}: NaN Volume present")
    if not (out["Volume"] >= 0).all():
        raise ValueError(f"{ticker}: negative Volume present")

    if out[GOLDEN_COLUMNS].isna().any().any():
        raise ValueError(f"{ticker}: NaN present in one of {GOLDEN_COLUMNS}")


def normalize_ticker(ticker: str, raw_filename: str, out_filename: str) -> pathlib.Path:
    """Normalize one ticker: read raw -> transform -> validate -> write (D-06/D-07).

    Parameters
    ----------
    ticker : str
        The ticker symbol (for messages).
    raw_filename : str
        The provider CSV filename under ``RAW_DIR``.
    out_filename : str
        The normalized output filename under ``OUT_DIR``.

    Returns
    -------
    pathlib.Path
        The path of the written output file.
    """
    raw_path = RAW_DIR / raw_filename
    out_path = OUT_DIR / out_filename

    raw = pd.read_csv(raw_path)
    out = normalize_frame(raw)
    validate_frame(out, ticker)  # D-06: raise BEFORE writing.

    # D-07: fixed column order, sorted rows, pinned float repr, no index.
    out.to_csv(out_path, index=False, float_format=FLOAT_FORMAT)
    return out_path


def verify_loads() -> None:
    """Optional acceptance check: load each output through CsvPriceStore (INGEST-03).

    Imports ``itrader`` (firing the singleton side effects), so this is isolated
    behind the ``--verify`` flag and OFF the hot transform path. Proves the
    produced files load through the UNCHANGED loader for the dataset's span.
    """
    from itrader.price_handler.store.csv_store import CsvPriceStore

    spans = {
        "ETHUSD": ("2021-01-01", "2026-12-31"),
        "SOLUSD": ("2021-01-01", "2026-12-31"),
        "AAVEUSD": ("2021-07-15", "2026-12-31"),
    }
    for ticker, (_raw, out_filename) in REGISTRY.items():
        start, end = spans[ticker]
        store = CsvPriceStore(
            csv_paths={ticker: str(OUT_DIR / out_filename)},
            start_date=start,
            end_date=end,
        )
        frame = store.read_bars(ticker)
        assert not frame.empty, f"{ticker}: CsvPriceStore returned an empty frame"
        print(f"{ticker}: CsvPriceStore loaded {len(frame)} bars (tz={frame.index.tz})")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, (raw_filename, out_filename) in REGISTRY.items():
        out_path = normalize_ticker(ticker, raw_filename, out_filename)
        print(f"{ticker}: wrote {out_path}")

    if "--verify" in sys.argv[1:]:
        verify_loads()


if __name__ == "__main__":
    main()
