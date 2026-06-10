"""
Typed sizing vocabulary for the iTrader engine (M5-06, D-01/D-02/D-05/D-07/D-13).

This module is the single home for the event-carried sizing types — the
strategy DECLARES policy, the order/risk layer RESOLVES quantity:

- **D-01 — typed policy + engine resolver.** Strategies declare a
  ``SizingPolicy`` value; the ONE resolver in the order layer
  (``order_handler/sizing_resolver.py``) match-dispatches on the kind and
  computes the per-portfolio quantity. Strategies never size.
- **D-02 — the v1 vocabulary.** Exactly three sizing kinds —
  ``FractionOfCash``, ``FixedQuantity``, ``RiskPercent`` — and the union
  alias ``SizingPolicy``. Growth means adding a kind here, never branching
  in handlers.
- **D-05 — optional ``step_size``, quantities ONLY.** When set, the resolver
  quantizes the resolved quantity ``ROUND_DOWN`` to the step. ``step_size``
  never touches prices — the Phase 6 D-14 price-precision policy is untouched.
- **D-07 — ``exit_fraction`` defaults to ``Decimal("1")``.** A full exit is
  the structural no-op default: the resolver returns the position's
  ``net_quantity`` UNCHANGED (no multiplication performed) so the golden path
  stays byte-exact.
- **D-13 — explicit SL/TP primary; ``SLTPPolicy`` is the declared
  alternative.** ``PercentFromFill`` / ``PercentFromDecision`` express
  percent-offset brackets; explicit ``stop_loss``/``take_profit`` values on
  ``SignalIntent`` take precedence.
- **Pitfall 1 — string-path Decimal literals.** Every policy Decimal literal
  MUST enter via the string path: ``Decimal("0.95")``, NEVER
  ``Decimal(0.95)`` (the float path carries the binary-repr artifact and
  breaks byte-exactness against the golden oracle).

All construction is validated in ``__post_init__`` (V5, D-06 fail-loud):
violations raise ``SizingPolicyViolation`` naming the field and value.

Import-cycle rule (RESEARCH Pitfall 3): these types live in ``core/``
precisely so ``SignalEvent`` can carry them without a runtime import cycle
through ``order_handler``. This module imports stdlib + intra-core ONLY —
NOTHING from ``order_handler``, ``events_handler``, or ``strategy_handler``.
"""

from dataclasses import dataclass
from decimal import Decimal

from itrader.core.enums import Side, TradingDirection
from itrader.core.exceptions import SizingPolicyViolation

__all__ = [
    "FixedQuantity",
    "FractionOfCash",
    "PercentFromDecision",
    "PercentFromFill",
    "RiskPercent",
    "SignalIntent",
    "SizingPolicy",
    "SLTPPolicy",
    "TradingDirection",
]

_ZERO = Decimal("0")
_ONE = Decimal("1")


def _require_positive(kind: str, field: str, value: Decimal) -> None:
    """D-06 fail-loud: ``value`` must be strictly positive."""
    if value <= _ZERO:
        raise SizingPolicyViolation(
            f"{kind}.{field} must be > 0: got {value!r}"
        )


def _require_unit_interval(kind: str, field: str, value: Decimal) -> None:
    """D-06 fail-loud: ``value`` must lie in (0, 1]."""
    if not (_ZERO < value <= _ONE):
        raise SizingPolicyViolation(
            f"{kind}.{field} must be in (0, 1]: got {value!r}"
        )


def _validate_step_size(kind: str, step_size: Decimal | None) -> None:
    """D-05: ``step_size`` is optional; when set it must be strictly positive."""
    if step_size is not None:
        _require_positive(kind, "step_size", step_size)


@dataclass(frozen=True, slots=True)
class FractionOfCash:
    """Size the entry as a fraction of available cash (D-02).

    The golden policy: ``FractionOfCash(fraction=Decimal("0.95"))`` reproduces
    the legacy ``(Decimal("0.95") * available) / to_money(price)`` expression
    byte-exact (Pitfall 1 — string-path literal, same operands, same order).

    Attributes
    ----------
    fraction : Decimal
        Fraction of available cash to deploy, in (0, 1].
    step_size : Decimal | None
        Optional exchange quantity step (D-05); ``None`` means no quantize.
    """

    fraction: Decimal
    step_size: Decimal | None = None

    def __post_init__(self) -> None:
        _require_unit_interval("FractionOfCash", "fraction", self.fraction)
        _validate_step_size("FractionOfCash", self.step_size)


@dataclass(frozen=True, slots=True)
class FixedQuantity:
    """Size the entry as a fixed instrument quantity (D-02).

    Attributes
    ----------
    qty : Decimal
        The fixed quantity, strictly positive.
    step_size : Decimal | None
        Optional exchange quantity step (D-05); ``None`` means no quantize.
    """

    qty: Decimal
    step_size: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive("FixedQuantity", "qty", self.qty)
        _validate_step_size("FixedQuantity", self.step_size)


@dataclass(frozen=True, slots=True)
class RiskPercent:
    """Van Tharp risk-percent sizing: risk a fixed equity fraction per trade (D-02).

    Resolution requires a usable stop: ``(equity * risk_pct) / |price - stop|``.
    A missing or price-equal stop is a ``SizingPolicyViolation`` at resolve
    time (D-06). Oracle-dark: the golden FractionOfCash run never reads equity.

    Attributes
    ----------
    risk_pct : Decimal
        Fraction of total equity to risk per trade, strictly positive.
    step_size : Decimal | None
        Optional exchange quantity step (D-05); ``None`` means no quantize.
    """

    risk_pct: Decimal
    step_size: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive("RiskPercent", "risk_pct", self.risk_pct)
        _validate_step_size("RiskPercent", self.step_size)


# D-01/D-02: the resolver match-dispatches on exactly these kinds, closing
# with assert_never so mypy --strict fails on an unhandled kind.
SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent


@dataclass(frozen=True, slots=True, kw_only=True)
class PercentFromFill:
    """SL/TP bracket as percent offsets from the FILL price (D-13).

    Children are created/adjusted when the parent fill price is known.

    Attributes
    ----------
    sl_pct : Decimal
        Stop-loss offset as a fraction of fill price, strictly positive.
    tp_pct : Decimal
        Take-profit offset as a fraction of fill price, strictly positive.
    """

    sl_pct: Decimal
    tp_pct: Decimal

    def __post_init__(self) -> None:
        _require_positive("PercentFromFill", "sl_pct", self.sl_pct)
        _require_positive("PercentFromFill", "tp_pct", self.tp_pct)


@dataclass(frozen=True, slots=True, kw_only=True)
class PercentFromDecision:
    """SL/TP bracket as percent offsets from the DECISION price (D-13).

    Levels are fixed at signal time from the decision-bar price.

    Attributes
    ----------
    sl_pct : Decimal
        Stop-loss offset as a fraction of decision price, strictly positive.
    tp_pct : Decimal
        Take-profit offset as a fraction of decision price, strictly positive.
    """

    sl_pct: Decimal
    tp_pct: Decimal

    def __post_init__(self) -> None:
        _require_positive("PercentFromDecision", "sl_pct", self.sl_pct)
        _require_positive("PercentFromDecision", "tp_pct", self.tp_pct)


# D-13: explicit SL/TP values on SignalIntent are primary; a declared
# SLTPPolicy is the percent-offset alternative.
SLTPPolicy = PercentFromFill | PercentFromDecision


# TradingDirection now lives in its canonical home ``core/enums/trading.py``
# and is re-exported here (see the import above + ``__all__``) so the existing
# ``from itrader.core.sizing import TradingDirection`` call sites keep working.


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalIntent:
    """The D-12 strategy-return contract: a pure trading intent, no sizing.

    ``Strategy.generate_signal`` returns a ``SignalIntent`` (or ``None``);
    the handler fans it out into per-portfolio ``SignalEvent``s and the
    order layer resolves quantity from the declared policy (D-01). Lives in
    ``core/`` per RESEARCH OQ2 — one coherent vocabulary module, cycle-safe.

    Attributes
    ----------
    ticker : str
        The instrument the intent targets.
    action : Side
        BUY or SELL at the event boundary (D-05 vocabulary).
    stop_loss : Decimal | None
        Explicit stop-loss level (primary over any SLTPPolicy, D-13).
    take_profit : Decimal | None
        Explicit take-profit level (primary over any SLTPPolicy, D-13).
    exit_fraction : Decimal
        Fraction of the open position an exit closes, in (0, 1]. Defaults to
        ``Decimal("1")`` — a full exit, resolved as a structural no-op (D-07).
    quantity : Decimal | None
        Explicit caller-supplied quantity; ``None`` means "resolver decides".
    """

    ticker: str
    action: Side
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    exit_fraction: Decimal = Decimal("1")
    quantity: Decimal | None = None
    # TODO add order_type and entry_price for stop/limit orders 

    def __post_init__(self) -> None:
        _require_unit_interval("SignalIntent", "exit_fraction", self.exit_fraction)
