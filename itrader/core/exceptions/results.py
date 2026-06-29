"""Results-store exceptions for the iTrader system (D-16)."""

import uuid

from .base import NotFoundError

# 02-01: a results-store ``run_id`` is a UUIDv7 at the store layer; the diagnostic
# accepts the int/str forms too so a missing-read raise is uniform with the other
# ``NotFoundError`` subclasses (e.g. ``PortfolioNotFoundError``).
RunIdLike = uuid.UUID | int | str


class ResultsNotFound(NotFoundError):
    """Raised when a results-store read finds no row for the requested ``run_id`` (D-16).

    Mirrors ``PortfolioNotFoundError`` — a thin ``NotFoundError`` subclass that pins the
    entity type (``"Run"``) and stashes the offending id for programmatic inspection.
    """

    def __init__(self, run_id: RunIdLike):
        self.run_id = run_id
        super().__init__("Run", run_id)
