"""UniverseHandler Level-2 retry policy — cadence gate + 3-strike warn (07-10 Task 4).

Once warmup re-delivery is idempotent (07-10 Tasks 2-3), the CR-02 FAILED-retry can no
longer corrupt state — so the retry policy is pure hygiene/observability (CR-01-retry,
Level 2):

- CADENCE GATE (``on_poll``): a FAILED still-desired symbol is not re-warmed more than
  once per bar interval (no new venue data closes before then). A symbol with no recorded
  prior attempt is retried immediately; a symbol retried < one interval ago is SKIPPED.
- 3-STRIKE WARN: three consecutive failed re-warms (``on_bars_load_failed`` and/or the
  WR-02 warm-verify MISS) emit a warning naming the symbol + streak; a re-warm success
  RESETS the streak. The symbol is NEVER auto-dropped / removed / quarantined (Level 3 is
  explicitly OUT).

Offline / socket-free; mirrors the ``test_universe_poll`` / ``test_universe_warmup_consumers``
stubs. 4-SPACE indentation. Warn-capture REQUIRES ``poetry run pytest``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from queue import Empty, Queue

import pytest

from itrader.core.bar import Bar
from itrader.core.instrument import Instrument
from itrader.events_handler.events import BarsLoaded, BarsLoadFailed, UniversePollEvent
from itrader.events_handler.events.universe import UniverseUpdateEvent
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig

pytestmark = pytest.mark.unit

_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)
_ONE_DAY = timedelta(days=1)


# --- fakes -----------------------------------------------------------------


class _FakeSelectionSource:
    def __init__(self, desired: set[str]) -> None:
        self._desired = desired

    def select(self, asof: datetime) -> set[str]:
        return set(self._desired)


class _RecordingFeed:
    """Records ``absorb_warmup`` calls; satisfies the _SupportsWarmup seam."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def warmup(self, symbol: str, timeframe: str, depth: int | None = None) -> None:
        self._log.append(("warmup", symbol))

    def absorb_warmup(self, symbol: str, timeframe: str, bars: object) -> None:
        self._log.append(("absorb", symbol))

    def cache_capacity(self) -> int:
        return 100


# --- helpers ---------------------------------------------------------------


def _inst(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"),
    )


def _universe(*symbols: str) -> Universe:
    members = sorted(symbols)
    return Universe(members=members, instrument_map={s: _inst(s) for s in members})


def _handler(universe: Universe, *, feed: object | None = None) -> UniverseHandler:
    return UniverseHandler(
        bus=Queue(),
        universe=universe,
        feed=feed if feed is not None else _RecordingFeed([]),
        config=UniverseHandlerConfig(poll_timeframe="1d"),
    )


def _bar() -> Bar:
    return Bar(
        time=_ASOF,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )


def _drain_one(q: "Queue[object]") -> object:
    event = q.get_nowait()
    with pytest.raises(Empty):
        q.get_nowait()
    return event


def _streak_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if "failed re-warm" in rec.getMessage()
    ]


# --- (i) CADENCE gate ------------------------------------------------------


def test_failed_symbol_not_rewarmed_within_one_interval() -> None:
    """A FAILED symbol is retried on the first poll, SKIPPED < one interval later, then
    retried again once event.time has advanced >= the bar interval."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH added, PENDING
    universe.mark_failed("ETH/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))

    # Poll 1 @ t0: no prior attempt -> retried immediately.
    handler.on_poll(UniversePollEvent(time=_ASOF))
    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    # mark_pending flipped it; simulate the re-warm failing again before the next poll.
    universe.mark_failed("ETH/USDC")

    # Poll 2 @ t0 + 1h (< one 1d interval): cadence gate SKIPS the re-warm.
    handler.on_poll(UniversePollEvent(time=_ASOF + timedelta(hours=1)))
    assert handler._bus.empty()  # nothing re-driven
    assert universe.failed_symbols() == {"ETH/USDC"}  # still FAILED, not re-pended

    # Poll 3 @ t0 + 1 day (>= interval): retried again.
    handler.on_poll(UniversePollEvent(time=_ASOF + _ONE_DAY))
    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)


def test_first_retry_allowed_immediately_no_prior_attempt() -> None:
    """A FAILED symbol with no recorded prior re-warm passes the cadence gate at once."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    universe.mark_failed("ETH/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))

    handler.on_poll(UniversePollEvent(time=_ASOF))

    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)


# --- (ii) 3-STRIKE warn ----------------------------------------------------


def test_third_consecutive_failure_warns(caplog: pytest.LogCaptureFixture) -> None:
    """The 3rd consecutive failed re-warm emits exactly one streak warning."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    handler = _handler(universe)

    with caplog.at_level("WARNING"):
        for _ in range(3):
            handler.on_bars_load_failed(
                BarsLoadFailed(time=_ASOF, symbol="ETH/USDC", reason="MissingPriceDataError")
            )

    warnings = _streak_warnings(caplog)
    assert len(warnings) == 1  # only at the 3rd
    assert "ETH/USDC" in warnings[0]
    assert "3 times" in warnings[0]


def test_warm_verify_miss_counts_toward_streak(caplog: pytest.LogCaptureFixture) -> None:
    """A WR-02 warm-verify MISS is a failed re-warm too — mixing both sites still trips at 3."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    handler = _handler(universe)

    class _AlwaysCold:
        def is_warm(self, symbol: str) -> bool:
            return False

    handler.set_strategy_warmth(_AlwaysCold())

    with caplog.at_level("WARNING"):
        for _ in range(3):
            handler.on_bars_loaded(
                BarsLoaded(time=_ASOF, symbol="ETH/USDC", timeframe="1d", bars=(_bar(),))
            )

    assert len(_streak_warnings(caplog)) == 1  # 3rd MISS warns


def test_success_resets_streak(caplog: pytest.LogCaptureFixture) -> None:
    """A re-warm success resets the streak: a subsequent single failure does NOT warn."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    handler = _handler(universe)  # no warmth wired -> on_bars_loaded marks ready

    with caplog.at_level("WARNING"):
        # Two failures (streak 2, no warn yet).
        for _ in range(2):
            handler.on_bars_load_failed(
                BarsLoadFailed(time=_ASOF, symbol="ETH/USDC", reason="Boom")
            )
        # A genuine re-warm success -> resets the streak.
        handler.on_bars_loaded(
            BarsLoaded(time=_ASOF, symbol="ETH/USDC", timeframe="1d", bars=(_bar(),))
        )
        assert universe.is_ready("ETH/USDC")
        # Two more failures — streak restarts at 1, 2: still below the 3-strike threshold.
        for _ in range(2):
            handler.on_bars_load_failed(
                BarsLoadFailed(time=_ASOF, symbol="ETH/USDC", reason="Boom")
            )

    assert _streak_warnings(caplog) == []  # never reached 3 consecutively


# --- (iii) NEVER auto-drop -------------------------------------------------


def test_never_auto_drops_after_many_failures() -> None:
    """After N failures the symbol is STILL a member with a live record — never dropped."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    handler = _handler(universe)

    for _ in range(5):
        handler.on_bars_load_failed(
            BarsLoadFailed(time=_ASOF, symbol="ETH/USDC", reason="Boom")
        )

    assert "ETH/USDC" in universe.members  # never removed from membership
    assert universe.instrument("ETH/USDC").symbol == "ETH/USDC"  # record survives
    assert universe.failed_symbols() == {"ETH/USDC"}  # dark, but retryable
