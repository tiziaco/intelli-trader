"""
Core identity types for the iTrader system.

Ten ``NewType`` aliases over the stdlib ``uuid.UUID`` (D-12). Each alias is a
distinct nominal type to ``mypy`` (so an ``OrderId`` cannot be silently passed
where a ``PortfolioId`` is expected) but is exactly ``uuid.UUID`` at runtime —
``OrderId(some_uuid)`` returns ``some_uuid`` unchanged.

There is deliberately NO discriminator field or type-prefix encoding (D-13): the
entity type is implicit in the field/entity that holds the id, never encoded
into the id value itself.
"""

import uuid
from typing import NewType

OrderId = NewType("OrderId", uuid.UUID)
PortfolioId = NewType("PortfolioId", uuid.UUID)
PositionId = NewType("PositionId", uuid.UUID)
TransactionId = NewType("TransactionId", uuid.UUID)
StrategyId = NewType("StrategyId", uuid.UUID)
ScreenerId = NewType("ScreenerId", uuid.UUID)
FillId = NewType("FillId", uuid.UUID)
EventId = NewType("EventId", uuid.UUID)
SignalId = NewType("SignalId", uuid.UUID)
CorrelationId = NewType("CorrelationId", uuid.UUID)

__all__ = [
    "OrderId",
    "PortfolioId",
    "PositionId",
    "TransactionId",
    "StrategyId",
    "ScreenerId",
    "FillId",
    "EventId",
    "SignalId",
    "CorrelationId",
]
