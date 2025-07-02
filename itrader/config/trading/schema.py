"""
Trading configuration schema definitions.

This module defines validation schemas for trading configurations
to ensure data integrity and consistency.
"""

from typing import Dict, Any

# Trading configuration schema
TRADING_SCHEMA = {
    'name': str,
    'description': str,
    'enable_trading': bool,
    'order_defaults': {
        'default_order_type': str,
        'default_time_in_force': str,
        'default_quantity': (str, type(None)),
        'max_order_size': (str, type(None)),
        'min_order_size': str
    },
    'execution': {
        'mode': str,
        'max_orders_per_second': int,
        'max_concurrent_orders': int,
        'enable_partial_fills': bool,
        'enable_order_routing': bool,
        'default_exchange': str,
        'supported_exchanges': list
    },
    'risk_controls': {
        'enable_position_limits': bool,
        'enable_order_size_limits': bool,
        'enable_daily_loss_limits': bool,
        'max_position_size': (str, type(None)),
        'max_daily_trades': (int, type(None)),
        'max_daily_volume': (str, type(None)),
        'enable_pre_trade_checks': bool
    },
    'fees': {
        'maker_fee': float,
        'taker_fee': float,
        'enable_fee_calculation': bool,
        'fee_currency': str
    },
    'strategies': {
        'enable_strategy_manager': bool,
        'max_active_strategies': int,
        'enable_strategy_isolation': bool,
        'strategy_timeout_seconds': int,
        'enable_strategy_logging': bool
    },
    'enable_logging': bool,
    'log_level': str,
    'enable_metrics': bool,
    'enable_alerts': bool
}


def validate_trading_config(config: Dict[str, Any]) -> bool:
    """
    Validate trading configuration data.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Check required top-level fields
        required_fields = ['name', 'enable_trading']
        for field in required_fields:
            if field not in config:
                return False
        
        # Validate order types
        if 'order_defaults' in config:
            order_defaults = config['order_defaults']
            valid_order_types = ['market', 'limit', 'stop', 'stop_limit']
            if 'default_order_type' in order_defaults:
                if order_defaults['default_order_type'] not in valid_order_types:
                    return False
            
            valid_tif = ['gtc', 'ioc', 'fok', 'day']
            if 'default_time_in_force' in order_defaults:
                if order_defaults['default_time_in_force'] not in valid_tif:
                    return False
        
        # Validate execution mode
        if 'execution' in config:
            execution = config['execution']
            valid_modes = ['simulation', 'paper', 'live']
            if 'mode' in execution:
                if execution['mode'] not in valid_modes:
                    return False
            
            # Validate limits
            if 'max_orders_per_second' in execution:
                if execution['max_orders_per_second'] <= 0:
                    return False
            
            if 'max_concurrent_orders' in execution:
                if execution['max_concurrent_orders'] <= 0:
                    return False
        
        # Validate fees
        if 'fees' in config:
            fees = config['fees']
            if 'maker_fee' in fees:
                if not (0 <= fees['maker_fee'] <= 1):
                    return False
            if 'taker_fee' in fees:
                if not (0 <= fees['taker_fee'] <= 1):
                    return False
        
        # Validate log level
        if 'log_level' in config:
            valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
            if config['log_level'] not in valid_levels:
                return False
        
        # Validate strategy settings
        if 'strategies' in config:
            strategies = config['strategies']
            if 'max_active_strategies' in strategies:
                if strategies['max_active_strategies'] <= 0:
                    return False
            
            if 'strategy_timeout_seconds' in strategies:
                if strategies['strategy_timeout_seconds'] <= 0:
                    return False
        
        return True
        
    except Exception:
        return False


def get_trading_schema() -> Dict[str, Any]:
    """Get the trading configuration schema."""
    return TRADING_SCHEMA.copy()
