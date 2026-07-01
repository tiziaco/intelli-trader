"""Shared offline fixtures for the LiveBarFeed unit matrix (Phase 3 / 03-01, FEED-01/03).

Wave-0 test infrastructure the Phase-3 ``LiveBarFeed`` tests (03-02) consume: a synthetic
``ClosedBar`` builder and a socket-free stub provider. Both let the feed matrix drive
``update(bar)`` and ``warmup(...)`` deterministically — NO live socket, NO aiohttp, NO
asyncio (mirrors the Phase-2 offline-fake discipline in
``tests/unit/connectors/test_okx_data_provider.py``).

- ``closed_bar`` — a factory building a single ``ClosedBar`` dict (Decimal OHLCV, the D-12
  ``symbol``/``timeframe`` routing keys). Every ``ts`` is a fixed epoch-ms literal, never
  wall-clock — the sequences are byte-reproducible.
- ``closed_bar_sequence`` — yields N consecutive ``ClosedBar``s advancing ``ts`` by exactly
  one timeframe (for in-sequence / warmup tests; each advance is one ``update()`` step so no
  spurious gap fires).
- ``stub_provider`` — a ``_StubProvider`` exposing a programmable
  ``fetch_ohlcv_backfill(symbol, timeframe, since=None, limit=1000) -> list[ClosedBar]``
  (return list assigned per-test) plus a captured-call log so a gap/backfill test can assert
  the ``since``/``limit`` it was invoked with.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named top-level
test packages break full-suite collection). Indentation is 4-SPACE (matched to the
``price_handler/feed`` tree).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

import pytest

from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.providers.okx_provider import ClosedBar

# A fixed byte-reproducible epoch-ms literal (2024-01-01T00:00:00Z), never wall-clock —
# every synthetic bar's business time is anchored to this so sequences are deterministic.
_DEFAULT_TS_MS = 1704067200000


def _make_closed_bar(
    ts_ms: int = _DEFAULT_TS_MS,
    *,
    symbol: str = "BTC-USDT",
    timeframe: str = "1d",
    open: str = "42000.0",
    high: str = "42500.0",
    low: str = "41800.0",
    close: str = "42100.0",
    volume: str = "1200.5",
) -> ClosedBar:
    """Build one synthetic ``ClosedBar`` — Decimal OHLCV + the D-12 routing keys.

    OHLCV cross the Decimal edge via ``Decimal(str(...))`` (never ``Decimal(float)``),
    mirroring the provider's ``to_money(str(...))`` edge. Callers typically vary only
    ``ts_ms``; symbol/timeframe/OHLCV are overridable for gap and multi-symbol cases.
    """
    return {
        "ts": int(ts_ms),
        "open": Decimal(str(open)),
        "high": Decimal(str(high)),
        "low": Decimal(str(low)),
        "close": Decimal(str(close)),
        "volume": Decimal(str(volume)),
        "symbol": symbol,
        "timeframe": timeframe,
    }


@pytest.fixture
def closed_bar() -> Callable[..., ClosedBar]:
    """Factory building a single synthetic ``ClosedBar`` (see ``_make_closed_bar``)."""
    return _make_closed_bar


@pytest.fixture
def closed_bar_sequence(
    closed_bar: Callable[..., ClosedBar],
) -> Callable[..., list[ClosedBar]]:
    """Factory yielding N consecutive ``ClosedBar``s advancing ``ts`` by one timeframe.

    Each bar's ``ts`` is ``start_ts + i * one_timeframe_ms`` (the timeframe converted via
    ``to_timedelta``), so replaying the sequence through ``update()`` advances the
    last-delivered stamp by exactly one interval per bar — no spurious gap-backfill fires.
    """

    def _seq(
        n: int,
        *,
        start_ts: int = _DEFAULT_TS_MS,
        symbol: str = "BTC-USDT",
        timeframe: str = "1d",
        **overrides: Any,
    ) -> list[ClosedBar]:
        step_ms = int(to_timedelta(timeframe).total_seconds() * 1000)
        return [
            closed_bar(
                start_ts + i * step_ms,
                symbol=symbol,
                timeframe=timeframe,
                **overrides,
            )
            for i in range(n)
        ]

    return _seq


class _StubProvider:
    """Socket-free stand-in for ``OkxDataProvider``'s REST backfill arm.

    Mimics the ``fetch_ohlcv_backfill`` signature the ``LiveBarFeed`` warmup path calls
    (``fetch_ohlcv_backfill(symbol, timeframe, since=None, limit=1000) -> list[ClosedBar]``).
    The return list is programmed per-test via :attr:`backfill_bars`; every invocation is
    appended to :attr:`calls` so a gap/backfill test can assert the ``since``/``limit`` it
    was called with. No socket, no aiohttp, no asyncio.
    """

    def __init__(self) -> None:
        self.backfill_bars: list[ClosedBar] = []
        self.calls: list[dict[str, Any]] = []

    def fetch_ohlcv_backfill(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 1000,
    ) -> list[ClosedBar]:
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        )
        return list(self.backfill_bars)


@pytest.fixture
def stub_provider() -> _StubProvider:
    """A fresh programmable, call-logging ``_StubProvider`` (no live socket)."""
    return _StubProvider()
