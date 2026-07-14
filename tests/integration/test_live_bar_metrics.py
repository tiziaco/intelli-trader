"""D-16 / WR-01 — live per-bar equity curve is recorded, keyed on EventType.BAR (05-06).

The live daemon previously keyed metric recording on ``EventType.TIME``. But ``LiveBarFeed``
emits ONLY ``BarEvent`` on the live path (the bar's arrival IS the event — there is no
``TimeEvent``), so the TIME key never fired and the live equity curve was always empty (WR-01,
surfaced in 04-REVIEW). ``LiveTradingSystem._record_bar_metrics`` now keys on ``EventType.BAR``
and stamps each snapshot with the bar-open BUSINESS time (``event.time``), never wall-clock.

These tests drive the recorder directly (the loop body, extracted to a testable helper) rather
than spinning the daemon thread: a ``BarEvent`` populates the per-bar equity curve with its
bar-open stamp; a ``TimeEvent`` records nothing (proving the recorder no longer keys on TIME —
with the old TIME key the curve would have been empty under the BAR-only live feed).

4-space indentation (matches ``tests/integration/*``); folder-derived ``integration`` marker.
"""

from datetime import datetime, timezone

from itrader.events_handler.events import BarEvent, TimeEvent


_BAR_OPEN = datetime(2021, 6, 1, 0, 0, 0, tzinfo=timezone.utc)


def _system_with_portfolio():
    """Construct an offline (in-memory) LiveTradingSystem with one active portfolio."""
    import itrader.trading_system.live_trading_system as lts

    # exchange='binance' keeps construction fully offline (no OKX/replay wiring); with no
    # SYSTEM_DB_URL the store falls back to in-memory — irrelevant to the metrics path.
    system = lts.LiveTradingSystem.for_exchange("binance")
    system.portfolio_handler.add_portfolio(
        name="live-metrics", exchange="binance", cash=100_000.0)
    return system


def test_bar_event_records_per_bar_equity_curve():
    """A BarEvent drives record_metrics per active portfolio with the bar-open stamp (D-16)."""
    system = _system_with_portfolio()
    try:
        portfolio = system.portfolio_handler.get_active_portfolios()[0]
        assert portfolio.metrics_manager.get_snapshots() == []   # empty before any bar

        system._record_bar_metrics(BarEvent(time=_BAR_OPEN, bars={}))

        snapshots = portfolio.metrics_manager.get_snapshots()
        assert len(snapshots) == 1                               # equity curve populated live
        # Business time (bar-open), never wall-clock (D-09).
        assert snapshots[0].timestamp == _BAR_OPEN
        # A fresh portfolio's equity is its cash (no positions) — a real, non-trivial point.
        assert snapshots[0].total_equity > 0
    finally:
        system.stop()


def test_time_event_records_nothing():
    """A TimeEvent records no snapshot — the recorder keys on BAR, not TIME (WR-01 fix).

    With the old TIME key AND a BAR-only live feed the curve was always empty; this asserts
    the inverse mapping — a TIME event is now a no-op — so the equity curve is driven by bars.
    """
    system = _system_with_portfolio()
    try:
        portfolio = system.portfolio_handler.get_active_portfolios()[0]

        system._record_bar_metrics(TimeEvent(time=_BAR_OPEN))

        assert portfolio.metrics_manager.get_snapshots() == []
    finally:
        system.stop()
