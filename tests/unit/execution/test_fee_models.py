"""
Model-level fee tests (plan 06-04, M5-04/D-12).

Locks the Decimal-native fee contract: pure-Decimal math, authoritative
maker/taker classification from real order context (D-11), and typed
ValidationError raises (no boolean validation contract, T-06-13).
"""

from decimal import Decimal

import pytest

from itrader.core.exceptions import ValidationError
from itrader.execution_handler.fee_model.base import FeeModel
from itrader.execution_handler.fee_model.zero_fee_model import ZeroFeeModel
from itrader.execution_handler.fee_model.percent_fee_model import PercentFeeModel
from itrader.execution_handler.fee_model.maker_taker_fee_model import MakerTakerFeeModel


# --- zero fee model ----------------------------------------------------------


def test_zero_model_returns_decimal_zero():
    fee = ZeroFeeModel().calculate_fee(Decimal("100"), Decimal("250"))
    assert isinstance(fee, Decimal)
    assert fee == Decimal("0")


def test_zero_model_validates_before_returning():
    with pytest.raises(ValidationError):
        ZeroFeeModel().calculate_fee(Decimal("-1"), Decimal("250"))


# --- percent fee model -------------------------------------------------------


def test_percent_math_exact_in_decimal():
    # 0.1% of (100 units @ 250) == Decimal("25") EXACTLY — no float artifact.
    model = PercentFeeModel(fee_rate=0.001)
    fee = model.calculate_fee(Decimal("100"), Decimal("250"))
    assert isinstance(fee, Decimal)
    assert fee == Decimal("25.000")
    assert fee == Decimal("100") * Decimal("250") * Decimal("0.001")


def test_percent_rates_held_as_decimal():
    # Constructor floats convert ONCE via to_money (Decimal(str(x))).
    model = PercentFeeModel(fee_rate=0.001, buy_rate=0.002, sell_rate=0.003)
    assert isinstance(model.fee_rate, Decimal)
    assert model.fee_rate == Decimal("0.001")
    assert model.buy_rate == Decimal("0.002")
    assert model.sell_rate == Decimal("0.003")


def test_percent_side_specific_rates():
    model = PercentFeeModel(fee_rate=0.001, sell_rate=0.002)
    buy_fee = model.calculate_fee(Decimal("10"), Decimal("100"), side="buy")
    sell_fee = model.calculate_fee(Decimal("10"), Decimal("100"), side="sell")
    assert buy_fee == Decimal("1.000")
    assert sell_fee == Decimal("2.000")


def test_percent_negative_rate_raises():
    with pytest.raises(ValueError):
        PercentFeeModel(fee_rate=-0.001)


# --- maker/taker fee model ---------------------------------------------------


def test_maker_taker_is_maker_true_overrides_order_type_string():
    # D-11: is_maker is AUTHORITATIVE — maker rate applies even when the
    # order_type string says "market".
    model = MakerTakerFeeModel(maker_rate=0.0005, taker_rate=0.001)
    fee = model.calculate_fee(Decimal("100"), Decimal("250"),
                              order_type="market", is_maker=True)
    assert fee == Decimal("100") * Decimal("250") * Decimal("0.0005")


def test_maker_taker_is_maker_false_overrides_order_type_string():
    # Taker rate applies even when the order_type string says "limit".
    model = MakerTakerFeeModel(maker_rate=0.0005, taker_rate=0.001)
    fee = model.calculate_fee(Decimal("100"), Decimal("250"),
                              order_type="limit", is_maker=False)
    assert fee == Decimal("100") * Decimal("250") * Decimal("0.001")


def test_maker_taker_string_fallback_when_no_context():
    # The order_type-string fallback survives for direct callers (D-11).
    model = MakerTakerFeeModel(maker_rate=0.0005, taker_rate=0.001)
    market_fee = model.calculate_fee(Decimal("10"), Decimal("100"), order_type="market")
    limit_fee = model.calculate_fee(Decimal("10"), Decimal("100"), order_type="limit")
    assert market_fee == Decimal("10") * Decimal("100") * Decimal("0.001")   # taker
    assert limit_fee == Decimal("10") * Decimal("100") * Decimal("0.0005")  # maker


def test_maker_taker_stop_defaults_to_taker():
    # Conservative default: a triggered stop removes liquidity.
    model = MakerTakerFeeModel(maker_rate=0.0005, taker_rate=0.001)
    fee = model.calculate_fee(Decimal("10"), Decimal("100"), order_type="stop")
    assert fee == Decimal("10") * Decimal("100") * Decimal("0.001")


def test_maker_taker_rates_held_as_decimal():
    model = MakerTakerFeeModel(maker_rate=0.0005, taker_rate=0.001)
    assert isinstance(model.maker_rate, Decimal)
    assert isinstance(model.taker_rate, Decimal)
    assert model.maker_rate == Decimal("0.0005")
    assert model.taker_rate == Decimal("0.001")


# --- typed validation raises (T-06-13) ----------------------------------------


@pytest.mark.parametrize("model", [
    ZeroFeeModel(),
    PercentFeeModel(fee_rate=0.001),
    MakerTakerFeeModel(),
])
def test_validate_raises_on_non_positive_quantity(model):
    with pytest.raises(ValidationError):
        model.calculate_fee(Decimal("0"), Decimal("100"))
    with pytest.raises(ValidationError):
        model.calculate_fee(Decimal("-5"), Decimal("100"))


@pytest.mark.parametrize("model", [
    ZeroFeeModel(),
    PercentFeeModel(fee_rate=0.001),
    MakerTakerFeeModel(),
])
def test_validate_raises_on_non_positive_price(model):
    with pytest.raises(ValidationError):
        model.calculate_fee(Decimal("10"), Decimal("0"))
    with pytest.raises(ValidationError):
        model.calculate_fee(Decimal("10"), Decimal("-100"))


def test_validate_raises_on_unknown_side():
    with pytest.raises(ValidationError):
        ZeroFeeModel().calculate_fee(Decimal("10"), Decimal("100"), side="hold")


def test_validate_raises_on_unknown_order_type():
    with pytest.raises(ValidationError):
        ZeroFeeModel().calculate_fee(Decimal("10"), Decimal("100"), order_type="iceberg")


def test_validate_inputs_returns_none_on_valid_input():
    # The raise-contract: valid input -> None, invalid -> raise. No booleans.
    assert ZeroFeeModel().validate_inputs(Decimal("10"), Decimal("100")) is None


# --- D-10: TieredFeeModel is deleted ------------------------------------------


def test_tiered_fee_model_is_gone():
    import itrader.execution_handler.fee_model as fee_pkg
    assert not hasattr(fee_pkg, "TieredFeeModel")
    assert "TieredFeeModel" not in fee_pkg.__all__
    with pytest.raises(ModuleNotFoundError):
        import itrader.execution_handler.fee_model.tiered_fee_model  # noqa: F401
