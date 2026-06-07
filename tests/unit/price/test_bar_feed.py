"""Unit tests for BacktestBarFeed — the phase's core regression locks (06-03).

Regression-locks the bar-timing contract (bar_feed module docstring, rules
1-7) at its single enforcement point:

1. M5-01 / D-02 look-ahead: the forming resampled bucket is INVISIBLE at the
   decision tick (both directions of the visibility boundary, rule 4).
2. D-02 both branches agree: same-timeframe windows obey the identical
   "last closed bar <= T" rule (rule 3).
3. M5-03 precompute: feed windows equal a hand-built resample reference and
   the per-tick path performs ZERO resample calls.
4. D-15 current_bars: Decimal Bar facts, sparse universe (absent != None).
5. FR7: unknown ticker raises MissingPriceDataError, never None.
6. D-19 / FR8 megaframe: keys == actually-included symbols, values aligned
   per key, tz-aware index.
7. Pitfall 2: minutes timeframes resample via 'min' (never month-end 'm') —
   filterwarnings=["error"] makes any FutureWarning an implicit failure.
"""

import logging
import queue
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from itrader.config import TIMEZONE
from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.price_handler.feed import BacktestBarFeed
from itrader.price_handler.store import CsvPriceStore

pytestmark = pytest.mark.unit

KLINE_HEADER = (
    'Open time,Open,High,Low,Close,Volume,Close time,Quote asset volume,'
    'Number of trades,Taker buy base asset volume,Taker buy quote asset volume,Ignore\n'
)

# Hand-built aggregation spec for the precompute-equality reference — kept
# independent from the implementation's spec on purpose.
AGG = {"open": "first", "high": "max", "low": "min",
       "close": "last", "volume": "sum"}


def ts(stamp: str) -> pd.Timestamp:
    """A tz-aware timestamp in the store/ping timezone."""
    return pd.Timestamp(stamp, tz=TIMEZONE)


def write_kline_csv(path: Path, stamps: list[str], base: float = 100.0) -> Path:
    """Write a Binance-kline-shaped CSV: bar i has open=base+i, high=base+10+i,
    low=base-10+i, close=base+5+i, volume=1000+i.

    ``stamps`` are interpreted in TIMEZONE so bar stamps land exactly on the
    given local timestamps after the store's utc->TIMEZONE conversion.
    """
    rows = [KLINE_HEADER]
    for i, stamp in enumerate(stamps):
        utc = pd.Timestamp(stamp, tz=TIMEZONE).tz_convert('UTC')
        open_time = utc.strftime('%Y-%m-%d %H:%M:%S') + '.000000 UTC'
        close_time = utc.strftime('%Y-%m-%d %H:%M:%S') + '.999000 UTC'
        rows.append(
            f"{open_time},"
            f"{base + i},{base + 10 + i},{base - 10 + i},{base + 5 + i},{1000 + i},"
            f"{close_time},1.0,1,1.0,1.0,0\n"
        )
    path.write_text(''.join(rows))
    return path


DAILY_DATES = [f'2020-01-{d:02d}' for d in range(1, 11)]  # stamped Jan 1..10


@pytest.fixture
def daily_store(tmp_path):
    """Single-symbol store: 1d base bars stamped 2020-01-01..2020-01-10."""
    csv = write_kline_csv(tmp_path / 'btc.csv', DAILY_DATES)
    return CsvPriceStore(csv_paths={'BTCUSD': csv},
                         start_date='2020-01-01', end_date='2020-12-31')


@pytest.fixture
def daily_feed(daily_store):
    return BacktestBarFeed(daily_store, timedelta(days=1))


@pytest.fixture
def daily_base_frame(daily_store):
    return daily_store.read_bars('BTCUSD')


@pytest.fixture
def duo_feed(tmp_path):
    """Three-symbol feed: BTC/ETH share the daily grid (distinct price seeds);
    LATEUSD only has bars in June — empty window at any January tick."""
    btc = write_kline_csv(tmp_path / 'btc.csv', DAILY_DATES, base=100.0)
    eth = write_kline_csv(tmp_path / 'eth.csv', DAILY_DATES, base=200.0)
    late = write_kline_csv(tmp_path / 'late.csv',
                           [f'2020-06-{d:02d}' for d in range(1, 8)], base=300.0)
    store = CsvPriceStore(
        csv_paths={'BTCUSD': btc, 'ETHUSD': eth, 'LATEUSD': late},
        start_date='2020-01-01', end_date='2020-12-31')
    return BacktestBarFeed(store, timedelta(days=1))


# -- 1. M5-01 / D-02: look-ahead regression (contract rule 4) ------------------

def test_look_ahead_forming_bucket_invisible(daily_feed):
    # Rule 4: bucket B=2020-01-01 (7d, covers Jan 1-7) is visible iff
    # B + TF <= T + tf_base. At T=Jan 6: Jan 8 > Jan 7 -> INVISIBLE.
    window = daily_feed.window('BTCUSD', timedelta(days=7), max_window=5,
                               asof=ts('2020-01-06'))
    assert window.empty or window.index[-1] < ts('2020-01-01')


def test_look_ahead_bucket_visible_once_closed(daily_feed, daily_base_frame):
    # Rule 4, other boundary direction: at T=Jan 7, B + TF == T + tf_base
    # (Jan 8 == Jan 8) -> bucket B=Jan 1 VISIBLE; its close is the base
    # close of its last contained bar (Jan 7).
    window = daily_feed.window('BTCUSD', timedelta(days=7), max_window=5,
                               asof=ts('2020-01-07'))
    assert window.index[-1] == ts('2020-01-01')
    assert float(window.iloc[-1]['close']) == \
        daily_base_frame.loc[ts('2020-01-07'), 'close']


def test_look_ahead_trailing_partial_bucket_absent(daily_feed, daily_base_frame):
    # Pitfall 1: pandas KEEPS the trailing forming bucket in the resampled
    # frame (verify it exists in the reference) — the Feed's slice must
    # still hide it. At T=Jan 10 the bucket B=Jan 8 (covers Jan 8-14) is
    # forming: B + TF = Jan 15 > Jan 11 = T + tf_base -> absent.
    reference = daily_base_frame.resample(
        '7D', label='left', closed='left').agg(AGG)
    assert ts('2020-01-08') in reference.index  # pandas retains the partial

    window = daily_feed.window('BTCUSD', timedelta(days=7), max_window=5,
                               asof=ts('2020-01-10'))
    assert ts('2020-01-08') not in window.index
    assert list(window.index) == [ts('2020-01-01')]


# -- 2. D-02: both branches agree (contract rule 3) ----------------------------

def test_same_timeframe_branch_agrees_with_base_tail(daily_feed, daily_base_frame):
    # Rule 3: with timeframe == base timeframe the cutoff degenerates to
    # asof — the window's last row is the bar stamped T (the last closed
    # bar <= T) and the window equals the equivalent base-frame tail slice.
    window = daily_feed.window('BTCUSD', timedelta(days=1), max_window=3,
                               asof=ts('2020-01-05'))
    assert window.index[-1] == ts('2020-01-05')
    pd.testing.assert_frame_equal(window, daily_base_frame.iloc[2:5])


# -- 3. M5-03: precompute equality + zero resample per tick --------------------

def test_precompute_window_equals_handbuilt_reference(daily_feed, daily_base_frame):
    # Feed windows for a 2d timeframe == hand-built resample reference
    # sliced by the rule-4 visibility cutoff, across several ticks.
    reference = daily_base_frame.resample(
        '2D', label='left', closed='left').agg(AGG)
    tf = timedelta(days=2)
    for asof in [ts('2020-01-04'), ts('2020-01-05'),
                 ts('2020-01-07'), ts('2020-01-10')]:
        cutoff = asof - tf + timedelta(days=1)  # rule 4: B <= T - TF + tf_base
        expected = reference[reference.index <= cutoff].tail(4)
        window = daily_feed.window('BTCUSD', tf, max_window=4, asof=asof)
        pd.testing.assert_frame_equal(window, expected, check_freq=False)


def test_zero_resample_calls_on_per_tick_path(daily_store, monkeypatch):
    # M5-03: after precompute(), window() performs ZERO pd.DataFrame.resample
    # calls; an undeclared timeframe lazily memoizes with exactly ONE, then 0.
    feed = BacktestBarFeed(daily_store, timedelta(days=1))
    feed.precompute(['BTCUSD'], timedelta(days=2))

    calls = {'count': 0}
    original = pd.DataFrame.resample

    def counting_resample(self, *args, **kwargs):
        calls['count'] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, 'resample', counting_resample)

    feed.window('BTCUSD', timedelta(days=2), 3, asof=ts('2020-01-06'))
    feed.window('BTCUSD', timedelta(days=2), 3, asof=ts('2020-01-07'))
    assert calls['count'] == 0  # precomputed pair: zero resamples per tick

    feed.window('BTCUSD', timedelta(days=5), 3, asof=ts('2020-01-07'))
    assert calls['count'] == 1  # new timeframe: exactly one lazy memoize
    feed.window('BTCUSD', timedelta(days=5), 3, asof=ts('2020-01-08'))
    assert calls['count'] == 1  # ...then zero again


# -- 4. D-15: current_bars Decimal facts, sparse universe -----------------------

def test_current_bars_decimal_fields_and_sparse_absence(duo_feed):
    bars = duo_feed.current_bars(ts('2020-01-03'))
    # LATEUSD has no bar at T -> ABSENT from the dict (sparse, never None).
    assert set(bars) == {'BTCUSD', 'ETHUSD'}

    bar = bars['BTCUSD']
    assert isinstance(bar, Bar)
    assert bar.time == ts('2020-01-03')
    # Decimal(str(csv value)) — bar i=2 on the base=100 seed.
    assert bar.open == Decimal(str(102.0))
    assert bar.close == Decimal(str(107.0))
    assert bar.volume == Decimal(str(1002.0))
    # Distinct seed proves per-symbol routing.
    assert bars['ETHUSD'].close == Decimal(str(207.0))


def test_current_bar_close_is_the_equity_mark(daily_feed, daily_base_frame):
    # Rule 6 (D-05): the close of current_bars(T)[ticker] is the value the
    # portfolio marks equity with at tick T.
    bar = daily_feed.current_bars(ts('2020-01-05'))['BTCUSD']
    assert bar.close == Decimal(str(daily_base_frame.loc[ts('2020-01-05'),
                                                         'close']))


# -- 5. FR7: loud typed errors ---------------------------------------------------

def test_unknown_ticker_raises_missing_price_data(daily_feed):
    with pytest.raises(MissingPriceDataError):
        daily_feed.window('NOPE', timedelta(days=1), 5, asof=ts('2020-01-05'))


def test_unsupported_timeframe_raises_value_error(daily_feed):
    # The feed's own offset-alias map rejects sub-minute units loudly.
    with pytest.raises(ValueError):
        daily_feed.window('BTCUSD', timedelta(seconds=30), 5,
                          asof=ts('2020-01-05'))


# -- 6. D-19 / FR8: megaframe ----------------------------------------------------

def test_megaframe_keys_are_included_symbols_and_values_aligned(duo_feed):
    tf = timedelta(days=2)
    asof = ts('2020-01-07')
    mega = duo_feed.megaframe(asof=asof, timeframe=tf, max_window=3)

    # FR8 key fix: LATEUSD's window is empty at a January tick -> the symbol
    # AND its key are excluded; keys == actually-included symbols.
    assert list(mega.columns) == ['BTCUSD', 'ETHUSD']
    assert mega.index.tz is not None

    # The :377 key-misalignment regression: per-key values must match the
    # per-symbol windows (distinct price seeds give the assertion teeth).
    for symbol in ['BTCUSD', 'ETHUSD']:
        expected = duo_feed.window(symbol, tf, 3, asof=asof)['close']
        pd.testing.assert_series_equal(mega[symbol], expected,
                                       check_names=False)


# -- 7. Pitfall 2: minutes offset-alias safety ------------------------------------

def test_minutes_precompute_resamples_without_futurewarning(tmp_path):
    # 'm' is month-end in pandas 2.3.3 and FutureWarning escalates to an
    # error under filterwarnings=["error"] — exercising a 30-minute
    # precompute on a minutes fixture is the implicit regression.
    stamps = [f'2020-03-02 09:{m:02d}:00' for m in range(60)]
    csv = write_kline_csv(tmp_path / 'btc_1m.csv', stamps)
    store = CsvPriceStore(csv_paths={'BTCUSD': csv},
                          start_date='2020-01-01', end_date='2020-12-31')
    feed = BacktestBarFeed(store, timedelta(minutes=1))
    feed.precompute(['BTCUSD'], timedelta(minutes=30))

    # Rule 4 sanity on the minutes grid: at T=09:59 the 09:30 bucket
    # (covers 09:30-09:59) has just closed -> both buckets visible.
    window = feed.window('BTCUSD', timedelta(minutes=30), max_window=4,
                         asof=ts('2020-03-02 09:59:00'))
    assert list(window.index) == [ts('2020-03-02 09:00:00'),
                                  ts('2020-03-02 09:30:00')]


# -- 8. BarEvent factory (relocated from DynamicUniverse — Plan 07-02, D-20) ------

def test_generate_bar_event_unbound_returns_the_bar_event(daily_feed):
    # Without a bound queue the factory RETURNS the BarEvent (test-friendly
    # contract, mirrors DynamicUniverse).
    event = daily_feed.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert isinstance(event, BarEvent)
    assert event.time == ts('2020-01-03')
    assert event.bars == daily_feed.current_bars(ts('2020-01-03'))


def test_generate_bar_event_bound_queue_enqueues_and_returns_none(daily_feed):
    q: queue.Queue = queue.Queue()
    daily_feed.bind(q, ['BTCUSD'])
    result = daily_feed.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert result is None
    event = q.get_nowait()
    assert isinstance(event, BarEvent)
    assert event.time == ts('2020-01-03')
    assert set(event.bars) == {'BTCUSD'}
    assert q.empty()


def test_generate_bar_event_missing_membership_ticker_warns(duo_feed, caplog):
    # The relocated missing-ticker warning (RESEARCH OQ4): a membership
    # ticker ABSENT from the produced bars logs a warning naming the
    # ticker and the tick time.
    duo_feed.bind(None, ['BTCUSD', 'LATEUSD'])
    with caplog.at_level(logging.WARNING):
        event = duo_feed.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert event is not None
    assert 'LATEUSD' not in event.bars  # sparse universe: absent, not None
    assert 'LATEUSD' in caplog.text
    assert '2020-01-03' in caplog.text


def test_generate_bar_event_no_warning_when_membership_covered(duo_feed, caplog):
    duo_feed.bind(None, ['BTCUSD', 'ETHUSD'])
    with caplog.at_level(logging.WARNING):
        duo_feed.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert caplog.records == []
