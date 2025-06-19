"""
Position Manager for portfolio operations.
Handles position lifecycle, calculations, and risk management.
"""

import threading
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np

from itrader.portfolio_handler.position import Position, PositionSide
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.exceptions import (
    InvalidTransactionError,
    PositionCalculationError,
    ConcurrencyError
)
from itrader.logger import get_itrader_logger


class PositionEvent(Enum):
    OPENED = "OPENED"
    UPDATED = "UPDATED"
    CLOSED = "CLOSED"
    MERGED = "MERGED"
    SPLIT = "SPLIT"


@dataclass
class PositionMetrics:
    """Position performance and risk metrics."""
    position_id: int
    ticker: str
    total_pnl: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    return_pct: Decimal
    holding_period_days: int
    max_drawdown: Decimal
    win_rate: float
    sharpe_ratio: Optional[float] = None


class PositionManager:
    """
    Manages position lifecycle, calculations, and risk metrics.
    
    Features:
    - Thread-safe position operations
    - High-precision position calculations
    - Position risk metrics and analytics
    - Position limits and validation
    - Complete position audit trail
    - Support for partial fills and averaging
    - Position consolidation and splitting
    """
    
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self._lock = threading.RLock()
        self.logger = get_itrader_logger().bind(component="PositionManager")
        
        # Active positions by ticker
        self._positions: Dict[str, Position] = {}
        
        # Closed positions history
        self._closed_positions: List[Position] = []
        
        # Position limits and configuration
        self.max_positions_per_ticker = 1  # Max concurrent positions per ticker
        self.max_total_positions = 100     # Max total open positions
        self.max_position_value = Decimal('1000000.00')  # Max value per position
        self.min_position_value = Decimal('10.00')       # Min value per position
        
        # Risk management
        self.max_concentration_pct = Decimal('0.20')  # Max 20% of portfolio in one position
        
        # Calculation precision
        self.precision = Decimal('0.00000001')  # 8 decimal places for calculations
        self.tolerance = Decimal('0.00001')     # Tolerance for position closure
        
        self.logger.info("PositionManager initialized",
            max_positions=self.max_total_positions,
            max_position_value=str(self.max_position_value)
        )
    
    def process_position_update(self, transaction: Transaction) -> Position:
        """
        Process a transaction and update positions accordingly.
        
        Args:
            transaction: Transaction to process
            
        Returns:
            Position: The affected position
            
        Raises:
            InvalidTransactionError: If transaction is invalid for position
            PositionCalculationError: If calculations result in invalid state
        """
        with self._lock:
            ticker = transaction.ticker
            existing_position = self._positions.get(ticker)
            
            if existing_position:
                return self._update_existing_position(existing_position, transaction)
            else:
                return self._create_new_position(transaction)
    
    def _create_new_position(self, transaction: Transaction) -> Position:
        """Create a new position from a transaction."""
        
        # Validate position limits
        if len(self._positions) >= self.max_total_positions:
            raise InvalidTransactionError(
                f"Cannot create position: Maximum {self.max_total_positions} positions reached",
                {"current_positions": len(self._positions)}
            )
        
        # Validate position value
        position_value = Decimal(str(transaction.price * transaction.quantity))
        if position_value < self.min_position_value:
            raise InvalidTransactionError(
                f"Position value ${position_value} below minimum ${self.min_position_value}",
                {"position_value": float(position_value)}
            )
        
        if position_value > self.max_position_value:
            raise InvalidTransactionError(
                f"Position value ${position_value} exceeds maximum ${self.max_position_value}",
                {"position_value": float(position_value)}
            )
        
        # Create new position
        position = Position.open_position(transaction)
        self._positions[transaction.ticker] = position
        
        self.logger.info("New position created",
            position_id=position.id,
            ticker=transaction.ticker,
            side=position.side.name,
            quantity=str(position.net_quantity),
            avg_price=str(position.avg_price)
        )
        
        return position
    
    def _update_existing_position(self, position: Position, transaction: Transaction) -> Position:
        """Update an existing position with a new transaction."""
        
        # Store original values for validation
        original_quantity = position.net_quantity
        original_avg_price = position.avg_price
        
        # Update position with transaction
        position.update_position(transaction)
        
        # Check if position should be closed
        if self._should_close_position(position):
            self._close_position(position, transaction.price, transaction.time)
            return position
        
        # Validate position consistency after update
        self._validate_position_consistency(position, transaction)
        
        self.logger.debug("Position updated",
            position_id=position.id,
            ticker=transaction.ticker,
            old_quantity=str(original_quantity),
            new_quantity=str(position.net_quantity),
            old_avg_price=str(original_avg_price),
            new_avg_price=str(position.avg_price)
        )
        
        return position
    
    def _should_close_position(self, position: Position) -> bool:
        """Determine if a position should be closed based on quantity."""
        return abs(position.net_quantity) <= float(self.tolerance)
    
    def _close_position(self, position: Position, price: float, time: datetime):
        """Close a position and move it to closed positions."""
        
        position.close_position(price, time)
        
        # Move from active to closed positions
        if position.ticker in self._positions:
            del self._positions[position.ticker]
        
        self._closed_positions.append(position)
        
        self.logger.info("Position closed",
            position_id=position.id,
            ticker=position.ticker,
            final_pnl=str(position.total_pnl),
            holding_period=str(time - position.entry_date)
        )
    
    def _validate_position_consistency(self, position: Position, transaction: Transaction):
        """Validate position consistency after update."""
        
        # Check for calculation errors
        if position.net_quantity < 0 and abs(position.net_quantity) > 1e-6:
            if position.side == PositionSide.LONG:
                raise PositionCalculationError(
                    "Long position cannot have negative net quantity",
                    {"position_id": position.id, "net_quantity": position.net_quantity}
                )
        
        # Check average price reasonableness
        if position.avg_price <= 0:
            raise PositionCalculationError(
                "Position average price must be positive",
                {"position_id": position.id, "avg_price": position.avg_price}
            )
        
        # Check for extreme price changes (potential data error)
        price_change_ratio = abs(transaction.price - position.avg_price) / position.avg_price
        if price_change_ratio > 0.5:  # 50% price change
            self.logger.warning("Large price change detected",
                position_id=position.id,
                ticker=position.ticker,
                old_price=str(position.avg_price),
                new_price=str(transaction.price),
                change_ratio=str(price_change_ratio)
            )
    
    def update_position_market_values(self, price_data: Dict[str, float], timestamp: datetime):
        """Update current market values for all positions."""
        
        with self._lock:
            updated_count = 0
            
            for ticker, position in self._positions.items():
                if ticker in price_data:
                    current_price = price_data[ticker]
                    position.update_current_price_time(current_price, timestamp)
                    updated_count += 1
            
            self.logger.debug("Position market values updated",
                updated_positions=updated_count,
                total_positions=len(self._positions)
            )
    
    def get_position(self, ticker: str) -> Optional[Position]:
        """Get active position for a ticker."""
        with self._lock:
            return self._positions.get(ticker)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """Get all active positions."""
        with self._lock:
            return self._positions.copy()
    
    def get_closed_positions(self, limit: Optional[int] = None) -> List[Position]:
        """Get closed positions history."""
        with self._lock:
            if limit:
                return self._closed_positions[-limit:]
            return self._closed_positions.copy()
    
    def get_position_count(self) -> int:
        """Get count of active positions."""
        with self._lock:
            return len(self._positions)
    
    def get_total_market_value(self) -> Decimal:
        """Calculate total market value of all positions."""
        with self._lock:
            total_value = Decimal('0.00')
            
            for position in self._positions.values():
                market_value = Decimal(str(position.market_value))
                total_value += market_value
            
            return total_value
    
    def get_total_unrealized_pnl(self) -> Decimal:
        """Calculate total unrealized P&L across all positions."""
        with self._lock:
            total_pnl = Decimal('0.00')
            
            for position in self._positions.values():
                unrealized_pnl = Decimal(str(position.unrealised_pnl))
                total_pnl += unrealized_pnl
            
            return total_pnl
    
    def get_total_realized_pnl(self) -> Decimal:
        """Calculate total realized P&L from open and closed positions."""
        with self._lock:
            total_pnl = Decimal('0.00')
            
            # Add realized P&L from open positions
            for position in self._positions.values():
                realized_pnl = Decimal(str(position.realised_pnl))
                total_pnl += realized_pnl
            
            # Add realized P&L from closed positions
            for position in self._closed_positions:
                realized_pnl = Decimal(str(position.realised_pnl))
                total_pnl += realized_pnl
            
            return total_pnl
    
    def calculate_position_metrics(self, position_id: int) -> Optional[PositionMetrics]:
        """Calculate comprehensive metrics for a position."""
        
        # Find position (active or closed)
        position = None
        for p in self._positions.values():
            if p.id == position_id:
                position = p
                break
        
        if not position:
            for p in self._closed_positions:
                if p.id == position_id:
                    position = p
                    break
        
        if not position:
            return None
        
        # Calculate metrics
        total_pnl = Decimal(str(position.total_pnl))
        unrealized_pnl = Decimal(str(position.unrealised_pnl))
        realized_pnl = Decimal(str(position.realised_pnl))
        
        # Calculate return percentage
        initial_investment = Decimal(str(position.avg_price * abs(position.net_quantity)))
        return_pct = (total_pnl / initial_investment * 100) if initial_investment > 0 else Decimal('0.00')
        
        # Calculate holding period
        end_time = position.exit_date if position.exit_date else datetime.now()
        holding_period = (end_time - position.entry_date).days
        
        # Basic metrics (advanced metrics like Sharpe ratio would need price history)
        return PositionMetrics(
            position_id=position.id,
            ticker=position.ticker,
            total_pnl=total_pnl,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            return_pct=return_pct,
            holding_period_days=holding_period,
            max_drawdown=Decimal('0.00'),  # Would need historical data
            win_rate=0.0  # Would need multiple closed positions for same ticker
        )
    
    def get_portfolio_concentration(self) -> Dict[str, Decimal]:
        """Calculate position concentration as percentage of total portfolio value."""
        
        with self._lock:
            total_portfolio_value = self.get_total_market_value()
            
            if total_portfolio_value == 0:
                return {}
            
            concentrations = {}
            
            for ticker, position in self._positions.items():
                position_value = Decimal(str(position.market_value))
                concentration_pct = (position_value / total_portfolio_value) * 100
                concentrations[ticker] = concentration_pct
            
            return concentrations
    
    def validate_position_limits(self, transaction: Transaction) -> bool:
        """Validate if transaction would violate position limits."""
        
        with self._lock:
            # Check total position count
            if transaction.ticker not in self._positions and len(self._positions) >= self.max_total_positions:
                return False
            
            # Check position value limits
            if transaction.ticker in self._positions:
                position = self._positions[transaction.ticker]
                # Simulate the update to check new value
                new_quantity = position.net_quantity
                if transaction.type == TransactionType.BUY:
                    new_quantity += transaction.quantity
                else:
                    new_quantity -= transaction.quantity
                
                new_value = Decimal(str(abs(new_quantity) * transaction.price))
            else:
                new_value = Decimal(str(transaction.quantity * transaction.price))
            
            if new_value > self.max_position_value:
                return False
            
            return True
    
    def get_positions_summary(self) -> Dict:
        """Get comprehensive positions summary."""
        
        with self._lock:
            return {
                "active_positions": len(self._positions),
                "closed_positions": len(self._closed_positions),
                "total_market_value": float(self.get_total_market_value()),
                "total_unrealized_pnl": float(self.get_total_unrealized_pnl()),
                "total_realized_pnl": float(self.get_total_realized_pnl()),
                "concentration": {k: float(v) for k, v in self.get_portfolio_concentration().items()},
                "positions_by_side": self._get_positions_by_side()
            }
    
    def _get_positions_by_side(self) -> Dict[str, int]:
        """Get count of positions by side (LONG/SHORT)."""
        
        side_counts = {"LONG": 0, "SHORT": 0}
        
        for position in self._positions.values():
            side_counts[position.side.name] += 1
        
        return side_counts
    
    def close_all_positions(self, current_prices: Dict[str, float], timestamp: datetime) -> List[Position]:
        """Close all open positions (emergency function)."""
        
        with self._lock:
            closed_positions = []
            
            for ticker, position in list(self._positions.items()):
                if ticker in current_prices:
                    self._close_position(position, current_prices[ticker], timestamp)
                    closed_positions.append(position)
                else:
                    self.logger.warning("Cannot close position: no price data",
                        position_id=position.id,
                        ticker=ticker
                    )
            
            self.logger.warning("Emergency position closure executed",
                closed_count=len(closed_positions)
            )
            
            return closed_positions
