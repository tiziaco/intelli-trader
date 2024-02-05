import os
import json

# Set the project base directory
basedir = os.path.abspath(os.path.dirname(__file__))
# Load API keys from JSON file
with open('keys.json', 'r') as keys_file:
	keys_data = json.load(keys_file)

TIMEZONE = 'Europe/Paris'
SUPPORTED_CURRENCIES = {'USDT', 'BUSD'}
SUPPORTED_EXCHANGES = {'BINANCE', 'KUCOIN'}
LOGGING = {'DATE_FORMAT': '%Y-%m-%d %H:%M:%S'}


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

	SECRET_KEYS = keys_data.get('SECRET_KEYS', {})
	PRINT_LOG = True
	SAVE_LOG = False

class DevelopmentConfig(Config):
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = True
	TESTING = False
	SQLALCHEMY_TRACK_MODIFICATIONS = False


class TestingConfig(Config):
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = False
	TESTING = True
	PRESERVE_CONTEXT_ON_EXCEPTION = False
	SQLALCHEMY_TRACK_MODIFICATIONS = False


class BacktestConfig(Config):
	DEBUG = False
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = False
	TESTING = False
	PRESERVE_CONTEXT_ON_EXCEPTION = True
	SQLALCHEMY_TRACK_MODIFICATIONS = True

class LiveConfig(Config):
	DEBUG = False
	DATA_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices'
	SYSTEM_DB_URL = 'postgresql+psycopg2://postgres:1234@localhost:5432/.......'
	DEBUG = False
	TESTING = False
	PRESERVE_CONTEXT_ON_EXCEPTION = True
	SQLALCHEMY_TRACK_MODIFICATIONS = True


set_config = dict(
	dev = DevelopmentConfig,
	test = TestingConfig,
	backtest = BacktestConfig,
	live = LiveConfig
)

def set_print_events(print_events=True):
	global PRINT_EVENTS
	PRINT_EVENTS = print_events
