"""Regression: the on-fill drift ABSORBER must be fee-aware (spot-base-fee-drift-halt).

Follow-on to the fee-currency-aware settlement fix. The settlement now moves a spot
position by ``amount - base_fee`` for a base-denominated fee (OKX spot BUY), so the
engine position == venue base balance EXACTLY. But the on-fill drift-halt ABSORBER
(``PortfolioHandler._compare_symbol_drift`` spurious-halt band, D-04/V17-04) forgives
the "fill applied to the engine but not yet in the venue snapshot" transient by checking
``venue_qty ≈ engine_qty - just_applied_fill_qty``. ``on_fill`` USED TO pass the RAW
``fill_event.quantity`` as ``just_applied_fill_qty`` — but the settlement only moved the
position by ``amount - base_fee``, so ``engine_qty - amount == pre - base_fee`` (off by the
fee from the true pre-fill holding). When the async venue cache is still pre-fill at compare
time (stream-vs-engine-thread race), the absorber fails and falls through to ``halt('drift')``.

This is the exact race the online ``test_demo_order_produces_real_fill_event`` hits. The fix
derives ``just_applied_fill_qty`` from the SAME fee-aware net-base delta the settlement
applied (``transaction.position_quantity``, signed by action) so the absorber reconstructs the
true pre-fill holding and forgives the transient.

Fully offline (``FakeLiveConnector`` spot fixture — no OKX creds, no network); ``disconnect()``
teardown keeps the strict suite clean (``filterwarnings=["error"]``). 4-space indent.
"""

import json
import queue
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.core.enums import FillStatus, Side, TransactionType
from itrader.core.ids import CorrelationId, OrderId, StrategyId
from itrader.events_handler.events import FillEvent
from itrader.portfolio_handler.account.venue import VenueAccount
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.transaction import Transaction

_TICKER = "BTC/USDC"
_SPOT_FIXTURE = Path(__file__).parent / "okx_recon_payloads_spot.json"


def _spot_payloads_with_btc(btc_total: str) -> dict:
    """Load the SPOT recon fixture with the base (BTC) balance total set (float edge)."""
    payloads = json.loads(_SPOT_FIXTURE.read_text())
    balance = payloads["fetch_balance"]
    balance["total"]["BTC"] = float(btc_total)
    balance["free"]["BTC"] = float(btc_total)
    return payloads


def _seed_buy(qty: str, price: str = "100") -> Transaction:
    """A zero-fee BUY used only to seed the engine position belief to the venue baseline."""
    return Transaction(
        datetime.now(), TransactionType.BUY, _TICKER, Decimal(price), Decimal(qty),
        Decimal("0"), None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )


def _base_fee_buy_fill(portfolio_id, *, amount: str, fee: str, price: str = "100") -> FillEvent:
    """An EXECUTED base-denominated-fee BUY FillEvent (fee_currency == pair base 'BTC')."""
    return FillEvent(
        time=datetime.now(),
        status=FillStatus.EXECUTED,
        ticker=_TICKER,
        action=Side.BUY,
        price=Decimal(price),
        quantity=Decimal(amount),
        commission=Decimal(fee),
        portfolio_id=portfolio_id,
        fill_id=uuid_compat.uuid7(),
        order_id=OrderId(uuid_compat.uuid7()),
        strategy_id=StrategyId(uuid_compat.uuid7()),
        fee_currency="BTC",
    )


@pytest.fixture
def venue_connectors():
    """Factory yielding CONNECTED FakeLiveConnectors with guaranteed teardown."""
    from tests.support.fake_venue_connector import make_fake_venue_connector

    created = []

    def _make(payloads):
        connector = make_fake_venue_connector(sandbox=True, payloads=payloads)
        connector.connect()
        created.append(connector)
        return connector

    try:
        yield _make
    finally:
        for connector in created:
            connector.disconnect()


@pytest.fixture
def handler() -> PortfolioHandler:
    return PortfolioHandler(queue.Queue())


@pytest.fixture
def halt_calls(handler: PortfolioHandler) -> list:
    calls: list = []
    handler.set_halt_signal(lambda reason: calls.append(reason))
    return calls


def _spot_venue_portfolio(venue_connectors, handler, btc_total: str) -> Portfolio:
    """A registered Portfolio whose account is a VenueAccount snapshotted from spot truth."""
    connector = venue_connectors(_spot_payloads_with_btc(btc_total))
    portfolio = Portfolio("spot_venue_pf", "okx", Decimal("150000"), datetime.now())
    account = VenueAccount(
        connector, quote_currency="USDC", market_type="spot", symbol=_TICKER
    )
    account.snapshot()
    portfolio.account = account
    handler._portfolios[portfolio.portfolio_id] = portfolio
    return portfolio


def test_base_fee_fill_with_prefill_venue_cache_does_not_halt(venue_connectors, handler, halt_calls):
    """A base-fee BUY whose venue cache is still PRE-fill must NOT spuriously halt.

    Venue base balance == engine belief == 1.0 BTC pre-fill (the snapshot is taken then).
    A base-fee BUY of 0.001 BTC (fee 0.000001 BTC) settles the engine to 1.000999, while the
    async venue cache still reads the pre-fill 1.0 (the stream-vs-engine-thread race). The
    on-fill absorber must reconstruct the pre-fill holding from the NET base delta
    (1.000999 - 0.000999 == 1.0 == venue) and forgive the transient.

    RED before the absorber fix: on_fill passed the RAW 0.001 as just_applied_fill_qty, so
    1.000999 - 0.001 == 0.999999 != 1.0 (off by the 1e-6 base fee, beyond the 1e-8 band) ->
    the absorber falls through to halt('drift'). GREEN after: net-base delta reconstructs 1.0.
    """
    portfolio = _spot_venue_portfolio(venue_connectors, handler, btc_total="1.0")
    # Engine believes 1.0 BTC — equal to the snapshotted venue base balance (pre-fill parity).
    portfolio.position_manager.process_position_update(_seed_buy(qty="1.0"))
    assert portfolio.get_open_position(_TICKER).net_quantity == Decimal("1.0")

    # A base-fee BUY streams in; settlement nets the fee out (engine -> 1.000999) while the
    # venue cache is NOT refreshed (still 1.0) — the exact on-fill race.
    fill = _base_fee_buy_fill(portfolio.portfolio_id, amount="0.001", fee="0.000001")
    handler.on_fill(fill)

    # Engine moved by the NET base (amount - base_fee); venue cache still pre-fill.
    assert portfolio.get_open_position(_TICKER).net_quantity == Decimal("1.000999")
    assert portfolio.account.positions.get(_TICKER) == Decimal("1.0")
    # The absorber forgave the transient — NO spurious halt.
    assert halt_calls == []


def test_genuine_unexplained_base_drift_still_halts(venue_connectors, handler, halt_calls):
    """The fee-aware absorber must NOT hide a genuine unexplained divergence.

    Engine believes 1.0 BTC but the venue base balance is 2.0 (a real, unexplained 1.0 BTC
    holding) with NO just-applied fill in flight. The per-symbol compare must still surface
    it as ``halt('drift')`` — the fee-awareness only forgives the pre-fill on-fill transient,
    never a persistent beyond-band divergence.
    """
    portfolio = _spot_venue_portfolio(venue_connectors, handler, btc_total="2.0")
    portfolio.position_manager.process_position_update(_seed_buy(qty="1.0"))

    handler._compare_symbol_drift(
        portfolio, _TICKER, CorrelationId(idgen.generate_correlation_id()))

    assert halt_calls == ["drift"]
