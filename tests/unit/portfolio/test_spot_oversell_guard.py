"""Fix A regression tests (OVERSELL-A / CR-02): the spot settlement path must
fail loud on an over-close SELL.

Root cause: `.planning/debug/spot-long-only-oversell.md` — the CR-02 over-close
guard lived ONLY on the margin settlement path; the SPOT path
(`_process_transaction_spot`) applied any SELL fill unconditionally, so a SELL
whose quantity EXCEEDS the held long settled silently (no exception, no clamp),
seeding net-short inventory mislabeled side=LONG with phantom positive equity.

These mirror the CR-02 margin analog tests at
tests/unit/portfolio/test_portfolio.py:426-509 but for the SPOT path
(enable_margin defaults False). The over-close test is RED before the Task-2 fix
and GREEN after; the exact/partial/scale-in tests are non-regression.
"""

from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader.core.exceptions import InvalidTransactionError
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


@pytest.fixture
def spot_portfolio():
    """A fresh SPOT simulated portfolio (enable_margin defaults False)."""
    return Portfolio("spot_pf", "simulated", 150000, datetime.now())


def _txn(txn_type, ticker, price, qty):
    """Build a zero-commission spot transaction with the test_portfolio idiom."""
    return Transaction(
        datetime.now(), txn_type, ticker, price, qty, 0, None,
        idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )


def test_spot_over_close_fill_fails_loud(spot_portfolio):
    """OVERSELL-A / CR-02 (spot): a SELL whose quantity EXCEEDS the held long
    (the silent over-sell from the debug repro: BUY 1 then SELL 5) must RAISE
    InvalidTransactionError BEFORE any mutation — never silently settle a
    net-short inventory under a stale side=LONG label."""
    pf = spot_portfolio
    # Open 1 unit @ 89591.
    pf.process_transaction(_txn(TransactionType.BUY, "BTCUSDT", 89591, 1))

    # Over-close: SELL 5 of an open 1 (would leave a residual net-short).
    over_close = _txn(TransactionType.SELL, "BTCUSDT", 89591, 5)
    with pytest.raises(InvalidTransactionError):
        pf.process_transaction(over_close)


def test_spot_sub_tolerance_over_close_absorbs_as_clean_close(spot_portfolio):
    """260623-h6i: a sub-tolerance over-close (excess << PositionManager.tolerance,
    1e-5) must NOT raise — it is Decimal quantization dust (the 1E-27 per-add
    bracket-child requantization on a pyramided position), not a real over-sell.
    BUY 1 then SELL 1 + 1e-9 @ 1000: the 1e-9 excess passes the tolerance-aware
    guard and `_should_close_position` (abs(net) <= tolerance) settles it to flat.
    Decimal-typed qty so the 1e-9 excess is exact, never a float artifact."""
    pf = spot_portfolio
    pf.process_transaction(_txn(TransactionType.BUY, "BTCUSDT", 1000, Decimal("1")))

    # Over-close by 1e-9 (<< tolerance 1e-5) — must NOT raise, settles to flat.
    over_close = _txn(TransactionType.SELL, "BTCUSDT", 1000, Decimal("1") + Decimal("1e-9"))
    pf.process_transaction(over_close)

    assert len(pf.positions) == 0
    assert len(pf.closed_positions) == 1


def test_spot_exact_full_close_still_succeeds(spot_portfolio):
    """The over-close guard must NOT regress an exact full-close: SELL == held
    qty settles to flat without raising (non-regression)."""
    pf = spot_portfolio
    pf.process_transaction(_txn(TransactionType.BUY, "BTCUSDT", 89591, 1))
    pf.process_transaction(_txn(TransactionType.SELL, "BTCUSDT", 89591, 1))  # must NOT raise

    assert len(pf.positions) == 0
    assert len(pf.closed_positions) == 1


def test_spot_partial_close_still_succeeds(spot_portfolio):
    """The over-close guard must NOT regress a partial-close: SELL < held qty
    keeps the position open (non-regression). Priced @ 1000 so the 4-unit open
    (4000) fits the $150000 spot cash budget."""
    pf = spot_portfolio
    pf.process_transaction(_txn(TransactionType.BUY, "BTCUSDT", 1000, 4))
    pf.process_transaction(_txn(TransactionType.SELL, "BTCUSDT", 1000, 1))  # must NOT raise

    position = pf.positions["BTCUSDT"]
    assert position.net_quantity == Decimal("3")


def test_spot_scale_in_still_succeeds(spot_portfolio):
    """The guard fires only on reductions: a same-side increase (BUY 1 then
    BUY 2) does NOT raise and yields net_quantity == 3 (non-regression).
    Priced @ 1000 so the cumulative 3-unit notional fits cash."""
    pf = spot_portfolio
    pf.process_transaction(_txn(TransactionType.BUY, "BTCUSDT", 1000, 1))
    pf.process_transaction(_txn(TransactionType.BUY, "BTCUSDT", 1000, 2))  # must NOT raise

    position = pf.positions["BTCUSDT"]
    assert position.net_quantity == Decimal("3")
