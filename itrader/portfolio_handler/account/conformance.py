"""Static account-contract conformance harness (D-02 / F/U-4).

``live_trading_system._link_venue_account_to_portfolios`` assigns a ``VenueAccount``
onto ``Portfolio.account`` — the ABC-vs-concretion wiring the live settlement path
relies on. That module sits in the ``D-live`` ``[[tool.mypy.overrides]]`` ignore block,
so ``mypy --strict`` never type-checks the assignment there. F/U-4 chooses the typed
conformance module over lifting the whole ``live_trading_system`` ignore (which pulls a
large deferred-D-live surface into strict scope): this module re-states the same wiring
in strict-checked code so a leaf that drifts off the ``Account`` ABC surface, or a
``Portfolio.account`` field re-narrowed back to a concretion, fails ``mypy --strict``
HERE instead of shipping silently (T-05.1-12).

It carries no runtime behaviour — nothing imports it, so it never runs; ``mypy``
type-checks it because it lives under the in-scope ``itrader`` package. The runtime twin
is ``tests/unit/portfolio/test_account_conformance.py`` (the permanent parametrized
3-leaf gate). Together they are the compile-time + runtime enforcement pair for D-02.
"""

from __future__ import annotations

from decimal import Decimal

from itrader.portfolio_handler.account import (
    Account,
    SimulatedCashAccount,
    SimulatedMarginAccount,
    VenueAccount,
)
from itrader.portfolio_handler.portfolio import Portfolio


def _assert_leaf_conforms(account: Account) -> None:
    """Every ``Account`` leaf must expose the full settlement-surface reads.

    A member dropped from a concrete leaf (drift off the ABC) fails ``mypy --strict``
    on these annotated reads — the D-01 surface (``balance`` / ``available_balance`` /
    ``reserved_balance``) is the admission + serialization contract every live
    portfolio depends on.
    """
    _balance: Decimal = account.balance
    _available: Decimal = account.available_balance
    _reserved: Decimal = account.reserved_balance


def _assert_live_wiring(
    portfolio: Portfolio,
    cash: SimulatedCashAccount,
    margin: SimulatedMarginAccount,
    venue: VenueAccount,
) -> None:
    """Mirror ``live_trading_system._link_venue_account_to_portfolios`` (D-02).

    Every leaf is assignable to the ABC-typed ``Portfolio.account`` field. If the field
    were re-narrowed back to a concretion, ``portfolio.account = venue`` would fail
    ``mypy --strict`` here — the exact ABC-vs-concretion drift D-02 forbids from
    shipping silently.
    """
    _assert_leaf_conforms(cash)
    _assert_leaf_conforms(margin)
    _assert_leaf_conforms(venue)
    portfolio.account = cash
    portfolio.account = margin
    portfolio.account = venue
