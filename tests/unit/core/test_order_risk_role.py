"""OrderRiskRole enum tests (D-05/D-16).

Pins the single shared risk-role vocabulary consumed by the SafetyController
dispatch gate (Plan 03) and the PreTradeThrottle (Plan 05):

  1. The three members (CANCEL/PROTECTIVE/ENTRY) exist with member name == .value.
  2. Case-insensitive ``_missing_`` parse (OrderCommand house pattern).
  3. An unknown value raises a clear f-string ``ValueError``.
  4. Per D-16 ONLY the enum lives here — no ``classify()`` in core/enums/order.py.
"""

from types import SimpleNamespace

import pytest

from itrader.core.enums import EventType, OrderCommand, OrderRiskRole

pytestmark = pytest.mark.unit


def test_members_and_values():
    """The three risk roles exist with member name == .value."""
    assert OrderRiskRole.CANCEL.value == "CANCEL"
    assert OrderRiskRole.PROTECTIVE.value == "PROTECTIVE"
    assert OrderRiskRole.ENTRY.value == "ENTRY"
    assert {m.name for m in OrderRiskRole} == {"CANCEL", "PROTECTIVE", "ENTRY"}


def test_parses_case_insensitively():
    """OrderRiskRole('cancel') → OrderRiskRole.CANCEL (case-insensitive parse)."""
    assert OrderRiskRole("cancel") is OrderRiskRole.CANCEL
    assert OrderRiskRole("Protective") is OrderRiskRole.PROTECTIVE
    assert OrderRiskRole("ENTRY") is OrderRiskRole.ENTRY


def test_unknown_value_raises_clear_error():
    """An unknown value raises a clear f-string ValueError."""
    with pytest.raises(ValueError) as exc_info:
        OrderRiskRole("not_a_real_role")
    assert "Unknown OrderRiskRole" in str(exc_info.value)


def test_classify_does_not_live_in_enum_module():
    """D-16: classify() travels with SafetyController (Plan 03), not the enum module."""
    from itrader.core.enums import order as order_enums

    assert not hasattr(order_enums, "classify")


# -- The shared classify() predicate (D-05/D-16; travels with SafetyController) --

def test_classify_cancel_command_is_cancel_role():
    """A CANCEL-command event → OrderRiskRole.CANCEL (risk-reducing)."""
    from itrader.trading_system.safety.safety_controller import classify

    event = SimpleNamespace(
        type=EventType.ORDER, command=OrderCommand.CANCEL, parent_order_id=None)
    assert classify(event) is OrderRiskRole.CANCEL


def test_classify_order_with_parent_is_protective_role():
    """An ORDER with parent_order_id set → OrderRiskRole.PROTECTIVE (bracket child)."""
    from itrader.trading_system.safety.safety_controller import classify

    event = SimpleNamespace(
        type=EventType.ORDER, command=OrderCommand.NEW, parent_order_id=object())
    assert classify(event) is OrderRiskRole.PROTECTIVE


def test_classify_parentless_new_order_is_entry_role():
    """A parentless NEW order → OrderRiskRole.ENTRY (opens new risk)."""
    from itrader.trading_system.safety.safety_controller import classify

    event = SimpleNamespace(
        type=EventType.ORDER, command=OrderCommand.NEW, parent_order_id=None)
    assert classify(event) is OrderRiskRole.ENTRY


def test_classify_raw_signal_is_entry_role():
    """A raw SIGNAL (no command, no parent) → OrderRiskRole.ENTRY."""
    from itrader.trading_system.safety.safety_controller import classify

    event = SimpleNamespace(type=EventType.SIGNAL)
    assert classify(event) is OrderRiskRole.ENTRY
