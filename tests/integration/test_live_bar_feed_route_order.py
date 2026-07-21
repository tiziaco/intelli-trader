"""FEED-05 — direct ``BarEvent`` emission preserves the TIME-before-BAR route order.

The live path drops ``TimeGenerator``: ``LiveBarFeed.update()`` emits a single-ticker
``BarEvent`` DIRECTLY onto ``global_queue`` the moment a confirm-gated closed bar arrives
(D-02/D-03/D-04) — the bar's arrival IS the event. This test proves that this direct
emission does NOT disturb the downstream ordering contract: dispatching the emitted
``BarEvent`` through the ``EventHandler``'s ``_routes`` runs the BAR route's registered
callables in their DECLARED order

    portfolio_handler.update_portfolios_market_value  (mark-to-market)
    -> execution_handler.on_market_data               (resting-order matching)
    -> strategies_handler.on_bar           (new signals)

exactly as the backtest TIME->BAR path does. LIST ORDER IS EXECUTION ORDER (D-14).

Fully offline (Phase-2 discipline): no socket, no connector, no async. The feed is driven
with a synthetic ``ClosedBar`` against a real ``queue.Queue``; the downstream handlers are
order-recording spies, so the assertion is on the dispatch sequence alone.

Indentation: 4 SPACES (matched to the ``price_handler/feed`` tree the feed lives in).
"""

from __future__ import annotations

import queue
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from itrader.events_handler.events import BarEvent
from itrader.events_handler.full_event_handler import EventHandler
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

# A fixed byte-reproducible epoch-ms literal (2024-01-01T00:00:00Z), never wall-clock.
_TS_MS = 1704067200000


def _closed_bar(
    ts_ms: int = _TS_MS, *, symbol: str = "BTC-USDT", timeframe: str = "1d"
) -> dict:
    """Build one synthetic ``ClosedBar`` — Decimal OHLCV + the D-12 routing keys."""
    return {
        "ts": int(ts_ms),
        "open": Decimal("42000.0"),
        "high": Decimal("42500.0"),
        "low": Decimal("41800.0"),
        "close": Decimal("42100.0"),
        "volume": Decimal("1200.5"),
        "symbol": symbol,
        "timeframe": timeframe,
    }


def test_update_emits_exactly_one_bar_event() -> None:
    """A single ``update()`` emits exactly one ``BarEvent`` onto the bound queue (FEED-05)."""
    q: "queue.Queue[Any]" = queue.Queue()
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta("1d"))
    feed.bind(q, ["BTC-USDT"])

    feed.update(_closed_bar())

    assert q.qsize() == 1
    event = q.get_nowait()
    assert isinstance(event, BarEvent)
    assert "BTC-USDT" in event.bars


def test_direct_emission_preserves_bar_route_order() -> None:
    """The emitted ``BarEvent`` drives the BAR route in the declared order (FEED-05/D-14).

    Direct ``update()`` emission replaces ``TimeGenerator`` while the downstream
    TIME-before-BAR ordering is preserved: mark-to-market -> resting-order matching ->
    new signals.
    """
    calls: list[str] = []

    def rec(name: str):
        def _handler(event: Any) -> None:
            calls.append(name)
        return _handler

    # Order-recording spies standing in for the real handlers — SimpleNamespace exposes
    # exactly the method names the EventHandler route literal references.
    portfolio = SimpleNamespace(
        update_portfolios_market_value=rec("portfolio.update_portfolios_market_value"),
        on_fill=rec("portfolio.on_fill"),
    )
    execution = SimpleNamespace(
        on_market_data=rec("execution.on_market_data"),
        on_order=rec("execution.on_order"),
    )
    strategies = SimpleNamespace(
        on_bar=rec("strategies.on_bar"),
    )
    screeners = SimpleNamespace(screen_markets=rec("screeners.screen_markets"))
    order = SimpleNamespace(
        on_signal=rec("order.on_signal"),
        on_fill=rec("order.on_fill"),
        on_order_ack=rec("order.on_order_ack"),  # D-06: EventHandler route literal references it
    )

    q: "queue.Queue[Any]" = queue.Queue()
    event_handler = EventHandler(
        strategies, screeners, portfolio, order, execution,
        bar_event_source=lambda e: None, global_queue=q,
        # 08-03: injected error_policy + error_handler (unused on the BAR route).
        error_policy=SimpleNamespace(on_handler_error=lambda e, h: None),
        error_handler=SimpleNamespace(on_error=lambda e: None),
    )

    # Drive the LIVE feed: update() emits the BarEvent directly (no TimeGenerator tick).
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta("1d"))
    feed.bind(q, ["BTC-USDT"])
    feed.update(_closed_bar())
    bar_event = q.get_nowait()

    # Dispatch the emitted BarEvent through the routing registry.
    event_handler._dispatch(bar_event)

    assert calls == [
        "portfolio.update_portfolios_market_value",
        "execution.on_market_data",
        "strategies.on_bar",
    ]
