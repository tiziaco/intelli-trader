"""
Precision-epsilon drift-tolerance primitive (D-01, RECON-01/RECON-03).

The reconciliation cluster's foundational compare: two Decimal quantities/prices
"agree" when their absolute difference is within one least-significant-digit unit
for the caller's instrument precision. This is the epsilon that gates whether a
cached ``VenueAccount`` value and the engine's computed value have drifted (a
strict ``==`` on venue floats-turned-Decimal would false-alarm on the last digit).

PORTED IN CONCEPT (never imported) from nautilus_trader ``live/reconciliation.py:52``
``is_within_single_unit_tolerance``. Importing ``nautilus_trader`` at runtime is
forbidden — nautilus is a non-gating reconciliation oracle for tests only, and the
live/backtest path must stay import-light and inertness-safe.

The ``precision`` argument is the caller's instrument amount/price precision — for OKX
it derives from ``client.markets[symbol]['precision']['amount'|'price']`` reconciled
into the engine ``Instrument`` at connector init. This helper hardcodes no per-symbol
table (Don't Hand-Roll): it keys off the SAME precision idiom as
``core/money.py::quantize`` (``instrument.price_precision`` / ``quantity_precision``,
``_DEFAULT_SCALES["quantity"] == 1e-8``, ``_CASH_SCALES["USD"] == 0.01``).

Indent: 4 spaces (matches ``core/`` and ``core/money.py``). Decimal-only — money policy
forbids floats anywhere near reconciliation math.
"""

from decimal import Decimal

__all__ = ["is_within_single_unit_tolerance"]


def is_within_single_unit_tolerance(v1: Decimal, v2: Decimal, precision: int) -> bool:
    """Return whether ``v1`` and ``v2`` agree within one least-significant unit.

    Parameters
    ----------
    v1, v2 : Decimal
        The two Decimal values to compare (e.g. engine-computed vs cached-venue
        quantity). Decimal-only — never floats (money policy, D-01).
    precision : int
        The caller's instrument amount/price precision. ``precision == 0`` means
        integer quantities and compares exactly; otherwise the tolerance is
        ``10 ** -precision`` (one least-significant-digit unit).

    Returns
    -------
    bool
        ``True`` when ``abs(v1 - v2) <= tolerance`` (or exact equality at
        ``precision == 0``); ``False`` beyond it.
    """
    if precision == 0:
        return v1 == v2                    # integer quantities: exact equality
    tolerance = Decimal(10) ** -precision  # one least-significant-digit unit
    return abs(v1 - v2) <= tolerance
