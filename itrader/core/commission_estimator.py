"""Commission-estimate read-model seam for the order domain (D-15).

Promotes the inline ``_estimate_commission`` closure (today living in
``backtest_trading_system.py``) to a typed read-model seam, mirroring
``core/portfolio_read_model.py``: the order domain reads execution's fee
estimate through an injected Protocol rather than importing across the
execution boundary.

Design decisions locked for this boundary:

* **D-15 — typed read-model seam.** ``OrderManager.commission_estimator`` retypes
  from ``Callable[[Decimal, Decimal], Decimal]`` to this Protocol; the concrete
  ``FeeModelCommissionEstimator`` adapter (Wave 2) satisfies it structurally —
  no adapter inheritance, ``mypy --strict`` enforces the boundary.
* **Zero ``itrader`` deps.** The signature is primitive ``(Decimal, Decimal) ->
  Decimal`` only — this module imports nothing from ``itrader`` (honors core's
  dependency rule; it must NOT import ``SimulatedExchange`` or any fee model).
* **Late binding (Wave 2 adapter concern).** The concrete adapter holds the
  exchange ref and dereferences ``fee_model`` in ``__call__`` so a post-construction
  ``update_config`` fee-model swap is reflected — that correctness property is
  tested when the adapter lands (04-02 Task 2 appends the late-binding test).
"""

from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = ["CommissionEstimator"]


@runtime_checkable
class CommissionEstimator(Protocol):
    """Structural seam (D-15) for order-domain reads of an execution fee estimate.

    A ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes the
    narrow ``f(quantity, price) -> commission`` boundary the concrete adapter
    (``FeeModelCommissionEstimator``, Wave 2) satisfies structurally — no
    inheritance. The primitive signature keeps this module ``itrader``-free.
    """

    def __call__(self, quantity: Decimal, price: Decimal) -> Decimal:
        """Estimate the commission for an order as ``f(quantity, price)``.

        Parameters
        ----------
        quantity : Decimal
            The order quantity (full precision, never quantized here).
        price : Decimal
            The reference price for the estimate (full precision).

        Returns
        -------
        Decimal
            The estimated commission at full precision.
        """
        ...
