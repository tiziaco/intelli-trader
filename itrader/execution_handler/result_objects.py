"""
Connection/health/preflight metadata DTOs for the execution layer.

D-21: events are the ONLY execution output — ``ExecutionResult`` and the
immediate ``execute_order`` path were deleted (D-13 single matching
path); every execution outcome (EXECUTED, REFUSED, CANCELLED) travels as
a FillEvent on the global queue. The dataclasses here are NOT execution
results: they carry connection-lifecycle, health-monitoring and
pre-trade-check metadata returned synchronously by exchange management
methods.

All DTOs are frozen/slots (construct-complete, no post-init mutation)
and money-denominated fields are Decimal (locked money decision).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from itrader.core.enums.execution import ExecutionErrorCode, ExchangeConnectionStatus


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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

    # Activity metrics (volume is money-denominated -> Decimal)
    orders_executed_today: int = 0
    orders_failed_today: int = 0
    total_volume_today: Decimal = Decimal("0")

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


@dataclass(frozen=True, slots=True)
class OrderPreflightResult:
    """
    Result of the exchange's pre-trade order checks (OQ3 rename).

    Formerly ``ValidationResult`` — renamed to resolve the name collision
    with the order-domain ``order_validator.ValidationResult`` (#39).
    Carries detailed information about preflight checks performed before
    order execution; rejection itself still travels as FillEvent(REFUSED).
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
