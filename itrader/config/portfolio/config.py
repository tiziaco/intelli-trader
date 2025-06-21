"""
Portfolio domain configuration classes.

This module defines configuration classes for portfolio management,
including portfolio settings, limits, and operational parameters.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional
from enum import Enum


class PortfolioType(Enum):
    """Portfolio types."""
    EQUITY = "equity"
    FUTURES = "futures"
    FOREX = "forex"
    CRYPTO = "crypto"
    MIXED = "mixed"


class RiskLevel(Enum):
    """Risk levels for portfolio management."""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass
class PortfolioLimits:
    """Portfolio limits and constraints."""
    max_positions: int = 50
    max_position_value: Decimal = field(default_factory=lambda: Decimal('1000000.0'))
    max_portfolio_concentration: float = 0.25
    max_daily_loss: Optional[Decimal] = None
    max_drawdown: Optional[float] = None
    min_cash_reserve: Decimal = field(default_factory=lambda: Decimal('1000.0'))


@dataclass
class RiskManagement:
    """Risk management configuration."""
    enable_stop_loss: bool = True
    enable_take_profit: bool = True
    default_stop_loss_pct: float = 0.05
    default_take_profit_pct: float = 0.10
    risk_level: RiskLevel = RiskLevel.MODERATE
    max_risk_per_trade: float = 0.02


@dataclass
class TradingRules:
    """Trading rules and preferences."""
    allow_short_selling: bool = False
    enable_margin: bool = False
    enable_options: bool = False
    enable_futures: bool = False
    min_trade_amount: Decimal = field(default_factory=lambda: Decimal('100.0'))
    max_trade_amount: Optional[Decimal] = None


@dataclass
class PortfolioConfig:
    """
    Main portfolio configuration class.
    
    This class contains all configuration parameters for a portfolio,
    including limits, risk management, and trading rules.
    """
    
    # Basic settings
    portfolio_id: Optional[int] = None
    name: str = "Default Portfolio"
    description: str = ""
    portfolio_type: PortfolioType = PortfolioType.EQUITY
    base_currency: str = "USD"
    initial_capital: Decimal = field(default_factory=lambda: Decimal('100000.0'))
    
    # Configuration objects
    limits: PortfolioLimits = field(default_factory=PortfolioLimits)
    risk_management: RiskManagement = field(default_factory=RiskManagement)
    trading_rules: TradingRules = field(default_factory=TradingRules)
    
    # Operational settings
    enable_analytics: bool = True
    enable_notifications: bool = True
    auto_rebalance: bool = False
    rebalance_frequency: str = "monthly"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        result = {}
        
        # Basic settings
        result['portfolio_id'] = self.portfolio_id
        result['name'] = self.name
        result['description'] = self.description
        result['portfolio_type'] = self.portfolio_type.value
        result['base_currency'] = self.base_currency
        result['initial_capital'] = str(self.initial_capital)
        
        # Configuration objects
        result['limits'] = {
            'max_positions': self.limits.max_positions,
            'max_position_value': str(self.limits.max_position_value),
            'max_portfolio_concentration': self.limits.max_portfolio_concentration,
            'max_daily_loss': str(self.limits.max_daily_loss) if self.limits.max_daily_loss else None,
            'max_drawdown': self.limits.max_drawdown,
            'min_cash_reserve': str(self.limits.min_cash_reserve)
        }
        
        result['risk_management'] = {
            'enable_stop_loss': self.risk_management.enable_stop_loss,
            'enable_take_profit': self.risk_management.enable_take_profit,
            'default_stop_loss_pct': self.risk_management.default_stop_loss_pct,
            'default_take_profit_pct': self.risk_management.default_take_profit_pct,
            'risk_level': self.risk_management.risk_level.value,
            'max_risk_per_trade': self.risk_management.max_risk_per_trade
        }
        
        result['trading_rules'] = {
            'allow_short_selling': self.trading_rules.allow_short_selling,
            'enable_margin': self.trading_rules.enable_margin,
            'enable_options': self.trading_rules.enable_options,
            'enable_futures': self.trading_rules.enable_futures,
            'min_trade_amount': str(self.trading_rules.min_trade_amount),
            'max_trade_amount': str(self.trading_rules.max_trade_amount) if self.trading_rules.max_trade_amount else None
        }
        
        # Operational settings
        result['enable_analytics'] = self.enable_analytics
        result['enable_notifications'] = self.enable_notifications
        result['auto_rebalance'] = self.auto_rebalance
        result['rebalance_frequency'] = self.rebalance_frequency
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PortfolioConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        # Basic settings
        config.portfolio_id = data.get('portfolio_id')
        config.name = data.get('name', config.name)
        config.description = data.get('description', config.description)
        
        if 'portfolio_type' in data:
            config.portfolio_type = PortfolioType(data['portfolio_type'])
        
        config.base_currency = data.get('base_currency', config.base_currency)
        
        if 'initial_capital' in data:
            config.initial_capital = Decimal(str(data['initial_capital']))
        
        # Limits
        if 'limits' in data:
            limits_data = data['limits']
            config.limits = PortfolioLimits(
                max_positions=limits_data.get('max_positions', config.limits.max_positions),
                max_position_value=Decimal(str(limits_data.get('max_position_value', config.limits.max_position_value))),
                max_portfolio_concentration=limits_data.get('max_portfolio_concentration', config.limits.max_portfolio_concentration),
                max_daily_loss=Decimal(str(limits_data['max_daily_loss'])) if limits_data.get('max_daily_loss') else None,
                max_drawdown=limits_data.get('max_drawdown'),
                min_cash_reserve=Decimal(str(limits_data.get('min_cash_reserve', config.limits.min_cash_reserve)))
            )
        
        # Risk management
        if 'risk_management' in data:
            risk_data = data['risk_management']
            config.risk_management = RiskManagement(
                enable_stop_loss=risk_data.get('enable_stop_loss', config.risk_management.enable_stop_loss),
                enable_take_profit=risk_data.get('enable_take_profit', config.risk_management.enable_take_profit),
                default_stop_loss_pct=risk_data.get('default_stop_loss_pct', config.risk_management.default_stop_loss_pct),
                default_take_profit_pct=risk_data.get('default_take_profit_pct', config.risk_management.default_take_profit_pct),
                risk_level=RiskLevel(risk_data.get('risk_level', config.risk_management.risk_level.value)),
                max_risk_per_trade=risk_data.get('max_risk_per_trade', config.risk_management.max_risk_per_trade)
            )
        
        # Trading rules
        if 'trading_rules' in data:
            trading_data = data['trading_rules']
            config.trading_rules = TradingRules(
                allow_short_selling=trading_data.get('allow_short_selling', config.trading_rules.allow_short_selling),
                enable_margin=trading_data.get('enable_margin', config.trading_rules.enable_margin),
                enable_options=trading_data.get('enable_options', config.trading_rules.enable_options),
                enable_futures=trading_data.get('enable_futures', config.trading_rules.enable_futures),
                min_trade_amount=Decimal(str(trading_data.get('min_trade_amount', config.trading_rules.min_trade_amount))),
                max_trade_amount=Decimal(str(trading_data['max_trade_amount'])) if trading_data.get('max_trade_amount') else None
            )
        
        # Operational settings
        config.enable_analytics = data.get('enable_analytics', config.enable_analytics)
        config.enable_notifications = data.get('enable_notifications', config.enable_notifications)
        config.auto_rebalance = data.get('auto_rebalance', config.auto_rebalance)
        config.rebalance_frequency = data.get('rebalance_frequency', config.rebalance_frequency)
        
        return config
