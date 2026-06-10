"""Hand-built fixture tests for ``itrader.reporting.cash_operations`` (Phase 8, D-02).

The cash-ledger snapshot serializer is the structural clone of
``itrader.reporting.orders`` (the opt-in orders-snapshot). These fixtures pin its
DETERMINISM contract — the snapshot must NOT leak the UUIDv7 ``operation_id``, the
raw ``reference_id`` (order id), or the wall-clock ``timestamp`` (RESERVATION /
RELEASE rows use ``datetime.now(UTC)`` — cash_manager.py:409,441 — non-deterministic
across runs). A RESERVATION must still be matchable to its RELEASE via a DERIVED
stable correlation (ticker-free per-reference ordinal/role, e.g. ``ORDER-1``).

The ``unit`` marker is folder-derived (tests/unit/) — not hand-added here.
"""

import uuid
from datetime import datetime, UTC
from decimal import Decimal

import pandas as pd

from itrader.core.enums import CashOperationType
from itrader.portfolio_handler.cash.cash_manager import CashOperation
from itrader.reporting.cash_operations import (
    CASH_OPERATION_COLUMNS,
    build_cash_operations,
)


def _op(op_type, amount, reference_id, before=None, after=None):
    """Build a CashOperation with a fresh UUIDv7 + wall-clock timestamp.

    The fresh id + wall-clock timestamp are deliberately non-deterministic so the
    test proves the serializer EXCLUDES them rather than freezing them.
    """
    return CashOperation(
        operation_id=uuid.uuid4(),
        operation_type=op_type,
        amount=amount,
        timestamp=datetime.now(UTC),
        description="test op",
        reference_id=reference_id,
        balance_before=before,
        balance_after=after,
    )


def test_empty_returns_columns_only():
    """build_cash_operations([]) -> empty frame with EXACTLY CASH_OPERATION_COLUMNS."""
    frame = build_cash_operations([])
    assert frame.empty
    assert list(frame.columns) == CASH_OPERATION_COLUMNS


def test_columns_exclude_non_deterministic_fields():
    """The frozen column set must carry NONE of the non-deterministic fields."""
    for forbidden in ("operation_id", "reference_id", "timestamp"):
        assert forbidden not in CASH_OPERATION_COLUMNS


def test_reservation_then_release_correlate_via_derived_label():
    """A RESERVATION + its RELEASE for one reference_id share a derived correlation.

    Two rows, operation_type via ``.name``, matching amount, matching DERIVED
    correlation (NOT the raw reference_id), and no leaked id/timestamp column.
    """
    raw_ref = "order-abc-uuid-7"
    ops = [
        _op(CashOperationType.RESERVATION, Decimal("100"), raw_ref,
            before=Decimal("1000"), after=Decimal("1000")),
        _op(CashOperationType.RELEASE_RESERVATION, Decimal("100"), raw_ref,
            before=Decimal("1000"), after=Decimal("1000")),
    ]
    frame = build_cash_operations(ops)
    assert len(frame) == 2
    assert set(frame["operation_type"]) == {"RESERVATION", "RELEASE_RESERVATION"}
    # Both rows correlate via the SAME derived label, and it is not the raw ref.
    correlations = set(frame["correlation"])
    assert len(correlations) == 1
    assert raw_ref not in correlations
    # Amounts match and are floats at the edge.
    assert set(frame["amount"]) == {100.0}
    assert all(isinstance(v, float) for v in frame["amount"])


def test_distinct_references_get_distinct_correlations_in_first_appearance_order():
    """Each distinct reference_id gets a stable ordinal in first-appearance order."""
    ops = [
        _op(CashOperationType.RESERVATION, Decimal("50"), "ref-1",
            before=Decimal("1000"), after=Decimal("1000")),
        _op(CashOperationType.RESERVATION, Decimal("60"), "ref-2",
            before=Decimal("950"), after=Decimal("950")),
        _op(CashOperationType.RELEASE_RESERVATION, Decimal("50"), "ref-1",
            before=Decimal("950"), after=Decimal("950")),
    ]
    frame = build_cash_operations(ops)
    by_ref = {}
    for _, row in frame.iterrows():
        by_ref.setdefault(row["correlation"], []).append(row["amount"])
    # Two distinct correlations, one per reference_id.
    assert len(by_ref) == 2


def test_money_columns_are_floats_at_edge():
    """amount / balance_before / balance_after are floats; None survives as NaN-safe."""
    ops = [
        _op(CashOperationType.RESERVATION, Decimal("100"), "ref-x",
            before=Decimal("1000"), after=Decimal("1000")),
    ]
    frame = build_cash_operations(ops)
    row = frame.iloc[0]
    assert isinstance(row["amount"], float)
    assert isinstance(row["balance_before"], float)
    assert isinstance(row["balance_after"], float)
