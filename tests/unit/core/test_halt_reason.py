"""Characterization tests for CFG-05 / D-10 (typed ``HaltReason`` vocabulary).

These pin the ``HaltReason`` enum P1 introduces (design D-10/D-11):

  1. Exactly the FIVE reasons that reach ``halt()`` / ``_update_status(halt_reason=)``
     today — ``BASELINE_RESIDUAL`` / ``CONNECTOR_FATAL`` /
     ``RECONCILIATION_UNRESOLVED`` / ``DURABLE_HALT`` / ``DRIFT``. One member per
     live reason, no dead members.
  2. Each member's ``.value`` equals its EXISTING wire string, so durable halt
     records persisted before the change still resolve (T-02-01, no data migration).
  3. Absence guard — no ``PAUSED_ON_DISCONNECT`` (a ``pause_submission`` reason,
     not a halt). ``DRIFT`` IS a member: ``portfolio_handler`` fires
     ``_halt_signal("drift")`` and ``LiveTradingSystem`` wires that signal to
     ``self.halt`` (``set_halt_signal(self.halt)``), so ``halt("drift")`` is a
     live, reachable call (CR-01).
"""

import pytest

from itrader.core.enums import HaltReason

pytestmark = pytest.mark.unit


def test_halt_reason_has_the_five_original_plus_four_tripwire_members():
    """D-10 / CR-01 + D-16: the 5 original reachable reasons plus the 4 P8 tripwire reasons.

    P1 pinned exactly the 5 reasons that reach ``halt()`` today. Phase 8 (D-16)
    adds one typed HaltReason per ``FailureClass`` for the CF-1 failure-rate
    tripwire — ``SETTLEMENT_FAILURE`` / ``ORDER_ROUTE_ERRORS`` /
    ``ADMISSION_ERRORS`` / ``LOOP_BACKSTOP`` (FILL_TRANSLATION reuses
    SETTLEMENT_FAILURE). Additive only — the 5 originals are byte-unchanged.
    """
    assert set(HaltReason.__members__) == {
        "BASELINE_RESIDUAL",
        "CONNECTOR_FATAL",
        "RECONCILIATION_UNRESOLVED",
        "DURABLE_HALT",
        "DRIFT",
        # D-16 tripwire reasons (Phase 8):
        "SETTLEMENT_FAILURE",
        "ORDER_ROUTE_ERRORS",
        "ADMISSION_ERRORS",
        "LOOP_BACKSTOP",
    }


def test_halt_reason_member_values_are_the_existing_wire_strings():
    """T-02-01: each .value equals its existing wire string (durable records still resolve)."""
    assert HaltReason.BASELINE_RESIDUAL.value == "baseline-residual"
    assert HaltReason.CONNECTOR_FATAL.value == "connector-fatal"
    assert HaltReason.RECONCILIATION_UNRESOLVED.value == "reconciliation-unresolved"
    assert HaltReason.DURABLE_HALT.value == "durable-halt"
    assert HaltReason.DRIFT.value == "drift"


def test_halt_reason_d16_tripwire_member_values():
    """D-16: the 4 new tripwire reasons carry new lowercase-hyphen wire strings."""
    assert HaltReason.SETTLEMENT_FAILURE.value == "settlement-failure"
    assert HaltReason.ORDER_ROUTE_ERRORS.value == "order-route-errors"
    assert HaltReason.ADMISSION_ERRORS.value == "admission-errors"
    assert HaltReason.LOOP_BACKSTOP.value == "loop-backstop"


def test_halt_reason_wire_strings_round_trip_to_members():
    """T-02-01: HaltReason('baseline-residual') → HaltReason.BASELINE_RESIDUAL (value-to-member identity)."""
    assert HaltReason("baseline-residual") is HaltReason.BASELINE_RESIDUAL
    assert HaltReason("connector-fatal") is HaltReason.CONNECTOR_FATAL
    assert HaltReason("reconciliation-unresolved") is HaltReason.RECONCILIATION_UNRESOLVED
    assert HaltReason("durable-halt") is HaltReason.DURABLE_HALT
    assert HaltReason("drift") is HaltReason.DRIFT


def test_halt_reason_excludes_paused_on_disconnect():
    """D-10: PAUSED_ON_DISCONNECT is a pause_submission() reason, not a halt — NOT a member.

    ``drift`` is deliberately NOT excluded: it is a live ``halt('drift')`` reason
    (portfolio_handler._halt_signal('drift') → LiveTradingSystem.halt), so it IS a
    member — see test_halt_reason_has_exactly_the_five_reachable_members (CR-01).
    """
    assert "PAUSED_ON_DISCONNECT" not in HaltReason.__members__
