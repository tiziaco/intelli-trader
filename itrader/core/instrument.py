"""
Frozen per-symbol ``Instrument`` value object (INST-01/INST-03, D-04/D-05).

This module is the single home for the per-symbol source of truth that replaces
the hard-coded ``_INSTRUMENT_SCALES`` table previously baked into
``core/money.py``. ``Instrument`` mirrors ``core/bar.py::Bar`` exactly:

- **D-04 — string entry / Decimal end-to-end.** Every Decimal field is a
  rounding *scale* (e.g. ``Decimal("0.00000001")`` for BTCUSD 8dp). Any factory
  that coerces external input enters the Decimal domain via ``Decimal(str(x))``
  (the ``core.money.to_money`` path) — NEVER ``Decimal(float)`` (the binary
  float-repr artifact). ``core`` depends on nothing inside ``itrader``; the
  intra-``core`` ``to_money`` import is allowed (D-05).
- **D-05 — instrument carries the precision; ``money.py`` stays stateless.**
  ``core.money.quantize(value, instrument, kind)`` reads its rounding scale off
  the handed-in ``Instrument`` and holds zero domain state. ``Instrument`` is
  the data; ``quantize`` is the mechanism.
- **D-01a — undeclared ``min_order_size``.** Defaults to ``None`` so the
  exchange falls through to the venue-level ``ExchangeLimits`` fallback. BTCUSD
  leaves it undeclared, which keeps the SMA_MACD oracle byte-exact.
- **D-10 — store the Decimal scale, not an int place-count** (RESEARCH Pitfall 3
  / A1): ``price_precision`` is the scale Decimal directly, byte-identical to the
  deleted ``_INSTRUMENT_SCALES["BTCUSD"]`` entry, so ``quantize`` stays a
  one-line ``value.quantize(scale, ...)``.

The INST-03 margin fields (``maintenance_margin_rate``, ``max_leverage``,
``settles_funding``) land **inert** in Phase 1 for downstream consumers
(Phase 2 leverage, Phase 4 liquidation, Phase B funding — deferred).

``Instrument`` is a value object, NOT an ``Event`` subclass: it carries no
``type``/``event_id`` machinery.
"""

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["Instrument"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Instrument:
    """Immutable per-symbol trading metadata.

    Fields
    ------
    symbol:
        Universe key (upper-cased to match store keying).
    quote_currency:
        Settlement currency; source of the ``kind="cash"`` scale (USD -> 2dp).
        Consumed by ``core.money.quantize(kind="cash")`` via ``_CASH_SCALES``
        (WR-01): USD resolves to 2dp; an unmapped quote currency falls back to
        2dp. Non-USD quote currencies are not yet derived this phase, so the
        mapping is effectively exercised only for USD until they land.
    price_precision:
        Price rounding **scale** as a ``Decimal`` (D-10 — the scale, e.g.
        ``Decimal("0.00000001")`` for BTCUSD 8dp), read by
        ``core.money.quantize(kind="price")``.
    quantity_precision:
        Quantity rounding **scale** as a ``Decimal`` (BTCUSD 8dp), read by
        ``core.money.quantize(kind="quantity")``.
    min_order_size:
        Minimum order size, or ``None`` when undeclared (D-01a). ``None`` falls
        through to the venue ``ExchangeLimits`` fallback; BTCUSD leaves it
        undeclared to keep the oracle byte-exact.
    maintenance_margin_rate:
        Maintenance-margin rate (INST-03; inert Phase 1, Phase 4 liquidation
        consumer).
    max_leverage:
        Maximum leverage (INST-03; inert Phase 1, Phase 2 margin/leverage
        consumer).
    settles_funding:
        Whether the instrument settles perpetual funding (INST-03; inert flag,
        Phase B deferred).
    """

    symbol: str
    price_precision: Decimal
    quantity_precision: Decimal
    maintenance_margin_rate: Decimal
    max_leverage: Decimal
    quote_currency: str = "USD"
    min_order_size: Decimal | None = None
    settles_funding: bool = False
