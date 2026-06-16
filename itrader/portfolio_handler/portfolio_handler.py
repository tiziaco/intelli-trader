"""
Enhanced PortfolioHandler with better separation of concerns.

D-19 single-writer contract: ALL portfolio state mutations happen on the
engine thread; queue.Queue is the thread boundary — other threads only put
events. Composite reads are consistent because nothing mutates concurrently.
Live cross-thread reads are a D-live design item.
"""
from queue import Queue
from datetime import datetime, UTC
from decimal import Decimal
from typing import Dict, Optional, Any, List, Generator, Union
from contextlib import contextmanager

from .portfolio import Portfolio
from .position import Position
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
from itrader.events_handler.events import OrderEvent
from itrader.core.portfolio_read_model import PositionView
from itrader.core.money import to_money, quantize
from itrader.portfolio_handler.transaction import Transaction
from itrader.events_handler.events import BarEvent, FillEvent, PortfolioUpdateEvent, PortfolioErrorEvent
from itrader.config import PortfolioConfig, get_portfolio_preset, deep_merge
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
    
    def __init__(self, global_queue: "Queue[Any]", config_dir: str = "settings", environment: str = "default") -> None:
        self.global_queue: "Queue[Any]" = global_queue
        self.current_time: Any = 0
        
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
    def add_portfolio(self, user_id: int, name: str, exchange: str, cash: float, portfolio_config: Optional[PortfolioConfig] = None) -> PortfolioId:
        """Create a new portfolio with enhanced capabilities."""
        
        with self._operation_context("add_portfolio") as correlation_id:
            try:
                # Global validations
                if cash <= 0:
                    raise PortfolioValidationError(0, "initial_cash", "Initial cash must be positive")
                
                if not name.strip():
                    raise PortfolioValidationError(0, "name", "Portfolio name cannot be empty")
                
                # Check global limits
                if len(self._portfolios) >= self.max_portfolios:
                    raise PortfolioConfigurationError("max_portfolios", self.max_portfolios, "maximum portfolios limit reached")
                
                # Create portfolio instance
                portfolio = Portfolio(
                    user_id=user_id,
                    name=name,
                    exchange=exchange,
                    cash=to_money(cash),
                    time=datetime.now(UTC),
                    config=portfolio_config
                )
                
                # Store portfolio
                self._portfolios[portfolio.portfolio_id] = portfolio
                
                self.logger.info(
                    "Portfolio created successfully",
                    portfolio_id=portfolio.portfolio_id,
                    user_id=user_id,
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
        return self.get_portfolio(portfolio_id).cash_manager.available_balance

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
        """Reserve cash for a pending order (per-reference, full precision — OQ4)."""
        self.get_portfolio(portfolio_id).cash_manager.reserve_cash(
            amount, "order cash reservation", str(order_id)
        )

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Release the cash reservation keyed by an order id (idempotent)."""
        self.get_portfolio(portfolio_id).cash_manager.release_reservation(str(order_id))

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on (admission metadata, OQ1)."""
        exchange: str = self.get_portfolio(portfolio_id).exchange
        return exchange

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
            portfolio.cash_manager.balance
            + portfolio.position_manager.get_total_market_value()
        )

    def set_universe(self, universe: Any) -> None:
        """Inject the Universe read-model used to resolve per-symbol Instruments.

        Plan 02-05 (D-13): called by the runner at its Trap-4 wiring point (after
        the Universe is built, mirroring the exchange/order-domain set_universe
        seam from Plan 02-03). Stores the reference; maintenance_margin reads
        ``universe.instrument(ticker).maintenance_margin_rate`` per open position.
        """
        self._universe = universe

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

        ``maintenance_margin = Σ (Instrument.maintenance_margin_rate × |size| ×
        current_price)`` over the portfolio's OPEN positions, resolving each
        ticker's Instrument via the injected Universe. Decimal end-to-end
        (RESEARCH Pitfall 8 — Position.net_quantity is already |size| Decimal and
        current_price is Decimal; the rate is Decimal). NOT a stored Position
        field (D-13a). With no open positions the sum is ``Decimal("0")``.
        """
        portfolio = self.get_portfolio(portfolio_id)
        total = Decimal("0")
        positions = portfolio.position_manager.get_all_positions()
        # WR-02 (T-03-17): the per-symbol Instrument read dereferences the
        # injected Universe. If positions exist but the Universe was never wired
        # (``set_universe`` not called), fail LOUD with a context-rich StateError
        # — never a bare ``AttributeError: 'NoneType' has no attribute
        # 'instrument'``. With NO open positions the read is never reached, so an
        # unwired Universe is benign and the sum is ``Decimal("0")``.
        if positions and self._universe is None:
            raise StateError(
                portfolio_id,
                "universe-unwired",
                required_state="universe-wired (call set_universe)",
                operation="maintenance_margin",
            )
        for position in positions.values():
            instrument = self._universe.instrument(position.ticker)
            total += (
                instrument.maintenance_margin_rate
                * abs(position.net_quantity)
                * position.current_price
            )
        return total

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        """Return ``total_equity() / maintenance_margin`` (D-12/D-13).

        Mark-to-market equity over maintenance margin — the figure a UI/live layer
        (deferred N+4) reads for margin-call warnings. Reads HONESTLY even when
        breached: an equity drop below maintenance returns a ratio < 1 with NO
        clamp (D-16 — the honest sub-1 reading is the P4 liquidation input). When
        maintenance margin is ``Decimal("0")`` (no open positions, no margin
        required) it returns the deterministic sentinel ``Decimal("0")`` rather
        than dividing by zero.
        """
        maintenance = self.maintenance_margin(portfolio_id)
        if maintenance == Decimal("0"):
            return Decimal("0")
        return self.total_equity(portfolio_id) / maintenance

    # ------------------------------------------------------------------
    # Isolated-margin liquidation engine (LIQ-01/02, D-01-CORR/D-03-CORR/D-04/
    # D-05/D-07). The BAR-route per-position breach check runs AFTER the per-
    # portfolio mark + P3 carry pass (D-02 placement — breach sees carry-eroded
    # equity). The math is Decimal end-to-end (Pitfall 5 — NEVER Decimal(float));
    # the liq price is quantized to the instrument price scale ONLY at the
    # FillEvent boundary in the mint step, never mid-formula.
    # ------------------------------------------------------------------

    @staticmethod
    def _isolated_liq_price(position: Position, wb: Decimal, mmr: Decimal) -> Decimal:
        """Corrected isolated liquidation price (D-01-CORR — HAND-VERIFIED).

        ``margin_per_unit = wb / |size|`` where ``wb`` is the position-keyed
        locked isolated margin (``CashManager.get_locked_margin_for``) and
        ``|size| = abs(net_quantity)``. With ``entry = avg_price``:

        * LONG : ``(entry − margin_per_unit) / (1 − mmr)``
        * SHORT: ``(entry + margin_per_unit) / (1 + mmr)``

        The corrected formula (NOT the literal CONTEXT D-01 string, which yields
        a negative price). For Entry=100, |size|=200, WB=4000, MMR=0.01 it gives
        the long 80.808080… / short 118.811881… worked numbers. Full Decimal
        precision is carried; quantization happens only at the FillEvent price
        boundary (the mint step).
        """
        size = abs(position.net_quantity)
        entry = position.avg_price
        margin_per_unit = wb / size
        if position.side == PositionSide.LONG:
            return (entry - margin_per_unit) / (Decimal("1") - mmr)
        return (entry + margin_per_unit) / (Decimal("1") + mmr)

    @staticmethod
    def _is_breached(position: Position, close: Decimal, liq_price: Decimal) -> bool:
        """Return True when the bar close crosses the liquidation price.

        LONG breaches when ``close <= liq`` (price fell into the maintenance
        floor); SHORT breaches when ``close >= liq`` (price rose into it). The
        liq price is computed once by the breach pass and passed in.
        """
        if position.side == PositionSide.LONG:
            return close <= liq_price
        return close >= liq_price

    @staticmethod
    def _liquidation_penalty(fee_rate: Decimal, size: Decimal, liq_price: Decimal) -> Decimal:
        """Forced-close penalty = ``fee_rate × |size| × liq_price`` (D-05/LIQ-02).

        Rides ``FillEvent.commission`` (no new FillStatus). Full Decimal
        precision; defaults to ``Decimal("0")`` for a 0 fee rate (oracle-dark).
        """
        return fee_rate * size * liq_price

    def _liq_inputs(self, portfolio: Portfolio, position: Position) -> "tuple[Decimal, Decimal, Decimal]":
        """Resolve ``(wb, mmr, fee_rate)`` for a position from cash + Universe.

        ``wb`` = the position-keyed locked isolated margin
        (``get_locked_margin_for(str(position.id))``); ``mmr`` =
        ``Instrument.maintenance_margin_rate``; ``fee_rate`` resolved
        Instrument-first (``instrument.liquidation_fee_rate``) — the Universe
        Instrument is the single per-symbol source of truth (the
        ``TradingRules`` config fallback is consulted by the caller only when no
        Universe Instrument carries the rate; here the Instrument always does
        since it defaults to ``Decimal("0")``).
        """
        wb = portfolio.cash_manager.get_locked_margin_for(str(position.id))
        instrument = self._universe.instrument(position.ticker)
        mmr = instrument.maintenance_margin_rate
        fee_rate = instrument.liquidation_fee_rate
        return wb, mmr, fee_rate

    def _collect_breaches(self, portfolio: Portfolio, close: Decimal,
                          bar_time: datetime) -> List[Position]:
        """Collect open positions breaching against a SINGLE shared close.

        WR-01: thin adapter — builds a ``{ticker: close}`` map keyed on every
        open position's ticker (all marked at the same ``close``) and delegates
        to ``_collect_breaches_over_prices`` so there is ONE breach predicate.
        Avoids the maintainability hazard of two near-identical collectors
        drifting apart (a fix to the predicate in one but not the other).
        """
        positions = portfolio.position_manager.get_all_positions()
        closes = {ticker: close for ticker in positions}
        return self._collect_breaches_over_prices(portfolio, closes, bar_time)

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
        penalty = self._liquidation_penalty(fee_rate, size, liq_price)

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

        WR-05: ``marked_portfolio_ids`` is the set of portfolios that re-marked
        cleanly this tick. Only those are evaluated — a portfolio whose mark
        raised mid-loop (possible only on the LIVE _publish_and_continue path;
        the backtest re-raise aborts before this pass) is SKIPPED so the breach
        never reads its stale, partially-marked equity. ``None`` (legacy direct
        callers / unit tests) means "no gating" — evaluate every active portfolio.
        """
        if bar_time is None or self._universe is None or self._order_storage is None:
            return
        for portfolio in self.get_active_portfolios():
            if (marked_portfolio_ids is not None
                    and portfolio.portfolio_id not in marked_portfolio_ids):
                continue
            for position in self._collect_breaches_over_prices(portfolio, closes, bar_time):
                wb, mmr, fee_rate = self._liq_inputs(portfolio, position)
                liq_price = self._isolated_liq_price(position, wb, mmr)
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

        The SINGLE breach predicate (WR-01): ``_collect_breaches`` is a thin
        adapter over this. Evaluates each position against ITS OWN ticker's
        close from ``closes`` — a position whose ticker is absent from this tick
        is skipped (stale mark, never a spurious breach). Returns the breached
        set sorted ``(ticker, open_time, position_id)``. The WR-02
        unwired-Universe guard fires only when there is a position to evaluate.
        """
        positions = portfolio.position_manager.get_all_positions()
        if not positions:
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
            wb, mmr, _fee_rate = self._liq_inputs(portfolio, position)
            if wb <= Decimal("0"):
                continue
            liq_price = self._isolated_liq_price(position, wb, mmr)
            if self._is_breached(position, close, liq_price):
                breached.append(position)
        breached.sort(key=lambda p: (p.ticker, p.entry_date, str(p.id)))
        return breached

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
                )

                portfolio.transact_shares(transaction)

                self.logger.debug(
                    "Fill event processed",
                    portfolio_id=portfolio_id,
                    ticker=fill_event.ticker,
                    correlation_id=correlation_id
                )

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

        # WR-05: record which portfolios re-marked cleanly THIS tick so the
        # liquidation pass never evaluates a breach against a stale mark. In the
        # backtest path the re-raise below aborts the run before the pass runs
        # (so all-or-nothing); in the LIVE path (_publish_and_continue swallows
        # at the dispatch boundary) a portfolio whose mark raised mid-loop is
        # SKIPPED by the pass — the "breach sees carry-eroded equity" invariant
        # (D-02) only holds for a portfolio that actually re-marked this tick.
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
        # WR-05: only portfolios that re-marked cleanly this tick are eligible.
        # IN-01: reuse the SAME ``prices`` map the mark used so the breach price
        # and the mark price cannot diverge (no second pass over bar_events).
        self._run_liquidation_pass(prices, bar_time, marked_portfolio_ids)

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
        """Thin delegate to the shared ``config.deep_merge`` helper (WR-04).

        Kept as a static method so any existing caller keeps working; the
        recursion now lives in ``itrader/config/merge.py`` (promoted to a single
        shared helper — do NOT re-derive a fresh merge per handler).
        """
        return deep_merge(base, updates)

    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update PortfolioHandler configuration at runtime (D-07/D-08/D-09).

        Canonical contract: deep_merge -> model_validate -> atomic-swap, wrapping
        pydantic ``ValidationError`` (which also rejects unknown keys via
        ``extra="forbid"``) into ``ConfigurationError``. Returns ``None`` and
        RAISES on failure (no longer returns ``bool``). After the swap the
        cached ``max_portfolios`` is re-derived (Pitfall 1).
        """
        # WR-04: deep-merge so a partial nested update (e.g. a single limits
        # field) preserves the other fields of that submodel instead of
        # replacing the whole submodel via a shallow `{**a, **b}`.
        merged = deep_merge(self.config_data.model_dump(), updates)
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
