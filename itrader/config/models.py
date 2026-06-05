"""Pydantic v2 config models (M2-06 / D-01..D-03).

The full domain-config surface as Pydantic v2 ``BaseModel``s, collapsing the deleted
hand-rolled ``config/{portfolio,trading,data,system,exchange}/`` packages (~3,380 lines)
into one typed module. One model serves BOTH the backtest-dict and the live-JSONB path:
``Model.model_validate(d)`` parses, ``model_dump(mode="json")`` serialises with
Decimal -> str / enum -> value coercion that round-trips exactly.

Field names, the nested-model shape, the ``to_kwargs`` / ``to_exchange_kwargs`` helpers,
and the preset factories are preserved so the runtime consumers keep their attribute
access unchanged (``config.limits.max_positions``,
``config.failure_simulation.simulate_failures``, ``config.performance.rng_seed``, ...).

Preset functions become ``@classmethod`` factories (D-03):
``PortfolioConfig.default()`` / ``ExchangeConfig.default()`` /
``get_exchange_preset(name)`` / ``get_portfolio_preset(name)``.

NOTE (03-05 Task 3): these models are split into per-domain files
``config/{portfolio,trading,data,system,exchange}.py`` once the old colliding package
directories are deleted. They live consolidated here in Task 1 to avoid a
file-vs-package import collision while the old config still ships.
"""

from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Portfolio domain
# ---------------------------------------------------------------------------
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
    """Get a portfolio config preset by name.

    Compat factory replacing ``config.portfolio.defaults.get_portfolio_preset``. The
    backtest path uses ``'default'`` (all-default fields). Unknown names raise.
    """
    factory = _PORTFOLIO_PRESETS.get(preset_name)
    if factory is None:
        raise ValueError(
            f"Unknown portfolio preset: {preset_name!r}. "
            f"Available presets: {list(_PORTFOLIO_PRESETS)}"
        )
    return factory()


# ---------------------------------------------------------------------------
# Trading domain
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Data domain
# ---------------------------------------------------------------------------
class DataSource(str, Enum):
    """Data source types."""

    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    YAHOO = "yahoo"
    ALPHA_VANTAGE = "alpha_vantage"
    IEX = "iex"
    QUANDL = "quandl"
    CSV = "csv"
    DATABASE = "database"


class DataFrequency(str, Enum):
    """Data frequency intervals."""

    TICK = "tick"
    SECOND = "1s"
    MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    THIRTY_MINUTE = "30m"
    HOUR = "1h"
    FOUR_HOUR = "4h"
    DAILY = "1d"
    WEEKLY = "1w"
    MONTHLY = "1M"


class StorageType(str, Enum):
    """Data storage types."""

    MEMORY = "memory"
    CSV = "csv"
    PARQUET = "parquet"
    HDF5 = "hdf5"
    DATABASE = "database"
    REDIS = "redis"


class DataSourceConfig(BaseModel):
    """Configuration for a data source."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source_type: DataSource
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit: int = 10
    timeout: int = 30
    retry_attempts: int = 3
    enabled: bool = True


class DataFeedConfig(BaseModel):
    """Configuration for a data feed."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    source: str
    frequency: DataFrequency
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    fields: List[str] = Field(
        default_factory=lambda: ["open", "high", "low", "close", "volume"]
    )
    enabled: bool = True


class StorageConfig(BaseModel):
    """Data storage configuration."""

    model_config = ConfigDict(extra="forbid")

    storage_type: StorageType = StorageType.PARQUET
    base_path: str = "data"
    compression: str = "snappy"
    max_file_size_mb: int = 100
    partition_by: Optional[str] = "date"
    retention_days: Optional[int] = None
    backup_enabled: bool = False
    backup_path: Optional[str] = None


class ProcessingConfig(BaseModel):
    """Data processing configuration."""

    model_config = ConfigDict(extra="forbid")

    enable_validation: bool = True
    enable_cleaning: bool = True
    enable_normalization: bool = False
    fill_missing_data: bool = True
    remove_outliers: bool = False
    outlier_threshold: float = 3.0
    enable_caching: bool = True
    cache_size_mb: int = 500


class RealTimeConfig(BaseModel):
    """Real-time data configuration."""

    model_config = ConfigDict(extra="forbid")

    enable_real_time: bool = False
    buffer_size: int = 1000
    update_frequency_ms: int = 1000
    enable_heartbeat: bool = True
    heartbeat_interval_s: int = 30
    reconnect_attempts: int = 5
    reconnect_delay_s: int = 5


class DataConfig(BaseModel):
    """Main data configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Default Data Config"
    description: str = ""
    sources: List[DataSourceConfig] = Field(default_factory=list)
    feeds: List[DataFeedConfig] = Field(default_factory=list)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    real_time: RealTimeConfig = Field(default_factory=RealTimeConfig)
    enable_logging: bool = True
    log_level: str = "INFO"
    enable_metrics: bool = True

    @classmethod
    def default(cls) -> "DataConfig":
        """Default data config."""
        return cls()


# ---------------------------------------------------------------------------
# System domain
# ---------------------------------------------------------------------------
class Environment(str, Enum):
    """Environment types."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class PerformanceSettings(BaseModel):
    """Performance tuning settings."""

    model_config = ConfigDict(extra="ignore")

    max_threads: int = 10
    max_processes: int = 4
    enable_multiprocessing: bool = False
    enable_async: bool = True
    connection_pool_size: int = 20
    timeout_seconds: int = 30
    enable_caching: bool = True
    cache_size_mb: int = 512
    # Determinism seed for stochastic components (D-11, #5/PERF2). Constant default;
    # drives only failure-simulation + slippage jitter, never a security value.
    rng_seed: int = 42


class MonitoringSettings(BaseModel):
    """Monitoring and metrics settings."""

    model_config = ConfigDict(extra="ignore")

    enable_metrics: bool = True
    metrics_port: int = 9090
    enable_health_check: bool = True
    health_check_port: int = 8080
    enable_profiling: bool = False
    profiling_port: int = 8081
    enable_tracing: bool = False


class SystemConfig(BaseModel):
    """Main system configuration."""

    # Tolerate unknown keys from a YAML override (the old from_dict ignored extras).
    model_config = ConfigDict(extra="ignore")

    name: str = "iTrader System"
    version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug_mode: bool = True

    data_dir: str = "data"
    log_dir: str = "logs"
    config_dir: str = "settings"
    cache_dir: str = "cache"

    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)

    enable_auto_restart: bool = False
    auto_restart_delay_seconds: int = 10
    enable_graceful_shutdown: bool = True
    shutdown_timeout_seconds: int = 30

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SystemConfig":
        """Build from a (possibly partial/empty) dict; missing keys take defaults."""
        return cls.model_validate(data or {})

    @classmethod
    def default(cls) -> "SystemConfig":
        """Default system config (documented defaults; rng_seed=42)."""
        return cls()


# ---------------------------------------------------------------------------
# Exchange domain
# ---------------------------------------------------------------------------
class ExchangeType(str, Enum):
    """Supported exchange types."""

    SIMULATED = "simulated"
    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"


class FeeModelType(str, Enum):
    """Supported fee model types."""

    ZERO = "zero"
    NO_FEE = "no_fee"
    PERCENT = "percent"
    MAKER_TAKER = "maker_taker"
    TIERED = "tiered"


class SlippageModelType(str, Enum):
    """Supported slippage model types."""

    NONE = "none"
    ZERO = "zero"
    LINEAR = "linear"
    FIXED = "fixed"


class FeeModelConfig(BaseModel):
    """Fee model configuration."""

    model_config = ConfigDict(extra="forbid")

    model_type: FeeModelType = FeeModelType.ZERO
    fee_rate: Optional[Decimal] = None
    maker_rate: Optional[Decimal] = None
    taker_rate: Optional[Decimal] = None
    tiers: Optional[List[Dict[str, Any]]] = None

    def to_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for fee model initialization."""
        kwargs: Dict[str, Any] = {}
        if self.fee_rate is not None:
            kwargs["fee_rate"] = float(self.fee_rate)
        if self.maker_rate is not None:
            kwargs["maker_rate"] = float(self.maker_rate)
        if self.taker_rate is not None:
            kwargs["taker_rate"] = float(self.taker_rate)
        if self.tiers is not None:
            kwargs["tiers"] = self.tiers
        return kwargs


class SlippageModelConfig(BaseModel):
    """Slippage model configuration."""

    model_config = ConfigDict(extra="forbid")

    model_type: SlippageModelType = SlippageModelType.NONE
    slippage_pct: Optional[Decimal] = None
    base_slippage_pct: Optional[Decimal] = None
    size_impact_factor: Optional[Decimal] = None
    max_slippage_pct: Optional[Decimal] = None
    random_variation: Optional[bool] = None

    def to_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for slippage model initialization."""
        kwargs: Dict[str, Any] = {}
        if self.slippage_pct is not None:
            kwargs["slippage_slippage_pct"] = float(self.slippage_pct)
        if self.base_slippage_pct is not None:
            kwargs["slippage_base_slippage_pct"] = float(self.base_slippage_pct)
        if self.size_impact_factor is not None:
            kwargs["slippage_size_impact_factor"] = float(self.size_impact_factor)
        if self.max_slippage_pct is not None:
            kwargs["slippage_max_slippage_pct"] = float(self.max_slippage_pct)
        if self.random_variation is not None:
            kwargs["slippage_random_variation"] = self.random_variation
        return kwargs


class ExchangeLimits(BaseModel):
    """Exchange trading limits."""

    model_config = ConfigDict(extra="forbid")

    min_order_size: Decimal = Decimal("0.001")
    max_order_size: Decimal = Decimal("1000000.0")
    max_price: Decimal = Decimal("1000000.0")
    supported_symbols: Set[str] = Field(
        default_factory=lambda: {"BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT", "SOLUSDT"}
    )


class FailureSimulation(BaseModel):
    """Failure simulation settings."""

    model_config = ConfigDict(extra="forbid")

    simulate_failures: bool = False
    failure_rate: Decimal = Decimal("0.01")
    enabled_scenarios: List[str] = Field(
        default_factory=lambda: [
            "network_timeout", "exchange_maintenance", "rate_limit", "execution_timeout"
        ]
    )


class ConnectionSettings(BaseModel):
    """Exchange connection settings."""

    model_config = ConfigDict(extra="forbid")

    auto_connect: bool = True
    connection_timeout: Decimal = Decimal("30.0")
    retry_attempts: int = 3
    retry_delay: Decimal = Decimal("1.0")


class ExchangeConfig(BaseModel):
    """Complete exchange configuration."""

    model_config = ConfigDict(extra="forbid")

    exchange_type: ExchangeType = ExchangeType.SIMULATED
    exchange_name: str = "DefaultExchange"

    fee_model: FeeModelConfig = Field(default_factory=FeeModelConfig)
    slippage_model: SlippageModelConfig = Field(default_factory=SlippageModelConfig)
    limits: ExchangeLimits = Field(default_factory=ExchangeLimits)
    failure_simulation: FailureSimulation = Field(default_factory=FailureSimulation)
    connection: ConnectionSettings = Field(default_factory=ConnectionSettings)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_exchange_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for exchange initialization."""
        kwargs: Dict[str, Any] = {
            "fee_model": self.fee_model.model_type.value,
            "slippage_model": self.slippage_model.model_type.value,
            "simulate_failures": self.failure_simulation.simulate_failures,
            "failure_rate": float(self.failure_simulation.failure_rate),
        }
        kwargs.update(self.fee_model.to_kwargs())
        kwargs.update(self.slippage_model.to_kwargs())
        return kwargs

    @classmethod
    def create_simulated_preset(cls, preset_name: str = "default") -> "ExchangeConfig":
        """Create a preset configuration for simulated exchange."""
        presets = {
            "default": cls(
                exchange_type=ExchangeType.SIMULATED,
                exchange_name="SimulatedExchange",
                fee_model=FeeModelConfig(model_type=FeeModelType.ZERO),
                slippage_model=SlippageModelConfig(model_type=SlippageModelType.NONE),
            ),
            "realistic": cls(
                exchange_type=ExchangeType.SIMULATED,
                exchange_name="RealisticSimulatedExchange",
                fee_model=FeeModelConfig(
                    model_type=FeeModelType.PERCENT,
                    fee_rate=Decimal("0.001"),
                ),
                slippage_model=SlippageModelConfig(
                    model_type=SlippageModelType.LINEAR,
                    base_slippage_pct=Decimal("0.01"),
                    size_impact_factor=Decimal("0.00001"),
                    max_slippage_pct=Decimal("0.1"),
                ),
                failure_simulation=FailureSimulation(
                    simulate_failures=True,
                    failure_rate=Decimal("0.005"),
                ),
            ),
            "high_fee": cls(
                exchange_type=ExchangeType.SIMULATED,
                exchange_name="HighFeeExchange",
                fee_model=FeeModelConfig(
                    model_type=FeeModelType.MAKER_TAKER,
                    maker_rate=Decimal("0.001"),
                    taker_rate=Decimal("0.002"),
                ),
                slippage_model=SlippageModelConfig(
                    model_type=SlippageModelType.FIXED,
                    slippage_pct=Decimal("0.005"),
                    random_variation=True,
                ),
            ),
        }
        return presets.get(preset_name, presets["default"])

    @classmethod
    def default(cls) -> "ExchangeConfig":
        """The default simulated-exchange preset (zero fee, no slippage)."""
        return cls.create_simulated_preset("default")


def get_exchange_preset(preset_name: str) -> ExchangeConfig:
    """Get a predefined exchange configuration preset."""
    return ExchangeConfig.create_simulated_preset(preset_name)


def list_available_exchange_presets() -> List[str]:
    """List all available exchange configuration presets."""
    return ["default", "realistic", "high_fee"]


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
