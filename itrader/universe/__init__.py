"""Universe package — one documented membership module (M5-08, D-20).

The legacy dynamic/static universe machinery is gone: membership is
``derive_membership`` (see ``membership`` module
docstring for the growth target), and BarEvent production lives in the
feed (``itrader.price_handler.feed.bar_feed``).
"""

from .membership import derive_membership

__all__ = [
    'derive_membership',
]
