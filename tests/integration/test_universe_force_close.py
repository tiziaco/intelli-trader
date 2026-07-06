"""Force-close remove policy — deterministic settle-then-detach proof (06-04).

Behavior (D-01 ``force-close`` flag): when a symbol still holding an open position is
removed, the engine emits a market EXIT (opposite side, full exit, Decimal money) for the
holding portfolio at removal, then detaches (unsubscribe). The exit SETTLES through the
REUSED ``SimulatedExchange`` (``FillEvent`` -> ``PortfolioHandler.on_fill``, position
flat) — proving the force-close order path end-to-end without a live venue (which the EEA
demo cannot reach a fill on, Phase-5 posture).

Driven through the REAL synchronous paper path (RESEARCH §10): two-symbol replay via
``LiveBarFeed.update``, the reused ``SimulatedExchange`` for settlement, and the plan-04
remove-policy consumer reading the REAL ``PortfolioHandler``. Fully offline.

Carries the ``integration`` marker AUTOMATICALLY via the ``tests/integration/`` path.
"""

from decimal import Decimal

from itrader.core.enums import Side


def test_force_close_emits_exit_settles_via_exchange_then_detaches(remove_policy_harness):
    """Force-close: market exit emitted at removal, settles via the exchange, detaches."""
    harness = remove_policy_harness(remove_policy="force-close")
    held = harness.held_symbol
    other = harness.other_symbol

    # Open a real long, then drive the second symbol (genuine two-symbol replay).
    harness.open_long(held, price="100")
    assert harness.position_qty(held) > 0
    harness.drive_bar(other, price="50")

    # Scripted REMOVE under force-close: emit a market exit for the holder, then detach.
    harness.remove(held)
    assert held in harness.universe.leaving_symbols()
    assert harness.provider.unsubscribed == [held]  # detached at removal

    # A market-exit SignalEvent is queued for the holding portfolio: opposite side of the
    # open long (SELL), full exit, Decimal money (no float leaked into the order path).
    exit_signals = harness.queued_signals(held)
    assert len(exit_signals) == 1
    exit_signal = exit_signals[0]
    assert exit_signal.action is Side.SELL
    assert exit_signal.exit_fraction == Decimal("1")
    assert exit_signal.portfolio_id == harness.portfolio_id
    assert isinstance(exit_signal.price, Decimal)

    # The force-close exit SETTLES through the reused SimulatedExchange: the queued exit
    # order rests, and the next bar fills it -> FillEvent -> PortfolioHandler.on_fill flat.
    harness.process_and_settle(held, price="100")
    assert harness.position_qty(held) == Decimal("0")

    # Detach-on-flat clears the leaving set (the socket was already released at removal).
    harness.fire_flat_fill(held)
    assert held not in harness.universe.leaving_symbols()
