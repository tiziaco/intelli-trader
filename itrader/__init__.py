from itrader.config import SystemConfig
from itrader.logger import init_logger
from itrader.outils.id_generator import IDGenerator

# Initialize configuration directly (M2-06 / D-01): the registry/provider getters were
# deleted; construct the Pydantic SystemConfig with documented defaults. A backtest run
# never needs a YAML override (the rng_seed default is the deterministic seed). Live /
# YAML-driven config wiring is deferred (D-live).
config = SystemConfig.default()

# Initialize logger and ID generator
logger = init_logger(config)
idgen = IDGenerator()
