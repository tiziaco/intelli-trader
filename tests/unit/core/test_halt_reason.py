"""Characterization tests for CFG-05 / D-10 (typed ``HaltReason`` vocabulary).

These pin the minimal ``HaltReason`` enum P1 introduces (design D-10/D-11):

  1. Exactly the FOUR reasons that reach ``halt()`` / ``_update_status(halt_reason=)``
     today — ``BASELINE_RESIDUAL`` / ``CONNECTOR_FATAL`` /
     ``RECONCILIATION_UNRESOLVED`` / ``DURABLE_HALT``. No more, no fewer.
  2. Each member's ``.value`` equals its EXISTING wire string, so durable halt
     records persisted before the change still resolve (T-02-01, no data migration).
  3. Absence guard — no ``DRIFT`` (comment-only, no live ``halt('drift')`` call) and
     no ``PAUSED_ON_DISCONNECT`` (a ``pause_submission`` reason, not a halt). Dead
     members are forbidden per D-10 ("minimal vocabulary").
"""

import pytest

from itrader.core.enums import HaltReason

pytestmark = pytest.mark.unit


def test_halt_reason_has_exactly_the_four_minimal_members():
    """D-10: exactly the 4 reasons that reach halt() today — no more, no fewer."""
    assert set(HaltReason.__members__) == {
        "BASELINE_RESIDUAL",
        "CONNECTOR_FATAL",
        "RECONCILIATION_UNRESOLVED",
        "DURABLE_HALT",
    }


def test_halt_reason_member_values_are_the_existing_wire_strings():
    """T-02-01: each .value equals its existing wire string (durable records still resolve)."""
    assert HaltReason.BASELINE_RESIDUAL.value == "baseline-residual"
    assert HaltReason.CONNECTOR_FATAL.value == "connector-fatal"
    assert HaltReason.RECONCILIATION_UNRESOLVED.value == "reconciliation-unresolved"
    assert HaltReason.DURABLE_HALT.value == "durable-halt"


def test_halt_reason_wire_strings_round_trip_to_members():
    """T-02-01: HaltReason('baseline-residual') → HaltReason.BASELINE_RESIDUAL (value-to-member identity)."""
    assert HaltReason("baseline-residual") is HaltReason.BASELINE_RESIDUAL
    assert HaltReason("connector-fatal") is HaltReason.CONNECTOR_FATAL
    assert HaltReason("reconciliation-unresolved") is HaltReason.RECONCILIATION_UNRESOLVED
    assert HaltReason("durable-halt") is HaltReason.DURABLE_HALT


def test_halt_reason_excludes_drift_and_paused_on_disconnect():
    """D-10: DRIFT (comment-only) and PAUSED_ON_DISCONNECT (a pause, not a halt) are NOT members."""
    assert "DRIFT" not in HaltReason.__members__
    assert "PAUSED_ON_DISCONNECT" not in HaltReason.__members__
