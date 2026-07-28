"""The rehydrate seam: portfolio DEFINITION rows become live portfolios at boot.

The ``portfolios`` definition row is the source of truth for which portfolios exist; seven
other portfolio-scoped tables record what a portfolio HAS (positions, cash, transactions,
account state, …), not that it exists. This module turns each definition row back into a
live ``Portfolio`` at composition time, so the engine's roster comes from the store rather
than from composition code.

Each portfolio is recreated with the ``portfolio_id`` its row carries, never a freshly
minted one — a fresh id would orphan the prior run's child rows (keyed on the old id) and
could let a portfolio reattach to another portfolio's state, while still looking completely
healthy: the right number of portfolios boot, with the right names and cash, and only their
history is silently gone.

The definition row already exists, so rehydrate calls the handler's public ``materialize``
verb (build the leaf + register), never ``add_portfolio`` and never ``create`` — it must
not re-enter the durable write or reach the handler's private ``_portfolios`` registry.
``materialize`` also enforces ``max_portfolios`` at registration, and rehydrate routes
through the same verb, so a restart with more persisted portfolios than the limit fails
loud partway through, leaving a partial set registered.

Reached only from inside ``build_live_system``'s durable-store gate (GATE-01) and never
barrel-exported, so the backtest import path stays SQL-free. It imports no store class:
the store arrives injected, duck-typed.

4-space indentation — the strategy-rehydrate collaborator this mirrors structurally is
tab-indented; the shape was transcribed, the whitespace was not.
"""

from decimal import Decimal
from typing import Any, Mapping, Protocol

from itrader.core.enums import PortfolioState
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger

__all__ = ["PortfolioDefinitionReader", "rehydrate_portfolios"]


class PortfolioDefinitionReader(Protocol):
    """The read-only slice of ``PortfolioDefinitionStore`` this module needs.

    A Protocol, not an import: keeping the store duck-typed means this module pulls no
    SQLAlchemy onto the import graph, and a test can drive it with a plain fake.

    ``read_all()`` returns every live definition row (enabled and disabled, never a
    retired one) ordered by ``portfolio_id`` ascending — a documented store contract, not
    an incidental property, so registration order is reproducible across runs and dialects.
    """

    def read_all(self) -> list[Mapping[str, Any]]:
        ...


def rehydrate_portfolios(
    *,
    store: PortfolioDefinitionReader,
    portfolio_handler: Any,
) -> list[PortfolioId]:
    """Recreate every persisted portfolio on ``portfolio_handler``.

    Each row becomes a ``materialize`` call carrying the row's ``portfolio_id``,
    ``account_id`` and ``venue_name``, so the rebuilt portfolio reattaches to its own
    child-table state — a runtime build only, never a durable re-write. ``exchange`` is
    passed as the row's ``venue_name`` because ``venue_name`` is the single source of
    truth for a portfolio's venue; there is deliberately no separate ``exchange`` column
    to drift apart from it.

    Returns
    -------
    list[PortfolioId]
        The ids rehydrated, in row order. Empty on a fresh database.
    """
    logger = get_itrader_logger().bind(component="PortfolioRehydrator")

    # An unreadable store propagates rather than booting with silently zero portfolios:
    # a live engine holding no positions it can manage out is worse than one that refuses
    # to start.
    rows = store.read_all()

    if not rows:
        logger.info(
            "No persisted portfolio definitions — booting with zero portfolios (MPORT-03 "
            "empty edge: a fresh database is a valid first-start state)")
        return []

    rehydrated: list[PortfolioId] = []
    for row in rows:
        portfolio_id = PortfolioId(row["portfolio_id"])

        # ``materialize`` loud-rejects a duplicate id, so without this guard a second pass
        # (or a portfolio already present) would raise instead of no-op'ing.
        if portfolio_handler.has_portfolio(portfolio_id):
            logger.debug(
                "Portfolio %s is already registered — skipping its definition row",
                portfolio_id)
            continue

        # The definition row already exists, so rehydrate calls the public ``materialize``
        # verb only — never ``add_portfolio`` or ``create`` — and never re-enters the
        # durable write.
        portfolio_handler.materialize(
            name=row["name"],
            # venue_name is the source of truth; exchange is derived from it.
            exchange=row["venue_name"],
            cash=_initial_cash(row),
            portfolio_id=portfolio_id,
            account_id=row["account_id"],
            venue_name=row["venue_name"],
        )
        rehydrated.append(portfolio_id)

        # `enabled` is runtime state, not a load filter: a disabled row is
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
    """This row's ``initial_cash`` as exact money.

    The store already hands back a ``Decimal`` (a ``Numeric`` column), so this is a
    re-entry rather than a conversion — written explicitly so a future edit does not
    "simplify" it into a float constructor.
    """
    return to_money(row["initial_cash"])
