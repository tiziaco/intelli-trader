"""Trust-on-first-use venue-UID assertion — alert on mismatch, NEVER halt (11-04, D-04, MPORT-01).

**Why this exists in THIS phase.** Per-account credentials are what make the misroute
REACHABLE: a mistyped ``secret_ref`` or a swapped vault entry means an ``account_id``
connects with a DIFFERENT account's keys. Orders then route to the wrong REAL account
and reconciliation succeeds cleanly against it — a silent, money-losing failure that
only exists once multi-account exists (T-11-15, the only high-severity spoofing threat
in this plan). The venue's self-reported account UID is the ONLY external evidence that
the session belongs to the account the engine thinks it does.

**Trust on first use.** The FIRST connect for a ``(venue_name, account_id)`` pair
RECORDS the observed UID; every later connect ASSERTS against it. The rejected
alternative — an operator-declared expected UID — adds one more value to look up and
mistype, and a wrong expected value would block a correctly-configured account. Recording
removes the operator from the loop entirely, so there is no typo surface at all.

**Observe-only, by explicit decision.** A mismatch fires a CRITICAL alert through the
existing sink and RETURNS NORMALLY. It does NOT halt (T-11-19: a venue reporting its UID
differently across endpoints must not take a correctly-configured account offline) and it
does NOT overwrite the stored value (T-11-20: overwriting would make the guard
self-healing — it would alert once and then accept the impostor forever).

**Fail-safe, but never fail-SILENT.** Store failures are swallowed so the guard cannot
break an otherwise healthy connect. That fail-safety is also a hazard: a renamed venue
field or a storage outage would otherwise permanently disable the only spoofing detector
with zero signal. So every degraded path here LOGS — and a venue that DECLARES a
credential model (i.e. one that should have a venue-side identity) yielding no UID logs a
WARNING rather than passing silently.

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only annotations
keep this module ccxt/sqlalchemy/async-free.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from itrader.logger import get_itrader_logger
from itrader.venues.registry import DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
    from datetime import datetime

# The FIXED LITERAL alert reason (the reconciliation-coordinator discipline): alert and
# halt reasons are constants, never a stringified exception and never an interpolated
# payload, so an operator alert-rule can match on them and no exception text can smuggle
# unvetted content into the egress channel.
VENUE_UID_MISMATCH_REASON = "venue-uid-mismatch"

# ---------------------------------------------------------------- D-40 outcome
# 11.2-06 (D-15/D-40): the guard now REPORTS its outcome AND reason instead of only
# performing a side effect. D-15's condition is that the ``venue_uid_guard_active``
# flag reflect the guard's ACTUAL outcome — a bare boolean tells an operator the guard
# is off but not WHICH of its holes they have, and the paths below need SIX different
# operator fixes.

#: The two top-level outcomes. ``armed`` means the guard is actually protecting this
#: session (it recorded on first connect, asserted a match, or DETECTED a mismatch — a
#: detection is the guard at its most armed, never an idle state). ``inert`` means the
#: guard produced no protection this connect, and the reason names why.
GUARD_ARMED = "armed"
GUARD_INERT = "inert"

#: The ARMED sub-reasons — the guard worked, told three ways apart so the status can
#: distinguish "just learned this account's identity" from "confirmed it" from "caught
#: an impostor".
REASON_RECORDED_FIRST_CONNECT = "recorded-first-connect"
REASON_ASSERTED_MATCH = "asserted-match"
REASON_MISMATCH_ALERTED = "mismatch-alerted"

#: The SIX inert paths, enumerated from THIS module's own code (not re-counted from a
#: decision doc). Each needs a DIFFERENT operator investigation, so none may collapse
#: into another:
#:  1. the plugin's ``fetch_venue_uid`` RAISED — a third-party plugin broke its
#:     no-raise contract; fix the plugin.
REASON_FETCH_RAISED = "fetch-raised"
#:  2. a CREDENTIALED venue supplied no uid — its endpoint or the ``uid`` field was
#:     renamed, or the read scope was revoked; restore the venue-side identity read.
REASON_UID_UNAVAILABLE_CREDENTIALED = "uid-unavailable-credentialed"
#:  3. the venue declares NO credentials and has no venue-side identity (paper) — the
#:     one BENIGN inert path; nothing to fix.
REASON_NO_VENUE_IDENTITY = "no-venue-identity"
#:  4. the store READ failed — the database is unreachable; restore the read path.
REASON_STORE_READ_FAILED = "store-read-failed"
#:  5. no account ROW for this pair yet — provision the account.
REASON_NO_ACCOUNT_ROW = "no-account-row"
#:  6. the first-connect record WRITE failed — a read-only replica or a write outage;
#:     the guard stays inert for this pair until the write succeeds.
REASON_RECORD_WRITE_FAILED = "record-write-failed"


@dataclass(frozen=True)
class VenueUidGuardOutcome:
    """What the D-04 UID guard did for one connect — outcome AND reason (D-15/D-40).

    Frozen so a recorded outcome cannot be mutated after the fact. ``armed`` is the
    boolean D-15 originally named, but it never travels ALONE — ``outcome`` and
    ``reason`` carry the WHICH-hole detail a bare boolean cannot, which is the entire
    point of D-40. Two guards that are both ``armed is False`` for different reasons
    (a paper no-op vs a database outage) are NOT the same operational state.
    """

    armed: bool
    outcome: str
    reason: str

    @classmethod
    def armed_with(cls, reason: str) -> "VenueUidGuardOutcome":
        """The guard protected this connect; ``reason`` says how (record/assert/detect)."""
        return cls(armed=True, outcome=GUARD_ARMED, reason=reason)

    @classmethod
    def inert_with(cls, reason: str) -> "VenueUidGuardOutcome":
        """The guard produced no protection this connect; ``reason`` names which hole."""
        return cls(armed=False, outcome=GUARD_INERT, reason=reason)


_logger = get_itrader_logger().bind(component="VenueUidGuard")


def assert_venue_uid(
    *,
    plugin: Any,
    connector: Any,
    venue_name: str,
    account_id: str | None,
    store: Any,
    alert_sink: Any,
    at: datetime,
) -> VenueUidGuardOutcome:
    """Record (first connect) or assert (later connects) the venue's account UID (D-04).

    Parameters
    ----------
    plugin :
        The venue plugin — supplies ``fetch_venue_uid`` (the venue-specific endpoint and
        field) and ``credential_model`` (used only to tell a credential-less venue's
        legitimate ``None`` from a credentialed venue's silent degradation).
    connector :
        The freshly-connected ``LiveConnector`` session to interrogate.
    venue_name, account_id :
        The composite natural key of the ``venue_accounts`` row. ``account_id`` may be
        ``None`` and is normalized here.
    store :
        The ``VenueAccountStore`` holding the recorded ``venue_uid``.
    alert_sink :
        The existing CRITICAL egress seam. D-04 needs no new channel.
    at :
        The business timestamp for the record write (the store is clock-free, D-07).

    Returns
    -------
    VenueUidGuardOutcome
        The armed/inert outcome AND its reason (D-15/D-40). This function never raises
        into the caller and never halts — an inert outcome is how every degraded path
        reports itself, so the caller can surface WHICH hole it has.
    """
    # The plugins normalize a None spec.account_id to DEFAULT_ACCOUNT_ID INSIDE
    # build_bundle — a normalization the lifecycle never sees. The guard MUST apply the
    # same one: writing a NULL PK half produces a row that silently never matches on any
    # later connect, permanently disabling the guard for that account.
    resolved_account_id = account_id or DEFAULT_ACCOUNT_ID

    uid, fetch_inert_reason = _fetch_uid(
        plugin, connector, venue_name, resolved_account_id)
    if uid is None:
        # Paths 1-3 live in _fetch_uid; it returns the specific reason so the three do
        # not collapse into one "no uid".
        assert fetch_inert_reason is not None
        return VenueUidGuardOutcome.inert_with(fetch_inert_reason)

    try:
        row = store.get(venue_name, resolved_account_id)
    except Exception:
        # Path 4. T-11-19: a storage outage must not abort a healthy connect. Logged
        # loudly because it means the spoofing detector is inert for this session.
        _logger.error(
            "venue-uid guard could not read the account row; the D-04 spoofing "
            "guard is inert for this connect",
            venue_name=venue_name,
            account_id=resolved_account_id,
            exc_info=True,
        )
        return VenueUidGuardOutcome.inert_with(REASON_STORE_READ_FAILED)

    if row is None:
        # Path 5. No row for this pair yet — account MINTING is plan 11-07's job, and
        # this guard deliberately does not create rows (it would invent an operator
        # record from a connect-time code path).
        _logger.warning(
            "venue-uid guard found no account row; nothing recorded or asserted",
            venue_name=venue_name,
            account_id=resolved_account_id,
        )
        return VenueUidGuardOutcome.inert_with(REASON_NO_ACCOUNT_ROW)

    recorded = row.get("venue_uid")

    if recorded is None:
        if not _record_uid(store, venue_name, resolved_account_id, uid, at):
            # Path 6. The write failed; the guard stays inert for this pair until it
            # succeeds. Distinct from the READ failure above — a different fix.
            return VenueUidGuardOutcome.inert_with(REASON_RECORD_WRITE_FAILED)
        return VenueUidGuardOutcome.armed_with(REASON_RECORDED_FIRST_CONNECT)

    if recorded == uid:
        return VenueUidGuardOutcome.armed_with(REASON_ASSERTED_MATCH)

    # THE detection (T-11-15). Alert; do NOT overwrite (T-11-20); return (T-11-19).
    _emit_mismatch_alert(
        alert_sink,
        venue_name,
        resolved_account_id,
        recorded=recorded,
        observed=uid,
        at=at,
    )
    return VenueUidGuardOutcome.armed_with(REASON_MISMATCH_ALERTED)


def _fetch_uid(
    plugin: Any, connector: Any, venue_name: str, account_id: str
) -> tuple[str | None, str | None]:
    """The plugin's venue UID, or ``(None, inert_reason)`` (D-04/D-40).

    Returns ``(uid, None)`` on success, or ``(None, reason)`` naming WHICH of the three
    no-uid paths produced it so the caller can keep them distinct:

    * ``credential_model is None`` marks a venue with no credentials and therefore no
      venue-side account (paper) — the expected clean no-op (``REASON_NO_VENUE_IDENTITY``).
    * a venue that DECLARES a credential model yet yields ``None`` broke its endpoint or
      renamed the field (``REASON_UID_UNAVAILABLE_CREDENTIALED``).
    * a plugin that RAISED violated the no-raise Protocol (``REASON_FETCH_RAISED``).
    """
    try:
        uid = plugin.fetch_venue_uid(connector)
    except Exception:
        # Path 1. The Protocol says fetch_venue_uid must not raise; belt-and-braces so a
        # third-party plugin cannot break a healthy connect either (T-11-19).
        _logger.error(
            "venue-uid fetch raised; the D-04 spoofing guard is inert for this connect",
            venue_name=venue_name,
            account_id=account_id,
            exc_info=True,
        )
        return None, REASON_FETCH_RAISED

    if uid is not None:
        return str(uid), None

    if getattr(plugin, "credential_model", None) is not None:
        # Path 2. A venue that should expose a UID but does not.
        _logger.warning(
            "venue-uid unavailable for a credentialed venue; the D-04 spoofing "
            "guard is inert for this connect",
            venue_name=venue_name,
            account_id=account_id,
        )
        return None, REASON_UID_UNAVAILABLE_CREDENTIALED

    # Path 3. The BENIGN inert path — a credential-less venue (paper) has no identity.
    return None, REASON_NO_VENUE_IDENTITY


def _record_uid(
    store: Any, venue_name: str, account_id: str, uid: str, at: datetime
) -> bool:
    """Trust-on-first-use write; a store failure is logged and swallowed (T-11-19).

    Returns ``True`` when the write landed, ``False`` when it failed — the caller turns
    a ``False`` into the ``REASON_RECORD_WRITE_FAILED`` inert outcome (path 6), kept
    distinct from the READ failure (path 4) because the two need different fixes.
    """
    try:
        store.record_venue_uid(venue_name, account_id, uid, at)
    except Exception:
        _logger.error(
            "venue-uid guard could not record the first-connect uid; the D-04 "
            "spoofing guard stays inert for this pair until it succeeds",
            venue_name=venue_name,
            account_id=account_id,
            exc_info=True,
        )
        return False
    _logger.info(
        "venue-uid recorded on first connect (trust-on-first-use)",
        venue_name=venue_name,
        account_id=account_id,
    )
    return True


def _emit_mismatch_alert(
    alert_sink: Any,
    venue_name: str,
    account_id: str,
    *,
    recorded: str,
    observed: str,
    at: datetime,
) -> None:
    """Escalate the mismatch as a CRITICAL ``ErrorEvent`` (fixed literal reason).

    The payload carries the pair and BOTH UIDs so an operator can act, and NOTHING
    else: no credential material and no ``secret_ref`` value ever reach the egress
    channel (T-11-17).
    """
    from itrader.core.enums import ErrorSeverity
    from itrader.events_handler.events import ErrorEvent

    try:
        alert_sink.alert(
            ErrorEvent(
                time=at,
                source="venue",
                error_type=VENUE_UID_MISMATCH_REASON,
                error_message=(
                    "the venue reported a different account identity than the one "
                    "recorded for this account on its first connect — the account "
                    "may be connecting with another account's credentials"
                ),
                operation="venue_uid_guard",
                severity=ErrorSeverity.CRITICAL,
                details={
                    "venue_name": venue_name,
                    "account_id": account_id,
                    "recorded_venue_uid": recorded,
                    "observed_venue_uid": observed,
                },
            )
        )
    except Exception:
        # Even the egress cannot be allowed to abort the connect (T-11-19). Logged at
        # CRITICAL so the detection is not lost with the alert.
        _logger.critical(
            "venue-uid MISMATCH detected but the alert sink failed",
            venue_name=venue_name,
            account_id=account_id,
            recorded_venue_uid=recorded,
            observed_venue_uid=observed,
            exc_info=True,
        )
