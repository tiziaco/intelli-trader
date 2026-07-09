"""Handler-owned storage retrofit for ``OrderHandler`` (CTX-02 / D-02, plan 02-02).

Proves the purely-additive ctor seam: with ``environment='backtest', sql_engine=None``
the handler owns its storage init and yields the SAME ``InMemoryOrderStorage`` concrete
the backtest path constructed before (byte-exact oracle preserved). The explicit
``order_storage=`` override still wins, and the instance exposed on ``.storage`` is the
exact object forwarded to ``OrderManager`` — the wiring seam ``compose_engine`` reads
back for ``portfolio_handler.set_order_storage(...)`` in plan 02-03 (D-18 preserved:
the manager still owns storage for all read paths; ``.storage`` is a wiring read, not a
second read path).
"""

import queue
from unittest.mock import MagicMock

from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage


def test_backtest_slice_yields_in_memory_storage():
    handler = OrderHandler(
        queue.Queue(), MagicMock(), environment="backtest", sql_engine=None
    )
    assert isinstance(handler.storage, InMemoryOrderStorage)


def test_explicit_order_storage_override_wins():
    explicit = InMemoryOrderStorage()
    handler = OrderHandler(queue.Queue(), MagicMock(), order_storage=explicit)
    assert handler.storage is explicit


def test_storage_is_the_instance_forwarded_to_order_manager():
    # Wiring-seam identity: `.storage` MUST be the exact object the manager owns,
    # because compose_engine (plan 02-03) reads `.storage` back to wire
    # portfolio_handler.set_order_storage(...). Prove it with an explicit sentinel
    # so the assertion holds regardless of the factory's construction path.
    explicit = InMemoryOrderStorage()
    handler = OrderHandler(queue.Queue(), MagicMock(), order_storage=explicit)
    assert handler.storage is handler.order_manager.order_storage
    assert handler.order_manager.order_storage is explicit
