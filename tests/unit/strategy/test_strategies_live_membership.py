"""WR-02 readiness gate + live warmup/command seams on StrategiesHandler (Plan 07-04).

Three live-only seams composed onto ``StrategiesHandler`` (D-01/D-03/D-11), each a
no-op / absent on the backtest oracle path:

1. ``calculate_signals``: a defensive ``universe.is_ready(sym)`` gate composed
   BEFORE the existing ``strategy.is_ready`` indicator-warmth gate — warm the
   indicator (``update`` runs) but do NOT trade while a symbol is PENDING/FAILED.
   None-guarded and O(1), so with no universe wired the oracle is byte-exact.
2. ``on_bars_loaded``: warm concerned strategies from a ``BarsLoaded`` payload via
   the identical ``strategy.update`` path, NO ``generate_signal`` (warmup, not
   trading).
3. ``on_strategy_command``: mutate ``strategy.tickers`` then EMIT a
   ``UniversePollEvent`` follow-on (queue-only; never call ``UniverseHandler``).

Folder-derived ``unit`` marker only (tests/conftest.py applies it).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from queue import Queue
from typing import Any

import pytest

from itrader.core.bar import Bar
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.events_handler.events import (
    BarEvent,
    BarsLoaded,
    StrategyCommandEvent,
    UniversePollEvent,
)
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit

_T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)  # midnight UTC -> 1d aligned


def _bar(close: str = "100", *, time: datetime = _T0) -> Bar:
    px = Decimal(close)
    return Bar(time=time, open=px, high=px, low=px, close=px, volume=Decimal("1"))


class _StubFeed:
    """Minimal BarFeed stand-in — these seams never touch the feed."""

    def symbols(self) -> list[str]:
        return ["BTCUSDT"]


class _FakeUniverse:
    """A fake universe exposing only the ``is_ready(sym) -> bool`` gate surface."""

    def __init__(self, ready: bool | dict[str, bool]) -> None:
        self._ready = ready

    def is_ready(self, symbol: str) -> bool:
        if isinstance(self._ready, bool):
            return self._ready
        return self._ready.get(symbol, False)


class _SpyStrategy:
    """A single-leg strategy spy recording ``update`` / ``generate_signal`` calls.

    Carries only the surface ``calculate_signals`` / ``on_bars_loaded`` /
    ``on_strategy_command`` read (NOT a PairStrategy, so the pair branch is
    skipped). ``generate_signal`` returns ``None`` so nothing is emitted — the
    behavioral proof is the recorded call lists, not queue traffic.
    """

    def __init__(self, tickers: list[str], name: str = "spy") -> None:
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
        self.update_calls: list[tuple[str, Any]] = []
        self.generate_calls: list[str] = []

    def update(self, ticker: str, bar: Any) -> None:
        self.update_calls.append((ticker, bar))

    def is_ready(self, ticker: str) -> bool:
        return True

    def generate_signal(self, ticker: str) -> None:
        self.generate_calls.append(ticker)
        return None


def _handler() -> StrategiesHandler:
    return StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore())


# --------------------------------------------------------------------------- #
# Task 1 — the defensive readiness gate in calculate_signals + set_universe.
# --------------------------------------------------------------------------- #


def test_no_universe_wired_fires_as_today() -> None:
    """No universe: the indicator gate alone runs, generate_signal fires (oracle path)."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"])
    handler.strategies.append(spy)

    handler.calculate_signals(BarEvent(time=_T0, bars={"BTCUSDT": _bar()}))

    assert spy.update_calls == [("BTCUSDT", spy.update_calls[0][1])]
    assert spy.generate_calls == ["BTCUSDT"]


def test_universe_ready_fires_like_no_universe() -> None:
    """A READY symbol: identical to no-universe — update AND generate_signal run."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"])
    handler.strategies.append(spy)
    handler.set_universe(_FakeUniverse(True))

    handler.calculate_signals(BarEvent(time=_T0, bars={"BTCUSDT": _bar()}))

    assert len(spy.update_calls) == 1
    assert spy.generate_calls == ["BTCUSDT"]


def test_universe_pending_warms_but_does_not_trade() -> None:
    """A PENDING/FAILED symbol: strategy.update STILL runs (warm) but generate_signal is skipped."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"])
    handler.strategies.append(spy)
    handler.set_universe(_FakeUniverse(False))

    handler.calculate_signals(BarEvent(time=_T0, bars={"BTCUSDT": _bar()}))

    assert len(spy.update_calls) == 1  # warmed
    assert spy.generate_calls == []  # NOT traded


def test_universe_gate_is_per_symbol() -> None:
    """The gate is per-symbol: a READY ticker fires while a PENDING one only warms."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT", "ETHUSDT"])
    handler.strategies.append(spy)
    handler.set_universe(_FakeUniverse({"BTCUSDT": True, "ETHUSDT": False}))

    handler.calculate_signals(
        BarEvent(time=_T0, bars={"BTCUSDT": _bar(), "ETHUSDT": _bar("50")})
    )

    assert {t for t, _ in spy.update_calls} == {"BTCUSDT", "ETHUSDT"}  # both warmed
    assert spy.generate_calls == ["BTCUSDT"]  # only the READY one traded


def test_set_universe_defaults_none() -> None:
    """set_universe is the only wiring point — the field defaults None (inert)."""
    handler = _handler()
    assert handler._universe is None
    fake = _FakeUniverse(True)
    handler.set_universe(fake)
    assert handler._universe is fake


# --------------------------------------------------------------------------- #
# Task 2 — on_bars_loaded warms concerned strategies (no signals).
# --------------------------------------------------------------------------- #


def test_on_bars_loaded_warms_concerned_strategy_in_order() -> None:
    """A concerned strategy receives K in-order update calls, no signals, queue empty."""
    queue: "Queue[Any]" = Queue()
    handler = StrategiesHandler(queue, _StubFeed(), InMemorySignalStore())
    spy = _SpyStrategy(["BTCUSDT"])
    handler.strategies.append(spy)

    bars = tuple(_bar(str(100 + i)) for i in range(4))  # K = 4
    handler.on_bars_loaded(
        BarsLoaded(time=_T0, symbol="BTCUSDT", timeframe="1d", bars=bars)
    )

    assert [t for t, _ in spy.update_calls] == ["BTCUSDT"] * 4
    assert [b for _, b in spy.update_calls] == list(bars)  # in-order
    assert spy.generate_calls == []  # warmup only — no signals
    assert queue.empty()  # nothing emitted


def test_on_bars_loaded_skips_non_concerned_strategy() -> None:
    """A strategy whose .tickers exclude the symbol receives zero updates."""
    handler = _handler()
    concerned = _SpyStrategy(["BTCUSDT"], name="concerned")
    other = _SpyStrategy(["ETHUSDT"], name="other")
    handler.strategies.extend([concerned, other])

    bars = tuple(_bar(str(100 + i)) for i in range(3))
    handler.on_bars_loaded(
        BarsLoaded(time=_T0, symbol="BTCUSDT", timeframe="1d", bars=bars)
    )

    assert len(concerned.update_calls) == 3
    assert other.update_calls == []


# --------------------------------------------------------------------------- #
# Task 3 — on_strategy_command mutates tickers + emits UniversePollEvent.
# --------------------------------------------------------------------------- #


def _drain(queue: "Queue[Any]") -> list[Any]:
    out: list[Any] = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def test_add_ticker_appends_and_emits_poll() -> None:
    """add_ticker for a known strategy appends the symbol and emits one UniversePollEvent."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.add_ticker("s1", "ETHUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT", "ETHUSDT"]
    emitted = _drain(handler.global_queue)
    assert len(emitted) == 1 and isinstance(emitted[0], UniversePollEvent)
    assert emitted[0].time == _T0


def test_add_ticker_idempotent() -> None:
    """add_ticker of an already-present symbol does not duplicate; still emits once."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.add_ticker("s1", "BTCUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT"]  # no duplicate
    emitted = _drain(handler.global_queue)
    assert len(emitted) == 1 and isinstance(emitted[0], UniversePollEvent)


def test_remove_ticker_removes_and_emits_poll() -> None:
    """remove_ticker removes the symbol and emits one UniversePollEvent."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT", "ETHUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.remove_ticker("s1", "ETHUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT"]
    emitted = _drain(handler.global_queue)
    assert len(emitted) == 1 and isinstance(emitted[0], UniversePollEvent)


def test_remove_ticker_idempotent_absent() -> None:
    """remove_ticker of an absent symbol (list stays non-empty) is a no-op mutation; emits once."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT", "ETHUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.remove_ticker("s1", "XRPUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT", "ETHUSDT"]  # unchanged
    emitted = _drain(handler.global_queue)
    assert len(emitted) == 1 and isinstance(emitted[0], UniversePollEvent)


def test_remove_ticker_refuses_emptying() -> None:
    """A remove that would empty .tickers is refused: list unchanged, no event (documented no-op)."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.remove_ticker("s1", "BTCUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT"]  # invariant preserved (non-empty)
    assert _drain(handler.global_queue) == []  # refused → no poll


def test_unknown_strategy_name_is_noop() -> None:
    """An unknown strategy_name mutates nothing and emits nothing."""
    handler = _handler()
    spy = _SpyStrategy(["BTCUSDT"], name="s1")
    handler.strategies.append(spy)

    handler.on_strategy_command(
        StrategyCommandEvent.add_ticker("nope", "ETHUSDT", time=_T0)
    )

    assert spy.tickers == ["BTCUSDT"]
    assert _drain(handler.global_queue) == []
