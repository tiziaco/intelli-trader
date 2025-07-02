"""
Default portfolio configurations and presets.

This module provides default configuration values and preset configurations
for different types of portfolios and risk profiles.
"""

from decimal import Decimal
from typing import Dict, Any

from .config import PortfolioConfig, PortfolioType, RiskLevel, PortfolioLimits, RiskManagement, TradingRules


def get_default_portfolio_config() -> PortfolioConfig:
    """Get default portfolio configuration."""
    return PortfolioConfig()


def get_conservative_portfolio_preset() -> PortfolioConfig:
    """Get conservative portfolio configuration preset."""
    return PortfolioConfig(
        name="Conservative Portfolio",
        description="Low-risk portfolio focused on capital preservation",
        portfolio_type=PortfolioType.EQUITY,
        initial_capital=Decimal('50000.0'),
        limits=PortfolioLimits(
            max_positions=20,
            max_position_value=Decimal('10000.0'),
            max_portfolio_concentration=0.15,
            max_daily_loss=Decimal('500.0'),
            max_drawdown=0.05,
            min_cash_reserve=Decimal('5000.0')
        ),
        risk_management=RiskManagement(
            enable_stop_loss=True,
            enable_take_profit=True,
            default_stop_loss_pct=0.03,
            default_take_profit_pct=0.06,
            risk_level=RiskLevel.CONSERVATIVE,
            max_risk_per_trade=0.01
        ),
        trading_rules=TradingRules(
            allow_short_selling=False,
            enable_margin=False,
            enable_options=False,
            enable_futures=False,
            min_trade_amount=Decimal('500.0'),
            max_trade_amount=Decimal('5000.0')
        ),
        auto_rebalance=True,
        rebalance_frequency="monthly"
    )


def get_moderate_portfolio_preset() -> PortfolioConfig:
    """Get moderate portfolio configuration preset."""
    return PortfolioConfig(
        name="Moderate Portfolio",
        description="Balanced portfolio with moderate risk tolerance",
        portfolio_type=PortfolioType.MIXED,
        initial_capital=Decimal('100000.0'),
        limits=PortfolioLimits(
            max_positions=30,
            max_position_value=Decimal('25000.0'),
            max_portfolio_concentration=0.20,
            max_daily_loss=Decimal('2000.0'),
            max_drawdown=0.10,
            min_cash_reserve=Decimal('10000.0')
        ),
        risk_management=RiskManagement(
            enable_stop_loss=True,
            enable_take_profit=True,
            default_stop_loss_pct=0.05,
            default_take_profit_pct=0.10,
            risk_level=RiskLevel.MODERATE,
            max_risk_per_trade=0.02
        ),
        trading_rules=TradingRules(
            allow_short_selling=False,
            enable_margin=True,
            enable_options=True,
            enable_futures=False,
            min_trade_amount=Decimal('1000.0'),
            max_trade_amount=Decimal('15000.0')
        ),
        auto_rebalance=True,
        rebalance_frequency="monthly"
    )


def get_aggressive_portfolio_preset() -> PortfolioConfig:
    """Get aggressive portfolio configuration preset."""
    return PortfolioConfig(
        name="Aggressive Portfolio",
        description="High-risk, high-reward portfolio for experienced traders",
        portfolio_type=PortfolioType.MIXED,
        initial_capital=Decimal('250000.0'),
        limits=PortfolioLimits(
            max_positions=50,
            max_position_value=Decimal('100000.0'),
            max_portfolio_concentration=0.30,
            max_daily_loss=Decimal('10000.0'),
            max_drawdown=0.20,
            min_cash_reserve=Decimal('25000.0')
        ),
        risk_management=RiskManagement(
            enable_stop_loss=True,
            enable_take_profit=True,
            default_stop_loss_pct=0.08,
            default_take_profit_pct=0.15,
            risk_level=RiskLevel.AGGRESSIVE,
            max_risk_per_trade=0.05
        ),
        trading_rules=TradingRules(
            allow_short_selling=True,
            enable_margin=True,
            enable_options=True,
            enable_futures=True,
            min_trade_amount=Decimal('2000.0'),
            max_trade_amount=Decimal('50000.0')
        ),
        auto_rebalance=False,
        rebalance_frequency="quarterly"
    )


def get_crypto_portfolio_preset() -> PortfolioConfig:
    """Get cryptocurrency portfolio configuration preset."""
    return PortfolioConfig(
        name="Crypto Portfolio",
        description="Cryptocurrency trading portfolio with high volatility tolerance",
        portfolio_type=PortfolioType.CRYPTO,
        base_currency="USDT",
        initial_capital=Decimal('50000.0'),
        limits=PortfolioLimits(
            max_positions=15,
            max_position_value=Decimal('20000.0'),
            max_portfolio_concentration=0.35,
            max_daily_loss=Decimal('5000.0'),
            max_drawdown=0.30,
            min_cash_reserve=Decimal('5000.0')
        ),
        risk_management=RiskManagement(
            enable_stop_loss=True,
            enable_take_profit=True,
            default_stop_loss_pct=0.10,
            default_take_profit_pct=0.20,
            risk_level=RiskLevel.AGGRESSIVE,
            max_risk_per_trade=0.03
        ),
        trading_rules=TradingRules(
            allow_short_selling=True,
            enable_margin=True,
            enable_options=False,
            enable_futures=True,
            min_trade_amount=Decimal('100.0'),
            max_trade_amount=Decimal('10000.0')
        ),
        auto_rebalance=False,
        rebalance_frequency="weekly"
    )


def get_portfolio_preset(preset_name: str) -> PortfolioConfig:
    """
    Get a portfolio configuration preset by name.
    
    Args:
        preset_name: Name of the preset ('conservative', 'moderate', 'aggressive', 'crypto')
        
    Returns:
        PortfolioConfig instance for the preset
        
    Raises:
        ValueError: If preset_name is not recognized
    """
    presets = {
        'default': get_default_portfolio_config,
        'conservative': get_conservative_portfolio_preset,
        'moderate': get_moderate_portfolio_preset,
        'aggressive': get_aggressive_portfolio_preset,
        'crypto': get_crypto_portfolio_preset
    }
    
    if preset_name not in presets:
        raise ValueError(f"Unknown portfolio preset: {preset_name}. Available presets: {list(presets.keys())}")
    
    return presets[preset_name]()


def get_default_portfolio_dict() -> Dict[str, Any]:
    """Get default portfolio configuration as dictionary."""
    return get_default_portfolio_config().to_dict()


def list_available_presets() -> list[str]:
    """List all available portfolio presets."""
    return ['default', 'conservative', 'moderate', 'aggressive', 'crypto']
