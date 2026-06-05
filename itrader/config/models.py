"""Aggregated config-model import home (M2-06).

Single module re-exporting every Pydantic config model from the per-domain modules
(``portfolio``/``trading``/``data``/``system``/``exchange``). Lets consumers and tests
import any model from one place (``from itrader.config.models import PortfolioConfig``)
without depending on the per-domain module layout.
"""

from itrader.config.data import (
    DataConfig,
    DataFeedConfig,
    DataFrequency,
    DataSource,
    DataSourceConfig,
    ProcessingConfig,
    RealTimeConfig,
    StorageConfig,
    StorageType,
)
from itrader.config.exchange import (
    ConnectionSettings,
    ExchangeConfig,
    ExchangeLimits,
    ExchangeType,
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
from itrader.config.system import (
    Environment,
    LogLevel,
    MonitoringSettings,
    PerformanceSettings,
    SystemConfig,
)
from itrader.config.trading import (
    ExecutionMode,
    ExecutionSettings,
    FeeStructure,
    OrderDefaults,
    OrderType,
    RiskControls,
    StrategySettings,
    TimeInForce,
    TradingConfig,
)

__all__ = [
    # Portfolio
    "PortfolioConfig", "PortfolioType", "RiskLevel", "PortfolioLimits",
    "RiskManagement", "TradingRules", "ValidationSettings", "EventSettings",
    "get_portfolio_preset",
    # Trading
    "TradingConfig", "OrderType", "TimeInForce", "ExecutionMode", "OrderDefaults",
    "ExecutionSettings", "RiskControls", "FeeStructure", "StrategySettings",
    # Data
    "DataConfig", "DataSource", "DataFrequency", "StorageType", "DataSourceConfig",
    "DataFeedConfig", "StorageConfig", "ProcessingConfig", "RealTimeConfig",
    # System
    "SystemConfig", "Environment", "LogLevel", "PerformanceSettings",
    "MonitoringSettings",
    # Exchange
    "ExchangeConfig", "ExchangeType", "FeeModelType", "SlippageModelType",
    "FeeModelConfig", "SlippageModelConfig", "ExchangeLimits", "FailureSimulation",
    "ConnectionSettings", "get_exchange_preset", "list_available_exchange_presets",
]
