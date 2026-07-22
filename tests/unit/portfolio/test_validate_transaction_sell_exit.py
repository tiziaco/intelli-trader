"""Regression: ``_validate_transaction`` gates OPEN limits on TYPE, not magnitude (WR-01).

``Transaction.quantity`` is a positive magnitude everywhere (direction rides
``transaction.type``). The buy-only position-limit checks (``max_positions`` /
``max_position_value``) must therefore key on ``transaction.type == BUY``, NOT on
``quantity > 0`` (which is *always* true). Before the WR-01 fix a closing SELL
issued while already at ``max_positions`` was wrongly rejected — blocking an exit
(and, in live, failing settlement into a drift-halt). Folder-derived ``unit``
marker only (tests/conftest.py applies it).
"""

from datetime import datetime
from decimal import Decimal

import pytest
import uuid_utils.compat as uuid_compat

from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.exceptions import PortfolioError
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.position import Position
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from tests.support.venue_wiring import compute_account

_TICKER = "BTCUSDT"
_PORTFOLIO_ID = "pf-wr01"
_TIME = datetime(2024, 1, 1)


def _at_limit_portfolio() -> Portfolio:
    """A portfolio at ``max_positions=1`` with transaction validation enabled."""
    config = PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"limits": {"max_positions": 1}, "validation": {"validate_transactions": True}},
    ))
    portfolio = Portfolio(
        name="wr01-pf", exchange="paper",
        cash=Decimal("100000"), time=_TIME, config=config,
        account=compute_account(Decimal("100000")),
    )
    # Seed ONE open long so n_open_positions == max_positions (at the limit).
    buy = Transaction(
        _TIME, TransactionType.BUY, _TICKER, Decimal("100"), Decimal("1"), Decimal("0"),
        _PORTFOLIO_ID, id=1, fill_id=uuid_compat.uuid7(),
    )
    portfolio.position_manager._storage.set_position(_TICKER, Position.open_position(buy))
    assert portfolio.n_open_positions == portfolio.config.limits.max_positions
    return portfolio


def test_closing_sell_at_max_positions_is_not_rejected() -> None:
    """A SELL at ``max_positions`` must validate — it reduces exposure, not opens."""
    portfolio = _at_limit_portfolio()
    sell = Transaction(
        _TIME, TransactionType.SELL, _TICKER, Decimal("100"), Decimal("1"), Decimal("0"),
        _PORTFOLIO_ID, id=2, fill_id=uuid_compat.uuid7(),
    )
    # Must NOT raise — the OPEN-limit gate is keyed on TYPE == BUY, not magnitude.
    portfolio._validate_transaction(sell)


def test_opening_buy_at_max_positions_is_still_rejected() -> None:
    """A BUY at ``max_positions`` must still breach the open-position limit (guard intact)."""
    portfolio = _at_limit_portfolio()
    buy = Transaction(
        _TIME, TransactionType.BUY, "ETHUSDT", Decimal("100"), Decimal("1"), Decimal("0"),
        _PORTFOLIO_ID, id=3, fill_id=uuid_compat.uuid7(),
    )
    with pytest.raises(PortfolioError):
        portfolio._validate_transaction(buy)
