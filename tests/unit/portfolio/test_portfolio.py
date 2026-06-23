from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader.core.enums import CashOperationType, PositionSide
from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError,
)
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


@pytest.fixture
def portfolio():
    """A fresh simulated portfolio funded with $150000."""
    return Portfolio(1, "test_pf", "simulated", 150000, datetime.now())


def test_long_position(portfolio):
    """
    Purchase/sell multiple lots of BTC and ETH at various prices/commissions to
    check the logic handling of the portfolio.
    """
    # Buy 1 of BTC over one transactions
    buy_txn = Transaction(datetime.now(), TransactionType.BUY,
                          "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn)

    # Sell 1 of BTC over one transactions
    sell_txn = Transaction(datetime.now(), TransactionType.SELL,
                           "BTCUSDT", 42000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert portfolio.cash == 152000
    assert portfolio.total_equity == 152000
    assert portfolio.total_unrealised_pnl == 0


def test_short_position(portfolio):
    """Sell then buy back a single BTC unit (short round-trip)."""
    # Sell 1 of BTC over one transactions
    sell_txn = Transaction(datetime.now(), TransactionType.SELL,
                           "BTCUSDT", 42000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn)

    # Buy 1 of BTC over one transactions
    buy_txn = Transaction(datetime.now(), TransactionType.BUY,
                          "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn)

    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert portfolio.cash == 152000
    assert portfolio.total_equity == 152000
    assert portfolio.total_unrealised_pnl == 0


def test_multiple_buys_followed_by_sell(portfolio):
    # Buy 2 units of BTC at $38000
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn1)

    # Buy 1 unit of BTC at $40000
    buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn2)

    # Sell 1 unit of BTC at $45000
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 45000, 3, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 0  # No position remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 169000  # Cash after transactions
    assert portfolio.total_equity == 169000  # Total equity after transactions
    assert portfolio.total_unrealised_pnl == 0  # Total unrealized P&L
    assert portfolio.total_realised_pnl == pytest.approx(19000, abs=0.01)  # Total realized P&L


def test_sell_followed_by_multiple_buys(portfolio):
    # Sell 3 unit of BTC at $45000
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 45000, 3, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn)

    # Buy 1 units of BTC at $40000
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn1)

    # Buy 2 unit of BTC at $38000
    buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn2)

    assert len(portfolio.positions) == 0  # No positions remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 169000  # Cash after transactions
    assert portfolio.total_equity == 169000  # Total equity after transactions
    assert portfolio.total_unrealised_pnl == 0  # Total unrealized P&L
    assert portfolio.total_realised_pnl == pytest.approx(19000, abs=0.01)  # Total realized P&L


def test_transaction_with_commission(portfolio):
    # Buy 2 units of BTC at $38000 with $100 commission
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 100, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn1)

    # Sell 2 units of BTC at $40000 with $100 commission
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 40000, 2, 100, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 0  # No position remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 154000 - 200  # Cash after transactions considering commissions
    assert portfolio.total_realised_pnl == 4000 - 200  # Realized P&L after commissions


def test_partial_closure(portfolio):
    # Buy 3 units of BTC at $40000 (total: $120,000 - within $150,000 budget)
    buy_txn = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 3, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn)

    # Sell 2 units of BTC at $45000 (partial closure)
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 45000, 2, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 1  # One position remaining
    assert portfolio.positions["BTCUSDT"].net_quantity == 1  # 1 unit remaining
    assert portfolio.cash == 150000 - (40000 * 3) + (45000 * 2)  # Cash after transactions
    assert portfolio.total_realised_pnl == 10000  # Realized P&L for the closed portion (2 * $5000)


def test_multiple_assets(portfolio):
    # Buy 1 unit of BTC at $40000
    buy_btc = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_btc)

    # Buy 2 units of ETH at $2500
    buy_eth = Transaction(datetime.now(), TransactionType.BUY, "ETHUSDT", 2500, 2, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_eth)

    # Sell 1 unit of BTC at $42000
    sell_btc = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 42000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_btc)

    assert len(portfolio.positions) == 1  # One position remaining (ETH)
    assert len(portfolio.closed_positions) == 1  # One position (BTC) closed
    assert portfolio.positions["ETHUSDT"].net_quantity == 2  # 2 units of ETH remaining
    assert portfolio.cash == 150000 - 40000 + 42000 - 2500 * 2  # Cash after transactions
    assert portfolio.total_realised_pnl == 2000  # Realized P&L for BTC


def test_mixed_buy_sell_transactions(portfolio):
    # Buy 2 units of BTC at $38000
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn1)

    # Sell 1 unit of BTC at $40000
    sell_txn1 = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn1)

    # Buy 1 unit of BTC at $37000
    buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 37000, 1, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(buy_txn2)

    # Sell 2 units of BTC at $39000
    sell_txn2 = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 39000, 2, 0, None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7())
    portfolio.process_transaction(sell_txn2)

    assert len(portfolio.positions) == 0  # No position remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 155000  # Cash after transactions
    assert portfolio.total_realised_pnl == pytest.approx(5000, abs=0.01)  # Realized P&L


# ---------------------------------------------------------------------------
# Atomic validate-first settlement (Plan 05-05 Task 2 — D-09/D-10/D-11/D-12)
# ---------------------------------------------------------------------------


def _txn(type_, ticker, price, quantity, commission=0):
    return Transaction(
        datetime(2021, 3, 14, 9, 26, 53), type_, ticker, price, quantity,
        commission, None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )


def test_failed_validation_leaves_position_and_cash_untouched(portfolio):
    """M4-02 regression lock (D-09): nothing mutates until all checks pass.

    The 'BT' ticker passes the position manager's own checks but fails
    TransactionManager validation — under the old position-first ordering
    this left a mutated position behind.
    """
    invalid = _txn(TransactionType.BUY, "BT", 40000, 1)

    with pytest.raises(InvalidTransactionError):
        portfolio.process_transaction(invalid)

    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 0
    assert portfolio.cash == Decimal("150000.00")
    assert len(portfolio.transactions) == 0


def test_buy_exceeding_balance_raises_before_position_mutation(portfolio):
    """D-10 invariant guard: actual net cost > balance raises typed
    InsufficientFundsError BEFORE any position mutation."""
    too_big = _txn(TransactionType.BUY, "BTCUSDT", 40000, 10)  # 400k > 150k

    with pytest.raises(InsufficientFundsError):
        portfolio.process_transaction(too_big)

    assert len(portfolio.positions) == 0
    assert portfolio.cash == Decimal("150000.00")
    assert len(portfolio.transactions) == 0


def test_successful_settlement_orders_ledger_and_history(portfolio):
    """D-12 sequence: validate -> invariant -> position -> ONE ledger entry
    (amount = signed net delta, fee = commission) -> recorded in history."""
    buy = _txn(TransactionType.BUY, "BTCUSDT", 40000, 1, commission=100)

    portfolio.process_transaction(buy)

    # Position mutated.
    assert len(portfolio.positions) == 1
    assert buy.position_id is not None

    # Exactly one ledger entry for the fill: signed net delta + fee (D-06),
    # event-derived timestamp (Pitfall 5), transaction-id reference.
    debits = portfolio.cash_manager.get_cash_operations(
        operation_type=CashOperationType.TRANSACTION_DEBIT
    )
    assert len(debits) == 1
    entry = debits[0]
    assert entry.amount == Decimal("-40100")  # -(40000 * 1 + 100)
    assert entry.fee == Decimal("100")
    assert entry.timestamp == buy.time
    assert entry.reference_id == str(buy.id)

    # Cash applied at full precision; transaction recorded in seam history.
    assert portfolio.cash == Decimal("150000.00") - Decimal("40100")
    assert len(portfolio.transactions) == 1
    assert portfolio.transactions[0] is buy


def test_process_transaction_returns_none_on_success(portfolio):
    """D-10 one-channel contract: None on success, raise typed on failure."""
    buy = _txn(TransactionType.BUY, "BTCUSDT", 40000, 1)
    assert portfolio.process_transaction(buy) is None


def test_transact_shares_returns_none_on_success(portfolio):
    """D-10 contract propagation: transact_shares is raise/None too."""
    buy = _txn(TransactionType.BUY, "BTCUSDT", 40000, 1)
    assert portfolio.transact_shares(buy) is None


def test_transaction_carries_fill_id(portfolio):
    """D-11: the recorded Transaction entity carries the originating fill_id."""
    fill_id = uuid_compat.uuid7()
    buy = Transaction(
        datetime(2021, 3, 14), TransactionType.BUY, "BTCUSDT", 40000, 1,
        0, None, idgen.generate_transaction_id(), fill_id=fill_id,
    )

    portfolio.process_transaction(buy)

    assert portfolio.transactions[0].fill_id == fill_id


def test_cash_property_is_read_only(portfolio):
    """D-05: the cash setter is deleted — assigning cash raises AttributeError."""
    with pytest.raises(AttributeError):
        portfolio.cash = Decimal("1.00")


# ---------------------------------------------------------------------------
# Lock-and-settle margin mode (Plan 02-04 Task 3 — D-09/D-11, byte-exact site #2)
# ---------------------------------------------------------------------------


@pytest.fixture
def margin_portfolio():
    """A $150000 portfolio with enable_margin=True (lock-and-settle on)."""
    pf = Portfolio(1, "margin_pf", "simulated", 150000, datetime.now())
    pf.update_config({"trading_rules": {"enable_margin": True, "max_leverage": Decimal("10")}})
    return pf


def _levered_txn(type_, ticker, price, quantity, commission, leverage):
    txn = Transaction(
        datetime(2021, 3, 14, 9, 26, 53), type_, ticker, price, quantity,
        commission, None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    txn.leverage = Decimal(str(leverage))
    return txn


def test_locked_margin_open_debits_only_commission(margin_portfolio):
    """D-08/Pitfall 3: opening a levered position debits ONLY commission (not
    the notional) and locks aggregate_notional / L. T-02-11 mitigation.

    Zero commission keeps the notional basis raw (avg_price == price) so the
    lock is exactly notional / L = 100000 / 5 = 20000.
    """
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)

    pf.process_transaction(buy)

    # Zero commission -> balance unchanged; ONLY the lock moves buying power.
    assert pf.cash == Decimal("150000")
    # locked = notional / L = (50000 * 2) / 5 = 20000.
    assert pf.cash_manager.locked_margin_total == Decimal("20000")
    # available = balance - reserved - locked = 150000 - 0 - 20000 = 130000.
    assert pf.cash_manager.available_balance == Decimal("130000")


def test_locked_margin_open_with_commission_debits_only_commission(margin_portfolio):
    """The open debit is EXACTLY the commission — never the notional (Pitfall 3)."""
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 50, 5)

    pf.process_transaction(buy)

    # Only the commission left the ledger — NOT the 100000 notional.
    assert pf.cash == Decimal("150000") - Decimal("50")
    # Lock = aggregate_notional / L (avg_price is commission-inflated: D-11 basis).
    position = pf.positions["BTCUSDT"]
    assert pf.cash_manager.locked_margin_total == position.aggregate_notional / Decimal("5")


def test_locked_margin_full_close_settles_pnl_and_releases(margin_portfolio):
    """D-11 full close: release the whole lock, settle realized PnL; balance
    change over the round trip equals realized PnL exactly (zero commission)."""
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)
    pf.process_transaction(buy)

    # realised_pnl (LONG, zero commission) = (55000-50000)*2 = 10000.
    sell = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 2, 0, 5)
    pf.process_transaction(sell)

    # Lock fully released.
    assert pf.cash_manager.locked_margin_total == Decimal("0")
    # Balance change over the round trip == realised PnL (10000).
    assert pf.cash == Decimal("150000") + Decimal("10000")
    assert pf.total_realised_pnl == Decimal("10000")
    # No open positions; equity == cash.
    assert len(pf.positions) == 0
    assert pf.total_equity == pf.cash


def test_locked_margin_full_close_with_commission_round_trip(margin_portfolio):
    """D-11 full close with commissions: the round-trip balance change equals
    the position's realized PnL exactly (open commission not double-counted)."""
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 50, 5)
    pf.process_transaction(buy)
    sell = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 2, 55, 5)

    pf.process_transaction(sell)

    closed = pf.closed_positions[0]
    # Round-trip cash delta == realized PnL (commissions netted exactly once).
    assert pf.cash == Decimal("150000") + closed.realised_pnl
    assert pf.cash_manager.locked_margin_total == Decimal("0")


def test_scale_in_margin_recomputes_lock(margin_portfolio):
    """D-11 scale-in: recompute locked_margin = new_aggregate_notional / L at
    the position's one leverage (release old, lock new)."""
    pf = margin_portfolio
    buy1 = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)
    pf.process_transaction(buy1)
    assert pf.cash_manager.locked_margin_total == Decimal("20000")  # 100000/5

    # Scale in: +1 unit at 50000. New aggregate notional recomputed off the
    # position (avg_price * net_quantity). Lock = new_aggregate_notional / 5.
    buy2 = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 1, 0, 5)
    pf.process_transaction(buy2)

    position = pf.positions["BTCUSDT"]
    expected_lock = position.aggregate_notional / Decimal("5")
    assert pf.cash_manager.locked_margin_total == expected_lock
    # 3 units @ 50000 / 5 = 30000.
    assert pf.cash_manager.locked_margin_total == Decimal("30000")
    # Zero commission -> balance never moved on either open.
    assert pf.cash == Decimal("150000")


def test_partial_close_margin_releases_fraction_and_settles_fraction(margin_portfolio):
    """D-11 partial close fraction p: release p × locked_margin and settle the
    realized-PnL increment for the closed portion; the position stays open."""
    pf = margin_portfolio
    # Open 4 units @ 50000, L=5, zero commission. notional=200000, locked=40000.
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 4, 0, 5)
    pf.process_transaction(buy)
    assert pf.cash_manager.locked_margin_total == Decimal("40000")

    # Partial close: sell 1 of 4 (p = 1/4) @ 55000, zero commission.
    sell = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 1, 0, 5)
    pf.process_transaction(sell)

    position = pf.positions["BTCUSDT"]
    assert position.is_open
    assert position.net_quantity == Decimal("3")

    # Lock recomputed to the remaining notional / L: 3*50000/5 = 30000
    # (== (1 - 1/4) * 40000); i.e. p × 40000 = 10000 was released.
    assert pf.cash_manager.locked_margin_total == Decimal("30000")

    # realised_pnl increment for the closed unit (zero commission):
    #   (55000-50000)*1 = 5000. Balance change == 5000.
    assert pf.cash == Decimal("150000") + Decimal("5000")
    assert pf.total_realised_pnl == Decimal("5000")


def test_margin_over_close_fill_fails_loud(margin_portfolio):
    """CR-02 (Phase-2 mitigation): a margin SELL fill whose quantity EXCEEDS the
    open long (an over-close / flip attempt) must RAISE InvalidTransactionError
    BEFORE any re-lock/settlement — never silently re-lock a flipped position and
    settle a wrong cash delta. Full flip-settlement economics are a Phase-3
    (shorts) concern."""
    pf = margin_portfolio
    # Open 2 units @ 50000, L=5, zero commission. locked = 100000/5 = 20000.
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)
    pf.process_transaction(buy)
    assert pf.cash_manager.locked_margin_total == Decimal("20000")

    # Over-close: SELL 3 of an open 2 (would leave a residual SHORT == flip).
    over_close = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 3, 0, 5)
    with pytest.raises(InvalidTransactionError):
        pf.process_transaction(over_close)


def test_margin_sub_tolerance_over_close_absorbs_as_clean_close(margin_portfolio):
    """260623-h6i: the margin CR-02 twin of the spot sub-tolerance test. A
    sub-tolerance over-close (excess << PositionManager.tolerance, 1e-5) must NOT
    raise — it is Decimal quantization dust, not a real over-close/flip. BUY 2
    then SELL 2 + 1e-9 @ 55000 L=5: the 1e-9 excess passes the tolerance-aware
    CR-02 guard and `_should_close_position` settles it to flat, releasing the
    lock. Decimal-typed qty so the 1e-9 excess is exact, never a float artifact."""
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, Decimal("2"), 0, 5)
    pf.process_transaction(buy)

    # Over-close by 1e-9 (<< tolerance 1e-5) — must NOT raise, settles to flat.
    sell = _levered_txn(
        TransactionType.SELL, "BTCUSDT", 55000, Decimal("2") + Decimal("1e-9"), 0, 5
    )
    pf.process_transaction(sell)

    assert len(pf.positions) == 0
    assert pf.cash_manager.locked_margin_total == Decimal("0")


def test_margin_exact_full_close_still_succeeds(margin_portfolio):
    """The over-close guard must NOT regress an exact full-close: sell == open
    qty settles realized PnL and releases the whole lock unchanged."""
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)
    pf.process_transaction(buy)

    sell = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 2, 0, 5)
    pf.process_transaction(sell)  # must NOT raise

    assert pf.cash_manager.locked_margin_total == Decimal("0")
    assert pf.cash == Decimal("150000") + Decimal("10000")
    assert len(pf.positions) == 0


def test_margin_partial_close_still_succeeds(margin_portfolio):
    """The over-close guard must NOT regress a partial-close: sell < open qty
    settles the fraction and keeps the position open unchanged."""
    pf = margin_portfolio
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 4, 0, 5)
    pf.process_transaction(buy)

    sell = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 1, 0, 5)
    pf.process_transaction(sell)  # must NOT raise

    position = pf.positions["BTCUSDT"]
    assert position.is_open
    assert position.net_quantity == Decimal("3")
    assert pf.cash_manager.locked_margin_total == Decimal("30000")


def test_margin_short_over_cover_fill_fails_loud(margin_portfolio):
    """D-07 (SCALE-03/criterion 3): the SHORT-side mirror of
    test_margin_over_close_fill_fails_loud. A margin BUY fill whose quantity
    EXCEEDS an open SHORT (a flip-to-long attempt) must RAISE
    InvalidTransactionError BEFORE any re-lock/settlement — the CR-02 over-cover
    guard at portfolio.py:399-404 is side-agnostic (is_increase derives from
    side-vs-type at :385-388, so a SHORT+BUY-over-cover is `not is_increase` and
    trips the `transaction.quantity > prior_qty` raise). This regression-locks
    the guard for the SHORT side now that short scale-in is admitted (Plan
    05.1-01); single-order flips stay a deferred close-then-open split."""
    pf = margin_portfolio
    # Open a SHORT of 2 units @ 50000, L=5, zero commission. locked = 100000/5.
    short = _levered_txn(TransactionType.SELL, "BTCUSDT", 50000, 2, 0, 5)
    pf.process_transaction(short)
    position = pf.positions["BTCUSDT"]
    assert position.side is PositionSide.SHORT
    assert pf.cash_manager.locked_margin_total == Decimal("20000")

    # Over-cover: BUY 3 of an open short 2 (would leave a residual LONG == flip).
    over_cover = _levered_txn(TransactionType.BUY, "BTCUSDT", 45000, 3, 0, 5)
    with pytest.raises(InvalidTransactionError):
        pf.process_transaction(over_cover)


def test_margin_short_exact_full_cover_still_succeeds(margin_portfolio):
    """The over-cover guard must NOT regress a legitimate exact full-cover: a
    BUY == the open short qty covers to flat without raising (D-07
    non-regression — the guard does not over-fire on a legitimate cover)."""
    pf = margin_portfolio
    short = _levered_txn(TransactionType.SELL, "BTCUSDT", 50000, 2, 0, 5)
    pf.process_transaction(short)
    assert pf.positions["BTCUSDT"].side is PositionSide.SHORT

    cover = _levered_txn(TransactionType.BUY, "BTCUSDT", 45000, 2, 0, 5)
    pf.process_transaction(cover)  # must NOT raise — settles to flat

    assert pf.cash_manager.locked_margin_total == Decimal("0")
    assert len(pf.positions) == 0


def test_spot_mode_process_transaction_unchanged_byte_exact(portfolio):
    """Pitfall 6 / byte-exact site #2: with enable_margin=False the spot arm is
    UNCHANGED — full notional debited, nothing locked, available == balance."""
    buy = Transaction(
        datetime(2021, 3, 14), TransactionType.BUY, "BTCUSDT", 40000, 1, 100,
        None, idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    portfolio.process_transaction(buy)

    # Full notional debited (spot), no lock.
    assert portfolio.cash == Decimal("150000") - Decimal("40100")
    assert portfolio.cash_manager.locked_margin_total == Decimal("0")
    assert portfolio.cash_manager.available_balance == portfolio.cash
