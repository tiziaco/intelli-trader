"""The on-fill drift absorber is fee-aware (spot-base-fee-drift-halt, D-04/V17-04).

Spot settlement moves a position by ``amount - base_fee`` when the fee is denominated in
the pair's BASE currency (an OKX spot BUY), so the engine position equals the venue base
balance exactly once the venue has streamed the fill.

Until it has, ``PortfolioHandler._compare_symbol_drift`` forgives the transient through
its spurious-halt band: it reconstructs the pre-fill holding as
``engine_qty - just_applied_fill_qty`` and accepts venue truth that still matches THAT.
The delta ``on_fill`` supplies must therefore be the NET base delta settlement actually
applied (``transaction.position_quantity``), not the raw ``fill_event.quantity`` — with
the raw amount the reconstruction lands a whole base fee away from the true pre-fill
holding, which is beyond the 1e-8 band, and a perfectly healthy first fill trips
``halt('drift')``.

Both arms drive the policy with hand-built ``AccountSnapshot`` venue truth injected
through ``PortfolioHandler.set_snapshot_source``, so what is under test is the absorber's
arithmetic rather than any venue payload shape. Fully offline — no credentials, no
network, no connector.
"""

import queue
from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.core.enums import FillStatus, Side, TransactionType
from itrader.core.ids import CorrelationId, OrderId, StrategyId
from itrader.events_handler.events import FillEvent
from itrader.execution_handler.exchanges.base import AccountSnapshot
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.transaction import Transaction
from tests.support.venue_wiring import (
    backtest_portfolio_handler,
    compute_account,
)

_TICKER = "BTC/USDC"


def _spot_snapshot(btc_total: str) -> AccountSnapshot:
    """Spot venue truth holding ``btc_total`` of the pair's base currency."""
    base = Decimal(btc_total)
    return AccountSnapshot(
        balances={"USDC": Decimal("150000"), "BTC": base},
        positions={_TICKER: base} if base != 0 else {},
    )


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
def handler() -> PortfolioHandler:
    return backtest_portfolio_handler(queue.Queue())


@pytest.fixture
def halt_calls(handler: PortfolioHandler) -> list:
    calls: list = []
    handler.set_halt_signal(lambda reason: calls.append(reason))
    return calls


@pytest.fixture
def spot_venue_portfolio(handler: PortfolioHandler):
    """A registered live-shaped ``Portfolio`` whose venue truth holds ``btc_total`` base.

    Registered directly so ``on_fill`` can address it, and sitting on a COMPUTE leaf as
    every live portfolio does: the engine tally is the portfolio's own, and the venue's
    answer arrives through the handler's snapshot source.

    The snapshot is captured ONCE and returned unchanged for the rest of the test, which
    is the whole point of the pre-fill arm — venue truth that does not move when the
    engine settles a fill is exactly the lag the absorber has to forgive.
    """

    def _make(btc_total: str) -> Portfolio:
        portfolio = Portfolio("spot_venue_pf", "okx", Decimal("150000"), datetime.now(),
                              account=compute_account(Decimal("150000")))
        snapshot = _spot_snapshot(btc_total)
        handler.set_snapshot_source(lambda p: snapshot)
        handler._portfolios[portfolio.portfolio_id] = portfolio
        return portfolio

    return _make


def test_base_fee_fill_with_prefill_venue_truth_does_not_halt(
        handler, halt_calls, spot_venue_portfolio):
    """A base-fee BUY whose venue truth is still PRE-fill must NOT spuriously halt.

    Venue base balance == engine belief == 1.0 BTC pre-fill. A base-fee BUY of 0.001 BTC
    (fee 0.000001 BTC) settles the engine to 1.000999 while venue truth still reads the
    pre-fill 1.0 (the venue has not streamed the fill yet). The absorber must reconstruct
    the pre-fill holding from the NET base delta — 1.000999 - 0.000999 == 1.0 == venue —
    and forgive the transient.

    Reconstructing from the RAW 0.001 instead gives 0.999999, which is a full base fee
    (1e-6) off the venue's 1.0 and beyond the 1e-8 band, so the absorber would fall
    through and halt the engine on an ordinary first fill.
    """
    portfolio = spot_venue_portfolio("1.0")
    # Engine believes 1.0 BTC — equal to venue base truth (pre-fill parity).
    portfolio.position_manager.process_position_update(_seed_buy(qty="1.0"))
    assert portfolio.get_open_position(_TICKER).net_quantity == Decimal("1.0")

    # A base-fee BUY streams in; settlement nets the fee out (engine -> 1.000999) while
    # venue truth is unchanged (still 1.0) — the exact on-fill lag.
    fill = _base_fee_buy_fill(portfolio.portfolio_id, amount="0.001", fee="0.000001")
    handler.on_fill(fill)

    # Engine moved by the NET base (amount - base_fee); venue truth is still pre-fill.
    assert portfolio.get_open_position(_TICKER).net_quantity == Decimal("1.000999")
    assert handler._venue_snapshot(portfolio).positions[_TICKER] == Decimal("1.0")
    # The absorber forgave the transient — NO spurious halt.
    assert halt_calls == []


def test_genuine_unexplained_base_drift_still_halts(handler, halt_calls,
                                                    spot_venue_portfolio):
    """The fee-aware absorber must NOT hide a genuine unexplained divergence.

    Engine believes 1.0 BTC but venue truth is 2.0 (a real, unexplained 1.0 BTC holding)
    with NO just-applied fill in flight. The per-symbol compare must still surface it as
    ``halt('drift')`` — fee-awareness only forgives the pre-fill on-fill transient, never
    a persistent beyond-band divergence, which no other check would ever catch.
    """
    portfolio = spot_venue_portfolio("2.0")
    portfolio.position_manager.process_position_update(_seed_buy(qty="1.0"))

    handler._compare_symbol_drift(
        portfolio, _TICKER, CorrelationId(idgen.generate_correlation_id()))

    assert halt_calls == ["drift"]
