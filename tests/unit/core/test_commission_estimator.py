"""Structural conformance tests for the CommissionEstimator Protocol (D-15).

Pins the read-model-seam shape promoted from the inline ``_estimate_commission``
closure in ``backtest_trading_system.py``: a ``runtime_checkable`` Protocol with
the primitive ``(Decimal, Decimal) -> Decimal`` ``__call__`` signature, mirroring
``PortfolioReadModel`` (zero ``itrader`` deps).

Scope (Wave 1): STRUCTURAL conformance only — an object whose class defines the
right ``__call__`` satisfies ``isinstance`` against the runtime_checkable Protocol.

The D-15 LATE-BINDING correctness test (construct ``FeeModelCommissionEstimator``,
swap the exchange fee model, assert the new non-zero estimate is reflected) is
APPENDED to this file in Wave 2 (04-02 Task 2), once the adapter exists. These
tests are written as standalone functions so that append does not collide.
"""

from decimal import Decimal

import pytest

from itrader.core.commission_estimator import CommissionEstimator

pytestmark = pytest.mark.unit


class _ConformingEstimator:
    """A minimal class whose ``__call__`` matches the Protocol signature."""

    def __call__(self, quantity: Decimal, price: Decimal) -> Decimal:
        return quantity * price


class _NonConformingEstimator:
    """A class missing ``__call__`` — structurally NOT a CommissionEstimator."""

    def estimate(self, quantity: Decimal, price: Decimal) -> Decimal:
        return Decimal("0")


def test_conforming_class_satisfies_protocol_isinstance():
    """A class defining ``__call__(quantity, price) -> Decimal`` passes isinstance."""
    estimator = _ConformingEstimator()
    assert isinstance(estimator, CommissionEstimator)


def test_conforming_estimator_returns_expected_value():
    """The conforming estimator is callable with the documented signature."""
    estimator = _ConformingEstimator()
    assert estimator(Decimal("2"), Decimal("100")) == Decimal("200")


def test_non_conforming_class_fails_protocol_isinstance():
    """An object without ``__call__`` is NOT a CommissionEstimator (narrowness)."""
    assert not isinstance(_NonConformingEstimator(), CommissionEstimator)


def test_protocol_is_runtime_checkable():
    """isinstance against the Protocol must not raise — it is runtime_checkable."""
    # If CommissionEstimator were not @runtime_checkable, this isinstance call
    # would raise TypeError rather than returning a bool.
    result = isinstance(_ConformingEstimator(), CommissionEstimator)
    assert result is True
