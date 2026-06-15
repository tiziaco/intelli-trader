"""
Centralized money policy for the iTrader system (D-01..D-04).

This module is the single home for the Decimal entry-and-rounding policy that was
previously scattered (and partly wrong) across the handlers:

- **D-01 — full precision through intermediate math.** Carry the default 28-digit
  ``decimal`` context through every intermediate multiply/add. Quantize ONLY at the
  money *boundaries* — writing the cash ledger, reporting realized PnL, or
  serializing a value out of the engine. Quantizing per intermediate operation
  accumulates rounding error and is a correctness defect (RESEARCH Pitfall 5).
- **D-02 — per-instrument scales read off the ``Instrument`` (D-05).** Different
  instruments carry different decimal resolution (BTC price/quantity at 8dp, USD
  cash at 2dp). ``quantize`` now reads its ``"price"``/``"quantity"`` scale off
  the handed-in ``Instrument`` (the per-symbol source of truth, INST-01) and
  holds zero domain state; the hard-coded per-instrument scale table is gone.
  ``_DEFAULT_SCALES`` is the no-data fallback (the ``"cash"`` scale derives from
  ``quote_currency``, default USD -> 2dp; D-09).
- **D-03 — ROUND_HALF_UP at the boundary.** ``quantize`` rounds half away from zero.
- **D-04 — string entry.** ``to_money`` always enters Decimal via ``Decimal(str(x))``.
  ``Decimal(some_float)`` would carry the binary-float repr artifact (e.g.
  ``Decimal(10.1)`` is ``10.0999999...``); ``Decimal(str(10.1))`` is exactly
  ``Decimal("10.1")``. NEVER call ``Decimal(float)`` anywhere.

- **D-05 — ``money.py`` stays pure/stateless.** The precision lives on the
  ``Instrument`` value object (``core/instrument.py``); this module is only the
  rounding mechanism. The intra-``core`` import of ``Instrument`` is allowed.
"""

from decimal import Decimal, ROUND_HALF_UP

from itrader.core.instrument import Instrument

# IN-01 — pin the intended public surface explicitly, matching the __all__
# convention used in core/sizing.py and sizing_resolver.py. ONE is now a
# documented shared primitive; relying on implicit export was inconsistent
# with this module's "single canonical public money primitive" framing.
__all__ = ["ONE", "to_money", "quantize"]

# D-02 — public because it is now shared cross-module (core/sizing.py,
# order_handler/sizing_resolver.py, order_handler/brackets/levels.py all import
# this single canonical constant). D-04 string-path literal, never Decimal(1.0).
ONE = Decimal("1")

_DEFAULT_SCALES: dict[str, Decimal] = {
    "price": Decimal("0.01"),
    "quantity": Decimal("0.00000001"),
    "cash": Decimal("0.01"),
}


def to_money(x: float | int | str | Decimal) -> Decimal:
    """Enter the Decimal domain via the string path (D-04).

    ``Decimal(str(x))`` avoids the binary float-repr artifact that
    ``Decimal(x)`` would introduce for a ``float`` ``x``. NEVER call
    ``Decimal(float)`` directly.
    """
    return Decimal(str(x))


def quantize(value: Decimal, instrument: Instrument, kind: str) -> Decimal:
    """Round ``value`` to ``instrument``'s scale for ``kind`` (D-02/D-03/D-05).

    Call this ONLY at money boundaries (cash ledger write, reported PnL,
    serialization) — never on intermediate arithmetic (D-01, Pitfall 5).

    ``kind`` is one of ``"price"``, ``"quantity"``, ``"cash"``. The
    ``"price"``/``"quantity"`` scales are read off the handed-in ``Instrument``
    (the per-symbol source of truth, INST-01); the ``"cash"`` scale derives from
    ``quote_currency`` (default USD -> 2dp), held in ``_DEFAULT_SCALES["cash"]``
    as the no-data fallback (D-09).
    """
    scale = {
        "price": instrument.price_precision,
        "quantity": instrument.quantity_precision,
        "cash": _DEFAULT_SCALES["cash"],
    }.get(kind, _DEFAULT_SCALES[kind])
    return value.quantize(scale, rounding=ROUND_HALF_UP)
