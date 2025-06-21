"""
Portfolio configuration schema definitions.

This module defines validation schemas for portfolio configurations
to ensure data integrity and consistency.
"""

from typing import Dict, Any

# Portfolio configuration schema
PORTFOLIO_SCHEMA = {
    'portfolio_id': (int, type(None)),
    'name': str,
    'description': str,
    'portfolio_type': str,
    'base_currency': str,
    'initial_capital': str,
    'limits': {
        'max_positions': int,
        'max_position_value': str,
        'max_portfolio_concentration': float,
        'max_daily_loss': (str, type(None)),
        'max_drawdown': (float, type(None)),
        'min_cash_reserve': str
    },
    'risk_management': {
        'enable_stop_loss': bool,
        'enable_take_profit': bool,
        'default_stop_loss_pct': float,
        'default_take_profit_pct': float,
        'risk_level': str,
        'max_risk_per_trade': float
    },
    'trading_rules': {
        'allow_short_selling': bool,
        'enable_margin': bool,
        'enable_options': bool,
        'enable_futures': bool,
        'min_trade_amount': str,
        'max_trade_amount': (str, type(None))
    },
    'enable_analytics': bool,
    'enable_notifications': bool,
    'auto_rebalance': bool,
    'rebalance_frequency': str
}


def validate_portfolio_config(config: Dict[str, Any]) -> bool:
    """
    Validate portfolio configuration data.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Check required top-level fields
        required_fields = ['name', 'portfolio_type', 'base_currency', 'initial_capital']
        for field in required_fields:
            if field not in config:
                return False
        
        # Validate portfolio type
        valid_types = ['equity', 'futures', 'forex', 'crypto', 'mixed']
        if config['portfolio_type'] not in valid_types:
            return False
        
        # Validate currency code (basic check)
        if len(config['base_currency']) != 3:
            return False
        
        # Validate initial capital is positive
        try:
            from decimal import Decimal
            initial_capital = Decimal(str(config['initial_capital']))
            if initial_capital <= 0:
                return False
        except:
            return False
        
        # Validate limits if present
        if 'limits' in config:
            limits = config['limits']
            if 'max_positions' in limits and limits['max_positions'] <= 0:
                return False
            if 'max_portfolio_concentration' in limits:
                conc = limits['max_portfolio_concentration']
                if not (0 < conc <= 1):
                    return False
        
        # Validate risk management if present
        if 'risk_management' in config:
            risk = config['risk_management']
            if 'risk_level' in risk:
                valid_levels = ['conservative', 'moderate', 'aggressive']
                if risk['risk_level'] not in valid_levels:
                    return False
            if 'max_risk_per_trade' in risk:
                if not (0 < risk['max_risk_per_trade'] <= 1):
                    return False
        
        # Validate rebalance frequency if present
        if 'rebalance_frequency' in config:
            valid_frequencies = ['daily', 'weekly', 'monthly', 'quarterly', 'annually']
            if config['rebalance_frequency'] not in valid_frequencies:
                return False
        
        return True
        
    except Exception:
        return False


def get_portfolio_schema() -> Dict[str, Any]:
    """Get the portfolio configuration schema."""
    return PORTFOLIO_SCHEMA.copy()
