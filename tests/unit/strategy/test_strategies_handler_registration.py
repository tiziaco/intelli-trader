"""Contract tests for ``StrategiesHandler.add_strategy`` registration gate.

SHORT-01 / D-07 — the two-flag registration gate. A non-``LONG_ONLY``
strategy (``SHORT_ONLY`` / ``LONG_SHORT``) is admissible ONLY when BOTH
``allow_short_selling`` AND ``enable_margin`` are on; with either flag off the
guard raises a ``ValueError`` naming both flags. Both flags default OFF, so the
golden ``LONG_ONLY`` path (SMA_MACD) is unaffected and the oracle stays
byte-exact (134 / ``46189.87730727451``).

``enable_margin`` is coupled into the gate because it turns on the
lock-and-settle model (Phase 2 D-09) — the only model that can represent a
short (a short has no notional to "spend"; spot debit-notional cannot express
it). Coupled with the default ``max_leverage == 1`` this gives
fully-collateralized shorts (no leverage); levered shorts are a separate opt-in
dial (D-07).

Folder-derived ``unit`` marker only (tests/conftest.py applies it).
"""

from decimal import Decimal
from queue import Queue

import pytest

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit


def _strategy(direction: TradingDirection) -> SMAMACDStrategy:
    """Construct a reference strategy carrying the requested direction.

    The registration gate keys off ``strategy.direction`` alone — the concrete
    strategy class is irrelevant, SMA_MACD is reused as the proven analog.
    """
    return SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSDT"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=direction,
        allow_increase=False,
    )


def _make_handler(
    *, allow_short_selling: bool = False, enable_margin: bool = False
) -> StrategiesHandler:
    return StrategiesHandler(
        Queue(),
        _StubFeed(),
        InMemorySignalStore(),
        allow_short_selling=allow_short_selling,
        enable_margin=enable_margin,
    )


class _StubFeed:
    """A minimal BarFeed stand-in — add_strategy never touches the feed."""

    def symbols(self) -> list[str]:
        return ["BTCUSDT"]


def test_short_registration_short_only_admitted_when_both_flags_on() -> None:
    """D-07: both flags on -> a SHORT_ONLY strategy registers."""
    handler = _make_handler(allow_short_selling=True, enable_margin=True)
    strategy = _strategy(TradingDirection.SHORT_ONLY)

    handler.add_strategy(strategy)

    assert strategy in handler.strategies


def test_short_registration_long_short_admitted_when_both_flags_on() -> None:
    """D-07: both flags on -> a LONG_SHORT strategy registers."""
    handler = _make_handler(allow_short_selling=True, enable_margin=True)
    strategy = _strategy(TradingDirection.LONG_SHORT)

    handler.add_strategy(strategy)

    assert strategy in handler.strategies


def test_short_registration_rejected_when_short_selling_off() -> None:
    """D-07: enable_margin on but allow_short_selling off -> raises naming both."""
    handler = _make_handler(allow_short_selling=False, enable_margin=True)
    strategy = _strategy(TradingDirection.SHORT_ONLY)

    with pytest.raises(ValueError) as exc:
        handler.add_strategy(strategy)

    message = str(exc.value)
    assert "allow_short_selling" in message
    assert "enable_margin" in message


def test_short_registration_rejected_when_margin_off() -> None:
    """D-07: allow_short_selling on but enable_margin off -> raises naming both."""
    handler = _make_handler(allow_short_selling=True, enable_margin=False)
    strategy = _strategy(TradingDirection.SHORT_ONLY)

    with pytest.raises(ValueError) as exc:
        handler.add_strategy(strategy)

    message = str(exc.value)
    assert "allow_short_selling" in message
    assert "enable_margin" in message


def test_short_registration_default_off_long_only_ok_short_rejected() -> None:
    """Byte-exact default: both flags off -> LONG_ONLY registers, SHORT_ONLY raises.

    This is the oracle-preserving default (SMA_MACD is LONG_ONLY): the golden
    path never trips the guard, and a non-LONG_ONLY strategy is rejected loudly.
    """
    handler = _make_handler()  # both flags default off

    long_only = _strategy(TradingDirection.LONG_ONLY)
    handler.add_strategy(long_only)
    assert long_only in handler.strategies

    short_only = _strategy(TradingDirection.SHORT_ONLY)
    with pytest.raises(ValueError):
        handler.add_strategy(short_only)
