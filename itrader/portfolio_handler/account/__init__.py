"""
Account subdomain package — the fifth peer delegate under ``portfolio_handler/``
next to ``cash/ position/ transaction/ metrics/`` (D-12).

The ``Account`` family owns balance/margin truth (D-01 / D-02, ACCT-01). It has
no queue and emits no events (the liquidation ``global_queue.put`` emission stays
in ``PortfolioHandler`` by design, ACCT-02), so it follows the queue-free *manager*
pattern, NOT the ``*_handler`` queue-facing pattern — hence ``account/`` lives here
and not as a top-level ``account_handler/``.

This barrel exports the ``Account`` ABC, the two COMPUTE leaves
(``SimulatedCashAccount`` / ``SimulatedMarginAccount``) and the ``CashOperation`` audit
entity. ``CashOperation`` is re-exported here so the importers that survived
``cash_manager.py``'s deletion (production ``sql_storage.py`` plus the reporting/storage
tests) have a single stable home: ``itrader.portfolio_handler.account``.

Every leaf here computes its own balance. Venue truth is NOT an account leaf: it is read
from the venue by the execution adapter that owns the authenticated session, as an
``AccountSnapshot``. That is why there is no venue-cached leaf to export — an account
whose balance is unreadable until a network round trip completes cannot be the leaf a
portfolio is CONSTRUCTED with, since construction reads the balance.
"""

from .base import Account
from .simulated import SimulatedCashAccount, SimulatedMarginAccount, CashOperation

__all__ = [
    "Account",
    "SimulatedCashAccount",
    "SimulatedMarginAccount",
    "CashOperation",
]
