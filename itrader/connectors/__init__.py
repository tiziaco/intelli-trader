"""
Connectors package — live trading venue interfaces (D-13).

A new top-level package (NOT a portfolio concern): it spans the data + order arms,
broader than execution. Phase 1 shipped the ``LiveConnector`` structural Protocol marker
(D-10); Phase 2 added ``connectors/okx.py`` (``OkxConnector`` — the shared authenticated
session/transport primitive) and Phase 4 adds ``connectors/paper.py`` (``PaperConnector``),
both implementing ``LiveConnector``.
"""

from .base import LiveConnector
from .okx import OkxConnector

__all__ = ["LiveConnector", "OkxConnector"]
