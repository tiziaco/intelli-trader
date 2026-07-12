"""VenueLifecycle — the fixed connector start/stop order, None-guarding absent members (05-06, VENUE-06, D-10).

``VenueLifecycle`` is the small orchestrator (RESEARCH Open Q3 — a class, not a
bare function, so the None-guards and fixed order live in one testable unit that
``assemble_venue`` returns and ``LiveTradingSystem`` delegates to). It encodes the
fixed venue START/STOP order and, per D-10, None-GUARDS the ENTIRELY ABSENT
components (paper carries ``connector=None``): the connector step is a no-op for a
paper bundle. These are STRUCTURAL guards (``if x is not None``), NOT venue-string
comparisons — killing every ``if exchange=='okx'`` / ``elif=='paper'`` branch is
the goal (D-10), not branch-freedom.

Scope (P5): this phase moves ONLY the connector connect/disconnect lifecycle into
``VenueLifecycle``. The venue-truth exchange-stream spawn + account snapshot/link
steps stay in ``LiveTradingSystem.start()`` this phase; P6 (RUN-01/RUN-06) folds
them into a ``SessionInitializer``. The comments below mark where those steps hook.

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free (the P5 inertness gate).

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle


class VenueLifecycle:
    """Fixed connector start/stop order for one venue bundle, None-guarding absent members (D-10).

    Holds the built ``bundle`` + ``provider`` (exposed read-only so the composition
    root can read them back) plus the optional shared ``ConnectorProvider``.
    ``start()`` / ``stop()`` drive ONLY the connector lifecycle this phase (P5); a
    paper bundle (``connector=None``) no-ops the connector step via a structural
    None-guard, never a venue-string check.
    """

    def __init__(
        self,
        bundle: VenueBundle,
        provider: LiveDataProvider,
        *,
        connectors: ConnectorProvider | None = None,
    ) -> None:
        self._bundle = bundle
        self._provider = provider
        self._connectors = connectors

    @property
    def bundle(self) -> VenueBundle:
        """The execution ``VenueBundle`` this lifecycle orchestrates (read-only)."""
        return self._bundle

    @property
    def provider(self) -> LiveDataProvider:
        """The venue ``LiveDataProvider`` this lifecycle orchestrates (read-only)."""
        return self._provider

    def start(self) -> None:
        """Bring the venue up in the fixed order, None-guarding absent members (D-10).

        Step 1 (this phase): connect the shared connector — ONLY when the bundle
        carries one. A paper bundle (``connector=None``) skips this step (structural
        None-guard), so ``start()`` is a fail-safe no-op for the connector step.

        The venue-truth exchange-stream spawn + account snapshot/link steps remain
        in ``LiveTradingSystem.start()`` this phase (P6 folds them into a
        ``SessionInitializer``); they hook AFTER this connector connect.
        """
        if self._bundle.connector is not None:
            self._bundle.connector.connect()

    def stop(self) -> None:
        """Tear the venue down in reverse order, None-guarding absent members (D-10).

        Prefer the shared ``ConnectorProvider.close_all()`` (it disconnects every
        memoized connector for the run and is a safe no-op on an empty memo — the
        paper case, which never populated it); fall back to the bundle connector's
        own ``disconnect()`` when no provider was injected. A paper bundle with no
        provider (``connector=None``) no-ops the connector step entirely.
        """
        if self._connectors is not None:
            self._connectors.close_all()
        elif self._bundle.connector is not None:
            self._bundle.connector.disconnect()
