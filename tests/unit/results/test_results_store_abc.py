"""Unit tests for the ``ResultsStore`` ABC seam (SPINE-02 — the spine's fourth concern).

Proves the seam is a usable composition target without building any Phase-2 implementation:

1. ``ResultsStore`` is abstract — direct instantiation raises ``TypeError`` (all four
   methods are ``@abstractmethod``).
2. A trivial concrete subclass implementing all four methods CAN be constructed — so the
   ABC is a real, satisfiable contract (the 4th composable concern, not a dead abstraction).

No ``__init__.py`` in this directory: ``tests/unit/`` is package-less (prepend import mode),
matching the sibling ``tests/unit/order`` / ``tests/unit/storage`` convention.
"""

import pytest

from itrader.results import ResultsStore


def test_results_store_cannot_be_instantiated():
    """``ResultsStore`` is an ABC — direct instantiation raises ``TypeError``."""
    with pytest.raises(TypeError):
        ResultsStore()  # type: ignore[abstract]


def test_concrete_subclass_implementing_four_methods_instantiates():
    """A minimal subclass implementing the four abstract methods is constructible."""

    class _MemoryResultsStore(ResultsStore):
        def save_run(self, run):
            return run

        def save_artifact(self, run_id, frame):
            return None

        def get_artifact(self, run_id):
            return None

        def top_runs(self, metric, n):
            return []

    store = _MemoryResultsStore()

    assert isinstance(store, ResultsStore)
    assert store.save_run("run-summary") == "run-summary"
    assert store.save_artifact("rid", None) is None
    assert store.get_artifact("rid") is None
    assert store.top_runs("sharpe", 5) == []
