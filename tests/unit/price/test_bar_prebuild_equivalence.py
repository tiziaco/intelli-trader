"""Field-for-field equivalence lock for the itertuples Bar prebuild (Req 3 / 08-03).

`bar_feed.py` replaces the per-row `frame.iterrows()` prebuild (which materializes
~69k throwaway pandas Series across the golden run) with an `itertuples`/vectorized
build. This file is the dedicated equivalence/drift test (08-PATTERNS "Audit-the-
invariant + dedicated equivalence test"): it asserts the new `{ts: Bar}` mapping is
byte-identical to the reference `iterrows` + `Bar.from_row` build — every ticker,
every ts, every OHLCV Decimal — preserving the D-14 `Decimal(str(...))` string path.

The open risk the test pins (08-PATTERNS, "No Analog Found"): `itertuples` yields
numpy/native scalars, so `str(np.float64(x))` MUST produce the SAME string as
`str(series_value)` did under `iterrows`. The `str_parity` test asserts exactly that
for the store-frame dtypes; if it ever diverges the test fails loudly (the byte-exact
pin), forcing the Series-shaped fallback documented in the prebuild.
"""

import queue
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from itrader.config import TIMEZONE
from itrader.core.bar import Bar
from itrader.price_handler.feed import BacktestBarFeed
from itrader.price_handler.store import CsvPriceStore

pytestmark = pytest.mark.unit

KLINE_HEADER = (
    'Open time,Open,High,Low,Close,Volume,Close time,Quote asset volume,'
    'Number of trades,Taker buy base asset volume,Taker buy quote asset volume,Ignore\n'
)


def write_kline_csv(path: Path, stamps: list[str], base: float = 100.0) -> Path:
    """Write a Binance-kline-shaped CSV with deliberately repr-artifact-prone
    fractional OHLCV values (e.g. 0.1 family + a high-precision close) so the
    Decimal(str(...)) path is exercised on values where Decimal(float) WOULD
    diverge from Decimal(str(value))."""
    rows = [KLINE_HEADER]
    for i, stamp in enumerate(stamps):
        utc = pd.Timestamp(stamp, tz=TIMEZONE).tz_convert('UTC')
        open_time = utc.strftime('%Y-%m-%d %H:%M:%S') + '.000000 UTC'
        close_time = utc.strftime('%Y-%m-%d %H:%M:%S') + '.999000 UTC'
        # repr-artifact-prone fractions: 0.1, 0.2, 0.3 ... and a long-decimal close.
        o = base + i + 0.1
        h = base + i + 0.3
        low = base + i - 0.2
        c = base + i + 0.123456789
        v = 1000 + i + 0.7
        rows.append(
            f"{open_time},{o},{h},{low},{c},{v},"
            f"{close_time},1.0,1,1.0,1.0,0\n"
        )
    path.write_text("".join(rows))
    return path


@pytest.fixture
def store(tmp_path: Path) -> CsvPriceStore:
    stamps = [f"2020-01-{d:02d} 00:00:00" for d in range(1, 11)]
    csv = write_kline_csv(tmp_path / "BTCUSDT.csv", stamps)
    return CsvPriceStore({"BTCUSDT": str(csv)})


def _iterrows_reference(frame: pd.DataFrame) -> dict[object, Bar]:
    """The OLD prebuild — the byte-exact reference the new path must match."""
    return {ts: Bar.from_row(ts, row) for ts, row in frame.iterrows()}


def test_prebuild_equivalence(store: CsvPriceStore) -> None:
    """The feed's itertuples-built {ts: Bar} prebuild is field-for-field
    byte-identical to the iterrows + Bar.from_row reference."""
    feed = BacktestBarFeed(store, timedelta(days=1))
    new_map = feed._prebuilt["BTCUSDT"]

    frame = store.read_bars("BTCUSDT")
    ref_map = _iterrows_reference(frame)

    # Every ticker / every ts present.
    assert set(new_map.keys()) == set(ref_map.keys())

    # Every Bar field byte-identical (assert on the Decimal repr string, not ==).
    for ts in ref_map:
        a, b = ref_map[ts], new_map[ts]
        assert a.time == b.time
        for field in ("open", "high", "low", "close", "volume"):
            av, bv = getattr(a, field), getattr(b, field)
            assert isinstance(bv, Decimal)
            assert str(av) == str(bv), f"{ts} {field}: {av!r} != {bv!r}"


def test_str_parity(store: CsvPriceStore) -> None:
    """The byte-exact pin: for the OHLCV columns, str(itertuples_scalar) ==
    str(series_value) for the store frame's dtypes. If a numpy scalar's str()
    ever diverges from the Series value this fails loudly (forcing the
    documented Series-shaped fallback)."""
    frame = store.read_bars("BTCUSDT")
    tuples = list(frame.itertuples(index=True))
    for i, ts in enumerate(frame.index):
        r = tuples[i]
        assert r.Index == ts
        for col in ("open", "high", "low", "close", "volume"):
            series_val = frame[col].iloc[i]
            tuple_val = getattr(r, col)
            assert str(tuple_val) == str(series_val), (
                f"str() parity broken for {col} at {ts}: "
                f"{str(tuple_val)!r} != {str(series_val)!r}"
            )


def test_decimal_string_path(store: CsvPriceStore) -> None:
    """A known repr-artifact-prone fraction produces the same Decimal via the
    new path as the old (D-14 preserved): Decimal(str(value)), NEVER
    Decimal(float)."""
    feed = BacktestBarFeed(store, timedelta(days=1))
    frame = store.read_bars("BTCUSDT")
    new_map = feed._prebuilt["BTCUSDT"]

    for ts in frame.index:
        bar = new_map[ts]
        close_series = frame["close"].loc[ts]
        # The D-14 contract: Decimal(str(x)), which differs from Decimal(float(x))
        # for repr-artifact-prone values. The Bar must use the string path.
        assert bar.close == Decimal(str(close_series))
        # Sanity: the repr-artifact-prone close is NOT what Decimal(float) gives
        # for at least one row (proves the test actually exercises the contract).
    # At least the .123456789 close on row 0 should differ under Decimal(float).
    first_ts = frame.index[0]
    raw_close = frame["close"].loc[first_ts]
    assert Decimal(str(raw_close)) != Decimal(float(raw_close))
