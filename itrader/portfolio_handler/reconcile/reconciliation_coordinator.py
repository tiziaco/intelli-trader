"""Owner of the live startup rehydrate → venue-reconcile → baseline-guard sequence.

The venue reconcile is keyed on account KIND (``Account.is_venue_truth``), never on
``exchange == 'okx'``, so a paper/simulated compute account never reaches it while a
durable paper engine still gets its ledger restored.

``halt`` is injected as ``Callable[[str], None]`` so this collaborator does not depend
on the concrete ``SafetyController``. Connector/OKX imports stay LAZY inside method
bodies so importing this module pulls no ccxt/SQL (inertness gate).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Iterable, List, Optional

from itrader.core.enums import HaltReason
from itrader.logger import get_itrader_logger

from .drift import is_within_single_unit_tolerance

if TYPE_CHECKING:
    from queue import Queue


@dataclass(frozen=True, slots=True)
class BaselineResidual:
    """One unexplained (portfolio, symbol) base-asset residual.

    The OBSERVABLE surface of the evaluate-all scan: the halt callable takes a FIXED
    literal reason, so "the scan reported BOTH mismatching portfolios rather than
    stopping at the first" cannot be observed through the halt calls at all — one halt
    looks identical to one halt. Without a collected record a first-mismatch return
    survives a green suite.
    """

    portfolio_id: Any
    account_id: Optional[str]
    symbol: str
    engine_qty: Decimal
    venue_qty: Decimal


class ReconciliationCoordinator:
    """Owns the live startup rehydrate → venue-reconcile → baseline-guard sequence.

    Parameters
    ----------
    portfolio_handler:
        The live ``PortfolioHandler`` — its ``rehydrate`` restores the durable ledger,
        ``get_active_portfolios`` supplies the reconcile/baseline-guard targets, and
        ``_drift_precision`` supplies the per-instrument dust epsilon.
    seed_applied_trades:
        The order-mirror seed sink (``OrderManager.seed_applied_trades``) threaded into
        ``portfolio_handler.rehydrate`` so the dedup ring is restart-seeded symmetrically
        with the portfolio ledger.
    order_storage:
        The order working-set store. Rehydrate + venue reconcile are gated on it exposing
        ``rehydrate`` (the durable CachedSql live store; the in-memory backtest backend is
        a clean skip → oracle-dark).
    execution_handler:
        The pair-keyed venue exchange registry (``exchanges[(venue_name, account_id)]``).
        A single scalar ``exchange`` instead would be handed to EVERY portfolio's
        ``VenueReconciler``, so portfolio B's reconcile would repopulate account **A's**
        correlation map; the registry is keyed by the same pair the portfolio names, so
        there is nothing to mis-address.
    global_queue:
        The shared event queue — reconciling ``FillEvent``s flow through it.
    halt:
        The injected freeze-in-place halt callable (bound to ``SafetyController.halt``).
        Called with the FIXED literal ``HaltReason.BASELINE_RESIDUAL.value`` on an
        unexplained baseline residual — never a stringified exception, so no venue
        secret can leak into an operator-facing halt record.

    Notes
    -----
    There is no scalar account, connector or exchange parameter. Each portfolio supplies
    its own account (``portfolio.account``), that account supplies its own connector
    (``account.connector``), and the registry supplies that account's exchange, so
    comparing portfolio A's believed position against portfolio B's venue truth is
    unexpressible rather than a rule to follow — there is no second account in scope.

    Injecting a map from account key to account object was rejected: it is easier to
    unit-test without portfolios, and that convenience is exactly how a second source of
    truth for "which account does this portfolio use" gets reintroduced.
    """

    def __init__(
        self,
        *,
        portfolio_handler: Any,
        seed_applied_trades: Callable[[Iterable[str]], None],
        order_storage: Any,
        execution_handler: Any,
        global_queue: "Queue[Any]",
        halt: Callable[[str], None],
    ) -> None:
        self._portfolio_handler = portfolio_handler
        self._seed_applied_trades = seed_applied_trades
        self._order_storage = order_storage
        self._execution_handler = execution_handler
        self._global_queue = global_queue
        self._halt = halt
        self.logger = get_itrader_logger().bind(component="ReconciliationCoordinator")

    # ------------------------------------------------------------------ entrypoint
    def run_startup_reconcile(self) -> None:
        """Startup rehydrate → venue-reconcile (venue-truth only) → baseline-guard.

        Runs on the ENGINE thread at startup BEFORE RUNNING, in that order: durable
        ledger RESTORE first (any account kind), then — for a venue-truth account ONLY —
        the venue REST reconcile, then the baseline guard that HALTs on an unexplained
        residual.
        """
        # Restore runs REGARDLESS of account kind, so a durable paper/simulated engine
        # also restores persisted cash + realized PnL. The in-memory backtest backend has
        # no rehydrate() → a clean skip.
        if hasattr(self._order_storage, "rehydrate"):
            self._portfolio_handler.rehydrate(self._seed_applied_trades)

        # Deduped by account IDENTITY: the distinct-account composition invariant
        # (portfolio_handler/rehydrate/distinct_account_invariant.py) refuses two
        # portfolios sharing an account, but this loop must not ASSUME it — a shared
        # account would otherwise be snapshotted twice and given two position streams.
        reconciled: List[int] = []
        for portfolio in self._portfolio_handler.get_active_portfolios():
            account = getattr(portfolio, "account", None)
            if account is None or not account.is_venue_truth:
                continue
            if id(account) in reconciled:
                continue
            reconciled.append(id(account))

            account.snapshot()
            account.start_streaming()

            # Store-gated too (the reconcile needs the rehydrated working set) so an
            # unconfigured durable store degrades cleanly. The lazy import keeps
            # SQL/async/connector off any non-live path (inertness gate).
            if hasattr(self._order_storage, "rehydrate"):
                from itrader.portfolio_handler.reconcile.venue_reconciler import (
                    VenueReconciler,
                )

                reconciler = VenueReconciler(
                    store=self._order_storage,
                    venue_account=account,
                    connector=account.connector,
                    global_queue=self._global_queue,
                    halt_signal=self._halt,
                    exchange=self._exchange_for(portfolio),
                )
                reconciler.reconcile()

        # Sequenced AFTER reconcile and BEFORE RUNNING.
        self._run_session_baseline_guard()

    def _exchange_for(self, portfolio: Any) -> Any:
        """This portfolio's own venue exchange, or ``None`` when none is registered.

        Resolved out of the pair-keyed ``ExecutionHandler.exchanges`` registry — the
        SAME ``(venue_name, account_id)`` key ``on_order`` routes by, so the exchange
        whose correlation map the reconcile repopulates is the exchange that submitted
        the orders. ``None`` is a clean skip on the paper/backtest/test paths, where the
        correlation-map repopulation seam does not exist.

        Deliberately NOT falling back to any other registered exchange: a fallback here
        writes one account's rehydrated orders into another account's correlation map,
        which is a silent cross-account contamination rather than a missing feature.
        """
        venue_name = getattr(portfolio, "venue_name", None) or portfolio.exchange
        account_id = getattr(portfolio, "account_id", None)
        return self._execution_handler.exchanges.get((venue_name, account_id))

    # ------------------------------------------------------------------ baseline guard
    def _run_session_baseline_guard(self) -> List[BaselineResidual]:
        """Session-start baseline guard: HALT on an unexplained base-asset residual.

        Sequenced AFTER reconciliation and BEFORE the engine thread spawns. The reconciler
        has already SYNCED every EXPLAINABLE delta; anything LEFT is a base-asset residual of
        UNKNOWN origin — wrong sub-account wiring, a crashed-session leftover, a forgotten
        manual deposit. The engine must NEVER trade on exposure it cannot explain and must
        NEVER auto-adopt it. Quote-side cash is NOT asserted, because a deposit is
        legitimate funding.

        Scope is every symbol the ACCOUNT holds rather than one configured symbol: any
        narrower scope makes an unexplained residual in an unsubscribed symbol invisible,
        which is precisely the exposure worth knowing about. The accepted cost is that a
        parked, unrelated holding on the same venue account is REPORTED as drift.

        The per-instrument dust epsilon is resolved INSIDE the per-symbol loop, not
        hoisted: one instrument's band applied to another produces both false
        reconciliations and false drift reports.

        EVALUATE ALL, then decide. Returning at the first mismatch stops the scan, so
        every later portfolio's drift is never seen; every portfolio and every symbol is
        evaluated and collected BEFORE any action is taken.

        Returns
        -------
        list[BaselineResidual]
            Every mismatch found, in a STABLE order: portfolios in
            ``get_active_portfolios()`` order (the handler's registration order, which
            rehydrate makes reproducible via its ``portfolio_id ASC`` read), and within
            each portfolio, symbols sorted lexicographically — the sort is what makes the
            report independent of venue-payload dict ordering. Empty when nothing is
            unexplained, including the two benign empty edges: zero active portfolios,
            and an account holding zero positions.
        """
        residuals: List[BaselineResidual] = []
        for portfolio in self._portfolio_handler.get_active_portfolios():
            account = getattr(portfolio, "account", None)
            if account is None or not account.is_venue_truth:
                continue
            for symbol in sorted(account.positions):
                venue_qty = account.positions[symbol]
                # Instrument-specific, so it is resolved per symbol: the same band the
                # on-fill drift compare keys off the instrument's quantity precision.
                precision = self._portfolio_handler._drift_precision(symbol)
                engine_position = portfolio.get_open_position(symbol)
                engine_qty = (
                    engine_position.net_quantity if engine_position is not None
                    else Decimal("0")
                )
                if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
                    continue
                residuals.append(BaselineResidual(
                    portfolio_id=getattr(portfolio, "portfolio_id", None),
                    account_id=getattr(account, "account_id", None),
                    symbol=symbol,
                    engine_qty=engine_qty,
                    venue_qty=venue_qty,
                ))

        # Collect-then-decide: the scan above is COMPLETE before anything below runs.
        for residual in residuals:
            self.logger.error(
                "Session-start baseline guard: unexplained base-asset residual — "
                "halting before trading (venue exposure the engine cannot explain). "
                "Check for ACCOUNT REUSE (ACCT-10/D-32): a fresh portfolio that took over a "
                "(venue, account_id) its retired predecessor left NON-FLAT inherits that "
                "predecessor's open holdings, and this guard tripping IS it working "
                "correctly — the engine must not silently adopt exposure it did not open. "
                "Also check for wrong sub-account wiring or a crashed-session leftover.",
                portfolio_id=str(residual.portfolio_id),
                account_id=str(residual.account_id),
                symbol=residual.symbol,
                engine_qty=str(residual.engine_qty),
                venue_qty=str(residual.venue_qty))
        if residuals:
            # NEVER auto-adopt exposure of unknown origin — latch HALT BEFORE trading,
            # with a FIXED literal reason so no venue detail leaks into the halt record.
            # One halt for the whole scan: halt is engine-wide and latched, so a
            # per-residual call would be N writes of the same state.
            self._halt(HaltReason.BASELINE_RESIDUAL.value)
        return residuals
