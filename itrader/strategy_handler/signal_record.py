"""Frozen signal-record entity for the SignalStore seam (Plan 05-03, SIG-01).

A ``SignalRecord`` is the typed, immutable fact captured ONCE per non-None
``SignalIntent`` returned by ``Strategy.generate_signal`` — captured BEFORE the
per-portfolio fan-out so it carries NO ``portfolio_id`` (D-09: a signal is a
single strategy decision, not a per-portfolio order). It mirrors the ``Order``
entity's id-defaulting pattern but lives in the strategy domain.

Design decisions:

- **D-08 — dedicated entity.** ``SignalRecord`` is its own frozen dataclass, not
  a reused ``SignalEvent`` / ``SignalIntent`` — the persisted shape is distinct
  from the on-the-wire event and the strategy-return intent.
- **D-09 — per-intent, pre-fan-out capture, no portfolio_id.** One record per
  intent regardless of how many portfolios the intent fans out to. The record
  has NO ``portfolio_id`` field.
- **D-10 — own SignalId.** Each record defaults a fresh UUIDv7 ``SignalId`` via
  ``idgen.generate_signal_id()`` (the single id scheme), mirroring how ``Order``
  defaults its ``OrderId``.
- **D-04 — config snapshot as a plain dict.** ``config`` holds a plain params
  snapshot ``dict`` captured from the strategy's declared attrs (``strategy.to_dict()``),
  not a frozen pydantic config — the pydantic config layer was deleted (D-01).

4-space indentation (co-located with the storage-seam house style, RESEARCH
Pitfall 6).
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from itrader import idgen
from itrader.core.enums import OrderType, Side
from itrader.core.ids import SignalId, StrategyId


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalRecord:
    """The persisted fact for a single strategy signal decision (D-08).

    Captured once per non-None ``SignalIntent``, before the per-portfolio
    fan-out (D-09) — so there is deliberately NO ``portfolio_id``.

    Attributes
    ----------
    signal_id : SignalId
        UUIDv7 identity, defaulted via ``idgen.generate_signal_id()`` (D-10).
    strategy_id : StrategyId
        The strategy that produced the signal.
    ticker : str
        The instrument the signal targets.
    time : datetime
        The business time stamped from the originating ``BarEvent`` (never
        wall-clock).
    action : Side
        BUY or SELL — the ``Side`` enum, consistent with ``SignalIntent`` /
        ``SignalEvent`` (RESEARCH OQ3).
    stop_loss : Decimal | None
        Explicit stop-loss level declared on the intent (None when absent).
    take_profit : Decimal | None
        Explicit take-profit level declared on the intent (None when absent).
    exit_fraction : Decimal
        Fraction of the open position an exit closes, in (0, 1].
    quantity : Decimal | None
        Explicit caller-supplied quantity; None means "resolver decides".
    order_type : OrderType
        The entry order type the strategy decided (D-02): MARKET for plain
        buy()/sell(), LIMIT/STOP for the typed factories. Oracle-dark audit
        field — never affects fills.
    entry_price : Decimal | None
        The limit/stop entry price declared on the intent (None for MARKET).
        Oracle-dark audit field (D-02) — never affects fills.
    config : dict[str, Any]
        A plain params snapshot dict captured from the strategy's declared
        attrs (``strategy.to_dict()``, D-04) — the pydantic config layer was
        deleted. Already serialization-ready (SIG-02 queryability).
    """

    signal_id: SignalId = field(
        default_factory=lambda: SignalId(idgen.generate_signal_id())
    )
    strategy_id: StrategyId
    ticker: str
    time: datetime
    action: Side
    order_type: OrderType
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    exit_fraction: Decimal = Decimal("1")
    quantity: Decimal | None = None
    entry_price: Decimal | None = None
    config: dict[str, Any]
