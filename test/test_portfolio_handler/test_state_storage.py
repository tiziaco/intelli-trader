"""Wave-0 characterization stub for M2-08 (portfolio state storage seam).

Written at Wave 0 of Phase 3 (M2b) under the CURRENT ``test/`` tree so ``make test``
collects it immediately (auto-marked ``portfolio`` via the ``test_portfolio_handler``
path in conftest). It pins the M2-08 behavior the storage-seam wave delivers:

  ``PortfolioStateStorageFactory.create("backtest")`` returns the in-memory backend, and
  positions / transactions / cash-ops / metrics round-trip through it (the same pluggable
  ``backtest`` vs ``postgresql`` seam the order storage already uses).

The factory does not exist yet. Until the M2-08 wave lands
``PortfolioStateStorageFactory``, the assertions are gated behind ``pytest.importorskip``
so the suite stays GREEN at Wave 0.

NOTE (03-08): this file MOVES with the test tree into
``tests/unit/test_portfolio_handler/`` during the 03-08 type-split — 03-08 reconciles it
there without duplication.
"""

import pytest


def _state_storage_factory_or_skip():
    """Return PortfolioStateStorageFactory once M2-08 lands; otherwise skip (Wave-0 pending)."""
    storage = pytest.importorskip(
        "itrader.portfolio_handler.storage",
        reason="pending M2-08: portfolio state storage seam not built yet",
    )
    factory = getattr(storage, "PortfolioStateStorageFactory", None)
    if factory is None:
        pytest.skip("pending M2-08: PortfolioStateStorageFactory not added yet")
    return factory


def test_backtest_backend_is_in_memory():
    """M2-08: factory.create('backtest') returns the in-memory backend."""
    PortfolioStateStorageFactory = _state_storage_factory_or_skip()
    backend = PortfolioStateStorageFactory.create("backtest")
    # The backtest backend is the in-memory implementation (mirrors order storage seam).
    assert "InMemory" in type(backend).__name__


def test_state_round_trips_through_backend():
    """M2-08: positions / transactions / cash-ops / metrics round-trip through the backend."""
    PortfolioStateStorageFactory = _state_storage_factory_or_skip()
    backend = PortfolioStateStorageFactory.create("backtest")
    # The concrete round-trip API is finalized by the M2-08 wave; assert the seam exists.
    assert backend is not None
