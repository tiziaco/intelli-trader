"""
Portfolio configuration domain.

This module provides portfolio-specific configuration management,
including configuration classes, validation schemas, and default presets.
"""

from .config import (
    PortfolioConfig, PortfolioType, RiskLevel,
    PortfolioLimits, RiskManagement, TradingRules,
    ValidationSettings, EventSettings
)
from .schema import validate_portfolio_config, get_portfolio_schema, PORTFOLIO_SCHEMA
from .defaults import (
    get_default_portfolio_config, get_portfolio_preset,
    get_conservative_portfolio_preset, get_moderate_portfolio_preset,
    get_aggressive_portfolio_preset, get_crypto_portfolio_preset,
    get_default_portfolio_dict, list_available_presets
)

__all__ = [
    # Configuration classes
    'PortfolioConfig',
    'PortfolioType',
    'RiskLevel',
    'PortfolioLimits',
    'RiskManagement',
    'TradingRules',
    'ValidationSettings',
    'EventSettings',
    
    # Schema and validation
    'validate_portfolio_config',
    'get_portfolio_schema',
    'PORTFOLIO_SCHEMA',
    
    # Defaults and presets
    'get_default_portfolio_config',
    'get_portfolio_preset',
    'get_conservative_portfolio_preset',
    'get_moderate_portfolio_preset',
    'get_aggressive_portfolio_preset',
    'get_crypto_portfolio_preset',
    'get_default_portfolio_dict',
    'list_available_presets'
]
