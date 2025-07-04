"""
Exchange configuration domain.

This module provides exchange-specific configuration management,
including configuration classes, validation schemas, and exchange settings.
"""

from .config import (
    ExchangeConfig, ExchangeType, FeeModelType, SlippageModelType,
    FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation,
    ConnectionSettings
)
from .schema import validate_exchange_config, get_exchange_schema, EXCHANGE_SCHEMA
from .presets import get_exchange_preset, list_available_exchange_presets

__all__ = [
    # Configuration classes
    'ExchangeConfig',
    'ExchangeType',
    'FeeModelType',
    'SlippageModelType',
    'FeeModelConfig',
    'SlippageModelConfig',
    'ExchangeLimits',
    'FailureSimulation',
    'ConnectionSettings',
    
    # Schema and validation
    'validate_exchange_config',
    'get_exchange_schema',
    'EXCHANGE_SCHEMA',
    
    # Presets
    'get_exchange_preset',
    'list_available_exchange_presets'
]
