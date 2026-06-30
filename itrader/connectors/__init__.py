"""
Connectors package — live trading venue interfaces (D-13).

A new top-level package (NOT a portfolio concern): it spans the data + order arms,
broader than execution. This phase ships the ``LiveConnector`` structural Protocol
marker only (D-10); Phase 2 adds ``connectors/okx.py`` (``OkxConnector``) and Phase 4
adds ``connectors/paper.py`` (``PaperConnector``), both implementing ``LiveConnector``.
"""

from .base import LiveConnector

__all__ = ["LiveConnector"]
