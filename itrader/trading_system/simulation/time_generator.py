from datetime import datetime
from typing import Any, Iterator, Optional, cast
import numpy as np
import re

from itrader.trading_system.simulation.base import SimulationEngine
from ...events_handler.event import PingEvent



class PingGenerator(SimulationEngine):
    """
    A SimulationEngine subclass that generates events on a 
    frequency defined with the time frame variable

    It produces a ping event.

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

    def __iter__(self) -> Iterator[PingEvent]:
        """
        Generate the daily timestamps in a ping event.

        Yields
        ------
        `PingEvent`
            Ping time simulation event to yield
        """
        if self.dates is None:
            return
        for time in np.nditer(self.dates, flags=["refs_ok"]): # enumerate(self.dates):
            # nditer yields 0-d array scalars; .item(0) extracts the python value.
            yield PingEvent(cast(Any, time).item(0))

    def set_dates(self, dates: Any) -> None:
        self.dates = np.array(dates)
    

    """
    for index, time in enumerate(self.dates):
            yield PingEvent(time)
    """

    
