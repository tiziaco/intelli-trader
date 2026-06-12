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


# ---------------------------------------------------------------------------
# Wave 2 (04-02 Task 2): D-15 LATE-BINDING correctness test.
#
# This is the SINGLE oracle-dark correctness check for D-15 — the golden run
# pins fees at 0 (ZeroFeeModel), so the byte-exact gate can NEVER catch a
# stale-fee regression. The FeeModelCommissionEstimator adapter must read
# `exchange.fee_model` inside __call__ (late binding), NEVER capture it at
# __init__. We prove this by hot-swapping the fee model AFTER constructing the
# adapter and asserting the estimate reflects the NEW model.
# ---------------------------------------------------------------------------

from queue import Queue

from itrader.trading_system.compose import FeeModelCommissionEstimator
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.config import FeeModelType


def _make_default_exchange() -> SimulatedExchange:
    """A SimulatedExchange on the default preset — its fee_model is ZeroFeeModel."""
    return SimulatedExchange(Queue())


def test_fee_model_commission_estimator_zero_before_swap():
    """On the default ZeroFeeModel the adapter estimates exactly 0."""
    exchange = _make_default_exchange()
    adapter = FeeModelCommissionEstimator(exchange)
    assert adapter(Decimal("1"), Decimal("1000")) == Decimal("0")


def test_fee_model_commission_estimator_late_binding_after_fee_swap():
    """D-15 LATE BINDING: after a fee-model hot-swap the adapter returns the NEW
    model's non-zero estimate — proving it reads exchange.fee_model in __call__
    and never captured the original ZeroFeeModel at __init__."""
    exchange = _make_default_exchange()
    adapter = FeeModelCommissionEstimator(exchange)
    # Before the swap: ZeroFeeModel → 0.
    assert adapter(Decimal("1"), Decimal("1000")) == Decimal("0")
    # Hot-swap to a percent fee model (re-inits self.fee_model on the exchange).
    # Drives the canonical dict/model_validate update_config contract (Wave 3,
    # 04-03). The D-15 LATE-BINDING property under test is independent of how the
    # swap is expressed.
    exchange.update_config(
        {"fee_model": {"model_type": FeeModelType.PERCENT.value, "fee_rate": "0.001"}})
    # After the swap: the NEW PercentFeeModel applies — a non-zero estimate.
    assert adapter(Decimal("1"), Decimal("1000")) > Decimal("0")


def test_fee_model_commission_estimator_conforms_to_protocol():
    """The adapter structurally satisfies the runtime_checkable CommissionEstimator."""
    exchange = _make_default_exchange()
    adapter = FeeModelCommissionEstimator(exchange)
    assert isinstance(adapter, CommissionEstimator)
