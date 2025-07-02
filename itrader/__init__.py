from itrader.config import get_config_registry, get_system_config_provider
from itrader.logger import init_logger
from itrader.outils.id_generator import IDGenerator

# Initialize configuration system
config_registry = get_config_registry()
system_provider = get_system_config_provider(config_registry)
config = system_provider.get_config()

# Initialize logger and ID generator
logger = init_logger(config)
idgen = IDGenerator()