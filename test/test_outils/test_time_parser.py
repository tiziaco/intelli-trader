"""Wave-0 characterization stub for M2-10 (time_parser timing correctness).

Written at Wave 0 of Phase 3 (M2b) under the CURRENT ``test/`` tree so ``make test``
collects it immediately (auto-marked ``unit`` via the ``test_outils`` path in conftest).
It pins the M2-10 behaviors the time-parser-correctness wave delivers:

  1. ``to_timedelta("1W")`` returns a 7-day timedelta (week support).
  2. ``to_timedelta("1M")`` raises a MONTH-specific error (months are not a fixed
     timedelta).
  3. ``to_timedelta("1H")`` is case-insensitive (parses like ``"1h"``).
  4. ``check_timeframe`` fires correctly on the golden daily-UTC grid.

Today ``to_timedelta`` supports only ``d/h/m`` (case-sensitive) and raises on ``W``/``M``;
weeks/months/case-insensitivity land in the M2-10 wave. Those three assertions are
therefore skip-gated to stay GREEN at Wave 0. ``check_timeframe`` already works on the
daily grid today, so it is asserted LIVE now (a real Wave-0 characterization of
current correct behavior).

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_outils/`` during
the 03-08 type-split — 03-08 reconciles it there without duplication.
"""

from datetime import datetime, timedelta

import pytz
import pytest

from itrader.outils.time_parser import check_timeframe


@pytest.mark.skip(reason="pending M2-10: to_timedelta week support ('1W' → 7 days)")
def test_to_timedelta_week():
    """M2-10: to_timedelta('1W') returns a 7-day timedelta."""
    from itrader.outils.time_parser import to_timedelta

    assert to_timedelta("1W") == timedelta(days=7)


@pytest.mark.skip(reason="pending M2-10: to_timedelta month-specific error ('1M')")
def test_to_timedelta_month_raises_month_specific_error():
    """M2-10: to_timedelta('1M') raises a month-specific error (months are not fixed)."""
    from itrader.outils.time_parser import to_timedelta

    with pytest.raises(ValueError, match="(?i)month"):
        to_timedelta("1M")


@pytest.mark.skip(reason="pending M2-10: to_timedelta case-insensitivity ('1H' == '1h')")
def test_to_timedelta_case_insensitive():
    """M2-10: to_timedelta('1H') is case-insensitive (parses like '1h')."""
    from itrader.outils.time_parser import to_timedelta

    assert to_timedelta("1H") == timedelta(hours=1)


def test_check_timeframe_fires_on_daily_utc_grid():
    """M2-10: check_timeframe is True at UTC-midnight on the golden daily grid (current behavior).

    This is a LIVE Wave-0 characterization: midnight UTC is a multiple of the 1-day
    timeframe, so check_timeframe returns True; a non-midnight time is not.
    """
    daily = timedelta(days=1)
    midnight_utc = datetime(2018, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
    midday_utc = datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc)

    assert check_timeframe(midnight_utc, daily) is True
    assert check_timeframe(midday_utc, daily) is False
