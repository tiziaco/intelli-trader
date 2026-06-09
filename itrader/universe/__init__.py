"""Universe package — one documented membership module (M5-08, D-20).

The legacy dynamic/static universe machinery is gone: membership is
``derive_membership`` (see ``membership`` module
docstring for the growth target), and BarEvent production lives in the
feed (``itrader.price_handler.feed.bar_feed``). The per-tick availability
query (``is_active`` / ``active_membership``, UNIV-01) was added alongside
``derive_membership`` (D-03).
"""

from .membership import active_membership, derive_membership, is_active

__all__ = [
    'active_membership',
    'derive_membership',
    'is_active',
]
