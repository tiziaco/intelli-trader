"""System domain configuration (Pydantic v2, M2-06 / D-01..D-03).

Replaces the deleted hand-rolled ``config/system/`` package. The runtime-critical
surface is ``SystemConfig.performance.rng_seed`` (read by ``ExecutionHandler`` for
determinism). ``from_dict`` is a thin wrapper over ``model_validate`` so a partial /
empty dict still yields documented defaults.
"""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class Environment(str, Enum):
    """Environment types."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class PerformanceSettings(BaseModel):
    """Performance tuning settings."""

    model_config = ConfigDict(extra="ignore")

    max_threads: int = 10
    max_processes: int = 4
    enable_multiprocessing: bool = False
    enable_async: bool = True
    connection_pool_size: int = 20
    timeout_seconds: int = 30
    enable_caching: bool = True
    cache_size_mb: int = 512
    # Determinism seed for stochastic components (D-11, #5/PERF2). Constant default;
    # drives only failure-simulation + slippage jitter, never a security value.
    rng_seed: int = 42


class MonitoringSettings(BaseModel):
    """Monitoring and metrics settings."""

    model_config = ConfigDict(extra="ignore")

    enable_metrics: bool = True
    metrics_port: int = 9090
    enable_health_check: bool = True
    health_check_port: int = 8080
    enable_profiling: bool = False
    profiling_port: int = 8081
    enable_tracing: bool = False


class SystemConfig(BaseModel):
    """Main system configuration."""

    # Tolerate unknown keys from a YAML override (the old from_dict ignored extras).
    model_config = ConfigDict(extra="ignore")

    name: str = "iTrader System"
    version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug_mode: bool = True

    data_dir: str = "data"
    log_dir: str = "logs"
    config_dir: str = "settings"
    cache_dir: str = "cache"

    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)

    enable_auto_restart: bool = False
    auto_restart_delay_seconds: int = 10
    enable_graceful_shutdown: bool = True
    shutdown_timeout_seconds: int = 30

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SystemConfig":
        """Build from a (possibly partial/empty) dict; missing keys take defaults."""
        return cls.model_validate(data or {})

    @classmethod
    def default(cls) -> "SystemConfig":
        """Default system config (documented defaults; rng_seed=42)."""
        return cls()
