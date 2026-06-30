"""
Account subdomain package — the fifth peer delegate under ``portfolio_handler/``
next to ``cash/ position/ transaction/ metrics/`` (D-12).

The ``Account`` family owns balance/margin truth (D-01 / D-02, ACCT-01). It has
no queue and emits no events (the liquidation ``global_queue.put`` emission stays
in ``PortfolioHandler`` by design, ACCT-02), so it follows the queue-free *manager*
pattern, NOT the ``*_handler`` queue-facing pattern — hence ``account/`` lives here
and not as a top-level ``account_handler/``.

This barrel exports the contract surface created in plan 01-01 (the ``Account`` ABC
and the interface-only ``VenueAccount`` stub leaf) extended in plan 01-02 with the
``Simulated*`` leaves (``SimulatedCashAccount`` / ``SimulatedMarginAccount``) and the
``CashOperation`` audit entity as the ``CashManager`` code-motion lands. ``CashOperation``
is re-exported here so the importers that survive ``cash_manager.py``'s deletion
(production ``sql_storage.py`` + the reporting/storage tests, re-pointed in plans
01-03/01-03b) have a single stable home: ``itrader.portfolio_handler.account``.
"""

from .base import Account
from .simulated import SimulatedCashAccount, SimulatedMarginAccount, CashOperation
from .venue import VenueAccount

__all__ = [
    "Account",
    "SimulatedCashAccount",
    "SimulatedMarginAccount",
    "VenueAccount",
    "CashOperation",
]
