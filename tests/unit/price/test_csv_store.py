"""Unit tests for CsvPriceStore (M5-05, FR6/FR7) — the first price_handler unit tests.

Locks the Store seam contract 06-03 (Feed) and 06-05 (rewiring) build against:

1. The golden CSV loads into the canonical frame shape (tz-aware 'date'
   index, float64 OHLCV columns, pinned 2018-01-01 window start).
2. Loud typed errors (FR7/T-06-04/T-06-05): malformed header ->
   MalformedDataError; empty window slice / unknown ticker ->
   MissingPriceDataError — never a silent ``None``.
3. Read-only run path (FR6): ``write_bars`` raises NotImplementedError.
4. Multi-symbol csv_paths mapping serves every symbol (the 06-03 megaframe
   fixture seed).
"""

from pathlib import Path

import pandas as pd
import pytest

from itrader.core.exceptions import MalformedDataError, MissingPriceDataError
from itrader.price_handler.store import CsvPriceStore

pytestmark = pytest.mark.unit

GOLDEN_CSV = 'data/BTCUSD_1d_ohlcv_2018_2026.csv'

KLINE_HEADER = (
    'Open time,Open,High,Low,Close,Volume,Close time,Quote asset volume,'
    'Number of trades,Taker buy base asset volume,Taker buy quote asset volume,Ignore\n'
)


def write_kline_csv(path: Path, dates: list[str]) -> Path:
    """Write a small Binance-kline-shaped CSV with one bar per date."""
    rows = [KLINE_HEADER]
    for i, date in enumerate(dates):
        rows.append(
            f"{date} 00:00:00.000000 UTC,"
            f"{100 + i},{110 + i},{90 + i},{105 + i},{1000 + i},"
            f"{date} 23:59:59.999000 UTC,1.0,1,1.0,1.0,0\n"
        )
    path.write_text(''.join(rows))
    return path


# -- Golden CSV read path -----------------------------------------------------

def test_golden_csv_loads_canonical_frame():
    store = CsvPriceStore()

    assert store.symbols() == ['BTCUSD']
    assert store.has('BTCUSD')

    index = store.index('BTCUSD')
    assert index.tz is not None  # tz-aware, matches the ping clock (Pitfall 6)
    assert index.name == 'date'

    frame = store.read_bars('BTCUSD')
    assert list(frame.columns) == ['open', 'high', 'low', 'close', 'volume']
    assert all(str(frame[col].dtype) == 'float64' for col in frame.columns)
    # D-02: window pinned — first stamp on/after 2018-01-01.
    assert frame.index[0] >= pd.Timestamp('2018-01-01', tz=str(index.tz))


# -- Loud typed errors (FR7 / T-06-04 / T-06-05) ------------------------------

def test_missing_required_column_raises_malformed(tmp_path):
    # T-06-04: a header missing 'Close' must raise loudly, not load garbage.
    csv = tmp_path / 'bad_header.csv'
    csv.write_text(
        'Open time,Open,High,Low,Volume\n'
        '2018-01-01 00:00:00.000000 UTC,100,110,90,1000\n'
    )
    with pytest.raises(MalformedDataError, match='Close'):
        CsvPriceStore(csv_paths={'BTCUSD': csv})


def test_empty_window_slice_raises_missing(tmp_path):
    # T-06-05: bars entirely outside the pinned window -> empty frame -> raise.
    csv = write_kline_csv(tmp_path / 'old_bars.csv', ['2017-01-01', '2017-01-02'])
    with pytest.raises(MissingPriceDataError):
        CsvPriceStore(csv_paths={'BTCUSD': csv},
                      start_date='2018-01-01', end_date='2018-12-31')


def test_unknown_ticker_raises_never_none(tmp_path):
    # FR7: unknown ticker raises MissingPriceDataError — never returns None.
    csv = write_kline_csv(tmp_path / 'btc.csv', ['2018-01-01', '2018-01-02'])
    store = CsvPriceStore(csv_paths={'BTCUSD': csv})

    with pytest.raises(MissingPriceDataError):
        store.read_bars('NOPE')
    with pytest.raises(MissingPriceDataError):
        store.index('NOPE')
    assert not store.has('NOPE')


# -- Read-only run path (FR6) -------------------------------------------------

def test_write_bars_raises_not_implemented(tmp_path):
    csv = write_kline_csv(tmp_path / 'btc.csv', ['2018-01-01'])
    store = CsvPriceStore(csv_paths={'BTCUSD': csv})

    with pytest.raises(NotImplementedError):
        store.write_bars('BTCUSD', pd.DataFrame())


# -- Multi-symbol mapping (the 06-03 megaframe fixture seed) ------------------

def test_two_symbol_mapping_serves_both(tmp_path):
    btc = write_kline_csv(tmp_path / 'btc.csv', ['2018-01-01', '2018-01-02'])
    eth = write_kline_csv(tmp_path / 'eth.csv', ['2018-01-01', '2018-01-02'])
    # Lower-cased input ticker proves the upper-cased keying (legacy parity).
    store = CsvPriceStore(csv_paths={'BTCUSD': btc, 'ethusd': eth})

    assert sorted(store.symbols()) == ['BTCUSD', 'ETHUSD']
    assert len(store.read_bars('BTCUSD')) == 2
    assert len(store.read_bars('ETHUSD')) == 2
    assert store.index('ETHUSD').tz is not None
