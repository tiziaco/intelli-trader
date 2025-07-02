"""
Legacy configuration module for backward compatibility.

This module provides backward compatibility with the old configuration system
while delegating to the new unified configuration management system.
"""

# Import everything from the new config system for backward compatibility
from itrader.config import (
    set_config,
    ENVIRONMENT,
    get_system_config
)

# Legacy compatibility
def load_secret_keys():
    """Load secret keys from environment variables."""
    system_config = get_system_config()
    return system_config.get_secret_keys()

# Create legacy data structure
keys_data = {'SECRET_KEYS': load_secret_keys()}

# Legacy constants
SUPPORTED_CURRENCIES = {'USDT', 'BUSD'}
SUPPORTED_EXCHANGES = {'BINANCE', 'KUCOIN'}

FORBIDDEN_SYMBOLS = {
    'BUSD': [
        'BUSD/BUSD', 'TUSD/BUSD', 'GBP/BUSD', 'BTCST/BUSD', 'BTG/BUSD',
        'USDP/BUSD', 'USDC/BUSD', 'PAX/BUSD', 'USDS/BUSD', 'USDSB/BUSD', 'UST/BUSD',
        '1INCH/BUSD', 'T/BUSD', 'PAXG/BUSD', 'USTC/BUSD', 'EUR/BUSD', 'AUD/BUSD',
        'USDP/BUSD', 'WBTC/BUSD', 'BETH/BUSD'
    ],
    'USDT': [
        'BUSD/USDT','TUSD/USDT','GBP/USDT','BTCST/USDT', 'BTG/USDT',
        'USDP/USDT','USDC/USDT','PAX/USDT','USDS/USDT','USDSB/USDT','UST/USDT',
        'T/USDT', 'PAXG/USDT', 'USTC/USDT', 'EUR/USDT', 'AUD/USDT',
        'USDP/USDT', 'BCHABC/USDT', '1INCH/USDT',
    ]
}

class Config:
    """
    Legacy Config class for backward compatibility.
    
    This now delegates to the new SystemConfig but maintains the same interface.
    """
    def __init__(self):
        self._system_config = get_system_config()
    
    @property
    def TIMEZONE(self):
        return self._system_config.timezone
    
    @property
    def SECRET_KEYS(self):
        return self._system_config.get_secret_keys()
    
    @property
    def LOG_LEVEL(self):
        return self._system_config.logging.log_level
    
    @property
    def DATA_DB_URL(self):
        return self._system_config.database.data_db_url
    
    @property
    def SYSTEM_DB_URL(self):
        return self._system_config.database.system_db_url
    
    @property
    def SUPPORTED_CURRENCIES(self):
        return self._system_config.exchanges.supported_currencies
    
    @property
    def SUPPORTED_EXCHANGES(self):
        return self._system_config.exchanges.supported_exchanges
    
    @property
    def FORBIDDEN_SYMBOLS(self):
        return self._system_config.forbidden_symbols


# For backward compatibility, keep the old set_config function
# It's already defined in the new config system and imported above
