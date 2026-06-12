"""OrderConfig model tests (D-05, RESEARCH Trap 5 / Assumption A1).

Pins the order-domain config model that folds the loose stringly-typed
``OrderManager`` ctor param (``market_execution: str | MarketExecution =
"immediate"``) into a thin Pydantic model:

  1. COERCION EQUIVALENCE (Trap 5 / A1): a string ``"immediate"`` validates to
     the ``MarketExecution.IMMEDIATE`` enum MEMBER (not a stored str) — byte-
     identical to today's ctor coercion ``MarketExecution(market_execution)``.
  2. DEFAULT: ``OrderConfig()`` / ``OrderConfig.default()`` reproduce the
     backtest default ``"immediate"``.
  3. ``extra="forbid"``: an unknown key raises pydantic ``ValidationError``
     (mass-assignment defense, T-04-01).
  4. Enum-member pass-through is a no-op.
"""

import pytest

import pydantic
from itrader.config.order import OrderConfig
from itrader.core.enums import MarketExecution

pytestmark = pytest.mark.unit


def test_string_immediate_coerces_to_enum_member():
    """Trap 5 / A1: model_validate of the string yields the enum MEMBER, not a str."""
    config = OrderConfig.model_validate({"market_execution": "immediate"})
    assert config.market_execution is MarketExecution.IMMEDIATE


def test_string_next_bar_coerces_to_enum_member():
    """The other valid string value coerces to its member too."""
    config = OrderConfig.model_validate({"market_execution": "next_bar"})
    assert config.market_execution is MarketExecution.NEXT_BAR


def test_default_reproduces_immediate():
    """OrderConfig() default reproduces the backtest default ('immediate')."""
    assert OrderConfig().market_execution is MarketExecution.IMMEDIATE


def test_default_classmethod_reproduces_immediate():
    """OrderConfig.default() reproduces the backtest default ('immediate')."""
    assert OrderConfig.default().market_execution is MarketExecution.IMMEDIATE


def test_enum_member_passthrough_is_noop():
    """Passing an existing MarketExecution member stores it unchanged."""
    config = OrderConfig(market_execution=MarketExecution.IMMEDIATE)
    assert config.market_execution is MarketExecution.IMMEDIATE


def test_unknown_key_raises_validation_error():
    """extra='forbid' rejects an unknown key (mass-assignment defense, T-04-01)."""
    with pytest.raises(pydantic.ValidationError):
        OrderConfig.model_validate({"bogus": 1})
