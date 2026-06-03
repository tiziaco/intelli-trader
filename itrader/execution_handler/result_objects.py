"""
Result objects for execution operations.

This module provides structured result objects for execution operations,
following the iTrader system's established patterns for data structures.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

from itrader.core.enums.execution import ExecutionStatus, ExecutionErrorCode, ExchangeConnectionStatus


@dataclass
class ExecutionResult:
    """
    Result of order execution with comprehensive details.
    
    Provides structured information about the execution attempt,
    including success status, execution details, and error information.
    """
    success: bool
    status: ExecutionStatus
    
    # Order identification
    order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None
    
    # Execution details
    executed_price: Optional[float] = None
    executed_quantity: Optional[float] = None
    remaining_quantity: Optional[float] = None
    commission: Optional[float] = None
    execution_time: Optional[datetime] = None
    
    # Error information
    error_code: Optional[ExecutionErrorCode] = None
    error_message: Optional[str] = None
    
    # Additional metadata
    metadata: Optional[Dict[str, Any]] = None
    
    @property
    def is_fully_filled(self) -> bool:
        """Check if order was completely filled."""
        return (self.remaining_quantity is not None and 
                self.remaining_quantity == 0.0 and 
                self.executed_quantity is not None and 
                self.executed_quantity > 0.0)
    
    @property
    def is_partially_filled(self) -> bool:
        """Check if order was partially filled."""
        return (self.executed_quantity is not None and 
                self.executed_quantity > 0.0 and 
                self.remaining_quantity is not None and 
                self.remaining_quantity > 0.0)
    
    @property
    def total_value(self) -> Optional[float]:
        """Calculate total value of executed trade."""
        if self.executed_price is not None and self.executed_quantity is not None:
            return self.executed_price * self.executed_quantity
        return None
    
    @property
    def net_value(self) -> Optional[float]:
        """Calculate net value after commission."""
        total = self.total_value
        if total is not None and self.commission is not None:
            return total - self.commission
        return total


@dataclass
class ConnectionResult:
    """
    Result of exchange connection operations.
    
    Provides information about connection attempts, including
    success status, connection state, and error details.
    """
    success: bool
    status: ExchangeConnectionStatus
    exchange_name: Optional[str] = None
    connection_time: Optional[datetime] = None
    error_code: Optional[ExecutionErrorCode] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self.status == ExchangeConnectionStatus.CONNECTED
    
    @property
    def connection_duration(self) -> Optional[float]:
        """Get connection duration in seconds."""
        if self.connection_time:
            return (datetime.now() - self.connection_time).total_seconds()
        return None


@dataclass
class HealthStatus:
    """
    Exchange health status information.
    
    Provides comprehensive health metrics for monitoring
    exchange connectivity and performance.
    """
    exchange_name: str
    connected: bool
    status: ExchangeConnectionStatus = ExchangeConnectionStatus.DISCONNECTED
    
    # Performance metrics
    last_ping_time: Optional[datetime] = None
    latency_ms: Optional[float] = None
    uptime_seconds: Optional[float] = None
    
    # Error tracking
    error_rate: Optional[float] = None
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    
    # Activity metrics
    orders_executed_today: int = 0
    orders_failed_today: int = 0
    total_volume_today: float = 0.0
    
    # Connection info
    connection_established: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    
    @property
    def is_healthy(self) -> bool:
        """Check if exchange is in healthy state."""
        return (self.connected and 
                self.status == ExchangeConnectionStatus.CONNECTED and
                (self.error_rate is None or self.error_rate < 0.1))
    
    @property
    def success_rate(self) -> Optional[float]:
        """Calculate order success rate."""
        total_orders = self.orders_executed_today + self.orders_failed_today
        if total_orders > 0:
            return self.orders_executed_today / total_orders
        return None
    
    @property
    def average_latency_category(self) -> str:
        """Categorize latency performance."""
        if self.latency_ms is None:
            return "unknown"
        elif self.latency_ms < 50:
            return "excellent"
        elif self.latency_ms < 100:
            return "good"
        elif self.latency_ms < 200:
            return "fair"
        else:
            return "poor"


@dataclass
class ValidationResult:
    """
    Result of order validation operations.
    
    Provides detailed information about validation checks
    performed before order execution.
    """
    is_valid: bool
    error_code: Optional[ExecutionErrorCode] = None
    error_message: Optional[str] = None
    failed_checks: Optional[list[str]] = None
    warnings: Optional[list[str]] = None
    validation_time: Optional[datetime] = None
    
    @property
    def has_warnings(self) -> bool:
        """Check if validation produced warnings."""
        return self.warnings is not None and len(self.warnings) > 0
    
    @property
    def check_count(self) -> int:
        """Get total number of failed checks."""
        return len(self.failed_checks) if self.failed_checks else 0
