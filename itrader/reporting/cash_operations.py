"""Cash-ledger snapshot serializer for the E2E cash_operations golden (Phase 8, D-02).

The opt-in sibling of ``itrader.reporting.orders`` — for scenarios whose ASSERTION
is the cash reservation/release lifecycle (CASH-01 no-commit, CASH-02 release on a
terminal state) rather than a closed trade or the order mirror. It joins the same
reporting serializer family: pandas + stdlib only, a DUCK-TYPED ``operations`` input
(``CashOperation``-shaped objects, NO handler import), the same
rows→DataFrame→sort→reset idiom, and ``float(...)`` only at the serialization edge
(Decimal stays internal upstream).

Determinism contract (D-02)
---------------------------
Business columns ONLY: a DERIVED ``correlation`` label, ``operation_type``,
``amount``, ``balance_before``, ``balance_after``. THREE source fields are EXCLUDED
because they are non-deterministic across runs:

* ``operation_id`` — a UUIDv7 minted per record (cash_manager.py:34).
* ``reference_id`` — the raw order id (a UUIDv7) keying the reservation.
* ``timestamp`` — RESERVATION / RELEASE_RESERVATION rows stamp ``datetime.now(UTC)``
  (admission audit wall-clock — cash_manager.py:409,441), NOT an event-derived
  business time, so it is never oracle-safe to freeze.

To keep a RESERVATION matchable to its RELEASE WITHOUT exposing the raw id, the
``correlation`` label is derived the way ``orders.py::_order_role`` derives a stable
label from linkage flags instead of a raw UUID: each distinct ``reference_id`` is
assigned a stable ordinal in first-appearance order and labelled ``ORDER-{n}`` (a
``None`` reference — e.g. a DEPOSIT seed — maps to a single ``ACCOUNT`` label).
``operation_type`` serializes via ``op.operation_type.name`` (mirrors orders.py
``o.status.name``). Rows are sorted by a stable business key (the derived
correlation, then operation_type, then amount as a tiebreak) so order is
reproducible across runs.

Indentation: 4 spaces (reporting package house style).
"""

from typing import Any

import pandas as pd

# Deterministic cash-ledger snapshot columns (D-02) — business fields only. NO
# UUIDv7 ``operation_id``, NO raw ``reference_id`` (order id), NO wall-clock
# ``timestamp``. ``correlation`` is the derived stable per-reference label that
# matches a RESERVATION to its RELEASE without exposing the raw id.
CASH_OPERATION_COLUMNS = [
    "correlation",
    "operation_type",
    "amount",
    "balance_before",
    "balance_after",
]


def _float_or_none(value: Any) -> float | None:
    """Decimal → float ONLY at the serialization edge; preserve ``None``.

    ``balance_before`` / ``balance_after`` are ``Optional[Decimal]`` on the source
    ``CashOperation`` — guard ``None`` so a missing balance survives as a NaN-safe
    cell instead of crashing ``float(None)``.
    """
    return None if value is None else float(value)


def build_cash_operations(operations: Any) -> pd.DataFrame:
    """Serialize the cash-operation ledger to a deterministic business-columns frame.

    ``operations`` is a duck-typed list of ``CashOperation``-shaped objects (the
    harness passes ``portfolio.cash_manager.get_cash_operations()``). Empty-safe;
    sorted by a stable business key so row order is reproducible. The raw
    ``reference_id`` is collapsed to a stable per-reference ordinal (``ORDER-{n}``
    in first-appearance order; a ``None`` reference → ``ACCOUNT``) so a RESERVATION
    matches its RELEASE without leaking the UUIDv7 order id. Decimal money → float
    only here at the serialization edge.
    """
    # First-appearance ordinal assignment for the derived correlation label.
    _ordinals: dict[str, int] = {}

    def _correlation(reference_id: Any) -> str:
        if reference_id is None:
            return "ACCOUNT"
        ref = str(reference_id)
        if ref not in _ordinals:
            _ordinals[ref] = len(_ordinals) + 1
        return f"ORDER-{_ordinals[ref]}"

    rows = [{
        "correlation": _correlation(op.reference_id),
        "operation_type": op.operation_type.name,
        "amount": float(op.amount),
        "balance_before": _float_or_none(op.balance_before),
        "balance_after": _float_or_none(op.balance_after),
    } for op in operations]
    frame = pd.DataFrame(rows, columns=CASH_OPERATION_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["correlation", "operation_type", "amount"]).reset_index(drop=True)
    return frame
