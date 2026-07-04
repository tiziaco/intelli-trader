"""A4 — spot-no-drift-halt RED test (D-03/D-04, V17-04/ARCH-2).

Pins the spot venue-truth + baseline-guard-band fix semantics as a failing
regression BEFORE it lands (05.1-08). On OKX SPOT there are NO position rows
(``fetch_positions`` / ``watch_positions`` return ``[]``): per-symbol position
truth must be DERIVED from the BASE-currency balance total (D-03), and the
session-start baseline guard must NOT spuriously halt on the "just-applied engine
fill vs not-yet-refreshed venue snapshot" band while STILL surfacing a genuinely
unexplained divergence (D-04).

Two arms, both RED against current code (this is the SUCCESS condition — D-19
CONF-A), because today ``VenueAccount.positions`` reads the derivative positions
channel only (``_extract_positions`` returns ``{}`` on spot — structurally blind):

* ``test_spot_no_drift_halt`` (ARM 1): the engine opens a real 0.5 BTC base
  position and venue base-balance agrees (0.5). It MUST NOT halt. RED today: the
  spot positions map is blind (``{}``) so venue reads 0, the engine's real 0.5
  looks like unexplained drift → spurious ``halt("drift")``.
* ``test_spot_unexplained_divergence_is_surfaced`` (ARM 2): the engine is FLAT but
  venue base-balance holds 0.9 BTC (a genuine unexplained holding). It MUST be
  surfaced (halt). RED today: the blind positions map reads 0 == engine 0 → within
  band → the divergence is hidden, no halt.

The A1/V17-01 settlement surface is itself RED, so a BUY cannot settle through the
``VenueAccount`` today; the drift DECISION is therefore driven directly against a
freshly-opened engine belief (seeded on the position manager) + the snapshotted spot
venue truth — mirroring ``test_venue_account_drift.py``. GREEN lands in 05.1-08.

Fully offline — no ``OKX_API_*`` credentials, no network; ``disconnect()`` teardown
keeps the strict suite clean (Pitfall 4, ``filterwarnings=["error"]``).
"""

import json
import queue
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.core.ids import CorrelationId
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.account.venue import VenueAccount

_TICKER = "BTC/USDC"
_SPOT_FIXTURE = Path(__file__).parent / "okx_recon_payloads_spot.json"


def _spot_payloads_with_btc(btc_total: str) -> dict:
    """Load the SPOT recon fixture with the base (BTC) balance total set.

    ccxt returns floats everywhere (Pitfall 2) — the payload carries floats and the
    venue ingress crosses the Decimal edge via ``to_money(str(x))`` (never
    ``Decimal(float)``). ``fetch_positions`` stays ``[]`` (spot has no position rows).
    """
    payloads = json.loads(_SPOT_FIXTURE.read_text())
    balance = payloads["fetch_balance"]
    balance["total"]["BTC"] = float(btc_total)
    balance["free"]["BTC"] = float(btc_total)
    return payloads


def _cid() -> CorrelationId:
    return CorrelationId(idgen.generate_correlation_id())


def _buy(qty: str, price: str = "100") -> Transaction:
    """A BUY ``Transaction`` used only to seed the engine position belief."""
    return Transaction(
        datetime.now(), TransactionType.BUY, _TICKER, Decimal(price), Decimal(qty),
        Decimal("0"), None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )


@pytest.fixture
def venue_connectors():
    """Factory yielding CONNECTED ``FakeLiveConnector``s with guaranteed teardown."""
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
def halt_calls(handler: PortfolioHandler) -> list[str]:
    calls: list[str] = []
    handler.set_halt_signal(lambda reason: calls.append(reason))
    return calls


def _spot_venue_portfolio(venue_connectors, btc_total: str) -> Portfolio:
    """A real Portfolio whose account is a VenueAccount snapshotted from spot truth.

    Quote currency from wiring (USDC, never the USDT default, D-03); venue base
    holding == ``btc_total``; ``fetch_positions`` == ``[]`` (spot has no rows).
    """
    connector = venue_connectors(_spot_payloads_with_btc(btc_total))
    portfolio = Portfolio("spot_venue_pf", "okx", Decimal("150000"), datetime.now())
    account = VenueAccount(connector, quote_currency="USDC")
    account.snapshot()
    portfolio.account = account
    return portfolio


# --- ARM 1: the just-applied fill must NOT spuriously halt (D-04 band) --------


def test_spot_no_drift_halt(venue_connectors, handler, halt_calls):
    """A freshly-opened spot fill that AGREES with venue base-balance must not halt.

    RED today: spot ``fetch_positions`` is ``[]`` so ``VenueAccount.positions`` is
    structurally blind (``{}``); venue reads 0 while the engine holds a real 0.5, so
    the compare fires a spurious ``halt("drift")`` on the first position-opening fill.
    GREEN after D-03/D-04: venue truth derives 0.5 from ``total[BTC]`` → within band.
    """
    portfolio = _spot_venue_portfolio(venue_connectors, btc_total="0.5")
    # One EXECUTED BUY opening 0.5 BTC (seeded directly — the account settlement
    # surface is itself RED per A1/V17-01, so drive the drift decision on the belief).
    portfolio.position_manager.process_position_update(_buy(qty="0.5"))

    handler._compare_symbol_drift(portfolio, _TICKER, _cid())

    assert halt_calls == []


# --- ARM 2: a genuine unexplained base-balance divergence MUST be surfaced ----


def test_spot_unexplained_divergence_is_surfaced(venue_connectors, handler, halt_calls):
    """An unexplained venue base-balance holding must be surfaced (halt), not hidden.

    RED today: the engine is FLAT and the blind spot positions map reads 0 == engine
    0 → within band → the real 0.9 BTC venue holding is never detected (structurally
    blind). GREEN after D-03: venue truth derives 0.9 from ``total[BTC]`` → beyond
    band, unexplained → ``halt("drift")``.
    """
    portfolio = _spot_venue_portfolio(venue_connectors, btc_total="0.9")
    # Engine believes FLAT (no seeded position).

    handler._compare_symbol_drift(portfolio, _TICKER, _cid())

    assert halt_calls == ["drift"]
