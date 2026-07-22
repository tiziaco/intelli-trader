"""Canonical ``update_config`` contract tests for SimulatedExchange + ExecutionHandler (COMP-02).

Covers the D-07/D-08/D-09 contract: ``update_config(self, updates: dict) -> None``
with recursive_merge -> model_validate -> atomic-swap, ConfigurationError wrapping, the
Pitfall 1 cache re-derivations (fee/slippage models, size caches as Decimal,
failure simulation, supported_symbols), the Pitfall 2 ``configure()`` fix, and the
Trap 1 symbol-set replacement/sibling-preservation property.

Oracle-dark (D-11) — validated here by direct unit tests.
"""

from decimal import Decimal
from queue import Queue

import pytest

from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.execution_handler.execution_handler import (
    DEFAULT_ACCOUNT_ID,
    ExecutionHandler,
)
from itrader.config import FeeModelType, SlippageModelType
from itrader.execution_handler.fee_model.percent_fee_model import PercentFeeModel
from itrader.execution_handler.slippage_model.linear_slippage_model import LinearSlippageModel
from itrader.core.exceptions.base import ConfigurationError


@pytest.fixture
def exchange():
    return SimulatedExchange(Queue())


# --- canonical contract ------------------------------------------------------

def test_valid_limits_update_rederives_min_order_size_as_decimal(exchange):
    """A valid limits update swaps config + re-derives the Decimal size cache."""
    result = exchange.update_config({"limits": {"min_order_size": "5"}})
    assert result is None
    assert exchange._min_order_size == Decimal("5")
    assert isinstance(exchange._min_order_size, Decimal)  # Decimal, no float


def test_fee_model_change_reinits_fee_model(exchange):
    """A fee-model change via update_config re-inits the fee model (Pitfall 1)."""
    exchange.update_config({"fee_model": {"model_type": "percent", "fee_rate": "0.002"}})
    assert exchange.config.fee_model.model_type is FeeModelType.PERCENT
    assert isinstance(exchange.fee_model, PercentFeeModel)


def test_slippage_model_change_reinits_slippage_model(exchange):
    exchange.update_config({"slippage_model": {"model_type": "linear", "base_slippage_pct": "0.02"}})
    assert exchange.config.slippage_model.model_type is SlippageModelType.LINEAR
    assert isinstance(exchange.slippage_model, LinearSlippageModel)


def test_failure_simulation_change_rederives_caches(exchange):
    exchange.update_config({"failure_simulation": {"simulate_failures": True, "failure_rate": "0.05"}})
    assert exchange.simulate_failures is True
    assert exchange.failure_rate == 0.05


def test_unknown_key_raises_configuration_error(exchange):
    """Unknown key rejected by extra='forbid' -> ConfigurationError."""
    with pytest.raises(ConfigurationError):
        exchange.update_config({"totally_unknown_key": 1})


def test_bad_value_raises_configuration_error(exchange):
    """Bad value -> pydantic ValidationError wrapped into ConfigurationError."""
    with pytest.raises(ConfigurationError):
        exchange.update_config({"limits": {"min_order_size": "not-a-number"}})


# --- Pitfall 2: configure() Protocol method ----------------------------------

def test_configure_returns_true_on_valid_dict(exchange):
    """configure() returns True on a valid dict (internally calls update_config(config))."""
    assert exchange.configure({"failure_simulation": {"simulate_failures": True}}) is True
    assert exchange.simulate_failures is True


def test_configure_returns_false_on_bad_dict(exchange):
    """configure() catches ConfigurationError (not ValueError) -> returns False."""
    assert exchange.configure({"unknown_key": 1}) is False


# --- Trap 1: symbol-set replacement / sibling preservation -------------------

def test_update_config_omitting_supported_symbols_preserves_the_set(exchange):
    """An update that omits supported_symbols must NOT wipe the construction-seeded set.

    _supported_symbols is re-derived from config.limits by REPLACEMENT, so the
    recursive_merge sibling-preservation is what keeps a known ticker admitting after
    an unrelated limits update (Trap 1 / T-04-08).
    """
    seeded = set(exchange.get_supported_symbols())
    assert "BTCUSDT" in seeded  # default preset member
    # An update touching only min_order_size omits supported_symbols.
    exchange.update_config({"limits": {"min_order_size": "5"}})
    # The full set survives the replacement-style re-derive.
    assert exchange.get_supported_symbols() == seeded
    assert exchange.validate_symbol("BTCUSDT")


# --- ExecutionHandler delegation ---------------------------------------------

@pytest.fixture
def handler():
    return ExecutionHandler(Queue())


def test_execution_handler_delegates_to_exchange(handler):
    """ExecutionHandler.update_config routes to the simulated exchange."""
    result = handler.update_config({"limits": {"min_order_size": "7"}})
    assert result is None
    simulated = handler.exchanges.get(("paper", DEFAULT_ACCOUNT_ID))
    assert simulated._min_order_size == Decimal("7")


def test_execution_handler_unknown_key_raises(handler):
    with pytest.raises(ConfigurationError):
        handler.update_config({"totally_unknown_key": 1})
