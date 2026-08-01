"""Non-zero-fee regression guard for the admission commission reservation.

Proves:
- **VENUE-08** — the commission the admission gate reserves is the fee model's
  real output, carried Decimal end-to-end, re-read on every call.
- **D-18** — the commission seam was DECOMPOSED by plan 11.1-10: ``core/``
  keeps a fee-model PROVIDER (``(venue, account_id) -> FeeModel | None`` since
  D-39/WR-01; ``() -> FeeModel | None`` before it) and the
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
from itrader.order_handler.storage import build_order_storage
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID


class _StubLogger:
    """The logger double this directory already uses (test_leverage_plumbing)."""

    def __init__(self) -> None:
        self.warnings = []

    def warning(self, *a, **k):
        self.warnings.append((a, k))

    def error(self, *a, **k): ...
    def info(self, *a, **k): ...
    def debug(self, *a, **k): ...


class _StubReadModel:
    """A ``PortfolioReadModel`` double exposing ONLY ``account_for``.

    ``_estimate_commission`` reads exactly one member of the read model — the
    ACCOUNT half of the ``(venue, account_id)`` lookup key — so the double
    carries exactly that member. ``account_for`` is ``Optional[str]`` in the
    Protocol (``portfolio_read_model.py:210``) and returns ``None`` for every
    backtest portfolio, so ``None`` is a first-class value here, not an error
    case invented for the test.
    """

    def __init__(self, account_id):
        self._account_id = account_id
        self.account_calls = []

    def account_for(self, portfolio_id):
        self.account_calls.append(portfolio_id)
        return self._account_id


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


def _make_admission(fee_model_provider, portfolio_handler=None) -> AdmissionManager:
    """An AdmissionManager wired for commission estimation only.

    Copies the construction idiom already used in
    ``tests/unit/order/test_leverage_plumbing.py::_admission`` — the collaborators
    ``_estimate_commission`` does not touch are passed as ``None``. D-18: the
    sixth positional collaborator is the fee-model PROVIDER, not the old
    ``(quantity, price) -> Decimal`` estimator.

    ``portfolio_handler`` defaults to ``None`` (the shape every pre-existing case
    in this file uses); the WR-01 cases below pass a ``_StubReadModel`` because
    the ACCOUNT half of the lookup key is read off it.
    """
    storage = build_order_storage("test")
    logger = _StubLogger()
    brackets = BracketBook()
    bracket_manager = BracketManager(storage, logger, brackets)
    return AdmissionManager(
        storage, logger,
        None,  # order_validator
        None,  # sizing_resolver
        portfolio_handler,
        fee_model_provider,
        brackets, bracket_manager,
    )


def _make_order(exchange: str = "paper") -> Order:
    """A PENDING order — ``_estimate_commission`` reads quantity, price and venue.

    ``exchange`` is the VENUE half of the ``(venue, account_id)`` lookup key
    (11.1-REVIEW WR-01). It defaults to the paper compute venue, so every
    pre-existing case in this file is unchanged.
    """
    return Order(
        time=datetime(2024, 1, 2, 12, 0, 0),
        type=OrderType.MARKET,
        status=OrderStatus.PENDING,
        ticker="BTCUSDT",
        action=Side.BUY,
        price=40000.0,
        quantity=0.5,
        exchange=exchange,
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
    manager = _make_admission(lambda venue, account_id: fee_model)

    assert manager._estimate_commission(_make_order()) == Decimal("7.5")


def test_absent_estimator_degrades_to_zero():
    """With no provider injected the reservation degrades to exactly zero.

    The FIRST guard-clause early exit (``fee_model_provider is None``): the
    reservation amount becomes plain price x quantity, which is today's
    funds-check math.

    D-18 gave this seam TWO distinct zero paths and they are asserted
    SEPARATELY, here and in the test below — conflating them into one test would
    let either path die undetected behind the other, and on this seam
    ``Decimal("0")`` is also the correct golden value (RESEARCH Pitfall 2).
    """
    manager = _make_admission(None)

    assert manager._estimate_commission(_make_order()) == Decimal("0")


def test_provider_returning_none_degrades_to_zero():
    """A venue that exposes NO fee model degrades to exactly zero (D-18).

    The SECOND guard-clause early exit (``fee_model is None``): the explicit
    "this venue exposes no fee model" contract that replaced the deleted
    adapter's ``isinstance(exchange, SimulatedExchange)`` guard. This is the path
    the LIVE OKX exchange takes today — a KNOWN, deliberately-deferred
    under-reservation (T-11.1-48) that D-18 makes visible without fixing.
    """
    manager = _make_admission(lambda venue, account_id: None)

    assert manager._estimate_commission(_make_order()) == Decimal("0")


def test_float_returning_estimator_is_normalised_to_decimal():
    """VENUE-08 precision edge: a float estimate crosses the money boundary safely.

    WR-04 / Decimal-end-to-end. ``10.1`` has no exact binary representation, so a
    direct ``Decimal(float)`` would import the repr artifact (10.0999999...) into
    the reservation amount — or raise a Decimal+float TypeError in the reserve
    path. The fee-model return must go through ``to_money``'s string entry.
    """
    manager = _make_admission(lambda venue, account_id: _FakeFeeModel(10.1))

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
    manager = _make_admission(
        lambda venue, account_id: getattr(exchange, "fee_model", None))

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
    manager = _make_admission(
        lambda venue, account_id: getattr(exchange, "fee_model", None))

    # Idempotency: the same model, called twice, yields the same value.
    assert manager._estimate_commission(_make_order()) == Decimal("1.25")
    assert manager._estimate_commission(_make_order()) == Decimal("1.25")

    # Hot-swap the fee model on the exchange, as update_config does at :775.
    second = _FakeFeeModel(Decimal("3.75"))
    exchange.fee_model = second

    assert manager._estimate_commission(_make_order()) == Decimal("3.75")


def test_provider_is_dereferenced_once_per_estimate():
    """VENUE-08 idempotency: exactly ONE provider deref per estimate (D-18).

    Proves the result is not memoized on ``self`` between orders. A cached fee
    model would show a deref count that stops rising while estimates keep coming
    — precisely the stale-rate failure the late-binding guard above exists to
    prevent, seen from the other side (call COUNT rather than call VALUE).
    """
    fee_model = _FakeFeeModel(Decimal("2.5"))
    calls = []

    def counting_provider(venue, account_id):
        calls.append(1)
        return fee_model

    manager = _make_admission(counting_provider)

    assert manager._estimate_commission(_make_order()) == Decimal("2.5")
    assert len(calls) == 1

    assert manager._estimate_commission(_make_order()) == Decimal("2.5")
    assert len(calls) == 2

    assert manager._estimate_commission(_make_order()) == Decimal("2.5")
    assert len(calls) == 3
    # And nothing was stashed on the manager between orders.
    assert not hasattr(manager, "_fee_model")


# ---------------------------------------------------------------------------
# 11.1-REVIEW WR-01 — the VENUE-BLIND fee-model provider.
#
# Before this plan the provider was a ZERO-ARG closure in ``compose.py`` over
# ``exchanges.get((COMPUTE_VENUE, DEFAULT_ACCOUNT_ID))`` — resolved ONCE at
# wiring time, so every order's admission reservation was priced against the
# PAPER compute exchange no matter which venue would actually fill it. The
# provider now takes the order's own ``(venue, account_id)`` pair and resolves
# the registry inside the call.
#
# RESEARCH Pitfall 2 applies to every case below: ``Decimal("0")`` is BOTH the
# correct golden value and what a dead seam returns, so each case that must
# distinguish a working seam from a broken one uses a NON-ZERO fee.
# ---------------------------------------------------------------------------


def test_provider_is_called_with_the_orders_own_venue_and_account():
    """The provider receives the ORDER's ``(venue, account_id)`` (WR-01).

    Asserts the RECORDED ARGUMENTS, not a call count: a venue-blind provider is
    still called exactly once per estimate, so a counter cannot see the defect.
    Only the arguments can.
    """
    calls = []

    def recording_provider(venue, account_id):
        calls.append((venue, account_id))
        return _FakeFeeModel(Decimal("7.5"))

    manager = _make_admission(
        recording_provider, portfolio_handler=_StubReadModel("acct-b"))

    assert manager._estimate_commission(
        _make_order(exchange="okx")) == Decimal("7.5")
    assert calls == [("okx", "acct-b")]


def test_two_venues_with_different_fee_models_yield_different_estimates():
    """IDENTITY SENTINEL (WR-01) — a venue-blind provider fails this case.

    Two registered pairs carrying DIFFERENT fee models. A provider that always
    resolves the paper compute exchange returns the paper fee for BOTH orders,
    so this is the case that goes red if venue-awareness regresses. A call
    counter would stay green through that regression, which is why this file
    pins an identity sentinel alongside the argument assertion above (the
    two-independent-signals convention from
    the venue-account tests).
    """
    registry = {
        ("paper", DEFAULT_ACCOUNT_ID): _FakeFeeModel(Decimal("1.5")),
        ("okx", "acct-b"): _FakeFeeModel(Decimal("9.25")),
    }

    def registry_provider(venue, account_id):
        return registry.get((venue, account_id))

    paper_manager = _make_admission(
        registry_provider, portfolio_handler=_StubReadModel(None))
    okx_manager = _make_admission(
        registry_provider, portfolio_handler=_StubReadModel("acct-b"))

    assert paper_manager._estimate_commission(
        _make_order(exchange="paper")) == Decimal("1.5")
    assert okx_manager._estimate_commission(
        _make_order(exchange="okx")) == Decimal("9.25")


def test_unregistered_pair_degrades_to_zero_without_raising():
    """An unresolvable pair yields ``Decimal("0")`` and does NOT raise (WR-01).

    The provider's contract is "return None on a miss, never raise" — admission
    must degrade exactly as it does for a venue that exposes no fee model. The
    degrade is deliberately NOT silent: the warning assertion below is what
    keeps a routing miss from hiding behind the golden zero.
    """
    def registry_provider(venue, account_id):
        return {("paper", DEFAULT_ACCOUNT_ID): _FakeFeeModel(Decimal("1.5"))}.get(
            (venue, account_id))

    manager = _make_admission(
        registry_provider, portfolio_handler=_StubReadModel("no-such-account"))

    assert manager._estimate_commission(
        _make_order(exchange="okx")) == Decimal("0")
    assert manager.logger.warnings, (
        "a pair that resolves no fee model must be LOUD — a silent Decimal('0') "
        "is exactly how the venue-blind provider survived review (WR-01)")


def test_unnamed_account_resolves_the_default_account_identity():
    """A portfolio naming NO account resolves ``DEFAULT_ACCOUNT_ID`` (WR-01).

    ``Portfolio.account_id`` is optional and EVERY backtest portfolio leaves it
    unset (``add_portfolio`` in ``backtest_trading_system.py:578-583`` passes no
    ``account_id``), so the golden run reaches this resolution with ``None``.
    Coercing it to the single-account identity is what keeps the byte-exact
    oracle resolving the ``('paper', DEFAULT_ACCOUNT_ID)`` compute exchange.
    """
    calls = []

    def recording_provider(venue, account_id):
        calls.append((venue, account_id))
        return _FakeFeeModel(Decimal("2.25"))

    manager = _make_admission(
        recording_provider, portfolio_handler=_StubReadModel(None))

    assert manager._estimate_commission(_make_order()) == Decimal("2.25")
    assert calls == [("paper", DEFAULT_ACCOUNT_ID)]


def test_no_read_model_resolves_the_default_account_identity():
    """With NO read model there is exactly ONE account (WR-01).

    Mirrors ``ExecutionHandler._resolve_account_id``'s no-read-model arm: the
    single-account identity is correct and unconditional, because a manager
    without a portfolio read model has no portfolio to ask.
    """
    calls = []

    def recording_provider(venue, account_id):
        calls.append((venue, account_id))
        return _FakeFeeModel(Decimal("4.5"))

    manager = _make_admission(recording_provider)

    assert manager._estimate_commission(_make_order()) == Decimal("4.5")
    assert calls == [("paper", DEFAULT_ACCOUNT_ID)]
