"""Aggregated config-model import home (M2-06).

Single module re-exporting every Pydantic config model from the per-domain modules
(``portfolio``/``system``/``exchange``). Lets consumers and tests import any model
from one place (``from itrader.config.models import PortfolioConfig``) without
depending on the per-domain module layout.
"""

from itrader.config.exchange import (
    ConnectionSettings,
    ExchangeConfig,
    ExchangeLimits,
    ExchangeVenue,
    FailureSimulation,
    FeeModelConfig,
    FeeModelType,
    SlippageModelConfig,
    SlippageModelType,
    get_exchange_preset,
    list_available_exchange_presets,
)
from itrader.config.portfolio import (
    EventSettings,
    PortfolioConfig,
    PortfolioLimits,
    PortfolioType,
    RiskLevel,
    RiskManagement,
    TradingRules,
    ValidationSettings,
    get_portfolio_preset,
)
from itrader.config.stream import (
    FeedProviderSettings,
    StreamSettings,
)
from itrader.config.system import (
    Environment,
    LogLevel,
    SystemConfig,
    SystemSettings,
    UniverseConfig,
)

__all__ = [
    # Portfolio
    "PortfolioConfig", "PortfolioType", "RiskLevel", "PortfolioLimits",
    "RiskManagement", "TradingRules", "ValidationSettings", "EventSettings",
    "get_portfolio_preset",
    # System
    "SystemConfig", "SystemSettings", "UniverseConfig", "Environment", "LogLevel",
    # Stream / feed-provider
    "StreamSettings", "FeedProviderSettings",
    # Exchange
    "ExchangeConfig", "ExchangeVenue", "FeeModelType", "SlippageModelType",
    "FeeModelConfig", "SlippageModelConfig", "ExchangeLimits", "FailureSimulation",
    "ConnectionSettings", "get_exchange_preset", "list_available_exchange_presets",
]
