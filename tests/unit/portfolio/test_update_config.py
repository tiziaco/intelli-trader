"""Canonical ``update_config`` contract tests for PortfolioHandler + Portfolio (COMP-02).

Covers the D-07/D-08/D-09 contract: ``update_config(self, updates: dict) -> None``
with recursive_merge -> model_validate -> atomic-swap, wrapping pydantic ValidationError
into ConfigurationError, re-deriving cached internals after the swap (Pitfall 1).

These methods are oracle-dark (never fire in the golden run) so they are validated
here by direct unit tests (D-11).
"""

from datetime import datetime, UTC
from decimal import Decimal
from queue import Queue

import pytest

from itrader.outils.dict_merge import recursive_merge
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.core.exceptions.base import ConfigurationError


# --- shared recursive_merge helper (WR-04 sibling preservation) -------------------

def test_recursive_merge_preserves_sibling_submodel_fields():
    """A partial nested update must preserve sibling fields, not replace the submodel."""
    merged = recursive_merge({"limits": {"a": 1, "b": 2}}, {"limits": {"a": 9}})
    assert merged == {"limits": {"a": 9, "b": 2}}


def test_recursive_merge_does_not_mutate_inputs():
    base = {"limits": {"a": 1, "b": 2}}
    updates = {"limits": {"a": 9}}
    recursive_merge(base, updates)
    assert base == {"limits": {"a": 1, "b": 2}}
    assert updates == {"limits": {"a": 9}}


def test_recursive_merge_replaces_non_dict_values():
    merged = recursive_merge({"x": [1, 2], "y": 1}, {"x": [3]})
    assert merged == {"x": [3], "y": 1}


# --- PortfolioHandler.update_config ------------------------------------------

@pytest.fixture
def handler():
    return PortfolioHandler(global_queue=Queue(), config_dir="settings", environment="test")


def test_handler_valid_update_swaps_config_and_rederives_cache(handler):
    """Valid update swaps config, re-derives max_portfolios cache, returns None."""
    result = handler.update_config({"limits": {"max_portfolios": 7}})
    assert result is None
    assert handler.config_data.limits.max_portfolios == 7
    assert handler.max_portfolios == 7  # Pitfall 1: cache re-derived


def test_handler_unknown_key_raises_configuration_error(handler):
    """Unknown key raises ConfigurationError (no longer returns False)."""
    with pytest.raises(ConfigurationError):
        handler.update_config({"totally_unknown_key": 123})


def test_handler_bad_value_raises_configuration_error(handler):
    """A bad value (wrong type) raises ConfigurationError wrapping pydantic ValidationError."""
    with pytest.raises(ConfigurationError):
        handler.update_config({"limits": {"max_portfolios": "not-an-int"}})


def test_handler_partial_nested_update_preserves_siblings(handler):
    """A single-field limits update preserves the other limits fields (WR-04)."""
    original_max_positions = handler.config_data.limits.max_positions
    handler.update_config({"limits": {"max_portfolios": 9}})
    assert handler.config_data.limits.max_portfolios == 9
    assert handler.config_data.limits.max_positions == original_max_positions


# --- Portfolio.update_config -------------------------------------------------

@pytest.fixture
def portfolio():
    return Portfolio(
        name="test_pf", exchange="paper",
        cash=Decimal("100000"), time=datetime.now(UTC),
    )


def test_portfolio_valid_update_swaps_config(portfolio):
    """Valid update swaps the config, returns None."""
    result = portfolio.update_config({"limits": {"max_positions": 7}})
    assert result is None
    assert portfolio.config.limits.max_positions == 7


def test_portfolio_unknown_key_raises_configuration_error(portfolio):
    with pytest.raises(ConfigurationError):
        portfolio.update_config({"totally_unknown_key": 123})


def test_portfolio_bad_value_raises_configuration_error(portfolio):
    with pytest.raises(ConfigurationError):
        portfolio.update_config({"limits": {"max_positions": "not-an-int"}})


def test_portfolio_partial_nested_update_preserves_siblings(portfolio):
    original_max_position_value = portfolio.config.limits.max_position_value
    portfolio.update_config({"limits": {"max_positions": 11}})
    assert portfolio.config.limits.max_positions == 11
    assert portfolio.config.limits.max_position_value == original_max_position_value


def test_max_leverage_rides_update_config(handler):
    """max_leverage survives recursive_merge -> model_validate -> atomic-swap (D-15).

    It is a TradingRules field, so the uniform update_config seam carries it with
    no special-casing — the swapped config_data reflects the new max_leverage.
    """
    assert handler.config_data.trading_rules.max_leverage == Decimal("1")
    result = handler.update_config({"trading_rules": {"max_leverage": Decimal("5")}})
    assert result is None
    assert handler.config_data.trading_rules.max_leverage == Decimal("5")


def test_max_leverage_below_floor_raises_configuration_error(handler):
    """max_leverage < 1 is rejected at validation (ge=1 floor, Plan 01)."""
    with pytest.raises(ConfigurationError):
        handler.update_config({"trading_rules": {"max_leverage": Decimal("0")}})


def test_max_leverage_update_preserves_sibling_trading_rules(handler):
    """A single max_leverage update preserves sibling TradingRules fields (WR-04)."""
    original_enable_margin = handler.config_data.trading_rules.enable_margin
    handler.update_config({"trading_rules": {"max_leverage": Decimal("3")}})
    assert handler.config_data.trading_rules.max_leverage == Decimal("3")
    assert handler.config_data.trading_rules.enable_margin == original_enable_margin
