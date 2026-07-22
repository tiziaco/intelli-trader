"""Regression: fee-currency-aware spot settlement (spot-base-fee-drift-halt).

Root cause (`.planning/debug/spot-base-fee-drift-halt.md`): OKX charges the spot
**BUY** taker fee in the **BASE** asset (BTC). The venue credits ``amount - base_fee``
BTC, but the engine used to record the FULL fill ``amount`` as the position and debit
the base-fee as a (unit-mismatched) quote cash outflow. Result: ``engine_qty ==
venue_qty + base_fee`` — the on-fill drift compare tripped ``halt('drift')`` on every
clean demo BUY, and the position was overstated by the fee.

The fix carries the fee **currency** onto the FillEvent / Transaction and branches
settlement on it:

* fee in the pair's **BASE** asset (OKX spot BUY) → deduct it from the **position**
  quantity (net base received = ``amount - base_fee``); NO quote cash debit for it.
* fee in the **QUOTE** asset (OKX spot SELL) → debit **cash** (unchanged behavior).

ORACLE SAFETY: a fill with ``fee_currency=None`` (every backtest/simulated fill) or a
quote-denominated fee takes the CURRENT path byte-for-byte — the SMA_MACD golden oracle
stays byte-exact. These are OFFLINE unit regressions (no network, no demo order) driving
``Portfolio.process_transaction`` directly. Folder-derived ``unit`` marker; 4-space indent.
"""

from datetime import datetime
from decimal import Decimal

import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


_INITIAL_CASH = 150000


def _txn(txn_type, ticker, price, qty, commission=0, fee_currency=None):
    """Build a spot transaction, optionally carrying the venue fee currency."""
    return Transaction(
        datetime.now(), txn_type, ticker, price, qty, commission, None,
        idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
        fee_currency=fee_currency,
    )


def _spot_portfolio():
    """A fresh SPOT simulated portfolio (enable_margin defaults False)."""
    return Portfolio("spot_pf", "paper", _INITIAL_CASH, datetime.now())


def test_base_fee_buy_reduces_position_not_cash():
    """A BASE-denominated fee (OKX spot BUY) nets out of the POSITION, not cash.

    BUY 0.001 BTC/USDC @ 100000 with a 0.000001 BTC base fee:
      * position.net_quantity == 0.001 - 0.000001 == 0.000999 (venue-credited net base)
      * cash == 150000 - (100000 * 0.001) == 149900   (notional only — NO fee cash debit)

    RED before the fix: the base-fee was ignored (position == 0.001) and debited from
    cash (149899.999999), reproducing the engine-overstates-by-base-fee drift.
    """
    pf = _spot_portfolio()
    pf.process_transaction(
        _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.001"),
             commission=Decimal("0.000001"), fee_currency="BTC"))

    position = pf.positions["BTC/USDC"]
    assert position.net_quantity == Decimal("0.000999")
    assert pf.cash == Decimal("149900")


def test_quote_fee_sell_debits_cash_not_position():
    """A QUOTE-denominated fee (OKX spot SELL) debits CASH — unchanged behavior.

    Open 0.001 @ 100000 (no fee), then SELL 0.0005 @ 110000 with a 0.055 USDC quote fee:
      * position.net_quantity == 0.001 - 0.0005 == 0.0005 (full sold qty leaves the base)
      * cash inflow == 0.0005 * 110000 - 0.055 == 54.945 (proceeds minus the quote fee)
    """
    pf = _spot_portfolio()
    pf.process_transaction(
        _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.001")))
    assert pf.cash == Decimal("149900")

    pf.process_transaction(
        _txn(TransactionType.SELL, "BTC/USDC", Decimal("110000"), Decimal("0.0005"),
             commission=Decimal("0.055"), fee_currency="USDC"))

    position = pf.positions["BTC/USDC"]
    assert position.net_quantity == Decimal("0.0005")
    assert pf.cash == Decimal("149954.945")


def test_none_fee_currency_preserves_oracle_behavior():
    """fee_currency=None (every backtest/simulated fill) takes the CURRENT path.

    A quote-side commission debits cash AND the position holds the FULL amount — the
    byte-exact behavior the SMA_MACD oracle regression-locks. BUY 0.001 @ 100000 with a
    0.1 quote commission and NO fee currency:
      * position.net_quantity == 0.001 (full amount, no base reduction)
      * cash == 150000 - (100 + 0.1) == 149899.9
    """
    pf = _spot_portfolio()
    pf.process_transaction(
        _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.001"),
             commission=Decimal("0.1"), fee_currency=None))

    position = pf.positions["BTC/USDC"]
    assert position.net_quantity == Decimal("0.001")
    assert pf.cash == Decimal("149899.9")


def test_base_fee_buy_scale_in_nets_each_leg():
    """Two base-fee BUYs each net their own fee out of the position (scale-in).

    BUY 0.001 (fee 0.000001 BTC) then BUY 0.002 (fee 0.000002 BTC), both @ 100000:
      * net_quantity == (0.001 - 0.000001) + (0.002 - 0.000002) == 0.002997
      * cash == 150000 - (100 + 200) == 149700 (notional only across both legs)
    """
    pf = _spot_portfolio()
    pf.process_transaction(
        _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.001"),
             commission=Decimal("0.000001"), fee_currency="BTC"))
    pf.process_transaction(
        _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.002"),
             commission=Decimal("0.000002"), fee_currency="BTC"))

    position = pf.positions["BTC/USDC"]
    assert position.net_quantity == Decimal("0.002997")
    assert pf.cash == Decimal("149700")


def test_transaction_seam_properties_are_fee_currency_aware():
    """Direct lock on the Transaction settlement seam (net_cash_delta / position_quantity).

    Base-fee BUY: quote_commission == 0, position_quantity == amount - fee,
    net_cash_delta == -(price*amount). Quote-fee / None: unchanged (commission in cash,
    position_quantity == amount)."""
    base = _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.001"),
                commission=Decimal("0.000001"), fee_currency="BTC")
    assert base.is_base_fee is True
    assert base.quote_commission == Decimal("0")
    assert base.position_quantity == Decimal("0.000999")
    assert base.net_cash_delta == Decimal("-100")

    quote = _txn(TransactionType.SELL, "BTC/USDC", Decimal("110000"), Decimal("0.0005"),
                 commission=Decimal("0.055"), fee_currency="USDC")
    assert quote.is_base_fee is False
    assert quote.quote_commission == Decimal("0.055")
    assert quote.position_quantity == Decimal("0.0005")
    assert quote.net_cash_delta == Decimal("54.945")

    default = _txn(TransactionType.BUY, "BTC/USDC", Decimal("100000"), Decimal("0.001"),
                   commission=Decimal("0.1"), fee_currency=None)
    assert default.is_base_fee is False
    assert default.quote_commission == Decimal("0.1")
    assert default.position_quantity == Decimal("0.001")
    assert default.net_cash_delta == Decimal("-100.1")
