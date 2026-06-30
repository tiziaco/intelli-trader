"""WR-04 regression — assert_lock_fits_buying_power credits the prior lock add-back.

The defect (deferred-items WR-04): the open/scale-in and partial/full-close arms
of ``Portfolio.transact_shares`` called ``cash_manager.release_margin(position_id)``
BEFORE ``cash_manager.assert_lock_fits_buying_power(new_lock, position_id)``. Because
``release_margin`` POPS the position's own lock, the assertion's documented add-back
(``own_prior_lock = get_locked_margin_for(position_id)``) read ``0`` at the moment the
guard ran — the "credit back the position's own prior lock" invariant did not hold
under that call order.

The fix (Option A — assert BEFORE release): the assertion runs while the prior lock is
STILL present, so ``own_prior_lock`` is the TRUE prior value. Numerically the guard's
outcome happens to coincide today (``release_margin`` frees into ``available_balance``
live, so it is conservative-not-a-leak), but the CALL-ORDER CONTRACT — assert reads the
position's own prior lock, not ``0`` — is what protects the FRAGILE margin seam the
04-03 liquidation floor re-touches.

These tests pin two things:
- The CALL-ORDER CONTRACT on the REAL ``Portfolio`` margin path (RED before the fix):
  at both the scale-in site and the partial-close site, the assertion observes the
  position's own prior lock STILL present (``get_locked_margin_for > 0``), proving the
  assert runs before the release.
- The guard still fails LOUD on a genuine over-lock (no leak introduced).

This test file is owned by Plan 04-02 (co-located with the fix, RED before GREEN).
Indentation: 4 SPACES (mirrors ``test_cash_manager.py`` / ``test_portfolio_margin.py``
imports and the 4-space ``cash_manager.py``).
"""

from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.config import PortfolioConfig, get_portfolio_preset, deep_merge
from itrader.core.enums import TransactionType
from itrader.core.exceptions import InsufficientFundsError
from itrader.portfolio_handler.account import SimulatedMarginAccount
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction


def _margin_config(max_leverage: str = "10") -> PortfolioConfig:
    """A PortfolioConfig with enable_margin=True (01-03 selects the account leaf
    at construction, so margin must be set in the constructor config — the old
    post-construction ``update_config`` toggle no longer rebuilds the leaf)."""
    return PortfolioConfig.model_validate(deep_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "max_leverage": Decimal(max_leverage)}},
    ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockPortfolio:
    """Minimal portfolio stub for the isolated margin-account guard test."""

    def __init__(self):
        self.portfolio_id = 12345


@pytest.fixture
def cm():
    """A SimulatedMarginAccount seeded with $10000 on a mock portfolio.

    The margin leaf — ``assert_lock_fits_buying_power`` / ``lock_margin`` live
    on the margin superset after the 01-02 split.
    """
    return SimulatedMarginAccount(_MockPortfolio(), 10000.0)


@pytest.fixture
def margin_portfolio():
    """A $100000 portfolio with enable_margin=True (lock-and-settle on)."""
    return Portfolio(
        "wr04_pf", "simulated", 100000, datetime.now(), config=_margin_config()
    )


def _levered_txn(type_, ticker, price, quantity, commission, leverage):
    txn = Transaction(
        datetime(2021, 3, 14, 9, 26, 53), type_, ticker, price, quantity,
        commission, None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    txn.leverage = Decimal(str(leverage))
    return txn


def _spy_prior_lock_seen_by_assert(pf):
    """Wrap ``assert_lock_fits_buying_power`` to capture the prior lock the guard
    observes at call time. Returns a one-element list updated on each call with
    ``get_locked_margin_for(position_id)`` as seen WHEN the assertion runs.

    Under the WR-04 defect (release-before-assert) the prior lock is already
    popped, so the spy records ``Decimal('0')``. Under the fix it records the
    TRUE prior lock (> 0 on a scale-in / partial close).
    """
    seen: list[Decimal] = []
    cmgr = pf.account
    original = cmgr.assert_lock_fits_buying_power

    def _wrapped(lock_amount, position_id):
        seen.append(cmgr._storage.get_locked_margin_for(position_id))
        return original(lock_amount, position_id)

    cmgr.assert_lock_fits_buying_power = _wrapped  # type: ignore[method-assign]
    return seen


# ---------------------------------------------------------------------------
# Test 1 — scale-in site honours the corrected add-back (call-order contract)
# ---------------------------------------------------------------------------


def test_scale_in_assert_sees_true_prior_lock(margin_portfolio):
    """A scale-in's solvency assertion observes the position's OWN prior lock
    STILL present (assert-before-release). Under the WR-04 defect the prior lock
    was popped first and the guard read ``0``."""
    pf = margin_portfolio
    # Open: lock = (50000 * 1) / 5 = 10000.
    pf.process_transaction(
        _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 1, 0, 5)
    )
    assert pf.account.locked_margin_total == Decimal("10000")

    seen = _spy_prior_lock_seen_by_assert(pf)

    # Scale-in: add 1 @ 50000 -> aggregate 2 * 50000 = 100000, new lock = 20000.
    pf.process_transaction(
        _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 1, 0, 5)
    )

    assert len(seen) == 1
    # The guard must have seen the TRUE prior lock (10000), not 0.
    assert seen[0] == Decimal("10000")
    assert pf.account.locked_margin_total == Decimal("20000")


# ---------------------------------------------------------------------------
# Test 2 — the guard still fails loud on a genuine over-lock (no leak)
# ---------------------------------------------------------------------------


def test_lock_exceeding_buying_power_still_raises(cm):
    """The guard must still fail LOUD — the add-back fix must not silently
    over-credit and introduce a solvency leak."""
    position_id = "POS-1"
    cm.lock_margin(position_id, Decimal("4000"))
    # buying power = (10000 - 4000) + 4000 == 10000; ask for 10000.01.
    with pytest.raises(InsufficientFundsError):
        cm.assert_lock_fits_buying_power(Decimal("10000.01"), position_id)


# ---------------------------------------------------------------------------
# Test 3 — partial-close site honours the same corrected add-back
# ---------------------------------------------------------------------------


def test_partial_close_assert_sees_true_prior_lock(margin_portfolio):
    """A partial close's remaining-lock assertion observes the position's OWN
    prior whole lock STILL present (assert-before-release), so the recomputed
    remaining lock is checked against buying power that credits the true prior
    lock — not ``0`` as under the WR-04 defect."""
    pf = margin_portfolio
    # Open LONG 2 @ 50000, L=5 -> aggregate 100000, lock = 20000.
    pf.process_transaction(
        _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)
    )
    assert pf.account.locked_margin_total == Decimal("20000")

    seen = _spy_prior_lock_seen_by_assert(pf)

    # Partial close: SELL 1 @ 50000 -> remaining 1 @ 50000, remaining lock = 10000.
    pf.process_transaction(
        _levered_txn(TransactionType.SELL, "BTCUSDT", 50000, 1, 0, 5)
    )

    assert len(seen) == 1
    # The guard must have seen the TRUE prior whole lock (20000), not 0.
    assert seen[0] == Decimal("20000")
    assert pf.account.locked_margin_total == Decimal("10000")
