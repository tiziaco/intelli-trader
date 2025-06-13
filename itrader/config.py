import os

# Load API keys from environment variables instead of JSON file
def load_secret_keys():
    """Load secret keys from environment variables."""
    return {
        'binance_main': {
            'API_KEY': os.getenv('BINANCE_MAIN_API_KEY'),
            'API_SECRET': os.getenv('BINANCE_MAIN_API_SECRET')
        },
        'binance_spot_testnet': {
            'API_KEY': os.getenv('BINANCE_SPOT_TESTNET_API_KEY'),
            'API_SECRET': os.getenv('BINANCE_SPOT_TESTNET_API_SECRET')
        },
        'binance_future_testnet': {
            'API_KEY': os.getenv('BINANCE_FUTURE_TESTNET_API_KEY'),
            'API_SECRET': os.getenv('BINANCE_FUTURE_TESTNET_API_SECRET')
        },
        'oanda_testnet': {
            'ACCOUNT_ID': os.getenv('OANDA_TESTNET_ACCOUNT_ID'),
            'API_KEY': os.getenv('OANDA_TESTNET_API_KEY'),
            'API_SECRET': os.getenv('OANDA_TESTNET_API_SECRET')
        }
    }

keys_data = {'SECRET_KEYS': load_secret_keys()}

ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")  # Get from env or default to "dev"

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
		'BUSD/USDT','TUSD/USDT','GBP/USDT','BTCST/USDT', 'BTG/USDT'
		'USDP/USDT','USDC/USDT','PAX/USDT','USDS/USDT','USDSB/USDT','UST/USDT',
		'T/USDT', 'PAXG/USDT', 'USTC/USDT', 'EUR/USDT', 'AUD/USDT',
		'USDP/USDT', 'BCHABC/USDT' '1INCH/USDT',
	]
}

class Config:
	"""
	iTrader general configuration variables.
	All settings can be overridden via environment variables.
	
	Environment Variables:
	----------------------
	LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO
	DATA_DB_URL: Database URL for price data. Default: postgres://postgres:1234@localhost:5432/trading_system_prices
	SYSTEM_DB_URL: Database URL for system data. Default: postgres://postgres:1234@localhost:5432/.......
	"""
	TIMEZONE = 'Europe/Paris'
	SECRET_KEYS = keys_data.get('SECRET_KEYS', {})
	LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()  # Default to INFO if not set

	# Database URLs - can be overridden via environment variables
	DATA_DB_URL = os.getenv('DATA_DB_URL', 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices')
	SYSTEM_DB_URL = os.getenv('SYSTEM_DB_URL', 'postgresql+psycopg2://postgres:1234@localhost:5432/.......')

	SUPPORTED_CURRENCIES = {'USDT', 'BUSD'}
	SUPPORTED_EXCHANGES = {'BINANCE', 'KUCOIN'}


def set_config(env) -> Config:
    """
    Sets the configuration based on the environment.
    
    This function now mainly validates the environment and returns the Config class.
    All environment-specific behavior is controlled via environment variables.

    Parameters
    ----------
    env : `str`
        Environment identifier ('dev', 'test', 'backtest', 'live').

    Returns
    ----------
    Config : `Config`
        Configuration object with settings loaded from environment variables.

    Raises
    ----------
        ValueError : If the specified environment is not recognized.
    """
    valid_environments = {'dev', 'test', 'backtest', 'live'}
    if env not in valid_environments:
        raise ValueError(f"Unknown environment: {env}. Supported environments are: {valid_environments}.")
    
    return Config
