"""
Trading configuration domain.

This module provides trading-specific configuration management,
including configuration classes, validation schemas, and execution settings.
"""

from .config import (
    TradingConfig, OrderType, TimeInForce, ExecutionMode,
    OrderDefaults, ExecutionSettings, RiskControls, FeeStructure, StrategySettings
)
from .schema import validate_trading_config, get_trading_schema, TRADING_SCHEMA

__all__ = [
    # Configuration classes
    'TradingConfig',
    'OrderType',
    'TimeInForce',
    'ExecutionMode',
    'OrderDefaults',
    'ExecutionSettings',
    'RiskControls',
    'FeeStructure',
    'StrategySettings',
    
    # Schema and validation
    'validate_trading_config',
    'get_trading_schema',
    'TRADING_SCHEMA'
]
