"""The D-08 rehydrate seam: portfolio DEFINITION rows become live portfolios at boot.

**D-08 — the definition row is the SOURCE OF TRUTH for which portfolios exist.** Seven
portfolio-scoped child tables record what a portfolio HAS (positions, cash operations,
transactions, account state, …). ``portfolios`` records what it IS. This module turns each
of those rows back into a live ``Portfolio`` at composition time, so the engine's roster
comes from the store rather than from composition code.

**F-1 / T-11-41 — the PERSISTED id is the entire point.** Each portfolio is recreated with
the ``portfolio_id`` its row carries, not a freshly minted one. Without that, the prior
run's child rows orphan (they are keyed on the old id) and the persisted strategy
subscription rows dangle — and worse, a portfolio could reattach to ANOTHER portfolio's
state. An id-equality assertion is the gate that pins this, because a rehydrate that mints
fresh ids looks completely healthy: the right NUMBER of portfolios boot, with the right
names and cash, and only their history is silently gone.

**MPORT-03 — two edges that must both hold.**

* ZERO rows is a clean no-op, not an error. A fresh database is a valid first-start state
  (the D-21 posture the strategy registry already takes), and it is today's behaviour for
  every existing live test — which is what makes construction-time rehydrate safe to land.
* Two rows on the SAME ``venue_name`` with DIFFERENT ``account_id`` values BOTH rehydrate.
  Same-venue portfolios are separate accounts; they do not collide. (The same PAIR on two
  portfolios is the D-14/D-15 collision, and it is refused upstream by
  ``assert_distinct_accounts`` before this function ever runs.)

**CR-01 posture on ``enabled``** — a disabled row is reconstructed PRESENT-BUT-INACTIVE
(created, then ``set_state(PortfolioState.INACTIVE)``), NOT dropped. This mirrors the
strategy registry's decision and the reasoning carries over with more force: a dropped
portfolio orphans its open positions and its cash, and makes them unreachable across the
restart. ``enabled`` is a runtime state, never a load filter. ``is_deleted`` (D-32 RETIRED)
IS the load filter, but it is applied ONE layer up in the store's ``read_all`` (11.2-02), so
a retired row never reaches this function at all — the distinction is deliberate: a PAUSED
portfolio must return (present-but-inactive), a RETIRED one must not.

**Materialize-only (D-25, 11.2-09).** The definition row already exists, so rehydrate calls
the handler's public ``materialize`` verb (build the leaf + register) — NOT ``add_portfolio``
and NOT ``create``. It never re-enters the durable write, and never reaches the handler's
private ``_portfolios`` registry. The duplicate-id guard lives in ``materialize`` now, so a
genuinely duplicate id still fails loud; within one boot ``read_all`` returns each id once.

**Money** enters the Decimal domain through ``to_money`` on the stored value. The store
already reads ``initial_cash`` back as ``Decimal`` (a ``Numeric`` column), so this is a
re-entry rather than a conversion — but it is written explicitly so no future edit
"simplifies" it into a float constructor.

**FLAGGED — the portfolio-count limit still applies to rehydrated portfolios.**
``materialize`` enforces ``max_portfolios`` (default 50) at registration, and rehydrate
routes through it (the same verb ``add_portfolio`` composes), so the limit is not a second
copy that could drift. A restart with more persisted portfolios than the limit therefore
fails LOUD partway through, leaving a PARTIAL set registered. Accepted at this phase's
realistic count of two, and recorded here rather than silently accepted.

**D-05/GATE-01** — this module is reached only from inside ``build_live_system``'s
``system_store is not None`` gate and is never barrel-exported, so the backtest import path
stays SQL-free. It imports no store class: the store arrives injected, duck-typed.

4-space indentation (the new ``rehydrate/`` package; note that the strategy-rehydrate
collaborator this mirrors structurally is TAB-indented — the shape was transcribed, the
whitespace was not).
"""

from decimal import Decimal
from typing import Any, Mapping, Protocol

from itrader.core.enums import PortfolioState
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger

__all__ = ["PortfolioDefinitionReader", "rehydrate_portfolios"]


class PortfolioDefinitionReader(Protocol):
    """The read-only slice of ``PortfolioDefinitionStore`` this module needs (D-05).

    A Protocol, not an import: keeping the store duck-typed means this module pulls no
    SQLAlchemy onto the import graph, and a test can drive it with a plain fake.

    ``read_all()`` returns every LIVE definition row — enabled AND disabled, but NOT
    ``is_deleted`` (D-32/ACCT-10) — ordered by ``portfolio_id`` ASC. A PAUSED
    (``enabled=False``) portfolio still rehydrates (present-but-inactive, below); a RETIRED
    (``is_deleted=True``) one is filtered out at the store so it never comes back with its
    persisted id and child tables reattached. That ordering is a documented contract on the
    store, not an incidental property: it makes the REGISTRATION order of rehydrated
    portfolios reproducible across runs and dialects.
    """

    def read_all(self) -> list[Mapping[str, Any]]:
        ...


def rehydrate_portfolios(
    *,
    store: PortfolioDefinitionReader,
    portfolio_handler: Any,
) -> list[PortfolioId]:
    """Recreate every persisted portfolio on ``portfolio_handler`` (D-08).

    Each row becomes a ``materialize`` call (D-25) carrying the row's ``portfolio_id``,
    ``account_id`` and ``venue_name``, so the rebuilt portfolio reattaches to its own
    child-table state — a runtime BUILD only, never a durable re-write. ``exchange`` is
    passed as the row's ``venue_name`` because D-07 makes ``venue_name`` the single source
    of truth for a portfolio's venue — there is deliberately no ``exchange`` column to drift
    apart from it.

    Returns
    -------
    list[PortfolioId]
        The ids rehydrated, in row order. Empty on a fresh database. The caller logs the
        count; it is also the natural handle for anything that needs to know which
        portfolios came from the store rather than from a spec.
    """
    logger = get_itrader_logger().bind(component="PortfolioRehydrator")

    # Infrastructure failures PROPAGATE: an unreadable store is a wiring problem, and a
    # live engine that boots with silently zero portfolios — holding no positions it can
    # manage out, reconciling nothing — is worse than one that refuses to start.
    rows = store.read_all()

    if not rows:
        logger.info(
            "No persisted portfolio definitions — booting with zero portfolios (MPORT-03 "
            "empty edge: a fresh database is a valid first-start state)")
        return []

    rehydrated: list[PortfolioId] = []
    for row in rows:
        portfolio_id = PortfolioId(row["portfolio_id"])

        # Idempotent within a boot: a portfolio whose id is already registered is skipped,
        # through the PUBLIC ``has_portfolio`` predicate (D-25/D-41) rather than the private
        # ``_portfolios`` map. ``materialize`` loud-rejects a duplicate id, so without this a
        # second pass (or a portfolio already present) would RAISE instead of no-op'ing.
        if portfolio_handler.has_portfolio(portfolio_id):
            logger.debug(
                "Portfolio %s is already registered — skipping its definition row",
                portfolio_id)
            continue

        # D-25 (11.2-09): rehydrate MATERIALIZES ONLY. The definition row already exists, so
        # it must NOT re-enter creation — before the create/materialize split, rehydrate
        # re-entered ``add_portfolio`` (write + build), which is the exact reason the write
        # path needed an absence gate (skip if the row exists) to avoid a DELETE-then-INSERT
        # wiping the operator's ``config_json`` on the first restart. It now calls the
        # handler's PUBLIC ``materialize`` verb (build the leaf through the factory + register),
        # never ``add_portfolio``, never ``create``, and never the private ``_portfolios``
        # registry. The duplicate-id guard moved INTO ``materialize`` (D-25), so a genuinely
        # duplicate id still fails loud there; within one boot ``read_all`` returns each id
        # once, so it never fires here.
        portfolio_handler.materialize(
            name=row["name"],
            # D-07: venue_name is the source of truth; `exchange` is derived from it.
            exchange=row["venue_name"],
            cash=_initial_cash(row),
            portfolio_id=portfolio_id,
            account_id=row["account_id"],
            venue_name=row["venue_name"],
        )
        rehydrated.append(portfolio_id)

        # CR-01: `enabled` becomes runtime state, NOT a load filter. A disabled row is
        # present-but-inactive so it still owns its positions and is re-enable-able.
        if not row["enabled"]:
            portfolio = portfolio_handler.get_portfolio(portfolio_id)
            portfolio.set_state(
                PortfolioState.INACTIVE,
                reason="rehydrated from a definition row with enabled=False")

    logger.info(
        "Rehydrated %d portfolio(s) from their definition rows with their persisted ids",
        len(rehydrated))
    return rehydrated


def _initial_cash(row: Mapping[str, Any]) -> Decimal:
    """This row's ``initial_cash`` as exact money (the ONLY entry into the money domain).

    The store already hands back a ``Decimal`` (a ``Numeric`` column), so ``to_money`` is
    a re-entry rather than a conversion. It is written explicitly anyway: money must never
    reach a portfolio through a float constructor, and an explicit helper call is what
    stops a future edit from "simplifying" this into one.
    """
    return to_money(row["initial_cash"])
