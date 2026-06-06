"""
Model-level slippage tests (plan 06-04, M5-04/D-12).

Locks the Decimal-native slippage contract: Decimal factor, typed
ValidationError raises (the bool-and-silently-return-1.0 contract is dead,
T-06-13), and deterministic seeded jitter (Phase 2 D-11 seam).
"""

import random
from decimal import Decimal

import pytest

from itrader.core.exceptions import ValidationError
from itrader.core.money import to_money
from itrader.execution_handler.slippage_model.zero_slippage_model import ZeroSlippageModel
from itrader.execution_handler.slippage_model.fixed_slippage_model import FixedSlippageModel
from itrader.execution_handler.slippage_model.linear_slippage_model import LinearSlippageModel


# --- factor is Decimal --------------------------------------------------------


def test_zero_model_returns_decimal_one():
    factor = ZeroSlippageModel().calculate_slippage_factor(Decimal("10"), Decimal("100"))
    assert isinstance(factor, Decimal)
    assert factor == Decimal("1")


def test_fixed_model_factor_is_decimal():
    model = FixedSlippageModel(slippage_pct=0.01, random_variation=False)
    factor = model.calculate_slippage_factor(Decimal("10"), Decimal("100"), side="buy")
    assert isinstance(factor, Decimal)
    assert factor == Decimal("1") + Decimal("0.01") / Decimal("100")


def test_fixed_model_directional_without_variation():
    model = FixedSlippageModel(slippage_pct=0.01, random_variation=False)
    buy = model.calculate_slippage_factor(Decimal("10"), Decimal("100"), side="buy")
    sell = model.calculate_slippage_factor(Decimal("10"), Decimal("100"), side="sell")
    assert buy > Decimal("1")    # buys slip worse (higher price)
    assert sell < Decimal("1")   # sells slip worse (lower price)


def test_linear_model_factor_is_decimal():
    model = LinearSlippageModel(base_slippage_pct=0.01, size_impact_factor=0.00001,
                                max_slippage_pct=0.1, rng=random.Random(42))
    factor = model.calculate_slippage_factor(Decimal("10"), Decimal("100"), side="buy")
    assert isinstance(factor, Decimal)


def test_linear_model_caps_total_slippage():
    # Huge order value drives size impact past the cap — the factor is capped.
    model = LinearSlippageModel(base_slippage_pct=0.0, size_impact_factor=1.0,
                                max_slippage_pct=0.1, rng=random.Random(42))
    factor = model.calculate_slippage_factor(Decimal("1000000"), Decimal("100"), side="buy")
    assert factor == Decimal("1") + to_money(0.1) / Decimal("100")


# --- typed validation raises — NO silent 1.0 (T-06-13) -------------------------


@pytest.mark.parametrize("model", [
    FixedSlippageModel(slippage_pct=0.01, random_variation=False),
    LinearSlippageModel(rng=random.Random(1)),
])
def test_invalid_quantity_raises_not_neutral(model):
    with pytest.raises(ValidationError):
        model.calculate_slippage_factor(Decimal("0"), Decimal("100"), side="buy")
    with pytest.raises(ValidationError):
        model.calculate_slippage_factor(Decimal("-1"), Decimal("100"), side="buy")


@pytest.mark.parametrize("model", [
    FixedSlippageModel(slippage_pct=0.01, random_variation=False),
    LinearSlippageModel(rng=random.Random(1)),
])
def test_invalid_price_raises_not_neutral(model):
    with pytest.raises(ValidationError):
        model.calculate_slippage_factor(Decimal("10"), Decimal("0"), side="buy")
    with pytest.raises(ValidationError):
        model.calculate_slippage_factor(Decimal("10"), Decimal("-5"), side="buy")


def test_invalid_side_raises_not_neutral():
    model = FixedSlippageModel(slippage_pct=0.01, random_variation=False)
    with pytest.raises(ValidationError):
        model.calculate_slippage_factor(Decimal("10"), Decimal("100"), side="hold")


def test_invalid_order_type_raises_not_neutral():
    model = FixedSlippageModel(slippage_pct=0.01, random_variation=False)
    with pytest.raises(ValidationError):
        model.calculate_slippage_factor(
            Decimal("10"), Decimal("100"), side="buy", order_type="iceberg")


def test_validate_inputs_returns_none_on_valid_input():
    # The raise-contract: valid input -> None, invalid -> raise. No booleans.
    model = ZeroSlippageModel()
    assert model.validate_inputs(Decimal("10"), Decimal("100"), "buy", "market") is None


# --- seeded determinism (Phase 2 D-11 seam preserved) --------------------------


def test_fixed_jitter_deterministic_for_fixed_seed():
    a = FixedSlippageModel(slippage_pct=0.01, random_variation=True,
                           rng=random.Random(1234))
    b = FixedSlippageModel(slippage_pct=0.01, random_variation=True,
                           rng=random.Random(1234))
    factors_a = [a.calculate_slippage_factor(Decimal("10"), Decimal("100"), "buy")
                 for _ in range(5)]
    factors_b = [b.calculate_slippage_factor(Decimal("10"), Decimal("100"), "buy")
                 for _ in range(5)]
    assert factors_a == factors_b
    assert all(isinstance(f, Decimal) for f in factors_a)


def test_linear_jitter_deterministic_for_fixed_seed():
    a = LinearSlippageModel(base_slippage_pct=0.01, rng=random.Random(99))
    b = LinearSlippageModel(base_slippage_pct=0.01, rng=random.Random(99))
    factors_a = [a.calculate_slippage_factor(Decimal("10"), Decimal("100"), "sell")
                 for _ in range(5)]
    factors_b = [b.calculate_slippage_factor(Decimal("10"), Decimal("100"), "sell")
                 for _ in range(5)]
    assert factors_a == factors_b


def test_jitter_enters_decimal_via_to_money_exactly_once():
    # The float jitter from rng.uniform enters Decimal via to_money — the
    # factor equals 1 + Decimal(str(jitter))/100 for the same seeded draw.
    seed = 7
    model = FixedSlippageModel(slippage_pct=0.01, random_variation=True,
                               rng=random.Random(seed))
    expected_jitter = random.Random(seed).uniform(-0.01, 0.01)
    factor = model.calculate_slippage_factor(Decimal("10"), Decimal("100"), "buy")
    assert factor == Decimal("1") + to_money(expected_jitter) / Decimal("100")
