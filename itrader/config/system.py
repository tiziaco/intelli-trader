"""System domain configuration (Pydantic v2, M2-06 / D-01..D-03).

Replaces the deleted hand-rolled ``config/system/`` package. The runtime-critical
surface is ``SystemConfig.performance.rng_seed`` (read by ``ExecutionHandler`` for
determinism). ``from_dict`` is a thin wrapper over ``model_validate`` so a partial /
empty dict still yields documented defaults.
"""

from enum import Enum
from functools import cached_property
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from itrader.config.safety import SafetySettings
from itrader.config.settings import Settings
from itrader.config.stream import FeedProviderSettings, StreamSettings

if TYPE_CHECKING:
    # Import here only to type the ``sql`` cached_property. The concrete import runs
    # lazily inside the property body so ``config/sql`` (and its transitive
    # ``sqlalchemy`` dependency) stays OFF the backtest import graph — GATE-01
    # (tests/unit/storage/test_import_quarantine.py). See D-05/D-06.
    from itrader.config.sql import SqlSettings


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
    # Live/control-plane ONLY (Phase 06-05, D-01/D-02): the dynamic-universe poll
    # cadence (seconds between membership polls, decoupled from bars per D-02) and
    # the open-position-on-remove disposition (orphan-and-track vs force-close,
    # D-01). These live on the monitoring/live plane, NEVER on PerformanceSettings
    # (which carries the oracle-critical rng_seed): they are read only by the
    # live-only poll-timer daemon + UniverseHandler, never on the backtest hot path
    # (the backtest builds its own EventHandler with an empty UNIVERSE_UPDATE route
    # and never constructs the handler or starts the timer), so the oracle-critical
    # config surface stays untouched.
    universe_poll_cadence_s: float = Field(default=60.0, gt=0.0)
    universe_remove_policy: str = "orphan-and-track"


class SystemSettings(BaseModel):
    """Demoted system-lifecycle sub-model (D-08).

    The lifecycle knobs that used to live directly on the ``SystemConfig`` aggregator
    demote here so the new frozen ``ITraderConfig`` root carries only immutable
    identity/determinism base params + mutable domain sub-models. This is a MUTABLE
    overlay: ``validate_assignment=True`` (D-13) re-runs coercion + ``Field(...)``
    constraints on every ``setattr`` so the P9 runtime-config router can mutate these
    keys via ``config.system.<field> = value``. ``extra`` is forbidden (mass-assignment
    defense, D-11). Inventory pass (D-08): these four are the only lifecycle knobs — the
    residual live-runner module tunables (``_LIVE_QUEUE_TIMEOUT``/``_LIVE_MAX_IDLE_TIME``)
    are LiveRunner-local, not system-lifecycle config, so they are deliberately NOT folded.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enable_auto_restart: bool = False
    auto_restart_delay_seconds: int = 10
    enable_graceful_shutdown: bool = True
    shutdown_timeout_seconds: int = 30


class UniverseConfig(BaseModel):
    """Live dynamic-universe sub-model (ex-``MonitoringSettings`` 2 used fields, D-09).

    Folds the only two consumed ``MonitoringSettings`` fields into a dedicated mutable
    sub-model, dropping the redundant ``universe_`` prefix (the handler already calls the
    param ``remove_policy``). Live/control-plane ONLY: read by the live-only universe
    poll-timer daemon + ``UniverseHandler``, NEVER on the backtest hot path (the backtest
    builds its own ``EventHandler`` with an empty ``UNIVERSE_UPDATE`` route and never
    constructs the handler or starts the timer), so the oracle-critical config surface
    stays untouched. Mutable overlay: ``validate_assignment=True`` (D-13); ``extra``
    forbidden (D-11).

    - ``poll_cadence_s`` — seconds between membership polls, decoupled from bars (D-02).
    - ``remove_policy`` — the open-position-on-remove disposition (orphan-and-track vs
      force-close, D-01).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    poll_cadence_s: float = Field(default=60.0, gt=0.0)
    remove_policy: str = "orphan-and-track"


class SystemConfig(BaseModel):
    """Main system configuration."""

    # D-09: reject unknown keys. The domain YAML that historically fed extras is
    # orphaned/dead (no loader references it), so a stray key is now a config typo
    # to catch loudly rather than silently absorb.
    model_config = ConfigDict(extra="forbid")

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

    # IN-01 / D-08: eager config home for the live stream + feed-provider settings.
    # config/stream.py imports only pydantic/stdlib (no ccxt/async/sql), so these
    # eager fields stay on the backtest import graph WITHOUT regressing inertness —
    # they are the single wiring source that replaces the retired inline
    # ``StreamSettings()`` / ``FeedProviderSettings()`` default-constructions.
    stream: StreamSettings = Field(default_factory=StreamSettings)
    feed_provider: FeedProviderSettings = Field(default_factory=FeedProviderSettings)

    # SAFE-06 / D-07/D-13/D-14: eager config home for the pre-trade safety caps.
    # config/safety.py imports only pydantic/stdlib (no ccxt/async/sql), so this
    # eager field stays on the backtest import graph WITHOUT regressing inertness —
    # exactly as the stream/feed_provider fields above. Static caps only here; the P9
    # runtime-mutation allowlist SHAPES around SafetySettings (no ConfigUpdateEvent
    # wiring in P7).
    safety: SafetySettings = Field(default_factory=SafetySettings)

    # D-07: eager runtime env layer. Constructing Settings reads ITRADER_* env but
    # builds NO SqlSettings (Settings carries no DB fields — the DB surface lives
    # wholly on the lazy `sql` accessor below), so this stays import-safe.
    runtime: Settings = Field(default_factory=Settings)

    enable_auto_restart: bool = False
    auto_restart_delay_seconds: int = 10
    enable_graceful_shutdown: bool = True
    shutdown_timeout_seconds: int = 30

    @cached_property
    def sql(self) -> "SqlSettings":
        """Lazy SQL backend config (D-05/D-06) — NOT a pydantic field.

        Constructed on FIRST access only; no ``SqlSettings`` is built at import or at
        ``SystemConfig`` construction (the inertness lever this milestone leans on —
        ``"sql" not in config.__dict__`` right after import). ``SqlSettings`` defaults
        to the SQLite arm (no credentials required); when the env selects the Postgres
        arm without a password/url its ``_require_pg_credentials`` validator raises
        ``pydantic.ValidationError``. That raising body is intentionally NOT cached, so
        it re-raises on each access rather than caching a half-built object.
        """
        from itrader.config.sql import SqlSettings

        return SqlSettings()

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SystemConfig":
        """Build from a (possibly partial/empty) dict; missing keys take defaults.

        Under ``extra="forbid"`` (D-09) any UNKNOWN key raises ``pydantic.ValidationError``
        rather than being silently ignored — the old tolerate-extras behaviour is gone.
        """
        return cls.model_validate(data or {})

    @classmethod
    def default(cls) -> "SystemConfig":
        """Default system config (documented defaults; rng_seed=42)."""
        return cls()
