"""Wave-0 characterization stub for M2-09 (order timestamps = event time, injected clock).

Written at Wave 0 of Phase 3 (M2b) under the CURRENT ``test/`` tree so ``make test``
collects it immediately (auto-marked ``orders`` via the ``test_order_handler`` path in
conftest). It pins the two M2-09 behaviors the determinism wave delivers:

  1. ``Order.add_state_change(time=event_time)`` records the EVENT time (NOT
     ``datetime.now()``) — state transitions are driven by the injected/event clock so
     runs are reproducible.
  2. ``modify_order`` routes its state transition THROUGH ``add_state_change`` (no direct
     append to the state-change history that would bypass the event-time path).

Until the M2-09 wave wires the event-time clock through ``add_state_change`` /
``modify_order``, the concrete assertions are gated behind ``pytest.importorskip`` /
``pytest.mark.skip`` so the suite stays GREEN at Wave 0.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_order_handler/``
during the 03-08 type-split — 03-08 reconciles it there without duplication.
"""

import pytest


@pytest.mark.skip(reason="pending M2-09: Order.add_state_change event-time wiring not finalized")
def test_add_state_change_records_event_time():
    """M2-09: add_state_change(time=event_time) records the event time, not datetime.now()."""
    # Pending the M2-09 determinism wave: the event-time clock is threaded through
    # Order.add_state_change so the recorded state-change timestamp equals the passed
    # event time (NOT the wall clock). Asserted live once that wave lands.
    raise AssertionError("unreached — skip-gated pending M2-09")


@pytest.mark.skip(reason="pending M2-09: modify_order → add_state_change routing not finalized")
def test_modify_order_routes_through_add_state_change():
    """M2-09: modify_order routes through add_state_change (no direct history append)."""
    # Pending the M2-09 determinism wave: modify_order must go through add_state_change so
    # the event-time path is the single source of state-change timestamps. Asserted live
    # once that wave lands.
    raise AssertionError("unreached — skip-gated pending M2-09")
