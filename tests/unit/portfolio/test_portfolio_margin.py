"""Portfolio margin seam residuals (WR-01 / WR-05) — Phase 3 (Plan 03-06).

WR-01 (`funds_invariant_lock`): a settlement-side solvency assertion that the
locked margin (``aggregate_notional / L``) fits available buying power at lock
time — a fail-loud guard BEFORE settlement on the short/levered path (T-03-15).

WR-05 (`open_commission_accumulator`): the margin close re-credits the EXACT
pre-debited open commission for the closed increment (tracked as a per-lock
accumulator), so a non-uniform-commission scale-in followed by staged partial
closes does not drift the cumulative round-trip cash delta away from realized
PnL (Pitfall 5 / T-03-16).

All assertions are oracle-dark — ``enable_margin`` is off on the SMA_MACD golden
path, so none of this touches the byte-exact oracle (134 / 46189.87730727451).
Folder-derived ``unit`` marker only (tests/conftest.py applies it).
"""

from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.enums import TransactionType
from itrader.core.exceptions import InsufficientFundsError
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction


def _margin_config(max_leverage: str = "10") -> PortfolioConfig:
    """A PortfolioConfig with enable_margin=True. 01-03 selects the account leaf
    at construction, so margin must be set in the constructor config (the former
    post-construction ``update_config`` toggle no longer rebuilds the leaf)."""
    return PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "max_leverage": Decimal(max_leverage)}},
    ))


@pytest.fixture
def margin_portfolio():
    """A $150000 portfolio with enable_margin=True (lock-and-settle on)."""
    return Portfolio(
        "margin_pf", "simulated", 150000, datetime.now(), config=_margin_config()
    )


def _levered_txn(type_, ticker, price, quantity, commission, leverage):
    txn = Transaction(
        datetime(2021, 3, 14, 9, 26, 53), type_, ticker, price, quantity,
        commission, None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    txn.leverage = Decimal(str(leverage))
    return txn


# ---------------------------------------------------------------------------
# WR-01 — settlement-side solvency assertion (funds_invariant_lock)
# ---------------------------------------------------------------------------


def test_funds_invariant_lock_raises_when_lock_exceeds_buying_power(margin_portfolio):
    """WR-01: a margin OPEN whose locked margin (aggregate_notional / L) exceeds
    the available buying power at lock time fails loud BEFORE settlement, rather
    than silently over-locking beyond buying power (T-03-15)."""
    pf = margin_portfolio
    # notional = 1_000_000 @ L=1 -> lock = 1_000_000 > 150_000 buying power.
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 20, 0, 1)

    with pytest.raises(InsufficientFundsError):
        pf.process_transaction(buy)


def test_funds_invariant_lock_admits_affordable_lock(margin_portfolio):
    """WR-01 must NOT regress an affordable lock: a lock within buying power
    settles normally (lock recorded, balance only moves by commission)."""
    pf = margin_portfolio
    # lock = (50000 * 2) / 5 = 20000 <= 150000 buying power.
    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 2, 0, 5)

    pf.process_transaction(buy)  # must NOT raise

    assert pf.account.locked_margin_total == Decimal("20000")
    assert pf.cash == Decimal("150000")


# ---------------------------------------------------------------------------
# WR-05 — per-lock open-commission accumulator (open_commission_accumulator)
# ---------------------------------------------------------------------------


def test_open_commission_accumulator_no_drift_on_staged_partial_closes(margin_portfolio):
    """WR-05: after a non-uniform-commission entry, staged partial closes settle
    cash such that the cumulative round-trip cash delta equals the position's
    realized PnL exactly — the per-lock open-commission accumulator removes the
    quantity-fraction proxy drift (Pitfall 5).

    Entry: BUY 4 @ 50000, commission 200 (non-uniform vs zero-commission exits).
    Stage 1: SELL 1 @ 55000, commission 0. Stage 2: SELL 3 @ 55000, commission 0.
    After the full round trip the net balance change MUST equal the closed
    position's realized PnL — no open-commission double-count or under-credit.
    """
    pf = margin_portfolio
    start = pf.cash

    buy = _levered_txn(TransactionType.BUY, "BTCUSDT", 50000, 4, 200, 5)
    pf.process_transaction(buy)
    # Open debit is ONLY the commission (D-08): balance dropped by 200.
    assert pf.cash == start - Decimal("200")

    # Stage 1 partial close (1 of 4).
    sell1 = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 1, 0, 5)
    pf.process_transaction(sell1)

    # Stage 2 close the remaining 3.
    sell2 = _levered_txn(TransactionType.SELL, "BTCUSDT", 55000, 3, 0, 5)
    pf.process_transaction(sell2)

    closed = pf.closed_positions[0]
    # The cumulative round-trip cash delta == realized PnL (commission netted
    # exactly once — no drift from the staged partial closes).
    assert pf.cash == start + closed.realised_pnl
    assert pf.account.locked_margin_total == Decimal("0")
    assert len(pf.positions) == 0
