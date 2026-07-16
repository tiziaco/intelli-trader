"""Top-level frozen runtime-config aggregator (Pydantic v2, D-04..D-09).

``ITraderConfig`` is the ROOT config object (D-06), replacing the retired legacy
top-level aggregator. It is the single process-wide ``config`` singleton constructed
once at import in
``itrader/__init__.py`` and mutated in place, never reassigned (Pitfall 6 — the live
factory in Wave 3 mutates ``config.<sub>.<field>`` in place so ``from itrader import
config`` importers see every change).

Structure (D-07):
  - The ``frozen=True`` BASE params (``rng_seed``, ``environment``, ``timezone``,
    identity, dirs) are the immutable determinism/identity guard — a runtime ``setattr``
    on a base param raises ``pydantic.ValidationError`` (RTCFG-04). ⚠ Pitfall 5: the
    frozen guard ONLY protects fields placed DIRECTLY on this base; a field nested inside
    a mutable sub-model is fully mutable (including whole-object swap). Every
    immutable-at-runtime key MUST be a direct base field here.
  - The domain sub-models (``system``/``universe``/``stream``/``feed_provider``/
    ``safety``/``order``/``logging``) are the MUTABLE overlay — each carries
    ``validate_assignment=True`` (D-13) so every field ``setattr`` re-runs coercion +
    ``Field(...)`` constraints. This is the runtime-config mutation surface (Wave 2).

Inertness (GATE-01, Pitfall 3): this module imports pydantic/stdlib ONLY; the DB surface
stays behind the lazy ``sql`` ``@cached_property`` (ported verbatim from the retired
top-level aggregator), so ``config = ITraderConfig()`` at import pulls NO sqlalchemy/ccxt.
Persisted-override LOADING happens in the live factory (``build_live_system``), never at
import.

⚠ Pitfall 4 (unhashable): ``frozen=True`` gives the model a ``__hash__``, but
``hash(config)`` raises ``TypeError`` because it hashes field values and the mutable
sub-models are unhashable. NEVER use ``config`` as a dict/set key or a cache key — it is
a singleton accessed by import.
"""

from functools import cached_property
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from itrader.config.order import OrderConfig
from itrader.config.runtime import RuntimeSettings
from itrader.config.safety import SafetySettings
from itrader.config.stream import FeedProviderSettings, StreamSettings
from itrader.config.system import Environment, SystemSettings, UniverseConfig

if TYPE_CHECKING:
    # Import here only to type the ``sql`` cached_property. The concrete import runs
    # lazily inside the property body so ``config/sql`` (and its transitive
    # ``sqlalchemy`` dependency) stays OFF the backtest import graph — GATE-01.
    from itrader.config.sql import SqlSettings


class ITraderConfig(BaseModel):
    """Frozen top-level runtime-config aggregator (D-06/D-07)."""

    # D-06/D-07: frozen root — base params can't be reassigned and a sub-model reference
    # can't be swapped; unknown keys are rejected (mass-assignment defense, D-11).
    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- FROZEN BASE: immutable determinism + identity (D-04/D-08) ----------------
    # RTCFG-04: a runtime ``setattr`` on any of these raises ValidationError. ``rng_seed``
    # moved up from the retired ``config.performance.rng_seed`` -> ``config.rng_seed``
    # (ORACLE-GATED — must resolve to 42 so the shared ``random.Random(42)`` is unchanged
    # -> byte-exact 134 / 46189.87730727451).
    rng_seed: int = 42
    environment: Environment = Environment.DEVELOPMENT
    name: str = "iTrader System"
    version: str = "1.0.0"
    debug_mode: bool = True

    # Oracle-critical project timezone home (user decision 3). A frozen base param —
    # a runtime ``setattr`` raises ValidationError. ``config.TIMEZONE`` re-derives from
    # this default; it MUST stay "Europe/Paris" or the byte-exact backtest oracle (134
    # trades / 46189.87730727451) breaks.
    timezone: str = "Europe/Paris"

    data_dir: str = "data"
    log_dir: str = "logs"
    config_dir: str = "settings"
    cache_dir: str = "cache"

    # --- MUTABLE SUB-MODELS: the runtime-config mutation overlay (D-07/D-12) -------
    # Each sub-model carries ``validate_assignment=True`` (D-13); the P9 router mutates
    # ``config.<scope>.<field> = value`` field-wise (never a sub-model-reference swap).
    system: SystemSettings = Field(default_factory=SystemSettings)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    stream: StreamSettings = Field(default_factory=StreamSettings)
    feed_provider: FeedProviderSettings = Field(default_factory=FeedProviderSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    order: OrderConfig = Field(default_factory=OrderConfig)

    # D-08: the env-var leaf stays a FIELD (never the root) so ``RuntimeSettings``'s
    # BaseSettings env-parsing (ITRADER_LOG_LEVEL/ITRADER_DISABLE_LOGS) does not leak
    # into every nested field. Named ``logging`` (user decision 4/5 — the legacy
    # ``runtime`` field is gone).
    logging: RuntimeSettings = Field(default_factory=RuntimeSettings)

    @cached_property
    def sql(self) -> "SqlSettings":
        """Lazy SQL backend config (D-05/D-06) — NOT a pydantic field.

        Constructed on FIRST access only; no ``SqlSettings`` is built at import or at
        ``ITraderConfig`` construction (the inertness lever this milestone leans on —
        ``"sql" not in config.__dict__`` right after import). ``SqlSettings`` defaults to
        the SQLite arm (no credentials required); when the env selects the Postgres arm
        without a password/url its ``_require_pg_credentials`` validator raises
        ``pydantic.ValidationError``. That raising body is intentionally NOT cached, so it
        re-raises on each access rather than caching a half-built object.
        """
        from itrader.config.sql import SqlSettings

        return SqlSettings()
