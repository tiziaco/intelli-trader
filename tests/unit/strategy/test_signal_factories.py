"""Unit coverage for the strategy→signal authoring factories (05-01, SIG-01/SIG-02).

The six buy/sell sugar methods on ``Strategy`` are the only genuinely-new
authoring surface in Phase 5 (D-01). These tests pin:

- the four typed factories (``buy_limit``/``buy_stop``/``sell_limit``/
  ``sell_stop``) return the right ``(action, order_type, entry_price)`` and
  thread ``sl``/``tp``/``exit_fraction`` through;
- ``price`` is required + keyword-only on every typed factory — omitting it
  raises ``TypeError`` (illegal ``(order_type, price)`` combos are
  unrepresentable by construction, D-01/D-04);
- plain ``buy()``/``sell()`` stay MARKET byte-exact: ``order_type=MARKET`` and
  ``entry_price=None`` (no ``price`` param);
- ``to_dict()`` no longer emits an ``"order_type"`` key (the per-instance attr
  is retired, D-01).
"""

from decimal import Decimal

import pytest

from itrader.core.enums import OrderType, Side
from itrader.core.money import to_money
from itrader.core.sizing import FractionOfCash, SignalIntent, TradingDirection
from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategy


_TICKER = "BTCUSDT"


def _strategy() -> EmptyStrategy:
    """A minimal concrete Strategy used purely to exercise the factory sugar."""
    return EmptyStrategy(
        timeframe="1d",
        tickers=[_TICKER],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
    )


# --- typed factories: action / order_type / entry_price ----------------------


def test_buy_limit_yields_limit_buy_intent() -> None:
    intent = _strategy().buy_limit(_TICKER, price=Decimal("100"))
    assert isinstance(intent, SignalIntent)
    assert intent.action is Side.BUY
    assert intent.order_type is OrderType.LIMIT
    assert intent.entry_price == to_money(Decimal("100"))


def test_buy_stop_yields_stop_buy_intent() -> None:
    intent = _strategy().buy_stop(_TICKER, price=Decimal("100"))
    assert intent.action is Side.BUY
    assert intent.order_type is OrderType.STOP
    assert intent.entry_price == to_money(Decimal("100"))


def test_sell_limit_yields_limit_sell_intent() -> None:
    intent = _strategy().sell_limit(_TICKER, price=Decimal("100"))
    assert intent.action is Side.SELL
    assert intent.order_type is OrderType.LIMIT
    assert intent.entry_price == to_money(Decimal("100"))


def test_sell_stop_yields_stop_sell_intent() -> None:
    intent = _strategy().sell_stop(_TICKER, price=Decimal("100"))
    assert intent.action is Side.SELL
    assert intent.order_type is OrderType.STOP
    assert intent.entry_price == to_money(Decimal("100"))


# --- price is required + keyword-only on every typed factory -----------------


@pytest.mark.parametrize(
    "method_name",
    ["buy_limit", "buy_stop", "sell_limit", "sell_stop"],
)
def test_typed_factory_requires_price(method_name: str) -> None:
    method = getattr(_strategy(), method_name)
    with pytest.raises(TypeError):
        method(_TICKER)


@pytest.mark.parametrize(
    "method_name",
    ["buy_limit", "buy_stop", "sell_limit", "sell_stop"],
)
def test_typed_factory_price_is_keyword_only(method_name: str) -> None:
    method = getattr(_strategy(), method_name)
    # price is keyword-only: a positional second arg must not bind to it.
    with pytest.raises(TypeError):
        method(_TICKER, Decimal("100"))


# --- typed factory threads sl / tp / exit_fraction ---------------------------


def test_typed_factory_threads_sl_tp_exit_fraction() -> None:
    intent = _strategy().buy_limit(
        _TICKER,
        price=Decimal("100"),
        sl=Decimal("90"),
        tp=Decimal("120"),
        exit_fraction=Decimal("0.5"),
    )
    assert intent.stop_loss == to_money(Decimal("90"))
    assert intent.take_profit == to_money(Decimal("120"))
    assert intent.exit_fraction == Decimal("0.5")


def test_typed_factory_float_price_enters_via_to_money() -> None:
    # to_money(x) -> Decimal(str(x)); a raw Decimal(float) would be a defect.
    intent = _strategy().buy_limit(_TICKER, price=0.1)
    assert intent.entry_price == to_money(0.1)
    assert intent.entry_price == Decimal("0.1")


# --- plain buy()/sell() stay MARKET byte-exact -------------------------------


def test_buy_is_market_with_no_entry_price() -> None:
    intent = _strategy().buy(_TICKER)
    assert intent.action is Side.BUY
    assert intent.order_type is OrderType.MARKET
    assert intent.entry_price is None


def test_sell_is_market_with_no_entry_price() -> None:
    intent = _strategy().sell(_TICKER)
    assert intent.action is Side.SELL
    assert intent.order_type is OrderType.MARKET
    assert intent.entry_price is None


def test_buy_threads_sl_tp() -> None:
    intent = _strategy().buy(_TICKER, sl=Decimal("90"), tp=Decimal("120"))
    assert intent.stop_loss == to_money(Decimal("90"))
    assert intent.take_profit == to_money(Decimal("120"))
    assert intent.entry_price is None


# --- to_dict drops the retired order_type key --------------------------------


def test_to_dict_has_no_order_type_key() -> None:
    assert "order_type" not in _strategy().to_dict()
