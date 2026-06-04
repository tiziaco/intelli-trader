"""
Configuration management system with domain-based architecture.

This module provides a clean, domain-based configuration system with:
- Portfolio configurations and presets
- Trading execution settings
- Data source and feed management
- System-level settings and logging
- Core registry and provider infrastructure
"""

# Core infrastructure
from .core import (
    ConfigRegistry, ConfigProvider, FileConfigProvider, RuntimeConfigProvider,
    ConfigValidator, SchemaValidator, BusinessValidator, ValidationError, ValidationResult
)

# Domain configurations
from .portfolio import (
    PortfolioConfig, PortfolioType, RiskLevel, PortfolioLimits, RiskManagement, TradingRules,
    validate_portfolio_config, get_portfolio_preset, list_available_presets
)

from .trading import (
    TradingConfig, OrderType, TimeInForce, ExecutionMode,
    OrderDefaults, ExecutionSettings, RiskControls, FeeStructure, StrategySettings,
    validate_trading_config
)

from .data import (
    DataConfig, DataSource, DataFrequency, StorageType,
    DataSourceConfig, DataFeedConfig, StorageConfig, ProcessingConfig, RealTimeConfig
)

from .system import (
    SystemConfig, Environment, PerformanceSettings, SecuritySettings,
    DatabaseSettings, NotificationSettings, MonitoringSettings,
    LoggingConfig, get_default_logging_config
)

from .exchange import (
    ExchangeConfig, ExchangeType, FeeModelType, SlippageModelType,
    FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation,
    ConnectionSettings, validate_exchange_config, get_exchange_preset,
    list_available_exchange_presets
)

# Re-export flat-module config names (M1-01 minimal fix).
#
# The flat module ``itrader/config.py`` defines ``FORBIDDEN_SYMBOLS``, ``TIMEZONE``,
# and ``Config``, but this package directory (``itrader/config/``) shadows it for
# ``from itrader.config import X``. Several backtest-path consumers still import the
# flat names (e.g. ``CCXT.py``: ``from itrader.config import FORBIDDEN_SYMBOLS`` and
# ``config.TIMEZONE``; ``data_provider.py``/``time_parser.py``: ``config.TIMEZONE``).
# We load the shadowed flat module by file path and re-export the three names so the
# import cascade resolves without modifying the flat ``config.py``. The real config
# collapse is deferred to M2-06.
import importlib.util as _importlib_util
import os as _os

_flat_config_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "config.py")
_flat_spec = _importlib_util.spec_from_file_location("itrader._flat_config", _flat_config_path)
_flat_config = _importlib_util.module_from_spec(_flat_spec)
_flat_spec.loader.exec_module(_flat_config)

FORBIDDEN_SYMBOLS = _flat_config.FORBIDDEN_SYMBOLS
Config = _flat_config.Config
# ``TIMEZONE`` lives only as a ``Config`` class attribute in the flat module
# (value ``'Europe/Paris'``); expose it as a module-level constant here so the four
# ``config.TIMEZONE`` call sites resolve. Must match the PingGenerator default and
# the CSV-branch index tz (Pitfall 6 tz-consistency).
TIMEZONE = Config.TIMEZONE

# Convenience functions
def get_config_registry(config_dir: str = "settings") -> ConfigRegistry:
    """Get or create global configuration registry."""
    return ConfigRegistry(config_dir)


def get_portfolio_config_provider(registry: ConfigRegistry = None) -> ConfigProvider:
    """Get portfolio configuration provider."""
    if registry is None:
        registry = get_config_registry()
    return registry.get_provider("portfolio")


def get_trading_config_provider(registry: ConfigRegistry = None) -> ConfigProvider:
    """Get trading configuration provider."""
    if registry is None:
        registry = get_config_registry()
    return registry.get_provider("trading")


def get_data_config_provider(registry: ConfigRegistry = None) -> ConfigProvider:
    """Get data configuration provider."""
    if registry is None:
        registry = get_config_registry()
    return registry.get_provider("data")


def get_system_config_provider(registry: ConfigRegistry = None) -> ConfigProvider:
    """Get system configuration provider."""
    if registry is None:
        registry = get_config_registry()
    return registry.get_provider("system")


__all__ = [
    # Core infrastructure
    'ConfigRegistry',
    'ConfigProvider',
    'FileConfigProvider',
    'RuntimeConfigProvider',
    'ConfigValidator',
    'SchemaValidator',
    'BusinessValidator',
    'ValidationError',
    'ValidationResult',
    
    # Portfolio domain
    'PortfolioConfig',
    'PortfolioType',
    'RiskLevel',
    'PortfolioLimits',
    'RiskManagement',
    'TradingRules',
    'validate_portfolio_config',
    'get_portfolio_preset',
    'list_available_presets',
    
    # Trading domain
    'TradingConfig',
    'OrderType',
    'TimeInForce',
    'ExecutionMode',
    'OrderDefaults',
    'ExecutionSettings',
    'RiskControls',
    'FeeStructure',
    'StrategySettings',
    'validate_trading_config',
    
    # Data domain
    'DataConfig',
    'DataSource',
    'DataFrequency',
    'StorageType',
    'DataSourceConfig',
    'DataFeedConfig',
    'StorageConfig',
    'ProcessingConfig',
    'RealTimeConfig',
    
    # System domain
    'SystemConfig',
    'Environment',
    'PerformanceSettings',
    'SecuritySettings',
    'DatabaseSettings',
    'NotificationSettings',
    'MonitoringSettings',
    'LoggingConfig',
    'get_default_logging_config',
    
    # Convenience functions
    'get_config_registry',
    'get_portfolio_config_provider',
    'get_trading_config_provider',
    'get_data_config_provider',
    'get_system_config_provider',

    # Flat-module re-exports (M1-01)
    'FORBIDDEN_SYMBOLS',
    'TIMEZONE',
    'Config'
]
