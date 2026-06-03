"""
Exchange domain configuration classes.

This module defines configuration classes for exchange operations,
including fee models, slippage models, and exchange settings.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional, List, Set
from enum import Enum


class ExchangeType(Enum):
    """Supported exchange types."""
    SIMULATED = "simulated"
    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"


class FeeModelType(Enum):
    """Supported fee model types."""
    ZERO = "zero"
    NO_FEE = "no_fee"
    PERCENT = "percent"
    MAKER_TAKER = "maker_taker"
    TIERED = "tiered"


class SlippageModelType(Enum):
    """Supported slippage model types."""
    NONE = "none"
    ZERO = "zero"
    LINEAR = "linear"
    FIXED = "fixed"


@dataclass
class FeeModelConfig:
    """Fee model configuration."""
    model_type: FeeModelType = FeeModelType.ZERO
    fee_rate: Optional[Decimal] = None
    maker_rate: Optional[Decimal] = None
    taker_rate: Optional[Decimal] = None
    tiers: Optional[List[Dict[str, Any]]] = None
    
    def to_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for fee model initialization."""
        kwargs = {}
        if self.fee_rate is not None:
            kwargs['fee_rate'] = float(self.fee_rate)
        if self.maker_rate is not None:
            kwargs['maker_rate'] = float(self.maker_rate)
        if self.taker_rate is not None:
            kwargs['taker_rate'] = float(self.taker_rate)
        if self.tiers is not None:
            kwargs['tiers'] = self.tiers
        return kwargs


@dataclass
class SlippageModelConfig:
    """Slippage model configuration."""
    model_type: SlippageModelType = SlippageModelType.NONE
    slippage_pct: Optional[Decimal] = None
    base_slippage_pct: Optional[Decimal] = None
    size_impact_factor: Optional[Decimal] = None
    max_slippage_pct: Optional[Decimal] = None
    random_variation: Optional[bool] = None
    
    def to_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for slippage model initialization."""
        kwargs = {}
        if self.slippage_pct is not None:
            kwargs['slippage_slippage_pct'] = float(self.slippage_pct)
        if self.base_slippage_pct is not None:
            kwargs['slippage_base_slippage_pct'] = float(self.base_slippage_pct)
        if self.size_impact_factor is not None:
            kwargs['slippage_size_impact_factor'] = float(self.size_impact_factor)
        if self.max_slippage_pct is not None:
            kwargs['slippage_max_slippage_pct'] = float(self.max_slippage_pct)
        if self.random_variation is not None:
            kwargs['slippage_random_variation'] = self.random_variation
        return kwargs


@dataclass
class ExchangeLimits:
    """Exchange trading limits."""
    min_order_size: Decimal = field(default_factory=lambda: Decimal('0.001'))
    max_order_size: Decimal = field(default_factory=lambda: Decimal('1000000.0'))
    max_price: Decimal = field(default_factory=lambda: Decimal('1000000.0'))
    supported_symbols: Set[str] = field(default_factory=lambda: {
        'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'
    })


@dataclass
class FailureSimulation:
    """Failure simulation settings."""
    simulate_failures: bool = False
    failure_rate: Decimal = field(default_factory=lambda: Decimal('0.01'))
    enabled_scenarios: List[str] = field(default_factory=lambda: [
        'network_timeout', 'exchange_maintenance', 'rate_limit', 'execution_timeout'
    ])


@dataclass
class ConnectionSettings:
    """Exchange connection settings."""
    auto_connect: bool = True
    connection_timeout: Decimal = field(default_factory=lambda: Decimal('30.0'))
    retry_attempts: int = 3
    retry_delay: Decimal = field(default_factory=lambda: Decimal('1.0'))


@dataclass
class ExchangeConfig:
    """
    Complete exchange configuration.
    
    This class encapsulates all exchange-related settings including
    fee models, slippage models, trading limits, and operational parameters.
    """
    
    # Exchange identification
    exchange_type: ExchangeType = ExchangeType.SIMULATED
    exchange_name: str = "DefaultExchange"
    
    # Model configurations
    fee_model: FeeModelConfig = field(default_factory=FeeModelConfig)
    slippage_model: SlippageModelConfig = field(default_factory=SlippageModelConfig)
    
    # Trading limits and rules
    limits: ExchangeLimits = field(default_factory=ExchangeLimits)
    
    # Simulation settings
    failure_simulation: FailureSimulation = field(default_factory=FailureSimulation)
    
    # Connection settings
    connection: ConnectionSettings = field(default_factory=ConnectionSettings)
    
    # Additional settings
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_exchange_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for exchange initialization."""
        kwargs = {
            'fee_model': self.fee_model.model_type.value,
            'slippage_model': self.slippage_model.model_type.value,
            'simulate_failures': self.failure_simulation.simulate_failures,
            'failure_rate': float(self.failure_simulation.failure_rate)
        }
        
        # Add fee model parameters
        kwargs.update(self.fee_model.to_kwargs())
        
        # Add slippage model parameters
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
                slippage_model=SlippageModelConfig(model_type=SlippageModelType.NONE)
            ),
            "realistic": cls(
                exchange_type=ExchangeType.SIMULATED,
                exchange_name="RealisticSimulatedExchange",
                fee_model=FeeModelConfig(
                    model_type=FeeModelType.PERCENT,
                    fee_rate=Decimal('0.001')
                ),
                slippage_model=SlippageModelConfig(
                    model_type=SlippageModelType.LINEAR,
                    base_slippage_pct=Decimal('0.01'),
                    size_impact_factor=Decimal('0.00001'),
                    max_slippage_pct=Decimal('0.1')
                ),
                failure_simulation=FailureSimulation(
                    simulate_failures=True,
                    failure_rate=Decimal('0.005')
                )
            ),
            "high_fee": cls(
                exchange_type=ExchangeType.SIMULATED,
                exchange_name="HighFeeExchange",
                fee_model=FeeModelConfig(
                    model_type=FeeModelType.MAKER_TAKER,
                    maker_rate=Decimal('0.001'),
                    taker_rate=Decimal('0.002')
                ),
                slippage_model=SlippageModelConfig(
                    model_type=SlippageModelType.FIXED,
                    slippage_pct=Decimal('0.005'),
                    random_variation=True
                )
            )
        }
        
        return presets.get(preset_name, presets["default"])


def get_exchange_preset(preset_name: str) -> ExchangeConfig:
    """Get a predefined exchange configuration preset."""
    return ExchangeConfig.create_simulated_preset(preset_name)


def list_available_exchange_presets() -> List[str]:
    """List all available exchange configuration presets."""
    return ["default", "realistic", "high_fee"]
