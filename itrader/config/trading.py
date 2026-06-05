"""Trading domain configuration (Pydantic v2, M2-06 / D-01..D-03).

Replaces the deleted hand-rolled ``config/trading/`` package. Not exercised on the
golden backtest path; kept as a typed model for the public config surface.
"""

from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    """Time in force options."""

    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    DAY = "day"


class ExecutionMode(str, Enum):
    """Execution modes."""

    SIMULATION = "simulation"
    PAPER = "paper"
    LIVE = "live"


class OrderDefaults(BaseModel):
    """Default order parameters."""

    model_config = ConfigDict(extra="forbid")

    default_order_type: OrderType = OrderType.MARKET
    default_time_in_force: TimeInForce = TimeInForce.GTC
    default_quantity: Optional[Decimal] = None
    max_order_size: Optional[Decimal] = None
    min_order_size: Decimal = Decimal("1.0")


class ExecutionSettings(BaseModel):
    """Execution engine settings."""

    model_config = ConfigDict(extra="forbid")

    mode: ExecutionMode = ExecutionMode.SIMULATION
    max_orders_per_second: int = 10
    max_concurrent_orders: int = 100
    enable_partial_fills: bool = True
    enable_order_routing: bool = True
    default_exchange: str = "BINANCE"
    supported_exchanges: List[str] = Field(
        default_factory=lambda: ["BINANCE", "COINBASE", "KRAKEN"]
    )


class RiskControls(BaseModel):
    """Trading risk controls."""

    model_config = ConfigDict(extra="forbid")

    enable_position_limits: bool = True
    enable_order_size_limits: bool = True
    enable_daily_loss_limits: bool = True
    max_position_size: Optional[Decimal] = None
    max_daily_trades: Optional[int] = None
    max_daily_volume: Optional[Decimal] = None
    enable_pre_trade_checks: bool = True


class FeeStructure(BaseModel):
    """Fee calculation settings."""

    model_config = ConfigDict(extra="forbid")

    maker_fee: float = Field(default=0.001, ge=0)
    taker_fee: float = Field(default=0.001, ge=0)
    enable_fee_calculation: bool = True
    fee_currency: str = "USD"


class StrategySettings(BaseModel):
    """Strategy execution settings."""

    model_config = ConfigDict(extra="forbid")

    enable_strategy_manager: bool = True
    max_active_strategies: int = 5
    enable_strategy_isolation: bool = True
    strategy_timeout_seconds: int = 300
    enable_strategy_logging: bool = True


class TradingConfig(BaseModel):
    """Main trading configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Default Trading Config"
    description: str = ""
    enable_trading: bool = False

    order_defaults: OrderDefaults = Field(default_factory=OrderDefaults)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    risk_controls: RiskControls = Field(default_factory=RiskControls)
    fees: FeeStructure = Field(default_factory=FeeStructure)
    strategies: StrategySettings = Field(default_factory=StrategySettings)

    enable_logging: bool = True
    log_level: str = "INFO"
    enable_metrics: bool = True
    enable_alerts: bool = True

    @classmethod
    def default(cls) -> "TradingConfig":
        """Default trading config."""
        return cls()
