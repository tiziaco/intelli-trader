import os
import json

# Set the project base directory
basedir = os.path.abspath(os.path.dirname(__file__))

# Load API keys from JSON file
with open(f'{basedir}/keys.json', 'r') as keys_file:
	keys_data = json.load(keys_file)

ENVIRONMENT = "dev" #Supported environments: 'dev', 'test', 'backtest', 'live'

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
		'USDP/USDT', 'BCHABC/USDT' #'1INCH/USDT',
	]
}

class Config:
	"""
	iTrader general configuration variables.
	"""
	TIMEZONE = 'Europe/Paris'
	SECRET_KEYS = keys_data.get('SECRET_KEYS', {})

	LOGGING_FORMAT = str('%(levelname)s | %(message)s') # %(asctime)s 
	PRINT_LOG = bool(True)
	SAVE_LOG = bool(False)

	SUPPORTED_CURRENCIES = {'USDT', 'BUSD'}
	SUPPORTED_EXCHANGES = {'BINANCE', 'KUCOIN'}

class DevelopmentConfig(Config):
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = bool(True)
	TESTING = bool(False)
	SQLALCHEMY_TRACK_MODIFICATIONS = bool(False)


class TestingConfig(Config):
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = bool(False)
	TESTING = bool(True)
	PRESERVE_CONTEXT_ON_EXCEPTION = bool(False)
	SQLALCHEMY_TRACK_MODIFICATIONS = bool(False)


class BacktestConfig(Config):
	DEBUG = False
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = bool(False)
	TESTING = bool(False)
	PRESERVE_CONTEXT_ON_EXCEPTION = bool(True)
	SQLALCHEMY_TRACK_MODIFICATIONS = bool(True)

class LiveConfig(Config):
	DEBUG = bool(False)
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = bool(False)
	TESTING = bool(False)
	PRESERVE_CONTEXT_ON_EXCEPTION = bool(True)
	SQLALCHEMY_TRACK_MODIFICATIONS = bool(True)


def set_config(env) -> Config:
    """
    Sets the configuration based on the environment.

    Parameters
    ----------
    env : `str`
		Environment identifier ('dev', 'test', 'backtest', 'live').

    Returns
    ----------
	Config : `Config`
		Configuration object corresponding to the specified environment.

    Raises
    ----------
        ValueError : If the specified environment is not recognized.
    """
    configs = {
        'dev': DevelopmentConfig,
        'test': TestingConfig,
        'backtest': BacktestConfig,
        'live': LiveConfig
    }
    config = configs.get(env)
    if config is None:
        raise ValueError(f"Unknown environment: {env}. Supported environments are: 'dev', 'test', 'backtest', 'live'.")
    return config
