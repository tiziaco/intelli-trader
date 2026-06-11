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

from itrader.core.enums import (
    ErrorSeverity,
    OrderStatus,
    OrderCommand,
    OrderOperationType,
    OrderTriggerSource,
    order_status_map,
    order_command_map,
)
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


def test_error_severity_member_values():
    """D-03: each ErrorSeverity member's .value equals its uppercase string."""
    assert ErrorSeverity.ERROR.value == "ERROR"
    assert ErrorSeverity.CRITICAL.value == "CRITICAL"
    assert ErrorSeverity.WARNING.value == "WARNING"


def test_error_severity_parses_case_insensitively():
    """D-03: ErrorSeverity('warning') → ErrorSeverity.WARNING (case-insensitive parse)."""
    assert ErrorSeverity("warning") is ErrorSeverity.WARNING
    assert ErrorSeverity("WARNING") is ErrorSeverity.WARNING
    assert ErrorSeverity("critical") is ErrorSeverity.CRITICAL


def test_error_severity_unknown_value_raises_clear_error():
    """D-03: an unknown value raises a clear f-string error (not the printf-tuple form)."""
    with pytest.raises(ValueError) as exc_info:
        ErrorSeverity("not_a_real_severity")
    message = str(exc_info.value)
    assert "not_a_real_severity" in message
    assert "('Value %s'" not in message


# --- D-03: order-domain enums (D-01 class-based OrderStatus/OrderCommand +
#     D-04 OrderOperationType/OrderTriggerSource value-equal vocabularies) ---


def test_order_status_member_values_equal_name():
    """D-01: each OrderStatus member's .value equals its name (string-valued)."""
    assert OrderStatus.PENDING.value == "PENDING"
    assert OrderStatus.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
    assert OrderStatus.FILLED.value == "FILLED"
    assert OrderStatus.CANCELLED.value == "CANCELLED"
    assert OrderStatus.REJECTED.value == "REJECTED"
    assert OrderStatus.EXPIRED.value == "EXPIRED"


def test_order_status_name_serialization_invariant():
    """D-02: OrderStatus serializes via .name (unchanged by the value flip)."""
    assert OrderStatus.PENDING.name == "PENDING"
    assert OrderStatus.FILLED.name == "FILLED"


def test_order_status_parses_case_insensitively():
    """D-01: OrderStatus('pending') → OrderStatus.PENDING (case-insensitive parse)."""
    assert OrderStatus("pending") is OrderStatus.PENDING
    assert OrderStatus("FILLED") is OrderStatus.FILLED


def test_order_status_unknown_value_raises_clear_error():
    """D-01: an unknown value raises a clear f-string error (not the printf-tuple form)."""
    with pytest.raises(ValueError) as exc_info:
        OrderStatus("not_a_real_status")
    message = str(exc_info.value)
    assert "not_a_real_status" in message
    assert "('Value %s'" not in message


def test_order_status_map_round_trip():
    """D-01: order_status_map round-trips a value string to the member."""
    assert order_status_map["FILLED"] is OrderStatus.FILLED
    assert order_status_map[OrderStatus.PENDING.value] is OrderStatus.PENDING


def test_order_command_member_values_and_map():
    """D-01: OrderCommand string values + order_command_map round-trip."""
    assert OrderCommand.NEW.value == "NEW"
    assert OrderCommand.CANCEL.value == "CANCEL"
    assert OrderCommand.MODIFY.value == "MODIFY"
    assert order_command_map["MODIFY"] is OrderCommand.MODIFY


def test_order_command_parses_case_insensitively():
    """D-01: OrderCommand('new') → OrderCommand.NEW (case-insensitive parse)."""
    assert OrderCommand("new") is OrderCommand.NEW
    with pytest.raises(ValueError) as exc_info:
        OrderCommand("not_a_command")
    assert "not_a_command" in str(exc_info.value)


def test_order_operation_type_values_equal_literals():
    """D-04: each OrderOperationType member's .value equals its current literal."""
    assert OrderOperationType.CREATE_PRIMARY_ORDER.value == "create_primary_order"
    assert OrderOperationType.CREATE_STOP_LOSS.value == "create_stop_loss"
    assert OrderOperationType.CREATE_TAKE_PROFIT.value == "create_take_profit"
    assert OrderOperationType.SIGNAL_VALIDATION.value == "signal_validation"
    assert OrderOperationType.SIGNAL_ADMISSION.value == "signal_admission"
    assert OrderOperationType.SIGNAL_SIZING.value == "signal_sizing"
    assert OrderOperationType.CASH_RESERVATION.value == "cash_reservation"
    assert OrderOperationType.MODIFY_ORDER.value == "modify_order"
    assert OrderOperationType.CANCEL_ORDER.value == "cancel_order"


def test_order_operation_type_parses_case_insensitively():
    """D-04: OrderOperationType('CREATE_PRIMARY_ORDER') parses case-insensitively."""
    assert OrderOperationType("create_primary_order") is OrderOperationType.CREATE_PRIMARY_ORDER
    assert OrderOperationType("CREATE_PRIMARY_ORDER") is OrderOperationType.CREATE_PRIMARY_ORDER
    with pytest.raises(ValueError) as exc_info:
        OrderOperationType("not_an_operation")
    assert "not_an_operation" in str(exc_info.value)
    assert "('Value %s'" not in str(exc_info.value)


def test_order_trigger_source_values_equal_literals():
    """D-04: each OrderTriggerSource member's .value equals its current literal."""
    assert OrderTriggerSource.SYSTEM.value == "system"
    assert OrderTriggerSource.STRATEGY.value == "strategy"
    assert OrderTriggerSource.USER.value == "user"
    assert OrderTriggerSource.EXCHANGE.value == "exchange"
    assert OrderTriggerSource.VALIDATOR.value == "validator"
    assert OrderTriggerSource.CASH_RESERVATION.value == "cash_reservation"
    assert OrderTriggerSource.SIZING_POLICY.value == "sizing_policy"
    assert OrderTriggerSource.ADMISSION_DIRECTION.value == "admission_direction"
    assert OrderTriggerSource.ADMISSION_INCREASE.value == "admission_increase"
    assert OrderTriggerSource.ADMISSION_MAX_POSITIONS.value == "admission_max_positions"


def test_order_trigger_source_parses_case_insensitively():
    """D-04: OrderTriggerSource('SYSTEM') parses case-insensitively; unknown raises clearly."""
    assert OrderTriggerSource("system") is OrderTriggerSource.SYSTEM
    assert OrderTriggerSource("SYSTEM") is OrderTriggerSource.SYSTEM
    with pytest.raises(ValueError) as exc_info:
        OrderTriggerSource("not_a_source")
    assert "not_a_source" in str(exc_info.value)
    assert "('Value %s'" not in str(exc_info.value)
