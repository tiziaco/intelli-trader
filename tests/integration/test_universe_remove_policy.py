"""Orphan-and-track remove policy — deterministic multi-symbol paper/replay proof (06-04).

Behavior (D-01 DEFAULT ``orphan-and-track``): when a symbol still holding an open
position is removed from the universe, the engine keeps its WS/ring ALIVE (defers the
unsubscribe), BLOCKS new entries for it (audited ``ADMISSION_LEAVING``), and DETACHES it
only once the orphaned position goes flat (unsubscribe + clear the leaving set on the
resulting FILL). Never a forced exit.

This drives a two-symbol universe through the REAL synchronous paper path (RESEARCH §10):
bars for both symbols flow through ``LiveBarFeed.update`` (the same provider->feed seam
OKX uses), the position opens/closes through the REUSED ``SimulatedExchange``, and the
plan-04 remove-policy consumer / detach-on-flat hook read the REAL ``PortfolioHandler`` as
their open-position truth. Fully offline — no live venue is touched.

Carries the ``integration`` marker AUTOMATICALLY via the ``tests/integration/`` path
(folder-derived TYPE auto-marking) — not hand-added.
"""

from decimal import Decimal


def test_orphan_and_track_defers_unsubscribe_blocks_entry_detaches_on_flat(
    remove_policy_harness,
):
    """Orphan-and-track: defer-until-flat + new-entry block + detach-on-flat, end-to-end."""
    harness = remove_policy_harness(remove_policy="orphan-and-track")
    held = harness.held_symbol
    other = harness.other_symbol

    # Open a real long on the soon-to-be-removed symbol (fills via SimulatedExchange).
    harness.open_long(held, price="100")
    assert harness.position_qty(held) > 0
    # Second symbol's ring is driven too — this is a genuine two-symbol replay.
    harness.drive_bar(other, price="50")

    # Scripted REMOVE while the symbol still holds a position (orphan-and-track).
    harness.remove(held)

    # (a) WS/ring stays ALIVE — no unsubscribe; symbol marked leaving; ring keeps
    #     receiving bars after the removal.
    assert harness.provider.unsubscribed == []
    assert held in harness.universe.leaving_symbols()
    harness.drive_bar(held, price="101")
    assert harness.system.feed.newest_bar(held) is not None
    assert harness.system.feed.newest_bar(held).close == Decimal("101")

    # (b) A NEW-entry signal for the leaving symbol is audited-REJECTED (ADMISSION_LEAVING)
    #     and emits NO order — no fresh exposure can open.
    results = harness.submit_new_entry(held, price="101")
    assert len(results) == 1
    assert results[0].success is False
    assert "leaving" in (results[0].error_details or results[0].message).lower()
    assert results[0].order_events == ()
    assert harness.has_audited_leaving_rejection(held)
    # The blocked entry did not change the open position.
    assert harness.position_qty(held) > 0

    # (c) A sanctioned exit PASSES the gate and settles; on the resulting flat FILL the
    #     symbol detaches (unsubscribe + cleared from the leaving set).
    harness.emit_exit_and_settle(held, price="101")
    assert harness.position_qty(held) == Decimal("0")

    harness.fire_flat_fill(held)
    assert harness.provider.unsubscribed == [held]
    assert held not in harness.universe.leaving_symbols()
