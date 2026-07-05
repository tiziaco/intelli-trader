"""CR-01 — a live restart must not crash on ``VenueAccount.restore_cash`` (05.2 review).

On the live OKX path ``LiveTradingSystem.start()`` runs, in order,
``VenueAccount.snapshot()`` (re-reads the venue's authoritative balance into the
cache), links the ``VenueAccount`` onto each portfolio, then
``PortfolioHandler.rehydrate()`` — which drives
``CachedSqlPortfolioStateStorage.rehydrate`` -> ``account.restore_cash(cash_balance)``
unconditionally when a persisted account-state row exists. Before the gap-closure
fix ``VenueAccount`` never overrode ``restore_cash``, so it inherited the base ABC's
``raise NotImplementedError`` — any live restart with >=1 persisted account-state row
crashed inside ``start()`` (caught -> ``SystemStatus.ERROR``).

This test exercises the REAL ``VenueAccount`` (NOT the ``Simulated*`` compute leaves)
snapshotted via the credential-free ``fake_venue_connector`` double, then drives the
same durable-store ``rehydrate(account)`` restore contract with a persisted cash
scalar. It asserts the restore does NOT raise AND the snapshotted venue balance is
NOT clobbered by the stale persisted engine scalar — the venue is the source of cash
truth (D-14 cache-not-recompute), so ``VenueAccount.restore_cash`` is a documented
no-op. RED before the venue.py fix: ``restore_cash`` raised ``NotImplementedError``.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Dict

from itrader.portfolio_handler.account.venue import VenueAccount
from itrader.portfolio_handler.storage.in_memory_storage import (
    InMemoryPortfolioStateStorage,
)
from tests.support.fake_venue_connector import FakeLiveConnector

# A business time (never wall clock) so the persisted row's timestamp is deterministic.
_BT = datetime(2024, 1, 1, tzinfo=timezone.utc)

# The canned REST balance the ``fake_venue_connector`` snapshot yields (quote USDT total).
_VENUE_SNAPSHOT_BALANCE = Decimal("78999.79")


class _CashDurableStoreDouble(InMemoryPortfolioStateStorage):
    """Durable-store stand-in carrying ONE persisted account-state cash row (CR-01).

    Mirrors the ``CachedSqlPortfolioStateStorage.rehydrate`` -> ``account.restore_cash``
    contract the live restart drives: a persisted cash scalar exists, so ``rehydrate``
    calls ``account.restore_cash(cash_balance)`` unconditionally. Used here to prove a
    ``VenueAccount`` survives that call (no ``NotImplementedError``) and keeps its
    snapshot-owned venue balance.
    """

    def __init__(self, *, durable_cash: Optional[Decimal] = None) -> None:
        super().__init__()
        self._durable_cash: Optional[Decimal] = durable_cash

    def load_account_state(self) -> Optional[Dict[str, Any]]:
        """Return the persisted account-state row, or None if none was persisted."""
        if self._durable_cash is None:
            return None
        return {
            "cash_balance": self._durable_cash,
            "realized_pnl": Decimal("0"),
            "total_equity": self._durable_cash,
            "peak_equity": self._durable_cash,
            "open_positions_count": 0,
            "updated_time": _BT,
        }

    def rehydrate(self, account: Any = None) -> None:
        """Drive the restore contract: push the persisted cash scalar into the account."""
        state = self.load_account_state()
        if account is not None and state is not None:
            account.restore_cash(state["cash_balance"])


def test_venue_account_restart_restore_does_not_raise_or_clobber(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """A durable restore on a snapshotted ``VenueAccount`` is a no-op, not a crash (CR-01).

    The venue snapshot at ``start()`` is authoritative for cash (D-14); the persisted
    engine scalar must NOT overwrite it. Before the fix ``restore_cash`` raised
    ``NotImplementedError`` and the whole live restart failed.
    """
    account = VenueAccount(fake_venue_connector)
    account.snapshot()
    assert account.balance == _VENUE_SNAPSHOT_BALANCE

    # A restart persisted a STALE engine cash scalar; the restore contract fires it at
    # the account. This must NOT raise (the crash CR-01 flagged) ...
    store = _CashDurableStoreDouble(durable_cash=Decimal("12345.67"))
    store.rehydrate(account)

    # ... and must NOT clobber the freshly-snapshotted venue balance (venue is truth).
    assert account.balance == _VENUE_SNAPSHOT_BALANCE


def test_venue_account_restore_cash_is_documented_noop(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """``VenueAccount.restore_cash`` accepts the scalar and leaves the cache untouched."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()
    before = account.balance

    account.restore_cash(Decimal("1.00"))

    assert account.balance == before
