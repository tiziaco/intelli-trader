"""
Immutable per-tick OHLCV bar value object (M5-02, D-14/D-15).

This module is the single home for the per-tick market-data struct that
replaces the per-ticker pandas Series payload on ``BarEvent``:

- **D-14 — Decimal OHLCV via the string path.** Every field enters the
  Decimal domain once, at construction, via ``Decimal(str(x))`` (the
  ``core.money.to_money`` path). ``Decimal(some_float)`` would carry the
  binary float-repr artifact — NEVER call ``Decimal(float)``.
- **D-04 — open-time stamping.** ``time`` is the bar's open-time stamp:
  the bar covering [T, T+tf) is stamped T.
- **Never round prices/quantities.** The ``core.money.quantize`` policy
  applies ONLY at cash/PnL/ledger boundaries — bar prices and volumes are
  carried at full precision; no ``quantize`` call exists in this module.

``Bar`` is a value object, NOT an ``Event`` subclass: it carries no
``type``/``event_id`` machinery. ``BarEvent.bars`` maps ticker ->
``Bar``; history comes from the Feed, not from events (D-15 "event =
fact, feed = query").
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    """Immutable OHLCV bar fact for one ticker at one tick.

    Fields
    ------
    time:
        Open-time stamp of the bar (D-04): the bar covering [T, T+tf)
        is stamped T.
    open, high, low, close:
        Bar prices as full-precision ``Decimal`` (D-14 — entered via the
        string path, never rounded).
    volume:
        Bar volume as full-precision ``Decimal``.
    """

    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_row(cls, time: datetime, row: Mapping[str, Any]) -> "Bar":
        """Build a ``Bar`` from a mapping-like OHLCV row (pandas Series qualifies).

        ``row`` must support ``__getitem__`` for the keys ``open``,
        ``high``, ``low``, ``close``, ``volume``. Every field enters the
        Decimal domain via ``Decimal(str(x))`` (D-14) — byte-identical to
        the ``core.money.to_money`` path, NEVER ``Decimal(float)``.
        """
        return cls(
            time=time,
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
        )
