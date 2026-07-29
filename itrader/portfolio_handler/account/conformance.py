"""Static account-contract conformance harness (D-02 / F/U-4).

``Portfolio.account`` is typed as the ``Account`` ABC, and the live settlement path
depends on that: admission reads ``available_balance``, serialization reads ``balance``,
and both must work for whichever leaf a portfolio was built with. This module re-states
that contract in strict-checked code, so a leaf that drifts off the ABC surface — or a
``Portfolio.account`` field re-narrowed back to one concretion — fails ``mypy --strict``
HERE rather than shipping silently.

Why a module rather than a test: the composition roots that assign leaves onto portfolios
live under a ``[[tool.mypy.overrides]]`` ignore block, so ``mypy --strict`` never checks
the assignment where it actually happens. Lifting that ignore would pull a large deferred
surface into strict scope; stating the same wiring here costs nothing and checks the part
that matters.

It carries no runtime behaviour — nothing imports it, so it never runs; ``mypy``
type-checks it because it lives under the in-scope ``itrader`` package. The runtime twin
is ``tests/unit/portfolio/test_account_conformance.py``, the parametrized per-leaf gate.
Together they are the compile-time and runtime halves of the same contract.

Indentation: 4-space.
"""

from __future__ import annotations

from decimal import Decimal

from itrader.core.ids import OrderId
from itrader.portfolio_handler.account import (
    Account,
    SimulatedCashAccount,
    SimulatedMarginAccount,
)
from itrader.portfolio_handler.portfolio import Portfolio


def _assert_leaf_conforms(account: Account) -> None:
    """Every ``Account`` leaf must expose the full settlement-surface reads.

    A member dropped from a concrete leaf (drift off the ABC) fails ``mypy --strict`` on
    these annotated reads — the ``balance`` / ``available_balance`` / ``reserved_balance``
    surface is the admission and serialization contract every portfolio depends on.
    """
    _balance: Decimal = account.balance
    _available: Decimal = account.available_balance
    _reserved: Decimal = account.reserved_balance


def _assert_ack_seam_is_declared(account: Account, order_id: OrderId) -> None:
    """``drop_pending`` is reachable on the ABC, not probed for at the call site.

    The ORDER-ACK read-model seam calls this unconditionally. Asserting it through the
    ABC-typed parameter is what keeps that call honest: were the member to exist only on
    some leaves, this line would fail ``mypy --strict`` and the call site would be back to
    a ``getattr`` probe — an account-type test in disguise.
    """
    account.drop_pending(order_id)


def _assert_portfolio_field_stays_abc_typed(
    portfolio: Portfolio,
    cash: SimulatedCashAccount,
    margin: SimulatedMarginAccount,
) -> None:
    """Every leaf is assignable to the ABC-typed ``Portfolio.account`` field.

    If the field were re-narrowed back to a single concretion, one of these assignments
    would fail ``mypy --strict`` here — the ABC-vs-concretion drift D-02 forbids from
    shipping silently.
    """
    _assert_leaf_conforms(cash)
    _assert_leaf_conforms(margin)
    portfolio.account = cash
    portfolio.account = margin
