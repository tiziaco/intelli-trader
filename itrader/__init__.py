from itrader.config import set_config
from itrader.logger import init_logger
from itrader.config import ENVIRONMENT

config = set_config(ENVIRONMENT)
logger = init_logger(config)