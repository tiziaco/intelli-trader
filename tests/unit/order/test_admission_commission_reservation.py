"""Non-zero-fee regression guard for the admission commission reservation.

Proves:
- **VENUE-08** — the commission the admission gate reserves is the fee model's
  real output, carried Decimal end-to-end, re-read on every call.
- **D-18** — the commission seam was DECOMPOSED by plan 11.1-10: ``core/``
  keeps a fee-model PROVIDER (``() -> FeeModel | None``) and the
  ``side="buy", order_type="market"`` admission convention moved into
  ``AdmissionManager._estimate_commission``. The value identity, the convention
  and the LATE BINDING of ``exchange.fee_model`` all had to survive that move,
  and this file is what proves they did — every expected value below is
  byte-identical to the pre-change one recorded in ``11.1-02-SUMMARY.md``.
- **RESEARCH Pitfall 2** — on this seam the value ``Decimal("0")`` is BOTH the
  correct golden result (the oracle run pins ``ZeroFeeModel``) AND the value a
  structurally-broken seam returns. A zero-fee test therefore cannot tell a
  working seam from a dead one, which is why "the oracle is still green" proves
  nothing here.

Every assertion in this file uses a NON-ZERO fee. That is the whole point: it is
the only evidence that can distinguish the two cases above.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.money import to_money
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.execution_handler.fee_model.base import FeeModel
from itrader.order_handler.admission.admission_manager import AdmissionManager
from itrader.order_handler.brackets.bracket_book import BracketBook
from itrader.order_handler.brackets.bracket_manager import BracketManager
from itrader.order_handler.order import Order
from itrader.order_handler.storage import OrderStorageFactory


class _StubLogger:
    """The logger double this directory already uses (test_leverage_plumbing)."""

    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...
    def info(self, *a, **k): ...
    def debug(self, *a, **k): ...


class _FakeFeeModel(FeeModel):
    """A fee model returning a fixed NON-ZERO fee and recording its call context.

    Subclasses the real ``FeeModel`` ABC so the double has the production
    ``calculate_fee`` shape rather than an invented one.
    """

    def __init__(self, fee: Decimal) -> None:
        self.fee = fee
        self.calls = []

    def calculate_fee(self, quantity, price, side="buy", order_type="market",
                      is_maker=None) -> Decimal:
        self.calls.append({"quantity": quantity, "price": price,
                           "side": side, "order_type": order_type})
        return self.fee


def _make_admission(fee_model_provider) -> AdmissionManager:
    """An AdmissionManager wired for commission estimation only.

    Copies the construction idiom already used in
    ``tests/unit/order/test_leverage_plumbing.py::_admission`` — the collaborators
    ``_estimate_commission`` does not touch are passed as ``None``. D-18: the
    sixth positional collaborator is the fee-model PROVIDER, not the old
    ``(quantity, price) -> Decimal`` estimator.
    """
    storage = OrderStorageFactory.create("test")
    logger = _StubLogger()
    brackets = BracketBook()
    bracket_manager = BracketManager(storage, logger, brackets)
    return AdmissionManager(
        storage, logger,
        None,  # order_validator
        None,  # sizing_resolver
        None,  # portfolio_handler
        fee_model_provider,
        brackets, bracket_manager,
    )


def _make_order() -> Order:
    """A PENDING order — ``_estimate_commission`` reads only quantity and price."""
    return Order(
        time=datetime(2024, 1, 2, 12, 0, 0),
        type=OrderType.MARKET,
        status=OrderStatus.PENDING,
        ticker="BTCUSDT",
        action=Side.BUY,
        price=40000.0,
        quantity=0.5,
        exchange="paper",
        strategy_id=1,
        portfolio_id=1,
    )


def _exchange_with_fee_model(fee_model: FeeModel) -> SimulatedExchange:
    """A REAL SimulatedExchange carrying ``fee_model``.

    Kept REAL rather than duck-typed so the swap test exercises the actual
    attribute the production provider dereferences. (Pre-D-18 this was mandatory
    because ``FeeModelCommissionEstimator`` guarded on
    ``isinstance(self._exchange, SimulatedExchange)`` and silently returned zero
    for anything else; that guard is gone, replaced by the explicit
    "provider returns None" contract, but a real exchange remains the honest
    subject.)
    """
    exchange = SimulatedExchange(Queue())
    exchange.fee_model = fee_model
    return exchange


def test_non_zero_commission_reaches_the_reservation():
    """A non-zero estimate arrives at the reservation UNCHANGED.

    The value-identity anchor: ``Decimal("7.5")`` is byte-identical to the value
    this test asserted BEFORE the D-18 decomposition (recorded in
    ``11.1-02-SUMMARY.md``). If the seam is broken the result collapses to zero
    and this assertion goes red.
    """
    fee_model = _FakeFeeModel(Decimal("7.5"))
    manager = _make_admission(lambda: fee_model)

    assert manager._estimate_commission(_make_order()) == Decimal("7.5")


def test_absent_estimator_degrades_to_zero():
    """With no provider injected the reservation degrades to exactly zero.

    The guard-clause early exit: the reservation amount becomes plain
    price x quantity, which is today's funds-check math.
    """
    manager = _make_admission(None)

    assert manager._estimate_commission(_make_order()) == Decimal("0")


def test_float_returning_estimator_is_normalised_to_decimal():
    """VENUE-08 precision edge: a float estimate crosses the money boundary safely.

    WR-04 / Decimal-end-to-end. ``10.1`` has no exact binary representation, so a
    direct ``Decimal(float)`` would import the repr artifact (10.0999999...) into
    the reservation amount — or raise a Decimal+float TypeError in the reserve
    path. The fee-model return must go through ``to_money``'s string entry.
    """
    manager = _make_admission(lambda: _FakeFeeModel(10.1))

    result = manager._estimate_commission(_make_order())

    assert isinstance(result, Decimal)
    assert result == to_money(10.1)
    # The string-path value, not the binary-float-repr one.
    assert result == Decimal("10.1")


def test_admission_convention_is_buy_market():
    """The admission estimate is taken at ``side="buy", order_type="market"`` (D-04).

    Plan 11.1-10 MOVED this convention into ``AdmissionManager``, so this test's
    import and subject changed with it — the ASSERTED CONVENTION did not.
    """
    fee_model = _FakeFeeModel(Decimal("3.25"))
    exchange = _exchange_with_fee_model(fee_model)
    manager = _make_admission(lambda: getattr(exchange, "fee_model", None))

    result = manager._estimate_commission(_make_order())

    # A non-zero result also proves the provider handed over a real fee model
    # rather than silently short-circuiting to zero.
    assert result == Decimal("3.25")
    assert len(fee_model.calls) == 1
    assert fee_model.calls[0]["side"] == "buy"
    assert fee_model.calls[0]["order_type"] == "market"


def test_fee_model_swap_is_observed_on_the_next_call():
    """LATE BINDING (D-18): the provider re-reads ``exchange.fee_model`` per call.

    ``SimulatedExchange.update_config`` REPLACES the fee-model object
    (``exchanges/simulated.py:775``, right after the atomic config swap at
    ``:770``), so a provider that captured it at construction would keep quoting
    the stale rate forever. Two derefs of an UNCHANGED model must agree (VENUE-08
    idempotency); a deref after a swap must see the swap (VENUE-08 concurrency).
    """
    first = _FakeFeeModel(Decimal("1.25"))
    exchange = _exchange_with_fee_model(first)
    manager = _make_admission(lambda: getattr(exchange, "fee_model", None))

    # Idempotency: the same model, called twice, yields the same value.
    assert manager._estimate_commission(_make_order()) == Decimal("1.25")
    assert manager._estimate_commission(_make_order()) == Decimal("1.25")

    # Hot-swap the fee model on the exchange, as update_config does at :775.
    second = _FakeFeeModel(Decimal("3.75"))
    exchange.fee_model = second

    assert manager._estimate_commission(_make_order()) == Decimal("3.75")
