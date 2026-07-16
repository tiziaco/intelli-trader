"""System domain configuration (Pydantic v2, M2-06 / D-01..D-03; P9 D-08/D-09).

Replaces the deleted hand-rolled ``config/system/`` package. Home of the ``Environment``
/``LogLevel`` enums and — since P9 — the demoted ``SystemSettings`` (lifecycle knobs, D-08)
and ``UniverseConfig`` (live universe poll cadence + remove policy, ex-``MonitoringSettings``
2 used fields, D-09) mutable sub-models mounted on the frozen ``ITraderConfig`` root
(``config/itrader_config.py``). The oracle-critical determinism seed now lives on the frozen
base as ``config.rng_seed`` (moved off the retired ``PerformanceSettings``, D-09).

``ITraderConfig`` is the sole process config root; the legacy ``SystemConfig`` aggregator
has been removed — this module keeps only the shared enums + the two demoted sub-models.
"""

from enum import Enum

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
