"""
Exchange configuration presets.
"""

from decimal import Decimal
from .config import (
    ExchangeConfig, ExchangeType, FeeModelType, SlippageModelType,
    FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation,
    ConnectionSettings
)


def get_exchange_preset(preset_name: str) -> ExchangeConfig:
    """
    Get a predefined exchange configuration preset.
    
    Parameters
    ----------
    preset_name : str
        Name of the preset ('default', 'realistic', 'high_fee', 'low_latency')
        
    Returns
    -------
    ExchangeConfig
        The configuration preset
        
    Raises
    ------
    ValueError
        If preset_name is not recognized
    """
    presets = {
        'default': _get_default_preset(),
        'realistic': _get_realistic_preset(),
        'high_fee': _get_high_fee_preset(),
        'low_latency': _get_low_latency_preset()
    }
    
    if preset_name not in presets:
        raise ValueError(f"Unknown exchange preset: {preset_name}. Available: {list(presets.keys())}")
    
    return presets[preset_name]


def list_available_exchange_presets() -> list[str]:
    """
    Get a list of available exchange configuration presets.
    
    Returns
    -------
    list[str]
        List of available preset names
    """
    return ['default', 'realistic', 'high_fee', 'low_latency']


def _get_default_preset() -> ExchangeConfig:
    """Get the default exchange configuration."""
    return ExchangeConfig(
        exchange_name="SimulatedExchange",
        exchange_type=ExchangeType.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.ZERO,
            fee_rate=Decimal('0.0')
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.NONE,
            base_slippage_pct=Decimal('0.0'),
            size_impact_factor=Decimal('0.0'),
            max_slippage_pct=Decimal('0.0')
        ),
        limits=ExchangeLimits(
            supported_symbols={'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'},
            min_order_size=Decimal('0.001'),
            max_order_size=Decimal('1000000.0'),
            max_price=Decimal('1000000.0')
        ),
    failure_simulation=FailureSimulation(
        simulate_failures=False,
        failure_rate=Decimal('0.0'),
        enabled_scenarios=['network_timeout', 'exchange_maintenance']
    ),
    connection=ConnectionSettings(
        auto_connect=True,
        connection_timeout=Decimal('30.0'),
        retry_attempts=3,
        retry_delay=Decimal('1.0')
    )
    )


def _get_realistic_preset() -> ExchangeConfig:
    """Get a realistic exchange configuration with fees and slippage."""
    return ExchangeConfig(
        exchange_name="RealisticSimulatedExchange",
        exchange_type=ExchangeType.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.PERCENT,
            fee_rate=Decimal('0.001')  # 0.1% fee
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.LINEAR,
            base_slippage_pct=Decimal('0.01'),      # 1% base slippage
            size_impact_factor=Decimal('0.00001'),  # Size impact factor
            max_slippage_pct=Decimal('0.1')         # 10% max slippage
        ),
        limits=ExchangeLimits(
            supported_symbols={'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'},
            min_order_size=Decimal('0.001'),
            max_order_size=Decimal('1000000.0'),
            max_price=Decimal('1000000.0')
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=True,
            failure_rate=Decimal('0.01'),  # 1% failure rate
            enabled_scenarios=['network_timeout', 'exchange_maintenance', 'rate_limit']
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal('30.0'),
            retry_attempts=3,
            retry_delay=Decimal('1.0')
        )
    )


def _get_high_fee_preset() -> ExchangeConfig:
    """Get a high-fee exchange configuration."""
    return ExchangeConfig(
        exchange_name="HighFeeSimulatedExchange",
        exchange_type=ExchangeType.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.MAKER_TAKER,
            maker_rate=Decimal('0.008'),  # 0.8% maker fee
            taker_rate=Decimal('0.010')   # 1.0% taker fee
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.FIXED,
            slippage_pct=Decimal('0.02'),    # 2% fixed slippage
            random_variation=True
        ),
        limits=ExchangeLimits(
            supported_symbols={'BTCUSDT', 'ETHUSDT', 'ADAUSDT'},
            min_order_size=Decimal('0.01'),   # Higher minimum
            max_order_size=Decimal('100000.0'),  # Lower maximum
            max_price=Decimal('1000000.0')
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=False,
            failure_rate=Decimal('0.0'),
            enabled_scenarios=[]
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal('30.0'),
            retry_attempts=3,
            retry_delay=Decimal('1.0')
        )
    )


def _get_low_latency_preset() -> ExchangeConfig:
    """Get a low-latency exchange configuration."""
    return ExchangeConfig(
        exchange_name="LowLatencySimulatedExchange",
        exchange_type=ExchangeType.SIMULATED,
        fee_model=FeeModelConfig(
            model_type=FeeModelType.PERCENT,
            fee_rate=Decimal('0.0005')  # 0.05% fee
        ),
        slippage_model=SlippageModelConfig(
            model_type=SlippageModelType.NONE,
            base_slippage_pct=Decimal('0.0'),
            size_impact_factor=Decimal('0.0'),
            max_slippage_pct=Decimal('0.0')
        ),
        limits=ExchangeLimits(
            supported_symbols={'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'},
            min_order_size=Decimal('0.001'),
            max_order_size=Decimal('1000000.0'),
            max_price=Decimal('1000000.0')
        ),
        failure_simulation=FailureSimulation(
            simulate_failures=False,
            failure_rate=Decimal('0.0'),
            enabled_scenarios=[]
        ),
        connection=ConnectionSettings(
            auto_connect=True,
            connection_timeout=Decimal('10.0'),  # Fast timeout
            retry_attempts=1,    # Minimal retries
            retry_delay=Decimal('0.5')  # Fast retry
        )
    )
