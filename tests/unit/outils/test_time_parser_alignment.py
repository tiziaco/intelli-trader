"""Boolean-equivalence lock for the per-bar alignment seam (Req 5, Phase 8).

Audit-first context (recorded in 08-02-SUMMARY.md):
- CONTEXT/SPEC cite a `check_aligned` function that does NOT exist; the alignment
  math is `_aligned(ts, tf)` + its delegator `check_timeframe`.
- `_aligned` ALREADY carries `@functools.lru_cache(maxsize=32)` (Phase 7 D-01).
  Req 5 is therefore audit + equivalence test + A/B — NOT a from-scratch cache.

This test is the dedicated equivalence guard (Phase 8 pattern: the test is the
guard, no hot-path runtime check). It pins `_aligned` / `check_timeframe` to a
FRESH reference computation of the same midnight-relative UTC math, across a
representative `(ts, tf)` set: the daily 00:00 UTC golden tick, intra-day
timestamps, a DST-boundary timestamp, a non-day-divisor 7h timeframe, and a
weekly timeframe. If a future lever (e.g. an int64-ns grid) replaces the body,
these assertions must still hold byte-identically.
"""

from datetime import datetime, timedelta

import pytz
import pytest

from itrader.outils.time_parser import _aligned, check_timeframe


# --------------------------------------------------------------------------- #
# Fresh reference computation — the SAME astimezone/replace/total_seconds math,  #
# independently re-derived so the test does not just echo the implementation.   #
# --------------------------------------------------------------------------- #

def _reference_aligned(ts: datetime, tf: timedelta) -> bool:
    """Independent reference: is ``ts`` on the midnight-relative UTC grid of ``tf``?"""
    utc = ts.astimezone(pytz.utc).replace(second=0, microsecond=0)
    midnight = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = (utc - midnight).total_seconds()
    return seconds_since_midnight % int(tf.total_seconds()) == 0


# A representative tick/timeframe matrix. Each tuple: (label, ts, tf, expected).
_UTC = pytz.utc
_TF_1H = timedelta(hours=1)
_TF_4H = timedelta(hours=4)
_TF_7H = timedelta(hours=7)        # non-day-divisor
_TF_1D = timedelta(days=1)
_TF_1W = timedelta(weeks=1)

_CASES = [
    # Daily 00:00 UTC golden tick — fires for every timeframe (anchor is midnight).
    ("daily_midnight_d", _UTC.localize(datetime(2021, 1, 1, 0, 0)), _TF_1D, True),
    ("daily_midnight_w", _UTC.localize(datetime(2021, 1, 1, 0, 0)), _TF_1W, True),
    ("daily_midnight_7h", _UTC.localize(datetime(2021, 1, 1, 0, 0)), _TF_7H, True),
    ("daily_midnight_1h", _UTC.localize(datetime(2021, 1, 1, 0, 0)), _TF_1H, True),
    # Intra-day: 04:00 fires for 1h/4h, NOT for daily/weekly.
    ("0400_4h_fires", _UTC.localize(datetime(2021, 6, 15, 4, 0)), _TF_4H, True),
    ("0400_1h_fires", _UTC.localize(datetime(2021, 6, 15, 4, 0)), _TF_1H, True),
    ("0400_d_no", _UTC.localize(datetime(2021, 6, 15, 4, 0)), _TF_1D, False),
    # Intra-day off-grid: 04:30 fires for nothing (sub-hour offset).
    ("0430_1h_no", _UTC.localize(datetime(2021, 6, 15, 4, 30)), _TF_1H, False),
    # Non-day-divisor 7h: 07:00 and 14:00 fire (00:00 anchor); 06:00 does not.
    ("0700_7h_fires", _UTC.localize(datetime(2021, 3, 10, 7, 0)), _TF_7H, True),
    ("1400_7h_fires", _UTC.localize(datetime(2021, 3, 10, 14, 0)), _TF_7H, True),
    ("0600_7h_no", _UTC.localize(datetime(2021, 3, 10, 6, 0)), _TF_7H, False),
    # DST boundary (US spring-forward 2021-03-14 in America/New_York). Alignment
    # is judged on the UTC grid AFTER conversion, so it is DST-immune. A NY-local
    # timestamp that is 00:00 UTC fires for the daily grid.
    ("dst_ny_midnight_utc_d", pytz.timezone("America/New_York").localize(
        datetime(2021, 3, 13, 19, 0)), _TF_1D, True),  # 19:00 EST == 00:00 UTC
    ("dst_ny_non_midnight_d", pytz.timezone("America/New_York").localize(
        datetime(2021, 3, 14, 3, 0)), _TF_1D, False),  # post-spring-forward, !=00:00 UTC
    # Weekly fires on every midnight (midnight-of-day anchor, not Thursday-epoch).
    ("weekly_any_midnight", _UTC.localize(datetime(2021, 6, 16, 0, 0)), _TF_1W, True),
]


@pytest.mark.parametrize("label,ts,tf,expected", _CASES, ids=[c[0] for c in _CASES])
def test_aligned_boolean_equivalence(label, ts, tf, expected):
    """_aligned matches the fresh reference AND the hand-pinned expected boolean."""
    ref = _reference_aligned(ts, tf)
    got = _aligned(ts, tf)
    assert got == ref, f"{label}: _aligned={got} != reference={ref}"
    assert got is expected, f"{label}: _aligned={got} != expected={expected}"


@pytest.mark.parametrize("label,ts,tf,expected", _CASES, ids=[c[0] for c in _CASES])
def test_check_timeframe_delegates_to_aligned(label, ts, tf, expected):
    """check_timeframe returns booleans byte-identical to _aligned (delegation)."""
    assert check_timeframe(ts, tf) == _aligned(ts, tf)
    assert check_timeframe(ts, tf) is expected


def test_returns_native_bool():
    """The seam returns a real Python bool (not numpy/Decimal), per its signature."""
    ts = _UTC.localize(datetime(2021, 1, 1, 0, 0))
    assert isinstance(_aligned(ts, _TF_1D), bool)
    assert isinstance(check_timeframe(ts, _TF_1D), bool)
