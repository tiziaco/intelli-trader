"""
Brackets subdomain package.

Re-exports the BracketBook pending-bracket state owner (D-04/D-05) so consumer
import paths stay short after the order-manager decomposition (pure move,
D-12/D-13). _PendingBracket stays internal (leading-underscore). The
BracketManager joins this barrel in plan 02.
"""

from .bracket_book import BracketBook

__all__ = ["BracketBook"]
