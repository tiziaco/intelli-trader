"""Canonical ``update_config`` contract tests for PortfolioHandler + Portfolio (COMP-02).

Covers the D-07/D-08/D-09 contract: ``update_config(self, updates: dict) -> None``
with deep_merge -> model_validate -> atomic-swap, wrapping pydantic ValidationError
into ConfigurationError, re-deriving cached internals after the swap (Pitfall 1).

These methods are oracle-dark (never fire in the golden run) so they are validated
here by direct unit tests (D-11).
"""

from datetime import datetime, UTC
from decimal import Decimal
from queue import Queue

import pytest

from itrader.config import deep_merge
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.core.exceptions.base import ConfigurationError


# --- shared deep_merge helper (WR-04 sibling preservation) -------------------

def test_deep_merge_preserves_sibling_submodel_fields():
    """A partial nested update must preserve sibling fields, not replace the submodel."""
    merged = deep_merge({"limits": {"a": 1, "b": 2}}, {"limits": {"a": 9}})
    assert merged == {"limits": {"a": 9, "b": 2}}


def test_deep_merge_does_not_mutate_inputs():
    base = {"limits": {"a": 1, "b": 2}}
    updates = {"limits": {"a": 9}}
    deep_merge(base, updates)
    assert base == {"limits": {"a": 1, "b": 2}}
    assert updates == {"limits": {"a": 9}}


def test_deep_merge_replaces_non_dict_values():
    merged = deep_merge({"x": [1, 2], "y": 1}, {"x": [3]})
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
        user_id=1, name="test_pf", exchange="simulated",
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


def test_max_leverage_wave0_stub():
    pytest.skip("Wave 0 stub — implemented in Phase 2 plan 05")
