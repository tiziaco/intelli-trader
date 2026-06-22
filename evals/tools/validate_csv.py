"""CSV validation gate for the evals 5m datasets (PERF-BASELINE §7 / §12 Step 1).

Bad source data invalidates the whole baseline, so this gate raises LOUDLY (an
``AssertionError``) on any violation rather than warning. It mirrors the
``CsvPriceStore`` store-style parse (rename OHLCV, ``pd.to_datetime(..., utc=True)``)
then asserts:

1. all six expected columns present after the rename,
2. a strictly-increasing, non-duplicated datetime index,
3. per-row OHLC invariants (low <= open, low <= close, high >= open,
   high >= close, high >= low),
4. NO fabricated flat O=H=L=C runs beyond a sane consecutive threshold (real
   gaps are allowed as MISSING rows, not as fabricated flats).

Run as ``__main__`` to validate all four committed data files.
"""

from pathlib import Path

import pandas as pd

_EXPECTED_RAW = ["Open time", "Open", "High", "Low", "Close", "Volume"]
_RENAMED = ["date", "open", "high", "low", "close", "volume"]

# >5 consecutive identical-OHLC bars is treated as a fabricated flat run. Real
# 5m crypto bars on liquid USDT pairs effectively never print 6 identical OHLC
# bars in a row; a ffill-resample (the defect we avoid) would.
_MAX_FLAT_RUN = 5

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_FILES = ["BTCUSDT_5m.csv", "ETHUSDT_5m.csv", "SOLUSDT_5m.csv", "BNBUSDT_5m.csv"]


def _max_flat_run(df: pd.DataFrame) -> int:
    """Return the longest run of consecutive identical-OHLC bars."""
    flat = (
        (df["open"] == df["high"])
        & (df["high"] == df["low"])
        & (df["low"] == df["close"])
    )
    longest = 0
    current = 0
    for is_flat in flat:
        current = current + 1 if is_flat else 0
        longest = max(longest, current)
    return longest


def validate_csv(path: str | Path) -> None:
    """Validate one kline-schema CSV; raise loudly on any violation."""
    path = Path(path)
    raw = pd.read_csv(path)

    missing = [c for c in _EXPECTED_RAW if c not in raw.columns]
    assert not missing, f"{path.name}: missing columns {missing}"

    # Store-style parse: select the six load-bearing columns, rename, index by
    # tz-aware datetime.
    df = raw[_EXPECTED_RAW].copy()
    df.columns = _RENAMED
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date")

    for col in _RENAMED:
        assert col in (["date"] + list(df.columns)), (
            f"{path.name}: column {col} missing after rename")

    assert len(df) > 0, f"{path.name}: empty frame"

    # Strictly-increasing, non-duplicated index.
    assert df.index.is_monotonic_increasing, (
        f"{path.name}: datetime index is not monotonic increasing")
    assert not df.index.has_duplicates, (
        f"{path.name}: datetime index has duplicate timestamps")

    # Per-row OHLC invariants.
    bad = df[
        ~(
            (df["low"] <= df["open"])
            & (df["low"] <= df["close"])
            & (df["high"] >= df["open"])
            & (df["high"] >= df["close"])
            & (df["high"] >= df["low"])
        )
    ]
    assert bad.empty, (
        f"{path.name}: {len(bad)} rows violate OHLC invariants; "
        f"first bad index {bad.index[0] if len(bad) else 'n/a'}")

    # No fabricated flat runs.
    run = _max_flat_run(df)
    assert run <= _MAX_FLAT_RUN, (
        f"{path.name}: {run} consecutive identical-OHLC bars "
        f"(> {_MAX_FLAT_RUN}) — fabricated-flat / ffill signature")

    span = f"{df.index[0]} -> {df.index[-1]}"
    print(f"OK  {path.name}: {len(df)} rows, {span}, max flat run {run}")


def main() -> None:
    for name in _FILES:
        validate_csv(_DATA_DIR / name)
    print("All CSVs validated.")


if __name__ == "__main__":
    main()
