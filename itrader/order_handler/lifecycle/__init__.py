"""
Lifecycle subdomain package.

Re-exports the LifecycleManager — the modify/cancel verbs collaborator
(D-01 4th bucket; D-07/D-08/D-09) — so consumer import paths stay short after the
order-manager decomposition (pure move, D-12/D-13). It is NOT added to the
order_handler top barrel (D-12): it is an OrderManager implementation detail.
"""

from .lifecycle_manager import LifecycleManager

__all__ = ["LifecycleManager"]
