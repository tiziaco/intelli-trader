"""
The ONE sizing resolver for the order layer (Plan 07-01, D-01/D-02/D-05/D-06/D-07).

Strategies DECLARE a ``SizingPolicy`` (D-01); this resolver — and nothing
else in the engine — turns the declaration into a per-portfolio quantity:

- **D-01 — ONE resolver, exhaustive dispatch.** ``resolve_entry`` match-
  dispatches on the policy kind, closing with ``typing.assert_never`` so
  ``mypy --strict`` fails loudly on an unhandled kind. Growth means adding a
  ``case`` arm here, never branching in handlers.
- **D-02 — the v1 vocabulary.** FractionOfCash / FixedQuantity / RiskPercent.
- **Byte-exact rule (Pitfall 1, T-07-02).** The FractionOfCash arm reproduces
  the legacy M1 expression at ``order_manager.py:628`` operand-for-operand:
  ``(policy.fraction * available) / to_money(price)``. The golden fraction
  ``Decimal("0.95")`` must reproduce the legacy quantity repr-exact BEFORE
  plan 07-05 swaps this resolver into ``_resolve_signal_quantity``.
- **D-05 — optional ``step_size``, quantities only.** When set, the resolved
  quantity is quantized ``ROUND_DOWN`` to the step; when ``None`` the value
  is NOT touched (structural no-op — no quantize call is made).
- **D-06 — fail-loud.** Policy violations raise ``SizingPolicyViolation``;
  translation to the audited REJECTED route is OrderManager's job (07-05).
- **D-07 — ``exit_fraction == 1`` is a structural no-op.** ``resolve_exit``
  returns ``net_quantity`` UNCHANGED (the multiply is skipped entirely) so
  the golden full-exit path carries the exact position quantity.

Discipline: the resolver never touches the events queue and never constructs
OperationResults (manager-never-touches-queue, D-18); it reads portfolio
state exclusively through the injected ``PortfolioReadModel`` Protocol —
never the concrete handler.
"""

from decimal import ROUND_DOWN, Decimal
from typing import assert_never

from itrader.core.exceptions import SizingPolicyViolation
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.core.portfolio_read_model import PortfolioReadModel
from itrader.core.sizing import FixedQuantity, FractionOfCash, RiskPercent, SizingPolicy

__all__ = ["SizingResolver"]

_ONE = Decimal("1")


def _quantize_to_step(qty: Decimal, step: Decimal) -> Decimal:
    """Quantize ``qty`` DOWN to the nearest multiple of ``step`` (D-05, WR-02).

    ``Decimal.quantize`` rounds to the *exponent* of ``step`` — correct only
    when ``step`` is exactly ``1 x 10^n``. The D-05 contract is "ROUND_DOWN to
    the step", i.e. to multiples of the step value: ``step_size=Decimal("0.5")``
    must yield the 0.5 grid (2.3 -> 2.0), ``Decimal("5")`` the multiples-of-5
    grid, ``Decimal("0.010")`` the 0.01 grid regardless of the string's stored
    exponent. Dividing by the step, flooring to an integer count, and
    re-multiplying gives the largest multiple of ``step`` not exceeding ``qty``.
    """
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


class SizingResolver:
    """Resolve declared sizing policies into per-portfolio quantities (D-01).

    Constructed with the narrow ``PortfolioReadModel`` Protocol (D-16 —
    injected, never the concrete ``PortfolioHandler``), mirroring the
    OrderManager constructor-injection shape.
    """

    def __init__(self, read_model: PortfolioReadModel) -> None:
        self._read_model = read_model

    def resolve_entry(
        self,
        policy: SizingPolicy,
        portfolio_id: PortfolioId,
        price: Decimal,
        stop: Decimal | None,
    ) -> Decimal:
        """Resolve the entry quantity for ``policy`` at ``price``.

        Parameters
        ----------
        policy : SizingPolicy
            The declared sizing policy (match-dispatched, D-01).
        portfolio_id : PortfolioId
            The portfolio whose state the policy reads.
        price : Decimal
            The signal price the entry sizes against.
        stop : Decimal | None
            The stop-loss level; REQUIRED (and distinct from ``price``) for
            ``RiskPercent`` (D-06), ignored by the other kinds.

        Returns
        -------
        Decimal
            The resolved quantity at full precision (D-01: quantize only via
            ``step_size``, never on the intermediate expression).

        Raises
        ------
        SizingPolicyViolation
            When ``RiskPercent`` has no usable stop (missing or equal to
            ``price`` — zero stop distance cannot size).
        """
        qty: Decimal
        match policy:
            case FractionOfCash():
                # Byte-exact M1 seam (Pitfall 1): SAME operands, SAME order
                # as order_manager.py:628 —
                #     (Decimal("0.95") * available) / to_money(price)
                # with the fraction now policy-declared by string construction.
                available = self._read_model.available_cash(portfolio_id)
                qty = (policy.fraction * available) / to_money(price)
            case FixedQuantity():
                qty = policy.qty
            case RiskPercent():
                # Van Tharp: risk a fixed equity fraction per unit of stop
                # distance — (equity * risk_pct) / |price - stop|.
                if stop is None or stop == price:
                    raise SizingPolicyViolation(
                        "RiskPercent requires stop_loss distinct from price: "
                        f"got stop={stop!r} at price={price!r}"
                    )
                equity = self._read_model.total_equity(portfolio_id)
                qty = (equity * policy.risk_pct) / abs(price - stop)
            case _:
                assert_never(policy)
        if policy.step_size is not None:
            # D-05: exchange step constraint — ROUND_DOWN to a multiple of the
            # step (never round an order quantity UP past what the policy
            # resolved). WR-02: snap to the step VALUE, not its exponent.
            qty = _quantize_to_step(qty, policy.step_size)
        return qty

    def resolve_exit(
        self,
        net_quantity: Decimal,
        exit_fraction: Decimal,
        step_size: Decimal | None,
    ) -> Decimal:
        """Resolve the exit quantity for a position of ``net_quantity``.

        Parameters
        ----------
        net_quantity : Decimal
            The open position's net quantity (exchange truth).
        exit_fraction : Decimal
            Fraction of the position to close, in (0, 1] (validated at
            ``SignalIntent`` construction).
        step_size : Decimal | None
            Optional exchange quantity step (D-05).

        Returns
        -------
        Decimal
            ``net_quantity`` UNCHANGED when ``exit_fraction == 1`` (D-07
            structural no-op — the multiply is skipped entirely so the
            golden path stays repr-exact); otherwise the sized partial exit,
            with the dust guard: when the post-exit remainder would drop
            below ``step_size``, the exit takes the full position.
        """
        if exit_fraction == _ONE:
            # D-07/Pitfall 1: structural no-op — return the exact object, no
            # multiplication artifact (net * 1 could change the exponent).
            return net_quantity
        sized = net_quantity * exit_fraction
        if step_size is not None:
            if (net_quantity - sized) < step_size:
                # Dust guard: a sub-step remainder is unclosable — the final
                # exit takes the whole position instead of stranding dust.
                return net_quantity
            # WR-02: snap to a multiple of the step VALUE, not its exponent.
            sized = _quantize_to_step(sized, step_size)
        return sized
