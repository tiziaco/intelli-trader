"""Structural + late-binding conformance tests for ``FeeModelProvider`` (D-18).

Pins the WIRING half of the decomposed commission seam: a ``runtime_checkable``
Protocol with a ``() -> FeeModel | None`` ``__call__``, mirroring
``PortfolioReadModel`` (zero ``itrader`` deps AT RUNTIME — the ``FeeModel``
annotation is ``TYPE_CHECKING``-guarded).

Proves:

* **Structural conformance** — an object whose class defines the right
  ``__call__`` satisfies ``isinstance`` against the runtime_checkable Protocol,
  and one that does not is rejected (narrowness). A plain ``lambda`` conforms,
  which is what the wiring seam in ``compose.py`` actually injects. (This
  subsumes the pre-D-18 ``test_adapter_satisfies_protocol``: the adapter class it
  referenced — ``compose.FeeModelCommissionEstimator`` — is DELETED by D-18, so
  the assertion is re-pointed at the lambda provider that replaced it rather than
  dropped.)
* **The explicit no-fee-model contract** — a provider may return ``None``, which
  the caller (``AdmissionManager._estimate_commission``) turns into a
  ``Decimal("0")`` estimate. This replaces the deleted adapter's
  ``isinstance(exchange, SimulatedExchange)`` guard.
* **LATE BINDING (D-18, the load-bearing property)** — the SINGLE oracle-dark
  correctness check on this seam. The golden run pins fees at 0 (``ZeroFeeModel``),
  so the byte-exact gate can NEVER catch a stale-fee regression. A provider must
  read ``exchange.fee_model`` INSIDE ``__call__``, never capture it at
  construction, because ``SimulatedExchange.update_config`` REPLACES the object
  (``exchanges/simulated.py:775``, right after the atomic config swap at ``:770``).
  Proven positively by ``test_late_binding_provider_reads_the_current_fee_model``
  (renamed from ``test_fee_model_commission_estimator_late_binding_after_fee_swap``
  when D-18 deleted the adapter it named — the assertion is strictly stronger, it
  now pins model IDENTITY rather than "> 0") and negatively by the explicit
  capturing counter-example beside it.
"""

from decimal import Decimal
from queue import Queue
from typing import Optional

import pytest

from itrader.config import FeeModelType
from itrader.core.commission_estimator import FeeModelProvider
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.execution_handler.fee_model import FeeModel, PercentFeeModel

pytestmark = pytest.mark.unit


class _ConformingProvider:
    """A minimal class whose ``__call__`` matches the Protocol signature."""

    def __init__(self, fee_model: Optional[FeeModel]) -> None:
        self._fee_model = fee_model

    def __call__(self) -> Optional[FeeModel]:
        return self._fee_model


class _NonConformingProvider:
    """A class missing ``__call__`` — structurally NOT a FeeModelProvider."""

    def fee_model(self) -> Optional[FeeModel]:
        return None


def _make_default_exchange() -> SimulatedExchange:
    """A SimulatedExchange on the default preset — its fee_model is ZeroFeeModel."""
    return SimulatedExchange(Queue())


def test_conforming_class_satisfies_protocol_isinstance():
    """A class defining ``__call__() -> FeeModel | None`` passes isinstance."""
    provider = _ConformingProvider(PercentFeeModel(fee_rate=Decimal("0.001")))
    assert isinstance(provider, FeeModelProvider)


def test_conforming_provider_returns_the_fee_model_it_provides():
    """The conforming provider is callable with the documented signature."""
    fee_model = PercentFeeModel(fee_rate=Decimal("0.001"))
    provider = _ConformingProvider(fee_model)
    assert provider() is fee_model


def test_non_conforming_class_fails_protocol_isinstance():
    """An object without ``__call__`` is NOT a FeeModelProvider (narrowness)."""
    assert not isinstance(_NonConformingProvider(), FeeModelProvider)


def test_protocol_is_runtime_checkable():
    """isinstance against the Protocol must not raise — it is runtime_checkable."""
    # If FeeModelProvider were not @runtime_checkable, this isinstance call
    # would raise TypeError rather than returning a bool.
    result = isinstance(_ConformingProvider(None), FeeModelProvider)
    assert result is True


def test_lambda_provider_satisfies_protocol():
    """The wiring shape ``compose_engine`` injects — a lambda — conforms.

    Re-points the pre-D-18 ``test_adapter_satisfies_protocol``: the
    ``FeeModelCommissionEstimator`` class it asserted against is deleted, and the
    provider that replaced it is a closure over the exchange.
    """
    exchange = _make_default_exchange()
    provider = lambda: getattr(exchange, "fee_model", None)  # noqa: E731
    assert isinstance(provider, FeeModelProvider)


def test_provider_may_return_none_for_a_venue_with_no_fee_model():
    """The explicit "this venue exposes no fee model" contract (D-18).

    Replaces the deleted adapter's ``isinstance(exchange, SimulatedExchange)``
    guard. A venue object carrying no ``fee_model`` attribute — the live OKX arm
    today — yields ``None``, which the caller degrades to ``Decimal("0")``.
    """

    class _VenueWithoutFeeModel:
        pass

    venue = _VenueWithoutFeeModel()
    provider = lambda: getattr(venue, "fee_model", None)  # noqa: E731

    assert isinstance(provider, FeeModelProvider)
    assert provider() is None


def test_late_binding_provider_reads_the_current_fee_model():
    """D-18 LATE BINDING: the provider re-reads ``exchange.fee_model`` per call.

    (Formerly ``test_fee_model_commission_estimator_late_binding_after_fee_swap``
    — renamed when D-18 deleted the adapter that name referred to; the property
    under test and its history are unchanged, and the assertion is tightened from
    "the estimate is > 0" to fee-model OBJECT IDENTITY.)

    ``update_config`` REPLACES ``self.fee_model`` after its atomic config swap
    (``simulated.py:775``), so a provider that captured the model at construction
    would keep returning the stale ``ZeroFeeModel`` forever — silently, at a rate
    the exchange no longer charges.
    """
    exchange = _make_default_exchange()
    provider = lambda: getattr(exchange, "fee_model", None)  # noqa: E731

    before = provider()
    # Idempotency: two derefs with NO config change agree (VENUE-08).
    assert provider() is before

    # Hot-swap the fee model through the REAL production mechanism (the canonical
    # dict/model_validate update_config contract), which re-inits self.fee_model.
    exchange.update_config(
        {"fee_model": {"model_type": FeeModelType.PERCENT.value, "fee_rate": "0.001"}})

    after = provider()
    assert after is not before
    assert after is exchange.fee_model
    assert isinstance(after, PercentFeeModel)


def test_a_provider_that_captures_its_fee_model_is_not_late_bound():
    """COUNTER-EXAMPLE — do NOT build providers this way (D-18 prohibition).

    An explicit negative control for the guard above: a provider that CAPTURES
    the fee model at construction keeps returning the pre-swap object after
    ``update_config`` replaced it. This is the silent-corruption shape the
    late-binding test exists to catch, and it is asserted here so the failure
    mode is visible rather than merely described in a docstring.
    """
    exchange = _make_default_exchange()
    original = exchange.fee_model
    # THE UNSUPPORTED PATTERN: the model is bound once, at construction.
    capturing_provider = _ConformingProvider(exchange.fee_model)
    late_bound_provider = lambda: getattr(exchange, "fee_model", None)  # noqa: E731

    exchange.update_config(
        {"fee_model": {"model_type": FeeModelType.PERCENT.value, "fee_rate": "0.001"}})

    # The capturing provider is STALE — it still hands out the retired model.
    assert capturing_provider() is original
    # The late-bound provider tracks the exchange. The divergence IS the defect.
    assert late_bound_provider() is exchange.fee_model
    assert capturing_provider() is not late_bound_provider()
