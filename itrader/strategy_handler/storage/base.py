"""SignalStore abstract base class (Plan 05-03, SIG-02, D-07).

Mirrors the ``order_handler`` storage seam: a narrow ABC that concrete backends
implement. v1.1 ships the in-memory backend only; a persistent backend is a
later-milestone concern (the factory rejects ``'live'`` loudly until then).

4-space indentation (matches the ``order_handler/storage/`` siblings).
"""

from abc import ABC, abstractmethod
from typing import List

from itrader.core.ids import StrategyId
from itrader.strategy_handler.signal_record import SignalRecord


class SignalStore(ABC):
    """Abstract base class for signal-record storage backends (D-07).

    Provides a unified, queryable interface over captured ``SignalRecord``s.
    The store is a sink/read-model: the handler writes records during the run
    and the composition root reads them post-run. It is NOT a cross-domain
    handler call (the queue-only contract is preserved, D-12).
    """

    @abstractmethod
    def add(self, record: SignalRecord) -> None:
        """Add a captured signal record to the store.

        Parameters
        ----------
        record : SignalRecord
            The record to persist (one per non-None intent, D-09).
        """
        pass

    @abstractmethod
    def get_all(self) -> List[SignalRecord]:
        """Return all stored signal records.

        Returns
        -------
        List[SignalRecord]
            Every record captured so far, in insertion order.
        """
        pass

    @abstractmethod
    def by_strategy(self, strategy_id: StrategyId) -> List[SignalRecord]:
        """Return the records produced by a single strategy.

        Parameters
        ----------
        strategy_id : StrategyId
            The strategy to filter by.

        Returns
        -------
        List[SignalRecord]
            Only the records whose ``strategy_id`` matches — no cross-strategy
            bleed (T-05-05).
        """
        pass

    @abstractmethod
    def by_ticker(self, ticker: str) -> List[SignalRecord]:
        """Return the records targeting a single ticker.

        Parameters
        ----------
        ticker : str
            The instrument symbol to filter by.

        Returns
        -------
        List[SignalRecord]
            Only the records whose ``ticker`` matches.
        """
        pass
