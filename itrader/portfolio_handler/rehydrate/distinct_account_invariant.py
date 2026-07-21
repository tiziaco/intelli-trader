"""The composition-time distinct-account invariant (D-14/D-15, MPORT-02).

**Identity is the PAIR.** A portfolio's venue account is ``(venue_name, account_id)``, never
``account_id`` alone. The same account-id STRING on two different venues names two different
real accounts and is perfectly legitimate; the same string on the same venue names ONE real
account, and two portfolios pointing at it is the T-11-38 collision.

**Why this runs over the UNION of both sources.** Rehydrated rows are already covered by the
database's ``UniqueConstraint('venue_name', 'account_id')`` (plan 11-01), so an application
check over only those proves nothing the DB has not already proven. The check's real job is a
duplicate inside a COMPOSITION-SUPPLIED spec — portfolios the database has never seen, and
cannot reject until they are written. Checking one source leaves the other open, which is why
the union is the contract rather than an implementation detail:

* spec x spec — two spec portfolios naming one account. Only this check catches it.
* spec x persisted — a new spec portfolio colliding with an existing durable row. The DB
  would eventually reject the write, but only as a raw integrity error, and only after the
  engine had already assembled around the collision.
* persisted x persisted — belt and braces over the DB constraint.

**D-14 — the two-layer overlap is deliberate, not redundant.** It matches the justified-
overlap posture the conventions document already pins for the order validators: the DB layer
binds out-of-band writers (a future integrations page) that never reach this code, and this
layer produces a readable, actionable refusal instead of an opaque ``IntegrityError``.

**D-15 — the failure is REFUSE TO START, before any account is minted.** Two portfolios on
one venue account conflate buying power into a single balance the venue cannot split back
out, so there is no safe way to pick which portfolio the account belongs to. This is
deliberately NOT the per-instance quarantine treatment a bad strategy row gets: a skipped
strategy is harmless, whereas a skipped portfolio may hold open positions. The caller must
therefore invoke this BEFORE minting accounts — after minting, the required-argument guard
plan 11-07 added has already been satisfied by a colliding pair and the damage is structural.

**D-05/GATE-01** — reached only from inside ``build_live_system``'s durable-store gate, via a
lazy import, and never barrel-exported. It imports no store and no spec class: both sides
arrive as duck-typed handles.

4-space indentation.
"""

from typing import Any, Iterable, Mapping, Optional

from itrader.core.exceptions import DuplicateVenueAccountError

__all__ = ["assert_distinct_accounts"]


def assert_distinct_accounts(
    *,
    persisted: Iterable[Mapping[str, Any]],
    spec_portfolios: Iterable[Any],
    venue_name: str,
) -> None:
    """Raise unless every portfolio names a DISTINCT ``(venue_name, account_id)`` pair.

    Parameters
    ----------
    persisted:
        The definition rows from ``PortfolioDefinitionStore.read_all()``. Each carries its
        OWN ``venue_name``, because a durable portfolio may live on a venue other than the
        one this boot is assembling.
    spec_portfolios:
        The composition-supplied ``PortfolioSpec``s. These carry only ``account_id`` — a
        spec describes portfolios on the venue being built — so they are paired with the
        ``venue_name`` argument.
    venue_name:
        The venue the spec portfolios belong to (``spec.execution_venue``).

    Raises
    ------
    DuplicateVenueAccountError
        Two portfolios name the same pair. The error carries the pair and both portfolio
        labels, and its message names the consequence and the remediation.

    Notes
    -----
    Portfolios that name NO account are skipped rather than grouped together. An unset
    ``account_id`` is "this portfolio has no venue account" — the legacy single-account
    shape — and treating several of them as colliding on a ``None`` key would refuse to
    start on a configuration that has always been valid.

    Zero and one portfolio both pass vacuously; that is the MPORT-03 empty edge, and it is
    today's behaviour for every live boot in the suite.
    """
    seen: dict[tuple[str, str], str] = {}

    for row in persisted:
        _claim(
            seen,
            venue_name=row["venue_name"],
            account_id=row["account_id"],
            label=_persisted_label(row),
        )

    for portfolio_spec in spec_portfolios:
        _claim(
            seen,
            venue_name=venue_name,
            account_id=getattr(portfolio_spec, "account_id", None),
            label=_spec_label(portfolio_spec),
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
        # No account reference — nothing to collide with. See the Notes above for why
        # these are skipped individually rather than grouped under a shared None key.
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


def _spec_label(portfolio_spec: Any) -> str:
    """A human handle for a composition-supplied portfolio."""
    name = getattr(portfolio_spec, "name", None) or "<unnamed>"
    return f"{name} (spec)"
