"""Domain-based configuration: Pydantic v2 models + a pydantic-settings layer.

The hand-rolled registry/provider/validator/schema machinery and the getters
(``get_config_registry``, ``get_*_config_provider``) were deleted in the M2-06 config
collapse (D-01). Consumers now construct Pydantic models directly. This package is a
clean re-export of those models plus the ``Settings`` env layer and the reference-data
constants — mirroring the grouped-re-export style of ``itrader.core.enums``.
"""

# Reference-data + timezone re-exports (M2-06 / D-02/D-03).
#
# The flat ``itrader/config.py`` shadow module (the M1-01 file-path loader workaround)
# has been DELETED. Its public names are now sourced from their permanent homes:
#   - FORBIDDEN_SYMBOLS / SUPPORTED_*  ->  itrader.core.constants (D-03)
#   - TIMEZONE                         ->  Settings.timezone (D-02/D-07)
from itrader.core.constants import (
    FORBIDDEN_SYMBOLS,
    SUPPORTED_CURRENCIES,
    SUPPORTED_EXCHANGES,
)

from .settings import Settings

# Domain models (Pydantic v2)
from .portfolio import (
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
from .system import (
    Environment,
    LogLevel,
    MonitoringSettings,
    PerformanceSettings,
    SystemConfig,
)
from .order import (
    OrderConfig,
    TrailType,
)
from .stream import (
    FeedProviderSettings,
    StreamSettings,
)
from .safety import (
    FailureRateSettings,
    SafetySettings,
    ThrottleSettings,
)
from .merge import deep_merge
from .exchange import (
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

# Module-level TIMEZONE constant (value 'Europe/Paris' by default). Read from the
# Settings field default rather than instantiating Settings (which requires the
# fail-loud secret). Must match the TimeGenerator default + the CSV-branch index tz
# (tz-consistency, D-07). A future live wiring would read Settings().timezone instead.
TIMEZONE: str = str(Settings.model_fields["timezone"].default)

__all__ = [
    # Settings + reference data
    "Settings",
    "FORBIDDEN_SYMBOLS",
    "SUPPORTED_CURRENCIES",
    "SUPPORTED_EXCHANGES",
    "TIMEZONE",
    # Portfolio domain
    "PortfolioConfig",
    "PortfolioType",
    "RiskLevel",
    "PortfolioLimits",
    "RiskManagement",
    "TradingRules",
    "ValidationSettings",
    "EventSettings",
    "get_portfolio_preset",
    # Order domain
    "OrderConfig",
    "TrailType",
    # Stream / feed-provider domain
    "StreamSettings",
    "FeedProviderSettings",
    # Pre-trade safety domain
    "FailureRateSettings",
    "SafetySettings",
    "ThrottleSettings",
    # Shared config helpers
    "deep_merge",
    # System domain
    "SystemConfig",
    "Environment",
    "LogLevel",
    "PerformanceSettings",
    "MonitoringSettings",
    # Exchange domain
    "ExchangeConfig",
    "ExchangeVenue",
    "FeeModelType",
    "SlippageModelType",
    "FeeModelConfig",
    "SlippageModelConfig",
    "ExchangeLimits",
    "FailureSimulation",
    "ConnectionSettings",
    "get_exchange_preset",
    "list_available_exchange_presets",
]
