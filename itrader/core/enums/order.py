"""
Order-related enums for the trading system.

Contains enums for order types, status, and related mappings used
across the order management system.
"""

from enum import Enum

# Order Type Enum
OrderType = Enum("OrderType", "MARKET STOP LIMIT")

# Order Status Enum  
OrderStatus = Enum("OrderStatus", "PENDING PARTIALLY_FILLED FILLED CANCELLED REJECTED EXPIRED")

# Order Type Mapping
order_type_map = {
	"MARKET": OrderType.MARKET,
	"STOP": OrderType.STOP,
	"LIMIT": OrderType.LIMIT
}

# Order Status Mapping
order_status_map = {
	"PENDING": OrderStatus.PENDING,
	"PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
	"FILLED": OrderStatus.FILLED,
	"CANCELLED": OrderStatus.CANCELLED,
	"REJECTED": OrderStatus.REJECTED,
	"EXPIRED": OrderStatus.EXPIRED
}

# Valid state transitions for order lifecycle
VALID_ORDER_TRANSITIONS = {
	None: [OrderStatus.PENDING],  # Initial creation
	OrderStatus.PENDING: [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED],
	OrderStatus.PARTIALLY_FILLED: [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED],
	OrderStatus.FILLED: [],  # Terminal state
	OrderStatus.CANCELLED: [],  # Terminal state
	OrderStatus.REJECTED: [],  # Terminal state
	OrderStatus.EXPIRED: []   # Terminal state
}
