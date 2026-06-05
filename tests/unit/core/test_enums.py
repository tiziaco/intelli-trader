"""Wave-0 characterization stub for M2-07 (enums, not strings; clear parse errors).

Written at Wave 0 of Phase 3 (M2b) under the CURRENT ``test/`` tree so ``make test``
collects it immediately (auto-marked ``unit`` via the ``test_core`` path in conftest).
It pins the two M2-07 behaviors the enums wave delivers:

  1. ``FillStatus("executed")`` parses case-insensitively to ``FillStatus.EXECUTED`` — the
     fill status is a real enum, not a bare string.
  2. An unknown value raises a CLEAR f-string error (NOT the legacy ``('Value %s', x)``
     printf-tuple form).

``FillStatus`` does not exist yet (today only ``ExecutionStatus`` is defined in
``itrader/core/enums/execution.py``). Until the M2-07 wave adds ``FillStatus`` with
case-insensitive parsing, the assertions are gated behind ``pytest.importorskip`` on the
attribute so the suite stays GREEN at Wave 0.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_core/`` during the
03-08 type-split — 03-08 reconciles it there without duplication.
"""

import pytest


def _fill_status_or_skip():
    """Return FillStatus once the M2-07 enum lands; otherwise skip (Wave-0 pending)."""
    enums = pytest.importorskip(
        "itrader.core.enums.execution",
        reason="pending M2-07: enums module",
    )
    fill_status = getattr(enums, "FillStatus", None)
    if fill_status is None:
        pytest.skip("pending M2-07: FillStatus enum not added yet")
    return fill_status


def test_fill_status_parses_case_insensitively():
    """M2-07: FillStatus('executed') → FillStatus.EXECUTED (case-insensitive parse)."""
    FillStatus = _fill_status_or_skip()
    assert FillStatus("executed") is FillStatus.EXECUTED
    assert FillStatus("EXECUTED") is FillStatus.EXECUTED


def test_fill_status_unknown_value_raises_clear_error():
    """M2-07: an unknown value raises a clear f-string error (not the printf-tuple form)."""
    FillStatus = _fill_status_or_skip()
    with pytest.raises(ValueError) as exc_info:
        FillStatus("not_a_real_status")
    # The message must be a clear human-readable string, NOT the legacy ('Value %s', x) tuple.
    message = str(exc_info.value)
    assert "not_a_real_status" in message
    assert "('Value %s'" not in message
