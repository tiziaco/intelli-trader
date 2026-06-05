"""Portfolio domain configuration (Pydantic v2, M2-06 / D-01..D-03).

Replaces the deleted hand-rolled ``config/portfolio/`` package. One model serves both
the backtest-dict and the JSONB path; preset functions become ``@classmethod``
factories (``PortfolioConfig.default()`` / ``get_portfolio_preset(name)``).
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PortfolioType(str, Enum):
    """Portfolio types."""

    EQUITY = "equity"
    FUTURES = "futures"
    FOREX = "forex"
    CRYPTO = "crypto"
    MIXED = "mixed"


class RiskLevel(str, Enum):
    """Risk levels for portfolio management."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class PortfolioLimits(BaseModel):
    """Portfolio limits and constraints."""

    model_config = ConfigDict(extra="forbid")

    max_positions: int = Field(default=50, gt=0)
    max_position_value: Decimal = Decimal("1000000.0")
    max_portfolio_concentration: float = Field(default=0.25, gt=0, le=1)
    max_daily_loss: Optional[Decimal] = None
    max_drawdown: Optional[float] = None
    min_cash_reserve: Decimal = Decimal("1000.0")


class RiskManagement(BaseModel):
    """Risk management configuration."""

    model_config = ConfigDict(extra="forbid")

    enable_stop_loss: bool = True
    enable_take_profit: bool = True
    default_stop_loss_pct: float = Field(default=0.05, ge=0, le=1)
    default_take_profit_pct: float = Field(default=0.10, ge=0, le=1)
    risk_level: RiskLevel = RiskLevel.MODERATE
    max_risk_per_trade: float = Field(default=0.02, ge=0, le=1)
    max_daily_loss_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_concentration_pct: float = Field(default=0.25, gt=0, le=1)


class TradingRules(BaseModel):
    """Trading rules and preferences."""

    model_config = ConfigDict(extra="forbid")

    allow_short_selling: bool = False
    enable_margin: bool = False
    enable_options: bool = False
    enable_futures: bool = False
    min_trade_amount: Decimal = Decimal("100.0")
    max_trade_amount: Optional[Decimal] = None
    max_transactions_per_day: Optional[int] = None
    max_cash_withdrawal_pct: float = Field(default=0.50, ge=0, le=1)


class ValidationSettings(BaseModel):
    """Validation and business logic settings."""

    model_config = ConfigDict(extra="forbid")

    validate_transactions: bool = True
    require_sufficient_funds: bool = True
    enable_position_limits: bool = True
    enable_risk_checks: bool = True


class EventSettings(BaseModel):
    """Event publishing configuration."""

    model_config = ConfigDict(extra="forbid")

    publish_update_events: bool = True
    publish_error_events: bool = True
    publish_transaction_events: bool = True
    publish_position_events: bool = True


class PortfolioConfig(BaseModel):
    """Main portfolio configuration."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: Optional[int] = None
    name: str = "Default Portfolio"
    description: str = ""
    portfolio_type: PortfolioType = PortfolioType.EQUITY
    base_currency: str = "USD"
    initial_capital: Decimal = Decimal("100000.0")

    limits: PortfolioLimits = Field(default_factory=PortfolioLimits)
    risk_management: RiskManagement = Field(default_factory=RiskManagement)
    trading_rules: TradingRules = Field(default_factory=TradingRules)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    events: EventSettings = Field(default_factory=EventSettings)

    enable_analytics: bool = True
    enable_notifications: bool = True
    auto_rebalance: bool = False
    rebalance_frequency: str = "monthly"

    @classmethod
    def default(cls) -> "PortfolioConfig":
        """All-default portfolio config (the historical 'default' preset)."""
        return cls()

    @classmethod
    def conservative(cls) -> "PortfolioConfig":
        """Low-risk preset focused on capital preservation."""
        return cls(
            name="Conservative Portfolio",
            description="Low-risk portfolio focused on capital preservation",
            portfolio_type=PortfolioType.EQUITY,
            initial_capital=Decimal("50000.0"),
            limits=PortfolioLimits(
                max_positions=20,
                max_position_value=Decimal("10000.0"),
                max_portfolio_concentration=0.15,
                max_daily_loss=Decimal("500.0"),
                max_drawdown=0.05,
                min_cash_reserve=Decimal("5000.0"),
            ),
            risk_management=RiskManagement(
                default_stop_loss_pct=0.03,
                default_take_profit_pct=0.06,
                risk_level=RiskLevel.CONSERVATIVE,
                max_risk_per_trade=0.01,
            ),
            trading_rules=TradingRules(
                min_trade_amount=Decimal("500.0"),
                max_trade_amount=Decimal("5000.0"),
            ),
            auto_rebalance=True,
            rebalance_frequency="monthly",
        )


_PORTFOLIO_PRESETS = {
    "default": PortfolioConfig.default,
    "conservative": PortfolioConfig.conservative,
}


def get_portfolio_preset(preset_name: str) -> PortfolioConfig:
    """Get a portfolio config preset by name (compat factory).

    The backtest path uses ``'default'`` (all-default fields). Unknown names raise.
    """
    factory = _PORTFOLIO_PRESETS.get(preset_name)
    if factory is None:
        raise ValueError(
            f"Unknown portfolio preset: {preset_name!r}. "
            f"Available presets: {list(_PORTFOLIO_PRESETS)}"
        )
    return factory()
