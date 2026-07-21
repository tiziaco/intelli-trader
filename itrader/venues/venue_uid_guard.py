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

from typing import TYPE_CHECKING, Any

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from datetime import datetime

# The FIXED LITERAL alert reason (the reconciliation-coordinator discipline): alert and
# halt reasons are constants, never a stringified exception and never an interpolated
# payload, so an operator alert-rule can match on them and no exception text can smuggle
# unvetted content into the egress channel.
VENUE_UID_MISMATCH_REASON = "venue-uid-mismatch"

# The account_id the plugins normalize a None spec.account_id to (``spec.account_id or
# "default"``, applied INSIDE build_bundle — a normalization the lifecycle never sees).
# The guard MUST apply the same one: writing a NULL PK half produces a row that silently
# never matches on any later connect, permanently disabling the guard for that account.
_DEFAULT_ACCOUNT_ID = "default"

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
) -> None:
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
    None
        Always. This function never raises into the caller and never halts.
    """
    resolved_account_id = account_id or _DEFAULT_ACCOUNT_ID

    uid = _fetch_uid(plugin, connector, venue_name, resolved_account_id)
    if uid is None:
        return

    try:
        row = store.get(venue_name, resolved_account_id)
    except Exception:
        # T-11-19: a storage outage must not abort a healthy connect. Logged loudly
        # because it means the spoofing detector is inert for this session.
        _logger.error(
            "venue-uid guard could not read the account row; the D-04 spoofing "
            "guard is inert for this connect",
            venue_name=venue_name,
            account_id=resolved_account_id,
            exc_info=True,
        )
        return

    if row is None:
        # No row for this pair yet — account MINTING is plan 11-07's job, and this
        # guard deliberately does not create rows (it would invent an operator record
        # from a connect-time code path).
        _logger.warning(
            "venue-uid guard found no account row; nothing recorded or asserted",
            venue_name=venue_name,
            account_id=resolved_account_id,
        )
        return

    recorded = row.get("venue_uid")

    if recorded is None:
        _record_uid(store, venue_name, resolved_account_id, uid, at)
        return

    if recorded == uid:
        return

    # THE detection (T-11-15). Alert; do NOT overwrite (T-11-20); return (T-11-19).
    _emit_mismatch_alert(
        alert_sink,
        venue_name,
        resolved_account_id,
        recorded=recorded,
        observed=uid,
        at=at,
    )


def _fetch_uid(
    plugin: Any, connector: Any, venue_name: str, account_id: str
) -> str | None:
    """The plugin's venue UID, or ``None``; warns when a CREDENTIALED venue supplies none.

    ``credential_model is None`` marks a venue with no credentials and therefore no
    venue-side account (paper) — its ``None`` is the expected clean no-op. A venue that
    DOES declare a credential model yielding ``None`` means its endpoint or field broke,
    which would otherwise disable the detector with no signal at all.
    """
    try:
        uid = plugin.fetch_venue_uid(connector)
    except Exception:
        # The Protocol says fetch_venue_uid must not raise; belt-and-braces so a
        # third-party plugin cannot break a healthy connect either (T-11-19).
        _logger.error(
            "venue-uid fetch raised; the D-04 spoofing guard is inert for this connect",
            venue_name=venue_name,
            account_id=account_id,
            exc_info=True,
        )
        return None

    if uid is not None:
        return str(uid)

    if getattr(plugin, "credential_model", None) is not None:
        _logger.warning(
            "venue-uid unavailable for a credentialed venue; the D-04 spoofing "
            "guard is inert for this connect",
            venue_name=venue_name,
            account_id=account_id,
        )
    return None


def _record_uid(
    store: Any, venue_name: str, account_id: str, uid: str, at: datetime
) -> None:
    """Trust-on-first-use write; a store failure is logged and swallowed (T-11-19)."""
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
        return
    _logger.info(
        "venue-uid recorded on first connect (trust-on-first-use)",
        venue_name=venue_name,
        account_id=account_id,
    )


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
