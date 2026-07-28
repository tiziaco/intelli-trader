"""The composition-time distinct-account invariant.

Identity is the PAIR ``(venue_name, account_id)``, never ``account_id`` alone: the same
account-id string on two different venues names two different real accounts, while the
same string on the same venue names one account that two portfolios must not share.

This stands over the database's own uniqueness constraint on the pair as belt-and-braces:
the DB binds out-of-band writers this code never sees, while this layer turns an opaque
``IntegrityError`` into a readable, actionable refusal before the engine assembles around
the collision — matching the justified-overlap posture already pinned for the order
validators.

The failure mode is REFUSE TO START, before any account is minted: two portfolios sharing
one venue account would conflate buying power into a balance the venue cannot split back
out, so there is no safe way to pick which portfolio keeps the account. This is
deliberately not the per-instance quarantine a bad strategy row gets — a skipped strategy
is harmless, a skipped portfolio may hold open positions.

Reached only from inside ``build_live_system``'s durable-store gate (GATE-01), via a lazy
import: it imports no store and no spec class, so both sides arrive as duck-typed handles.

4-space indentation.
"""

from typing import Any, Iterable, Mapping, Optional

from itrader.core.exceptions import DuplicateVenueAccountError

__all__ = ["assert_distinct_accounts"]


def assert_distinct_accounts(
    *,
    persisted: Iterable[Mapping[str, Any]],
) -> None:
    """Raise unless every portfolio names a DISTINCT ``(venue_name, account_id)`` pair.

    Parameters
    ----------
    persisted:
        The definition rows from ``PortfolioDefinitionStore.read_all()``. Each carries its
        OWN ``venue_name``, because a durable portfolio may live on a venue other than the
        one this boot is assembling.

    Raises
    ------
    DuplicateVenueAccountError
        Two portfolios name the same pair. The error carries the pair and both portfolio
        labels, and its message names the consequence and the remediation.

    Notes
    -----
    A RETIRED row never reaches here: ``read_all`` already filters ``is_deleted`` at the
    store, so a retired portfolio's pair is released before this check runs and a
    successor can claim it without tripping the invariant. No ``is_deleted`` logic is
    added here deliberately — it would never see a retired row, and a second filter is a
    second place the rule could drift from the store's. A PAUSED (``enabled=False``)
    portfolio, by contrast, is still returned by ``read_all`` and still claims its account
    here: pausing keeps the account, so re-enabling can never collide with a successor.
    """
    seen: dict[tuple[str, str], str] = {}

    for row in persisted:
        _claim(
            seen,
            venue_name=row["venue_name"],
            account_id=row["account_id"],
            label=_persisted_label(row),
        )


def _claim(
    seen: dict[tuple[str, str], str],
    *,
    venue_name: Optional[str],
    account_id: Optional[str],
    label: str,
) -> None:
    """Record one portfolio's claim on a pair, raising when the pair is already claimed."""
    if venue_name is None or account_id is None:
        # Skipped individually, not grouped under a shared None key: an unset
        # account_id means "no venue account", and several of those are not a collision.
        return
    key = (venue_name, account_id)
    incumbent = seen.get(key)
    if incumbent is not None:
        raise DuplicateVenueAccountError(venue_name, account_id, incumbent, label)
    seen[key] = label


def _persisted_label(row: Mapping[str, Any]) -> str:
    """A human handle for a durable portfolio — its name, with its id for disambiguation.

    Both are included because names are not unique: an error naming two identically-named
    portfolios would not tell an operator which durable row to fix.
    """
    return f"{row['name']} (persisted {row['portfolio_id']})"
