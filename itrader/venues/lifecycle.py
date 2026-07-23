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

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from itrader.logger import get_itrader_logger
from itrader.venues.venue_uid_guard import assert_venue_uid

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle

_logger = get_itrader_logger().bind(component="VenueLifecycle")


class VenueLifecycle:
    """Fixed connector start/stop order for one venue bundle, None-guarding absent members (D-10).

    Holds the built ``bundle`` and OPTIONALLY a ``provider`` (both exposed read-only so
    the composition root can read them back) plus the optional shared
    ``ConnectorProvider``. ``start()`` / ``stop()`` drive ONLY the connector lifecycle
    this phase (P5); a paper bundle (``connector=None``) no-ops the connector step via a
    structural None-guard, never a venue-string check.

    **Only the PRIMARY account's lifecycle carries a provider (11.1-08, D-14).** There
    is ONE ``LiveBarFeed`` and therefore ONE data provider — the decision is documented
    at the composition root's facade-dependent wiring loop ("the DATA provider stays
    deliberately single (one feed, the primary's provider), so it is wired outside the
    loop"). ``provider`` was a REQUIRED positional this class never read: it only
    re-exposed it, so ``assemble_venue`` built one per account and the composition root
    discarded all but the first. Those discarded objects are ``11-REVIEW.md``'s WR-07 —
    each resolves its own account's credentials, so an unwired one is a live
    credential-bearing object with no owner and no halt path. D-14 closes that by never
    constructing them, so the parameter is keyword-only and defaults to ``None``.

    Nothing in this class dereferences ``_provider``; ``start()`` / ``stop()`` drive the
    connector only. A provider-less lifecycle is therefore a fully functional one, not a
    degraded one.
    """

    def __init__(
        self,
        bundle: VenueBundle,
        *,
        provider: LiveDataProvider | None = None,
        connectors: ConnectorProvider | None = None,
        plugin: Any = None,
        venue_name: str | None = None,
        account_id: str | None = None,
        account_store: Any = None,
        alert_sink: Any = None,
    ) -> None:
        self._bundle = bundle
        self._provider = provider
        self._connectors = connectors
        # 11-04 (D-04): the post-connect venue-UID guard's collaborators. Optional so
        # existing construction sites keep working — but note that "optional" is
        # exactly how a security guard ships as DEAD CODE, so ``assemble_venue``
        # supplies ``plugin``/``venue_name``/``account_id`` unconditionally and the
        # live composition root supplies ``account_store``/``alert_sink``. The guard
        # is skipped only when a caller genuinely has no store (no Postgres arm).
        self._plugin = plugin
        self._venue_name = venue_name
        self._account_id = account_id
        self._account_store = account_store
        self._alert_sink = alert_sink

    @property
    def bundle(self) -> VenueBundle:
        """The execution ``VenueBundle`` this lifecycle orchestrates (read-only)."""
        return self._bundle

    @property
    def provider(self) -> LiveDataProvider | None:
        """The ONE feed-bound ``LiveDataProvider``, or ``None`` (read-only, D-14).

        Populated for the PRIMARY account only. A non-primary lifecycle answers
        ``None`` because that account's provider is never built — see the class
        docstring (WR-07). Callers already None-guard this: the facade reads it as
        ``streaming[0].provider if streaming else None`` and gates every use on
        ``is not None``.
        """
        return self._provider

    def start(self) -> None:
        """Bring the venue up in the fixed order, None-guarding absent members (D-10).

        Step 1 (this phase): connect the shared connector — ONLY when the bundle
        carries one. A paper bundle (``connector=None``) skips this step (structural
        None-guard), so ``start()`` is a fail-safe no-op for the connector step.

        Step 2 (11-04, D-04): assert the venue's own account UID immediately after the
        connect — trust-on-first-use, alert on mismatch, NEVER halt. It lives inside
        the same structural ``None``-guard so a paper bundle skips it entirely, and it
        runs FIRST among the post-connect hooks so a misrouted session is flagged
        before any venue-truth snapshot is trusted.

        The venue-truth exchange-stream spawn + account snapshot/link steps remain
        in ``LiveTradingSystem.start()`` this phase (P6 folds them into a
        ``SessionInitializer``); they hook AFTER this connector connect.
        """
        if self._bundle.connector is not None:
            self._bundle.connector.connect()
            self._assert_venue_uid(self._bundle.connector)

    def _assert_venue_uid(self, connector: Any) -> None:
        """Run the D-04 trust-on-first-use UID guard for this venue account.

        Skipped only when a collaborator is genuinely absent (e.g. a deployment with
        no SQL arm, so there is no ``VenueAccountStore`` to record into). The skip is
        LOGGED — a silently-skipped security guard is indistinguishable from a passing
        one, which is precisely how this mitigation would ship inert.
        """
        if self._account_store is None or self._alert_sink is None or self._plugin is None:
            _logger.warning(
                "venue-uid guard skipped — no account store / alert sink wired; the "
                "D-04 spoofing detector is inert for this venue",
                venue_name=self._venue_name,
                account_id=self._account_id,
            )
            return

        assert_venue_uid(
            plugin=self._plugin,
            connector=connector,
            venue_name=self._venue_name or "",
            account_id=self._account_id,
            store=self._account_store,
            alert_sink=self._alert_sink,
            # Wall clock is correct here: this is a LIVE session-identity observation,
            # not an engine-path business time. The store is clock-free by design
            # (D-07), so the timestamp is supplied at the call boundary.
            at=datetime.now(UTC),
        )

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
