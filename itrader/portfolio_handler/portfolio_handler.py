"""Portfolio lifecycle, fill settlement and global configuration for the portfolio domain."""
from collections import OrderedDict
from datetime import datetime, UTC
from decimal import Decimal
from typing import Dict, Iterable, Optional, Any, List, Generator, Union, Callable
from contextlib import contextmanager

from .portfolio import Portfolio
from .position import Position
from .account import Account, SimulatedMarginAccount, VenueAccount
from itrader.portfolio_handler.reconcile import is_within_single_unit_tolerance
from itrader.core.exceptions import (
    PortfolioNotFoundError, InvalidPortfolioOperationError,
    PortfolioStateError, PortfolioValidationError, PortfolioConfigurationError,
    StateError,
)
from itrader.core.enums import (
    PortfolioState, TransactionType, FillStatus, Side, PositionSide,
    OrderType, OrderStatus, OrderTriggerSource,
)
from itrader.core.ids import OrderId, PortfolioId, TransactionId, CorrelationId, StrategyId
from itrader.order_handler.base import OrderStorage
from itrader.order_handler.order import Order
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import OrderEvent
from itrader.core.portfolio_read_model import PositionView
from itrader.core.money import to_money, quantize
from itrader.portfolio_handler.transaction import Transaction
from itrader.events_handler.events import BarEvent, FillEvent, PortfolioUpdateEvent, PortfolioErrorEvent
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.exceptions.base import ConfigurationError

import pydantic

from itrader import idgen
from itrader.logger import get_itrader_logger


class PortfolioHandler:
    """Portfolio lifecycle, global configuration, health monitoring and fill routing.

    Individual portfolios own their own state (ACTIVE/INACTIVE/ARCHIVED), configuration
    and health.

    Single-writer contract: ALL portfolio state mutations happen on the engine thread;
    queue.Queue is the thread boundary — other threads only put events. Composite reads
    are consistent because nothing mutates concurrently, which is why the portfolio
    collection carries no lock.
    """
    
    def __init__(self, global_queue: "EventBus", config_dir: str = "settings",
                 environment: str = "backtest", sql_engine: "Optional[Any]" = None,
                 *,
                 portfolio_factory: "Optional[Any]" = None) -> None:
        self.global_queue: "EventBus" = global_queue
        self.current_time: Any = 0

        # Durable portfolio-storage selector. "backtest" is the in-memory path; "live"
        # plus the shared SqlEngine persists every portfolio to the SQL ledger and
        # rehydrates its truth on restart. ``sql_engine`` is typed Any to keep the
        # SqlEngine import off this module (GATE-01 inertness).
        self._environment = environment
        self._sql_engine = sql_engine

        # The SOLE leaf-builder: ``materialize`` builds every portfolio's runtime graph —
        # id-scoped ``PortfolioStateStorage`` seam, ``Account`` leaf, ``Portfolio`` — through
        # this factory, so account-kind selection and venue-truth authority live in ONE
        # place. The factory holds a real, mode-agnostic authority at construction (live:
        # ``VenueAccountManager``, raises on a missing/disabled/not-online account;
        # backtest: the compute authority, ``account_id`` None, never raises). Typed
        # ``Optional[Any]`` for the GATE-01 reason ``sql_engine`` is; ``None`` is the
        # direct-construction arm (unit tests that never call ``add_portfolio``).
        self._factory = portfolio_factory

        # The ``portfolios`` DEFINITION-row writer. Constructed here rather than at the
        # composition root so POST-BOOT ``add_portfolio`` calls persist too — live
        # portfolios are added by the application after build_live_system returns, and a
        # writer that only ran at boot would persist none of them.
        #
        # The import is LAZY inside the gate deliberately: this module is on the BACKTEST
        # import graph and the store pulls SQLAlchemy, so a module-top import breaks the
        # GATE-01 inertness gate (tests/integration/test_okx_inertness.py).
        self.definition_store: Optional[Any] = None
        if environment == "live" and sql_engine is not None:
            from itrader.storage.portfolio_definition_store import (
                PortfolioDefinitionStore,
            )
            self.definition_store = PortfolioDefinitionStore(sql_engine)

        # Pydantic validates on construction, so no separate validator is needed.
        self.config_data: PortfolioConfig = PortfolioConfig.default()

        # limits.max_portfolios, NOT limits.max_positions (the per-portfolio limit).
        self.max_portfolios = self.config_data.limits.max_portfolios
        self.publish_error_events = True  # Default behavior

        # Keyed by PortfolioId (UUID) at runtime while events still carry an int
        # portfolio_id; typed Any to bridge both forms until that migration completes.
        # No collection lock — single-writer contract, see the class docstring.
        self._portfolios: Dict[Any, Portfolio] = {}

        # The injected Universe read-model resolving each open position's Instrument
        # (maintenance_margin_rate) on demand. None until ``set_universe`` is called by
        # the runner, AFTER this handler is constructed in compose_engine.
        self._universe: Any = None

        # The narrow injected write-seam the liquidation engine uses to register a
        # forced-close Order in the shared order mirror (set via ``set_order_storage``).
        # compose.py injects the SAME instance the OrderHandler/ReconcileManager hold, so
        # the portfolio side writes into the exact mirror the reconcile reads.
        self._order_storage: Optional[OrderStorage] = None

        # Engine-thread drift-halt seam: the live root injects ``LiveTradingSystem.halt``
        # via ``set_halt_signal`` and unexplained beyond-band per-symbol drift freezes the
        # WHOLE engine. None on backtest — no VenueAccount portfolio, so no compare.
        self._halt_signal: Optional[Callable[[str], None]] = None
        # Answers whether a beyond-band drift maps to a KNOWN venue event (an external
        # cancel / external or hand-closed fill) and is therefore adopt-and-continue
        # rather than a halt. ``None`` → the conservative money-first default: any
        # beyond-band drift is unexplained and halts.
        self._drift_reconciler: Optional[
            Callable[[Any, str, Decimal, Decimal], bool]
        ] = None

        # Bounded-FIFO ledger of already-settled venue trade ids — the cross-emitter
        # fill-dedup guard. The live OKX stream and the restart VenueReconciler can both
        # book the SAME economic venue trade, and they share no other idempotency key
        # (fill_id is a fresh uuid7 per emit). ``on_fill`` rejects an id already here so
        # position/cash settle exactly once; the cap keeps a long-running session bounded.
        # Backtest/simulated fills carry venue_trade_id=None and never touch it.
        self._settled_venue_trade_ids: "OrderedDict[str, None]" = OrderedDict()
        self._max_settled_venue_trade_ids = 100_000

        # Global logger
        self.logger = get_itrader_logger().bind(component="PortfolioHandler")

        self.logger.info(
            "Enhanced PortfolioHandler initialized",
            max_portfolios=self.max_portfolios
        )

    def _generate_correlation_id(self) -> CorrelationId:
        """Generate a unique correlation ID for operation tracking."""
        return CorrelationId(idgen.generate_correlation_id())

    def _publish_error_event(self, error: Exception, operation: str, correlation_id: CorrelationId, portfolio_id: Optional[Any] = None) -> None:
        """Publish error event if enabled."""
        if not self.publish_error_events:
            return
        
        # Wall-clock carve-out: error paths never fire during a green oracle run, so
        # datetime.now(UTC) here cannot perturb determinism — the engine path itself
        # stays on business time.
        error_event = PortfolioErrorEvent(
            time=datetime.now(UTC),
            error_type=type(error).__name__,
            error_message=str(error),
            operation=operation,
            correlation_id=correlation_id,
            portfolio_id=portfolio_id
        )

        self.global_queue.put(error_event)
    
    @contextmanager
    def _operation_context(self, operation_name: str) -> Generator[CorrelationId, None, None]:
        """Context manager supplying a correlation ID for operation tracking.

        Carries no concurrency-limiting machinery: the single-writer contract makes it
        unnecessary.
        """
        correlation_id = self._generate_correlation_id()
        yield correlation_id
    
    # Main portfolio management methods (keeping same names for compatibility)
    def add_portfolio(self, name: str, exchange: str, cash: "float | Decimal",
                      portfolio_config: Optional[PortfolioConfig] = None,
                      portfolio_id: Optional[PortfolioId] = None,
                      account_id: Optional[str] = None,
                      venue_name: Optional[str] = None) -> PortfolioId:
        """Create a portfolio: write its definition row, then build its runtime graph.

        ``portfolio_id`` / ``account_id`` / ``venue_name`` mirror ``Portfolio.__init__``
        one-for-one and are threaded straight through. All three default, so a minimal
        call works, but the backtest composition root passes ``venue_name`` EXPLICITLY —
        the same shape a live portfolio is created with.

        * ``portfolio_id`` — an EXISTING id to reattach to on rehydrate. Supplying an id
          already registered RAISES rather than overwriting: a silent overwrite would
          destroy the first portfolio's cash and positions.
        * ``account_id`` — the venue account this portfolio's orders reach.
        * ``venue_name`` — the source of truth for the portfolio's exchange; when
          supplied it wins and ``exchange`` is derived from it.
        """

        with self._operation_context("add_portfolio") as correlation_id:
            try:
                # Global validations (creation-input; rehydrate trusts the store's rows).
                if cash <= 0:
                    raise PortfolioValidationError(0, "initial_cash", "Initial cash must be positive")

                if not name.strip():
                    raise PortfolioValidationError(0, "name", "Portfolio name cannot be empty")

                # The id is resolved HERE so the definition row and the runtime graph carry
                # the SAME id. ``create`` runs FIRST: a create that succeeds followed by a
                # materialize that raises leaves a durable row with no live Portfolio — the
                # next boot rehydrates it, so the row is not orphaned.
                resolved_id = (
                    portfolio_id if portfolio_id is not None
                    else PortfolioId(idgen.generate_portfolio_id())
                )
                self.create(
                    resolved_id,
                    name=name,
                    cash=cash,
                    account_id=account_id,
                    venue_name=venue_name,
                )
                portfolio = self.materialize(
                    name=name,
                    exchange=exchange,
                    cash=cash,
                    config=portfolio_config,
                    portfolio_id=resolved_id,
                    account_id=account_id,
                    venue_name=venue_name,
                )

                self.logger.info(
                    "Portfolio created successfully",
                    portfolio_id=portfolio.portfolio_id,
                    name=name,
                    initial_cash=cash,
                    correlation_id=correlation_id
                )

                return portfolio.portfolio_id

            except Exception as e:
                self._publish_error_event(e, "add_portfolio", correlation_id)
                raise

    def create(self, portfolio_id: PortfolioId, *, name: str,
               cash: "float | Decimal", account_id: Optional[str],
               venue_name: Optional[str]) -> None:
        """Write this portfolio's DEFINITION row — the durable half of create/materialize.

        The row records what a portfolio IS (``portfolio_id`` / ``name`` /
        ``(venue_name, account_id)`` / ``initial_cash``): the source of truth
        ``rehydrate_portfolios`` reads at the next boot, and the persisted ``portfolio_id``
        is what reattaches the child tables across a restart. It builds no Portfolio and
        registers nothing — that is ``materialize``'s job.

        ``create`` runs ONCE per ``portfolio_id`` (rehydrate materializes only and never
        re-enters here; ``add_portfolio`` refuses a duplicate id via ``materialize``), so
        the INSERT is always a first write and needs no absence gate.

        There is deliberately NO early return for a portfolio naming no
        ``(venue_name, account_id)``: skipping the row would disagree with
        ``SqlPortfolioStorage.save_config``, which RAISES ``PortfolioStateError`` on
        ``rowcount == 0`` — the very row it expects this path to have made. Without the
        skip this either writes the row or fails LOUD on the composite FK onto
        ``venue_accounts``, so the two halves cannot drift.

        A write failure PROPAGATES (``add_portfolio``'s except arm publishes the error
        event and re-raises): a definition that did not persist would boot into nothing on
        the next restart while its positions and cash rows orphan — a silent money loss,
        worse than failing loud. The no-store guard stays: on the backtest/in-memory arm
        there is nothing to write.
        """
        if self.definition_store is None:
            return
        self.definition_store.upsert(
            portfolio_id,
            name=name,
            venue_name=venue_name,
            account_id=account_id,
            initial_cash=to_money(cash),
            enabled=True,
            # config is owned by save_config/load_config on this row; a definition write
            # never authors or overwrites it.
            config=None,
            at=datetime.now(UTC),
        )

    def materialize(self, name: str, exchange: str, cash: "float | Decimal",
                    config: Optional[PortfolioConfig] = None,
                    portfolio_id: Optional[PortfolioId] = None,
                    account_id: Optional[str] = None,
                    venue_name: Optional[str] = None) -> Portfolio:
        """Build the runtime Portfolio through the factory and register it — the BUILD half.

        Builds the id-scoped state-storage seam, the ``Account`` leaf and the ``Portfolio``
        over them through the injected factory, then REGISTERS the portfolio. It writes
        NOTHING durable — the definition row is ``create``'s job. Both ``add_portfolio``
        and ``rehydrate_portfolios`` call this, so the duplicate-id guard and the
        max-portfolios limit live HERE, where registration happens, and both callers
        inherit them.

        On the LIVE arm the factory's authority is the ``VenueValidatedComputeAuthority``,
        so a portfolio naming a not-provisioned/disabled account raises
        ``VenueAccountNotProvisionedError`` rather than silently sitting on a fabricated
        balance; on backtest the compute authority builds an ``account_id=None`` leaf and
        never raises.
        """
        # A handler built without a factory (the direct-construction unit arm) cannot build
        # portfolios: refuse LOUDLY. The tempting inline ``SimulatedCashAccount(...)``
        # fallback would reinstate a second account-kind selection, on a path nothing covers.
        if self._factory is None:
            raise PortfolioConfigurationError(
                "portfolio_factory", None,
                "PortfolioHandler was constructed without a PortfolioFactory, so it cannot "
                "build this portfolio's account leaf (D-24). Refusing to mint an account "
                "inline — that would put account-kind selection back in a second place.",
            )

        # A duplicate id must fail loud — the registry write below is an unconditional dict
        # assignment, so without this a re-materialize would SILENTLY destroy the first
        # portfolio along with its cash and open positions. It lives HERE (not in
        # add_portfolio) so rehydrate inherits it too.
        if portfolio_id is not None and portfolio_id in self._portfolios:
            raise PortfolioValidationError(
                portfolio_id, "portfolio_id",
                "A portfolio with this id is already registered"
            )

        # Enforced at REGISTRATION so both the add and the rehydrate path honour it.
        if len(self._portfolios) >= self.max_portfolios:
            raise PortfolioConfigurationError(
                "max_portfolios", self.max_portfolios,
                "maximum portfolios limit reached")

        # ``self._factory`` is typed ``Any`` (GATE-01), so pin the built object to
        # ``Portfolio`` — that keeps ``portfolio.portfolio_id`` a real ``PortfolioId``.
        portfolio: Portfolio = self._factory.materialize(
            name=name,
            exchange=exchange,
            cash=cash,
            config=config,
            portfolio_id=portfolio_id,
            account_id=account_id,
            venue_name=venue_name,
        )
        self._portfolios[portfolio.portfolio_id] = portfolio
        return portfolio

    def get_portfolio(self, portfolio_id: PortfolioId) -> Portfolio:
        """Get portfolio instance."""
        if portfolio_id not in self._portfolios:
            raise PortfolioNotFoundError(portfolio_id)
        return self._portfolios[portfolio_id]

    def has_portfolio(self, portfolio_id: PortfolioId) -> bool:
        """Whether a portfolio with this id is REGISTERED in this process.

        The narrowest public registration predicate, so ``rehydrate_portfolios`` can skip
        an already-registered id without reaching the private ``_portfolios`` map.
        """
        return portfolio_id in self._portfolios

    def all_portfolios(self) -> Dict[PortfolioId, Portfolio]:
        """Every REGISTERED portfolio regardless of state, keyed by ``portfolio_id``.

        The handler's full public read surface alongside ``has_portfolio``;
        ``get_active_portfolios()`` answers a DIFFERENT question (ACTIVE only).

        Returns a SHALLOW COPY of the registry, never the live private dict: an accessor
        that lets a caller mutate the registry is the reach-in with extra steps.
        ``has_portfolio(pid)`` is true exactly when ``pid`` is a key here — both read the
        same registry, so the two cannot disagree. An empty registry returns an empty
        mapping, never ``None``; entries preserve insertion order.
        """
        return dict(self._portfolios)

    def delete_portfolio(self, portfolio_id: PortfolioId, force: bool = False) -> bool:
        """Delete a portfolio with validation."""
        
        with self._operation_context("delete_portfolio") as correlation_id:
            try:
                portfolio = self.get_portfolio(portfolio_id)
                
                # Validate deletion is allowed
                if not force:
                    if portfolio.n_open_positions > 0:
                        raise InvalidPortfolioOperationError("Cannot delete portfolio with open positions")
                    
                    if portfolio.cash > 0:
                        raise InvalidPortfolioOperationError("Cannot delete portfolio with remaining cash")
                
                # RETIRE the definition durably BEFORE the in-memory teardown. Persisting
                # is_deleted=True first orders the failure the safe way: a crash after this
                # leaves the row RETIRED (rehydrate's read_all filters is_deleted, so it
                # never returns), never a still-live row that comes back trading. Retiring
                # also RELEASES the (venue_name, account_id) pair for a successor. None on
                # the backtest/in-memory arm — nothing durable to retire.
                if self.definition_store is not None:
                    self.definition_store.set_deleted(portfolio_id, True, datetime.now(UTC))

                # Archive portfolio (terminal in-memory state) first
                portfolio.set_state(PortfolioState.ARCHIVED, "Portfolio deletion")

                # Remove from collection
                del self._portfolios[portfolio_id]

                self.logger.info(
                    "Portfolio deleted successfully",
                    portfolio_id=portfolio_id,
                    force=force,
                    correlation_id=correlation_id
                )
                
                return True
                
            except Exception as e:
                self._publish_error_event(e, "delete_portfolio", correlation_id, portfolio_id)
                raise
    
    def deactivate_portfolio(self, portfolio_id: PortfolioId) -> None:
        """PAUSE a portfolio durably — persist enabled=False, THEN flip in memory.

        The pause is ONE operation — the durable write and the in-memory
        ``Portfolio.set_state(INACTIVE)`` flip — performed here in the handler, which
        already owns the definition store. ``Portfolio.set_state`` stays a pure in-memory
        domain transition holding NO storage (rejected: a state-change callback on
        ``Portfolio``, which puts persistence inside the domain object; and an event-driven
        persist, which is asynchronous relative to the flip and loses the deactivation on a
        crash between the two).

        Crash-safety ORDERING: persist ``enabled=False`` BEFORE the in-memory flip, so the
        state surviving ANY crash between the two halves is always "stopped", never
        "trading". On restart the present-but-inactive rehydrate branch reconstructs it
        INACTIVE from the persisted ``enabled=False``. Idempotent: re-deactivating
        re-persists and ``set_state`` is a no-op, so it does not raise.

        Disabling a portfolio NEVER touches its venue account — a venue account is a real
        external thing that outlives any number of internal portfolios. On the
        backtest/in-memory arm this is the in-memory flip alone.
        """
        portfolio = self.get_portfolio(portfolio_id)
        if self.definition_store is not None:
            self.definition_store.set_enabled(portfolio_id, False, datetime.now(UTC))
        portfolio.set_state(PortfolioState.INACTIVE, "operator deactivation (ACCT-10/D-30)")

    def activate_portfolio(self, portfolio_id: PortfolioId) -> None:
        """RESUME a portfolio durably — flip in memory FIRST, THEN persist enabled=True.

        The mirror of ``deactivate_portfolio``, ordered the OTHER way for the SAME reason:
        the state surviving any crash must be "stopped", so this flips to ACTIVE first and
        persists ``enabled=True`` only after. A crash between the two leaves the durable row
        still ``enabled=False``, so the next boot rehydrates it INACTIVE — never a portfolio
        that returns trading on a half-completed resume. Idempotent.
        """
        portfolio = self.get_portfolio(portfolio_id)
        portfolio.set_state(PortfolioState.ACTIVE, "operator activation (ACCT-10/D-30)")
        if self.definition_store is not None:
            self.definition_store.set_enabled(portfolio_id, True, datetime.now(UTC))

    def get_active_portfolios(self) -> List[Portfolio]:
        """Get all active portfolios."""
        return [p for p in self._portfolios.values() if p.is_active()]

    def get_portfolios_by_state(self, state: PortfolioState) -> List[Portfolio]:
        """Get portfolios by state."""
        return [p for p in self._portfolios.values() if p.state == state]

    def get_portfolio_count(self) -> int:
        """Get total portfolio count."""
        return len(self._portfolios)

    # PortfolioReadModel — structural Protocol implementation.
    #
    # The order domain reads portfolio state through this narrow Protocol surface ONLY
    # (itrader/core/portfolio_read_model.py). No inheritance, no adapter. Live Position
    # objects never cross the boundary — get_position returns a frozen PositionView.

    def active_portfolio_ids(self) -> List[PortfolioId]:
        """Return the ids of all active portfolios."""
        return [p.portfolio_id for p in self._portfolios.values() if p.is_active()]

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        """Return the portfolio's buying power (balance minus reservations)."""
        return self.get_portfolio(portfolio_id).account.available_balance

    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> Optional[PositionView]:
        """Return a frozen snapshot of the open position, or None when flat."""
        position = self.get_portfolio(portfolio_id).get_open_position(ticker)
        if position is None:
            return None
        return PositionView(
            ticker=position.ticker,
            side=position.side,
            net_quantity=position.net_quantity,
            avg_price=position.avg_price,
        )

    def reserve(self, portfolio_id: PortfolioId, order_id: OrderId, amount: Decimal) -> None:
        """Reserve cash for a pending order (per-reference, full precision).

        The ``PortfolioReadModel`` signature is FROZEN and keyed by ``portfolio_id``,
        which the Account has no notion of; only the delegation re-points to the
        Account-level ``reserve(order_id, amount)``.
        """
        self.get_portfolio(portfolio_id).account.reserve(order_id, amount)

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Release the cash reservation keyed by an order id (idempotent)."""
        self.get_portfolio(portfolio_id).account.release(order_id)

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Drop the local pending overlay on the venue ORDER-ACK.

        Getattr-guarded: only ``VenueAccount`` carries a pending overlay, so this resolves
        ``account.drop_pending`` dynamically and skips cleanly for paper/simulated
        accounts. NON-terminal — it pops only the admission overlay, never the settled
        ledger.
        """
        fn = getattr(self.get_portfolio(portfolio_id).account, "drop_pending", None)
        if fn is not None:
            fn(order_id)

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on."""
        exchange: str = self.get_portfolio(portfolio_id).exchange
        return exchange

    def account_for(self, portfolio_id: PortfolioId) -> Optional[str]:
        """Return the venue account the portfolio's orders reach.

        The mirror of ``exchange_for``: an order's target is the pair
        ``(venue, account_id)`` and this reads the account half. Routed through
        ``get_portfolio``, so an unknown id raises ``PortfolioNotFoundError``.
        ``Optional[str]`` because ``Portfolio.account_id`` is optional; a
        composition-time invariant is what requires a named account in live.
        """
        account_id: Optional[str] = self.get_portfolio(portfolio_id).account_id
        return account_id

    def open_position_count(self, portfolio_id: PortfolioId) -> int:
        """Return the number of open positions."""
        count: int = self.get_portfolio(portfolio_id).n_open_positions
        return count

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        """Return total equity as Decimal: full cash balance + position market values.

        Computed from the Decimal internals directly, NEVER through the float
        ``Portfolio.total_equity`` property. Uses the FULL ledger balance (available cash
        plus reservations) — equity is a sizing/metrics figure, not buying power.
        """
        portfolio = self.get_portfolio(portfolio_id)
        return (
            portfolio.account.balance
            + portfolio.position_manager.get_total_market_value()
        )

    def set_universe(self, universe: Any) -> None:
        """Inject the Universe read-model used to resolve per-symbol Instruments.

        Called by the runner once the Universe is built. ``maintenance_margin`` reads
        ``universe.instrument(ticker).maintenance_margin_rate`` per open position; since
        the margin/liquidation math lives on ``SimulatedMarginAccount`` and reads the
        account's OWN Universe, the reference is propagated down to each existing margin
        account. Spot accounts have no margin surface and are skipped. Backtest adds all
        portfolios before this call, so every margin account is reached.
        """
        self._universe = universe
        for portfolio in self._portfolios.values():
            account = portfolio.account
            if isinstance(account, SimulatedMarginAccount):
                account.set_universe(universe)

    def set_order_storage(self, order_storage: OrderStorage) -> None:
        """Inject the shared order mirror for the liquidation forced-close.

        The BAR-route liquidation engine uses this to register a real forced-close
        ``Order`` so ``ReconcileManager.on_fill`` reconciles EXECUTED→FILLED — without the
        registered order the reconcile early-returns and the mirror silently no-ops.
        ``compose.py`` injects the SAME instance the ``OrderHandler``/``ReconcileManager``
        hold, so the mirror is a single shared store. NOT a raw handler-to-handler call and
        NOT an enqueued OrderEvent (the ORDER route would fill next-bar-open)."""
        self._order_storage = order_storage

    def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
        """Return maintenance margin computed on demand.

        A thin pass-through: the math lives on ``SimulatedMarginAccount``, reading the
        account's OWN injected Universe plus the portfolio-side inputs this handler
        supplies (the open positions and the portfolio id). A spot
        (``SimulatedCashAccount``) account has no margin requirement and returns
        ``Decimal("0")``. The ``PortfolioReadModel`` signature is FROZEN.
        """
        portfolio = self.get_portfolio(portfolio_id)
        account = portfolio.account
        if not isinstance(account, SimulatedMarginAccount):
            return Decimal("0")
        # Pass ``portfolio.portfolio_id``, NOT the ``portfolio_id`` argument: the argument
        # may arrive as an int under the in-flight id migration (which is why
        # ``_portfolios`` is Any-keyed), and the StateError carries the resolved
        # PortfolioId as its attribution context.
        return account.maintenance_margin(
            portfolio.position_manager.get_all_positions(),
            portfolio.portfolio_id,
        )

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        """Return ``total_equity / maintenance_margin``.

        A thin pass-through to ``SimulatedMarginAccount.margin_ratio``, supplied with the
        portfolio-side inputs (mark-to-market equity, the open positions, the portfolio
        id); the ratio arithmetic and its zero-maintenance sentinel stay on the leaf. A
        spot account returns the deterministic ``Decimal("0")`` sentinel. Signature FROZEN.
        """
        portfolio = self.get_portfolio(portfolio_id)
        account = portfolio.account
        if not isinstance(account, SimulatedMarginAccount):
            return Decimal("0")
        return account.margin_ratio(
            portfolio.total_equity,
            portfolio.position_manager.get_all_positions(),
            portfolio.portfolio_id,
        )

    # ------------------------------------------------------------------
    # Isolated-margin liquidation engine. The BAR-route per-position breach check runs
    # AFTER the per-portfolio mark + carry pass, so a breach sees carry-eroded equity.
    #
    # The pure-Decimal MATH (``_isolated_liq_price`` / ``_is_breached`` /
    # ``_liquidation_penalty`` / ``_liq_inputs``) lives on ``SimulatedMarginAccount``; the
    # EMISSION SHELL stays here (``order_storage.add_order`` + the ``OrderEvent`` /
    # ``FillEvent`` mint + ``global_queue.put`` + log) and calls down into the portfolio's
    # margin account for the math. The queue-only rule is preserved — the account has no
    # queue. Spot accounts have no margin/liquidation surface and are skipped. The liq
    # price is quantized to the instrument price scale ONLY at the FillEvent boundary in
    # the mint step, never mid-formula.
    # ------------------------------------------------------------------

    def _liquidate_position(self, portfolio: Portfolio, position: Position,
                            liq_price: Decimal, fee_rate: Decimal,
                            bar_time: datetime) -> None:
        """Force-close a breached position on the BAR route.

        Mints a REAL opposite-side ``Order`` (SELL to close a long / BUY to close a short;
        qty = ``|net_quantity|``) tagged ``OrderTriggerSource.LIQUIDATION``, registers it
        in the injected ``order_storage`` (without this ``ReconcileManager.on_fill``
        early-returns and the mirror never reaches FILLED), and emits a
        ``FillEvent(EXECUTED)`` DIRECTLY on the queue at the liq price with
        ``time=bar_time`` — NOT routed through ExecutionHandler / SimulatedExchange, which
        fill next-bar-open; liquidation settles on the breach bar. The penalty rides
        ``commission``; ``portfolio.on_fill`` realizes the PnL + penalty and releases the
        lock.

        The realized loss is bounded by SETTLING THE FORCED CLOSE AT THE ISOLATED
        MAINTENANCE LIQ PRICE: the position closes AT the floor, never below it, even when
        the breach bar gaps far below it. There is NO explicit ``min(loss + penalty, WB)``
        clamp — fill-at-liq-price IS the loss-bounding mechanism.
        """
        if self._order_storage is None:
            raise StateError(
                portfolio.portfolio_id,
                "order-storage-unwired",
                required_state="order-storage-wired (call set_order_storage)",
                operation="liquidate_position",
            )
        size = abs(position.net_quantity)
        # Opposite side closes the position: SELL closes a long, BUY a short.
        close_side = Side.SELL if position.side == PositionSide.LONG else Side.BUY
        # The penalty math lives on the margin account. Reached only for breached
        # margin positions.
        penalty = SimulatedMarginAccount._liquidation_penalty(fee_rate, size, liq_price)

        # Quantize the liq price to the instrument price scale ONLY here, at the FillEvent
        # money boundary — never mid-formula. A stub Instrument carrying no price scale
        # (unit tests) leaves the full-precision liq price untouched.
        fill_price = liq_price
        instrument = self._universe.instrument(position.ticker)
        price_scale = getattr(instrument, "price_precision", None)
        if price_scale is not None:
            fill_price = quantize(liq_price, instrument, "price")

        # A forced deleverage is never owned by a strategy — mint a fresh
        # StrategyId so the trade log still carries a real fill→order→strategy
        # chain (the LIQUIDATION trigger source distinguishes it from a
        # strategy-driven close).
        order = Order(
            time=bar_time,
            type=OrderType.MARKET,
            status=OrderStatus.PENDING,
            ticker=position.ticker,
            action=close_side,
            price=fill_price,
            quantity=size,
            exchange=portfolio.exchange,
            strategy_id=StrategyId(idgen.generate_strategy_id()),
            portfolio_id=portfolio.portfolio_id,
        )
        # Record the forced-close trigger (admission-bypassing — a forced
        # deleverage is never rejected by a margin check).
        order.add_state_change(
            OrderStatus.PENDING,
            f"Forced liquidation close for {position.ticker}",
            OrderTriggerSource.LIQUIDATION,
            time=bar_time,
            allow_same_status=True,
        )
        # Register in the SHARED mirror so the reconcile reaches FILLED.
        self._order_storage.add_order(order)

        order_event = OrderEvent.new_order_event(order)
        fill_event = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=fill_price, quantity=size, commission=penalty, time=bar_time)
        self.global_queue.put(fill_event)

        # The logged ``liq_price`` is the QUANTIZED FillEvent price — the price the
        # position actually settles at — while ``penalty`` carries FULL precision (computed
        # on the unquantized formula price). Intentional: the log mirrors the emitted
        # FillEvent.
        self.logger.info(
            "Position force-liquidated",
            ticker=position.ticker,
            side=position.side.name,
            liq_price=str(fill_price),
            penalty=str(penalty),
            order_id=order.id,
            portfolio_id=portfolio.portfolio_id,
        )

    def _run_liquidation_pass(self, closes: Dict[str, Decimal],
                              bar_time: Optional[datetime],
                              marked_portfolio_ids: Optional[set[Any]] = None) -> None:
        """BAR-route per-position liquidation breach check.

        Runs AFTER the per-portfolio mark + carry pass so the breach sees carry-eroded
        equity. For each active portfolio, collect the deterministically sorted breached
        positions at this tick's close and force-close each. No Universe / no order_storage
        wired → no-op.

        ``closes`` is the SAME per-ticker close map the caller built for the mark — passed
        in rather than re-derived from bar_events, so the mark price and the breach price
        are guaranteed identical.

        ``marked_portfolio_ids`` gates evaluation to the portfolios that re-marked cleanly
        this tick. Under the CURRENT error policy the skip never fires: a failed mark in
        ``update_portfolios_market_value`` RE-RAISES rather than continuing the loop, and
        the dispatch error seam works at whole-handler-call granularity, so either every
        active portfolio re-marked or this pass is never reached. It is kept as a DEFENSIVE
        guardrail — were a per-portfolio continue-on-mark-failure policy ever adopted for
        live mode, the partial-mark case would become reachable and this gate would already
        stop the breach reading a stale, partially-marked equity. ``None`` means no gating.
        """
        if bar_time is None or self._universe is None or self._order_storage is None:
            return
        for portfolio in self.get_active_portfolios():
            if (marked_portfolio_ids is not None
                    and portfolio.portfolio_id not in marked_portfolio_ids):
                continue
            # The liq math lives on the margin account; a spot account has no
            # margin/liquidation surface, so skip it.
            account = portfolio.account
            if not isinstance(account, SimulatedMarginAccount):
                continue
            for position in self._collect_breaches_over_prices(portfolio, closes, bar_time):
                wb, mmr, fee_rate = account._liq_inputs(position)
                liq_price = account._isolated_liq_price(position, wb, mmr)
                # LOAD-BEARING: the breach is DETECTED on the bar close but the position
                # is SETTLED at ``liq_price`` (the maintenance liq price), NOT at the
                # breaching close. With no ``min(loss + penalty, WB)`` clamp, filling at
                # the maintenance floor is THE mechanism bounding the realized loss near
                # WB even on a gap-through. "Fixing" this to settle at the realistic
                # breach close silently removes that bound — see the gap-through
                # regression test_liquidation_fills_at_liq_price_on_far_gap_through.
                self._liquidate_position(portfolio, position, liq_price, fee_rate, bar_time)

    def _collect_breaches_over_prices(self, portfolio: Portfolio,
                                      closes: Dict[str, Decimal],
                                      bar_time: datetime) -> List[Position]:
        """Collect breached open positions across a per-ticker close map.

        The SINGLE breach predicate: the live path and the unit tests both call this
        directly, so there is no second collector to drift apart. Each position is
        evaluated against ITS OWN ticker's close — a position whose ticker is absent from
        this tick is skipped (stale mark, never a spurious breach). Returns the breached
        set sorted ``(ticker, open_time, position_id)``. The unwired-Universe guard fires
        only when there is a position to evaluate.
        """
        positions = portfolio.position_manager.get_all_positions()
        if not positions:
            return []
        # A spot (SimulatedCashAccount) account has no margin/liquidation surface — it is
        # never breached. The margin math is delegated to the account.
        account = portfolio.account
        if not isinstance(account, SimulatedMarginAccount):
            return []
        if self._universe is None:
            raise StateError(
                portfolio.portfolio_id,
                "universe-unwired",
                required_state="universe-wired (call set_universe)",
                operation="liquidation_breach_check",
            )
        breached: List[Position] = []
        for ticker, position in positions.items():
            if not position.is_open:
                continue
            close = closes.get(ticker)
            if close is None or close <= Decimal("0"):
                continue
            wb, mmr, _fee_rate = account._liq_inputs(position)
            if wb <= Decimal("0"):
                continue
            liq_price = account._isolated_liq_price(position, wb, mmr)
            if account._is_breached(position, close, liq_price):
                breached.append(position)
        breached.sort(key=lambda p: (p.ticker, p.entry_date, str(p.id)))
        return breached

    # ------------------------------------------------------------------
    # Engine-thread drift compare + halt decision. The venue is the arbiter of truth in
    # live: the async push writer only WRITES the VenueAccount cache (single-writer); the
    # per-symbol COMPARE + halt DECISION run HERE, on the engine thread, after a fill
    # drains (on_fill) and once per closed bar (BAR-route backstop). That placement
    # structurally defeats the phantom-drift race — the engine tally is fully applied
    # before the compare reads it, and no compare is reachable from a spawned coroutine.
    # A backtest/paper portfolio holds a SimulatedAccount, so the compare skips cleanly.
    # ------------------------------------------------------------------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the composition-root freeze-in-place halt entrypoint.

        The live root wires ``LiveTradingSystem.halt`` here; the engine-thread drift
        compare calls it with a machine-readable reason (``"drift"``) on unexplained
        beyond-band drift. Backtest never wires it — no VenueAccount, so no compare.
        """
        self._halt_signal = halt_signal

    def set_drift_reconciler(
        self, reconciler: Callable[[Any, str, Decimal, Decimal], bool]
    ) -> None:
        """Inject the external-event reconciler for beyond-band drift.

        Answers whether a beyond-band per-symbol drift reconciles to a KNOWN venue event
        (an external cancel / external or hand-closed fill) — adopt-and-continue — versus
        genuinely unexplained drift that halts the engine. ``None`` treats every
        beyond-band drift as unexplained: the conservative money-first default.
        """
        self._drift_reconciler = reconciler

    def _drift_precision(self, ticker: str) -> int:
        """Resolve the instrument quantity precision for the drift epsilon.

        Keys the ``is_within_single_unit_tolerance`` band off the SAME instrument
        precision ``core/money.py::quantize`` consumes, resolved via the injected
        Universe — never a hand-rolled per-symbol table. Falls back to ``8`` (the
        money-policy quantity default) when no Universe is wired or the instrument carries
        no precision.
        """
        default = 8
        if self._universe is None:
            return default
        try:
            instrument = self._universe.instrument(ticker)
        except (KeyError, AttributeError):
            return default
        precision = getattr(instrument, "quantity_precision", None)
        if precision is None:
            return default
        return int(precision)

    def _compare_symbol_drift(self, portfolio: Portfolio, ticker: str,
                              correlation_id: CorrelationId,
                              just_applied_fill_qty: Optional[Decimal] = None) -> None:
        """Per-symbol engine-vs-venue drift compare on the ENGINE thread.

        Runs ONLY for a live ``VenueAccount`` portfolio — a backtest/paper
        ``SimulatedAccount`` portfolio has no venue truth, so this is a clean skip.
        Compares the engine's fill-applied position quantity for ``ticker`` against the
        ``VenueAccount`` cached venue truth via ``is_within_single_unit_tolerance`` keyed
        to the instrument precision:

        * within the precision-epsilon band → adopt venue truth silently (the difference
          is last-digit dust);
        * spurious-halt band: on the IMMEDIATE on-fill compare the just-applied fill may
          not yet be reflected in the venue snapshot — the only skew the fill itself
          explains is exactly its own signed quantity, so absorb that transient and defer
          to the periodic sweep (a first spot position-opening fill must NOT halt);
        * beyond band AND reconciles to a known venue event → adopt-and-continue (an
          external fill / hand-closed position is NOT unexplained drift);
        * beyond band AND unexplained → freeze-in-place halt the WHOLE engine.

        Parameters
        ----------
        just_applied_fill_qty : Optional[Decimal]
            The SIGNED position delta of a fill JUST applied to the engine belief for
            ``ticker`` (``+qty`` BUY, ``-qty`` SELL), passed ONLY by the on-fill compare.
            ``None`` (the per-bar sweep) means no just-applied fill — every beyond-band
            skew is a candidate drift. The band is deliberately scoped to the on-fill
            transient so the periodic sweep still halts once the venue snapshot has had
            time to catch up, and a genuinely persistent divergence is never hidden.

        Single-writer safe: the async push writer only writes the VenueAccount cache; this
        compare and decision run on the engine thread AFTER the fill has drained, never
        from a spawned coroutine.
        """
        account: Account = portfolio.account
        if not isinstance(account, VenueAccount):
            return  # backtest/paper — no venue truth, nothing to reconcile.

        venue_qty = account.positions.get(ticker, Decimal("0"))
        engine_position = portfolio.get_open_position(ticker)
        engine_qty = (
            engine_position.net_quantity if engine_position is not None
            else Decimal("0")
        )
        precision = self._drift_precision(ticker)
        if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
            return  # within the precision-epsilon band — adopt silently.

        # Spurious-halt band: a just-applied engine fill vs a not-yet-refreshed venue
        # snapshot. The snapshot legitimately lags the fill it hasn't streamed yet, and the
        # ONLY holding that lag explains is the pre-fill one
        # (``engine_qty - just_applied_fill_qty``). When venue truth still matches that
        # within the band, the skew IS the un-streamed fill, not drift — absorb it and let
        # the periodic per-bar sweep be the backstop once the snapshot refreshes. Only the
        # on-fill compare supplies a fill qty.
        if just_applied_fill_qty is not None and is_within_single_unit_tolerance(
                venue_qty, engine_qty - just_applied_fill_qty, precision):
            self.logger.info(
                "Just-applied fill not yet reflected in venue snapshot — deferring "
                "drift decision to the periodic sweep (spurious-halt band, D-04)",
                ticker=ticker,
                engine_qty=str(engine_qty),
                venue_qty=str(venue_qty),
                fill_qty=str(just_applied_fill_qty),
                correlation_id=correlation_id,
            )
            return

        # Beyond band: adopt-and-continue if it maps to a known venue event.
        if self._drift_reconciler is not None and self._drift_reconciler(
                portfolio, ticker, engine_qty, venue_qty):
            self.logger.warning(
                "Adopted external venue event (beyond-band drift reconciled)",
                ticker=ticker,
                engine_qty=str(engine_qty),
                venue_qty=str(venue_qty),
                correlation_id=correlation_id,
            )
            return

        # Unexplained beyond-band drift → freeze-in-place halt the whole engine. The
        # compare declared the engine's own state untrustworthy. The halt does NOT
        # auto-flatten or auto-cancel — it stops NEW submissions and surfaces HALTED plus a
        # CRITICAL alert (wired by the composition root).
        self.logger.error(
            "Unexplained per-symbol drift beyond tolerance — halting engine",
            ticker=ticker,
            engine_qty=str(engine_qty),
            venue_qty=str(venue_qty),
            correlation_id=correlation_id,
        )
        if self._halt_signal is not None:
            self._halt_signal("drift")

    def _run_drift_sweep(self, bar_time: Optional[datetime]) -> None:
        """Periodic per-closed-bar drift backstop on the ENGINE thread.

        The on-bar complement to the immediate on-fill compare: sweeps every active
        ``VenueAccount`` portfolio and compares each symbol's engine tally against venue
        truth across the union of engine-held and venue-reported tickers. A backtest/paper
        portfolio holds a ``SimulatedAccount`` and is skipped.
        """
        if bar_time is None:
            return
        for portfolio in self.get_active_portfolios():
            account: Account = portfolio.account
            if not isinstance(account, VenueAccount):
                continue
            engine_tickers = set(portfolio.positions.keys())
            venue_tickers = set(account.positions.keys())
            for ticker in sorted(engine_tickers | venue_tickers):
                self._compare_symbol_drift(
                    portfolio, ticker, self._generate_correlation_id())

    def _mark_venue_trade_settled(self, venue_trade_id: str) -> None:
        """Record a venue trade id as settled in the bounded FIFO dedup ledger.

        Evicts the oldest id once the ledger exceeds its cap so a long-running live session
        cannot grow it without bound. Re-inserting an already-present id refreshes its
        recency.
        """
        self._settled_venue_trade_ids[venue_trade_id] = None
        self._settled_venue_trade_ids.move_to_end(venue_trade_id)
        while len(self._settled_venue_trade_ids) > self._max_settled_venue_trade_ids:
            self._settled_venue_trade_ids.popitem(last=False)

    def _persist_account_state(self, portfolio: Portfolio, updated_time: datetime) -> None:
        """Write-through the durable account-state scalar after a settled fill.

        The restart path reads the cash scalar back via ``load_account_state`` ->
        ``Account.restore_cash``; that read is only meaningful if ``save_account_state`` is
        actually written on the settlement path, so a process restart restores the true
        balance rather than the construction-time initial cash.

        LIVE ONLY: the in-memory backtest backend exposes no ``save_account_state`` (only
        ``CachedSqlPortfolioStateStorage`` does), so this is a clean ``getattr`` skip.
        ``updated_time`` is the fill's BUSINESS time, never wall-clock — determinism.
        ``peak_equity`` tracks the high-water equity across restarts.
        """
        storage = portfolio.state_storage
        save_account_state = getattr(storage, "save_account_state", None)
        if save_account_state is None:
            return  # in-memory backtest backend — nothing durable to persist.

        total_equity = portfolio.total_equity
        # Carry the high-water peak forward across restarts (the drawdown basis).
        load_account_state = getattr(storage, "load_account_state", None)
        prior_peak = Decimal("0")
        if load_account_state is not None:
            prior_state = load_account_state()
            if prior_state is not None:
                prior_peak = prior_state["peak_equity"]
        peak_equity = max(prior_peak, total_equity)

        save_account_state(
            cash_balance=portfolio.account.balance,
            realized_pnl=portfolio.total_realised_pnl,
            total_equity=total_equity,
            peak_equity=peak_equity,
            open_positions_count=portfolio.n_open_positions,
            updated_time=updated_time,
        )

    def rehydrate(
        self,
        applied_trade_sink: Optional[Callable[[Iterable[str]], None]] = None,
    ) -> None:
        """Restore live portfolio state + the durable dedup ledger on restart.

        The cross-restart arm the in-session guard does NOT cover: on a live restart
        ``_settled_venue_trade_ids`` starts EMPTY, so a venue trade re-delivered after the
        restart (an OKX stream re-send, or the ``VenueReconciler`` adopting a downtime
        fill) would be booked a SECOND time. Per active portfolio this seam:

        1. **Drives ``state_storage.rehydrate(account)``** — open positions surface through
           the live ``PositionManager`` read cache and the persisted cash scalar is
           restored into the ``Account``. The in-memory backtest backend exposes no
           ``rehydrate`` and is skipped.
        2. **Seeds the settled-trade dedup ledger** from the durable
           ``transactions.venue_trade_id``, keyed ``f"{ticker}:{venue_trade_id}"``
           (collision-safe — the same numeric trade id on a DIFFERENT symbol still
           settles). A re-delivered pair is then a no-op at the ``on_fill`` guard.
        3. **Restart-seeds the ORDER-mirror dedup ring symmetrically** when an
           ``applied_trade_sink`` is supplied. ``ReconcileManager._applied_trade_keys``
           also starts EMPTY on a restart, so the SAME keys are forwarded once — a single
           history pass, since ReconcileManager has no durable transaction store of its
           own. The composition root wires the sink; backtest passes ``None``.

        Sequencing: this MUST run BEFORE ``VenueReconciler.reconcile()`` so adoption diffs
        against restored state and the dedup ledger already knows every settled venue trade.

        Args:
            applied_trade_sink: Optional seed hook (``OrderManager.seed_applied_trades``)
                driven with the durable ``f"{ticker}:{venue_trade_id}"`` history. ``None``
                keeps the portfolio-arm-only behaviour.
        """
        seeded_keys: List[str] = []
        for portfolio in self.get_active_portfolios():
            storage = portfolio.state_storage
            rehydrate_fn = getattr(storage, "rehydrate", None)
            if rehydrate_fn is None:
                # Backtest in-memory backend — nothing durable to restore (oracle-dark).
                continue
            # (a) Positions into the live managers' read cache + the persisted cash
            # scalar into the account.
            rehydrate_fn(portfolio.account)
            # (a2) Re-seed the realised-PnL accumulator from the durable account-state
            # scalar. The accumulator is not one of the containers the working-set cache
            # carries, so without this a post-restart fill would overwrite the durable
            # realized_pnl column with a 0-based value.
            load_account_state = getattr(storage, "load_account_state", None)
            if load_account_state is not None:
                account_state = load_account_state()
                if account_state is not None:
                    portfolio.position_manager.restore_realised_pnl(
                        account_state["realized_pnl"]
                    )
            # (b) Durable backstop: seed the dedup ledger from the transaction history,
            # keyed f"{ticker}:{venue_trade_id}". Backtest/simulated transactions carry no
            # venue key and are skipped.
            for transaction in storage.get_transaction_history():
                venue_trade_id = getattr(transaction, "venue_trade_id", None)
                if venue_trade_id is None:
                    continue
                dedup_key = f"{transaction.ticker}:{venue_trade_id}"
                self._mark_venue_trade_settled(dedup_key)
                # Collect the SAME key for the order-mirror ring seed so both dedup arms
                # read from ONE history pass (no second divergent read).
                seeded_keys.append(dedup_key)
        # Restart-seed the order-mirror dedup ring symmetrically with the portfolio
        # ledger — one history pass feeds both arms. Skipped when no sink is wired.
        if applied_trade_sink is not None and seeded_keys:
            applied_trade_sink(seeded_keys)

    # Fill event processing
    def on_fill(self, fill_event: FillEvent) -> None:
        """Process fill event for the appropriate portfolio.

        Returns ``None``; failures raise typed domain exceptions which propagate to the
        dispatch registry's ``_on_handler_error`` seam (backtest re-raise — the run stops
        loudly rather than producing corrupted numbers).
        """

        # A non-EXECUTED fill is a pure no-op on portfolio state, so it returns before
        # _operation_context — no correlation id is allocated for it.
        if fill_event.status != FillStatus.EXECUTED:
            self.logger.debug(
                "Ignoring non-executed fill",
                status=str(fill_event.status),
                ticker=fill_event.ticker,
            )
            return

        # Cross-emitter fill-dedup at the settlement chokepoint. The venue trade id is the
        # ONE idempotency key shared by the two live emitters (the OKX trade stream and the
        # restart VenueReconciler); a fill whose venue_trade_id was already settled is a
        # duplicate booking of the SAME economic venue trade — reject it BEFORE it mutates
        # position/cash, so 0.5 BTC is never booked as 1.0.
        #
        # Key by f"{ticker}:{venue_trade_id}", NOT the raw id: the numeric venue tradeId is
        # only unique per instrument, so the SAME id on a different symbol is a DISTINCT
        # economic trade and must still settle. Backtest/simulated fills carry
        # venue_trade_id=None and skip the guard entirely.
        venue_trade_id = getattr(fill_event, "venue_trade_id", None)
        dedup_key = (
            f"{fill_event.ticker}:{venue_trade_id}"
            if venue_trade_id is not None
            else None
        )
        if dedup_key is not None and dedup_key in self._settled_venue_trade_ids:
            self.logger.warning(
                "Rejecting duplicate venue trade fill (already settled)",
                venue_trade_id=venue_trade_id,
                ticker=fill_event.ticker,
            )
            return

        with self._operation_context("on_fill") as correlation_id:
            try:
                portfolio_id = fill_event.portfolio_id
                portfolio = self.get_portfolio(portfolio_id)

                # Events carry Side; Portfolio maps Side -> TransactionType at its own
                # boundary, keeping the two vocabularies distinct. FillEvent money is
                # already Decimal, so to_money is an identity normalization here — kept
                # deliberately: the ledger never trusts an unnormalized input.
                transaction_type = TransactionType.BUY if fill_event.action is Side.BUY else TransactionType.SELL
                transaction = Transaction(
                    time=fill_event.time,
                    type=transaction_type,
                    ticker=fill_event.ticker,
                    price=to_money(fill_event.price),
                    quantity=to_money(fill_event.quantity),
                    commission=to_money(fill_event.commission),
                    portfolio_id=portfolio_id,
                    id=TransactionId(idgen.generate_transaction_id()),
                    # Audit chain: the settlement record carries the originating fill's
                    # identity (fill -> order -> strategy).
                    fill_id=fill_event.fill_id,
                    # The admission-clamped EFFECTIVE leverage, so the opening Transaction
                    # sets Position.leverage to the effective value and the position-life
                    # locked margin (aggregate_notional / leverage) EQUALS the admission
                    # reservation (notional / effective_leverage).
                    leverage=getattr(fill_event, "leverage", Decimal("1")),
                    venue_trade_id=venue_trade_id,
                    # The venue fee currency, so the spot settlement seam nets a
                    # base-denominated fee (OKX spot BUY) out of the position quantity
                    # instead of the quote cash leg. None for backtest/simulated fills.
                    fee_currency=getattr(fill_event, "fee_currency", None),
                )

                # Wrap the durable position upsert (transact_shares -> set_position) and
                # the cash-scalar account-state upsert (_persist_account_state ->
                # save_account_state) in ONE transaction, so a crash between them can never
                # leave the durable position one fill ahead of the durable cash — a torn
                # restore, which is PERMANENT on the SimulatedAccount path since no venue
                # heals it. The in-memory backtest backend exposes no fill_transaction, so
                # this is a clean getattr-skip. LIVE ONLY.
                fill_transaction = getattr(
                    portfolio.state_storage, "fill_transaction", None)
                if fill_transaction is not None:
                    with fill_transaction():
                        portfolio.transact_shares(transaction)
                        # Write-through the account-state scalar so the restart restore
                        # has a persisted balance to read — atomic with the position.
                        self._persist_account_state(portfolio, fill_event.time)
                else:
                    portfolio.transact_shares(transaction)
                    self._persist_account_state(portfolio, fill_event.time)

                # Record the venue trade id as settled ONLY after the durable persist
                # committed, so a later re-delivery is a no-op at the guard above and a
                # rolled-back persist never records a key for a fill that did not land.
                # Same f"{ticker}:{venue_trade_id}" key the guard reads, so the
                # durable-ledger seed and the live mark share one key space.
                if dedup_key is not None:
                    self._mark_venue_trade_settled(dedup_key)

                self.logger.debug(
                    "Fill event processed",
                    portfolio_id=portfolio_id,
                    ticker=fill_event.ticker,
                    correlation_id=correlation_id
                )

                # Engine-thread per-symbol drift compare + halt decision, immediately
                # after the fill has drained (single-writer safe). No-op for
                # backtest/paper SimulatedAccount portfolios.
                #
                # The signed delta passed here MUST be the ACTUAL position delta the
                # settlement applied — NET of a base-denominated fee. Settlement moves a
                # base-fee BUY by (amount - base_fee), so passing the RAW
                # fill_event.quantity leaves the spurious-halt band's pre-fill
                # reconstruction (engine_qty - just_applied_fill_qty) off by the fee and
                # trips halt('drift') while the venue cache is still pre-fill.
                # transaction.position_quantity is (amount - base_fee) for a base BUY and
                # the raw amount otherwise.
                settled_base_delta = transaction.position_quantity
                just_applied_fill_qty = (
                    settled_base_delta if fill_event.action is Side.BUY
                    else -settled_base_delta
                )
                self._compare_symbol_drift(
                    portfolio, fill_event.ticker, correlation_id,
                    just_applied_fill_qty=just_applied_fill_qty)

            except Exception as e:
                error_portfolio_id = getattr(fill_event, "portfolio_id", None)
                self._publish_error_event(e, "on_fill", correlation_id, error_portfolio_id)
                raise
    
    # Market data updates
    def update_portfolios_market_value(self, bar_events: Union[BarEvent, List[BarEvent]]) -> None:
        """Update market values for all active portfolios."""
        
        # Normalize input to always be a list
        if isinstance(bar_events, BarEvent):
            bar_events = [bar_events]
        
        # The close is already Decimal via the Bar struct; downstream position updates
        # enter via to_money (value-identity on Decimal input).
        prices = {}
        # Thread the bar's BUSINESS time down into the per-portfolio mark + carry accrual
        # — NEVER datetime.now(UTC), which breaks the determinism double-run gate. One
        # BarEvent per tick on the daily grid; the last event's time stamps this mark.
        bar_time = None
        for bar_event in bar_events:
            bar_time = bar_event.time
            for ticker, bar in bar_event.bars.items():
                prices[ticker] = bar.close

        # Update only active portfolios (each handles its own thread safety)
        active_portfolios = self.get_active_portfolios()

        # Which portfolios re-marked cleanly THIS tick, passed to the liquidation gate.
        # Under the current error policy this is always the FULL active set: the except
        # below RE-RAISES rather than continuing the loop, and the dispatch error seam
        # works at handler-call granularity, so the pass either sees every portfolio
        # re-marked or never runs. Kept as a DEFENSIVE guardrail — were the re-raise ever
        # softened to a per-portfolio continue, the partial-mark case would become
        # reachable and this set would already protect the "breach sees carry-eroded
        # equity" invariant.
        marked_portfolio_ids: set[Any] = set()

        for portfolio in active_portfolios:
            try:
                # Thread bar business time + the injected Universe so each open short can
                # resolve its Instrument.borrow_rate. With no universe / rate-0 / no open
                # shorts the carry accrual is a no-op.
                portfolio.update_market_value_of_portfolio(prices, bar_time, self._universe)
                marked_portfolio_ids.add(portfolio.portfolio_id)
            except Exception as e:
                # A failed mark must NOT be swallowed: silently continuing leaves the
                # equity curve carrying stale position values that the
                # metrics/drawdown/oracle blocks then consume as if valid. Mirror
                # on_fill's fail-fast contract — publish a PortfolioErrorEvent to the
                # ERROR route, then re-raise so the backtest policy aborts the run
                # instead of producing silently-wrong numbers.
                correlation_id = self._generate_correlation_id()
                self._publish_error_event(
                    e, "update_portfolios_market_value", correlation_id,
                    portfolio.portfolio_id)
                raise

        # The per-position liquidation breach check runs AFTER the per-portfolio mark +
        # carry pass so a breach sees carry-eroded equity. Reuses the SAME ``prices`` map
        # the mark used, so the breach price and the mark price cannot diverge.
        self._run_liquidation_pass(prices, bar_time, marked_portfolio_ids)

        # Per-closed-bar drift backstop on the engine thread — the on-bar complement to
        # the on-fill compare. SimulatedAccount portfolios are skipped.
        self._run_drift_sweep(bar_time)

    # Global health and monitoring
    def get_global_health_report(self) -> Dict[str, Any]:
        """Generate global health report."""
        portfolios = list(self._portfolios.values())

        healthy_count = 0
        unhealthy_portfolios = []
        state_counts = {state: 0 for state in PortfolioState}
        
        for portfolio in portfolios:
            health = portfolio.validate_health()
            if health['is_healthy']:
                healthy_count += 1
            else:
                unhealthy_portfolios.append({
                    'portfolio_id': portfolio.portfolio_id,
                    'issues': health['issues']
                })
            
            state_counts[portfolio.state] += 1
        
        return {
            'timestamp': datetime.now(UTC).isoformat(),
            'total_portfolios': len(portfolios),
            'healthy_portfolios': healthy_count,
            'unhealthy_portfolios': len(unhealthy_portfolios),
            'unhealthy_details': unhealthy_portfolios,
            'portfolios_by_state': {state.value: count for state, count in state_counts.items()},
            'global_limits': {
                'max_portfolios': self.max_portfolios
            }
        }
    
    # Export and serialization
    def portfolios_to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Convert all portfolios to dictionary format."""
        return {
            str(portfolio_id): portfolio.to_dict()
            for portfolio_id, portfolio in self._portfolios.items()
        }
    
    def generate_portfolios_update_event(self) -> PortfolioUpdateEvent:
        """Generate portfolio update event."""
        return PortfolioUpdateEvent(
            time=datetime.now(UTC),
            portfolios=self.portfolios_to_dict()
        )
    
    # Configuration management. The handler holds a single validated Pydantic
    # ``PortfolioConfig``; ``update_config`` merges and re-validates through the model.
    @staticmethod
    def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Thin delegate to the shared ``recursive_merge`` helper.

        The recursion lives in ``itrader/outils/dict_merge.py`` — do NOT re-derive a fresh
        merge per handler.
        """
        return recursive_merge(base, updates)

    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update PortfolioHandler configuration at runtime.

        recursive_merge -> model_validate -> atomic swap, wrapping pydantic
        ``ValidationError`` (which also rejects unknown keys via ``extra="forbid"``) into
        ``ConfigurationError``. Returns ``None`` and RAISES on failure. The cached
        ``max_portfolios`` is re-derived after the swap.
        """
        # Recursive-merge so a partial nested update (e.g. a single limits field)
        # preserves the other fields of that submodel instead of replacing the whole
        # submodel via a shallow `{**a, **b}`.
        merged = recursive_merge(self.config_data.model_dump(), updates)
        try:
            new_config = PortfolioConfig.model_validate(merged)
        except pydantic.ValidationError as e:
            raise ConfigurationError(reason=str(e)) from e
        self.config_data = new_config  # atomic GIL-safe reference swap
        self.max_portfolios = self.config_data.limits.max_portfolios
        self.logger.info("Configuration updated successfully", updates=updates)

    def get_config(self) -> Dict[str, Any]:
        """Get current PortfolioHandler configuration as a dict."""
        return self.config_data.model_dump(mode="json")

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate a candidate PortfolioHandler configuration via the Pydantic model."""
        try:
            PortfolioConfig.model_validate(config)
            return True
        except Exception as e:
            self.logger.error("Configuration validation failed", error=str(e))
            return False

    def rollback_config(self) -> bool:
        """Reset PortfolioHandler configuration to the default preset."""
        try:
            self.config_data = get_portfolio_preset('default')
            self.max_portfolios = self.config_data.limits.max_portfolios
            self.logger.info("Configuration rolled back to defaults")
            return True
        except Exception as e:
            self.logger.error("Failed to rollback configuration", error=str(e))
            return False

    def update_portfolio_config(self, portfolio_id: PortfolioId, updates: Dict[str, Any]) -> bool:
        """Update configuration for a specific portfolio (not wired).

        Deferred with the live runtime-config surface.
        """
        self.logger.warning(
            "update_portfolio_config is not wired (deferred to D-live)",
            portfolio_id=portfolio_id,
        )
        return False

    def get_portfolio_config(self, portfolio_id: PortfolioId) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific portfolio (not wired)."""
        self.logger.warning(
            "get_portfolio_config is not wired (deferred to D-live)",
            portfolio_id=portfolio_id,
        )
        return None
    
    def __str__(self) -> str:
        return f"PortfolioHandler(portfolios={self.get_portfolio_count()})"
    
    def __repr__(self) -> str:
        return str(self)
