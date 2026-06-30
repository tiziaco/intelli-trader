"""
Account subdomain package — the fifth peer delegate under ``portfolio_handler/``
next to ``cash/ position/ transaction/ metrics/`` (D-12).

The ``Account`` family owns balance/margin truth (D-01 / D-02, ACCT-01). It has
no queue and emits no events (the liquidation ``global_queue.put`` emission stays
in ``PortfolioHandler`` by design, ACCT-02), so it follows the queue-free *manager*
pattern, NOT the ``*_handler`` queue-facing pattern — hence ``account/`` lives here
and not as a top-level ``account_handler/``.

This barrel exports the contract surface created in plan 01-01: the ``Account`` ABC
and the interface-only ``VenueAccount`` stub leaf. Plan 01-02 extends this barrel
with the ``Simulated*`` leaves (``SimulatedCashAccount`` /
``SimulatedMarginAccount``) and ``CashOperation`` as the ``CashManager`` code-motion
lands.
"""

from .base import Account
from .venue import VenueAccount

__all__ = ["Account", "VenueAccount"]
