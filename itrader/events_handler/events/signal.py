"""
Strategy signal event: a pure, immutable strategy fact (D-03 — no
verdict flag; the validator verdict lives on the Order entity, never
on the event).
"""

from dataclasses import dataclass, field
from typing import Any

from itrader.core.enums import EventType, OrderType, Side
from itrader.core.ids import StrategyId

from .base import Event


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalEvent(Event):
    """
    Signal event generated from a Strategy object.
    This is received by the Order handler object that validates and
    sends the order to the Execution handler object.

    Parameters
    ----------
    time: `timestamp`
        Event time
    order_type: `OrderType`
        Type of order, e.g. ``OrderType.MARKET``, ``OrderType.LIMIT``,
        ``OrderType.STOP`` (enum-typed at the event boundary, D-05).
    ticker: `str`
        The ticker symbol, e.g. 'BTCUSD'.
    action: `Side`
        ``Side.BUY`` (for long) or ``Side.SELL`` (for short) — enum-typed
        at the event boundary (D-05); Portfolio maps Side -> TransactionType
        at its own boundary.
    price: `float`
        Last close price for the instrument (float until M4, D-04)
    stop_loss: `float`
        Stop loss price for the instrument
    take_profit: `float`
        Take profit price for the instrument
    strategy_id: `StrategyId`
        The ID of the strategy who generated the signal
    portfolio_id: `int`
        The ID of the portfolio where to transact the position
    strategy_setting: `dict`
        Strategy settings used to generate the signal.
    quantity: `float | None`
        Quantity to trade. ``None`` (the default) means "the order/risk
        layer sizes me" (D-10 — the 0 sentinel is gone); an explicit
        caller-supplied positive quantity is used as-is.
    """

    type: EventType = field(default=EventType.SIGNAL, init=False)
    ticker: str
    action: Side
    order_type: OrderType
    price: float
    stop_loss: float
    take_profit: float
    # 02-05 carry-over: strategy_id carries a UUIDv7-backed StrategyId, not a raw int.
    strategy_id: StrategyId
    portfolio_id: int
    strategy_setting: dict[str, Any]
    quantity: float | None = None

    def __str__(self) -> str:
        return f"{self.type} ({self.ticker}, {self.action}, {round(self.price, 4)} $)"

    def __repr__(self) -> str:
        return str(self)
