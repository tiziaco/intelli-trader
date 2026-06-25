"""BarEvent payload contract (M5-02, D-14/D-15).

The legacy ``get_last_*`` accessor tests died with the accessors: the payload
is now ``dict[str, Bar]`` — one immutable Decimal OHLCV struct per ticker,
absent key = no bar at T (sparse universe), direct field access only.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from itrader.core.bar import Bar
from itrader.events_handler.events import BarEvent

pytestmark = pytest.mark.unit


@pytest.fixture
def bar():
    t = datetime(2024, 1, 1)
    bars = {
        "BTCUSDT": Bar(time=t, open=Decimal("30"), high=Decimal("60"),
                       low=Decimal("20"), close=Decimal("40"), volume=Decimal("1000"))
    }
    return BarEvent(time=t, bars=bars)


def test_payload_fields_are_decimal(bar):
    # D-14: the per-ticker payload carries Decimal OHLCV, no pandas.
    struct = bar.bars["BTCUSDT"]
    assert isinstance(struct, Bar)
    assert isinstance(struct.close, Decimal)
    assert struct.open == Decimal("30")
    assert struct.high == Decimal("60")
    assert struct.low == Decimal("20")
    assert struct.close == Decimal("40")
    assert struct.volume == Decimal("1000")


def test_missing_ticker_absent_from_dict(bar):
    # Sparse-universe contract: a ticker with no bar at T is ABSENT —
    # consumers guard membership with .get()/in, never a None accessor.
    assert "ETHUSDT" not in bar.bars
    assert bar.bars.get("ETHUSDT") is None


def test_bar_event_is_frozen(bar):
    with pytest.raises(AttributeError):
        bar.bars = {}  # type: ignore[misc]


def test_payload_bar_struct_is_frozen(bar):
    # Immutability reaches INTO the payload: the Bar struct itself is frozen.
    with pytest.raises(AttributeError):
        bar.bars["BTCUSDT"].close = Decimal("99")  # type: ignore[misc]


def test_no_accessor_methods_exist(bar):
    # FR1: the four hasattr-ladder accessors are deleted, not deprecated.
    for name in ("get_last_close", "get_last_open", "get_last_high", "get_last_low"):
        assert not hasattr(bar, name)
