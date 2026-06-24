"""PairStrategy two-leg dispatch contract tests (PAIR-01, D-01/D-02/D-08/D-14).

Locks the ``StrategiesHandler._dispatch_pair`` branch (the only net-new engine
surface Phase 6 adds beside ``PairStrategy``) WITHOUT the concrete ETH/BTC
reference strategy: a tiny module-local ``_StubPair(PairStrategy)`` returns a
FIXED β-weighted entry pair so the test exercises the dispatch contract — fan
both legs, both-present guard, β-weighted quantities + LONG_SHORT direction —
independent of the β/z statsmodels math (Plan 06-02).

The handler is constructed with ``allow_short_selling=True, enable_margin=True``
so the registration gate (strategies_handler.py:280-287) admits the LONG_SHORT
pair strategy; otherwise ``add_strategy`` raises (T-06-10).

Selectors: ``-k both_legs``, ``-k both_present``, ``-k beta_weighted``
(06-VALIDATION.md Per-Task Verification Map). Folder-derived ``unit`` marker.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from queue import Queue

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import OrderType, Side, TradingDirection
from itrader.core.sizing import FixedQuantity, SignalIntent
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.strategy_handler.pair_base import PairStrategy
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit

# Pair legs: leg A (tickers[0]) is the RICH leg (SELL), leg B (tickers[1]) is the
# CHEAP leg (BUY). The stub returns a fixed β-weighted entry: SELL N of A, BUY
# β·N of B — proving the dispatch threads per-leg β-weighted quantities (D-08).
_TICKER_A = "ETHUSD"   # rich leg — SELL
_TICKER_B = "BTCUSD"   # cheap leg — BUY
_N = Decimal("3")      # base leg quantity (leg A)
_BETA = Decimal("2")   # β: leg B quantity is β·N
_BETA_N = _BETA * _N   # 6 — leg B β-weighted quantity

_BETA_WARMUP = 5
_Z_LOOKBACK = 3
_MAX_WINDOW = _BETA_WARMUP + _Z_LOOKBACK  # 8 — clears validate() (Pitfall 3)


class _StubPair(PairStrategy):
    """A tiny pair strategy that ignores the windows and returns a FIXED
    β-weighted entry pair — SELL ``_N`` of leg A, BUY ``_BETA_N`` of leg B.

    Carries NO β/z math (that lives in the concrete reference strategy, Plan
    06-02): the whole point is to exercise the dispatch contract in isolation.
    """

    name = "stub_pair"
    sizing_policy = FixedQuantity(qty=Decimal("1"))
    z_lookback = _Z_LOOKBACK
    beta_warmup = _BETA_WARMUP
    max_window = _MAX_WINDOW

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def evaluate_pair(
        self, win_A: pd.DataFrame, win_B: pd.DataFrame
    ) -> list[SignalIntent] | None:
        # Fixed β-weighted entry — SELL the rich leg, BUY the cheap leg.
        return [
            self._entry(self.tickers[0], Side.SELL, _N),
            self._entry(self.tickers[1], Side.BUY, _BETA_N),
        ]


class _StubFeed:
    """A minimal ``BarFeed`` stand-in.

    P5-D13/D15: the pair dispatch no longer slices ``feed.window()`` — it pushes
    both legs into the pair's OWN bounded buffers via ``update_pair`` and gates on
    ``is_pair_ready()``. The feed is therefore never queried on the pair path; this
    stub only needs ``symbols`` for wiring and a vestigial ``window`` to satisfy the
    ``BarFeed`` shape if ever called (it is not, on the pair path).
    """

    def symbols(self) -> list[str]:
        return [_TICKER_A, _TICKER_B]

    def window(self, ticker, timeframe, max_window, asof):  # type: ignore[no-untyped-def]
        n = _MAX_WINDOW + 2
        idx = pd.date_range(end=asof, periods=n, freq="1D", tz="UTC")
        return pd.DataFrame(
            {
                "open": [100.0] * n,
                "high": [100.0] * n,
                "low": [100.0] * n,
                "close": [100.0] * n,
                "volume": [1.0] * n,
            },
            index=idx,
        )


def _bar(price: float) -> Bar:
    return Bar(
        time=datetime(2020, 1, 8, tzinfo=timezone.utc),
        open=Decimal(str(price)),
        high=Decimal(str(price)),
        low=Decimal(str(price)),
        close=Decimal(str(price)),
        volume=Decimal("1"),
    )


def _make_handler() -> StrategiesHandler:
    # T-06-10: both flags ON so add_strategy admits the LONG_SHORT pair strategy.
    return StrategiesHandler(
        Queue(),
        _StubFeed(),
        InMemorySignalStore(),
        allow_short_selling=True,
        enable_margin=True,
    )


def _make_subscribed_pair(handler: StrategiesHandler) -> _StubPair:
    strategy = _StubPair(timeframe="1d", tickers=[_TICKER_A, _TICKER_B])
    handler.add_strategy(strategy)
    strategy.subscribe_portfolio(1)
    return strategy


def _bar_event(*, both_legs: bool, day: int = 8) -> BarEvent:
    bars = {_TICKER_A: _bar(2000.0)}
    if both_legs:
        bars[_TICKER_B] = _bar(40000.0)
    return BarEvent(time=datetime(2020, 1, day, tzinfo=timezone.utc), bars=bars)


def _drain(queue: "Queue") -> list[SignalEvent]:  # type: ignore[type-arg]
    events: list[SignalEvent] = []
    while not queue.empty():
        events.append(queue.get())
    return events


def _warm_to_ready(handler: StrategiesHandler) -> None:
    """P5-D15: feed ``beta_warmup + z_lookback - 1`` two-leg ticks WITHOUT crossing
    the readiness threshold, draining each so the queue is empty on the final
    (ready) tick the test asserts on.

    The pair dispatch now gates on the pair's OWN bounded-buffer fill
    (``is_pair_ready()`` == ``beta_warmup + z_lookback`` bars buffered), NOT a
    ``feed.window()`` slice. So a single tick no longer fires — the buffer must be
    primed to one-below-ready first.
    """
    for d in range(1, _MAX_WINDOW):  # _MAX_WINDOW-1 priming ticks (day 1.._MAX_WINDOW-1)
        handler.calculate_signals(_bar_event(both_legs=True, day=d))
    _drain(handler.global_queue)


def test_both_legs_emit_once_per_tick() -> None:
    """D-01: both legs present (and buffer ready) -> EXACTLY two SignalEvents."""
    handler = _make_handler()
    _make_subscribed_pair(handler)
    _warm_to_ready(handler)

    handler.calculate_signals(_bar_event(both_legs=True))

    signals = _drain(handler.global_queue)
    assert len(signals) == 2, "both legs present -> exactly 2 SignalEvents"
    tickers = {s.ticker for s in signals}
    assert tickers == {_TICKER_A, _TICKER_B}, "one SignalEvent per leg"


def test_both_present_guard_skips_when_one_absent() -> None:
    """D-02: one leg's bar absent -> ZERO SignalEvents (skip silently)."""
    handler = _make_handler()
    _make_subscribed_pair(handler)
    _warm_to_ready(handler)

    handler.calculate_signals(_bar_event(both_legs=False))

    signals = _drain(handler.global_queue)
    assert signals == [], "a missing leg -> no spread -> 0 SignalEvents (D-02)"


def test_beta_weighted_leg_quantities() -> None:
    """D-08/D-14: the two SignalEvents carry N vs β·N quantities, LONG_SHORT on
    each, SELL on the rich leg and BUY on the cheap leg."""
    handler = _make_handler()
    _make_subscribed_pair(handler)
    _warm_to_ready(handler)

    handler.calculate_signals(_bar_event(both_legs=True))

    signals = _drain(handler.global_queue)
    assert len(signals) == 2
    by_ticker = {s.ticker: s for s in signals}

    # D-14: every leg carries the LONG_SHORT direction.
    assert all(s.direction is TradingDirection.LONG_SHORT for s in signals)

    leg_A = by_ticker[_TICKER_A]
    leg_B = by_ticker[_TICKER_B]

    # D-08: β-weighted quantities — N on leg A, β·N on leg B.
    assert leg_A.quantity == _N, "rich leg carries N"
    assert leg_B.quantity == _BETA_N, "cheap leg carries β·N"

    # Direction-of-trade: SELL the rich leg, BUY the cheap leg.
    assert leg_A.action is Side.SELL, "rich leg is sold"
    assert leg_B.action is Side.BUY, "cheap leg is bought"

    # Both legs are MARKET entries (the _entry constructor).
    assert leg_A.order_type is OrderType.MARKET
    assert leg_B.order_type is OrderType.MARKET
