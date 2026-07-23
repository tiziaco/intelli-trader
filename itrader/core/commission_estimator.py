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
  wiring half — ``(venue, account_id) -> FeeModel | None``. The convention now lives in
  ``AdmissionManager._estimate_commission``, which owns admission policy.
  ``CommissionEstimator`` is DELETED: leaving two Protocols side by side would
  invite a caller to inject the wrong one, and no consumer remains (checked
  tree-wide). This deliberately REOPENS the D-15 Protocol shape — a considered
  amendment, not a drift.
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
* **D-39 / 11.1-REVIEW WR-01 — the seam is keyed on the ``(venue, account_id)``
  PAIR.** The provider was originally ``() -> FeeModel | None``, and the one
  implementation (``compose_engine``) satisfied it with a closure over an
  exchange resolved ONCE at wiring time — always the paper compute exchange. The
  Protocol's own zero-arg shape is what made that venue-blindness invisible: a
  provider that cannot be ASKED about a venue cannot be caught answering for the
  wrong one. Naming the pair in the signature is the fix; an order's admission
  reservation now resolves the venue that will actually fill it. The pair is the
  same routing key ``ExecutionHandler.exchanges`` is keyed on (D-27/MPORT-07) —
  do not re-splice it into a single ``"venue:account"`` string.
"""

from typing import Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    # D-18 / RESEARCH F-7: concrete-type import for the ANNOTATION ONLY, in the
    # ``engine_context.py:53-65`` style. A real (unguarded) import would pull
    # ``itrader.execution_handler`` onto ``core``'s import graph and invert the
    # core-depends-on-nothing rule pinned in CLAUDE.md. Guarded + string
    # forward-ref keeps the annotation unevaluated at runtime while still
    # narrowing the return type for ``mypy --strict``.
    from itrader.execution_handler.fee_model.base import FeeModel

__all__ = ["FeeModelProvider"]


@runtime_checkable
class FeeModelProvider(Protocol):
    """Structural seam (D-18) for order-domain reads of the venue's fee model.

    A ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes the
    narrow ``(venue, account_id) -> FeeModel | None`` boundary the wiring-side
    provider satisfies structurally (a plain closure qualifies — no inheritance).
    The order domain never imports the execution package; it only calls this.
    """

    def __call__(self, venue: str, account_id: str) -> Optional["FeeModel"]:
        """Return the fee model of the exchange serving ``(venue, account_id)``.

        BOTH the registry lookup and the ``fee_model`` read happen INSIDE the
        call. Late binding is the whole point (D-18): the exchange REPLACES its
        ``fee_model`` object on ``update_config`` (``simulated.py:775``), so an
        implementation that captured the model at construction would compute
        reservations at a stale rate with nothing anywhere raising.

        D-39 / WR-01: the PAIR is an argument, not a wiring-time capture. A
        provider that resolves one exchange up front prices every order against
        that venue's economics regardless of where the order routes — and since
        the golden run pins fees to zero, nothing anywhere goes red.

        Parameters
        ----------
        venue : str
            The venue half of the routing key — an order's own ``exchange``
            string (e.g. ``'paper'``, ``'okx'``).
        account_id : str
            The venue-account half. Callers resolve it from the order's
            portfolio and MUST pass the single-account identity
            ``DEFAULT_ACCOUNT_ID`` for a portfolio that names no account.

        Returns
        -------
        Optional[FeeModel]
            The pair's current fee model, or ``None`` when the pair resolves no
            exchange OR the exchange it resolves exposes no fee model at all.
            ``None`` is an explicit contract, not an error: implementations must
            NOT raise on an unregistered pair, and the caller
            (``AdmissionManager._estimate_commission``) turns it into a
            ``Decimal("0")`` estimate — loudly. It replaces the former adapter's
            ``isinstance(exchange, SimulatedExchange)`` guard.
        """
        ...
