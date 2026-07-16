from itrader.config import ITraderConfig
from itrader.logger import init_logger
from itrader.outils.id_generator import IDGenerator

# Initialize configuration directly (P9 D-06): construct the frozen ITraderConfig root
# ONCE at import with documented defaults + empty persisted overrides (import-inert — no
# SQL/ccxt). The singleton is MUTATED IN PLACE and NEVER reassigned (Pitfall 6): the live
# factory layers persisted overrides into config.<sub>.<field> at boot, so every
# `from itrader import config` importer sees the change. A backtest run needs no override
# (the rng_seed default 42 on the frozen base is the deterministic seed, RTCFG-04).
config = ITraderConfig()

# Initialize logger and ID generator
logger = init_logger(config)
idgen = IDGenerator()
