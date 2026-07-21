"""ReconciliationCoordinator — the startup rehydrate → venue-reconcile → baseline-guard owner (SAFE-05, D-17).

Single owner of the live startup reconcile sequence, extracted from the
``LiveTradingSystem`` facade's inline ``start()`` block (the donor rehydrate→reconcile
region + ``_run_session_baseline_guard``). Plan 06 wires this coordinator into the
composition root (``VenueLifecycle`` / ``build_live_system``), replacing the facade's
inline block; this plan authors the collaborator only — the facade keeps its inline
block until Plan 06 swaps it.

The sequence ``run_startup_reconcile`` performs, in order:

1. **Rehydrate** the durable portfolio ledger when the order storage exposes
   ``rehydrate`` (RESTORE, D-23) — runs REGARDLESS of account kind so a durable
   paper/simulated engine restores persisted cash + realized PnL on restart.
2. **Venue reconcile** — PER PORTFOLIO, for a venue-truth account ONLY: snapshot +
   start_streaming + construct a ``VenueReconciler`` and ``reconcile()``. Keyed on
   account KIND (the ``Account.is_venue_truth`` discriminator, SAFE-05 / §11d / A4),
   NOT on ``exchange=='okx'`` — so the paper/simulated (compute) account NEVER reaches
   the venue reconcile (matches the current D-23 RESTORE-only behavior).
3. **Baseline guard** — after reconcile, before RUNNING: an EVALUATE-ALL scan over every
   portfolio and every symbol its account holds, collected before deciding, then HALT via
   the INJECTED halt callable on any unexplained base-asset residual, preserving the FIXED
   literal reason ``HaltReason.BASELINE_RESIDUAL.value`` (never ``str(exc)`` — no venue
   secret can leak, ASVS V7 / T-07-01).

**11-09 (D-19/D-20/D-21, MPORT-05) — this collaborator holds NO venue scalars.** It used
to take a ``venue_account``, a ``connector`` and an ``exchange``, all three of which were
the PRIMARY account's and all three of which were applied to every portfolio. Each
portfolio now supplies its own account, that account supplies its own connector, and the
pair-keyed exchange registry supplies that account's exchange — so comparing portfolio A
against account B, or repopulating account A's correlation map from portfolio B's
reconcile, stopped being a rule to remember and became unexpressible.

The injected ``halt`` callable is bound to the ``SafetyController``'s halt at wiring
time (Plan 06); authored here as ``Callable[[str], None]`` so this collaborator does not
depend on the concrete ``SafetyController``. No facade back-reference; every dependency
is constructor-injected. All connector/OKX imports stay LAZY inside the method body so
importing this module pulls no ccxt/SQL (inertness gate). 4-space indentation (matches
``core/`` + the ``reconcile/`` siblings ``venue_reconciler.py`` / ``drift.py``).
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
    """One unexplained (portfolio, symbol) base-asset residual (D-21/F-2, 11-09).

    The OBSERVABLE surface of the evaluate-all scan, and it exists for a reason worth
    stating: the halt callable is ``Callable[[str], None]`` taking a FIXED literal
    reason, so "the scan reported BOTH mismatching portfolios rather than stopping at
    the first" cannot be observed through the halt calls at all — one halt looks
    identical to one halt. Without a collected record the whole D-21 fix would be
    unfalsifiable, which is how a first-mismatch return survives a green suite.

    Frozen: a scan result is a fact about a moment, not a mutable accumulator.
    """

    portfolio_id: Any
    account_id: Optional[str]
    symbol: str
    engine_qty: Decimal
    venue_qty: Decimal


class ReconciliationCoordinator:
    """Owns the live startup rehydrate → venue-reconcile → baseline-guard sequence (SAFE-05, D-17).

    Parameters
    ----------
    portfolio_handler:
        The live ``PortfolioHandler`` — its ``rehydrate`` restores the durable ledger,
        ``get_active_portfolios`` supplies the link/baseline-guard targets, and
        ``_drift_precision`` supplies the per-instrument dust epsilon.
    seed_applied_trades:
        The order-mirror seed sink (``OrderManager.seed_applied_trades``) threaded into
        ``portfolio_handler.rehydrate`` so the dedup ring is restart-seeded symmetrically
        with the portfolio ledger (D-22 / WR-05).
    order_storage:
        The order working-set store. Rehydrate + venue reconcile are gated on it exposing
        ``rehydrate`` (the durable CachedSql live store; the in-memory backtest backend is
        a clean skip → oracle-dark).
    execution_handler:
        The pair-keyed venue exchange registry (``exchanges[(venue_name, account_id)]``).
        11-09 (D-19): REPLACES the former scalar ``exchange`` parameter. That scalar was
        the primary account's exchange and was handed to EVERY portfolio's
        ``VenueReconciler``, so portfolio B's reconcile repopulated account **A's**
        correlation map — the exact cross-account write T-11-44 claims to make
        structurally impossible. The registry is keyed by the same pair the portfolio
        names, so there is nothing to mis-address.
    global_queue:
        The shared event queue — reconciling ``FillEvent``s flow through it.
    halt:
        The injected freeze-in-place halt callable (bound to ``SafetyController.halt`` in
        Plan 06). Called with the FIXED literal ``HaltReason.BASELINE_RESIDUAL.value`` on
        an unexplained baseline residual (never a stringified exception — V7).

    Notes
    -----
    **11-09 / D-19 / MPORT-05 — there is no scalar account, connector or exchange.**
    All three used to be constructor parameters, and with N portfolios that meant every
    portfolio was reconciled against ONE account: comparing portfolio A's believed
    position against portfolio B's venue truth was not merely possible, it was the
    default. Each portfolio now supplies its own account (``portfolio.account``), that
    account supplies its own connector (``account.connector``), and the registry
    supplies that account's exchange. Cross-portfolio comparison is no longer a rule to
    follow — it is unexpressible, because there is no second account in scope.

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
        """Startup rehydrate → venue-reconcile (venue-truth only) → baseline-guard (SAFE-05/D-17).

        Runs on the ENGINE thread at startup BEFORE RUNNING. Sequenced exactly as the donor
        facade block: durable ledger RESTORE first (D-23, any account kind), then — for a
        venue-truth account ONLY — the venue REST reconcile, then the baseline guard that
        HALTs on an unexplained residual (D-04).
        """
        # 1. durable portfolio-ledger RESTORE (D-23): runs whenever the store exposes
        #    rehydrate(), REGARDLESS of exchange/account kind, so a durable paper/simulated
        #    engine restores persisted cash + realized PnL on restart. The in-memory backtest
        #    backend has no rehydrate() → a clean skip (oracle-dark).
        if hasattr(self._order_storage, "rehydrate"):
            self._portfolio_handler.rehydrate(self._seed_applied_trades)

        # 2. venue reconcile — PER PORTFOLIO, venue-truth accounts ONLY (SAFE-05 / §11d /
        #    A4 / D-19). Keyed on account KIND (Account.is_venue_truth), NOT
        #    exchange=='okx', so paper/simulated (compute) accounts NEVER reach the venue
        #    reconcile (D-23 RESTORE-only). Each portfolio is reconciled against ITS OWN
        #    account; there is no scalar account here to reconcile the wrong one against.
        #
        #    Deduped by account IDENTITY: 11-08's distinct-account invariant refuses two
        #    portfolios sharing an account at composition time, but this loop must not
        #    ASSUME it — a shared account would otherwise be snapshotted twice and given
        #    two live position streams.
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

            # The venue reconcile itself is additionally store-gated (needs the
            # rehydrated working set) so an unconfigured durable store degrades cleanly.
            # Lazy-import keeps the SQL/async/connector import off any non-live path
            # (inertness gate).
            if hasattr(self._order_storage, "rehydrate"):
                from itrader.portfolio_handler.reconcile.venue_reconciler import (
                    VenueReconciler,
                )

                reconciler = VenueReconciler(
                    store=self._order_storage,
                    venue_account=account,
                    # D-19: the connector comes from THAT account, not from a separate
                    # scalar parameter — one source of truth. A second parameter is how
                    # portfolio A's reconcile ends up reading account B's session.
                    connector=account.connector,
                    global_queue=self._global_queue,
                    halt_signal=self._halt,
                    exchange=self._exchange_for(portfolio),
                )
                reconciler.reconcile()

        # 3. session-start baseline guard, sequenced AFTER reconcile and BEFORE RUNNING.
        self._run_session_baseline_guard()

    def _exchange_for(self, portfolio: Any) -> Any:
        """This portfolio's own venue exchange, or ``None`` when none is registered.

        Resolved out of the pair-keyed ``ExecutionHandler.exchanges`` registry — the
        SAME ``(venue_name, account_id)`` key ``on_order`` routes by, so the exchange
        whose correlation map the reconcile repopulates is the exchange that submitted
        the orders. ``None`` is a clean skip on the paper/backtest/test paths (the
        correlation-map repopulation seam is live-only).

        Deliberately NOT falling back to any other registered exchange: a fallback here
        writes one account's rehydrated orders into another account's correlation map,
        which is a silent cross-account contamination rather than a missing feature.
        """
        venue_name = getattr(portfolio, "venue_name", None) or portfolio.exchange
        account_id = getattr(portfolio, "account_id", None)
        return self._execution_handler.exchanges.get((venue_name, account_id))

    # ``_link_venue_account_to_portfolios`` — the single-account attach that assigned ONE
    # scalar ``VenueAccount`` to every active portfolio and raised ``RuntimeError`` at
    # N>1 — is DELETED here rather than in plan 11-07b as originally sequenced. It lost
    # its only caller the moment the venue reconcile became per-portfolio, and leaving a
    # dead-but-callable "assign one account to all portfolios" method inside the very
    # collaborator this plan made per-portfolio is the precise footgun the change exists
    # to remove: the next caller to reach for it would silently re-conflate two real
    # venue balances. Attachment now happens once, at composition, in
    # ``live_trading_system._attach_venue_accounts``, resolved by each portfolio's own
    # ``account_id``. Its N>1 ``RuntimeError`` is not "lost" — 11-08's
    # ``assert_distinct_accounts`` refuses the collision it guarded against, earlier and
    # over the union of persisted and spec-supplied portfolios.

    # ------------------------------------------------------------------ baseline guard (D-04)
    def _run_session_baseline_guard(self) -> List[BaselineResidual]:
        """Session-start baseline guard (D-04/D-20/D-21, ARCH-2): HALT on unexplained residual.

        Sequenced AFTER reconciliation and BEFORE the engine thread spawns. The reconciler
        has already SYNCED every EXPLAINABLE delta; anything LEFT is a base-asset residual of
        UNKNOWN origin — wrong sub-account wiring, a crashed-session leftover, a forgotten
        manual deposit. Per ARCH-2 the engine must NEVER trade on exposure it cannot explain
        and must NEVER auto-adopt it. Quote-side cash is NOT asserted (deposits are
        legitimate funding). The halt reason is a FIXED literal (never ``str(exc)`` — no
        venue secret can leak, ASVS V7 / T-07-01).

        Three properties, each of which was a defect before 11-09:

        **D-20 — every symbol the ACCOUNT holds, not one globally configured symbol.**
        The guard used to read ``config.stream.okx_stream_symbol`` and check that ONE
        symbol. That is a blind spot that exists at ONE portfolio, single-account or not:
        an unexplained residual in any other symbol was invisible, and an unexplained
        residual is precisely the exposure worth knowing about. The accepted cost is that
        a parked, unrelated holding on the same venue account is now REPORTED as drift —
        a behavior change relative to before, and the intended trade (the narrower
        union-of-subscribed-symbols scope was considered and rejected for exactly the
        reason above).

        **D-20 — per-instrument precision resolved INSIDE the per-symbol loop.** The dust
        epsilon is instrument-specific. Hoisting it outside the loop was harmless while
        exactly one symbol was ever checked and is wrong the moment two are: one
        instrument's band applied to another produces both false reconciliations and
        false drift reports.

        **D-21/F-2 — EVALUATE ALL, then decide.** The scan used to ``return`` immediately
        after the first halt. At one portfolio that is benign; at N it stops the scan, so
        every later portfolio's drift is never seen — and plan 11-10's per-portfolio
        quarantine makes it worse than cosmetic, because it would quarantine one account
        and leave the rest unexamined. Every portfolio and every symbol is now evaluated
        and collected BEFORE any action is taken.

        Boundary semantics (documented, not incidental): ``is_within_single_unit_tolerance``
        is INCLUSIVE — ``abs(engine - venue) <= 10**-precision`` — so exactly-equal is
        reconciled and exactly-at-the-tolerance-band is ALSO reconciled. Only a difference
        strictly GREATER than one least-significant unit is a residual.

        Returns
        -------
        list[BaselineResidual]
            Every mismatch found, in a STABLE documented order: portfolios in
            ``get_active_portfolios()`` order (the handler's registration order, which
            rehydrate makes reproducible via its ``portfolio_id ASC`` read), and within
            each portfolio, symbols sorted lexicographically. Sorting the symbols is what
            makes the report independent of venue-payload dict ordering. Empty when
            nothing is unexplained — including the two benign empty edges: zero active
            portfolios, and an account holding zero positions.
        """
        residuals: List[BaselineResidual] = []
        for portfolio in self._portfolio_handler.get_active_portfolios():
            account = getattr(portfolio, "account", None)
            if account is None or not account.is_venue_truth:
                continue
            # D-20: EVERY symbol this account holds a position in. An empty map is a
            # benign no-op (nothing held ⇒ nothing unexplained).
            for symbol in sorted(account.positions):
                venue_qty = account.positions[symbol]
                # F/U-6 + D-20: the per-instrument drift epsilon, resolved HERE inside
                # the per-symbol iteration because it is instrument-specific — the same
                # band the on-fill drift compare keys off the instrument's quantity
                # precision.
                precision = self._portfolio_handler._drift_precision(symbol)
                engine_position = portfolio.get_open_position(symbol)
                engine_qty = (
                    engine_position.net_quantity if engine_position is not None
                    else Decimal("0")
                )
                if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
                    continue  # holding == believed position, within the band — trustworthy.
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
                "halting before trading (venue exposure the engine cannot explain)",
                portfolio_id=str(residual.portfolio_id),
                account_id=str(residual.account_id),
                symbol=residual.symbol,
                engine_qty=str(residual.engine_qty),
                venue_qty=str(residual.venue_qty))
        if residuals:
            # NEVER auto-adopt exposure of unknown origin — latch HALT BEFORE trading
            # (D-04/D-05) with the FIXED literal reason (V7). One halt for the whole
            # scan: halt is engine-wide and latched, so a per-residual call would be N
            # writes of the same state. Plan 11-10 replaces this terminal action with the
            # per-portfolio quarantine, which is why the SCAN had to become complete
            # first — the action changes, the collection does not.
            self._halt(HaltReason.BASELINE_RESIDUAL.value)
        return residuals
