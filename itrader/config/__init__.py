"""Domain-based configuration: Pydantic v2 models + a pydantic-settings layer.

The hand-rolled registry/provider/validator/schema machinery and the getters
(``get_config_registry``, ``get_*_config_provider``) were deleted in the M2-06 config
collapse (D-01). Consumers now construct Pydantic models directly. This package is a
clean re-export of those models plus the ``RuntimeSettings`` env layer and the
reference-data constants — mirroring the grouped-re-export style of ``itrader.core.enums``.
"""

# Reference-data + timezone re-exports (M2-06 / D-02/D-03).
#
# The flat ``itrader/config.py`` shadow module (the M1-01 file-path loader workaround)
# has been DELETED. Its public names are now sourced from their permanent homes:
#   - FORBIDDEN_SYMBOLS / SUPPORTED_*  ->  itrader.core.constants (D-03)
#   - TIMEZONE                         ->  ITraderConfig.timezone (D-02/D-07)
from itrader.core.constants import (
    FORBIDDEN_SYMBOLS,
    SUPPORTED_CURRENCIES,
    SUPPORTED_EXCHANGES,
)

from .runtime import RuntimeSettings

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
    SystemSettings,
    UniverseConfig,
)
from .itrader_config import ITraderConfig
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
)

# Module-level TIMEZONE constant (value 'Europe/Paris' by default). Read from the
# frozen ITraderConfig base-field default rather than constructing the config (avoids
# any import-time side effect). Must match the TimeGenerator default + the CSV-branch
# index tz (tz-consistency, D-07). A future live wiring would read config.timezone.
TIMEZONE: str = str(ITraderConfig.model_fields["timezone"].default)

__all__ = [
    # Runtime env layer + reference data
    "RuntimeSettings",
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
    # System domain
    "ITraderConfig",
    "SystemSettings",
    "UniverseConfig",
    "Environment",
    "LogLevel",
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
]
