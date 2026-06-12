"""Class-attribute authoring-surface tests (Plan 02-03, D-05..D-08).

The pydantic strategy-config layer is DELETED (D-01,
Plan 02-02). A strategy now DECLARES its params as class attributes and the base
engine (``_apply_params``) applies ``**kwargs`` over them: kwargs override a
class-attr default; an unknown kwarg raises ``UnknownParamError``; a missing
required base attr raises ``MissingParamError``; the three ``_COERCE`` enum
fields (timeframe / order_type / direction) coerce a str off their annotation,
while every other knob is left as supplied (never silently int()-ed). 4-space
indentation (tests house style).
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from itrader.core.enums import Timeframe, TradingDirection
from itrader.core.exceptions.strategy import MissingParamError, UnknownParamError
from itrader.core.sizing import FractionOfCash
from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategy
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy


def _golden_sizing() -> FractionOfCash:
    """The golden string-path Decimal literal (Pitfall 4 — byte-exact)."""
    return FractionOfCash(Decimal("0.95"))


def test_reject_unknown_kwarg_raises() -> None:
    """An unknown construction kwarg is rejected loudly (D-06, T-02-01)."""
    with pytest.raises(UnknownParamError):
        SMAMACDStrategy(
            timeframe="1d",
            tickers=["BTCUSD"],
            sizing_policy=_golden_sizing(),
            not_a_real_param=123,
        )


def test_missing_required_param_raises() -> None:
    """Omitting a required base attr (sizing_policy) is rejected (D-07, T-02-02).

    ``EmptyStrategy`` does NOT pin ``sizing_policy``/``tickers`` as class attrs
    (unlike ``SMAMACDStrategy``), so omitting ``sizing_policy`` leaves the bare
    base annotation with no value/no prior — the engine raises ``MissingParamError``.
    """
    with pytest.raises(MissingParamError):
        EmptyStrategy(
            timeframe="1d",
            tickers=["BTCUSD"],
        )


def test_kwargs_override_class_attr_default() -> None:
    """A kwarg overrides a class-attr default (D-05)."""
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
        short_window=30,
    )
    assert strategy.short_window == 30


def test_timeframe_str_coerces_to_timedelta_on_instance() -> None:
    """``timeframe="1d"`` coerces to an enum, then resolves to a timedelta (D-08, Pitfall 1)."""
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
    )
    # self.timeframe is the RESOLVED consumer type (timedelta), not the enum.
    assert isinstance(strategy.timeframe, timedelta)
    # The stashed enum/alias remain available for serialization.
    assert strategy._timeframe is Timeframe.D1
    assert strategy.timeframe_alias == "1d"


def test_non_enum_knob_not_coerced_to_int() -> None:
    """A non-enum knob (max_positions="3") is NOT int-coerced — stays a str (D-08).

    Only the three ``_COERCE`` enum fields (timeframe/order_type/direction) coerce.
    ``max_positions`` is a plain base knob: a str kwarg is applied verbatim, never
    silently ``int()``-ed (the engine does not guess types off the annotation).
    """
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
        max_positions="3",
    )
    assert strategy.max_positions == "3"
    assert isinstance(strategy.max_positions, str)


def test_str_direction_coerces_to_enum() -> None:
    """The ``direction`` knob is a _COERCE field — a str coerces to the enum (D-08)."""
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
        direction="long_only",
    )
    assert strategy.direction is TradingDirection.LONG_ONLY
