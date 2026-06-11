"""
Reconcile subdomain package.

Re-exports the ReconcileManager (the fill-reconciliation `on_fill` collaborator,
D-01 5th bucket; D-07/D-08/D-09) so consumer import paths stay short after the
order-manager decomposition (pure move, D-12/D-13). It is NOT added to the
order_handler top barrel (D-12): it is an OrderManager implementation detail.
"""

from .reconcile_manager import ReconcileManager

__all__ = ["ReconcileManager"]
