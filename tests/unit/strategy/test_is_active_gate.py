"""D-07 — the ``is_active`` gate on ``StrategiesHandler.on_bar``.

``Strategy.is_active`` (base.py:193, defaults True) was an INERT flag before P10:
``activate_strategy``/``deactivate_strategy`` flipped it and nothing read it. P10
wires it into the per-tick loop so Plan 06's enable/disable command has something
to gate.

The contract locked here:

- an inactive strategy emits NOTHING (single-leg AND pair — D-16: a pair is a full
  registry instance and uses the same gate);
- an ACTIVE sibling in the same ``self.strategies`` list is unaffected;
- a disabled strategy STAYS in ``self.strategies`` and STAYS warm — re-enabling
  trades the NEXT bar with no re-warmup (removing it on disable would cost a full
  100-bar re-warm);
- ``is_active`` defaults True, so the guard is inert unless something explicitly
  deactivates — which is why the backtest oracle stays byte-exact.

Module-local stubs (no concrete reference strategy) so the gate is exercised in
isolation. 4-space indented, matching ``test_pair_dispatch.py``. Folder-derived
``unit`` marker (do NOT hand-apply).
"""

from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import Side
from itrader.core.sizing import FixedQuantity, FractionOfCash, SignalIntent, TradingDirection
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.pair_base import PairStrategy
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit

_TICKER = "BTCUSD"
_TICKER_B = "ETHUSD"

# The SMA window used by the "stays warm" strategy — small so the test warms in
# a handful of bars rather than 100.
_SMA_WINDOW = 3


class _AlwaysBuyStrategy(Strategy):
    """Handle-free single-leg strategy: always ready, fires a MARKET BUY every tick.

    Handle-free => ``is_ready`` is unconditionally True (base.py:588), so any
    absence of a signal in these tests is attributable to the ``is_active`` gate
    and nothing else.
    """

    name = "always_buy"
    sizing_policy = FractionOfCash(Decimal("0.95"))
    direction = TradingDirection.LONG_ONLY

    def init(self) -> None:
        return None

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return self.buy(ticker)


class _WarmSMAStrategy(Strategy):
    """Single-leg strategy gated on a real SMA handle — used by the warmth test.

    Unlike ``_AlwaysBuyStrategy`` this one is NOT ready until the SMA handle has
    seen ``_SMA_WINDOW`` bars, so it can prove that a disable/re-enable cycle pays
    no re-warmup.
    """

    name = "warm_sma"
    sizing_policy = FractionOfCash(Decimal("0.95"))
    direction = TradingDirection.LONG_ONLY
    short_window: int = _SMA_WINDOW

    def init(self) -> None:
        self.sma = self.indicator(SMA, "close", self.short_window)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return self.buy(ticker)


class _StubPair(PairStrategy):
    """Minimal two-leg pair returning a fixed entry pair once its buffers fill."""

    name = "stub_pair"
    sizing_policy = FixedQuantity(qty=Decimal("1"))
    z_lookback = 2
    beta_warmup = 2
    max_window = 4

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def evaluate_pair(
        self, win_A: pd.DataFrame, win_B: pd.DataFrame
    ) -> list[SignalIntent] | None:
        return [
            self._entry(self.tickers[0], Side.SELL, Decimal("1")),
            self._entry(self.tickers[1], Side.BUY, Decimal("1")),
        ]


class _StubFeed:
    """Minimal ``BarFeed`` stand-in — the tested paths never slice a window."""

    def symbols(self) -> list[str]:
        return [_TICKER, _TICKER_B]

    def window(self, ticker, timeframe, max_window, asof):  # type: ignore[no-untyped-def]
        n = 8
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


def _bar(price: float, day: int) -> Bar:
    return Bar(
        time=datetime(2020, 1, day, tzinfo=timezone.utc),
        open=Decimal(str(price)),
        high=Decimal(str(price)),
        low=Decimal(str(price)),
        close=Decimal(str(price)),
        volume=Decimal("1"),
    )


def _bar_event(day: int, *, tickers: tuple[str, ...] = (_TICKER,)) -> BarEvent:
    """A bar event on the 1d grid (every calendar day is on-grid for `1d`)."""
    return BarEvent(
        time=datetime(2020, 1, day, tzinfo=timezone.utc),
        bars={t: _bar(100.0 + day, day) for t in tickers},
    )


def _drain(queue: "Queue") -> list[SignalEvent]:  # type: ignore[type-arg]
    events: list[SignalEvent] = []
    while not queue.empty():
        events.append(queue.get())
    return events


def _make_handler(**kwargs: object) -> StrategiesHandler:
    return StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore(), **kwargs)  # type: ignore[arg-type]


def _add(handler: StrategiesHandler, strategy: Strategy) -> Strategy:
    handler.add_strategy(strategy)
    strategy.subscribe_portfolio(1)
    return strategy


# --- Test 1: an inactive strategy emits nothing ------------------------------


def test_inactive_strategy_emits_no_signal() -> None:
    """D-07: is_active False -> the strategy is skipped, nothing is enqueued."""
    handler = _make_handler()
    strategy = _add(handler, _AlwaysBuyStrategy(timeframe="1d", tickers=[_TICKER]))
    strategy.deactivate_strategy()

    handler.on_bar(_bar_event(day=8))

    assert _drain(handler.global_queue) == [], (
        "an inactive strategy must emit no signals on an on-grid bar")


# --- Test 2: an active sibling is unaffected ---------------------------------


def test_active_sibling_unaffected_by_inactive_peer() -> None:
    """D-07: the guard skips ONLY the inactive strategy — the loop continues."""
    handler = _make_handler()
    inactive = _AlwaysBuyStrategy(timeframe="1d", tickers=[_TICKER])
    active = _AlwaysBuyStrategy(timeframe="1d", tickers=[_TICKER])
    # D-02: `name` is the durable per-instance identity and `add_strategy` rejects a
    # duplicate, so two instances of one class must be named distinctly (the class pins a
    # single default name). Registering them as siblings is the point of this test.
    inactive.name = "always_buy_inactive"
    active.name = "always_buy_active"
    inactive = _add(handler, inactive)
    active = _add(handler, active)
    inactive.deactivate_strategy()

    handler.on_bar(_bar_event(day=8))

    signals = _drain(handler.global_queue)
    assert len(signals) == 1, "exactly the active sibling emits"
    assert signals[0].strategy_id == active.strategy_id, (
        "the emitted signal belongs to the ACTIVE strategy")


# --- Test 3: a disabled strategy stays warm ----------------------------------


def test_disabled_strategy_stays_warm_and_trades_on_re_enable() -> None:
    """D-07: disable keeps the object in ``self.strategies`` with its warmth intact,
    so re-enabling trades the NEXT bar — no re-warmup is paid.

    Warm the SMA while active, disable across several bars, then re-enable and
    drive ONE on-grid bar: the signal fires immediately. A handler that dropped
    the strategy (or reset it) on disable would need ``_SMA_WINDOW`` fresh bars
    before firing again.
    """
    handler = _make_handler()
    strategy = _add(handler, _WarmSMAStrategy(timeframe="1d", tickers=[_TICKER]))

    # Warm the SMA handle while ACTIVE.
    for day in range(1, _SMA_WINDOW + 1):
        handler.on_bar(_bar_event(day=day))
    _drain(handler.global_queue)
    assert strategy.is_ready(_TICKER), "precondition: the SMA warmed while active"

    # Disable and drive several bars — nothing emits.
    strategy.deactivate_strategy()
    for day in range(_SMA_WINDOW + 1, _SMA_WINDOW + 6):
        handler.on_bar(_bar_event(day=day))
    assert _drain(handler.global_queue) == [], "a disabled strategy emits nothing"

    # The object was never removed from the registry.
    assert strategy in handler.strategies, (
        "D-07: disable must NOT remove the strategy from self.strategies")
    assert strategy.is_ready(_TICKER), "D-07: warmth survives the disabled window"

    # Re-enable and drive ONE bar — it trades immediately, no re-warmup.
    strategy.activate_strategy()
    handler.on_bar(_bar_event(day=_SMA_WINDOW + 6))

    signals = _drain(handler.global_queue)
    assert len(signals) == 1, (
        "re-enabling must trade on the NEXT bar with no re-warmup")


# --- Test 4: the flag defaults True (the guard is inert) ---------------------


def test_is_active_defaults_true() -> None:
    """D-07: a freshly constructed strategy is active, so the guard never fires
    unless something explicitly deactivates — this is why the backtest oracle is
    byte-exact (no backtest path calls deactivate_strategy)."""
    strategy = _AlwaysBuyStrategy(timeframe="1d", tickers=[_TICKER])
    assert strategy.is_active is True, "is_active defaults True"

    handler = _make_handler()
    _add(handler, strategy)
    handler.on_bar(_bar_event(day=8))

    assert len(_drain(handler.global_queue)) == 1, (
        "a default-constructed strategy trades — the guard is inert")


# --- Test 5: the gate covers pairs too (D-16) --------------------------------


def test_inactive_pair_strategy_is_skipped() -> None:
    """D-16: the guard precedes the ``_dispatch_pair`` branch, so an inactive pair
    is skipped exactly like any other instance."""
    handler = _make_handler(allow_short_selling=True, enable_margin=True)
    pair = _StubPair(timeframe="1d", tickers=[_TICKER, _TICKER_B])
    _add(handler, pair)

    # Prime the pair's buffers to ready while ACTIVE, draining as we go.
    for day in range(1, pair.max_window + 2):
        handler.on_bar(_bar_event(day=day, tickers=(_TICKER, _TICKER_B)))
    assert _drain(handler.global_queue), "precondition: the active pair emits"

    pair.deactivate_strategy()
    handler.on_bar(
        _bar_event(day=pair.max_window + 2, tickers=(_TICKER, _TICKER_B)))

    assert _drain(handler.global_queue) == [], (
        "D-16: an inactive PairStrategy emits nothing — the guard precedes "
        "the _dispatch_pair branch")
