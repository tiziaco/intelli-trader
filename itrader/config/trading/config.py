"""
Trading domain configuration classes.

This module defines configuration classes for trading operations,
including execution settings, order management, and strategy parameters.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional, List
from enum import Enum


class OrderType(Enum):
    """Supported order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(Enum):
    """Time in force options."""
    GTC = "gtc"  # Good Till Cancelled
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill
    DAY = "day"  # Day order


class ExecutionMode(Enum):
    """Execution modes."""
    SIMULATION = "simulation"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class OrderDefaults:
    """Default order parameters."""
    default_order_type: OrderType = OrderType.MARKET
    default_time_in_force: TimeInForce = TimeInForce.GTC
    default_quantity: Optional[Decimal] = None
    max_order_size: Optional[Decimal] = None
    min_order_size: Decimal = field(default_factory=lambda: Decimal('1.0'))


@dataclass
class ExecutionSettings:
    """Execution engine settings."""
    mode: ExecutionMode = ExecutionMode.SIMULATION
    max_orders_per_second: int = 10
    max_concurrent_orders: int = 100
    enable_partial_fills: bool = True
    enable_order_routing: bool = True
    default_exchange: str = "BINANCE"
    supported_exchanges: List[str] = field(default_factory=lambda: ["BINANCE", "COINBASE", "KRAKEN"])


@dataclass
class RiskControls:
    """Trading risk controls."""
    enable_position_limits: bool = True
    enable_order_size_limits: bool = True
    enable_daily_loss_limits: bool = True
    max_position_size: Optional[Decimal] = None
    max_daily_trades: Optional[int] = None
    max_daily_volume: Optional[Decimal] = None
    enable_pre_trade_checks: bool = True


@dataclass
class FeeStructure:
    """Fee calculation settings."""
    maker_fee: float = 0.001  # 0.1%
    taker_fee: float = 0.001  # 0.1%
    enable_fee_calculation: bool = True
    fee_currency: str = "USD"


@dataclass
class StrategySettings:
    """Strategy execution settings."""
    enable_strategy_manager: bool = True
    max_active_strategies: int = 5
    enable_strategy_isolation: bool = True
    strategy_timeout_seconds: int = 300
    enable_strategy_logging: bool = True


@dataclass
class TradingConfig:
    """
    Main trading configuration class.
    
    This class contains all configuration parameters for trading operations,
    including order defaults, execution settings, and risk controls.
    """
    
    # Basic settings
    name: str = "Default Trading Config"
    description: str = ""
    enable_trading: bool = False
    
    # Configuration objects
    order_defaults: OrderDefaults = field(default_factory=OrderDefaults)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    risk_controls: RiskControls = field(default_factory=RiskControls)
    fees: FeeStructure = field(default_factory=FeeStructure)
    strategies: StrategySettings = field(default_factory=StrategySettings)
    
    # Operational settings
    enable_logging: bool = True
    log_level: str = "INFO"
    enable_metrics: bool = True
    enable_alerts: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        result = {
            # Basic settings
            'name': self.name,
            'description': self.description,
            'enable_trading': self.enable_trading,
            
            # Order defaults
            'order_defaults': {
                'default_order_type': self.order_defaults.default_order_type.value,
                'default_time_in_force': self.order_defaults.default_time_in_force.value,
                'default_quantity': str(self.order_defaults.default_quantity) if self.order_defaults.default_quantity else None,
                'max_order_size': str(self.order_defaults.max_order_size) if self.order_defaults.max_order_size else None,
                'min_order_size': str(self.order_defaults.min_order_size)
            },
            
            # Execution settings
            'execution': {
                'mode': self.execution.mode.value,
                'max_orders_per_second': self.execution.max_orders_per_second,
                'max_concurrent_orders': self.execution.max_concurrent_orders,
                'enable_partial_fills': self.execution.enable_partial_fills,
                'enable_order_routing': self.execution.enable_order_routing,
                'default_exchange': self.execution.default_exchange,
                'supported_exchanges': self.execution.supported_exchanges
            },
            
            # Risk controls
            'risk_controls': {
                'enable_position_limits': self.risk_controls.enable_position_limits,
                'enable_order_size_limits': self.risk_controls.enable_order_size_limits,
                'enable_daily_loss_limits': self.risk_controls.enable_daily_loss_limits,
                'max_position_size': str(self.risk_controls.max_position_size) if self.risk_controls.max_position_size else None,
                'max_daily_trades': self.risk_controls.max_daily_trades,
                'max_daily_volume': str(self.risk_controls.max_daily_volume) if self.risk_controls.max_daily_volume else None,
                'enable_pre_trade_checks': self.risk_controls.enable_pre_trade_checks
            },
            
            # Fee structure
            'fees': {
                'maker_fee': self.fees.maker_fee,
                'taker_fee': self.fees.taker_fee,
                'enable_fee_calculation': self.fees.enable_fee_calculation,
                'fee_currency': self.fees.fee_currency
            },
            
            # Strategy settings
            'strategies': {
                'enable_strategy_manager': self.strategies.enable_strategy_manager,
                'max_active_strategies': self.strategies.max_active_strategies,
                'enable_strategy_isolation': self.strategies.enable_strategy_isolation,
                'strategy_timeout_seconds': self.strategies.strategy_timeout_seconds,
                'enable_strategy_logging': self.strategies.enable_strategy_logging
            },
            
            # Operational settings
            'enable_logging': self.enable_logging,
            'log_level': self.log_level,
            'enable_metrics': self.enable_metrics,
            'enable_alerts': self.enable_alerts
        }
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradingConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        # Basic settings
        config.name = data.get('name', config.name)
        config.description = data.get('description', config.description)
        config.enable_trading = data.get('enable_trading', config.enable_trading)
        
        # Order defaults
        if 'order_defaults' in data:
            order_data = data['order_defaults']
            config.order_defaults = OrderDefaults(
                default_order_type=OrderType(order_data.get('default_order_type', config.order_defaults.default_order_type.value)),
                default_time_in_force=TimeInForce(order_data.get('default_time_in_force', config.order_defaults.default_time_in_force.value)),
                default_quantity=Decimal(str(order_data['default_quantity'])) if order_data.get('default_quantity') else None,
                max_order_size=Decimal(str(order_data['max_order_size'])) if order_data.get('max_order_size') else None,
                min_order_size=Decimal(str(order_data.get('min_order_size', config.order_defaults.min_order_size)))
            )
        
        # Execution settings
        if 'execution' in data:
            exec_data = data['execution']
            config.execution = ExecutionSettings(
                mode=ExecutionMode(exec_data.get('mode', config.execution.mode.value)),
                max_orders_per_second=exec_data.get('max_orders_per_second', config.execution.max_orders_per_second),
                max_concurrent_orders=exec_data.get('max_concurrent_orders', config.execution.max_concurrent_orders),
                enable_partial_fills=exec_data.get('enable_partial_fills', config.execution.enable_partial_fills),
                enable_order_routing=exec_data.get('enable_order_routing', config.execution.enable_order_routing),
                default_exchange=exec_data.get('default_exchange', config.execution.default_exchange),
                supported_exchanges=exec_data.get('supported_exchanges', config.execution.supported_exchanges)
            )
        
        # Risk controls
        if 'risk_controls' in data:
            risk_data = data['risk_controls']
            config.risk_controls = RiskControls(
                enable_position_limits=risk_data.get('enable_position_limits', config.risk_controls.enable_position_limits),
                enable_order_size_limits=risk_data.get('enable_order_size_limits', config.risk_controls.enable_order_size_limits),
                enable_daily_loss_limits=risk_data.get('enable_daily_loss_limits', config.risk_controls.enable_daily_loss_limits),
                max_position_size=Decimal(str(risk_data['max_position_size'])) if risk_data.get('max_position_size') else None,
                max_daily_trades=risk_data.get('max_daily_trades'),
                max_daily_volume=Decimal(str(risk_data['max_daily_volume'])) if risk_data.get('max_daily_volume') else None,
                enable_pre_trade_checks=risk_data.get('enable_pre_trade_checks', config.risk_controls.enable_pre_trade_checks)
            )
        
        # Fee structure
        if 'fees' in data:
            fee_data = data['fees']
            config.fees = FeeStructure(
                maker_fee=fee_data.get('maker_fee', config.fees.maker_fee),
                taker_fee=fee_data.get('taker_fee', config.fees.taker_fee),
                enable_fee_calculation=fee_data.get('enable_fee_calculation', config.fees.enable_fee_calculation),
                fee_currency=fee_data.get('fee_currency', config.fees.fee_currency)
            )
        
        # Strategy settings
        if 'strategies' in data:
            strategy_data = data['strategies']
            config.strategies = StrategySettings(
                enable_strategy_manager=strategy_data.get('enable_strategy_manager', config.strategies.enable_strategy_manager),
                max_active_strategies=strategy_data.get('max_active_strategies', config.strategies.max_active_strategies),
                enable_strategy_isolation=strategy_data.get('enable_strategy_isolation', config.strategies.enable_strategy_isolation),
                strategy_timeout_seconds=strategy_data.get('strategy_timeout_seconds', config.strategies.strategy_timeout_seconds),
                enable_strategy_logging=strategy_data.get('enable_strategy_logging', config.strategies.enable_strategy_logging)
            )
        
        # Operational settings
        config.enable_logging = data.get('enable_logging', config.enable_logging)
        config.log_level = data.get('log_level', config.log_level)
        config.enable_metrics = data.get('enable_metrics', config.enable_metrics)
        config.enable_alerts = data.get('enable_alerts', config.enable_alerts)
        
        return config
