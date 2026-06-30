"""
Cash subdomain package — ABSORBED into ``account/`` (ACCT-01/02, plan 01-03).

The former ``CashManager`` cash-leaf was moved byte-for-byte into
``SimulatedCashAccount`` (plan 01-02, D-05) and the ``CashOperation`` audit entity
relocated to ``itrader.portfolio_handler.account``; ``cash_manager.py`` was then
deleted (plan 01-03). This package is intentionally left as an empty namespace —
no public surface remains here. Import the account leaves and ``CashOperation``
from ``itrader.portfolio_handler.account`` (the single stable home).
"""

__all__: list[str] = []
