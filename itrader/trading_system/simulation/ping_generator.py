from datetime import datetime
import numpy as np
import re

from itrader.trading_system.simulation.base import SimulationEngine
from ...instances.event import PingEvent



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

    def __init__(self, timezone='Europe/Paris'):
        self.timezone = timezone
        self.dates = None
    
    def __iter__(self):
        """
        Generate the daily timestamps in a ping event.

        Yields
        ------
        `PingEvent`
            Ping time simulation event to yield
        """
        for time in np.nditer(self.dates, flags=["refs_ok"]): # enumerate(self.dates):
            yield PingEvent(time.item(0))
    
    def set_dates(self, dates):
        self.dates = np.array(dates)
    

    """
    for index, time in enumerate(self.dates):
            yield PingEvent(time)
    """

    
