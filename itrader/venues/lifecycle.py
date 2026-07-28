"""VenueLifecycle — the fixed connector start/stop order, None-guarding absent members.

A small orchestrator class, not a bare function, so the None-guards and fixed
order live in one testable unit that ``assemble_venue`` returns and
``LiveTradingSystem`` delegates to. It encodes the venue START/STOP order and
None-guards components that are entirely absent (a paper bundle carries
``connector=None``): the connector step is then a no-op. These are structural
``if x is not None`` guards, never venue-string comparisons.

This class drives ONLY the connector connect/disconnect lifecycle; the
venue-truth exchange-stream spawn and account snapshot/link steps live in
``LiveTradingSystem.start()``, which calls each lifecycle's ``start()`` first.

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from itrader.logger import get_itrader_logger
from itrader.venues.venue_uid_guard import (
    VenueUidGuardOutcome,
    assert_venue_uid,
)

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle

_logger = get_itrader_logger().bind(component="VenueLifecycle")

# These are LIFECYCLE-LEVEL inert reasons — states that keep the venue-UID guard from
# running at all — kept separate from the guard's own reasons (which describe why it
# ran and produced no protection), so an operator can tell "never reached" apart from
# "reached and degraded".
#: ``start()`` has not run yet — the connect on which the guard arms has not happened.
GUARD_REASON_NOT_STARTED = "lifecycle-not-started"
#: A paper bundle carries no connector, so ``start()`` never connects and the
#: post-connect guard never runs. Benign — paper has no venue identity to protect.
GUARD_REASON_PAPER_NO_CONNECTOR = "lifecycle-paper-no-connector"
#: A guard collaborator (store / alert sink / plugin) was not wired, so the guard was
#: deliberately skipped rather than silently passing.
GUARD_REASON_COLLABORATORS_ABSENT = "lifecycle-guard-collaborators-absent"


class VenueLifecycle:
    """Fixed connector start/stop order for one venue bundle, None-guarding absent members.

    Holds the built ``bundle`` and optionally a ``provider`` (both exposed read-only)
    plus the optional shared ``ConnectorProvider``. ``start()``/``stop()`` drive ONLY
    the connector lifecycle; a paper bundle (``connector=None``) no-ops the connector
    step via a structural None-guard, never a venue-string check.

    ``provider`` exists for direct construction and standalone testing of
    ``assemble_venue``; on the live boot path it is always left at ``None`` — there is
    no privileged "primary" account, and the feed's data connection is bound by
    ``FeedConnectionBinder`` instead of a lifecycle's provider. An unwired per-account
    provider would otherwise be a live credential-bearing object with no owner and no
    halt path, which is why one is never built for a lifecycle that does not need it.

    Nothing in this class dereferences ``_provider``; a provider-less lifecycle is
    therefore a fully functional one, not a degraded one.
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
        # The post-connect venue-UID guard's collaborators. Optional so existing
        # construction sites keep working, but "optional" is exactly how a security
        # guard ships as dead code: the guard is skipped only when a caller genuinely
        # has no store (no Postgres arm), never silently.
        self._plugin = plugin
        self._venue_name = venue_name
        self._account_id = account_id
        self._account_store = account_store
        self._alert_sink = alert_sink
        # Seeded "not started" so a status read BEFORE start() reports the guard as
        # not yet armed, never a stale armed value from a previous run.
        self._venue_uid_guard_outcome: VenueUidGuardOutcome = (
            VenueUidGuardOutcome.inert_with(GUARD_REASON_NOT_STARTED))

    @property
    def bundle(self) -> VenueBundle:
        """The execution ``VenueBundle`` this lifecycle orchestrates (read-only)."""
        return self._bundle

    @property
    def provider(self) -> LiveDataProvider | None:
        """The ``LiveDataProvider`` this lifecycle was constructed with, or ``None``.

        Always ``None`` on the live boot path: the feed's data connection is bound by
        ``FeedConnectionBinder``, not by a lifecycle. Kept for direct construction and
        standalone testing of ``assemble_venue``.
        """
        return self._provider

    @property
    def venue_uid_guard_outcome(self) -> VenueUidGuardOutcome:
        """The venue-UID guard's outcome for this lifecycle's most recent ``start()``.

        The single source of truth for the per-pair ``venue_uid_guard_active`` surface
        ``VenueAccountManager`` exposes. Before ``start()`` it reports
        ``GUARD_REASON_NOT_STARTED`` — never a stale armed value, because arming is a
        CONNECT-time event and ``bring_online`` does not connect.
        """
        return self._venue_uid_guard_outcome

    def start(self) -> None:
        """Bring the venue up in the fixed order, None-guarding absent members.

        Step 1: connect the shared connector — ONLY when the bundle carries one. A
        paper bundle (``connector=None``) skips this step, so ``start()`` is a
        fail-safe no-op for the connector step.

        Step 2: assert the venue's own account UID immediately after the connect —
        trust-on-first-use, alert on mismatch, NEVER halt. It lives inside the same
        structural ``None``-guard so a paper bundle skips it entirely, and it runs
        FIRST among the post-connect hooks so a misrouted session is flagged before
        any venue-truth snapshot is trusted.

        The venue-truth exchange-stream spawn and account snapshot/link steps live in
        ``LiveTradingSystem.start()``, which calls each lifecycle's ``start()`` first.
        """
        if self._bundle.connector is not None:
            self._bundle.connector.connect()
            self._venue_uid_guard_outcome = self._assert_venue_uid(
                self._bundle.connector)
        else:
            # Benign inert state, but RECORDED rather than left at the initial "not
            # started" value — a status read after start() must reflect that the guard
            # was reached-and-skipped for a real reason.
            self._venue_uid_guard_outcome = VenueUidGuardOutcome.inert_with(
                GUARD_REASON_PAPER_NO_CONNECTOR)

    def _assert_venue_uid(self, connector: Any) -> VenueUidGuardOutcome:
        """Run the trust-on-first-use venue-UID guard for this venue account.

        Skipped only when a collaborator is genuinely absent (e.g. a deployment with
        no SQL arm, so there is no ``VenueAccountStore`` to record into). The skip is
        LOGGED and REPORTED — a silently-skipped security guard is indistinguishable
        from a passing one.
        """
        if self._account_store is None or self._alert_sink is None or self._plugin is None:
            _logger.warning(
                "venue-uid guard skipped — no account store / alert sink wired; the "
                "D-04 spoofing detector is inert for this venue",
                venue_name=self._venue_name,
                account_id=self._account_id,
            )
            return VenueUidGuardOutcome.inert_with(GUARD_REASON_COLLABORATORS_ABSENT)

        return assert_venue_uid(
            plugin=self._plugin,
            connector=connector,
            venue_name=self._venue_name or "",
            account_id=self._account_id,
            store=self._account_store,
            alert_sink=self._alert_sink,
            # Wall clock is correct here: this is a LIVE session-identity observation,
            # not an engine-path business time, and the store is clock-free by design —
            # the timestamp is supplied at the call boundary.
            at=datetime.now(UTC),
        )

    def stop(self) -> None:
        """Tear the venue down in reverse order, None-guarding absent members.

        Prefer the shared ``ConnectorProvider.close_all()`` (it disconnects every
        memoized connector for the run and is a safe no-op on an empty memo — the
        paper case, which never populated it); fall back to the bundle connector's
        own ``disconnect()`` when no provider was injected. A paper bundle
        (``connector=None``) no-ops the connector step entirely.
        """
        if self._connectors is not None:
            self._connectors.close_all()
        elif self._bundle.connector is not None:
            self._bundle.connector.disconnect()
