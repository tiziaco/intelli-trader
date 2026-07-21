"""
Enhanced PortfolioHandler with better separation of concerns.

D-19 single-writer contract: ALL portfolio state mutations happen on the
engine thread; queue.Queue is the thread boundary — other threads only put
events. Composite reads are consistent because nothing mutates concurrently.
Live cross-thread reads are a D-live design item.
"""
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
    """
    Enhanced PortfolioHandler with better separation of concerns.
    
    This handler focuses on:
    - Global system configuration via a Pydantic PortfolioConfig
    - Portfolio lifecycle management (creation, deletion)
    - System-wide monitoring and health checks
    - Event publishing coordination
    - Runtime configuration updates via API

    Individual portfolios manage their own:
    - State (ACTIVE, INACTIVE, ARCHIVED)
    - Configuration (limits, validation)
    - Health monitoring

    D-19 single-writer contract: ALL portfolio state mutations happen on the
    engine thread; queue.Queue is the thread boundary — other threads only put
    events. Composite reads are consistent because nothing mutates
    concurrently. Live cross-thread reads are a D-live design item.
    """
    
    def __init__(self, global_queue: "EventBus", config_dir: str = "settings",
                 environment: str = "backtest", sql_engine: "Optional[Any]" = None) -> None:
        self.global_queue: "EventBus" = global_queue
        self.current_time: Any = 0

        # D-07 (05.2-05): the durable portfolio-storage selector threaded down
        # into each Portfolio's state storage (add_portfolio -> Portfolio ->
        # PortfolioStateStorageFactory.create). "backtest" (the default) is the
        # in-memory oracle-dark path; the live composition root passes "live" +
        # the shared SqlEngine so every portfolio persists to the durable SQL
        # ledger and rehydrates its truth on restart. ``sql_engine`` is typed Any
        # to keep the SqlEngine import off this hot-path module (GATE-01).
        self._environment = environment
        self._sql_engine = sql_engine
        
        # Initialize configuration by constructing the Pydantic model directly
        # (M2-06 / D-01): the registry/provider getters were deleted. Pydantic validates
        # on construction, so no separate validator is needed.
        self.config_data: PortfolioConfig = PortfolioConfig.default()

        # Extract key configuration values with defaults.
        # WR-08: sourced from the dedicated limits.max_portfolios field —
        # NOT limits.max_positions (the per-portfolio position limit).
        self.max_portfolios = self.config_data.limits.max_portfolios
        self.publish_error_events = True  # Default behavior

        # Portfolio storage - now just stores portfolio instances.
        # 02-05 carry-over: portfolios are keyed by PortfolioId (UUID) at runtime
        # while events still carry an int portfolio_id. Until the portfolio_id
        # migration completes, the key is typed Any to bridge both forms (the full
        # retype is deferred — not mandated by Task 2).
        # D-19: collection lock removed — single-writer contract, see class docstring.
        self._portfolios: Dict[Any, Portfolio] = {}

        # Plan 02-05 (D-13/MARGIN-03): the injected Universe read-model used to
        # resolve each open position's Instrument (maintenance_margin_rate) on
        # demand. None until wired — the runner builds the Universe at its Trap-4
        # point (AFTER this handler is constructed in compose_engine) and calls
        # set_universe, mirroring the exchange/order-domain seam from Plan 02-03.
        # maintenance_margin/margin_ratio are query-only and unread on the golden
        # path, so a None Universe never trips during the byte-exact SMA_MACD run.
        self._universe: Any = None

        # LIQ-03 (04-03): the NARROW INJECTED WRITE-SEAM the liquidation engine
        # uses to register a forced-close Order in the shared order mirror, set
        # via set_order_storage (the analog of set_universe). None until wired —
        # compose.py injects the SAME order_storage instance the OrderHandler /
        # ReconcileManager hold, so the portfolio side writes into the exact
        # mirror the reconcile reads. Oracle-dark on the spot path: with no
        # breaches it is never written, so SMA_MACD stays byte-exact.
        self._order_storage: Optional[OrderStorage] = None

        # 05-04 (D-15/D-01/D-02, RECON-01/RECON-03): the engine-thread drift-halt
        # seam. The live composition root injects a halt callback
        # (``LiveTradingSystem.halt``) via ``set_halt_signal``; on unexplained
        # beyond-band per-symbol drift the engine-thread compare calls it to freeze
        # the WHOLE engine (D-02). ``None`` on the backtest path — no VenueAccount
        # portfolio exists, so the compare is never reached and the SMA_MACD oracle
        # stays byte-exact (drift is inert on the spot SimulatedAccount path).
        self._halt_signal: Optional[Callable[[str], None]] = None
        # 05-04 (D-04): the injected reconciler answering whether a beyond-band
        # drift maps to a KNOWN venue event (an external cancel / external or
        # hand-closed fill) and is therefore adopt-and-continue rather than a halt.
        # Signature ``(portfolio, ticker, engine_qty, venue_qty) -> bool``. ``None``
        # → the conservative money-first default: any beyond-band drift is
        # unexplained (halt). The full resolver (venue order/fill events + stored
        # intent) is a follow-on (restart/resilience); this plan wires the halt.
        self._drift_reconciler: Optional[
            Callable[[Any, str, Decimal, Decimal], bool]
        ] = None

        # CR-01: bounded per-handler set of already-settled venue trade ids — the
        # cross-emitter fill-dedup ledger. The live OKX stream and the restart
        # VenueReconciler can both book the SAME economic venue trade (they share
        # no other idempotency key: fill_id is a fresh uuid7 per emit). on_fill
        # rejects a fill whose venue_trade_id is already here so the position/cash
        # settles exactly once. An OrderedDict is used as a bounded FIFO (oldest
        # evicted past the cap) so a long-running live session cannot grow it
        # unbounded. Backtest/simulated fills carry venue_trade_id=None and NEVER
        # touch this ledger — the SMA_MACD oracle stays byte-exact (oracle-dark).
        self._settled_venue_trade_ids: "OrderedDict[str, None]" = OrderedDict()
        self._max_settled_venue_trade_ids = 100_000

        # Global logger
        self.logger = get_itrader_logger().bind(component="PortfolioHandler")

        self.logger.info(
            "Enhanced PortfolioHandler initialized",
            max_portfolios=self.max_portfolios
        )

    def _generate_correlation_id(self) -> CorrelationId:
        """Generate unique correlation ID for operation tracking (D-01/D-02 — single UUIDv7 idgen scheme)."""
        return CorrelationId(idgen.generate_correlation_id())

    def _publish_error_event(self, error: Exception, operation: str, correlation_id: CorrelationId, portfolio_id: Optional[Any] = None) -> None:
        """Publish error event if enabled."""
        if not self.publish_error_events:
            return
        
        # Frozen PortfolioErrorEvent (D-06): type=EventType.ERROR via the
        # ErrorEvent base; source defaults to "portfolio" on the child.
        # Wall-clock carve-out (RESEARCH Open Question 4): error paths never
        # fire during a green oracle run, so datetime.now(UTC) here cannot
        # perturb determinism — the engine path itself stays on business time.
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
        """Context manager providing a correlation ID for operation tracking.

        D-19: the concurrency-limiting machinery (_operations_lock /
        _active_operations) was removed with the single-writer contract.
        Correlation-id generation and error-event publication (Pitfall 8)
        survive — this context only supplies the correlation id now.
        """
        correlation_id = self._generate_correlation_id()
        yield correlation_id
    
    # Main portfolio management methods (keeping same names for compatibility)
    def add_portfolio(self, name: str, exchange: str, cash: float,
                      portfolio_config: Optional[PortfolioConfig] = None,
                      portfolio_id: Optional[PortfolioId] = None,
                      account_id: Optional[str] = None,
                      venue_name: Optional[str] = None) -> PortfolioId:
        """Create a new portfolio with enhanced capabilities.

        ACCT-04: the former owning-user first positional parameter was dropped —
        that mapping is an app-layer (FastAPI) concern, not a Portfolio concern,
        and is not relocated onto the Account.

        F-5 (11-05): ``portfolio_id`` / ``account_id`` / ``venue_name`` mirror the
        ``Portfolio.__init__`` parameters one-for-one and are threaded straight
        through. All three DEFAULT so the byte-exact backtest composition-root call
        — ``add_portfolio(name=, exchange='csv', cash=)`` — stays untouched.

        * ``portfolio_id`` — an EXISTING id to reattach to on rehydrate (F-1).
          Supplying an id already registered here RAISES rather than overwriting:
          a silent overwrite would destroy the first portfolio's cash and positions.
        * ``account_id`` — the venue account this portfolio's orders reach (D-06).
        * ``venue_name`` — the source of truth for the portfolio's exchange (D-07);
          when supplied it wins and ``exchange`` is derived from it.
        """

        with self._operation_context("add_portfolio") as correlation_id:
            try:
                # Global validations
                if cash <= 0:
                    raise PortfolioValidationError(0, "initial_cash", "Initial cash must be positive")

                if not name.strip():
                    raise PortfolioValidationError(0, "name", "Portfolio name cannot be empty")

                # F-1 (11-05): now that ids are supplyable, a duplicate must fail
                # loud. The store below is an unconditional dict assignment, so
                # without this guard a re-add would SILENTLY destroy the first
                # portfolio along with its cash and open positions.
                if portfolio_id is not None and portfolio_id in self._portfolios:
                    raise PortfolioValidationError(
                        portfolio_id, "portfolio_id",
                        "A portfolio with this id is already registered"
                    )

                # Check global limits
                if len(self._portfolios) >= self.max_portfolios:
                    raise PortfolioConfigurationError("max_portfolios", self.max_portfolios, "maximum portfolios limit reached")
                
                # Create portfolio instance. D-07 (05.2-05): thread the durable
                # environment + shared backend so the portfolio's state storage
                # is the live SQL ledger when wired 'live' (default "backtest" =
                # in-memory, oracle-dark).
                portfolio = Portfolio(
                    name=name,
                    exchange=exchange,
                    cash=to_money(cash),
                    time=datetime.now(UTC),
                    config=portfolio_config,
                    environment=self._environment,
                    sql_engine=self._sql_engine,
                    portfolio_id=portfolio_id,
                    account_id=account_id,
                    venue_name=venue_name,
                )
                
                # Store portfolio
                self._portfolios[portfolio.portfolio_id] = portfolio
                
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
    
    def get_portfolio(self, portfolio_id: PortfolioId) -> Portfolio:
        """Get portfolio instance."""
        if portfolio_id not in self._portfolios:
            raise PortfolioNotFoundError(portfolio_id)
        return self._portfolios[portfolio_id]
    
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
                
                # Archive portfolio first
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
    
    def get_active_portfolios(self) -> List[Portfolio]:
        """Get all active portfolios."""
        return [p for p in self._portfolios.values() if p.is_active()]

    def get_portfolios_by_state(self, state: PortfolioState) -> List[Portfolio]:
        """Get portfolios by state."""
        return [p for p in self._portfolios.values() if p.state == state]

    def get_portfolio_count(self) -> int:
        """Get total portfolio count."""
        return len(self._portfolios)

    # PortfolioReadModel — structural Protocol implementation (D-16, Plan 05-03)
    #
    # The order domain reads portfolio state through this narrow Protocol surface ONLY
    # (itrader/core/portfolio_read_model.py). No inheritance, no adapter:
    # PortfolioHandler satisfies the runtime_checkable Protocol structurally.
    # D-15: live Position objects never cross the boundary — get_position
    # returns a frozen PositionView snapshot (None when flat).

    def active_portfolio_ids(self) -> List[PortfolioId]:
        """Return the ids of all active portfolios (WR-02, LIFE-01 sweep)."""
        return [p.portfolio_id for p in self._portfolios.values() if p.is_active()]

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        """Return the portfolio's buying power (balance minus reservations, D-14)."""
        return self.get_portfolio(portfolio_id).account.available_balance

    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> Optional[PositionView]:
        """Return a frozen snapshot of the open position, or None when flat (D-15)."""
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
        """Reserve cash for a pending order (per-reference, full precision — OQ4).

        D-06/D-07: the ``PortfolioReadModel.reserve(portfolio_id, order_id,
        amount)`` Protocol signature stays FROZEN (keyed by ``portfolio_id``,
        which the Account has no notion of); only the delegation re-points to the
        Account-level ``reserve(order_id, amount)`` (the fixed "order cash
        reservation" description + ``str(order_id)`` reference are folded into the
        account method). Zero order-domain ripple.
        """
        self.get_portfolio(portfolio_id).account.reserve(order_id, amount)

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Release the cash reservation keyed by an order id (idempotent).

        D-06/D-07: Protocol signature FROZEN; delegation re-points to the
        Account-level ``release(order_id)``.
        """
        self.get_portfolio(portfolio_id).account.release(order_id)

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Drop the local pending overlay on the venue ORDER-ACK (D-15, V17-13).

        Getattr-guarded delegate: only ``VenueAccount`` carries a local pending
        overlay to drop, so this resolves ``account.drop_pending`` dynamically and
        skips cleanly when absent (paper/simulated accounts have no such method —
        oracle-dark, the byte-exact backtest never takes this branch). Mirrors the
        ``save_account_state`` getattr-skip idiom. NON-terminal: the account drop
        pops only the admission overlay, never the settled ledger.
        """
        fn = getattr(self.get_portfolio(portfolio_id).account, "drop_pending", None)
        if fn is not None:
            fn(order_id)

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on (admission metadata, OQ1)."""
        exchange: str = self.get_portfolio(portfolio_id).exchange
        return exchange

    def account_for(self, portfolio_id: PortfolioId) -> Optional[str]:
        """Return the venue account the portfolio's orders reach (D-27, plan 11-05).

        The direct mirror of ``exchange_for``: an order's target is the pair
        ``(venue, account_id)`` and this reads the account half. Routed through
        ``get_portfolio`` so an unknown id raises ``PortfolioNotFoundError``,
        identically to ``exchange_for``.

        ``Optional[str]`` because ``Portfolio.account_id`` is optional — the
        default keeps the byte-exact backtest call site untouched; plan 11-08's
        composition-time invariant is what requires a named account in live.

        ExecutionHandler reads this through the injected ``PortfolioReadModel``
        Protocol (11-06) and never imports this class.
        """
        account_id: Optional[str] = self.get_portfolio(portfolio_id).account_id
        return account_id

    def open_position_count(self, portfolio_id: PortfolioId) -> int:
        """Return the number of open positions (position-limit check, OQ1)."""
        count: int = self.get_portfolio(portfolio_id).n_open_positions
        return count

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        """Return total equity as Decimal: full cash balance + position market values.

        Plan 07-01 (M5-06): the RiskPercent sizing input — computed from the
        Decimal internals directly (RESEARCH Pitfall 8: CashManager.balance and
        PositionManager.get_total_market_value() are both Decimal-native), NEVER
        through the float Portfolio.total_equity property. Uses the FULL ledger
        balance (available cash + reservations) — equity is a sizing/metrics
        figure, not buying power. Oracle-dark: the golden FractionOfCash policy
        never reads it.
        """
        portfolio = self.get_portfolio(portfolio_id)
        return (
            portfolio.account.balance
            + portfolio.position_manager.get_total_market_value()
        )

    def set_universe(self, universe: Any) -> None:
        """Inject the Universe read-model used to resolve per-symbol Instruments.

        Plan 02-05 (D-13): called by the runner at its Trap-4 wiring point (after
        the Universe is built, mirroring the exchange/order-domain set_universe
        seam from Plan 02-03). Stores the reference; maintenance_margin reads
        ``universe.instrument(ticker).maintenance_margin_rate`` per open position.

        ACCT-02: the margin/liquidation MATH now lives on
        ``SimulatedMarginAccount`` and reads the account's OWN injected Universe
        (the math-pulldown moved the universe seam down with it, 01-02). Propagate
        the reference down to each existing margin account so the delegated math is
        wired. Spot (``SimulatedCashAccount``) accounts have no margin surface and
        are skipped. Backtest adds all portfolios before this Trap-4 call, so every
        margin account is reached; this is oracle-dark (the golden run is spot).
        """
        self._universe = universe
        for portfolio in self._portfolios.values():
            account = portfolio.account
            if isinstance(account, SimulatedMarginAccount):
                account.set_universe(universe)

    def set_order_storage(self, order_storage: OrderStorage) -> None:
        """Inject the shared order mirror for the liquidation forced-close (LIQ-03).

        04-03: the NARROW INJECTED WRITE-SEAM (the analog of ``set_universe`` and
        the ``PortfolioReadModel.reserve``/``release`` write-ish surface) the
        BAR-route liquidation engine uses to register a real forced-close
        ``Order`` so ``ReconcileManager.on_fill`` reconciles EXECUTED→FILLED
        (Pitfall 4 — without the registered order the reconcile early-returns and
        the mirror silently no-ops). ``compose.py`` injects the SAME
        ``order_storage`` instance the ``OrderHandler``/``ReconcileManager`` hold,
        so the mirror is a single shared store. NOT a raw handler-to-handler call
        and NOT an enqueued OrderEvent (the ORDER route would fill next-bar-open,
        violating D-04/Pitfall 6). Query/write-only and oracle-dark on the golden
        path (no breaches → never written)."""
        self._order_storage = order_storage

    def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
        """Return maintenance margin computed on demand (D-13/MARGIN-03).

        ACCT-02: the inline computation was pulled DOWN to
        ``SimulatedMarginAccount.maintenance_margin`` (the math reads the
        account's OWN injected Universe + the portfolio's open positions). This
        handler method is now a thin pass-through delegating to the portfolio's
        account. A spot (``SimulatedCashAccount``) account has no margin
        requirement and returns ``Decimal("0")``. The PortfolioReadModel
        signature ``maintenance_margin(portfolio_id) -> Decimal`` is FROZEN.
        """
        account = self.get_portfolio(portfolio_id).account
        if not isinstance(account, SimulatedMarginAccount):
            return Decimal("0")
        return account.maintenance_margin()

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        """Return ``total_equity / maintenance_margin`` (D-12/D-13).

        ACCT-02: pulled DOWN to ``SimulatedMarginAccount.margin_ratio``; this is a
        thin pass-through. A spot account returns the deterministic ``Decimal("0")``
        sentinel (no margin required). Signature FROZEN (PortfolioReadModel).
        """
        account = self.get_portfolio(portfolio_id).account
        if not isinstance(account, SimulatedMarginAccount):
            return Decimal("0")
        return account.margin_ratio()

    # ------------------------------------------------------------------
    # Isolated-margin liquidation engine (LIQ-01/02, D-01-CORR/D-03-CORR/D-04/
    # D-05/D-07). The BAR-route per-position breach check runs AFTER the per-
    # portfolio mark + P3 carry pass (D-02 placement — breach sees carry-eroded
    # equity).
    #
    # ACCT-02: the pure-Decimal MATH (``_isolated_liq_price`` / ``_is_breached`` /
    # ``_liquidation_penalty`` / ``_liq_inputs`` + the ``maintenance_margin`` /
    # ``margin_ratio`` bodies above) was pulled DOWN onto ``SimulatedMarginAccount``.
    # The EMISSION SHELL stays HERE (``_liquidate_position`` /
    # ``_run_liquidation_pass`` / ``_collect_breaches_over_prices``): it keeps the
    # ``order_storage.add_order`` + ``OrderEvent``/``FillEvent`` mint +
    # ``global_queue.put`` + log, and calls DOWN into the portfolio's margin
    # account for the math. The queue-only rule is preserved (the account has no
    # queue). Spot accounts have no margin/liquidation surface, so they are skipped
    # — byte-identical to the prior wb==0 continue (oracle-dark). The liq price is
    # quantized to the instrument price scale ONLY at the FillEvent boundary in the
    # mint step, never mid-formula.
    # ------------------------------------------------------------------

    def _liquidate_position(self, portfolio: Portfolio, position: Position,
                            liq_price: Decimal, fee_rate: Decimal,
                            bar_time: datetime) -> None:
        """Force-close a breached position on the BAR route (LIQ-02/LIQ-03/D-04).

        Mints a REAL opposite-side ``Order`` (SELL to close a long / BUY to close
        a short; qty = ``|net_quantity|``) tagged ``OrderTriggerSource.LIQUIDATION``,
        registers it in the injected ``order_storage`` (Pitfall 4 — without this
        ``ReconcileManager.on_fill`` early-returns and the mirror never reaches
        FILLED), and emits a ``FillEvent(EXECUTED)`` DIRECTLY on the queue at the
        liq price with ``time=bar_time`` — NOT routed through ExecutionHandler /
        SimulatedExchange (D-04/Pitfall 6 — those fill next-bar-open; liquidation
        settles on the breach bar). The liq price enters the FillEvent as the
        executed price; the penalty rides ``commission`` (D-05). The existing
        ``portfolio.on_fill`` settle path realizes the PnL + penalty and releases
        the lock. The realized loss is bounded by SETTLING THE FORCED CLOSE AT THE
        ISOLATED MAINTENANCE LIQ PRICE (D-03 automatic-floor reading): the position
        is closed AT the floor, never below it, even when the breach bar gaps far
        below the liq price (the engine fills at the liq price, not the gapped
        close). There is NO explicit ``min(loss + penalty, WB)`` clamp —
        fill-at-liq-price is the loss-bounding mechanism.
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
        # ACCT-02: the penalty math now lives on the margin account (static — no
        # instance state needed). Reached only for breached margin positions.
        penalty = SimulatedMarginAccount._liquidation_penalty(fee_rate, size, liq_price)

        # Quantize the liq price to the instrument price scale ONLY here, at the
        # FillEvent money boundary (Pitfall 5 — never mid-formula). The Universe
        # Instrument carries the per-symbol price scale; a stub Instrument without
        # one (unit tests) leaves the full-precision liq price untouched.
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
        # Pitfall 4: register in the SHARED mirror so the reconcile reaches FILLED.
        self._order_storage.add_order(order)

        order_event = OrderEvent.new_order_event(order)
        fill_event = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=fill_price, quantity=size, commission=penalty, time=bar_time)
        self.global_queue.put(fill_event)

        # IN-01: ``liq_price`` here is the QUANTIZED FillEvent price (``fill_price``,
        # rounded to the instrument price scale above) — that IS the price the
        # position settles at. The ``penalty`` field carries FULL precision
        # (``fee_rate × |size| × liq_price`` on the UNquantized formula price),
        # so a reader cross-checking the log against the hand-computed isolated
        # liq formula will see the rounded field but the full-precision penalty.
        # This is intentional: the logged value mirrors the emitted FillEvent.
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
        """BAR-route per-position liquidation breach check (D-02 placement).

        Runs AFTER the per-portfolio mark + P3 carry pass so the breach sees the
        carry-eroded equity. For each active portfolio, collect the deterministically
        sorted breached positions at this tick's close and force-close each. Fully
        oracle-dark: with the liquidation engine default-off (no locked margin /
        zero breaches) this loop finds nothing and emits no fills, so SMA_MACD
        stays byte-exact (D-11). No Universe / no order_storage wired (legacy
        mark-only callers) → no-op.

        IN-01: ``closes`` is the SAME per-ticker close map the caller already
        built for the mark — passed in (not re-derived from bar_events) so the
        mark price and the breach price are guaranteed identical.

        WR-05 (WR-02 re-review): ``marked_portfolio_ids`` is the set of
        portfolios that re-marked cleanly this tick. Only those are evaluated.
        Under the CURRENT error policy this gate NEVER fires: a failed mark in
        ``update_portfolios_market_value`` re-raises (it does not continue the
        per-portfolio loop), and the dispatch error seam operates at the
        granularity of the whole handler call — so in BOTH backtest and live
        modes either every active portfolio re-marked (and this pass runs with a
        full set) or the re-raise propagates out and this pass is never reached.
        ``marked_portfolio_ids`` is therefore always the full active set whenever
        the pass runs, and the ``not in`` skip below is never taken in
        production. The gate is kept purely as a DEFENSIVE guardrail: if a future
        per-portfolio continue-on-mark-failure policy is ever adopted for live
        mode, the partial-mark scenario would become reachable and this gate
        would already prevent the breach from reading a stale, partially-marked
        equity. ``None`` (legacy direct callers / unit tests) means "no gating"
        — evaluate every active portfolio.
        """
        if bar_time is None or self._universe is None or self._order_storage is None:
            return
        for portfolio in self.get_active_portfolios():
            if (marked_portfolio_ids is not None
                    and portfolio.portfolio_id not in marked_portfolio_ids):
                continue
            # ACCT-02: the liq math lives on the margin account. A spot account has
            # no margin/liquidation surface — skip it (byte-identical to the prior
            # wb==0 continue; oracle-dark since the golden run is all-spot).
            account = portfolio.account
            if not isinstance(account, SimulatedMarginAccount):
                continue
            for position in self._collect_breaches_over_prices(portfolio, closes, bar_time):
                wb, mmr, fee_rate = account._liq_inputs(position)
                liq_price = account._isolated_liq_price(position, wb, mmr)
                # WR-04 / CR-01 (LOAD-BEARING): the breach is DETECTED on the
                # bar close (``_is_breached``) but the position is SETTLED at
                # ``liq_price`` (the maintenance liq price), NOT at the breaching
                # close. With NO explicit ``min(loss + penalty, WB)`` clamp,
                # filling at the maintenance floor is THE mechanism that bounds
                # the realized loss near WB even on a gap-through (DEF-01-C). A
                # maintainer "fixing" this to settle at the realistic breach
                # close would silently re-open DEF-01-C with no clamp behind it —
                # see _liquidate_position's docstring (fill-at-liq-price is the
                # loss bound) and the gap-through regression
                # test_liquidation_fills_at_liq_price_on_far_gap_through.
                self._liquidate_position(portfolio, position, liq_price, fee_rate, bar_time)

    def _collect_breaches_over_prices(self, portfolio: Portfolio,
                                      closes: Dict[str, Decimal],
                                      bar_time: datetime) -> List[Position]:
        """Collect breached open positions across a per-ticker close map.

        The SINGLE breach predicate (WR-01): the live path
        (``_run_liquidation_pass``) and the unit tests both call this directly;
        there is no second collector to drift apart. Evaluates each position
        against ITS OWN ticker's
        close from ``closes`` — a position whose ticker is absent from this tick
        is skipped (stale mark, never a spurious breach). Returns the breached
        set sorted ``(ticker, open_time, position_id)``. The WR-02
        unwired-Universe guard fires only when there is a position to evaluate.
        """
        positions = portfolio.position_manager.get_all_positions()
        if not positions:
            return []
        # ACCT-02: a spot (SimulatedCashAccount) account has no margin/liquidation
        # surface — it is never breached (byte-identical to the prior wb==0
        # continue; oracle-dark). The margin math is delegated to the account.
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
    # Engine-thread drift compare + halt decision (05-04, D-15/D-01/D-04,
    # RECON-01/RECON-03). The venue is the arbiter of truth in live: the async
    # push writer only WRITES the VenueAccount cache (D-15 single-writer); the
    # per-symbol COMPARE + halt DECISION run HERE, on the engine thread, after a
    # fill drains (on_fill) and once per closed bar (BAR-route backstop). This
    # placement structurally defeats the phantom-drift race (Pitfall 8): the
    # engine tally is fully applied before the compare reads it, and no compare is
    # reachable from a spawned coroutine. Fully oracle-dark: a backtest/paper
    # portfolio holds a SimulatedAccount, so the compare skips cleanly and
    # SMA_MACD stays byte-exact.
    # ------------------------------------------------------------------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the composition-root freeze-in-place halt entrypoint (05-04, D-01/D-02).

        The live root wires ``LiveTradingSystem.halt`` here; the engine-thread
        drift compare calls it with a machine-readable reason (``"drift"``) on
        unexplained beyond-band drift. Backtest never wires it (no VenueAccount →
        no compare → the signal is never invoked).
        """
        self._halt_signal = halt_signal

    def set_drift_reconciler(
        self, reconciler: Callable[[Any, str, Decimal, Decimal], bool]
    ) -> None:
        """Inject the external-event reconciler for beyond-band drift (05-04, D-04).

        Answers whether a beyond-band per-symbol drift reconciles to a KNOWN venue
        event (an external cancel / external or hand-closed fill) — adopt-and-
        continue — versus genuinely unexplained drift that halts the engine.
        ``None`` → every beyond-band drift is treated as unexplained (the
        conservative money-first default; an external fill is NOT unexplained
        drift and is adopted only when the reconciler confirms it).
        """
        self._drift_reconciler = reconciler

    def _drift_precision(self, ticker: str) -> int:
        """Resolve the instrument quantity precision for the drift epsilon (D-01).

        Keys the ``is_within_single_unit_tolerance`` band off the SAME instrument
        precision ``core/money.py::quantize`` consumes
        (``Instrument.quantity_precision``), resolved via the injected Universe —
        never a hand-rolled per-symbol table. Falls back to ``8`` (the money-policy
        quantity default, ``1e-8``) when no Universe is wired or the instrument
        carries no precision.
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
        """Per-symbol engine-vs-venue drift compare on the ENGINE thread (D-15/D-01/D-04).

        Runs ONLY for a live ``VenueAccount`` portfolio — a backtest/paper
        ``SimulatedAccount`` portfolio has no venue truth, so this is a clean skip
        (oracle-dark). Compares the engine's fill-applied position quantity for
        ``ticker`` against the ``VenueAccount`` cached venue truth via
        ``is_within_single_unit_tolerance`` keyed to the instrument precision:

        * within the precision-epsilon band → adopt venue truth silently
          (auto-correct, D-01) — a no-op (the difference is last-digit dust);
        * D-04 spurious-halt band: on the IMMEDIATE on-fill compare, the just-applied
          fill may not yet be reflected in the not-yet-refreshed venue snapshot — the
          only skew the fill itself explains is exactly its own signed quantity (venue
          still at the pre-fill holding), so absorb that transient and defer to the
          periodic sweep (a first spot position-opening fill must NOT halt, V17-04);
        * beyond band AND reconciles to a known venue event → adopt-and-continue
          (D-04 — an external fill / hand-closed position is NOT unexplained drift);
        * beyond band AND unexplained → freeze-in-place halt the WHOLE engine
          (D-01/D-02) via the injected halt signal.

        Parameters
        ----------
        just_applied_fill_qty : Optional[Decimal]
            The SIGNED position delta of a fill JUST applied to the engine belief for
            ``ticker`` (``+qty`` BUY, ``-qty`` SELL), passed ONLY by the on-fill
            compare. ``None`` (the per-bar sweep + the session-start baseline guard)
            means no just-applied fill — every beyond-band skew is a candidate drift.
            The band is deliberately scoped to the on-fill transient: the periodic
            sweep (``None``) is the backstop that halts once the venue snapshot has
            had time to catch up, so a genuinely persistent divergence is never hidden.

        Single-writer safe (D-15): the async push writer only writes the
        VenueAccount cache; this compare + decision run on the engine thread AFTER
        the fill has drained — never from a spawned coroutine (Pitfall 8).
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
            return  # within the precision-epsilon band — adopt silently (D-01).

        # D-04 spurious-halt band (V17-04): a just-applied engine fill vs a
        # not-yet-refreshed venue snapshot. The venue snapshot legitimately lags the
        # fill it hasn't streamed yet, and the ONLY holding that lag explains is the
        # pre-fill one — ``engine_qty - just_applied_fill_qty``. When the venue truth
        # still matches that pre-fill holding within the band, the skew is exactly the
        # fill the venue hasn't caught up to (NOT drift), so absorb it and let the
        # periodic per-bar sweep (which passes no fill qty) be the backstop once the
        # snapshot refreshes. Only the on-fill compare supplies a fill qty; every
        # other caller falls straight through to the drift decision below.
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

        # Beyond band: adopt-and-continue if it maps to a known venue event (D-04).
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

        # Unexplained beyond-band drift → freeze-in-place halt the whole engine.
        # The compare declared the engine's own state untrustworthy; per D-02 the
        # halt does NOT auto-flatten/auto-cancel — it stops NEW submissions and
        # surfaces HALTED + a CRITICAL alert (wired by the composition root).
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
        """Periodic per-closed-bar drift backstop on the ENGINE thread (D-15).

        The on-bar backstop to the on-fill compare (D-15 — on fill immediate + on
        bar periodic): sweeps every active ``VenueAccount`` portfolio and compares
        each symbol's engine tally against venue truth across the union of
        engine-held and venue-reported tickers. Fully oracle-dark — a
        backtest/paper portfolio holds a ``SimulatedAccount`` and is skipped, so
        SMA_MACD stays byte-exact.
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
        """Record a venue trade id as settled in the bounded FIFO dedup ledger (CR-01).

        Evicts the oldest id once the ledger exceeds its cap so a long-running live
        session cannot grow it without bound. Re-inserting an already-present id
        refreshes its recency (moves it to the newest end).
        """
        self._settled_venue_trade_ids[venue_trade_id] = None
        self._settled_venue_trade_ids.move_to_end(venue_trade_id)
        while len(self._settled_venue_trade_ids) > self._max_settled_venue_trade_ids:
            self._settled_venue_trade_ids.popitem(last=False)

    def _persist_account_state(self, portfolio: Portfolio, updated_time: datetime) -> None:
        """Write-through the durable account-state scalar after a settled fill (F/U-11).

        The D-07 restore path (Plan 04) reads the cash scalar back on restart via
        ``load_account_state`` -> ``Account.restore_cash``; that read is only
        meaningful if ``save_account_state`` is actually written on the settlement
        path. This seam persists ``cash_balance`` (+ the derived accounting scalars
        the row carries) once the fill has settled, so a process restart restores
        the true balance rather than the construction-time initial cash.

        LIVE ONLY / oracle-dark: the in-memory backtest backend exposes no
        ``save_account_state`` (only ``CachedSqlPortfolioStateStorage`` does), so
        this is a clean ``getattr`` skip on the SMA_MACD path (no persistence, no
        new branch through the byte-exact run). ``updated_time`` is the fill's
        BUSINESS time (never wall-clock — determinism). ``peak_equity`` monotonically
        tracks the high-water equity across restarts by max-ing the current equity
        against any previously-persisted peak.
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
        """Restore live portfolio state + the durable dedup ledger on restart (D-07/D-08).

        The cross-restart arm the in-session A5 guard (Plan 03) does NOT cover: on a live
        restart ``_settled_venue_trade_ids`` starts EMPTY, so a venue trade re-delivered
        AFTER the restart (an OKX stream re-send, or the ``VenueReconciler`` adopting a
        downtime fill) would be booked a SECOND time. Per active portfolio this seam:

        1. **Drives ``state_storage.rehydrate(account)``** — the Task-1 restore path: open
           positions surface through the live ``PositionManager`` read cache and the
           persisted cash scalar is restored into the ``Account`` (D-07 / V17-05). The
           in-memory backtest backend exposes no ``rehydrate`` (oracle-dark) — skipped.
        2. **Seeds the settled-trade dedup ledger** from the durable
           ``transactions.venue_trade_id`` (the D-08 Layer-2 durable backstop), keyed
           ``f"{ticker}:{venue_trade_id}"`` (V17-12 collision-safe — the same numeric
           trade id on a DIFFERENT symbol still settles) via the bounded-FIFO
           ``_mark_venue_trade_settled``. A re-delivered ``(ticker, venue_trade_id)`` is
           then a no-op at the ``on_fill`` guard.

        3. **Restart-seeds the ORDER-mirror dedup ring symmetrically (D-22 / WR-05)**
           when an ``applied_trade_sink`` is supplied. The order-mirror
           ``ReconcileManager._applied_trade_keys`` also starts EMPTY on a restart, so
           the SAME ``f"{ticker}:{venue_trade_id}"`` keys collected for the portfolio
           arm are forwarded ONCE (single history pass, Pitfall 8 — ReconcileManager
           has no durable transaction store of its own) into the sink
           (``OrderManager.seed_applied_trades``). Both dedup arms then survive a
           restart symmetrically. The composition root wires the sink; the in-memory
           backtest path passes ``None`` (oracle-dark).

        Sequencing (composition-root, Plan 05): this MUST run BEFORE
        ``VenueReconciler.reconcile()`` so adoption diffs against restored state and the
        dedup ledger already knows every already-settled venue trade.

        Args:
            applied_trade_sink: Optional seed hook (``OrderManager.seed_applied_trades``)
                driven with the durable ``f"{ticker}:{venue_trade_id}"`` history so the
                order-mirror dedup ring is restart-seeded symmetrically (D-22). ``None``
                keeps the portfolio-arm-only behaviour (backtest / no order domain).
        """
        seeded_keys: List[str] = []
        for portfolio in self.get_active_portfolios():
            storage = portfolio.state_storage
            rehydrate_fn = getattr(storage, "rehydrate", None)
            if rehydrate_fn is None:
                # Backtest in-memory backend — nothing durable to restore (oracle-dark).
                continue
            # (a) D-07 restore: positions into the live managers' read cache + the
            # persisted cash scalar into the account.
            rehydrate_fn(portfolio.account)
            # (a2) WR-03 restore: re-seed the realised-PnL accumulator from the durable
            # account-state scalar. The accumulator is not one of the containers the
            # working-set cache carries, so without this a post-restart fill would
            # overwrite the durable realized_pnl column with a 0-based value. Guarded
            # exactly like the cash restore — only when durable state exists.
            load_account_state = getattr(storage, "load_account_state", None)
            if load_account_state is not None:
                account_state = load_account_state()
                if account_state is not None:
                    portfolio.position_manager.restore_realised_pnl(
                        account_state["realized_pnl"]
                    )
            # (b) D-08 Layer 2 durable backstop: seed the dedup ledger from the durable
            # transaction history, keyed f"{ticker}:{venue_trade_id}" (V17-12). None-keyed
            # backtest/simulated transactions carry no venue key and are skipped.
            for transaction in storage.get_transaction_history():
                venue_trade_id = getattr(transaction, "venue_trade_id", None)
                if venue_trade_id is None:
                    continue
                dedup_key = f"{transaction.ticker}:{venue_trade_id}"
                self._mark_venue_trade_settled(dedup_key)
                # D-22: collect the SAME key for the order-mirror ring seed so both
                # dedup arms read from ONE history pass (no second divergent read).
                seeded_keys.append(dedup_key)
        # D-22 (WR-05): restart-seed the order-mirror dedup ring symmetrically with
        # the portfolio ledger — one history pass feeds both arms. Skipped when no
        # sink is wired (backtest / no order domain — oracle-dark).
        if applied_trade_sink is not None and seeded_keys:
            applied_trade_sink(seeded_keys)

    # Fill event processing
    def on_fill(self, fill_event: FillEvent) -> None:
        """Process fill event for the appropriate portfolio.

        D-10 contract: returns ``None``; failures raise typed domain
        exceptions which propagate to the dispatch registry's
        ``_on_handler_error`` seam (backtest re-raise — the run stops loudly
        rather than producing corrupted numbers).
        """

        # W1-07: hoist the non-EXECUTED no-op guard ABOVE the operation-context /
        # correlation-id allocation. A non-EXECUTED fill is a pure no-op on
        # portfolio state, so it returns early WITHOUT entering _operation_context
        # (no correlation-id allocated, no active-operation tracked). The EXECUTED
        # path below is unchanged — it still enters the context and processes.
        if fill_event.status != FillStatus.EXECUTED:
            self.logger.debug(
                "Ignoring non-executed fill",
                status=str(fill_event.status),
                ticker=fill_event.ticker,
            )
            return

        # CR-01: cross-emitter fill-dedup at the settlement chokepoint. The venue
        # trade id is the ONE idempotency key shared by the two live emitters (the
        # OKX trade stream and the restart VenueReconciler); a fill whose
        # venue_trade_id was already settled is a duplicate booking of the SAME
        # economic venue trade — reject it BEFORE it mutates position/cash, so
        # 0.5 BTC is never booked as 1.0 (the CR-01 double-count). Backtest and
        # simulated fills carry venue_trade_id=None and SKIP the guard entirely —
        # the SMA_MACD oracle takes no new branch (oracle-dark).
        # D-08 Layer 2 (V17-12): key the dedup ledger by f"{ticker}:{venue_trade_id}",
        # NOT the raw id — the numeric venue tradeId is only unique per instrument, so
        # the SAME id on a different symbol is a DISTINCT economic trade and must still
        # settle (collision-safe). None-keyed backtest/simulated fills skip the guard.
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
                # Portfolio ids are native uuid.UUID (D-13/D-14); the dict is keyed
                # directly by the UUID — no int/str coercion (the integer scheme is gone).
                portfolio_id = fill_event.portfolio_id
                portfolio = self.get_portfolio(portfolio_id)

                # Portfolio handles its own validation and processing.
                # D-05 boundary map: events carry Side; Portfolio maps
                # Side -> TransactionType at its own boundary (the vocabularies
                # stay distinct — same precedent as FillStatus -> OrderStatus).
                # D-22: FillEvent money is Decimal end-to-end now — to_money is
                # an identity normalization at this domain entry (kept
                # deliberately: the ledger never trusts an unnormalized input).
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
                    # D-11 audit chain: the settlement record carries the
                    # originating fill's identity (fill -> order -> strategy).
                    fill_id=fill_event.fill_id,
                    # LEV-03 (Finding B): carry the admission-clamped EFFECTIVE
                    # leverage from the fill so the opening Transaction sets
                    # Position.leverage to the effective value — the position-life
                    # locked margin (aggregate_notional / leverage) then EQUALS
                    # the admission reservation (notional / effective_leverage).
                    # getattr default keeps spot fills byte-exact (oracle-dark).
                    leverage=getattr(fill_event, "leverage", Decimal("1")),
                    # CR-01: carry the venue trade id onto the durable settlement
                    # record (None for backtest/simulated fills — oracle-dark).
                    venue_trade_id=venue_trade_id,
                    # spot-base-fee-drift-halt: carry the venue fee currency so the
                    # spot settlement seam nets a base-denominated fee (OKX spot BUY)
                    # out of the position quantity instead of the quote cash leg.
                    # None for backtest/simulated fills (oracle-dark).
                    fee_currency=getattr(fill_event, "fee_currency", None),
                )

                # D-19 (WR-04): wrap the durable position upsert (driven by
                # transact_shares -> set_position) AND the cash-scalar account-state
                # upsert (_persist_account_state -> save_account_state) in ONE
                # transaction so a crash between them can never leave the durable
                # position one fill ahead of the durable cash (a torn restore, which
                # is PERMANENT on the SimulatedAccount path — no venue heals it). The
                # in-memory backtest backend exposes no fill_transaction, so this is a
                # clean getattr-skip on the SMA_MACD path (oracle-dark — the two
                # writes stay independent, but backtest never persists at all). LIVE
                # ONLY.
                fill_transaction = getattr(
                    portfolio.state_storage, "fill_transaction", None)
                if fill_transaction is not None:
                    with fill_transaction():
                        portfolio.transact_shares(transaction)
                        # F/U-11 (05.2-05): write-through the account-state scalar on
                        # the settlement path so the D-07 restore (rehydrate ->
                        # load_account_state -> Account.restore_cash) has a persisted
                        # balance to read on restart — now atomic with the position.
                        self._persist_account_state(portfolio, fill_event.time)
                else:
                    portfolio.transact_shares(transaction)
                    self._persist_account_state(portfolio, fill_event.time)

                # CR-01: record the venue trade id as settled ONLY after the durable
                # persist committed — a later re-delivery (stream re-send or the
                # restart reconciler) of the SAME venue trade is then a no-op at the
                # guard above. Placed AFTER the fill_transaction so a rolled-back
                # atomic persist (D-19) does not record a dedup key for a fill that
                # never durably landed. Recorded under the SAME
                # f"{ticker}:{venue_trade_id}" key the guard reads (D-08 Layer 2 /
                # V17-12 — symbol-scoped so the durable-ledger seed and the live mark
                # share one key space). None-keyed backtest/simulated fills never
                # record.
                if dedup_key is not None:
                    self._mark_venue_trade_settled(dedup_key)

                self.logger.debug(
                    "Fill event processed",
                    portfolio_id=portfolio_id,
                    ticker=fill_event.ticker,
                    correlation_id=correlation_id
                )

                # 05-04 (D-15): engine-thread per-symbol drift compare + halt
                # decision, immediately after the fill has drained (single-writer
                # safe — Pitfall 8). No-op for backtest/paper SimulatedAccount
                # portfolios, so the SMA_MACD oracle stays byte-exact.
                # D-04: pass the SIGNED just-applied fill delta (+qty BUY / -qty
                # SELL) so the spurious-halt band can absorb the "fill applied to the
                # engine but not yet in the venue snapshot" transient (V17-04) — a
                # first spot position-opening fill must not spuriously halt.
                # spot-base-fee-drift-halt: this MUST be the ACTUAL signed position
                # delta the settlement applied — NET of a base-denominated fee. The
                # settlement moves a base-fee BUY by (amount - base_fee), so passing
                # the RAW fill_event.quantity here left the absorber's pre-fill
                # reconstruction (engine_qty - just_applied_fill_qty) off by the fee,
                # spuriously tripping halt('drift') when the venue cache was still
                # pre-fill. transaction.position_quantity is (amount - base_fee) for a
                # base BUY and the raw amount otherwise (fee_currency None / quote fee
                # -> identity, so simulated fills yield +/- fill_event.quantity as
                # before — oracle-dark).
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
        
        # Convert bar events to price dictionary. The close is already
        # Decimal via the Bar struct (D-14); downstream position updates
        # enter via to_money (value-identity on Decimal input).
        prices = {}
        # CARRY-01/D-04: thread the bar's BUSINESS time down into the per-portfolio
        # mark + carry accrual — NEVER datetime.now(UTC) (a wall-clock stamp breaks
        # the determinism double-run gate). One BarEvent per tick on the daily grid;
        # the last event's time stamps the mark for this tick.
        bar_time = None
        for bar_event in bar_events:
            bar_time = bar_event.time
            for ticker, bar in bar_event.bars.items():
                prices[ticker] = bar.close

        # Update only active portfolios (each handles its own thread safety)
        active_portfolios = self.get_active_portfolios()

        # WR-05 (WR-02 re-review): record which portfolios re-marked cleanly
        # THIS tick and pass the set to the liquidation gate. Under the CURRENT
        # error policy this is always the FULL active set whenever the pass runs:
        # the except below RE-RAISES (it does not continue the loop), so a single
        # mark failure aborts the whole handler call in both backtest and live
        # modes (the dispatch error seam — _on_handler_error / live
        # _publish_and_continue — works at handler-call granularity, not
        # per-portfolio). Hence the pass either sees every portfolio re-marked,
        # or never runs at all; the gate's "skip a partially-marked portfolio"
        # branch never fires in production today. It is kept purely as a
        # DEFENSIVE guardrail for a FUTURE per-portfolio continue-on-mark-failure
        # policy: were the swallow ever moved INSIDE this loop, the partial-mark
        # scenario would become reachable and this set would already protect the
        # "breach sees carry-eroded equity" invariant (D-02).
        marked_portfolio_ids: set[Any] = set()

        for portfolio in active_portfolios:
            try:
                # CARRY-01/D-01: thread bar business time + the injected Universe
                # so each open short can resolve its Instrument.borrow_rate (the
                # same read pattern as maintenance_margin). _universe is None until
                # set_universe is wired; with no universe / rate-0 / no open shorts
                # the carry accrual is a no-op (SMA_MACD byte-exact under default-off).
                portfolio.update_market_value_of_portfolio(prices, bar_time, self._universe)
                marked_portfolio_ids.add(portfolio.portfolio_id)
            except Exception as e:
                # WR-08: a failed mark must NOT be swallowed. In a project whose
                # core value is "numbers you can trust", silently continuing
                # leaves the equity curve carrying stale position values that
                # the metrics/drawdown/oracle blocks then consume as if valid.
                # Mirror on_fill's D-10 fail-fast contract on this same dispatch
                # path: publish a PortfolioErrorEvent to the ERROR route, then
                # re-raise so the registry's _on_handler_error backtest policy
                # aborts the run instead of producing silently-wrong numbers.
                correlation_id = self._generate_correlation_id()
                self._publish_error_event(
                    e, "update_portfolios_market_value", correlation_id,
                    portfolio.portfolio_id)
                raise

        # LIQ-01/02/03 (D-02 placement): the per-position liquidation breach
        # check runs AFTER the per-portfolio mark + P3 carry pass so a breach
        # sees the carry-eroded equity. Oracle-dark on the spot path (no locked
        # margin / no Universe-or-storage wired → zero breaches, no fills).
        # WR-05 (WR-02 re-review): the marked-set gate is a defensive guardrail
        # that, under the current re-raise-on-mark-failure policy, always passes
        # the full active set (see the comment on marked_portfolio_ids above).
        # IN-01: reuse the SAME ``prices`` map the mark used so the breach price
        # and the mark price cannot diverge (no second pass over bar_events).
        self._run_liquidation_pass(prices, bar_time, marked_portfolio_ids)

        # 05-04 (D-15): per-closed-bar drift backstop on the engine thread — the
        # on-bar complement to the on-fill compare. Oracle-dark (SimulatedAccount
        # portfolios are skipped), so SMA_MACD stays byte-exact.
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
    
    # Configuration Management Methods
    #
    # M2-06 / D-01: the hot-reloadable registry/provider machinery was deleted; the
    # handler holds a single validated Pydantic ``PortfolioConfig`` (``config_data``).
    # ``update_config`` merges + re-validates via the model (Pydantic raises on bad
    # input); the per-portfolio variants were never wired on the backtest path.
    @staticmethod
    def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Thin delegate to the shared ``recursive_merge`` helper (WR-04).

        Kept as a static method so any existing caller keeps working; the
        recursion now lives in ``itrader/outils/dict_merge.py`` (promoted to a
        single shared helper — do NOT re-derive a fresh merge per handler).
        """
        return recursive_merge(base, updates)

    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update PortfolioHandler configuration at runtime (D-07/D-08/D-09).

        Canonical contract: recursive_merge -> model_validate -> atomic-swap, wrapping
        pydantic ``ValidationError`` (which also rejects unknown keys via
        ``extra="forbid"``) into ``ConfigurationError``. Returns ``None`` and
        RAISES on failure (no longer returns ``bool``). After the swap the
        cached ``max_portfolios`` is re-derived (Pitfall 1).
        """
        # WR-04: recursive-merge so a partial nested update (e.g. a single limits
        # field) preserves the other fields of that submodel instead of
        # replacing the whole submodel via a shallow `{**a, **b}`.
        merged = recursive_merge(self.config_data.model_dump(), updates)
        try:
            new_config = PortfolioConfig.model_validate(merged)
        except pydantic.ValidationError as e:
            raise ConfigurationError(reason=str(e)) from e
        self.config_data = new_config  # atomic GIL-safe reference swap (D-11)
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
        """Update configuration for a specific portfolio (not wired — D-live).

        Per-portfolio config mutation was a dormant provider method never wired on the
        backtest path; it is deferred with the live runtime-config surface (D-live).
        """
        self.logger.warning(
            "update_portfolio_config is not wired (deferred to D-live)",
            portfolio_id=portfolio_id,
        )
        return False

    def get_portfolio_config(self, portfolio_id: PortfolioId) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific portfolio (not wired — D-live)."""
        self.logger.warning(
            "get_portfolio_config is not wired (deferred to D-live)",
            portfolio_id=portfolio_id,
        )
        return None
    
    def __str__(self) -> str:
        return f"PortfolioHandler(portfolios={self.get_portfolio_count()})"
    
    def __repr__(self) -> str:
        return str(self)
