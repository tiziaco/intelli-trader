"""Liquidation formula / breach / penalty / fill-at-liq-price (LIQ-01, LIQ-02) — 04-03.

Isolated-margin liquidation engine unit coverage (D-01-CORR / D-03-CORR / D-04 /
D-05 / D-07). The corrected worked scenario is Entry=100, |size|=200, leverage
L=5 → WB (locked margin) = notional/L = 100×200/5 = 4000, MMR=0.01:

  margin_per_unit = WB/|size| = 20
  LONG  liq = (entry − 20)/(1 − 0.01) = 80/0.99   = 80.808080…  (corrected, D-01-CORR)
  SHORT liq = (entry + 20)/(1 + 0.01) = 120/1.01  = 118.811881… (corrected)

A NEGATIVE result FAILS — it would mean the literal CONTEXT D-01 string was used
instead of the corrected D-01-CORR formula.

Folder-derived `unit` marker (tests/conftest.py applies it; no decorator here).
No reference-engine import (NEVER `backtesting`/`backtrader`).
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue
from typing import Any, List

import uuid_utils.compat as uuid_compat

from itrader.core.enums import OrderStatus, OrderTriggerSource
from itrader.events_handler.events import FillEvent
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.position import Position
from itrader.portfolio_handler.transaction import Transaction, TransactionType


# ----- worked scenario constants -------------------------------------------------
_TICKER = "LIQUSD"
_ENTRY = Decimal("100")
_SIZE = Decimal("200")
_LEVERAGE = Decimal("5")
_WB = _ENTRY * _SIZE / _LEVERAGE       # 4000 — locked isolated margin
_MMR = Decimal("0.01")

_LONG_LIQ = (_ENTRY - _WB / _SIZE) / (Decimal("1") - _MMR)    # 80.808080…
_SHORT_LIQ = (_ENTRY + _WB / _SIZE) / (Decimal("1") + _MMR)   # 118.811881…


class _StubInstrument:
    def __init__(self, mmr: Decimal, fee_rate: Decimal) -> None:
        self.maintenance_margin_rate = mmr
        self.liquidation_fee_rate = fee_rate


class _StubUniverse:
    """Universe read-model: instrument(ticker) -> per-ticker _StubInstrument."""

    def __init__(self, instruments: dict[str, _StubInstrument]) -> None:
        self._instruments = instruments

    def instrument(self, symbol: str) -> _StubInstrument:
        return self._instruments[symbol]


def _handler(universe: Any = None) -> PortfolioHandler:
    h = PortfolioHandler(Queue())
    if universe is not None:
        h.set_universe(universe)
    return h


def _open_position(handler: PortfolioHandler, *, side: str, ticker: str = _TICKER,
                   entry: Decimal = _ENTRY, size: Decimal = _SIZE,
                   leverage: Decimal = _LEVERAGE,
                   entry_date: datetime = datetime(2024, 1, 1),
                   cash: Decimal = Decimal("1000000")) -> tuple[Any, Position]:
    """Create a portfolio with one open LONG/SHORT position + a WB margin lock."""
    pid = handler.add_portfolio(
        user_id=1, name=f"liq-{ticker}", exchange="simulated", cash=float(cash))
    portfolio: Portfolio = handler.get_portfolio(pid)
    txn_type = TransactionType.BUY if side == "long" else TransactionType.SELL
    txn = Transaction(
        entry_date, txn_type, ticker, entry, size, 0,
        portfolio.portfolio_id, id=1, fill_id=uuid_compat.uuid7(),
    )
    position = Position.open_position(txn)
    portfolio.position_manager._storage.set_position(ticker, position)
    # Lock the isolated margin (WB) keyed by the position id — the WB source the
    # liquidation floor reads via get_locked_margin_for.
    wb = entry * size / leverage
    portfolio.cash_manager.lock_margin(str(position.id), wb)
    return portfolio.portfolio_id, position


def test_isolated_liq_price_long():
    """LIQ-01 (D-01-CORR): long liq = (entry − WB/|size|)/(1 − MMR) ≈ 80.808080…"""
    h = _handler(_StubUniverse({_TICKER: _StubInstrument(_MMR, Decimal("0"))}))
    pid, position = _open_position(h, side="long")

    liq = h._isolated_liq_price(position, _WB, _MMR)

    assert liq > Decimal("0"), "corrected formula must be positive (D-01-CORR, not CONTEXT D-01)"
    assert liq == _LONG_LIQ
    assert str(liq).startswith("80.808080")


def test_isolated_liq_price_short():
    """LIQ-01 (D-01-CORR): short liq = (entry + WB/|size|)/(1 + MMR) ≈ 118.811881…"""
    h = _handler(_StubUniverse({_TICKER: _StubInstrument(_MMR, Decimal("0"))}))
    pid, position = _open_position(h, side="short")

    liq = h._isolated_liq_price(position, _WB, _MMR)

    assert liq == _SHORT_LIQ
    assert str(liq).startswith("118.811881")


def test_liquidation_breach_detected_on_bar_close():
    """LIQ-01: breach when bar close crosses the liq price (long: close <= liq;
    short: close >= liq); NOT detected otherwise."""
    h = _handler(_StubUniverse({_TICKER: _StubInstrument(_MMR, Decimal("0"))}))
    pid, position = _open_position(h, side="long")

    # close above liq → no breach; close at/below liq → breach.
    assert h._is_breached(position, _LONG_LIQ + Decimal("1"), _LONG_LIQ) is False
    assert h._is_breached(position, _LONG_LIQ, _LONG_LIQ) is True
    assert h._is_breached(position, _LONG_LIQ - Decimal("5"), _LONG_LIQ) is True

    h2 = _handler(_StubUniverse({_TICKER: _StubInstrument(_MMR, Decimal("0"))}))
    _, short_pos = _open_position(h2, side="short")
    assert h2._is_breached(short_pos, _SHORT_LIQ - Decimal("1"), _SHORT_LIQ) is False
    assert h2._is_breached(short_pos, _SHORT_LIQ, _SHORT_LIQ) is True
    assert h2._is_breached(short_pos, _SHORT_LIQ + Decimal("5"), _SHORT_LIQ) is True


def test_liquidation_penalty():
    """LIQ-02: penalty = liquidation_fee_rate × |size| × liq_price."""
    h = _handler()
    fee_rate = Decimal("0.0075")
    penalty = h._liquidation_penalty(fee_rate, _SIZE, _LONG_LIQ)
    assert penalty == fee_rate * _SIZE * _LONG_LIQ


def test_multi_breach_deterministic():
    """LIQ-01: simultaneous multi-position breaches are collected in a FIXED
    (ticker, open_time, position_id) order regardless of dict iteration order."""
    # Two breaching longs on two tickers, opened at different times.
    instruments = {
        "ZZZUSD": _StubInstrument(_MMR, Decimal("0")),
        "AAAUSD": _StubInstrument(_MMR, Decimal("0")),
    }
    h = _handler(_StubUniverse(instruments))
    pid = h.add_portfolio(user_id=1, name="multi", exchange="simulated", cash=1000000.0)
    portfolio = h.get_portfolio(pid)

    # Insert ZZZ first (later open time) then AAA (earlier open time) so the dict
    # iteration order does NOT match the required sort order.
    def _add(ticker: str, entry_date: datetime) -> Position:
        txn = Transaction(
            entry_date, TransactionType.BUY, ticker, _ENTRY, _SIZE, 0,
            portfolio.portfolio_id, id=1, fill_id=uuid_compat.uuid7(),
        )
        pos = Position.open_position(txn)
        portfolio.position_manager._storage.set_position(ticker, pos)
        portfolio.cash_manager.lock_margin(str(pos.id), _WB)
        return pos

    _add("ZZZUSD", datetime(2024, 1, 2))
    _add("AAAUSD", datetime(2024, 1, 1))

    # Both breach at a deep close.
    breached = h._collect_breaches(portfolio, Decimal("50"), datetime(2024, 2, 1))
    tickers = [b.ticker for b in breached]
    assert tickers == sorted(tickers)
    assert tickers == ["AAAUSD", "ZZZUSD"]


def test_liquidation_emits_executed_fill_on_bar_route():
    """LIQ-02/D-04: a bar-close breach mints a FillEvent(EXECUTED) on the queue at
    the liq price, time == bar_time, commission == penalty, NOT routed through
    ExecutionHandler / next-bar-open."""
    fee_rate = Decimal("0.001")
    h = _handler(_StubUniverse({_TICKER: _StubInstrument(_MMR, fee_rate)}))
    pid, position = _open_position(h, side="long")
    h.set_order_storage(_DictOrderStorage())

    bar_time = datetime(2024, 2, 1)
    # Drain the queue, then mark below the liq price → breach.
    _drain(h.global_queue)
    _mark_close(h, _TICKER, Decimal("70"), bar_time)

    fills = [e for e in _drain(h.global_queue) if isinstance(e, FillEvent)]
    assert len(fills) == 1
    fill = fills[0]
    assert str(fill.status) == "FillStatus.EXECUTED" or fill.status.name == "EXECUTED"
    assert fill.time == bar_time
    assert fill.quantity == _SIZE
    assert fill.price == _LONG_LIQ
    assert fill.commission == fee_rate * _SIZE * _LONG_LIQ
    # Opposite side to close a long.
    assert fill.action.name == "SELL"


def test_liquidation_fills_at_liq_price_on_far_gap_through():
    """CR-01 (option a): fill-at-liq-price IS the loss-bounding mechanism.

    When the breach bar gaps FAR below the isolated liq price (close=10 vs
    liq≈80.808), the forced close still books the fill AT the liq price (≈80.81),
    NOT at the gapped close. The realized loss is the liq-price loss
    ``(entry − liq) × |size|``, NOT the gapped-close loss ``(entry − 10) × |size|``.

    This pins the actual mechanism: there is NO explicit ``min(loss + penalty,
    WB)`` clamp — the loss is bounded by SETTLING AT THE FLOOR (D-03 automatic-
    floor reading). The engine never models a pessimistic below-floor gap fill.
    """
    fee_rate = Decimal("0.001")
    h = _handler(_StubUniverse({_TICKER: _StubInstrument(_MMR, fee_rate)}))
    pid, position = _open_position(h, side="long")
    h.set_order_storage(_DictOrderStorage())

    bar_time = datetime(2024, 2, 1)
    gapped_close = Decimal("10")   # FAR below the 80.808… liq floor.
    assert gapped_close < _LONG_LIQ
    _drain(h.global_queue)
    _mark_close(h, _TICKER, gapped_close, bar_time)

    fills = [e for e in _drain(h.global_queue) if isinstance(e, FillEvent)]
    assert len(fills) == 1
    fill = fills[0]

    # The fill is booked AT the liq price (≈80.81), NOT the gapped close (10).
    assert fill.price == _LONG_LIQ
    assert fill.price != gapped_close
    assert str(fill.price).startswith("80.808080")

    # Realized loss is the LIQ-PRICE loss, not the gapped-close loss.
    liq_price_loss = (_ENTRY - _LONG_LIQ) * _SIZE
    gapped_close_loss = (_ENTRY - gapped_close) * _SIZE
    assert fill.price * _SIZE == _LONG_LIQ * _SIZE
    booked_loss = (_ENTRY - fill.price) * _SIZE
    assert booked_loss == liq_price_loss
    assert booked_loss != gapped_close_loss
    # The liq-price loss is below WB (the floor bounds it by construction);
    # the gapped-close loss would have blown WELL past WB had the engine filled
    # at the gapped close (proving why fill-at-liq-price is what bounds the loss).
    assert liq_price_loss < _WB
    assert gapped_close_loss > _WB

    assert fill.commission == fee_rate * _SIZE * _LONG_LIQ
    assert fill.action.name == "SELL"


# ----- helpers -------------------------------------------------------------------
class _DictOrderStorage:
    """Minimal order_storage stand-in: add_order / get_order_by_id over a flat dict."""

    def __init__(self) -> None:
        self._by_id: dict[Any, Any] = {}

    def add_order(self, order: Any) -> None:
        self._by_id[order.id] = order

    def get_order_by_id(self, order_id: Any, portfolio_id: Any = None) -> Any:
        return self._by_id.get(order_id)

    def update_order(self, order: Any) -> bool:
        self._by_id[order.id] = order
        return True


def _drain(queue: "Queue[Any]") -> List[Any]:
    out: List[Any] = []
    while True:
        try:
            out.append(queue.get_nowait())
        except Exception:
            break
    return out


def _mark_close(handler: PortfolioHandler, ticker: str, close: Decimal,
                bar_time: datetime) -> None:
    from itrader.core.bar import Bar
    from itrader.events_handler.events import BarEvent

    bar = Bar(
        time=bar_time, open=close, high=close, low=close, close=close,
        volume=Decimal("1"),
    )
    bar_event = BarEvent(time=bar_time, bars={ticker: bar})
    handler.update_portfolios_market_value(bar_event)
