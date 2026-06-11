"""
Brackets subdomain package.

Re-exports the BracketManager + the BracketBook pending-bracket state owner
(D-04/D-05) so consumer import paths stay short after the order-manager
decomposition (pure move, D-12/D-13). The stateless levels helper and
_PendingBracket stay internal (leading-underscore).
"""

from .bracket_manager import BracketManager
from .bracket_book import BracketBook

__all__ = ["BracketManager", "BracketBook"]
