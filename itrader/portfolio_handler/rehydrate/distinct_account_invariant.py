"""The composition-time distinct-account invariant (D-14/D-15, MPORT-02).

**Identity is the PAIR.** A portfolio's venue account is ``(venue_name, account_id)``, never
``account_id`` alone. The same account-id STRING on two different venues names two different
real accounts and is perfectly legitimate; the same string on the same venue names ONE real
account, and two portfolios pointing at it is the T-11-38 collision.

**Why this runs over the persisted rows (11.2-07, ACCT-01/D-20).** The account set is now
STORE-DERIVED: the live boot no longer computes account identity from the spec, so the
spec-derived arm this check used to carry — a ``spec_portfolios`` list paired with the booted
``venue_name`` — is GONE. The only source of portfolio pairs left is the persisted definition
rows, and this layer stands over the database's ``UniqueConstraint('venue_name',
'account_id')`` (plan 11-01) as belt-and-braces:

* persisted x persisted — the DB constraint binds out-of-band writers this code never sees;
  this layer turns the DB's raw ``IntegrityError`` into a readable, actionable refusal
  BEFORE the engine assembles around the collision.

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
) -> None:
    """Raise unless every portfolio names a DISTINCT ``(venue_name, account_id)`` pair.

    11.2-07 (ACCT-01/D-20): the account set is now STORE-DERIVED. The spec-derived arm —
    a ``spec_portfolios`` list paired with the booted ``venue_name`` — is GONE: the live
    boot no longer computes account identity from the spec, so the only source of
    portfolio pairs left is the persisted definition rows, each carrying its OWN
    ``venue_name``. The ``venue_name`` argument left with the spec arm it served.

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
    Portfolios that name NO account are skipped rather than grouped together. An unset
    ``account_id`` is "this portfolio has no venue account" — the legacy single-account
    shape — and treating several of them as colliding on a ``None`` key would refuse to
    start on a configuration that has always been valid.

    Zero and one portfolio both pass vacuously; that is the MPORT-03 empty edge, and it is
    today's behaviour for every live boot in the suite.

    RETIRED rows never reach here (D-32/ACCT-10). The only production caller feeds this
    ``read_all()`` (``live_trading_system`` boot), and ``read_all`` already filters
    ``is_deleted`` at the store (11.2-02), so a retired portfolio has already released its
    ``(venue_name, account_id)`` pair before this check runs — its successor can claim the
    account WITHOUT tripping the distinct-account invariant. No ``is_deleted`` logic is added
    HERE deliberately: it would be dead code that never sees a retired row, and a second
    filter is a second place the rule could drift from the store's. A PAUSED
    (``enabled=False``) portfolio, by contrast, IS returned by ``read_all`` and DOES still
    claim its account here — correctly, per D-32: pausing keeps the account, so re-enabling
    can never collide with a successor.

    The persisted x persisted layer stands over the database's own
    ``UniqueConstraint('venue_name', 'account_id')`` as belt-and-braces: the DB binds
    out-of-band writers this code never sees, and this layer turns a raw ``IntegrityError``
    into a readable, actionable refusal before the engine assembles around the collision.
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
