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
    """Epoch alignment is DST-immune: a 00:00 UTC daily bar fires regardless of DST.

    2020-03-29 is the EU DST spring-forward day; the old market-tz-local anchor
    would mis-align here. Epoch alignment fires on the 00:00 UTC grid unchanged.
    """
    daily = timedelta(days=1)
    dst_midnight_utc = datetime(2020, 3, 29, 0, 0, 0, tzinfo=pytz.utc)
    assert check_timeframe(dst_midnight_utc, daily) is True


# --------------------------------------------------------------------------- #
# _aligned — the single replaceable epoch seam                                 #
# --------------------------------------------------------------------------- #

def test_aligned_seam_epoch_modulo():
    """_aligned is the int(ts.timestamp()) % int(tf.total_seconds()) == 0 seam."""
    daily = timedelta(days=1)
    midnight_utc = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    midday_utc = datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc)

    assert _aligned(midnight_utc, daily) is True
    assert _aligned(midday_utc, daily) is False
    # explicit epoch arithmetic cross-check
    assert int(midnight_utc.timestamp()) % int(daily.total_seconds()) == 0


# --------------------------------------------------------------------------- #
# Dead helpers are gone                                                        #
# --------------------------------------------------------------------------- #

def test_dead_helpers_deleted():
    """format_timeframe / elapsed_time / round_timestamp_to_frequency are removed."""
    import itrader.outils.time_parser as tp

    assert not hasattr(tp, "format_timeframe")
    assert not hasattr(tp, "elapsed_time")
    assert not hasattr(tp, "round_timestamp_to_frequency")
