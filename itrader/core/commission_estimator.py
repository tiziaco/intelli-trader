"""Fee-model PROVIDER seam for the order domain (D-18, narrowing D-15).

The order domain reads execution's CURRENT fee model through an injected
Protocol rather than importing across the execution boundary — the same
read-model discipline as ``core/portfolio_read_model.py``.

Design decisions locked for this boundary:

* **D-18 — the seam is a fee-model PROVIDER, not a commission calculator.**
  The former ``CommissionEstimator`` Protocol (``(quantity, price) -> Decimal``)
  and its ``compose.py`` adapter did TWO unrelated jobs: they late-resolved the
  exchange's current fee model (a WIRING concern) and they applied the
  ``side="buy", order_type="market"`` admission convention (an ADMISSION-POLICY
  concern). D-18 gives each job to its rightful owner. This module keeps only the
  wiring half — ``() -> FeeModel | None``. The convention now lives in
  ``AdmissionManager._estimate_commission``, which owns admission policy.
  ``CommissionEstimator`` is RETIRED and is deleted in the very next commit of
  this plan, once the three order-domain call sites are retyped: leaving two
  Protocols side by side permanently would invite a caller to inject the wrong
  one, and no consumer outside those three sites exists (checked tree-wide). It
  survives this one commit ONLY so the tree stays type-clean between the two
  halves of the change. This deliberately REOPENS the D-15 Protocol shape — a
  considered amendment, not a drift.
* **Zero ``itrader`` deps AT RUNTIME.** This module imports nothing from
  ``itrader`` at runtime. The ``FeeModel`` return annotation is
  ``TYPE_CHECKING``-guarded and written as a STRING forward-ref, so it is never
  evaluated at import time — a real import would pull the execution package into
  ``core/`` and invert core's depends-on-nothing rule. This is the sanctioned
  in-tree idiom, established at ``trading_system/engine_context.py:53-65`` for
  ``SqlEngine`` / ``BarFeed`` / ``PriceStore``: runtime purity AND a narrowed type
  for ``mypy --strict`` (an ``Any`` return would lose type safety at exactly the
  seam this phase exists to tighten).
* **Late binding is the contract, not an implementation detail.**
  ``SimulatedExchange.update_config`` REPLACES ``self.fee_model`` with a freshly
  built object after its atomic config swap (``exchanges/simulated.py:775``, right
  after the swap at ``:770``). A provider that CAPTURES the fee model therefore
  keeps quoting a rate the exchange no longer charges, silently, forever — nothing
  raises. Implementations MUST dereference the exchange attribute inside
  ``__call__``. The golden run pins ``ZeroFeeModel``, so the byte-exact oracle can
  never catch a stale-fee regression; the guard is
  ``tests/unit/core/test_commission_estimator.py`` (a live late-binding test plus
  an explicit capturing-provider counter-example).
"""

from decimal import Decimal
from typing import Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    # D-18 / RESEARCH F-7: concrete-type import for the ANNOTATION ONLY, in the
    # ``engine_context.py:53-65`` style. A real (unguarded) import would pull
    # ``itrader.execution_handler`` onto ``core``'s import graph and invert the
    # core-depends-on-nothing rule pinned in CLAUDE.md. Guarded + string
    # forward-ref keeps the annotation unevaluated at runtime while still
    # narrowing the return type for ``mypy --strict``.
    from itrader.execution_handler.fee_model.base import FeeModel

__all__ = ["FeeModelProvider", "CommissionEstimator"]


@runtime_checkable
class CommissionEstimator(Protocol):
    """RETIRED by D-18 — deleted in the next commit of this plan.

    The pre-D-18 read-model seam (``f(quantity, price) -> commission``). It
    conflated wiring with admission policy; ``FeeModelProvider`` below keeps the
    wiring half and ``AdmissionManager`` took the policy half. Do NOT inject this
    into anything new — it exists for exactly one commit so the three order-domain
    call sites can be retyped in their own change.
    """

    def __call__(self, quantity: Decimal, price: Decimal) -> Decimal:
        """Estimate the commission for an order as ``f(quantity, price)``."""
        ...


@runtime_checkable
class FeeModelProvider(Protocol):
    """Structural seam (D-18) for order-domain reads of the venue's fee model.

    A ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes the
    narrow ``() -> FeeModel | None`` boundary the wiring-side provider satisfies
    structurally (a plain closure qualifies — no inheritance). The order domain
    never imports the execution package; it only calls this.
    """

    def __call__(self) -> Optional["FeeModel"]:
        """Return the venue's CURRENT fee model, dereferenced at CALL time.

        Late binding is the whole point (D-18). The exchange REPLACES its
        ``fee_model`` object on ``update_config`` (``simulated.py:775``), so an
        implementation that captured the model at construction would compute
        reservations at a stale rate with nothing anywhere raising. Read the
        attribute off the exchange inside the call; never memoize it.

        Returns
        -------
        Optional[FeeModel]
            The venue's current fee model, or ``None`` when this venue exposes
            NO fee model at all. ``None`` is an explicit contract, not an error:
            the caller (``AdmissionManager._estimate_commission``) turns it into
            a ``Decimal("0")`` estimate. It replaces the former adapter's
            ``isinstance(exchange, SimulatedExchange)`` guard.
        """
        ...
