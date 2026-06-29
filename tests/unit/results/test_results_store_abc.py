"""Unit tests for the ``ResultsStore`` ABC seam (SPINE-02 — the spine's fourth concern).

Proves the seam is a usable composition target without building any Phase-2 implementation:

1. ``ResultsStore`` is abstract — direct instantiation raises ``TypeError`` (all five
   methods are ``@abstractmethod``).
2. A trivial concrete subclass implementing all five widened methods CAN be constructed —
   so the ABC is a real, satisfiable contract (the 4th composable concern, not a dead
   abstraction).

No ``__init__.py`` in this directory: ``tests/unit/`` is package-less (prepend import mode),
matching the sibling ``tests/unit/order`` / ``tests/unit/storage`` convention.
"""

import uuid

import pytest

from itrader.results import ResultsStore

_FIXED_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_results_store_cannot_be_instantiated():
    """``ResultsStore`` is an ABC — direct instantiation raises ``TypeError``."""
    with pytest.raises(TypeError):
        ResultsStore()  # type: ignore[abstract]


def test_concrete_subclass_implementing_five_methods_instantiates():
    """A minimal subclass implementing the five widened abstract methods is constructible."""

    class _MemoryResultsStore(ResultsStore):
        def save_run(self, run):
            return _FIXED_RUN_ID

        def save_artifact(self, run_id, portfolio_id, artifact_type, frame):
            return None

        def get_artifact(self, run_id):
            return {}

        def top_runs(self, metric, n):
            return []

        def top_portfolios(self, metric, n):
            return []

    store = _MemoryResultsStore()

    assert isinstance(store, ResultsStore)
    assert store.save_run("run-summary") == _FIXED_RUN_ID
    assert store.save_artifact(_FIXED_RUN_ID, None, "equity_curve", None) is None
    assert store.get_artifact(_FIXED_RUN_ID) == {}
    assert store.top_runs("sharpe", 5) == []
    assert store.top_portfolios("sharpe", 5) == []
