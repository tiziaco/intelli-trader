"""Canonical ``update_config`` contract tests for OrderManager + OrderHandler (COMP-02).

Covers the D-05/D-07/D-08/D-09 contract over ``OrderConfig``: deep_merge ->
model_validate -> atomic-swap, wrapping pydantic ValidationError into
ConfigurationError, re-deriving the cached ``market_execution`` after the swap
(Pitfall 1), and the thin-facade delegation from OrderHandler to OrderManager
(CLAUDE.md handler/manager split).

Oracle-dark (D-11) — validated here by direct unit tests.
"""

from queue import Queue
from unittest.mock import Mock

import pytest

from itrader.order_handler.order_manager import OrderManager
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.core.enums import MarketExecution
from itrader.core.exceptions.base import ConfigurationError


# --- OrderManager.update_config ----------------------------------------------

@pytest.fixture
def manager():
    return OrderManager(InMemoryOrderStorage(), Mock(), market_execution="immediate")


def test_manager_valid_update_swaps_config_and_rederives_cache(manager):
    """Valid update swaps OrderConfig, re-derives the market_execution cache, returns None."""
    assert manager.market_execution is MarketExecution.IMMEDIATE
    result = manager.update_config({"market_execution": "next_bar"})
    assert result is None
    assert manager.order_config.market_execution is MarketExecution.NEXT_BAR
    assert manager.market_execution is MarketExecution.NEXT_BAR  # Pitfall 1: cache re-derived


def test_manager_unknown_key_raises_configuration_error(manager):
    """Unknown key rejected by OrderConfig extra='forbid' -> ConfigurationError."""
    with pytest.raises(ConfigurationError):
        manager.update_config({"totally_unknown_key": 1})


def test_manager_bad_value_raises_configuration_error(manager):
    """An invalid market_execution -> pydantic ValidationError wrapped into ConfigurationError."""
    with pytest.raises(ConfigurationError):
        manager.update_config({"market_execution": "not-a-valid-timing"})


# --- OrderHandler facade delegation ------------------------------------------

@pytest.fixture
def handler():
    q = Queue()
    ptf_handler = PortfolioHandler(q)
    ptf_handler.add_portfolio("test_ptf", "default", 10000)
    return OrderHandler(q, ptf_handler)


def test_handler_delegates_update_config_to_manager(handler):
    """Calling the facade's update_config mutates the manager's OrderConfig."""
    assert handler.order_manager.market_execution is MarketExecution.IMMEDIATE
    result = handler.update_config({"market_execution": "next_bar"})
    assert result is None
    assert handler.order_manager.order_config.market_execution is MarketExecution.NEXT_BAR
    # Handler's own cached mirror is re-synced too.
    assert handler.market_execution is MarketExecution.NEXT_BAR


def test_handler_unknown_key_raises_configuration_error(handler):
    with pytest.raises(ConfigurationError):
        handler.update_config({"totally_unknown_key": 1})
