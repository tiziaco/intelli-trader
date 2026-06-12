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
from itrader.core.exceptions import (
    PortfolioNotFoundError, InvalidPortfolioOperationError,
    PortfolioStateError, PortfolioValidationError, PortfolioConfigurationError
)
from itrader.core.enums import PortfolioState, TransactionType, FillStatus, Side
from itrader.core.ids import OrderId, PortfolioId, TransactionId, CorrelationId
from itrader.core.portfolio_read_model import PositionView
from itrader.core.money import to_money
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
    # The order domain reads portfolio state through these six members ONLY
    # (itrader/core/portfolio_read_model.py). No inheritance, no adapter:
    # PortfolioHandler satisfies the runtime_checkable Protocol structurally.
    # D-15: live Position objects never cross the boundary — get_position
    # returns a frozen PositionView snapshot (None when flat).

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
        for bar_event in bar_events:
            for ticker, bar in bar_event.bars.items():
                prices[ticker] = bar.close
        
        # Update only active portfolios (each handles its own thread safety)
        active_portfolios = self.get_active_portfolios()

        for portfolio in active_portfolios:
            try:
                portfolio.update_market_value_of_portfolio(prices)
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

    def rollback_config(self, steps: int = 1) -> bool:
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
