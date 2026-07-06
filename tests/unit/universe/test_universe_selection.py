"""Lean ``UniverseSelectionModel`` selection seam (Plan 06-03 Task 1).

The D-20 growth target: a pure "what SHOULD the universe be?" selection seam
that answers ``select(asof) -> set[str]`` holding NO queue and NO feed (mirrors
``active_membership``'s "compose over injected data, return a set" shape, PATTERNS
"Lean UniverseSelectionModel"). It is explicitly NOT the deferred v2 ranked
production screener — just the lean poll seam (UNIV-01).

Behaviors asserted:
1. ``StaticUniverseSelectionModel`` conforms to the ``UniverseSelectionModel`` Protocol.
2. ``select(any_dt)`` returns the injected symbol set.
3. Purity-by-construction: the ctor takes ONLY symbols (no queue, no feed param).
4. ``set_symbols`` drives the desired set (the operator/test add/remove lever).
5. ``select`` returns a ``set`` (unordered, composes into the poll's D-06 filter).
"""

import inspect
from datetime import datetime, timezone

import pytest

from itrader.universe.membership import (
    StaticUniverseSelectionModel,
    UniverseSelectionModel,
)

pytestmark = pytest.mark.unit


_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_static_model_conforms_to_protocol() -> None:
    """The concrete static model is a ``UniverseSelectionModel`` (runtime-checkable)."""
    model = StaticUniverseSelectionModel(["BTC/USDC", "ETH/USDC"])
    assert isinstance(model, UniverseSelectionModel)


def test_static_select_returns_injected_set() -> None:
    """``select(any_dt)`` returns exactly the injected symbol set."""
    model = StaticUniverseSelectionModel(["BTC/USDC", "ETH/USDC"])
    assert model.select(_ASOF) == {"BTC/USDC", "ETH/USDC"}


def test_purity_by_construction_ctor_takes_only_symbols() -> None:
    """The model holds NO queue and NO feed — the ctor accepts only symbols.

    Assert purity by construction: the signature has exactly one non-self
    parameter (the symbols), so there is no seam for a queue/feed/connector.
    """
    params = list(inspect.signature(StaticUniverseSelectionModel).parameters)
    assert params == ["symbols"]
    # And the instance carries no queue/feed attributes.
    model = StaticUniverseSelectionModel(["BTC/USDC"])
    assert not hasattr(model, "global_queue")
    assert not hasattr(model, "feed")


def test_set_symbols_drives_the_desired_set() -> None:
    """``set_symbols`` re-drives ``select`` (the mid-run add/remove lever)."""
    model = StaticUniverseSelectionModel(["BTC/USDC"])
    assert model.select(_ASOF) == {"BTC/USDC"}

    model.set_symbols(["BTC/USDC", "ETH/USDC"])  # add
    assert model.select(_ASOF) == {"BTC/USDC", "ETH/USDC"}

    model.set_symbols(["ETH/USDC"])  # remove BTC
    assert model.select(_ASOF) == {"ETH/USDC"}


def test_select_returns_a_set_type() -> None:
    """``select`` returns a ``set`` (matching ``active_membership``'s contract)."""
    model = StaticUniverseSelectionModel(["BTC/USDC", "ETH/USDC"])
    result = model.select(_ASOF)
    assert isinstance(result, set)


def test_select_returns_a_defensive_copy() -> None:
    """Mutating the returned set must not corrupt the model's internal state."""
    model = StaticUniverseSelectionModel(["BTC/USDC"])
    result = model.select(_ASOF)
    result.add("MUTATED/USDC")
    assert model.select(_ASOF) == {"BTC/USDC"}
