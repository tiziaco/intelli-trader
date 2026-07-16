"""Live dynamic-universe configuration (Pydantic v2, ex-``MonitoringSettings``, D-09).

Home of ``UniverseConfig`` — the live universe poll cadence + open-position remove
policy. Relocated from ``config/system.py`` into its own module to match the ``config/``
one-domain-per-file convention (exchange/order/portfolio/safety/stream/sql/log each own a
file). Live/control-plane ONLY: read by the live-only universe poll-timer daemon +
``UniverseHandler``, NEVER on the backtest hot path, so the oracle-critical config surface
stays untouched. Imports pydantic/stdlib ONLY so ``import itrader`` stays inert (GATE-01).
"""

from pydantic import BaseModel, ConfigDict, Field


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
