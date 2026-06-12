"""
Centralized money policy for the iTrader system (D-01..D-04).

This module is the single home for the Decimal entry-and-rounding policy that was
previously scattered (and partly wrong) across the handlers:

- **D-01 — full precision through intermediate math.** Carry the default 28-digit
  ``decimal`` context through every intermediate multiply/add. Quantize ONLY at the
  money *boundaries* — writing the cash ledger, reporting realized PnL, or
  serializing a value out of the engine. Quantizing per intermediate operation
  accumulates rounding error and is a correctness defect (RESEARCH Pitfall 5).
- **D-02 — per-instrument scales.** Different instruments carry different decimal
  resolution (BTC price/quantity at 8dp, USD cash at 2dp). ``_INSTRUMENT_SCALES``
  holds the overrides; ``_DEFAULT_SCALES`` is the fallback.
- **D-03 — ROUND_HALF_UP at the boundary.** ``quantize`` rounds half away from zero.
- **D-04 — string entry.** ``to_money`` always enters Decimal via ``Decimal(str(x))``.
  ``Decimal(some_float)`` would carry the binary-float repr artifact (e.g.
  ``Decimal(10.1)`` is ``10.0999999...``); ``Decimal(str(10.1))`` is exactly
  ``Decimal("10.1")``. NEVER call ``Decimal(float)`` anywhere.

Only ``BTCUSD`` carries an override entry today; a general per-token registry is
deferred (the golden dataset is BTCUSD-only).
"""

from decimal import Decimal, ROUND_HALF_UP

# D-02 — public because it is now shared cross-module (core/sizing.py,
# order_handler/sizing_resolver.py, order_handler/brackets/levels.py all import
# this single canonical constant). D-04 string-path literal, never Decimal(1.0).
ONE = Decimal("1")

_DEFAULT_SCALES: dict[str, Decimal] = {
    "price": Decimal("0.01"),
    "quantity": Decimal("0.00000001"),
    "cash": Decimal("0.01"),
}

_INSTRUMENT_SCALES: dict[str, dict[str, Decimal]] = {
    "BTCUSD": {
        "price": Decimal("0.00000001"),
        "quantity": Decimal("0.00000001"),
        "cash": Decimal("0.01"),
    },
}


def to_money(x: float | int | str | Decimal) -> Decimal:
    """Enter the Decimal domain via the string path (D-04).

    ``Decimal(str(x))`` avoids the binary float-repr artifact that
    ``Decimal(x)`` would introduce for a ``float`` ``x``. NEVER call
    ``Decimal(float)`` directly.
    """
    return Decimal(str(x))


def quantize(value: Decimal, instrument: str, kind: str) -> Decimal:
    """Round ``value`` to the per-instrument scale for ``kind`` (D-02/D-03).

    Call this ONLY at money boundaries (cash ledger write, reported PnL,
    serialization) — never on intermediate arithmetic (D-01, Pitfall 5).

    ``kind`` is one of ``"price"``, ``"quantity"``, ``"cash"``. Unknown
    instruments fall back to ``_DEFAULT_SCALES``; unknown kinds fall back to the
    default cash/price/quantity scale for that kind.
    """
    scale = _INSTRUMENT_SCALES.get(instrument, _DEFAULT_SCALES).get(
        kind, _DEFAULT_SCALES[kind]
    )
    return value.quantize(scale, rounding=ROUND_HALF_UP)
