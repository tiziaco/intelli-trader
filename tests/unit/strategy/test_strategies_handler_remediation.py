"""07-09 remediation: strategy_handler live-control-plane + pair-readiness hardening.

Behavioral proofs for four in-scope Phase-7-review findings landed on
``StrategiesHandler`` (all live-only, backtest-inert):

- CR-01: a ``STRATEGY_COMMAND`` add/remove_ticker addressed to a ``PairStrategy``
  is REFUSED (loud no-op) — no ticker mutation, no follow-on ``UniversePollEvent``,
  and the next BAR's ``on_bar`` does NOT raise (the unbounded
  ErrorEvent crash-storm is gone).
- IN-02: ``on_strategy_command`` emits a ``UniversePollEvent`` ONLY when the
  tickers actually mutated; an idempotent no-op (add already-present / remove
  absent) emits nothing.
- WR-01: ``_dispatch_pair`` short-circuits (no ``update_pair`` / ``evaluate_pair``)
  when EITHER leg is not ``universe.is_ready`` — mirroring the single-leg gate.
- WR-02 producer: ``is_warm(symbol)`` aggregates per-symbol indicator warmth
  across concerned strategies (vacuously True when none are concerned).

Folder-derived ``unit`` marker only (tests/conftest.py). Respects
filterwarnings=["error"] / --strict-markers.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from queue import Queue
from typing import Any

import pandas as pd
import pytest
from uuid_utils.compat import uuid7

from itrader.core.bar import Bar
from itrader.core.enums import Side
from itrader.core.ids import PortfolioId
from itrader.core.sizing import FixedQuantity, FractionOfCash, SignalIntent, TradingDirection
from itrader.events_handler.events import (
    BarEvent,
    StrategyCommandEvent,
    UniversePollEvent,
)
from itrader.strategy_handler.pair_base import PairStrategy
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit

# Portfolio handles are ALWAYS UUIDv7-backed ``PortfolioId`` values (FL-02).
_PID = PortfolioId(uuid7())

_T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)  # midnight UTC -> 1d aligned

_TICKER_A = "ETHUSD"
_TICKER_B = "BTCUSD"
_BETA_WARMUP = 5
_Z_LOOKBACK = 3
_MAX_WINDOW = _BETA_WARMUP + _Z_LOOKBACK  # 8


def _bar(close: str = "100", *, time: datetime = _T0) -> Bar:
    px = Decimal(close)
    return Bar(time=time, open=px, high=px, low=px, close=px, volume=Decimal("1"))


class _StubFeed:
    """Minimal BarFeed stand-in — these seams never touch the feed."""

    def symbols(self) -> list[str]:
        return [_TICKER_A, _TICKER_B]


class _FakeUniverse:
    """A fake universe exposing only ``is_ready(sym) -> bool``."""

    def __init__(self, ready: bool | dict[str, bool]) -> None:
        self._ready = ready

    def is_ready(self, symbol: str) -> bool:
        if isinstance(self._ready, bool):
            return self._ready
        return self._ready.get(symbol, False)


class _SpyPair(PairStrategy):
    """A tiny pair strategy recording ``update_pair`` / ``evaluate_pair`` calls.

    Returns a fixed both-leg entry so a firing tick emits two SignalEvents; the
    behavioral proof for WR-01 is the recorded call lists (dispatch never reaches
    update_pair/evaluate_pair when a leg is not universe-ready).
    """

    name = "spy_pair"
    sizing_policy = FixedQuantity(qty=Decimal("1"))
    z_lookback = _Z_LOOKBACK
    beta_warmup = _BETA_WARMUP
    max_window = _MAX_WINDOW

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))
        self.update_pair_calls: int = 0
        self.evaluate_pair_calls: int = 0

    def update_pair(self, bar_A: Any, bar_B: Any) -> None:
        self.update_pair_calls += 1
        super().update_pair(bar_A, bar_B)

    def evaluate_pair(
        self, win_A: pd.DataFrame, win_B: pd.DataFrame
    ) -> list[SignalIntent] | None:
        self.evaluate_pair_calls += 1
        return [
            self._entry(self.tickers[0], Side.SELL, Decimal("3")),
            self._entry(self.tickers[1], Side.BUY, Decimal("6")),
        ]


class _SpyStrategy:
    """A single-leg strategy spy with a CONTROLLABLE ``is_ready``."""

    def __init__(
        self, tickers: list[str], *, name: str = "spy", ready: bool = True
    ) -> None:
        self.tickers = list(tickers)
        self.name = name
        self.timeframe = timedelta(days=1)
        self.strategy_id = "spy-id"
        self.subscribed_portfolios: list[Any] = []
        self.sizing_policy = FractionOfCash(Decimal("0.95"))
        self.direction = TradingDirection.LONG_ONLY
        self.allow_increase = False
        self.max_positions = 1
        self.sltp_policy = None
        self._ready = ready

    def update(self, ticker: str, bar: Any) -> None:
        pass

    def is_ready(self, ticker: str) -> bool:
        return self._ready

    def generate_signal(self, ticker: str) -> None:
        return None


def _handler() -> StrategiesHandler:
    return StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore())


def _pair_handler() -> StrategiesHandler:
    return StrategiesHandler(
        Queue(),
        _StubFeed(),
        InMemorySignalStore(),
        allow_short_selling=True,
        enable_margin=True,
    )


def _drain(queue: "Queue[Any]") -> list[Any]:
    out: list[Any] = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def _bar_event(*, both_legs: bool = True, day: int = 1) -> BarEvent:
    t = datetime(2020, 1, day, tzinfo=timezone.utc)
    bars = {_TICKER_A: _bar("2000", time=t)}
    if both_legs:
        bars[_TICKER_B] = _bar("40000", time=t)
    return BarEvent(time=t, bars=bars)


# --------------------------------------------------------------------------- #
# (i) CR-01 — a PairStrategy ticker mutation is refused; next BAR does not raise.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("factory", ["add_ticker", "remove_ticker"])
def test_cr01_pair_strategy_command_refused(factory: str) -> None:
    """CR-01: add/remove_ticker on a PairStrategy mutates nothing + emits no poll."""
    handler = _pair_handler()
    pair = _SpyPair(timeframe="1d", tickers=[_TICKER_A, _TICKER_B])
    handler.add_strategy(pair)
    pair.subscribe_portfolio(_PID)

    make = getattr(StrategyCommandEvent, factory)
    handler.on_strategy_command(make("spy_pair", "XRPUSD", time=_T0))

    assert pair.tickers == [_TICKER_A, _TICKER_B]  # exact-2 contract preserved
    assert len(pair.tickers) == 2
    assert _drain(handler.global_queue) == []  # refused → no follow-on poll


def test_cr01_next_bar_does_not_raise_after_refusal() -> None:
    """CR-01: after a refused pair command the next on_bar does NOT raise."""
    handler = _pair_handler()
    pair = _SpyPair(timeframe="1d", tickers=[_TICKER_A, _TICKER_B])
    handler.add_strategy(pair)
    pair.subscribe_portfolio(_PID)

    handler.on_strategy_command(
        StrategyCommandEvent.add_ticker("spy_pair", "XRPUSD", time=_T0)
    )

    # The crash-storm scenario: a mutated pair (3 tickers) would make
    # _dispatch_pair's tuple-unpack raise every BAR. The guard kept it at 2, so
    # this drives cleanly (no exception).
    handler.on_bar(_bar_event(both_legs=True, day=1))  # must not raise


# --------------------------------------------------------------------------- #
# (ii) IN-02 — poll emitted only on a genuine mutation.
# --------------------------------------------------------------------------- #


def test_in02_noop_add_emits_nothing() -> None:
    handler = _handler()
    handler.strategies.append(_SpyStrategy(["BTCUSDT"], name="s1"))

    handler.on_strategy_command(
        StrategyCommandEvent.add_ticker("s1", "BTCUSDT", time=_T0)
    )

    assert _drain(handler.global_queue) == []


def test_in02_noop_remove_emits_nothing() -> None:
    handler = _handler()
    handler.strategies.append(_SpyStrategy(["BTCUSDT", "ETHUSDT"], name="s1"))

    handler.on_strategy_command(
        StrategyCommandEvent.remove_ticker("s1", "XRPUSDT", time=_T0)
    )

    assert _drain(handler.global_queue) == []


def test_in02_genuine_add_emits_one() -> None:
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.add_ticker("s1", "ETHUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT", "ETHUSDT"]
    emitted = _drain(handler.global_queue)
    assert len(emitted) == 1 and isinstance(emitted[0], UniversePollEvent)


def test_in02_genuine_remove_emits_one() -> None:
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT", "ETHUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.remove_ticker("s1", "ETHUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT"]
    emitted = _drain(handler.global_queue)
    assert len(emitted) == 1 and isinstance(emitted[0], UniversePollEvent)


# --------------------------------------------------------------------------- #
# (iii) WR-01 — the per-leg readiness gate short-circuits _dispatch_pair.
# --------------------------------------------------------------------------- #


def test_wr01_pending_leg_skips_pair_dispatch() -> None:
    """One leg PENDING: update_pair/evaluate_pair never run, no signal emitted."""
    handler = _pair_handler()
    pair = _SpyPair(timeframe="1d", tickers=[_TICKER_A, _TICKER_B])
    handler.add_strategy(pair)
    pair.subscribe_portfolio(_PID)
    handler.set_universe(_FakeUniverse({_TICKER_A: True, _TICKER_B: False}))

    handler.on_bar(_bar_event(both_legs=True, day=1))

    assert pair.update_pair_calls == 0  # gate short-circuits BEFORE update_pair
    assert pair.evaluate_pair_calls == 0
    assert _drain(handler.global_queue) == []  # no signal


def test_wr01_both_ready_pair_evaluates() -> None:
    """Both legs READY: the pair warms to ready then evaluates and emits."""
    handler = _pair_handler()
    pair = _SpyPair(timeframe="1d", tickers=[_TICKER_A, _TICKER_B])
    handler.add_strategy(pair)
    pair.subscribe_portfolio(_PID)
    handler.set_universe(_FakeUniverse(True))

    # Prime the pair buffers to one-below-ready, draining each tick.
    for d in range(1, _MAX_WINDOW):
        handler.on_bar(_bar_event(both_legs=True, day=d))
    _drain(handler.global_queue)

    handler.on_bar(_bar_event(both_legs=True, day=_MAX_WINDOW))

    assert pair.evaluate_pair_calls >= 1
    signals = _drain(handler.global_queue)
    assert len(signals) == 2
    assert {s.ticker for s in signals} == {_TICKER_A, _TICKER_B}


# --------------------------------------------------------------------------- #
# (iv) is_warm — the WR-02 producer aggregate.
# --------------------------------------------------------------------------- #


def test_is_warm_false_when_a_concerned_strategy_not_ready() -> None:
    handler = _handler()
    handler.strategies.append(_SpyStrategy(["BTCUSDT"], name="a", ready=False))
    handler.strategies.append(_SpyStrategy(["BTCUSDT"], name="b", ready=True))

    assert handler.is_warm("BTCUSDT") is False


def test_is_warm_true_when_all_concerned_ready() -> None:
    handler = _handler()
    handler.strategies.append(_SpyStrategy(["BTCUSDT"], name="a", ready=True))
    handler.strategies.append(_SpyStrategy(["BTCUSDT", "ETHUSDT"], name="b", ready=True))

    assert handler.is_warm("BTCUSDT") is True


def test_is_warm_vacuously_true_when_no_strategy_concerned() -> None:
    handler = _handler()
    handler.strategies.append(_SpyStrategy(["ETHUSDT"], name="a", ready=False))

    # No strategy has BTCUSDT in its tickers → vacuously warm.
    assert handler.is_warm("BTCUSDT") is True
