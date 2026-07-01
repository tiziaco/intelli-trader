"""
LiveConnector — structural Protocol marker for a live trading venue (D-07 / D-10).

This is a ``runtime_checkable`` ``Protocol`` rather than an ABC — the same
structural-seam choice as ``AbstractExchange`` (D-07): it describes the swap-a-fake
boundary that every live venue (Phase 2 ``OkxConnector``) and the local paper venue
(Phase 4 ``PaperConnector``) must satisfy, with no shared implementation to inherit.
The ``Account`` family uses an ABC (cash→margin is a real superset to inherit); the
connector is purely a structural contract, so it uses a Protocol.

Scope this phase (D-10): a **thin marker that names the arm boundaries only** — the
data arm, the order arm, and lifecycle — so Phase 2 knows the slots to fill. The
real signatures (async submit → ack → fill, ``watch_ohlcv`` with the OKX ``confirm``
flag, balances / positions) are shaped against OKX reality in Phase 2 (CONN-*) and
are deliberately NOT frozen here — freezing OKX-shaped signatures before the
integration exists would be the premature-interface trap. Method bodies are ``...``
placeholders that name the slots, not concrete contracts.

This package is top-level ``itrader/connectors/`` (D-13), NOT a portfolio concern:
it spans the data + order arms (broader than execution) and anticipates Phase 2
``connectors/okx.py`` and Phase 4 ``connectors/paper.py``. ``VenueAccount`` stays in
``portfolio_handler/account/venue.py`` — it is an ``Account`` leaf, not a connector.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LiveConnector(Protocol):
    """
    Structural interface marker (D-07 / D-10) for a live trading venue.

    Names the arm boundaries Phase 2 fills; real signatures are deferred to
    Phase 2 (CONN-*) and shaped against OKX. ``runtime_checkable`` for
    swap-a-fake consistency with ``AbstractExchange``.
    """

    # Data arm — market-data streaming (Phase 2 CONN-*: watch_ohlcv + OKX confirm flag)
    def watch_data(self) -> Any:
        """Stream market data from the venue (slot — Phase 2 CONN-*)."""
        ...

    # Order arm — order submission / cancellation (Phase 2 CONN-*: async submit->ack->fill)
    def submit_order(self, *args: Any, **kwargs: Any) -> Any:
        """Submit an order to the venue (slot — Phase 2 CONN-*)."""
        ...

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        """Cancel a resting order on the venue (slot — Phase 2 CONN-*)."""
        ...

    # Lifecycle — connection management (Phase 2 CONN-*: sandbox routing)
    def connect(self) -> Any:
        """Open the connection to the venue (slot — Phase 2 CONN-*)."""
        ...

    def disconnect(self) -> Any:
        """Close the connection to the venue (slot — Phase 2 CONN-*)."""
        ...
