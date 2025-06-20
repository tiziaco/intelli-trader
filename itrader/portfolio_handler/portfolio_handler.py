"""
Enhanced PortfolioHandler with better separation of concerns.
"""
import threading
import uuid
from queue import Queue
from datetime import datetime, UTC
from typing import Dict, Optional, Set, Any, List, Generator, Union
from decimal import Decimal
from dataclasses import dataclass
from contextlib import contextmanager

from readerwriterlock import rwlock

from .portfolio import Portfolio, PortfolioConfig, PortfolioState
from .exceptions import (
    PortfolioHandlerError, PortfolioNotFoundError, InvalidPortfolioOperationError,
    PortfolioStateError, PortfolioValidationError, PortfolioConfigurationError
)
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.events_handler.event import BarEvent, FillEvent, PortfolioUpdateEvent, PortfolioErrorEvent
from itrader.config import (
    get_config_registry, get_portfolio_handler_config, PortfolioHandlerConfig
)

from itrader import config, idgen
from itrader.logger import get_itrader_logger


class PortfolioHandler:
    """
    Enhanced PortfolioHandler with better separation of concerns.
    
    This handler focuses on:
    - Global system configuration via ConfigRegistry
    - Portfolio lifecycle management (creation, deletion)
    - System-wide monitoring and health checks
    - Event publishing coordination
    - Global thread safety for collection operations
    - Runtime configuration updates via API
    
    Individual portfolios manage their own:
    - State (ACTIVE, INACTIVE, ARCHIVED)
    - Configuration (limits, validation)
    - Thread safety (per-portfolio locks)
    - Health monitoring
    """
    
    def __init__(self, global_queue: Queue, config_dir: str = "config", environment: str = "default"):
        self.global_queue: Queue = global_queue
        self.current_time = 0
        
        # Initialize configuration registry
        self.config_registry = get_config_registry(config_dir, environment)
        self.config = get_portfolio_handler_config()
        
        # Portfolio storage - now just stores portfolio instances
        self._portfolios: Dict[int, Portfolio] = {}
        
        # Global collection lock (lightweight, just for adding/removing portfolios)
        self._portfolios_lock = rwlock.RWLockFair()
        
        # Operation tracking for global monitoring
        self._active_operations: Set[str] = set()
        self._operations_lock = threading.Lock()
        
        # Global logger
        self.logger = get_itrader_logger().bind(component="PortfolioHandler")
        
        self.logger.info(
            "Enhanced PortfolioHandler initialized",
            max_portfolios=self.config.limits.max_portfolios_total,
            max_concurrent_ops=self.config.limits.max_concurrent_operations
        )
    
    def _generate_correlation_id(self) -> str:
        """Generate unique correlation ID for operation tracking."""
        return f"ph_{uuid.uuid4().hex[:12]}"
    
    def _publish_error_event(self, error: Exception, operation: str, correlation_id: str, portfolio_id: Optional[int] = None):
        """Publish error event if enabled."""
        if not self.config.events.publish_error_events:
            return
        
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
    def _operation_context(self, operation_name: str) -> Generator[str, None, None]:
        """Context manager for operation tracking."""
        correlation_id = self._generate_correlation_id()
        
        # Check concurrent operation limits
        with self._operations_lock:
            if len(self._active_operations) >= self.config.limits.max_concurrent_operations:
                raise PortfolioHandlerError(f"Maximum concurrent operations limit reached: {self.config.limits.max_concurrent_operations}")
            self._active_operations.add(correlation_id)
        
        try:
            yield correlation_id
        finally:
            with self._operations_lock:
                self._active_operations.discard(correlation_id)
    
    # Main portfolio management methods (keeping same names for compatibility)
    def add_portfolio(self, user_id: int, name: str, exchange: str, cash: float, portfolio_config: Optional[PortfolioConfig] = None) -> int:
        """Create a new portfolio with enhanced capabilities."""
        
        with self._operation_context("add_portfolio") as correlation_id:
            try:
                # Global validations
                if cash <= 0:
                    raise PortfolioValidationError(0, "initial_cash", "Initial cash must be positive")
                
                if not name.strip():
                    raise PortfolioValidationError(0, "name", "Portfolio name cannot be empty")
                
                # Check global limits
                with self._portfolios_lock.gen_rlock():
                    if len(self._portfolios) >= self.config.limits.max_portfolios_total:
                        raise PortfolioConfigurationError(f"Maximum portfolios limit reached: {self.config.limits.max_portfolios_total}")
                
                # Create portfolio instance
                portfolio = Portfolio(
                    user_id=user_id,
                    name=name,
                    exchange=exchange,
                    cash=cash,
                    time=datetime.now(UTC),
                    config=portfolio_config
                )
                
                # Store portfolio
                with self._portfolios_lock.gen_wlock():
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
    
    def get_portfolio(self, portfolio_id: int) -> Portfolio:
        """Get portfolio instance."""
        with self._portfolios_lock.gen_rlock():
            if portfolio_id not in self._portfolios:
                raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
            return self._portfolios[portfolio_id]
    
    def delete_portfolio(self, portfolio_id: int, force: bool = False) -> bool:
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
                with self._portfolios_lock.gen_wlock():
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
        with self._portfolios_lock.gen_rlock():
            return [p for p in self._portfolios.values() if p.is_active()]
    
    def get_portfolios_by_state(self, state: PortfolioState) -> List[Portfolio]:
        """Get portfolios by state."""
        with self._portfolios_lock.gen_rlock():
            return [p for p in self._portfolios.values() if p.state == state]
    
    def get_portfolio_count(self) -> int:
        """Get total portfolio count."""
        with self._portfolios_lock.gen_rlock():
            return len(self._portfolios)
    
    # Fill event processing
    def on_fill(self, fill_event: FillEvent) -> bool:
        """Process fill event for the appropriate portfolio."""
        
        with self._operation_context("on_fill") as correlation_id:
            try:
                portfolio_id = int(fill_event.portfolio_id)  # Convert string to int
                portfolio = self.get_portfolio(portfolio_id)
                
                # Portfolio handles its own validation and processing
                transaction_type = TransactionType.BUY if fill_event.action == "BUY" else TransactionType.SELL
                transaction = Transaction(
                    time=fill_event.time,
                    type=transaction_type,
                    ticker=fill_event.ticker,
                    price=fill_event.price,
                    quantity=fill_event.quantity,
                    commission=fill_event.commission,
                    portfolio_id=portfolio_id,
                    id=idgen.generate_transaction_id()
                )
                
                result = portfolio.transact_shares(transaction)
                
                self.logger.debug(
                    "Fill event processed",
                    portfolio_id=portfolio_id,
                    ticker=fill_event.ticker,
                    correlation_id=correlation_id
                )
                
                return result
                
            except Exception as e:
                portfolio_id_int = None
                try:
                    portfolio_id_int = int(fill_event.portfolio_id)
                except (ValueError, AttributeError):
                    pass
                self._publish_error_event(e, "on_fill", correlation_id, portfolio_id_int)
                raise
    
    # Market data updates
    def update_portfolios_market_value(self, bar_events: Union[BarEvent, List[BarEvent]]) -> None:
        """Update market values for all active portfolios."""
        
        # Normalize input to always be a list
        if isinstance(bar_events, BarEvent):
            bar_events = [bar_events]
        
        # Convert bar events to price dictionary
        prices = {}
        for bar_event in bar_events:
            for ticker in bar_event.bars.keys():
                prices[ticker] = bar_event.get_last_close(ticker)
        
        # Update only active portfolios (each handles its own thread safety)
        active_portfolios = self.get_active_portfolios()
        
        for portfolio in active_portfolios:
            try:
                portfolio.update_market_value_of_portfolio(prices)
            except Exception as e:
                self.logger.warning(
                    "Failed to update portfolio market value",
                    portfolio_id=portfolio.portfolio_id,
                    error=str(e)
                )
    
    def update_portfolios_market(self, bar_event: BarEvent) -> None:
        """Update market values for all portfolios (backward compatible method)."""
        # Extract prices from bar event
        prices = {}
        if hasattr(bar_event, 'bars'):
            for ticker, bar in bar_event.bars.items():
                prices[ticker] = bar.close_price
        else:
            # Single ticker bar event
            prices[bar_event.ticker] = bar_event.close_price
        
        # Update all active portfolios
        active_portfolios = self.get_active_portfolios()
        
        for portfolio in active_portfolios:
            try:
                portfolio.update_market_value_of_portfolio(prices)
            except Exception as e:
                self.logger.warning(
                    "Failed to update portfolio market value",
                    portfolio_id=portfolio.portfolio_id,
                    error=str(e)
                )
    
    # Global health and monitoring
    def get_global_health_report(self) -> Dict[str, Any]:
        """Generate global health report."""
        with self._portfolios_lock.gen_rlock():
            portfolios = list(self._portfolios.values())
        
        # Analyze portfolios without holding the global lock
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
            'active_operations': len(self._active_operations),
            'global_limits': {
                'max_portfolios': self.config.limits.max_portfolios_total,
                'max_concurrent_operations': self.config.limits.max_concurrent_operations
            }
        }
    
    # Export and serialization
    def portfolios_to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Convert all portfolios to dictionary format."""
        with self._portfolios_lock.gen_rlock():
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
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """Update PortfolioHandler configuration at runtime."""
        try:
            self.config_registry.update_module_config("PortfolioHandler", updates)
            # Refresh local config
            self.config = get_portfolio_handler_config()
            self.logger.info("Configuration updated successfully", updates=updates)
            return True
        except Exception as e:
            self.logger.error("Failed to update configuration", error=str(e))
            return False
    
    def get_config(self) -> PortfolioHandlerConfig:
        """Get current PortfolioHandler configuration."""
        return self.config
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate PortfolioHandler configuration."""
        try:
            return self.config_registry.validate_module_config("PortfolioHandler", config)
        except Exception as e:
            self.logger.error("Configuration validation failed", error=str(e))
            return False
    
    def rollback_config(self, steps: int = 1) -> bool:
        """Rollback PortfolioHandler configuration."""
        try:
            success = self.config_registry.rollback_module_config("PortfolioHandler", steps)
            if success:
                # Refresh local config
                self.config = get_portfolio_handler_config()
                self.logger.info("Configuration rolled back successfully", steps=steps)
            return success
        except Exception as e:
            self.logger.error("Failed to rollback configuration", error=str(e))
            return False
    
    def update_portfolio_config(self, portfolio_id: int, updates: Dict[str, Any]) -> bool:
        """Update configuration for a specific portfolio."""
        try:
            manager_key = f"Portfolio_{portfolio_id}"
            self.config_registry.update_module_config(manager_key, updates)
            self.logger.info("Portfolio configuration updated", portfolio_id=portfolio_id, updates=updates)
            return True
        except Exception as e:
            self.logger.error("Failed to update portfolio configuration", portfolio_id=portfolio_id, error=str(e))
            return False
    
    def get_portfolio_config(self, portfolio_id: int) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific portfolio."""
        try:
            manager_key = f"Portfolio_{portfolio_id}"
            return self.config_registry.get_module_config(manager_key)
        except Exception as e:
            self.logger.error("Failed to get portfolio configuration", portfolio_id=portfolio_id, error=str(e))
            return None
    
    def __str__(self):
        return f"PortfolioHandler(portfolios={self.get_portfolio_count()})"
    
    def __repr__(self):
        return str(self)
