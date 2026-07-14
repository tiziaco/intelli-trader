"""Tests for the ``FailureClass`` enum (D-08 / D-10, Phase 8 error subsystem).

Pins the five route-classification failure classes the CF-1 aggregate
failure-rate tripwire (08-02) keys its ``_POLICY`` map on:

  1. Exactly FIVE members — ``SETTLEMENT`` / ``ORDER_IO`` / ``ADMISSION`` /
     ``LOOP_BACKSTOP`` / ``FILL_TRANSLATION`` (D-08 + D-10 FILL_TRANSLATION).
  2. Each ``.value`` is a readable lowercase-hyphen literal (HaltReason house
     style). These values are NOT persisted, so they are descriptive only.
  3. Importable from the ``itrader.core.enums`` barrel (mirrors HaltReason).
"""

import pytest

from itrader.core.enums import FailureClass

pytestmark = pytest.mark.unit


def test_failure_class_has_exactly_the_five_members():
    """D-08 / D-10: exactly the five route-classification failure classes."""
    assert set(FailureClass.__members__) == {
        "SETTLEMENT",
        "ORDER_IO",
        "ADMISSION",
        "LOOP_BACKSTOP",
        "FILL_TRANSLATION",
    }
    assert len(list(FailureClass)) == 5


def test_failure_class_values_are_lowercase_hyphen_literals():
    """.value mirrors the HaltReason wire-string house style (descriptive only)."""
    assert FailureClass.SETTLEMENT.value == "settlement"
    assert FailureClass.ORDER_IO.value == "order-io"
    assert FailureClass.ADMISSION.value == "admission"
    assert FailureClass.LOOP_BACKSTOP.value == "loop-backstop"
    assert FailureClass.FILL_TRANSLATION.value == "fill-translation"


def test_failure_class_barrel_export_matches_direct_import():
    """FailureClass re-exports from the barrel (same object as the module)."""
    from itrader.core.enums.system import FailureClass as _Direct

    assert FailureClass is _Direct
