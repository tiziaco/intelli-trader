"""Venue-allowlist regression guard for ``EnhancedOrderValidator``.

Proves:
- **VENUE-04** — the venue name a portfolio carries must be admitted at
  admission; an unknown or empty venue must be REFUSED with a typed error code,
  never silently accepted.
- **D-05** — the backtest venue name is renamed by plan 11.1-06. The rename is
  only safe if the allowlist moves with it; this file is what goes red if it
  does not.
- **D-19** — the venue reaches the validator as ``Portfolio.exchange``, which is
  exactly the field D-19 changes.
- **RESEARCH F-3** — ``order_validator.py:117`` is a default-deny allowlist and
  NOTHING guarded it before Phase 11.1. A missed allowlist update refuses every
  SMA_MACD signal at admission: a total, silent, zero-trade run.

This file exists because that control was unguarded. The backtest venue name in
the parametrized set below is EXPECTED TO CHANGE when D-05 lands — plan 11.1-06
must update this list and ``EnhancedOrderValidator.supported_exchanges`` in the
SAME commit, or one of them goes red.

Scope: these tests call ``_validate_exchange_support`` directly rather than
driving ``validate_order_pipeline``. The full pipeline layers price, quantity
and market-hours checks on top, which are irrelevant noise for a venue-allowlist
guard and would blur which control actually refused the order.
"""

from datetime import datetime
from unittest.mock import Mock

import pytest

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.order_handler.order import Order
from itrader.order_handler.order_validator import (
    EnhancedOrderValidator,
    ValidationLevel,
)


# A venue name that is deliberately fictional: it must never be in the allowlist,
# under any rename. Used by both the behavioural refusal test and the structural
# default-deny test so the two cannot drift apart.
_FICTIONAL_VENUE = "nyse-moon"


def _make_order(**overrides) -> Order:
    """A PENDING order entity — only ``portfolio_id`` matters to the venue check.

    ``_validate_exchange_support`` reads the venue off the READ MODEL
    (``portfolio_handler.exchange_for(order.portfolio_id)``), never off
    ``Order.exchange``, so the entity here is deliberately minimal.
    """
    defaults = {
        "time": datetime(2024, 1, 2, 12, 0, 0),
        "type": OrderType.MARKET,
        "status": OrderStatus.PENDING,
        "ticker": "BTCUSDT",
        "action": Side.BUY,
        "price": 40000.0,
        "quantity": 0.1,
        "exchange": "csv",
        "strategy_id": 1,
        "portfolio_id": 1,
    }
    defaults.update(overrides)
    return Order(**defaults)


def _validator_reporting_venue(venue: str) -> EnhancedOrderValidator:
    """A validator over a read model whose ``exchange_for`` returns ``venue``."""
    read_model = Mock()
    read_model.exchange_for.return_value = venue
    return EnhancedOrderValidator(read_model)


# The venue names a backtest portfolio can currently carry. "csv" is the golden
# offline feed venue (`scripts/run_backtest.py` and `build_backtest_system` both
# create portfolios with exchange="csv"); "default" and "simulated" are the
# harness/simulated-exchange venues.
#
# Plan 11.1-06 (D-05) adds the NEW backtest venue name to BOTH this list and
# `EnhancedOrderValidator.supported_exchanges`, in the same commit.
@pytest.mark.parametrize("venue", ["csv", "default", "simulated"])
def test_backtest_venue_names_are_admitted(venue):
    """Every venue a backtest portfolio can carry passes the allowlist check.

    This is the half that goes red on a MISSED rename: if D-05 renames the
    backtest venue without widening the allowlist, admission refuses every
    signal and the run produces zero trades.
    """
    validator = _validator_reporting_venue(venue)

    messages = validator._validate_exchange_support(_make_order())

    assert messages == []


def test_unknown_venue_is_refused_with_the_typed_error_code():
    """An unknown venue produces exactly one ERROR carrying UNSUPPORTED_EXCHANGE.

    This is the half that goes red if the check is DELETED or downgraded to a
    WARNING — i.e. if someone "fixes" a rename by weakening the refusal instead
    of correcting the allowlist.
    """
    validator = _validator_reporting_venue(_FICTIONAL_VENUE)

    messages = validator._validate_exchange_support(_make_order())

    assert len(messages) == 1
    message = messages[0]
    assert message.level is ValidationLevel.ERROR
    assert message.field == "exchange"
    assert message.code == "UNSUPPORTED_EXCHANGE"
    assert _FICTIONAL_VENUE in message.message


def test_empty_venue_name_is_refused():
    """VENUE-04 empty edge: an unset venue must not slip through.

    The empty string is falsy, so any truthiness shortcut in the venue check
    would let an account-less portfolio trade unvalidated. Assert it takes the
    same typed refusal as any other unknown venue.
    """
    validator = _validator_reporting_venue("")

    messages = validator._validate_exchange_support(_make_order())

    assert len(messages) == 1
    assert messages[0].level is ValidationLevel.ERROR
    assert messages[0].code == "UNSUPPORTED_EXCHANGE"


def test_allowlist_is_default_deny_not_accept_all():
    """The allowlist is a non-empty ``set``, and the fictional venue is not in it.

    The structural companion to the behavioural tests above: it goes red if the
    allowlist is widened into an accept-all (or emptied into a
    check-that-cannot-fire). ``set`` membership is also why VENUE-04's ordering
    edge is structurally satisfied — no iteration order is observable to any
    caller, so no verdict can be order-dependent.
    """
    validator = _validator_reporting_venue("csv")

    assert isinstance(validator.supported_exchanges, set)
    assert validator.supported_exchanges
    assert _FICTIONAL_VENUE not in validator.supported_exchanges
