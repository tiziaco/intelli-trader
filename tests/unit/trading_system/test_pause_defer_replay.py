"""A8 (D-14 / V17-11) RED gate — protective orders must survive a submission pause.

CONF-A spine (D-19), Wave-1 slice 3. This is an EXPECTED-FAILING regression test: it pins
the V17-11 dropped-protective-order bug and turns GREEN only once the D-14 defer+replay path
lands in Phase 05.3. It MUST be RED against current code — that is the success condition of a
CONF-A spine plan, NOT a broken build.

The bug (V17-11)
----------------
While submission is paused-on-disconnect (or HALTED), ``LiveTradingSystem._dispatch_live``
(``live_trading_system.py:736-741``) SUPPRESSES **every** SIGNAL/ORDER event with NO defer
queue and NO replay. That is correct for a fresh ENTRY (don't open new risk while blind to
the venue), but catastrophic for the RISK-REDUCING orders a draining FILL generates during
the pause window:

- a **bracket-child submission** (the stop-loss / take-profit protecting a just-filled
  entry) — dropped, so the position is left NAKED; and
- an **OCO / orphan CANCEL** — dropped, so a stale resting order lingers.

When the pause lifts, nothing is replayed: the protection is simply gone.

The fix (D-14, Phase 05.3)
--------------------------
During a pause, DEFER the protective orders (bracket children + cancels) onto a replay queue
and REPLAY them on resume; keep suppressing fresh ENTRIES; and ALWAYS let a CANCEL through
immediately (a cancel only reduces risk).

These tests drive the pause gate (``_dispatch_live``) directly with the OrderEvents a FILL
would generate — that is the exact code site D-14 modifies. Three arms:
1. a protective bracket-child order is DEFERRED then REPLAYED on resume (RED today: dropped);
2. a fresh ENTRY stays suppressed and is never replayed (control — passes now and after D-14);
3. a CANCEL command is ALWAYS dispatched, even mid-pause (RED today: suppressed).

Fully offline: a credential-free ``LiveTradingSystem`` on the default (non-OKX) venue; the
engine-thread resume path is driven directly (no daemon thread, no network). New test dir is
package-less (no ``__init__.py``) to avoid the full-suite package-collision. Folder-derived
``unit`` marker.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List
from unittest.mock import MagicMock

import pytest

from itrader.core.enums import OrderCommand, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import OrderEvent
from itrader.trading_system.live_trading_system import LiveTradingSystem


def _live_system(monkeypatch: Any) -> LiveTradingSystem:
    """A credential-free LiveTradingSystem for the default (non-OKX) venue."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    return LiveTradingSystem.for_exchange("binance")


def _order_event(
    *, command: OrderCommand = OrderCommand.NEW, parent: OrderId | None = None
) -> OrderEvent:
    """An OrderEvent; ``parent`` set marks it a protective bracket child (risk-reducing)."""
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.SELL if parent is not None else Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=PortfolioId(uuid.uuid4()),
        order_type=OrderType.LIMIT,
        order_id=OrderId(uuid.uuid4()),
        parent_order_id=parent,
        command=command,
    )


def _record_dispatch(system: LiveTradingSystem) -> List[Any]:
    """Replace the inner dispatch with a recorder; return the list it appends to.

    The injected SafetyController gate dispatches through a LATE-BOUND lambda over
    ``event_handler._dispatch``, so patching it here is honoured by ``gate_and_dispatch``
    (and by the deferred-protective replay on resume).
    """
    dispatched: List[Any] = []
    system.event_handler._dispatch = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda ev: dispatched.append(ev))
    return dispatched


def _resume_via_engine_thread(system: LiveTradingSystem) -> None:
    """Drive the engine-thread reconnect-resume (§11c): the STREAM_STATE(up) route target.

    On a non-OKX venue the StreamRecoveryHandler's arms are all None (catch-up + snapshot
    skipped, streams healthy), so ``on_reconnect`` resumes submission — which drains the
    D-14 deferred-protective replay queue on the injected SafetyController.
    """
    system._stream_recovery.on_reconnect()


def test_pause_defer_replay_protective_order_replayed_on_resume(monkeypatch: Any) -> None:
    """A protective bracket-child order deferred during a pause must be REPLAYED on resume (A8).

    RED today: ``_dispatch_live`` drops the protective ORDER with no defer/replay queue, so it
    never reaches ``_dispatch`` even after the pause lifts — the just-filled position is left
    naked. GREEN after D-14 (Phase 05.3) defers + replays it on resume.
    """
    system = _live_system(monkeypatch)
    dispatched = _record_dispatch(system)
    system.pause_submission("paused-on-disconnect")

    protective = _order_event(command=OrderCommand.NEW, parent=OrderId(uuid.uuid4()))
    system._safety.gate_and_dispatch(protective)
    # Suppressed WHILE paused (correct both now and after the fix — it is deferred, not sent).
    assert protective not in dispatched

    _resume_via_engine_thread(system)

    assert protective in dispatched, (
        "A8/V17-11: a protective bracket-child order generated during the pause was DROPPED, "
        "not replayed on resume — _dispatch_live suppresses ALL ORDER events while paused with "
        "no defer/replay queue, so the just-filled position is left naked. D-14 (Phase 05.3) "
        "must defer protective orders and replay them on resume."
    )


def test_pause_defer_replay_entry_stays_suppressed(monkeypatch: Any) -> None:
    """A fresh ENTRY order stays suppressed and is never replayed (A8 over-fit guard).

    Passes today AND must after D-14: only risk-REDUCING protective orders are deferred+replayed;
    a fresh entry opens new risk while the engine is blind to the venue and must stay suppressed.
    Guards against an over-broad replay-everything fix.
    """
    system = _live_system(monkeypatch)
    dispatched = _record_dispatch(system)
    system.pause_submission("paused-on-disconnect")

    entry = _order_event(command=OrderCommand.NEW, parent=None)
    system._safety.gate_and_dispatch(entry)
    assert entry not in dispatched  # suppressed while paused

    _resume_via_engine_thread(system)

    assert entry not in dispatched, (
        "A8/V17-11 (over-fit guard): a fresh ENTRY order must STAY suppressed and never be "
        "replayed — only protective (risk-reducing) orders are deferred+replayed (D-14). A "
        "replay-everything fix that resends entries would re-open risk taken while blind."
    )


def test_pause_defer_replay_cancel_always_dispatched(monkeypatch: Any) -> None:
    """A CANCEL command must ALWAYS pass the pause gate, even mid-pause (A8).

    RED today: ``_dispatch_live`` suppresses ALL ORDER events while paused, including CANCELs,
    so a stale/orphan order cannot be cancelled during the pause window. GREEN after D-14 lets
    cancels through immediately — a cancel only REDUCES risk.
    """
    system = _live_system(monkeypatch)
    dispatched = _record_dispatch(system)
    system.pause_submission("paused-on-disconnect")

    cancel = _order_event(command=OrderCommand.CANCEL, parent=None)
    system._safety.gate_and_dispatch(cancel)

    assert cancel in dispatched, (
        "A8/V17-11: a CANCEL command was suppressed during the pause — a cancel only REDUCES "
        "risk and must ALWAYS pass the pause gate (never dropped). Today _dispatch_live "
        "suppresses every ORDER event while paused. D-14 (Phase 05.3) must let cancels through."
    )
