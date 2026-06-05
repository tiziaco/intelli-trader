from datetime import datetime
from typing import Any, Iterator, Optional, cast
import numpy as np
import re

from itrader.trading_system.simulation.base import SimulationEngine
from ...events_handler.events import TimeEvent


class TimeGenerator(SimulationEngine):
    """
    A SimulationEngine subclass that generates events on a
    frequency defined with the time frame variable.

    It yields a ``TimeEvent`` per simulation timestamp — "the clock
    advanced to T" — pairing with the ``itrader.core.clock.Clock``
    family (D-08).

    Parameters
    ----------
    start_date : `pd.Timestamp`
        The starting day of the simulation.
    end_date : `pd.Timestamp`
        The ending day of the simulation.
    timeframe : `str`
        Range at which to generate events
    """

    def __init__(self, timezone: str = 'Europe/Paris') -> None:
        self.timezone = timezone
        self.dates: Optional[np.ndarray[Any, Any]] = None

    def __iter__(self) -> Iterator[TimeEvent]:
        """
        Generate the daily timestamps in a time event.

        Yields
        ------
        `TimeEvent`
            Simulation-clock event ("the clock advanced to T") to yield
        """
        if self.dates is None:
            return
        for time in np.nditer(self.dates, flags=["refs_ok"]):
            # nditer yields 0-d array scalars; .item(0) extracts the python value.
            yield TimeEvent(time=cast(Any, time).item(0))

    def set_dates(self, dates: Any) -> None:
        self.dates = np.array(dates)
