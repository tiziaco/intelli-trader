"""Handler-owned signal-store retrofit for ``StrategiesHandler`` (CTX-02 / D-02, plan 02-02).

Proves the purely-additive ctor seam: with ``environment='backtest', sql_engine=None``
(and no ``signal_store`` passed) the handler owns its signal-store init and yields the
SAME ``InMemorySignalStore`` concrete the backtest path built before (byte-exact oracle
preserved). An explicit ``signal_store=`` override still wins — the concrete exposed on
``.signal_store`` is the object ``compose_engine`` reads back onto the Engine holder in
plan 02-03.
"""

import queue
from unittest.mock import MagicMock

from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler


def test_backtest_slice_yields_in_memory_signal_store():
    handler = StrategiesHandler(
        queue.Queue(), MagicMock(), environment="backtest", sql_engine=None
    )
    assert isinstance(handler.signal_store, InMemorySignalStore)


def test_explicit_signal_store_override_wins():
    explicit = InMemorySignalStore()
    handler = StrategiesHandler(queue.Queue(), MagicMock(), signal_store=explicit)
    assert handler.signal_store is explicit
