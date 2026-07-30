"""Portfolio lifecycle, fill settlement and global configuration for the portfolio domain."""
from collections import OrderedDict
from datetime import datetime, UTC
from decimal import Decimal
from typing import Dict, Iterable, Optional, Any, List, Generator, Union, Callable
from contextlib import contextmanager

from .portfolio import Portfolio
from .position import Position
from .account import Account, SimulatedMarginAccount
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

    Single-writer contract: ALL portfolio state mutations happen on the engine thread and
    the queue is the thread boundary — other threads only put events. Composite reads are
    consistent because nothing mutates concurrently, which is why neither the portfolio
    collection nor an individual ``Portfolio`` carries a lock.
    """
    
    def __init__(self, global_queue: "EventBus", environment: str = "backtest",
                 sql_engine: "Optional[Any]" = None,
                 *,
                 portfolio_factory: "Optional[Any]" = None) -> None:
        self.global_queue: "EventBus" = global_queue
        self.current_time: Any = 0

        # "backtest" is the in-memory path; "live" plus the shared SqlEngine persists every
        # portfolio to the SQL ledger and rehydrates its truth on restart. ``sql_engine``
        # is typed Any to keep the SqlEngine import off this module.
        self._environment = environment
        self._sql_engine = sql_engine

        # The SOLE leaf-builder: every portfolio's runtime graph is routed through it, so
        # account-kind selection and venue-truth authority live in ONE place. ``None`` is
        # the direct-construction arm — callers that never build a portfolio.
        self._factory = portfolio_factory

        # Constructed here rather than at the composition root so POST-BOOT
        # ``add_portfolio`` calls persist too: live portfolios are added after
        # ``build_live_system`` returns, and a boot-only writer would persist none of them.
        # The import stays LAZY inside the gate — this module is on the BACKTEST import
        # graph and the store pulls SQLAlchemy, so a module-top import breaks inertness.
        self.definition_store: Optional[Any] = None
        if environment == "live" and sql_engine is not None:
            from itrader.storage.portfolio_definition_store import (
                PortfolioDefinitionStore,
            )
            self.definition_store = PortfolioDefinitionStore(sql_engine)

        self.config_data: PortfolioConfig = PortfolioConfig.default()

        # limits.max_portfolios, NOT limits.max_positions (the per-portfolio limit).
        self.max_portfolios = self.config_data.limits.max_portfolios
        self.publish_error_events = True

        # Keyed by PortfolioId (UUID) at runtime while events still carry an int
        # portfolio_id; typed Any to bridge both forms until that migration completes.
        self._portfolios: Dict[Any, Portfolio] = {}

        # The injected Universe read-model resolving each open position's Instrument on
        # demand. None until ``set_universe``, which runs after this handler is built.
        self._universe: Any = None

        # The write-seam the liquidation engine registers its forced-close Order through.
        # Composition injects the SAME instance the OrderHandler/ReconcileManager hold.
        self._order_storage: Optional[OrderStorage] = None

        # Engine-thread drift-halt seam: unexplained beyond-band per-symbol drift freezes
        # the WHOLE engine. None on backtest, where no portfolio has venue truth behind it
        # and so nothing is compared.
        self._halt_signal: Optional[Callable[[str], None]] = None
        # Answers "is there venue truth for this portfolio, and what is it?". None → no
        # venue anywhere, the backtest/paper default, and every drift compare skips.
        self._snapshot_source: Optional[
            Callable[[Portfolio], Optional[Any]]
        ] = None
        # Answers whether a beyond-band drift maps to a KNOWN venue event and is therefore
        # adopt-and-continue rather than a halt. ``None`` → the conservative money-first
        # default: any beyond-band drift is unexplained and halts.
        self._drift_reconciler: Optional[
            Callable[[Any, str, Decimal, Decimal], bool]
        ] = None

        # Bounded-FIFO ledger of already-settled venue trade ids — the cross-emitter
        # fill-dedup guard read in ``on_fill``. The live stream and the restart
        # VenueReconciler can both book the SAME economic venue trade and share no other
        # idempotency key, since fill_id is a fresh uuid7 per emit.
        self._settled_venue_trade_ids: "OrderedDict[str, None]" = OrderedDict()
        self._max_settled_venue_trade_ids = 100_000

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
        # datetime.now(UTC) here cannot perturb determinism.
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

        Holds no concurrency-limiting machinery — the single-writer contract makes it
        unnecessary.
        """
        correlation_id = self._generate_correlation_id()
        yield correlation_id
    
    def add_portfolio(self, name: str, exchange: str, cash: "float | Decimal",
                      portfolio_config: Optional[PortfolioConfig] = None,
                      portfolio_id: Optional[PortfolioId] = None,
                      account_id: Optional[str] = None,
                      venue_name: Optional[str] = None) -> PortfolioId:
        """Create a portfolio: write its definition row, then build its runtime graph.

        Parameters
        ----------
        portfolio_id : Optional[PortfolioId]
            An EXISTING id to reattach to on rehydrate. Supplying an id already registered
            RAISES rather than overwriting — a silent overwrite would destroy the first
            portfolio's cash and positions.
        account_id : Optional[str]
            The venue account this portfolio's orders reach.
        venue_name : Optional[str]
            The source of truth for the portfolio's exchange; when supplied it wins and
            ``exchange`` is derived from it.

        Returns the resolved ``portfolio_id``.
        """

        with self._operation_context("add_portfolio") as correlation_id:
            try:
                # Global validations (creation-input; rehydrate trusts the store's rows).
                if cash <= 0:
                    raise PortfolioValidationError(0, "initial_cash", "Initial cash must be positive")

                if not name.strip():
                    raise PortfolioValidationError(0, "name", "Portfolio name cannot be empty")

                # Resolve the id HERE so the definition row and the runtime graph carry
                # the SAME one.
                resolved_id = (
                    portfolio_id if portfolio_id is not None
                    else PortfolioId(idgen.generate_portfolio_id())
                )
                # ``materialize`` runs FIRST (WR-03). It is what VALIDATES the named venue
                # account, and the durable row carries a composite foreign key onto
                # ``venue_accounts`` — so inserting first means an unprovisioned account is
                # refused by the DATABASE with an ``IntegrityError`` before the domain ever
                # gets to raise its own ``VenueAccountNotProvisionedError``, which is the
                # error that names the account and tells the operator how to provision it.
                portfolio = self.materialize(
                    name=name,
                    exchange=exchange,
                    cash=cash,
                    config=portfolio_config,
                    portfolio_id=resolved_id,
                    account_id=account_id,
                    venue_name=venue_name,
                )
                # A live Portfolio whose definition row did NOT persist is worse than no
                # portfolio at all: it trades this session and vanishes at the next boot
                # while its positions and cash rows orphan. So a failed insert UNREGISTERS
                # the portfolio it belongs to, and the refusal stays total.
                try:
                    self.create(
                        resolved_id,
                        name=name,
                        cash=cash,
                        account_id=account_id,
                        venue_name=venue_name,
                    )
                except Exception:
                    self._portfolios.pop(portfolio.portfolio_id, None)
                    raise

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
        ``(venue_name, account_id)`` / ``initial_cash``): what ``rehydrate_portfolios``
        reads at the next boot, and what reattaches the child tables across a restart. It
        builds no Portfolio and registers nothing — that is ``materialize``'s job, and it
        runs ONCE per ``portfolio_id``, so the INSERT needs no absence gate.

        There is deliberately NO early return for a portfolio naming no
        ``(venue_name, account_id)``: skipping the row would disagree with
        ``SqlPortfolioStateStorage.save_config``, which RAISES ``PortfolioStateError`` on
        a zero rowcount — the very row it expects this path to have made. Without the skip
        this either writes the row or fails LOUD on the composite FK onto
        ``venue_accounts``, so the two halves cannot drift.

        A write failure PROPAGATES: a definition that did not persist would boot into
        nothing on the next restart while its positions and cash rows orphan — a silent
        money loss, worse than failing loud. The no-store guard stays; on the
        backtest/in-memory arm there is nothing to write.
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
            # config is owned by save_config/load_config on this row — never written here.
            config=None,
            at=datetime.now(UTC),
        )

    def materialize(self, name: str, exchange: str, cash: "float | Decimal",
                    config: Optional[PortfolioConfig] = None,
                    portfolio_id: Optional[PortfolioId] = None,
                    account_id: Optional[str] = None,
                    venue_name: Optional[str] = None) -> Portfolio:
        """Build the runtime Portfolio through the factory and register it — the BUILD half.

        Writes NOTHING durable; the definition row is ``create``'s job. Both
        ``add_portfolio`` and ``rehydrate_portfolios`` call this, so the duplicate-id
        guard and the max-portfolios limit live HERE, where registration happens, and both
        callers inherit them.

        Raises
        ------
        PortfolioConfigurationError
            No factory wired, or the max-portfolios limit is reached.
        PortfolioValidationError
            ``portfolio_id`` is already registered.
        VenueAccountNotProvisionedError
            Live only: the named venue account is missing or disabled. The live
            ``AccountFactory``'s injected validator refuses rather than let the portfolio
            sit on a fabricated balance; a backtest one holds no validator and never
            raises.
        """
        # Refuse LOUDLY: the tempting inline ``SimulatedCashAccount(...)`` fallback would
        # reinstate a second account-kind selection, on a path nothing covers.
        if self._factory is None:
            raise PortfolioConfigurationError(
                "portfolio_factory", None,
                "PortfolioHandler was constructed without a PortfolioFactory, so it cannot "
                "build this portfolio's account leaf (D-24). Refusing to mint an account "
                "inline — that would put account-kind selection back in a second place.",
            )

        # The registry write below is an unconditional dict assignment, so without this a
        # re-materialize SILENTLY destroys the first portfolio, its cash and its positions.
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

        # ``self._factory`` is typed ``Any``, so pin the result to keep
        # ``portfolio.portfolio_id`` a real ``PortfolioId``.
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
        """Whether a portfolio with this id is REGISTERED — so callers never reach into
        ``_portfolios`` themselves."""
        return portfolio_id in self._portfolios

    def all_portfolios(self) -> Dict[PortfolioId, Portfolio]:
        """Every REGISTERED portfolio regardless of state, keyed by ``portfolio_id``.

        ``get_active_portfolios()`` answers a DIFFERENT question (ACTIVE only).

        Returns
        -------
        A SHALLOW COPY in insertion order, never the live private dict — an accessor that
        lets a caller mutate the registry is the reach-in with extra steps. Empty registry
        yields an empty mapping, never ``None``.
        """
        return dict(self._portfolios)

    def delete_portfolio(self, portfolio_id: PortfolioId, force: bool = False) -> bool:
        """Delete a portfolio with validation."""
        
        with self._operation_context("delete_portfolio") as correlation_id:
            try:
                portfolio = self.get_portfolio(portfolio_id)
                
                if not force:
                    if portfolio.n_open_positions > 0:
                        raise InvalidPortfolioOperationError("Cannot delete portfolio with open positions")
                    
                    if portfolio.cash > 0:
                        raise InvalidPortfolioOperationError("Cannot delete portfolio with remaining cash")
                
                # RETIRE the definition durably BEFORE the in-memory teardown: a crash
                # after this leaves the row RETIRED (rehydrate filters is_deleted), never
                # a still-live row that comes back trading. Retiring also RELEASES the
                # (venue_name, account_id) pair for a successor. Nothing to retire on the
                # backtest/in-memory arm.
                if self.definition_store is not None:
                    self.definition_store.set_deleted(portfolio_id, True, datetime.now(UTC))

                portfolio.set_state(PortfolioState.ARCHIVED, "Portfolio deletion")
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

        Both halves run here so ``Portfolio.set_state`` stays a pure in-memory domain
        transition holding no storage. A state-change callback on ``Portfolio`` would put
        persistence inside the domain object; an event-driven persist is asynchronous
        relative to the flip and loses the deactivation on a crash between the two.

        Crash-safety ORDERING: persist ``enabled=False`` BEFORE the in-memory flip, so the
        state surviving ANY crash between the halves is "stopped", never "trading"; the
        next boot reconstructs it INACTIVE from the persisted flag. Idempotent.

        Disabling NEVER touches the venue account — that is a real external thing which
        outlives any number of internal portfolios.
        """
        portfolio = self.get_portfolio(portfolio_id)
        if self.definition_store is not None:
            self.definition_store.set_enabled(portfolio_id, False, datetime.now(UTC))
        portfolio.set_state(PortfolioState.INACTIVE, "operator deactivation (ACCT-10/D-30)")

    def activate_portfolio(self, portfolio_id: PortfolioId) -> None:
        """RESUME a portfolio durably — flip in memory FIRST, THEN persist enabled=True.

        Ordered the OTHER way from ``deactivate_portfolio`` for the SAME reason: the state
        surviving any crash must be "stopped". A crash between the halves leaves the row
        still ``enabled=False``, so the next boot rehydrates it INACTIVE — never a
        portfolio that returns trading on a half-completed resume. Idempotent.
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

    # PortfolioReadModel — structural Protocol implementation (no inheritance, no
    # adapter). The order domain reads portfolio state through this narrow surface ONLY.
    # Live Position objects never cross the boundary: get_position returns a frozen
    # PositionView.

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

        The ``PortfolioReadModel`` signature is keyed by ``portfolio_id``, which the
        Account has no notion of — hence the re-point onto ``reserve(order_id, amount)``.
        """
        self.get_portfolio(portfolio_id).account.reserve(order_id, amount)

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Release the cash reservation keyed by an order id (idempotent)."""
        self.get_portfolio(portfolio_id).account.release(order_id)

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Drop the local pending overlay on the venue ORDER-ACK.

        An unconditional call: ``drop_pending`` is declared on the account ABC, where a
        compute leaf documents it as a no-op because it holds no venue-side hold. The
        previous ``getattr`` probe was an account-type test in disguise, and it also
        silently skipped for any leaf that merely forgot to implement it.

        NON-terminal: it pops only the admission overlay, never the settled ledger.
        """
        self.get_portfolio(portfolio_id).account.drop_pending(order_id)

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on."""
        exchange: str = self.get_portfolio(portfolio_id).exchange
        return exchange

    def account_for(self, portfolio_id: PortfolioId) -> Optional[str]:
        """Return the venue account the portfolio's orders reach.

        The mirror of ``exchange_for``: an order's target is the pair
        ``(venue, account_id)`` and this reads the account half.

        Returns
        -------
        ``None`` when the portfolio names no account — live portfolios are required to
        name one by a composition-time invariant, not by this method.

        Raises
        ------
        PortfolioNotFoundError
            The id is not registered.
        """
        account_id: Optional[str] = self.get_portfolio(portfolio_id).account_id
        return account_id

    def open_position_count(self, portfolio_id: PortfolioId) -> int:
        """Return the number of open positions."""
        count: int = self.get_portfolio(portfolio_id).n_open_positions
        return count

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        """Return total equity as Decimal: full cash balance + position market values.

        Uses the FULL ledger balance (available cash PLUS reservations) — equity is a
        sizing/metrics figure, not buying power, so it must not net out reservations.
        """
        portfolio = self.get_portfolio(portfolio_id)
        return (
            portfolio.account.balance
            + portfolio.position_manager.get_total_market_value()
        )

    def set_universe(self, universe: Any) -> None:
        """Inject the Universe read-model used to resolve per-symbol Instruments.

        The margin math reads each ``SimulatedMarginAccount``'s OWN Universe, so the
        reference is propagated down to every margin account already registered.
        Portfolios are added before this runs, so none is missed.
        """
        self._universe = universe
        for portfolio in self._portfolios.values():
            account = portfolio.account
            if isinstance(account, SimulatedMarginAccount):
                account.set_universe(universe)

    def set_order_storage(self, order_storage: OrderStorage) -> None:
        """Inject the shared order mirror the liquidation forced-close registers into.

        Composition injects the SAME instance the ``OrderHandler``/``ReconcileManager``
        hold, so the mirror written here is the mirror the reconcile reads."""
        self._order_storage = order_storage

    def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
        """Return maintenance margin computed on demand.

        A pass-through to ``SimulatedMarginAccount``, which reads its OWN injected
        Universe plus the portfolio-side inputs supplied here.

        Returns
        -------
        ``Decimal("0")`` for a spot account — it carries no margin requirement.
        """
        portfolio = self.get_portfolio(portfolio_id)
        account = portfolio.account
        if not isinstance(account, SimulatedMarginAccount):
            return Decimal("0")
        # Pass ``portfolio.portfolio_id``, NOT the argument: the argument may arrive as an
        # int under the in-flight id migration, and the StateError carries the resolved
        # PortfolioId as its attribution context.
        return account.maintenance_margin(
            portfolio.position_manager.get_all_positions(),
            portfolio.portfolio_id,
        )

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        """Return ``total_equity / maintenance_margin``.

        The ratio arithmetic and its zero-maintenance sentinel stay on the leaf.

        Returns
        -------
        ``Decimal("0")`` for a spot account — the same deterministic sentinel the leaf
        returns when maintenance margin is zero.
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
    # Isolated-margin liquidation engine. The pure-Decimal math lives on
    # ``SimulatedMarginAccount``; only the emission shell (order registration, event mint,
    # queue put, log) stays here, so the account never needs a queue. Spot accounts have
    # no margin/liquidation surface and are skipped. The liq price is quantized to the
    # instrument price scale ONLY at the FillEvent boundary, never mid-formula.
    # ------------------------------------------------------------------

    def _liquidate_position(self, portfolio: Portfolio, position: Position,
                            liq_price: Decimal, fee_rate: Decimal,
                            bar_time: datetime) -> None:
        """Force-close a breached position on the BAR route.

        Mints a REAL opposite-side ``Order`` tagged ``OrderTriggerSource.LIQUIDATION``,
        registers it in the injected ``order_storage`` (without that,
        ``ReconcileManager.on_fill`` early-returns and the mirror never reaches FILLED),
        and puts a ``FillEvent(EXECUTED)`` DIRECTLY on the queue at ``time=bar_time`` —
        never through ExecutionHandler / SimulatedExchange, which fill next-bar-open, one
        bar too late for a breach settling on this bar. The penalty rides ``commission``.

        ``liq_price`` is the isolated maintenance floor, so the position closes AT it and
        never below, even when the breach bar gaps far through.

        Raises
        ------
        StateError
            No order storage wired.
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
        penalty = SimulatedMarginAccount._liquidation_penalty(fee_rate, size, liq_price)

        # Quantize ONLY here, at the FillEvent money boundary — never mid-formula. A stub
        # Instrument carrying no price scale leaves the full-precision price untouched.
        fill_price = liq_price
        instrument = self._universe.instrument(position.ticker)
        price_scale = getattr(instrument, "price_precision", None)
        if price_scale is not None:
            fill_price = quantize(liq_price, instrument, "price")

        # A forced deleverage is never owned by a strategy — mint a fresh StrategyId so the
        # trade log still carries a real fill→order→strategy chain; the LIQUIDATION
        # trigger source is what distinguishes it from a strategy-driven close.
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
        # Admission-bypassing: a forced deleverage is never rejected by a margin check.
        order.add_state_change(
            OrderStatus.PENDING,
            f"Forced liquidation close for {position.ticker}",
            OrderTriggerSource.LIQUIDATION,
            time=bar_time,
            allow_same_status=True,
        )
        self._order_storage.add_order(order)

        order_event = OrderEvent.new_order_event(order)
        fill_event = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=fill_price, quantity=size, commission=penalty, time=bar_time)
        self.global_queue.put(fill_event)

        # The logged ``liq_price`` is the QUANTIZED FillEvent price — what the position
        # actually settles at — while ``penalty`` carries the full precision it was
        # computed at. The log mirrors the emitted FillEvent.
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
        equity. No Universe / no order_storage wired → no-op.

        Parameters
        ----------
        closes : Dict[str, Decimal]
            The SAME per-ticker close map the caller built for the mark, passed in rather
            than re-derived from bar_events, so the mark price and the breach price are
            guaranteed identical.
        marked_portfolio_ids : Optional[set]
            Gates evaluation to the portfolios that re-marked cleanly this tick; ``None``
            means no gating. Under the current error policy the skip never fires — a
            failed mark RE-RAISES and the dispatch error seam works at whole-handler-call
            granularity, so either every active portfolio re-marked or this pass is not
            reached. Kept as a DEFENSIVE guardrail: were the re-raise ever softened to a
            per-portfolio continue, the partial-mark case would become reachable and this
            gate would already stop a breach reading stale, partially-marked equity.
        """
        if bar_time is None or self._universe is None or self._order_storage is None:
            return
        for portfolio in self.get_active_portfolios():
            if (marked_portfolio_ids is not None
                    and portfolio.portfolio_id not in marked_portfolio_ids):
                continue
            account = portfolio.account
            if not isinstance(account, SimulatedMarginAccount):
                continue
            for position in self._collect_breaches_over_prices(portfolio, closes, bar_time):
                wb, mmr, fee_rate = account._liq_inputs(position)
                liq_price = account._isolated_liq_price(position, wb, mmr)
                # LOAD-BEARING: the breach is DETECTED on the bar close but SETTLED at
                # ``liq_price``, the maintenance liq price. With no
                # ``min(loss + penalty, WB)`` clamp, filling at the maintenance floor is
                # THE mechanism bounding the realized loss near WB on a gap-through.
                # "Fixing" this to settle at the realistic breach close silently removes
                # that bound.
                self._liquidate_position(portfolio, position, liq_price, fee_rate, bar_time)

    def _collect_breaches_over_prices(self, portfolio: Portfolio,
                                      closes: Dict[str, Decimal],
                                      bar_time: datetime) -> List[Position]:
        """Collect breached open positions across a per-ticker close map.

        The SINGLE breach predicate — the live path and the unit tests both call this, so
        there is no second collector to drift apart. Each position is evaluated against
        ITS OWN ticker's close; a position whose ticker is absent from this tick is
        skipped, since a stale mark must never read as a breach.

        Returns
        -------
        The breached positions sorted ``(ticker, entry_date, position_id)`` — a
        deterministic order. Empty for a flat portfolio or a spot account.

        Raises
        ------
        StateError
            A position needs evaluating but no Universe is wired.
        """
        positions = portfolio.position_manager.get_all_positions()
        if not positions:
            return []
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
    # live, and the read of that truth plus the compare and the halt decision all run HERE,
    # on the engine thread. That placement structurally defeats the phantom-drift race —
    # the engine tally is fully applied before the compare reads it, and no compare is
    # reachable from a spawned coroutine.
    # ------------------------------------------------------------------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the composition-root freeze-in-place halt entrypoint.

        The live root wires ``LiveTradingSystem.halt`` here. Backtest never wires it — no
        venue truth anywhere, so nothing is compared.
        """
        self._halt_signal = halt_signal

    def set_snapshot_source(
        self, source: Callable[[Portfolio], Optional[Any]]
    ) -> None:
        """Inject the per-portfolio venue-truth source for the drift compare.

        Returns an ``AccountSnapshot`` for a portfolio whose account has a venue behind
        it, or ``None`` when there is none — backtest and paper, where cash and positions
        are engine-computed and there is nothing external to compare against.

A source rather than an account-type test. "Is there venue truth for this
        portfolio?" is answered by whoever wired the venue, not inferred from which
        concrete leaf the portfolio happens to hold — an inferred answer is one that can
        become uniformly False and silently disable the whole compare with nothing red.

        Left unwired, every portfolio reports no venue truth and the compare skips — the
        correct backtest default.
        """
        self._snapshot_source = source

    def set_drift_reconciler(
        self, reconciler: Callable[[Any, str, Decimal, Decimal], bool]
    ) -> None:
        """Inject the external-event reconciler for beyond-band drift.

        Answers whether a beyond-band per-symbol drift reconciles to a KNOWN venue event
        (an external cancel, an external or hand-closed fill) — adopt-and-continue — or is
        genuinely unexplained and halts the engine. Left unwired, every beyond-band drift
        counts as unexplained: the conservative money-first default.
        """
        self._drift_reconciler = reconciler

    def _drift_precision(self, ticker: str) -> int:
        """Resolve the instrument quantity precision for the drift epsilon.

        Keys the tolerance band off the SAME instrument precision ``core.money.quantize``
        consumes, never a hand-rolled per-symbol table.

        Returns
        -------
        The instrument's ``quantity_precision``, or the money-policy default of 8 when no
        Universe is wired, the symbol is unknown, or the instrument declares none.
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
                              just_applied_fill_qty: Optional[Decimal] = None,
                              snapshot: Optional[Any] = None) -> None:
        """Per-symbol engine-vs-venue drift compare on the ENGINE thread.

        Runs ONLY for a portfolio with venue truth behind it; backtest and paper have none
        and skip cleanly. Compares the engine's fill-applied quantity for ``ticker``
        against venue truth, keyed to the instrument precision:

        * within the precision-epsilon band → adopt venue truth silently (last-digit dust);
        * within the spurious-halt band → absorb, defer to the periodic sweep;
        * beyond band but reconciling to a known venue event → adopt-and-continue;
        * beyond band and unexplained → freeze-in-place halt the WHOLE engine.

        Parameters
        ----------
        just_applied_fill_qty : Optional[Decimal]
            The SIGNED position delta of a fill JUST applied to the engine belief
            (``+qty`` BUY, ``-qty`` SELL), passed ONLY by the on-fill compare. It opens
            the spurious-halt band: the venue snapshot legitimately lags a fill it has not
            streamed yet, and a first position-opening fill must not halt. ``None`` — the
            per-bar sweep — means every beyond-band skew is a candidate drift, so the
            sweep still halts once the snapshot has had time to catch up and a genuinely
            persistent divergence is never hidden.
        snapshot : Optional[AccountSnapshot]
            Venue truth already read by the caller. Passed in by the per-bar sweep, which
            takes ONE snapshot per portfolio and compares every symbol against it: reading
            it per symbol would multiply the venue round trips and, worse, let two symbols
            be judged against two different pictures of the venue. ``None`` means "read it
            here" — the on-fill compare, which examines a single symbol.
        """
        if snapshot is None:
            snapshot = self._venue_snapshot(portfolio)
        if snapshot is None:
            return  # backtest/paper — no venue truth, nothing to reconcile.

        venue_qty = snapshot.positions.get(ticker, Decimal("0"))
        engine_position = portfolio.get_open_position(ticker)
        engine_qty = (
            engine_position.net_quantity if engine_position is not None
            else Decimal("0")
        )
        precision = self._drift_precision(ticker)
        if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
            return  # within the precision-epsilon band — adopt silently.

        # Spurious-halt band: the ONLY holding the snapshot's lag explains is the pre-fill
        # one (``engine_qty - just_applied_fill_qty``). When venue truth still matches
        # THAT within the band, the skew IS the un-streamed fill, not drift.
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

        # Unexplained beyond-band drift → freeze-in-place halt: the compare just declared
        # the engine's own state untrustworthy. The halt does NOT auto-flatten or
        # auto-cancel — it stops NEW submissions and surfaces HALTED plus a CRITICAL
        # alert. Flattening on state you have decided you cannot trust is worse.
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
        """Periodic per-closed-bar drift backstop — the on-bar complement to the on-fill
        compare.

        Sweeps the union of engine-held and venue-reported tickers, so a position the
        engine has forgotten is still compared. Portfolios with no venue truth are skipped.

        ONE snapshot per portfolio, taken here and threaded into every per-symbol compare.
        That placement is load-bearing now that venue truth is read on demand rather than
        off a streamed cache: taking it inside the symbol loop would turn one sweep into
        one venue round trip PER SYMBOL, and would let two symbols of the same portfolio be
        judged against two different pictures of the venue.
        """
        if bar_time is None:
            return
        for portfolio in self.get_active_portfolios():
            snapshot = self._venue_snapshot(portfolio)
            if snapshot is None:
                continue
            engine_tickers = set(portfolio.positions.keys())
            venue_tickers = set(snapshot.positions.keys())
            for ticker in sorted(engine_tickers | venue_tickers):
                self._compare_symbol_drift(
                    portfolio, ticker, self._generate_correlation_id(),
                    snapshot=snapshot)

    def _venue_snapshot(self, portfolio: Portfolio) -> Optional[Any]:
        """Venue truth for ``portfolio``, or ``None`` when it has none behind it.

        A failed venue read is NOT a drift signal: reporting an empty snapshot would make
        every engine-held position look like a phantom and halt a healthy engine on a
        transient network fault. Unreadable venue truth means "no comparison is possible
        right now", which is what ``None`` says.
        """
        if self._snapshot_source is None:
            return None
        try:
            return self._snapshot_source(portfolio)
        except Exception:
            self.logger.error(
                "Venue snapshot failed — skipping the drift compare for this portfolio "
                "rather than treating unreadable truth as drift", exc_info=True)
            return None

    def _mark_venue_trade_settled(self, venue_trade_id: str) -> None:
        """Record a venue trade id as settled in the bounded FIFO dedup ledger.

        Evicts the oldest id past the cap so a long-running session cannot grow it without
        bound; re-inserting a present id refreshes its recency.
        """
        self._settled_venue_trade_ids[venue_trade_id] = None
        self._settled_venue_trade_ids.move_to_end(venue_trade_id)
        while len(self._settled_venue_trade_ids) > self._max_settled_venue_trade_ids:
            self._settled_venue_trade_ids.popitem(last=False)

    def _persist_account_state(self, portfolio: Portfolio, updated_time: datetime) -> None:
        """Write-through the durable account-state scalar after a settled fill.

        The restart path reads this cash scalar back through ``Account.restore_cash``, so
        without the write a restart would restore the construction-time initial cash
        instead of the true balance.

        LIVE ONLY — the in-memory backtest backend exposes no ``save_account_state``, so
        this is a clean ``getattr`` skip. ``updated_time`` is the fill's BUSINESS time,
        never wall-clock.
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

        The cross-restart arm the in-session guard does NOT cover: both dedup ledgers start
        EMPTY on a restart, so a venue trade re-delivered afterwards — an OKX stream
        re-send, or the ``VenueReconciler`` adopting a downtime fill — would be booked a
        SECOND time. Per active portfolio this seam:

        1. Drives ``state_storage.rehydrate(account)``, surfacing open positions through
           the live ``PositionManager`` read cache and restoring the persisted cash scalar
           into the ``Account``. The in-memory backtest backend exposes no ``rehydrate``.
        2. Seeds the settled-trade dedup ledger from the durable
           ``transactions.venue_trade_id``, keyed ``f"{ticker}:{venue_trade_id}"`` —
           collision-safe, because the same numeric trade id on a DIFFERENT symbol is a
           distinct economic trade and must still settle.
        3. Forwards those SAME keys to ``applied_trade_sink``, so the order-mirror ring
           (``ReconcileManager._applied_trade_keys``, which has no durable store of its
           own) is seeded off ONE history pass rather than a second divergent read.

        Sequencing: this MUST run BEFORE ``VenueReconciler.reconcile()`` so adoption diffs
        against restored state and the dedup ledger already knows every settled venue trade.

        Parameters
        ----------
        applied_trade_sink : Optional[Callable[[Iterable[str]], None]]
            ``OrderManager.seed_applied_trades`` in live; ``None`` on backtest keeps the
            portfolio-arm-only behaviour.
        """
        seeded_keys: List[str] = []
        for portfolio in self.get_active_portfolios():
            storage = portfolio.state_storage
            rehydrate_fn = getattr(storage, "rehydrate", None)
            if rehydrate_fn is None:
                continue  # backtest in-memory backend — nothing durable to restore.
            rehydrate_fn(portfolio.account)
            # The realised-PnL accumulator is NOT one of the containers the working-set
            # cache carries, so without this re-seed a post-restart fill would overwrite
            # the durable realized_pnl column with a 0-based value.
            load_account_state = getattr(storage, "load_account_state", None)
            if load_account_state is not None:
                account_state = load_account_state()
                if account_state is not None:
                    portfolio.position_manager.restore_realised_pnl(
                        account_state["realized_pnl"]
                    )
            # Backtest/simulated transactions carry no venue key and are skipped.
            for transaction in storage.get_transaction_history():
                venue_trade_id = getattr(transaction, "venue_trade_id", None)
                if venue_trade_id is None:
                    continue
                dedup_key = f"{transaction.ticker}:{venue_trade_id}"
                self._mark_venue_trade_settled(dedup_key)
                seeded_keys.append(dedup_key)
        if applied_trade_sink is not None and seeded_keys:
            applied_trade_sink(seeded_keys)

    def on_fill(self, fill_event: FillEvent) -> None:
        """Settle an EXECUTED fill into the addressed portfolio.

        Raises
        ------
        Typed domain exceptions, which propagate to the dispatch registry's
        ``HandlerErrorPolicy`` seam. Under the backtest ``FailFastPolicy`` the run stops
        loudly rather than producing corrupted numbers.
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

        # Cross-emitter fill-dedup at the settlement chokepoint, BEFORE anything mutates
        # position/cash, so a re-delivered 0.5 BTC is never booked as 1.0. The venue trade
        # id is the ONE idempotency key the two live emitters share. Key by
        # f"{ticker}:{venue_trade_id}", NOT the raw id: the numeric venue tradeId is only
        # unique per instrument, so the same id on another symbol is a DISTINCT economic
        # trade and must still settle. Simulated fills carry None and skip the guard.
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

                # FillEvent money is already Decimal, so to_money is an identity
                # normalization here — kept deliberately, since the ledger never trusts an
                # unnormalized input.
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
                    # Audit chain: fill -> order -> strategy.
                    fill_id=fill_event.fill_id,
                    # The admission-clamped EFFECTIVE leverage, so the position-life locked
                    # margin (aggregate_notional / leverage) EQUALS the admission
                    # reservation (notional / effective_leverage).
                    leverage=getattr(fill_event, "leverage", Decimal("1")),
                    venue_trade_id=venue_trade_id,
                    # Lets the spot settlement seam net a base-denominated fee out of the
                    # position quantity instead of the quote cash leg. None when simulated.
                    fee_currency=getattr(fill_event, "fee_currency", None),
                )

                # Wrap the durable position upsert and the cash-scalar upsert in ONE
                # transaction: a crash between them would leave the durable position one
                # fill ahead of the durable cash, and that torn restore is PERMANENT on the
                # SimulatedAccount path since no venue heals it. The in-memory backtest
                # backend exposes no fill_transaction, so this getattr-skips.
                fill_transaction = getattr(
                    portfolio.state_storage, "fill_transaction", None)
                if fill_transaction is not None:
                    with fill_transaction():
                        portfolio.transact_shares(transaction)
                        self._persist_account_state(portfolio, fill_event.time)
                else:
                    portfolio.transact_shares(transaction)
                    self._persist_account_state(portfolio, fill_event.time)

                # Mark settled ONLY after the durable persist committed, so a rolled-back
                # persist never records a key for a fill that did not land.
                if dedup_key is not None:
                    self._mark_venue_trade_settled(dedup_key)

                self.logger.debug(
                    "Fill event processed",
                    portfolio_id=portfolio_id,
                    ticker=fill_event.ticker,
                    correlation_id=correlation_id
                )

                # Drift compare immediately after the fill has drained. The signed delta
                # MUST be the ACTUAL position delta settlement applied — NET of a
                # base-denominated fee, which ``transaction.position_quantity`` already is.
                # Passing the RAW fill_event.quantity leaves the spurious-halt band's
                # pre-fill reconstruction off by the fee and trips halt('drift') while the
                # venue cache is still pre-fill.
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
    
    def update_portfolios_market_value(self, bar_events: Union[BarEvent, List[BarEvent]]) -> None:
        """Mark every active portfolio, then run the liquidation and drift passes."""
        
        if isinstance(bar_events, BarEvent):
            bar_events = [bar_events]
        
        # The close is already Decimal via the Bar struct; downstream position updates
        # enter via to_money (value-identity on Decimal input).
        prices = {}
        # The bar's BUSINESS time drives the mark and the carry accrual — NEVER
        # datetime.now(UTC), which breaks the determinism double-run gate.
        bar_time = None
        for bar_event in bar_events:
            bar_time = bar_event.time
            for ticker, bar in bar_event.bars.items():
                prices[ticker] = bar.close

        active_portfolios = self.get_active_portfolios()

        # Which portfolios re-marked cleanly THIS tick, fed to the liquidation gate. Always
        # the FULL active set under the current error policy — see _run_liquidation_pass
        # for why it is kept anyway.
        marked_portfolio_ids: set[Any] = set()

        for portfolio in active_portfolios:
            try:
                # The Universe lets each open short resolve its Instrument.borrow_rate;
                # with no universe, rate 0, or no open shorts the carry accrual no-ops.
                portfolio.update_market_value_of_portfolio(prices, bar_time, self._universe)
                marked_portfolio_ids.add(portfolio.portfolio_id)
            except Exception as e:
                # A failed mark must NOT be swallowed: continuing would leave the equity
                # curve carrying stale position values that the metrics/drawdown/oracle
                # blocks then consume as if valid. Publish, then re-raise so the backtest
                # policy aborts instead of producing silently-wrong numbers.
                correlation_id = self._generate_correlation_id()
                self._publish_error_event(
                    e, "update_portfolios_market_value", correlation_id,
                    portfolio.portfolio_id)
                raise

        # AFTER the mark + carry pass, so a breach sees carry-eroded equity, and over the
        # SAME ``prices`` map the mark used, so the two prices cannot diverge.
        self._run_liquidation_pass(prices, bar_time, marked_portfolio_ids)
        self._run_drift_sweep(bar_time)

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
    
    @staticmethod
    def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to the shared ``recursive_merge`` — never a per-handler merge."""
        return recursive_merge(base, updates)

    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update PortfolioHandler configuration at runtime.

        recursive_merge -> model_validate -> atomic swap, re-deriving the cached
        ``max_portfolios``.

        Raises
        ------
        ConfigurationError
            The merged config failed validation, including on an unknown key
            (``extra="forbid"``). Nothing is swapped in on failure.
        """
        # Recursive-merge so a partial nested update (a single limits field, say)
        # preserves the rest of that submodel instead of replacing it wholesale, as a
        # shallow `{**a, **b}` would.
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
