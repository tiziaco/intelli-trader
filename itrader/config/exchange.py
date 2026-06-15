"""Exchange domain configuration (Pydantic v2, M2-06 / D-01..D-03).

Replaces the deleted hand-rolled ``config/exchange/`` package. Field names, the
nested-model shape, the ``to_kwargs`` / ``to_exchange_kwargs`` helpers, and the
``get_exchange_preset`` factory (4 presets: default / realistic / high_fee /
low_latency, behavior-preserving against the deleted ``presets.py``) are preserved so
``SimulatedExchange`` keeps its attribute access unchanged.
"""

from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field


class ExchangeVenue(str, Enum):
    """Supported exchange venues."""

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
    """Venue-level exchange trading limits (D-01, INST-03).

    ``min_order_size`` is the venue-level FALLBACK for symbols whose
    ``Instrument`` does not declare one (``Instrument.min_order_size is None``,
    D-01a). The per-symbol ``Instrument`` is the source of truth; the exchange
    resolves Instrument-first and falls through to this value only when the
    instrument leaves it undeclared. The value is unchanged from before the
    INST-03 demotion — BTCUSD (undeclared) reads ``Decimal("0.001")`` here,
    byte-identical to the pre-demotion behavior.
    """

    model_config = ConfigDict(extra="forbid")

    # D-01/INST-03: the venue-level min-order-size fallback for UNDECLARED
    # symbols (Instrument-first resolution falls through to this). Value
    # unchanged (byte-exact) — BTCUSD reads this 0.001 today.
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

    exchange_type: ExchangeVenue = ExchangeVenue.SIMULATED
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
    def default(cls) -> "ExchangeConfig":
        """The default simulated-exchange preset (zero fee, no slippage)."""
        return get_exchange_preset("default")


def _default_preset() -> ExchangeConfig:
    """Default exchange config: zero fee, no slippage, no failures."""
    return ExchangeConfig(
        exchange_name="SimulatedExchange",
        exchange_type=ExchangeVenue.SIMULATED,
        fee_model=FeeModelConfig(model_type=FeeModelType.ZERO, fee_rate=Decimal("0.0")),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.NONE,
            base_slippage_pct=Decimal("0.0"),
            size_impact_factor=Decimal("0.0"),
            max_slippage_pct=Decimal("0.0"),
        ),
        limits=ExchangeLimits(
            supported_symbols={"BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT", "SOLUSDT"},
            min_order_size=Decimal("0.001"),
            max_order_size=Decimal("1000000.0"),
            max_price=Decimal("1000000.0"),
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=False,
            failure_rate=Decimal("0.0"),
            enabled_scenarios=["network_timeout", "exchange_maintenance"],
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal("30.0"),
            retry_attempts=3,
            retry_delay=Decimal("1.0"),
        ),
    )


def _realistic_preset() -> ExchangeConfig:
    """Realistic exchange config with fees and slippage."""
    return ExchangeConfig(
        exchange_name="RealisticSimulatedExchange",
        exchange_type=ExchangeVenue.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.PERCENT, fee_rate=Decimal("0.001")
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.LINEAR,
            base_slippage_pct=Decimal("0.01"),
            size_impact_factor=Decimal("0.00001"),
            max_slippage_pct=Decimal("0.1"),
        ),
        limits=ExchangeLimits(
            supported_symbols={"BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT", "SOLUSDT"},
            min_order_size=Decimal("0.001"),
            max_order_size=Decimal("1000000.0"),
            max_price=Decimal("1000000.0"),
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=True,
            failure_rate=Decimal("0.01"),
            enabled_scenarios=["network_timeout", "exchange_maintenance", "rate_limit"],
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal("30.0"),
            retry_attempts=3,
            retry_delay=Decimal("1.0"),
        ),
    )


def _high_fee_preset() -> ExchangeConfig:
    """High-fee exchange config."""
    return ExchangeConfig(
        exchange_name="HighFeeSimulatedExchange",
        exchange_type=ExchangeVenue.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.MAKER_TAKER,
            maker_rate=Decimal("0.008"),
            taker_rate=Decimal("0.010"),
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.FIXED,
            slippage_pct=Decimal("0.02"),
            random_variation=True,
        ),
        limits=ExchangeLimits(
            supported_symbols={"BTCUSDT", "ETHUSDT", "ADAUSDT"},
            min_order_size=Decimal("0.01"),
            max_order_size=Decimal("100000.0"),
            max_price=Decimal("1000000.0"),
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=False,
            failure_rate=Decimal("0.0"),
            enabled_scenarios=[],
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal("30.0"),
            retry_attempts=3,
            retry_delay=Decimal("1.0"),
        ),
    )


def _low_latency_preset() -> ExchangeConfig:
    """Low-latency exchange config."""
    return ExchangeConfig(
        exchange_name="LowLatencySimulatedExchange",
        exchange_type=ExchangeVenue.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.PERCENT, fee_rate=Decimal("0.0005")
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.NONE,
            base_slippage_pct=Decimal("0.0"),
            size_impact_factor=Decimal("0.0"),
            max_slippage_pct=Decimal("0.0"),
        ),
        limits=ExchangeLimits(
            supported_symbols={"BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT", "SOLUSDT"},
            min_order_size=Decimal("0.001"),
            max_order_size=Decimal("1000000.0"),
            max_price=Decimal("1000000.0"),
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=False,
            failure_rate=Decimal("0.0"),
            enabled_scenarios=[],
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal("10.0"),
            retry_attempts=1,
            retry_delay=Decimal("0.5"),
        ),
    )


_EXCHANGE_PRESETS = {
    "default": _default_preset,
    "realistic": _realistic_preset,
    "high_fee": _high_fee_preset,
    "low_latency": _low_latency_preset,
}


def get_exchange_preset(preset_name: str) -> ExchangeConfig:
    """Get a predefined exchange configuration preset (behavior-preserving).

    Replaces the deleted ``config/exchange/presets.py::get_exchange_preset``. Unknown
    names raise ``ValueError`` (matching the prior contract).
    """
    factory = _EXCHANGE_PRESETS.get(preset_name)
    if factory is None:
        raise ValueError(
            f"Unknown exchange preset: {preset_name}. "
            f"Available: {list(_EXCHANGE_PRESETS)}"
        )
    return factory()


def list_available_exchange_presets() -> List[str]:
    """List all available exchange configuration presets."""
    return ["default", "realistic", "high_fee", "low_latency"]
