"""
Strategy signal event: a pure, immutable strategy fact (D-03 — no
verdict flag; the validator verdict lives on the Order entity, never
on the event).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from itrader.core.enums import EventType, OrderType, Side
from itrader.core.ids import PortfolioId, StrategyId
# Pitfall 3 (cycle safety): the typed sizing vocabulary is imported from
# itrader.core.sizing ONLY — NEVER from order_handler (which imports events).
from itrader.core.sizing import SizingPolicy, SLTPPolicy, TradingDirection

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
    price: `Decimal`
        Last close price for the instrument. Decimal-typed since D-22
        (closing the Phase 4 D-04 deferral): the strategy's float close
        enters via ``to_money`` (the string path) at signal construction.
    stop_loss: `Decimal`
        Stop loss price for the instrument (Decimal, D-22)
    take_profit: `Decimal`
        Take profit price for the instrument (Decimal, D-22)
    strategy_id: `StrategyId`
        The ID of the strategy who generated the signal
    portfolio_id: `PortfolioId`
        The UUIDv7-backed identity of the portfolio where to transact the position
    sizing_policy: `SizingPolicy`
        The strategy's DECLARED sizing policy (D-01) — the order layer's
        resolver turns it into a per-portfolio quantity; strategies never
        size. Typed vocabulary from ``itrader.core.sizing`` (D-02).
    direction: `TradingDirection`
        The strategy's declared trading direction (D-08 admission seam).
    allow_increase: `bool`
        Whether the strategy permits increasing an already-open position
        (D-10 declaration; enforcement lands with the admission rules).
    max_positions: `int`
        Maximum concurrent open positions the strategy declares.
    exit_fraction: `Decimal`
        Fraction of the open position an exit closes, in (0, 1].
        ``Decimal("1")`` (the default) is a full exit — resolved as a
        structural no-op (D-07).
    leverage: `Decimal`
        The strategy-declared leverage scalar (D-03). ``Decimal("1")``
        (the default) is unlevered — byte-exact (the engine caps it
        against the account-wide ``max_leverage`` and applies it in the
        order layer). SMA_MACD never sets this. Inert until Wave 2.
    sltp_policy: `SLTPPolicy | None`
        Optional percent-offset SL/TP bracket declaration (D-13);
        explicit ``stop_loss``/``take_profit`` values take precedence.
    quantity: `Decimal | None`
        Quantity to trade. ``None`` (the default) means "the order/risk
        layer sizes me" (D-10 — the 0 sentinel is gone); an explicit
        caller-supplied positive quantity is used as-is.
    """

    type: EventType = field(default=EventType.SIGNAL, init=False)
    ticker: str
    action: Side
    order_type: OrderType
    price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    # 02-05 carry-over: strategy_id carries a UUIDv7-backed StrategyId, not a raw int.
    strategy_id: StrategyId
    # FL-02: portfolio_id carries a UUIDv7-backed PortfolioId (#10 carry-forward).
    portfolio_id: PortfolioId
    # D-01: the untyped settings dict is DEAD — the signal carries the
    # typed policy vocabulary instead (kw_only, so required fields may
    # follow defaulted ones).
    sizing_policy: SizingPolicy
    direction: TradingDirection
    allow_increase: bool = False
    max_positions: int = 1
    exit_fraction: Decimal = Decimal("1")
    leverage: Decimal = Decimal("1")
    sltp_policy: SLTPPolicy | None = None
    quantity: Decimal | None = None

    def __str__(self) -> str:
        return f"{self.type} ({self.ticker}, {self.action}, {round(self.price, 4)} $)"

    def __repr__(self) -> str:
        return str(self)
