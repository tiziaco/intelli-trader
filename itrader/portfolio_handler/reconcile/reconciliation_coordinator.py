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
2. **Venue reconcile** — for a venue-truth account ONLY: snapshot + start_streaming +
   link-to-portfolios + construct a ``VenueReconciler`` and ``reconcile()``. Keyed on
   account KIND (the ``Account.is_venue_truth`` discriminator, SAFE-05 / §11d / A4),
   NOT on ``exchange=='okx'`` — so the paper/simulated (compute) account NEVER reaches
   the venue reconcile (matches the current D-23 RESTORE-only behavior).
3. **Baseline guard** — after reconcile, before RUNNING: HALT via the INJECTED halt
   callable on an unexplained base-asset residual, preserving the FIXED literal reason
   ``HaltReason.BASELINE_RESIDUAL.value`` (never ``str(exc)`` — no venue secret can leak,
   ASVS V7 / T-07-01).

The injected ``halt`` callable is bound to the ``SafetyController``'s halt at wiring
time (Plan 06); authored here as ``Callable[[str], None]`` so this collaborator does not
depend on the concrete ``SafetyController``. No facade back-reference; every dependency
is constructor-injected. All connector/OKX imports stay LAZY inside the method body so
importing this module pulls no ccxt/SQL (inertness gate). 4-space indentation (matches
``core/`` + the ``reconcile/`` siblings ``venue_reconciler.py`` / ``drift.py``).
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Iterable, List

from itrader.core.enums import HaltReason
from itrader.logger import get_itrader_logger

from .drift import is_within_single_unit_tolerance

if TYPE_CHECKING:
    from queue import Queue

    from itrader.portfolio_handler.account.venue import VenueAccount


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
    venue_account:
        The venue-cached account (``VenueAccount``) or ``None`` on the paper/backtest path.
        The venue reconcile runs ONLY when this account's ``is_venue_truth`` is True (A4).
    connector:
        The injected ``LiveConnector`` session the ``VenueReconciler`` reads through.
    exchange:
        The order-arm venue exchange (``OkxExchange``) for correlation-map repopulation,
        or ``None`` on the paper/backtest/test paths.
    global_queue:
        The shared event queue — reconciling ``FillEvent``s flow through it.
    halt:
        The injected freeze-in-place halt callable (bound to ``SafetyController.halt`` in
        Plan 06). Called with the FIXED literal ``HaltReason.BASELINE_RESIDUAL.value`` on
        an unexplained baseline residual (never a stringified exception — V7).
    """

    def __init__(
        self,
        *,
        portfolio_handler: Any,
        seed_applied_trades: Callable[[Iterable[str]], None],
        order_storage: Any,
        venue_account: "VenueAccount | None",
        connector: Any,
        exchange: Any,
        global_queue: "Queue[Any]",
        halt: Callable[[str], None],
    ) -> None:
        self._portfolio_handler = portfolio_handler
        self._seed_applied_trades = seed_applied_trades
        self._order_storage = order_storage
        self._venue_account = venue_account
        self._connector = connector
        self._exchange = exchange
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

        # 2. venue reconcile — venue-truth accounts ONLY (SAFE-05 / §11d / A4). Keyed on
        #    account KIND (Account.is_venue_truth), NOT exchange=='okx', so paper/simulated
        #    (compute) accounts NEVER reach the venue reconcile (D-23 RESTORE-only).
        account = self._venue_account
        if account is None or not account.is_venue_truth:
            return

        account.snapshot()
        account.start_streaming()
        self._link_venue_account_to_portfolios(account)

        # The venue reconcile itself is additionally store-gated (needs the rehydrated
        # working set) so an unconfigured durable store degrades cleanly. Lazy-import keeps
        # the SQL/async/connector import off any non-live path (inertness gate).
        if hasattr(self._order_storage, "rehydrate"):
            from itrader.portfolio_handler.reconcile.venue_reconciler import (
                VenueReconciler,
            )

            reconciler = VenueReconciler(
                store=self._order_storage,
                venue_account=account,
                connector=self._connector,
                global_queue=self._global_queue,
                halt_signal=self._halt,
                exchange=self._exchange,
            )
            reconciler.reconcile()

        # 3. session-start baseline guard, sequenced AFTER reconcile and BEFORE RUNNING.
        self._run_session_baseline_guard(account)

    # ------------------------------------------------------------------ venue-account link
    def _link_venue_account_to_portfolios(self, account: "VenueAccount") -> None:
        """Link the venue-cached account into the active live portfolio (WR-02).

        The ``VenueAccount`` is a FIRST-CLASS KEYED entity — one venue sub-account owning
        that sub-account's balance/available/positions cache — NOT a shared singleton.
        Assigning the SAME instance to every active portfolio would conflate their buying
        power and positions and silently discard each portfolio's prior ledger. Multi-
        portfolio-live needs a per-portfolio ``VenueAccount`` keyed by venue sub-account —
        deferred. Until it exists, FAIL LOUD on MORE THAN ONE active portfolio (a
        ``RuntimeError``, not a strippable ``assert``, so the guard holds under ``python
        -O``). Zero active portfolios is a benign no-op; exactly one is the supported
        single-portfolio-live path.
        """
        active_portfolios = self._portfolio_handler.get_active_portfolios()
        if len(active_portfolios) > 1:
            raise RuntimeError(
                "Live venue-account wiring supports at most one active portfolio "
                f"(found {len(active_portfolios)}). Sharing one VenueAccount "
                "across portfolios would conflate their buying power / positions "
                "and discard each SimulatedAccount ledger. Multi-portfolio-live "
                "requires a per-portfolio VenueAccount keyed by venue sub-account "
                "(AccountId) with position attribution by clOrdId/tag — deferred "
                "work; wire that before running more than one live portfolio.")
        # Zero -> no-op; exactly one -> link the venue-cached account onto it.
        for portfolio in active_portfolios:
            portfolio.account = account

    # ------------------------------------------------------------------ baseline guard (D-04)
    def _run_session_baseline_guard(self, account: "VenueAccount") -> None:
        """Session-start baseline guard (D-04, ARCH-2): HALT on unexplained residual.

        Sequenced AFTER reconciliation and BEFORE the engine thread spawns. The reconciler
        has already SYNCED every EXPLAINABLE delta; anything LEFT is a base-asset residual of
        UNKNOWN origin — wrong sub-account wiring, a crashed-session leftover, a forgotten
        manual deposit. Per ARCH-2 the engine must NEVER trade on exposure it cannot explain
        and must NEVER auto-adopt it. Compare the venue base-asset holding against the
        engine's post-reconcile believed position within the per-instrument dust epsilon
        (F/U-6 — the SAME drift.py band the on-fill compare uses), and on ANY residual
        mismatch call the LATCHED halt (D-05). Quote-side cash is NOT asserted (deposits are
        legitimate funding). The halt reason is a FIXED literal (never ``str(exc)`` — no
        venue secret can leak, ASVS V7 / T-07-01).
        """
        from itrader import config as _system_config
        symbol = _system_config.stream.okx_stream_symbol
        venue_qty = account.positions.get(symbol, Decimal("0"))
        # F/U-6: reuse the per-instrument drift epsilon (the same band the on-fill drift
        # compare keys off the wired instrument's quantity precision).
        precision = self._portfolio_handler._drift_precision(symbol)
        for portfolio in self._portfolio_handler.get_active_portfolios():
            engine_position = portfolio.get_open_position(symbol)
            engine_qty = (
                engine_position.net_quantity if engine_position is not None
                else Decimal("0")
            )
            if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
                continue  # base-asset balance == believed position — trustworthy.
            # Unexplained base-asset residual: NEVER auto-adopt exposure of unknown origin —
            # latch HALT BEFORE trading (D-04/D-05) with the FIXED literal reason (V7).
            self.logger.error(
                "Session-start baseline guard: unexplained base-asset residual — "
                "halting before trading (venue exposure the engine cannot explain)",
                symbol=symbol,
                engine_qty=str(engine_qty),
                venue_qty=str(venue_qty))
            self._halt(HaltReason.BASELINE_RESIDUAL.value)
            return
