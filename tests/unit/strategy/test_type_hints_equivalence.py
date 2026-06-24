"""Equivalence drift-lock for the PERF-04 memoized type-hint resolution (D-05/D-07).

PERF-04 (Phase 4) replaced the per-signal ``get_type_hints(type(self))`` re-walk in
``Strategy.to_dict`` (hot) and ``Strategy._apply_params`` (cold) with a single
module-level ``@functools.cache def _declared_hints(cls)`` so the constant-per-class
annotations resolve exactly once per concrete subclass (``itrader/strategy_handler/base.py``).

This test is the dedicated unit-level drift lock (D-07): the "oracle" here is the
UN-cached ``get_type_hints(cls)`` direct call. It asserts (1) ``_declared_hints(cls)``
equals ``get_type_hints(cls)`` with the SAME keys AND order (``list(a) == list(b)``) —
the byte-exact-key-order property to_dict relies on; (2) two calls return the SAME object
(``is``) so memoization actually fires; (3) two distinct subclasses resolve to different
dicts (no cross-class cache bleed, since ``type(self)`` keys the cache on the concrete class).

The byte-exact SMA_MACD oracle + the determinism double-run are the run-path drift locks;
the ``to_dict`` snapshot regression in ``test_strategy.py`` locks the full serialized
surface. This file locks the resolution itself. No hot-path runtime guard re-resolving the
hints is added (D-05) — re-paying that per-signal cost is exactly what the phase removes.
"""

from typing import get_type_hints

import pytest

from itrader.strategy_handler.base import Strategy, _declared_hints
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy

pytestmark = pytest.mark.unit


def test_declared_hints_equals_get_type_hints_same_keys_and_order():
    """D-07: _declared_hints(cls) == get_type_hints(cls), same keys AND order.

    to_dict iterates the resolved hints to build the snapshot, so a key-ORDER
    drift between the memoized helper and the direct call would silently re-order
    the snapshot in this byte-exact phase. Assert value-equality AND list-order
    equality against the un-cached oracle.
    """
    oracle = get_type_hints(SMAMACDStrategy)
    memoized = _declared_hints(SMAMACDStrategy)

    assert memoized == oracle  # same keys + same resolved types
    assert list(memoized) == list(oracle)  # same ORDER (snapshot key order)


def test_declared_hints_is_memoized_same_object():
    """D-05: repeated calls return the SAME object — memoization fires.

    The whole PERF-04 win is collapsing the per-signal MRO walk to a dict lookup;
    proving identity (``is``) proves the @cache is actually serving the cached
    dict rather than re-resolving.
    """
    first = _declared_hints(SMAMACDStrategy)
    second = _declared_hints(SMAMACDStrategy)

    assert first is second


def test_declared_hints_keys_on_concrete_subclass_no_cross_class_bleed():
    """D-05: keying on type(self) yields distinct dicts per concrete subclass.

    The cache is keyed on the concrete class object, so a second strategy
    subclass declaring extra annotated knobs must resolve to its OWN dict (the
    base + subclass MRO merge), never the first class's cached dict.
    """

    class _OtherStrategy(Strategy):
        # An extra declared (annotated) knob the SMA strategy does not own.
        extra_knob: int = 7

        def generate_signal(self, ticker: str):
            return None

    sma_hints = _declared_hints(SMAMACDStrategy)
    other_hints = _declared_hints(_OtherStrategy)

    # Distinct cached objects (no cross-class bleed).
    assert sma_hints is not other_hints
    # The subclass-only annotation appears only in its own resolution.
    assert "extra_knob" in other_hints
    assert "extra_knob" not in sma_hints
    # Each matches its own un-cached oracle.
    assert other_hints == get_type_hints(_OtherStrategy)
    assert list(other_hints) == list(get_type_hints(_OtherStrategy))
