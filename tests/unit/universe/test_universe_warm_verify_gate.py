"""07-09 remediation: UniverseHandler warm-verify readiness gate + IN-01 log reword.

WR-02: ``on_bars_loaded`` re-verifies the injected strategy-warmth read-model
(``is_warm``) AFTER the ring absorb and BEFORE flipping the symbol READY. A
warm-check MISS marks the symbol FAILED (skip BOTH mark_ready and subscribe) so a
partially-warmed symbol is never tradeable and is re-warmed on the next poll
(composes with the CR-02 FAILED-retry). No warmth wired (paper/backtest) leaves
the original absorb -> mark_ready -> subscribe path unchanged (inert).

IN-01: the force-close removal log no longer implies teardown already completed.

Mirrors ``test_universe_warmup_consumers.py`` (stub feed/provider/universe) with a
stub warmth read-model. Folder-derived ``unit`` marker; respects
filterwarnings=["error"].
"""

from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any

import pytest

from itrader.core.enums import PositionSide, Readiness
from itrader.core.instrument import Instrument
from itrader.core.bar import Bar
from itrader.core.portfolio_read_model import PositionView
from itrader.events_handler.events import BarsLoaded
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler

pytestmark = pytest.mark.unit

_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)


# --- fakes -----------------------------------------------------------------


class _WarmupFeed:
    """Records absorb/warmup calls into a shared ordered log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def warmup(self, symbol: str, timeframe: str, depth: int | None = None) -> None:
        self._log.append(("warmup", symbol))

    def absorb_warmup(
        self, symbol: str, timeframe: str, bars: tuple[Bar, ...]
    ) -> None:
        self._log.append(("absorb", symbol))

    def cache_capacity(self) -> int:
        return 100


class _WarmupProvider:
    """Records subscribe/unsubscribe into a shared ordered log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        self._log.append(("spawn", symbol))

    def subscribe(self, symbol: str) -> None:
        self._log.append(("subscribe", symbol))

    def unsubscribe(self, symbol: str) -> None:
        self._log.append(("unsubscribe", symbol))


class _SpyUniverse(Universe):
    """Logs readiness mutations into a shared ordered log."""

    def __init__(self, log: list[tuple[str, str]], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._log = log

    def mark_ready(self, symbol: str) -> None:
        self._log.append(("mark_ready", symbol))
        super().mark_ready(symbol)

    def mark_failed(self, symbol: str) -> None:
        self._log.append(("mark_failed", symbol))
        super().mark_failed(symbol)


class _FakeWarmth:
    """A stub strategy-warmth read-model (``is_warm(symbol) -> bool``)."""

    def __init__(self, warm: bool | dict[str, bool]) -> None:
        self._warm = warm

    def is_warm(self, symbol: str) -> bool:
        if isinstance(self._warm, bool):
            return self._warm
        return self._warm.get(symbol, False)


class _RecordingLogger:
    """Captures ``info`` / ``warning`` call arg-tuples for message assertions."""

    def __init__(self) -> None:
        self.info_calls: list[tuple[Any, ...]] = []
        self.warning_calls: list[tuple[Any, ...]] = []

    def info(self, *args: Any, **kwargs: Any) -> None:
        self.info_calls.append(args)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self.warning_calls.append(args)

    def bind(self, **kwargs: Any) -> "_RecordingLogger":
        return self


# --- helpers ---------------------------------------------------------------


def _inst(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"),
    )


def _spy_universe(log: list[tuple[str, str]], *symbols: str) -> _SpyUniverse:
    members = sorted(symbols)
    return _SpyUniverse(
        log, members=members, instrument_map={s: _inst(s) for s in members}
    )


def _handler(
    universe: Universe,
    *,
    feed: object,
    provider: object | None = None,
    warmth: object | None = None,
    remove_policy: str = "orphan-and-track",
) -> UniverseHandler:
    handler = UniverseHandler(
        global_queue=Queue(),
        universe=universe,
        feed=feed,  # type: ignore[arg-type]
        timeframe="1d",
        remove_policy=remove_policy,
    )
    if provider is not None:
        handler.set_provider(provider)  # type: ignore[arg-type]
    if warmth is not None:
        handler.set_strategy_warmth(warmth)  # type: ignore[arg-type]
    return handler


def _bar(price: str) -> Bar:
    px = Decimal(price)
    return Bar(time=_ASOF, open=px, high=px, low=px, close=px, volume=Decimal("1"))


def _bars_loaded(symbol: str) -> BarsLoaded:
    return BarsLoaded(time=_ASOF, symbol=symbol, timeframe="1d", bars=(_bar("100"),))


# --- (i) warm-verify MISS -> FAILED, no mark_ready, no subscribe -----------


def test_warm_verify_miss_marks_failed_skips_ready_and_subscribe() -> None:
    log: list[tuple[str, str]] = []
    universe = _spy_universe(log, "BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH pending
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log)
    handler = _handler(
        universe, feed=feed, provider=provider, warmth=_FakeWarmth(False)
    )

    handler.on_bars_loaded(_bars_loaded("ETH/USDC"))

    # absorb ran, then FAILED — NOT ready, NOT subscribed.
    assert log == [("absorb", "ETH/USDC"), ("mark_failed", "ETH/USDC")]
    assert not universe.is_ready("ETH/USDC")
    assert universe._entries["ETH/USDC"].readiness is Readiness.FAILED
    assert ("subscribe", "ETH/USDC") not in log
    # Kept in membership → retried next poll (composes with CR-02).
    assert "ETH/USDC" in universe.members


# --- (ii) warm-verify HIT -> absorb -> mark_ready -> subscribe (unchanged) --


def test_warm_verify_hit_preserves_absorb_ready_subscribe_order() -> None:
    log: list[tuple[str, str]] = []
    universe = _spy_universe(log, "BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log)
    handler = _handler(
        universe, feed=feed, provider=provider, warmth=_FakeWarmth(True)
    )

    handler.on_bars_loaded(_bars_loaded("ETH/USDC"))

    assert log == [
        ("absorb", "ETH/USDC"),
        ("mark_ready", "ETH/USDC"),
        ("subscribe", "ETH/USDC"),
    ]
    assert universe.is_ready("ETH/USDC")


# --- (iii) no warmth wired -> unchanged paper/backtest path -----------------


def test_no_warmth_wired_flips_ready_and_subscribes() -> None:
    log: list[tuple[str, str]] = []
    universe = _spy_universe(log, "BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log)
    handler = _handler(universe, feed=feed, provider=provider)  # no warmth

    handler.on_bars_loaded(_bars_loaded("ETH/USDC"))

    assert log == [
        ("absorb", "ETH/USDC"),
        ("mark_ready", "ETH/USDC"),
        ("subscribe", "ETH/USDC"),
    ]
    assert universe.is_ready("ETH/USDC")


# --- (iv) IN-01 force-close log reword --------------------------------------


class _OneHolderReadModel:
    """A read-model reporting exactly one portfolio holding ``sym`` LONG."""

    def __init__(self, sym: str) -> None:
        self._sym = sym

    def active_portfolio_ids(self) -> list[Any]:
        return [1]

    def get_position(self, portfolio_id: Any, ticker: str) -> PositionView | None:
        if ticker != self._sym:
            return None
        return PositionView(
            ticker=ticker,
            side=PositionSide.LONG,
            net_quantity=Decimal("1"),
            avg_price=Decimal("100"),
        )


def test_in01_force_close_log_wording() -> None:
    log: list[tuple[str, str]] = []
    universe = _spy_universe(log, "ETH/USDC")
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log)
    handler = _handler(
        universe, feed=feed, provider=provider, remove_policy="force-close"
    )
    handler.set_portfolio_read_model(_OneHolderReadModel("ETH/USDC"))  # type: ignore[arg-type]
    recorder = _RecordingLogger()
    handler.logger = recorder  # type: ignore[assignment]

    handler._on_symbol_removed("ETH/USDC", _ASOF)

    # The reworded IN-01 message: emitted + unsubscribed, detach on flat fill.
    assert recorder.info_calls, "force-close path should log an info line"
    fmt = recorder.info_calls[-1][0]
    assert fmt == (
        "Force-close removal for %s: exit order emitted, unsubscribed; "
        "detach completes on flat fill"
    )
    # The %s placeholder is present (structlog PositionalArgumentsFormatter needs
    # it because sym is passed as a positional arg).
    assert "%s" in fmt
    # The old misleading wording is gone.
    assert "exit emitted + detached" not in fmt
