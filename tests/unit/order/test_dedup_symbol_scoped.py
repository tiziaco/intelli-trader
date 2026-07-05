"""D-08 / V17-12 — the correlation-ring dedup must be SYMBOL-scoped, not raw-tradeId.

Two live venue emitters can deliver trades that share the SAME numeric ``tradeId``
while resolving to orders on DIFFERENT instruments (OKX tradeIds are unique only
per-instrument, not globally). ``VenueCorrelationIndex.resolve`` deduped on the raw
``trade['id']`` alone, so the SECOND symbol's fill collided with the first and was
dropped as a false ``duplicate`` — the V17-12 instrument-scoped-tradeId collision.

The fix (Plan 05.2-03 Task 2): re-key the ring on ``f"{symbol}:{trade_id}"`` where
``symbol`` is the RESOLVED order's ticker — so two symbols sharing a numeric tradeId
both settle, while re-delivering the SAME ``(symbol, tradeId)`` is still a duplicate
no-op.

RED today (raw-tradeId keying): the second symbol's fill is a false ``duplicate``.
GREEN after the re-key: both settle; a genuine same-(symbol, tradeId) re-send dedups.

Socket-free, fully offline — constructs the index directly (mirrors
``tests/unit/execution/test_venue_correlation.py``). Folder-derived ``unit`` marker.
"""

from datetime import datetime, timezone
from decimal import Decimal

from itrader.core.enums import OrderCommand, OrderType, Side
from itrader.events_handler.events import OrderEvent
from itrader.execution_handler.exchanges.venue_correlation import VenueCorrelationIndex


def _make_order(*, ticker: str, order_id: int) -> OrderEvent:
    """A minimal OrderEvent on a given ticker (mirrors the venue_correlation suite)."""
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker=ticker,
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="okx",
        strategy_id=7,
        portfolio_id=3,
        order_type=OrderType.LIMIT,
        order_id=order_id,
        command=OrderCommand.NEW,
    )


def test_same_tradeid_across_symbols_both_settle() -> None:
    """Two trades sharing a numeric tradeId on DIFFERENT symbols must BOTH emit.

    RED today: the second symbol's fill is a false ``duplicate`` because the ring
    deduped on the raw tradeId. GREEN after the ``f"{symbol}:{trade_id}"`` re-key.
    """
    idx = VenueCorrelationIndex()
    btc = _make_order(ticker="BTC-USDT", order_id=1)
    eth = _make_order(ticker="ETH-USDT", order_id=2)

    idx.register("OID-BTC", btc, "it-btc")
    idx.register("OID-ETH", eth, "it-eth")

    # Same numeric tradeId "42" — but each resolves to a DIFFERENT symbol's order.
    res_btc = idx.resolve({"id": "42", "order": "OID-BTC", "amount": "0.2"})
    res_eth = idx.resolve({"id": "42", "order": "OID-ETH", "amount": "0.2"})

    assert res_btc.outcome == "emit"
    assert res_btc.order is btc
    assert res_eth.outcome == "emit", (
        "V17-12: the ETH fill sharing numeric tradeId 42 with the BTC fill was "
        f"dropped as a false duplicate (outcome={res_eth.outcome!r}); the ring must "
        "dedup on f'{symbol}:{trade_id}', not the raw tradeId."
    )
    assert res_eth.order is eth


def test_same_symbol_and_tradeid_still_dedups() -> None:
    """Re-delivering the SAME (symbol, tradeId) is still a duplicate no-op."""
    idx = VenueCorrelationIndex()
    btc = _make_order(ticker="BTC-USDT", order_id=1)
    idx.register("OID-BTC", btc, "it-btc")

    first = idx.resolve({"id": "42", "order": "OID-BTC", "amount": "0.2"})
    second = idx.resolve({"id": "42", "order": "OID-BTC", "amount": "0.2"})

    assert first.outcome == "emit"
    assert second.outcome == "duplicate"
