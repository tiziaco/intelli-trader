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
from itrader.events_handler.events import (
    BarEvent,
    SignalEvent,
    StrategyCommandEvent,
)
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


# ---------------------------------------------------------------------------
# The VERB-SCOPED pair guard (D-16 / D-17 / CR-01)
# ---------------------------------------------------------------------------
#
# The v1.7 guard refused EVERY StrategyCommandEvent verb for a PairStrategy. That is
# BROADER than D-16 permits: D-16 requires pairs to add/remove/enable/disable/subscribe
# and rehydrate as FULL registry instances. A blanket refusal silently guts pair
# durability while LOOKING like a conservative safety measure — a refusal that is too
# broad is as much a defect as one that is too narrow. The guard is now scoped to
# exactly `reconfigure` (D-17) + the two ticker verbs (CR-01).


def _pair_command(verb: str, **kwargs: object) -> StrategyCommandEvent:
    return getattr(StrategyCommandEvent, verb)(
        strategy_name="stub_pair", time=datetime(2020, 1, 8, tzinfo=timezone.utc),
        **kwargs)


@pytest.mark.parametrize("verb, kwargs, check", [
    ("enable", {}, lambda s: s.is_active is True),
    ("disable", {}, lambda s: s.is_active is False),
    ("subscribe_portfolio", {"portfolio_id": "p9"},
     lambda s: "p9" in s.subscribed_portfolios),
])
def test_pair_accepts_the_lifecycle_verbs(verb, kwargs, check) -> None:  # type: ignore[no-untyped-def]
    """D-16: a pair IS a full registry instance — the lifecycle verbs apply to it.

    This is the test that catches a blanket guard silently gutting D-16.
    """
    handler = _make_handler()
    strategy = _make_subscribed_pair(handler)
    if verb == "enable":
        strategy.deactivate_strategy()

    handler.on_strategy_command(_pair_command(verb, **kwargs))

    assert check(strategy)


def test_pair_accepts_unsubscribe_portfolio() -> None:
    """D-16: the symmetric fan-out arm applies to a pair too."""
    handler = _make_handler()
    strategy = _make_subscribed_pair(handler)
    handler.on_strategy_command(
        _pair_command("subscribe_portfolio", portfolio_id="p9"))

    handler.on_strategy_command(
        _pair_command("unsubscribe_portfolio", portfolio_id="p9"))

    assert "p9" not in strategy.subscribed_portfolios


def test_pair_refuses_reconfigure() -> None:
    """D-17: ALL pair reconfiguration is refused in P10 — a loud, documented no-op.

    Not a taste call. ``pair_base._entry`` sets NO stop_loss/take_profit, so an open
    spread has NO resting exchange bracket and its ONLY exit is ``evaluate_pair()``,
    gated on ``is_pair_ready()``. ``_run_init`` unconditionally blanks ``_buf_A``/
    ``_buf_B``/``_pair_bar_count`` and ``reconfigure()`` ALWAYS calls ``_run_init()``.
    So reconfiguring a pair holding an open spread strands an unhedged, bracket-less
    spread with no reachable exit for ``beta_warmup + z_lookback`` bars.
    """
    handler = _make_handler()
    strategy = _make_subscribed_pair(handler)
    before = strategy.entry_z

    handler.on_strategy_command(
        _pair_command("reconfigure", config={"entry_z": "3"}))

    assert strategy.entry_z == before, "no param may change"
    assert _drain(handler.global_queue) == [], "no follow-on on a refusal"


def test_pair_refuses_the_ticker_verbs() -> None:
    """CR-01: the exact-2-ticker contract keeps the v1.7 ticker refusal intact.

    Mutating a pair's tickers would break ``_dispatch_pair``'s len-2 guard and make
    EVERY subsequent BAR raise — an unbounded self-inflicted ErrorEvent storm.
    """
    handler = _make_handler()
    strategy = _make_subscribed_pair(handler)

    handler.on_strategy_command(_pair_command("add_ticker", symbol="SOLUSD"))
    handler.on_strategy_command(_pair_command("remove_ticker", symbol=_TICKER_B))

    assert strategy.tickers == [_TICKER_A, _TICKER_B], "the pair contract is immutable"
    assert _drain(handler.global_queue) == []


def test_pair_enable_re_warms_the_spread_not_just_the_handles() -> None:
    """WD-1 + WD-2's pair arm: a re-enabled pair must NOT trade on a cold β.

    A pair is handle-free, so ``is_ready`` is vacuously True and a handles-only unwarm
    would leave it reporting warm INSTANTLY while ``_buf_A``/``_buf_B`` still held
    pre-disable closes — re-entering the spread on a β fit across a discontinuity.
    """
    handler = _make_handler()
    strategy = _make_subscribed_pair(handler)
    _warm_to_ready(handler)
    handler.calculate_signals(_bar_event(both_legs=True, day=_MAX_WINDOW))
    _drain(handler.global_queue)
    assert strategy.is_pair_ready() is True

    handler.on_strategy_command(_pair_command("disable"))
    handler.on_strategy_command(_pair_command("enable"))

    assert strategy.is_pair_ready() is False
    # And it stays dark on the next tick rather than firing from the stale spread.
    handler.calculate_signals(_bar_event(both_legs=True, day=_MAX_WINDOW + 1))
    assert _drain(handler.global_queue) == []
