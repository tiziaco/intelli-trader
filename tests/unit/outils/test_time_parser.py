"""Characterization + correctness tests for M2-10 (time_parser timing correctness).

Originally written at Wave 0 of Phase 3 (M2b) as a skip-gated characterization
stub; finalized at Plan 03-04 (M2-10) which delivers the three D-06/D-07/D-08
corrections:

  1. ``to_timedelta`` is case-insensitive (``"1H"``/``"1D"``/``"1W"`` work like the
     lowercase forms), supports week (``w``), RAISES a clear month-specific error
     on ``M``/``m``-as-month, RAISES on any unknown unit (no silent ``None``), and
     guards ``timeframe is None``.
  2. ``check_timeframe`` fires on the golden daily-UTC grid via a single
     Unix-epoch alignment seam (``_aligned``) — DST-immune and, for daily bars at
     00:00 UTC, coincident with the old midnight anchor.
  3. The dead buggy helpers (``format_timeframe``, ``elapsed_time``,
     ``round_timestamp_to_frequency``) are deleted.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_outils/``
during the 03-08 type-split — 03-08 reconciles it there without duplication.
"""

from datetime import datetime, timedelta

import pytz
import pytest

from itrader.outils.time_parser import (
    _aligned,
    check_timeframe,
    to_timedelta,
)


# --------------------------------------------------------------------------- #
# to_timedelta — case-insensitivity, week support, month/unknown raises, None  #
# --------------------------------------------------------------------------- #

def test_to_timedelta_week():
    """to_timedelta('1W') returns a 7-day (1-week) timedelta."""
    assert to_timedelta("1W") == timedelta(weeks=1)
    assert to_timedelta("1W") == timedelta(days=7)


def test_to_timedelta_week_lowercase():
    """to_timedelta('1w') is the case-insensitive twin of '1W'."""
    assert to_timedelta("1w") == timedelta(weeks=1)


def test_to_timedelta_case_insensitive_hour():
    """to_timedelta('1H') parses like '1h'."""
    assert to_timedelta("1H") == timedelta(hours=1)
    assert to_timedelta("1h") == timedelta(hours=1)


def test_to_timedelta_case_insensitive_day():
    """to_timedelta('1D') parses like '1d'."""
    assert to_timedelta("1D") == timedelta(days=1)
    assert to_timedelta("1d") == timedelta(days=1)


def test_to_timedelta_minutes_lowercase_still_minutes():
    """to_timedelta('5m') stays minutes (the only literal 'm' unit)."""
    assert to_timedelta("5m") == timedelta(minutes=5)


def test_to_timedelta_multi_digit_quantity():
    """Multi-digit quantities parse correctly under case-folding."""
    assert to_timedelta("15M".lower()) == timedelta(minutes=15)
    assert to_timedelta("12H") == timedelta(hours=12)


def test_to_timedelta_month_raises_month_specific_error():
    """to_timedelta('1M') raises a MONTH-specific error (months are not fixed)."""
    with pytest.raises(ValueError, match="(?i)month"):
        to_timedelta("1M")


def test_to_timedelta_unknown_unit_raises():
    """to_timedelta('1x') raises a clear error rather than returning None."""
    with pytest.raises(ValueError):
        to_timedelta("1x")


def test_to_timedelta_unparseable_raises():
    """A string that does not match the <number><unit> grammar raises."""
    with pytest.raises(ValueError):
        to_timedelta("garbage")


def test_to_timedelta_none_guarded():
    """to_timedelta(None) raises a clear error rather than crashing downstream."""
    with pytest.raises((ValueError, TypeError)):
        to_timedelta(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# check_timeframe — epoch-aligned firing on the golden daily-UTC grid          #
# --------------------------------------------------------------------------- #

def test_check_timeframe_fires_on_daily_utc_grid():
    """check_timeframe is True at UTC-midnight on the golden daily grid, False off-grid."""
    daily = timedelta(days=1)
    midnight_utc = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    midday_utc = datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc)

    assert check_timeframe(midnight_utc, daily) is True
    assert check_timeframe(midday_utc, daily) is False


def test_check_timeframe_fires_across_multiple_daily_bars():
    """Every 00:00 UTC bar fires; intra-day points do not."""
    daily = timedelta(days=1)
    for day in range(1, 6):
        midnight = datetime(2020, 3, day, 0, 0, 0, tzinfo=pytz.utc)
        off_grid = datetime(2020, 3, day, 6, 30, 0, tzinfo=pytz.utc)
        assert check_timeframe(midnight, daily) is True
        assert check_timeframe(off_grid, daily) is False


def test_check_timeframe_hourly_grid():
    """Hourly timeframe fires on the top of each hour."""
    hourly = timedelta(hours=1)
    top = datetime(2021, 7, 1, 14, 0, 0, tzinfo=pytz.utc)
    mid = datetime(2021, 7, 1, 14, 30, 0, tzinfo=pytz.utc)
    assert check_timeframe(top, hourly) is True
    assert check_timeframe(mid, hourly) is False


def test_check_timeframe_dst_boundary_is_immune():
    """Midnight-relative alignment is DST-immune: a 00:00 UTC daily bar fires regardless of DST.

    2020-03-29 is the EU DST spring-forward day; the old market-tz-local anchor
    would mis-align here. Midnight-of-day-UTC alignment fires on the 00:00 UTC
    grid unchanged.
    """
    daily = timedelta(days=1)
    dst_midnight_utc = datetime(2020, 3, 29, 0, 0, 0, tzinfo=pytz.utc)
    assert check_timeframe(dst_midnight_utc, daily) is True


def test_check_timeframe_weekly_fires_on_any_midnight():
    """Weekly timeframe fires on ANY midnight, not only Thursdays (WR-01 regression).

    The old epoch seam anchored on 1970-01-01 (a Thursday), so a weekly tf fired
    only on Thursday 00:00 UTC. The midnight-relative anchor fires on every
    midnight regardless of weekday; a midday point never fires.
    """
    weekly = timedelta(weeks=1)
    # 2018-01-01 is a Monday — the old epoch seam returned False here.
    monday_midnight = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    # 2018-01-03 is a Wednesday — another non-Thursday midnight in the same week.
    wednesday_midnight = datetime(2018, 1, 3, 0, 0, 0, tzinfo=pytz.utc)
    midday = datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc)

    assert check_timeframe(monday_midnight, weekly) is True
    assert check_timeframe(wednesday_midnight, weekly) is True
    assert check_timeframe(midday, weekly) is False


def test_check_timeframe_7h_aligns_to_midnight():
    """A 7h (non-day-divisor) timeframe aligns to midnight-of-day.

    seconds-since-midnight is 0 at 00:00 (0 % 25200 == 0) and 25200 at 07:00
    (25200 % 25200 == 0); 06:00 (21600) does not align. The old epoch seam never
    aligned 7h to midnight.
    """
    seven_h = to_timedelta("7h")
    midnight = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    seven_am = datetime(2018, 1, 1, 7, 0, 0, tzinfo=pytz.utc)
    six_am = datetime(2018, 1, 1, 6, 0, 0, tzinfo=pytz.utc)

    assert check_timeframe(midnight, seven_h) is True
    assert check_timeframe(seven_am, seven_h) is True
    assert check_timeframe(six_am, seven_h) is False


def test_check_timeframe_dst_boundary_tz_aware():
    """A tz-aware DST-zone timestamp is judged on the UTC midnight grid (DST-immune).

    Build a tz-aware instant in Europe/Rome that crosses the EU spring-forward
    (2020-03-29). check_timeframe converts to UTC first, so firing is judged on
    the UTC midnight grid deterministically. The corresponding 00:00 UTC instant
    fires for daily; the off-grid local-DST instant does not mis-fire.
    """
    daily = timedelta(days=1)
    rome = pytz.timezone("Europe/Rome")
    # Local 03:00 just after spring-forward is CEST (UTC+2) -> 01:00 UTC, an
    # off-grid (non-UTC-midnight) instant that must NOT fire daily.
    off_grid_local = rome.localize(datetime(2020, 3, 29, 3, 0, 0))
    assert off_grid_local.astimezone(pytz.utc).hour == 1  # sanity: maps to 01:00 UTC
    # Local 02:00 CET (UTC+1, the instant before spring-forward) -> 01:00 UTC too,
    # but local 01:00 CET -> 00:00 UTC, which IS on-grid and fires.
    on_grid_local = rome.localize(datetime(2020, 3, 29, 1, 0, 0))
    assert on_grid_local.astimezone(pytz.utc).hour == 0  # sanity: maps to 00:00 UTC
    midnight_utc = datetime(2020, 3, 29, 0, 0, 0, tzinfo=pytz.utc)

    assert check_timeframe(midnight_utc, daily) is True
    assert check_timeframe(on_grid_local, daily) is True
    assert check_timeframe(off_grid_local, daily) is False


# --------------------------------------------------------------------------- #
# _aligned — the single replaceable midnight-relative seam                     #
# --------------------------------------------------------------------------- #

def test_aligned_seam_midnight_relative():
    """_aligned is the (seconds-since-UTC-midnight % tf_seconds) == 0 seam."""
    daily = timedelta(days=1)
    midnight_utc = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    midday_utc = datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc)

    assert _aligned(midnight_utc, daily) is True
    assert _aligned(midday_utc, daily) is False
    # explicit midnight-relative arithmetic cross-check
    utc_mid = midday_utc.astimezone(pytz.utc).replace(
        second=0, microsecond=0
    )
    seconds_since_midnight = (
        utc_mid - utc_mid.replace(hour=0, minute=0, second=0, microsecond=0)
    ).total_seconds()
    assert seconds_since_midnight % int(daily.total_seconds()) != 0


# --------------------------------------------------------------------------- #
# _aligned — D-01 (PERF-07) bounded-memo: equivalence, memo-active, bounded    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "ts, tf, expected",
    [
        # daily 00:00 UTC -> seconds-since-midnight 0 % 86400 == 0 -> aligned
        (datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc), timedelta(days=1), True),
        # intraday non-aligned: 12:00 is not on the 5-minute grid? 12:00 IS on the
        # 5m grid (43200 % 300 == 0); use 12:03 to be off the 5-minute grid.
        (datetime(2018, 1, 1, 12, 3, 0, tzinfo=pytz.utc), timedelta(minutes=5), False),
        # weekly tf fires on every midnight (midnight-of-the-day anchor) -> aligned
        (datetime(2018, 1, 4, 0, 0, 0, tzinfo=pytz.utc), timedelta(weeks=1), True),
        # 7h non-divisor of a day: 07:00 UTC aligns (25200 % 25200 == 0)
        (datetime(2018, 1, 1, 7, 0, 0, tzinfo=pytz.utc), timedelta(hours=7), True),
        # 7h non-divisor: 03:00 UTC does NOT align (10800 % 25200 != 0)
        (datetime(2018, 1, 1, 3, 0, 0, tzinfo=pytz.utc), timedelta(hours=7), False),
    ],
)
def test_aligned_equivalence_sampled_grid(ts, tf, expected):
    """T1: _aligned returns the documented alignment boolean for a sampled grid.

    Mirrors the docstring examples at time_parser.py:127-145 — daily 00:00,
    intraday non-aligned, weekly-on-midnight, and a 7h non-divisor case.
    """
    assert _aligned(ts, tf) is expected


def test_aligned_memo_active_and_bounded():
    """T2: the lru_cache is bounded at 32 and a repeat call is a cache hit."""
    _aligned.cache_clear()  # isolate from other tests' cache state
    assert _aligned.cache_info().maxsize == 32

    ts = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    tf = timedelta(days=1)
    _aligned(ts, tf)  # miss -> populates the memo
    _aligned(ts, tf)  # identical args -> cache hit, not a recompute
    assert _aligned.cache_info().hits >= 1


def test_aligned_memo_bounded_currsize():
    """T3: with many distinct (ts, tf) the memo never exceeds maxsize=32."""
    _aligned.cache_clear()
    tf = timedelta(days=1)
    base = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    for i in range(150):  # >100 distinct timestamps
        _aligned(base + timedelta(hours=i), tf)
    assert _aligned.cache_info().currsize <= 32


# --------------------------------------------------------------------------- #
# Dead helpers are gone                                                        #
# --------------------------------------------------------------------------- #

def test_dead_helpers_deleted():
    """format_timeframe / elapsed_time / round_timestamp_to_frequency are removed."""
    import itrader.outils.time_parser as tp

    assert not hasattr(tp, "format_timeframe")
    assert not hasattr(tp, "elapsed_time")
    assert not hasattr(tp, "round_timestamp_to_frequency")
