"""Characterization tests for M2-07 (enums, not strings; clear parse errors).

These pin the two M2-07 behaviors the enums wave delivers:

  1. ``FillStatus("executed")`` parses case-insensitively to ``FillStatus.EXECUTED`` — the
     fill status is a real enum, not a bare string.
  2. An unknown value raises a CLEAR f-string error (NOT the legacy ``('Value %s', x)``
     printf-tuple form).

``FillStatus`` now exists in ``itrader/core/enums/execution.py`` with case-insensitive
parsing (M2-07 shipped), so the assertions import and run directly. The Wave-0
``pytest.importorskip`` / ``pytest.skip`` gating was removed as dead code (FL-03,
plan 04-01) — the two FillStatus assertions now execute against the real enum.
"""

import pytest

from itrader.core.enums.execution import FillStatus


def test_fill_status_parses_case_insensitively():
    """M2-07: FillStatus('executed') → FillStatus.EXECUTED (case-insensitive parse)."""
    assert FillStatus("executed") is FillStatus.EXECUTED
    assert FillStatus("EXECUTED") is FillStatus.EXECUTED


def test_fill_status_unknown_value_raises_clear_error():
    """M2-07: an unknown value raises a clear f-string error (not the printf-tuple form)."""
    with pytest.raises(ValueError) as exc_info:
        FillStatus("not_a_real_status")
    # The message must be a clear human-readable string, NOT the legacy ('Value %s', x) tuple.
    message = str(exc_info.value)
    assert "not_a_real_status" in message
    assert "('Value %s'" not in message
