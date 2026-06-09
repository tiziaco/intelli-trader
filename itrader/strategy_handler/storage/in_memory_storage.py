"""In-memory SignalStore backend (Plan 05-03, SIG-02, D-07).

A single flat ``{signal_id: SignalRecord}`` dict is the SOLE container — keyed
on the native UUIDv7 ``SignalId`` (D-10). Queries are predicate filters over
the stored records, evaluated at query time (mirrors the
``InMemoryOrderStorage`` flat-dict + predicate-filter style).

4-space indentation (matches the ``order_handler/storage/`` siblings).
"""

import uuid
from typing import Dict, List

from itrader.core.ids import StrategyId
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage.base import SignalStore


class InMemorySignalStore(SignalStore):
    """In-memory implementation of ``SignalStore``.

    Flat-dict-only design: a single ``self._by_id: Dict[uuid.UUID,
    SignalRecord]`` keyed on the native ``SignalId`` (D-10). ``get_all`` returns
    the values in insertion order; ``by_strategy`` / ``by_ticker`` are
    list-comprehension predicate filters — no implicit cross-strategy bleed
    (T-05-05).
    """

    def __init__(self) -> None:
        """Initialize the in-memory store (the flat dict is the ONLY container)."""
        self._by_id: Dict[uuid.UUID, SignalRecord] = {}

    def add(self, record: SignalRecord) -> None:
        """Add a signal record (single flat-dict write keyed on its SignalId)."""
        self._by_id[record.signal_id] = record

    def get_all(self) -> List[SignalRecord]:
        """Return every stored record in insertion order."""
        return list(self._by_id.values())

    def by_strategy(self, strategy_id: StrategyId) -> List[SignalRecord]:
        """Return only the records produced by ``strategy_id`` (predicate filter)."""
        return [
            record for record in self._by_id.values()
            if record.strategy_id == strategy_id
        ]

    def by_ticker(self, ticker: str) -> List[SignalRecord]:
        """Return only the records targeting ``ticker`` (predicate filter)."""
        return [
            record for record in self._by_id.values()
            if record.ticker == ticker
        ]
