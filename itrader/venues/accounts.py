"""The venue-ACCOUNT domain: one spec, one manager, one routing map.

A durable ``venue_accounts`` row is the ONLY source of a live account's identity. This
module is everything that happens to such a row: ``AccountSpec`` is its typed in-memory
form, ``VenueAccountManager`` writes it, brings it online, retires it and enumerates what
is online, and the trust-on-first-use identity guard runs between the session opening and
the account becoming routable.

**``bring_online`` is registration-LAST.** Resolve the spec, validate and merge the
account's own config, open its session, build its execution adapter, connect it, assert
the venue's account identity, wire the halt + stream-state signals — and only then write
the ``(venue_name, account_id)`` routing entry the order path reads. Every earlier failure
therefore leaves the pair UNROUTABLE rather than routable against a session that never
opened. There is exactly one writer of that map, and the write is the last statement.

**One implementation, with boot as its bulk case.** An account provisioned at runtime must
be usable in the SAME process with no restart, so boot is
``for row in read_enabled_for(venue): bring_online(row)`` and a runtime provision is the
same call on one row. The alternative — a boot-time assembly path plus a second
"also assemble this new one" path beside it — is two implementations that agree the day
they are written and diverge on every change after.

**Teardown is per account.** ``bring_offline`` disconnects ITS OWN session and drops ITS
OWN routing entry. Retiring one account must not close the sessions of the accounts that
were not retired: those would stop receiving fills while still looking online.

**Why provisioning lives HERE and not on the live facade.** It is reached as
``system.venue_accounts.provision(...)``, mirroring how scripts already reach
``system.portfolio_handler.add_portfolio(...)``. ``bring_online`` is a DIRECT inline call
with the same threading posture ``add_portfolio`` has, never a queued CONTROL event: a
queued provision would return before the account was usable, reintroducing the two-step
timing this class exists to remove.

**Why the degrade policy lives in the MANAGER, not the store.** A missing
``venue_accounts`` table is the fresh-deployment state, not a fault, so ``read_enabled_for``
warns and returns ``[]``. ANY other fault propagates LOUD. The probe is deliberately
narrow — it tests for the TABLE and nothing else — because under DB-as-sole-truth a
swallowed read means zero accounts, and every persisted portfolio then refuses: N derived
errors hiding one real cause.

**Why it is not in the barrel.** ``venues/__init__.py`` imports no concretion, so importing
``itrader.venues`` pulls nothing heavy. This module is imported DIRECTLY by the live
composition root: it composes SQLAlchemy through its stores, and a barrel entry would put
that on the backtest import graph the inertness gate protects.

Manager convention: EXCLUSIVE ownership of its storage, no back-reference to a handler, and
NO events-queue access — layering is one-directional (facade -> manager -> storage).
Collaborators are RECEIVED at construction, never minted, and never ``Optional``.

Indentation: 4-space. ``mypy --strict`` applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping, Optional

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from itrader.core.exceptions import (
    DuplicateVenueAccountProvisionError,
    UnknownVenueAccountConfigKeyError,
    ValidationError,
    VenueAccountInUseError,
    VenueAccountNotProvisionedError,
)
from itrader.logger import get_itrader_logger
from itrader.outils.dict_merge import recursive_merge
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector
    from itrader.connectors.pool import ConnectorPool
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.venues.catalog import VenueDescriptor

#: An execution-adapter recipe: builds ONE account's adapter. ``spec`` is the account's
#: ``AccountSpec``, ``connector`` its session (``None`` for a venue that has none) and
#: ``ctx`` the shared ``EngineContext``.
#:
#: The adapter is treated STRUCTURALLY here, as it is in the routing map and on the online
#: record: the halt / stream-state seam a session-bearing adapter is wired through is
#: declared on the live adapters that have streams to escalate, not on the shared
#: execution contract, where a paper adapter would inherit it as a silent no-op.
ExchangeRecipe = Callable[..., Any]

#: The one table name the fresh-deployment probe tests for. Narrow BY DESIGN.
_ACCOUNTS_TABLE = "venue_accounts"

#: The EXHAUSTIVE set of ``venue_accounts.config_json`` keys that reach an ``AccountSpec``.
#:
#: **An EXPLICIT ALLOWLIST, and an unrecognised key RAISES.** These are the keys that
#: decide where an account's money goes: ``sandbox`` and ``region`` select the HOST an
#: authenticated session reaches (``region`` picks the regional entity — an EEA-issued key
#: answers 50119 on the global host — and ``sandbox`` picks demo vs PRODUCTION), while
#: ``market_type`` reaches the execution adapter and selects which channel it reads
#: position truth from. So a silently-dropped ``sandox`` typo does NOT degrade to a
#: harmless default: it leaves the account on whatever the ambient process environment
#: says, routing a live order to the production host while the operator believes the
#: account is pinned to demo. The raise IS the control; accepting a key that changes
#: nothing would be worse still.
#:
#: PRECEDENCE is one-directional: the ACCOUNT overrides the venue, and a key the account
#: does not name leaves the venue default in force.
_MERGEABLE_CONFIG_KEYS = frozenset({"sandbox", "region", "market_type"})

#: The VENUE-LEVEL baseline the account's own config is merged ONTO. Every value is
#: ``None`` — "this account names no override" — because the real defaults live with each
#: venue's own recipe and settings model; restating them here would be a second home that
#: drifts.
_VENUE_LEVEL_CONFIG: dict[str, Any] = {
    "sandbox": None,
    "region": None,
    "market_type": None,
}

#: The shared market-type vocabulary. Validated HERE, unlike ``region``, because a bad
#: value fails SILENTLY: ``"spott"`` is not ``"spot"``, so the adapter reads position truth
#: from the derivative channel and a coin-holding spot account reports FLAT. ``region``'s
#: vocabulary belongs to the VENUE (``OkxSettings.region`` is a ``Literal`` that fails loud
#: at build time), so a second copy here would only drift from it.
_LEGAL_MARKET_TYPES = ("spot", "derivative")


@dataclass(frozen=True, slots=True)
class AccountSpec:
    """One ``venue_accounts`` row, typed and in memory. Nothing more.

    Frozen so a spec cannot be retuned after the session it identifies has been built:
    ``secret_ref`` / ``sandbox`` / ``region`` are the fields that decide WHICH REAL SESSION
    a connector is, and the pool memoizes a session against exactly those values.

    ``secret_ref`` is a POINTER at wherever the credential lives (``env:<PREFIX>``), never a
    credential itself. ``None`` means "this account has no per-account credentials" — the
    supported paper shape, not a fail-open.

    ``sandbox`` / ``region`` / ``market_type`` are ``None`` when the row names no override,
    rather than carrying a concrete default: a real default here would be a second home for
    each venue's own default, and the two would drift.
    """

    venue_name: str
    account_id: str
    secret_ref: Optional[str] = None
    sandbox: Optional[bool] = None
    region: Optional[str] = None
    market_type: Optional[Literal["spot", "derivative"]] = None


# ---------------------------------------------------------------- identity guard
#
# **Why this exists.** Per-account credentials are what make the misroute reachable: a
# mistyped ``secret_ref`` or a swapped vault entry means an ``account_id`` connects with a
# different account's keys. Orders then route to the wrong real account and reconciliation
# succeeds cleanly against it — a silent, money-losing failure that only exists once
# multi-account exists. The venue's self-reported account UID is the only external evidence
# that the session belongs to the account the engine thinks it does.
#
# **Trust on first use.** The FIRST bring-up for a ``(venue_name, account_id)`` pair RECORDS
# the observed UID; every later one ASSERTS against it. The rejected alternative — an
# operator-declared expected UID — adds one more value to look up and mistype, and a wrong
# expected value would block a correctly-configured account. Recording removes the operator
# from the loop entirely, so there is no typo surface at all.
#
# **Observe-only, by explicit decision.** A mismatch fires a CRITICAL alert through the
# existing sink and RETURNS NORMALLY. It does NOT halt (a venue reporting its UID
# differently across endpoints must not take a correctly-configured account offline) and it
# does NOT overwrite the stored value (overwriting would make the guard self-healing — it
# would alert once and then accept the impostor forever).
#
# **Fail-safe, but never fail-SILENT.** Store failures are swallowed so the guard cannot
# break an otherwise healthy bring-up. That fail-safety is also a hazard: a renamed venue
# field or a storage outage would otherwise permanently disable the only spoofing detector
# with zero signal. So every degraded path LOGS — and a venue that DECLARES a credential
# model (i.e. one that should have a venue-side identity) yielding no UID logs a WARNING
# rather than passing silently.

# The FIXED LITERAL alert reason (the reconciliation-coordinator discipline): alert and halt
# reasons are constants, never a stringified exception and never an interpolated payload, so
# an operator alert-rule can match on them and no exception text can smuggle unvetted content
# into the egress channel.
VENUE_UID_MISMATCH_REASON = "venue-uid-mismatch"

#: The two top-level outcomes. ``armed`` means the guard is actually protecting this
#: session (it recorded on first connect, asserted a match, or DETECTED a mismatch — a
#: detection is the guard at its most armed, never an idle state). ``inert`` means the
#: guard produced no protection this bring-up, and the reason names why.
GUARD_ARMED = "armed"
GUARD_INERT = "inert"

#: The ARMED sub-reasons — the guard worked, told three ways apart so the status can
#: distinguish "just learned this account's identity" from "confirmed it" from "caught an
#: impostor".
REASON_RECORDED_FIRST_CONNECT = "recorded-first-connect"
REASON_ASSERTED_MATCH = "asserted-match"
REASON_MISMATCH_ALERTED = "mismatch-alerted"

#: The six inert paths. Each needs a DIFFERENT operator investigation, so none may collapse
#: into another:
#:  1. the adapter's ``fetch_venue_uid`` RAISED — an adapter broke its no-raise contract;
#:     fix the adapter.
REASON_FETCH_RAISED = "fetch-raised"
#:  2. a CREDENTIALED venue supplied no uid — its endpoint or the ``uid`` field was renamed,
#:     or the read scope was revoked; restore the venue-side identity read.
REASON_UID_UNAVAILABLE_CREDENTIALED = "uid-unavailable-credentialed"
#:  3. the venue declares NO credentials and has no venue-side identity (paper) — the one
#:     BENIGN inert path; nothing to fix.
REASON_NO_VENUE_IDENTITY = "no-venue-identity"
#:  4. the store READ failed — the database is unreachable; restore the read path.
REASON_STORE_READ_FAILED = "store-read-failed"
#:  5. no account ROW for this pair yet — provision the account.
REASON_NO_ACCOUNT_ROW = "no-account-row"
#:  6. the first-connect record WRITE failed — a read-only replica or a write outage; the
#:     guard stays inert for this pair until the write succeeds.
REASON_RECORD_WRITE_FAILED = "record-write-failed"


@dataclass(frozen=True)
class VenueUidGuardOutcome:
    """What the identity guard did for one bring-up — outcome AND reason.

    Frozen so a recorded outcome cannot be mutated after the fact. ``outcome`` and
    ``reason`` carry the WHICH-hole detail a bare ``armed`` boolean cannot: two guards that
    are both ``armed is False`` for different reasons (a paper no-op vs a database outage)
    are NOT the same operational state.
    """

    armed: bool
    outcome: str
    reason: str

    @classmethod
    def armed_with(cls, reason: str) -> "VenueUidGuardOutcome":
        """The guard protected this bring-up; ``reason`` says how (record/assert/detect)."""
        return cls(armed=True, outcome=GUARD_ARMED, reason=reason)

    @classmethod
    def inert_with(cls, reason: str) -> "VenueUidGuardOutcome":
        """The guard produced no protection this bring-up; ``reason`` names which hole."""
        return cls(armed=False, outcome=GUARD_INERT, reason=reason)


_logger = get_itrader_logger().bind(component="VenueUidGuard")


def assert_venue_uid(
    *,
    descriptor: Any,
    adapter: Any,
    venue_name: str,
    account_id: str,
    store: Any,
    alert_sink: Any,
    at: datetime,
) -> VenueUidGuardOutcome:
    """Record (first bring-up) or assert (later ones) the venue's account UID.

    Parameters
    ----------
    descriptor :
        The venue's catalogue entry. Its ``credential_model`` is read for one purpose
        only: telling a credential-less venue's legitimate ``None`` apart from a
        credentialed venue's silent degradation.
    adapter :
        The freshly-connected execution adapter — it owns the session, so it is what
        reads the venue's account identity off it.
    venue_name, account_id :
        The composite natural key of the ``venue_accounts`` row, used VERBATIM — no
        substitution. Substituting here would let the guard record an unnamed account
        under a fabricated key while the registration side keyed it differently, leaving
        the recorded row unreachable by any later bring-up.
    store :
        The ``VenueAccountStore`` holding the recorded ``venue_uid``.
    alert_sink :
        The existing CRITICAL egress seam.
    at :
        The business timestamp for the record write (the store is clock-free).

    Returns
    -------
    VenueUidGuardOutcome
        The armed/inert outcome and its reason. This function never raises into the caller
        and never halts — an inert outcome is how every degraded path reports itself, so
        the caller can surface WHICH hole it has.
    """
    uid, fetch_inert_reason = _fetch_uid(descriptor, adapter, venue_name, account_id)
    if uid is None:
        # Paths 1-3 live in _fetch_uid; it returns the specific reason so the three do not
        # collapse into one "no uid".
        assert fetch_inert_reason is not None
        return VenueUidGuardOutcome.inert_with(fetch_inert_reason)

    try:
        row = store.get(venue_name, account_id)
    except Exception:
        # Path 4. A storage outage must not abort a healthy bring-up. Logged loudly because
        # it means the spoofing detector is inert for this session.
        _logger.error(
            "venue-uid guard could not read the account row; the spoofing guard is "
            "inert for this bring-up",
            venue_name=venue_name,
            account_id=account_id,
            exc_info=True,
        )
        return VenueUidGuardOutcome.inert_with(REASON_STORE_READ_FAILED)

    if row is None:
        # Path 5. No row for this pair yet — this guard deliberately does not create rows
        # (it would invent an operator record from a connect-time code path).
        _logger.warning(
            "venue-uid guard found no account row; nothing recorded or asserted",
            venue_name=venue_name,
            account_id=account_id,
        )
        return VenueUidGuardOutcome.inert_with(REASON_NO_ACCOUNT_ROW)

    recorded = row.get("venue_uid")

    if recorded is None:
        if not _record_uid(store, venue_name, account_id, uid, at):
            # Path 6. The write failed; the guard stays inert for this pair until it
            # succeeds. Distinct from the READ failure above — a different fix.
            return VenueUidGuardOutcome.inert_with(REASON_RECORD_WRITE_FAILED)
        return VenueUidGuardOutcome.armed_with(REASON_RECORDED_FIRST_CONNECT)

    if recorded == uid:
        return VenueUidGuardOutcome.armed_with(REASON_ASSERTED_MATCH)

    # THE detection. Alert; do NOT overwrite; return without halting.
    _emit_mismatch_alert(
        alert_sink, venue_name, account_id, recorded=recorded, observed=uid, at=at)
    return VenueUidGuardOutcome.armed_with(REASON_MISMATCH_ALERTED)


def _fetch_uid(
    descriptor: Any, adapter: Any, venue_name: str, account_id: str
) -> tuple[Optional[str], Optional[str]]:
    """The adapter's venue UID, or ``(None, inert_reason)``.

    Returns ``(uid, None)`` on success, or ``(None, reason)`` naming WHICH of the three
    no-uid paths produced it so the caller can keep them distinct:

    * ``descriptor.credential_model is None`` marks a venue with no credentials and
      therefore no venue-side account (paper) — the expected clean no-op
      (``REASON_NO_VENUE_IDENTITY``).
    * a venue that DECLARES a credential model yet yields ``None`` broke its endpoint or
      renamed the field (``REASON_UID_UNAVAILABLE_CREDENTIALED``).
    * an adapter that RAISED violated the no-raise contract (``REASON_FETCH_RAISED``).
    """
    try:
        uid = adapter.fetch_venue_uid()
    except Exception:
        # Path 1. The adapter contract says fetch_venue_uid must not raise; belt-and-braces
        # so a broken adapter cannot break a healthy bring-up either.
        _logger.error(
            "venue-uid fetch raised; the spoofing guard is inert for this bring-up",
            venue_name=venue_name,
            account_id=account_id,
            exc_info=True,
        )
        return None, REASON_FETCH_RAISED

    if uid is not None:
        return str(uid), None

    if getattr(descriptor, "credential_model", None) is not None:
        # Path 2. A venue that should expose a UID but does not.
        _logger.warning(
            "venue-uid unavailable for a credentialed venue; the spoofing guard is "
            "inert for this bring-up",
            venue_name=venue_name,
            account_id=account_id,
        )
        return None, REASON_UID_UNAVAILABLE_CREDENTIALED

    # Path 3. The BENIGN inert path — a credential-less venue (paper) has no identity.
    return None, REASON_NO_VENUE_IDENTITY


def _record_uid(
    store: Any, venue_name: str, account_id: str, uid: str, at: datetime
) -> bool:
    """Trust-on-first-use write; a store failure is logged and swallowed.

    Returns ``True`` when the write landed, ``False`` when it failed — the caller turns a
    ``False`` into the ``REASON_RECORD_WRITE_FAILED`` inert outcome (path 6), kept distinct
    from the READ failure (path 4) because the two need different fixes.
    """
    try:
        store.record_venue_uid(venue_name, account_id, uid, at)
    except Exception:
        _logger.error(
            "venue-uid guard could not record the first-connect uid; the spoofing "
            "guard stays inert for this pair until it succeeds",
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

    The payload carries the pair and BOTH UIDs so an operator can act, and NOTHING else: no
    credential material and no ``secret_ref`` value ever reach the egress channel.
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
        # Even the egress cannot be allowed to abort the bring-up. Logged at CRITICAL so
        # the detection is not lost with the alert.
        _logger.critical(
            "venue-uid MISMATCH detected but the alert sink failed",
            venue_name=venue_name,
            account_id=account_id,
            recorded_venue_uid=recorded,
            observed_venue_uid=observed,
            exc_info=True,
        )


# ---------------------------------------------------------------- online record


@dataclass(frozen=True)
class OnlineAccount:
    """What ``bring_online`` built for one ``(venue_name, account_id)`` pair.

    Held together under the pair that owns them rather than shattered into parallel scalar
    maps, which is how one account ends up split across several aliases that disagree.
    ``spec`` rides alongside the adapter because it carries the account's ``secret_ref`` —
    the ONE record of which credentials this session was built with.

    ``connector`` is ``None`` for a venue with no session (paper): the record is then a
    fully-formed online account, not a degraded one.
    """

    spec: AccountSpec
    adapter: Any
    connector: Optional["LiveConnector"]
    uid_outcome: VenueUidGuardOutcome


class VenueAccountManager:
    """Owns the venue-ACCOUNT domain: provision, bring online, retire, enumerate.

    Parameters
    ----------
    store :
        The durable ``VenueAccountStore``, EXCLUSIVELY owned and never ``None``.
    pool :
        The shared ``ConnectorPool``. One authenticated session per account, built on
        first ask and torn down by the account that owns it.
    routing :
        The composition-root-owned ``(venue_name, account_id) -> adapter`` map — the SAME
        object ``ExecutionHandler`` reads on order, which ``bring_online`` writes into as
        its LAST step. Injecting the bare map rather than the execution handler is what
        keeps the manager from reaching THROUGH it. Typed ``Any`` because naming the
        concrete element type would drag ``AbstractExchange`` onto this import graph.
    catalog :
        The venue catalogue. Supplies each venue's static facts — notably
        ``credential_model``, which decides whether a venue has a session to open and
        whether a missing UID is benign.
    exchange_recipes :
        Venue name to execution-adapter recipe. A plain mapping of functions: selecting a
        venue is a dict lookup, and the construction knowledge lives beside what it builds.
    ctx :
        The shared ``EngineContext`` every recipe reads (the bus, the seeded rng, the
        stream config).
    alert_sink :
        The CRITICAL-escalation egress the identity guard alerts through. Required, not
        optional: an account brought online with nowhere to escalate an identity mismatch
        is a silently-disarmed guard.
    halt_signal :
        The connector-loop halt callback wired onto every session-bearing adapter and its
        connector. Required: an adapter whose streams cannot escalate a fatal error keeps
        looking healthy while it has stopped delivering fills.
    stream_state_listener :
        The ``(on_down, on_up)`` pair wired alongside it, so a dropped stream pauses
        submission and a recovered one drives the resume path.
    feed_binder :
        The ``FeedConnectionBinder`` this manager DRIVES; it owns the data-provider build,
        the feed wiring and the re-borrow rule. Required, not optional: a manager that
        could bring an account online with no feed to connect it to would silently ship a
        live boot that receives no bars.
    """

    def __init__(
        self,
        *,
        store: VenueAccountStore,
        pool: ConnectorPool,
        routing: Any,
        catalog: Mapping[str, VenueDescriptor],
        exchange_recipes: Mapping[str, ExchangeRecipe],
        ctx: Any,
        alert_sink: Any,
        halt_signal: Callable[[str], None],
        stream_state_listener: tuple[Callable[[str], None], Callable[[str], None]],
        feed_binder: Any,
    ) -> None:
        self._store = store
        self._pool = pool
        self._routing = routing
        self._catalog = catalog
        self._recipes = exchange_recipes
        self._ctx = ctx
        self._alert_sink = alert_sink
        self._halt_signal = halt_signal
        self._stream_state_listener = stream_state_listener
        self._feed_binder = feed_binder
        # The DURABLE read backing the account-disable refusal, built over the SAME shared
        # ``SqlEngine`` this manager's store already owns — no new injected collaborator to
        # re-thread through the composition root. A READ-ONLY view: reading the block here
        # keeps the manager free of a portfolio-handler back-reference, preserving the
        # one-directional layering. ``build_portfolio_definition_tables`` registers
        # idempotently on the shared MetaData, so a second view over the same spine is safe.
        self._portfolio_definitions = PortfolioDefinitionStore(store.backend)
        # Keyed on the PAIR, the same key the routing map and the connector memo use. A
        # second memo on any other key is how those registries end up disagreeing about an
        # account.
        self._online: dict[tuple[str, str], OnlineAccount] = {}
        self.logger = get_itrader_logger().bind(component="VenueAccountManager")

    # ------------------------------------------------------------------ reads

    @property
    def pool(self) -> ConnectorPool:
        """The shared session pool this manager builds every account's session from."""
        return self._pool

    def read_enabled_for(self, venue_name: str) -> list[Mapping[str, Any]]:
        """This venue's ENABLED account rows, or ``[]`` on a fresh deployment.

        The account SET is STORE-DERIVED and VENUE-SCOPED: read off durable rows rather
        than re-derived from a spec, and one venue never sees another's accounts
        (``account_id`` alone cannot derive its venue). Ordering follows the store's
        ``venue_name`` / ``account_id`` ASC contract, so bring-up order is reproducible
        across runs and dialects. Zero enabled rows is a SUPPORTED state: a fresh
        deployment comes up RUNNING and empty.

        The degrade is deliberately narrow. A missing ``venue_accounts`` TABLE is the
        fresh-deployment state — a new database, or an Alembic chain that has not run — so
        warn and return ``[]``. Every other fault PROPAGATES. Widening this to a catch-all
        over the base exception type would convert one real cause (an unreachable database,
        a permissions error) into zero accounts, and from there into a refusal for every
        persisted portfolio: N derived errors burying the one that matters.

        The warning goes through the bound structlog logger, never the stdlib warnings
        module — the suite runs under ``filterwarnings=["error"]``, so a stdlib warning on
        the fresh-deployment path would fail every test that reached it.
        """
        if not sa_inspect(self._store.engine).has_table(_ACCOUNTS_TABLE):
            self.logger.warning(
                "The `%s` table is not provisioned — no venue account will come online "
                "for venue %r until the schema exists (first start, or the Alembic chain "
                "has not run). Boot continues with zero accounts.",
                _ACCOUNTS_TABLE, venue_name)
            return []
        return self._store.read_enabled_for(venue_name)

    def is_online(self, venue_name: str, account_id: str) -> bool:
        """Whether ``bring_online`` built a runtime for this pair IN THIS PROCESS."""
        return (venue_name, account_id) in self._online

    def online_records(self) -> list[OnlineAccount]:
        """Every runtime ``bring_online`` built, in bring-up order.

        The ONE enumeration the safety and reconcile planes read. They ask this at USE time
        rather than being handed a container at build time, which is what makes "an account
        is online but the consumer's list is empty" unrepresentable: there is no second
        container to forget to populate, and an account brought online after those
        collaborators were constructed is covered automatically.

        Distinct BY CONSTRUCTION — the map is keyed by ``(venue_name, account_id)``, so a
        caller needs no identity de-duplication pass to avoid acting on one account twice.

        A copy, so a caller iterating it cannot be tripped by a concurrent bring-up
        mutating the map underneath.
        """
        return list(self._online.values())

    def venue_uid_guard_active(self) -> dict[tuple[str, str], VenueUidGuardOutcome]:
        """The identity-guard outcome for EVERY online pair.

        Carries OUTCOME + REASON per ``(venue_name, account_id)`` rather than a bare
        boolean, because a boolean tells an operator the guard is off but not WHICH of its
        holes they have — and the holes need different fixes.

        In-memory only; nothing is persisted.
        """
        return {pair: record.uid_outcome for pair, record in self._online.items()}

    def online(self, venue_name: str, account_id: str) -> OnlineAccount:
        """The runtime ``bring_online`` built for this pair; refuses when there is none.

        Fails loud rather than returning ``None`` — a caller that can silently receive "no
        runtime" is a caller that will proceed without one.
        """
        key = (venue_name, account_id)
        if key not in self._online:
            raise VenueAccountNotProvisionedError(
                venue_name, account_id, VenueAccountNotProvisionedError.NOT_ONLINE)
        return self._online[key]

    def spec_for(self, row: Mapping[str, Any]) -> AccountSpec:
        """One durable row as an ``AccountSpec``, with its config VALIDATED and merged.

        The single row->spec translation. It carries the row's OWN ``secret_ref``: without
        it every NAMED account silently reverts to the ambient credentials and two accounts
        authenticate as one. A NULL ``secret_ref`` is NOT that fail-open case — it means
        "this account has no per-account credentials", the supported paper shape.

        Validation runs HERE, ahead of everything the spec is used for, so a refused config
        produces no spec and therefore nothing online: a refusal that had already opened a
        session would leave a live authenticated connection for a config the engine
        declined to understand.
        """
        venue_name = str(row["venue_name"])
        account_id = str(row["account_id"])
        secret_ref = row.get("secret_ref")
        overrides = self.merge_account_config(
            venue_name, account_id, row.get("config"))
        return AccountSpec(
            venue_name=venue_name,
            account_id=account_id,
            secret_ref=str(secret_ref) if secret_ref else None,
            **overrides,
        )

    # ------------------------------------------------------------------ writes

    def provision(
        self,
        venue_name: str,
        account_id: str,
        *,
        secret_ref: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """CREATE one durable ``venue_accounts`` row and return it.

        The config allowlist/value checks run BEFORE the durable write, so a row the engine
        could never bring online is never persisted. Validating only at bring-up time would
        let ``provision`` report success on a row whose next boot refuses — the operator
        learns about the typo one restart away from the action that caused it.

        Create-only. A second ``provision`` of the same pair raises
        ``DuplicateVenueAccountProvisionError`` and writes NOTHING — the database's
        composite primary key is the arbiter and its ``IntegrityError`` is classified on the
        ERROR path. There is deliberately no pre-check ``SELECT``: a pre-check is TOCTOU
        and, decisively, cannot bind the out-of-band writers a durable table always has.

        It does NOT bring the account online. ``provision`` (the durable write) and
        ``bring_online`` (the runtime build) are two verbs by design: a caller wanting the
        account usable in this process performs both, explicitly, with no restart between.
        The split is also what makes an interrupted provision safe — an enabled row with no
        runtime is exactly what the next boot brings online.

        The secret-key denylist is NOT re-implemented here. ``VenueAccountStore`` runs the
        single recursive guard as the first statement of its write, before any transaction
        opens, so a ``config`` carrying a secret-looking key persists nothing. A second
        denylist here would be a drifting duplicate of the one control — membership is
        EXACT, so ``"credential"`` is denied while ``"credentials"`` passes by one letter.

        ``secret_ref`` is a POINTER at wherever the credential lives (``env:<PREFIX>``),
        never a credential itself.
        """
        account_config = dict(config) if config is not None else {}
        self.merge_account_config(venue_name, account_id, account_config)
        # The write timestamp is minted at the CALL SITE: the store is clock-free and takes
        # a caller-supplied ``at``, the same idiom every durable-write caller uses.
        self._create_row(
            venue_name,
            account_id,
            secret_ref=secret_ref,
            config=account_config,
            at=datetime.now(UTC),
        )
        row = self._store.get(venue_name, account_id)
        if row is None:  # pragma: no cover - a committed INSERT is always readable back
            raise VenueAccountNotProvisionedError(
                venue_name, account_id,
                VenueAccountNotProvisionedError.NOT_PROVISIONED)
        self.logger.info(
            "Provisioned venue account (%s, %s)", venue_name, account_id)
        return row

    def _create_row(
        self,
        venue_name: str,
        account_id: str,
        *,
        secret_ref: Optional[str],
        config: dict[str, Any],
        at: datetime,
    ) -> None:
        """Delegate the create-only write and CLASSIFY the database's duplicate refusal.

        The classification sits on the ERROR path rather than in front of the write: the
        uniqueness decision belongs to the database, the one participant that sees every
        writer.
        """
        try:
            self._store.create(
                venue_name,
                account_id,
                secret_ref=secret_ref,
                venue_uid=None,
                enabled=True,
                config=config,
                at=at,
            )
        except IntegrityError as exc:
            raise DuplicateVenueAccountProvisionError(venue_name, account_id) from exc

    def set_enabled(self, venue_name: str, account_id: str, enabled: bool) -> None:
        """Enable/disable a venue account durably, REFUSING a disable a live portfolio needs.

        The row must EXIST. A ``set_enabled`` against a pair that was never provisioned
        would otherwise write nothing and report success, leaving the operator believing an
        account is disabled — or enabled — when no such account exists at all.

        Disabling an account no live portfolio references succeeds; disabling one a LIVE
        portfolio still depends on raises ``VenueAccountInUseError`` naming the account, the
        blocking portfolio ids, and the remediation. A disable that raises writes NOTHING —
        the check runs BEFORE the store write.

        **"Live" is resolved against the DURABLE store, not in-memory portfolio state.** A
        blocking portfolio is one whose definition row has ``enabled = True AND NOT
        is_deleted``. Pause and retire are DURABLE, so the block a disable must respect is
        durable too, and reading it here keeps the manager free of a portfolio-handler
        back-reference. A PAUSED portfolio does NOT block — which is exactly why pausing is
        the sanctioned way to release the block — and a RETIRED one has already released
        its pair.

        **Independence.** Account-``enabled`` and portfolio-``enabled`` are independent.
        Disabling a PORTFOLIO must NEVER touch its account (a venue account is a real
        external thing outliving any number of internal portfolios), and symmetrically
        disabling the ACCOUNT is refused while a live portfolio needs it.

        **Out-of-band case.** An account disabled behind the engine's back — a future
        integrations page writing the row directly, which this in-band refusal cannot bind —
        is simply never brought online: ``read_enabled_for`` skips it and ``assert_available``
        raises DISABLED, so its portfolios hit the composition-time refusal and the boot
        fails LOUD rather than trading against a leaf with no venue truth. Enabling is never
        refused.
        """
        if self._store.get(venue_name, account_id) is None:
            raise VenueAccountNotProvisionedError(
                venue_name, account_id,
                VenueAccountNotProvisionedError.NOT_PROVISIONED)
        if not enabled:
            blocking = self._portfolio_definitions.live_portfolio_ids_for_account(
                venue_name, account_id)
            if blocking:
                raise VenueAccountInUseError(venue_name, account_id, list(blocking))
        self._store.set_enabled(venue_name, account_id, enabled, datetime.now(UTC))
        self.logger.info(
            "Set venue account (%s, %s) enabled=%s", venue_name, account_id, enabled)

    def bring_online(self, row: Mapping[str, Any]) -> OnlineAccount:
        """Turn ONE durable account row into a live, routable venue account.

        REGISTRATION IS LAST. The steps below run in this order because each one can fail,
        and a failure must leave the pair unroutable:

        1. Resolve the row into an ``AccountSpec`` — config validated and merged.
        2. Open the account's OWN session through the pool, when its venue has one to open.
           A venue that declares no credential model has no authenticated session and no
           venue-side identity; paper is that case.
        3. Build the execution adapter through the venue's recipe, over that session.
        4. Connect: the session first, then the adapter (which spawns its fill/order
           streams). ``AbstractExchange.connect`` RETURNS a result rather than raising, so
           an unsuccessful one is turned into a raise here — a bare call would swallow it
           and register an adapter whose streams never started, leaving every order mirror
           PENDING forever while the account looked healthy.
        5. Assert the venue's account identity (trust on first use) before the account can
           receive an order, so a misrouted session is flagged before anything trades.
        6. Wire the halt + stream-state signals, so the account is never routable while its
           streams have no way to escalate a failure.
        7. ONLY THEN write the routing map and the online record.

        The routing key is the row's ``(venue_name, account_id)`` VERBATIM, never coerced to
        a default: that key must be byte-identical to the one the order path builds when it
        reads, or the venue registers an account no order can reach.

        A pair that is ALREADY online is returned as-is rather than rebuilt: one pair has
        one session and one adapter, and a second build would double-spawn that account's
        streams.
        """
        venue_name = str(row["venue_name"])
        account_id = str(row["account_id"])
        key = (venue_name, account_id)
        existing = self._online.get(key)
        if existing is not None:
            return existing

        spec = self.spec_for(row)
        descriptor = self._descriptor_for(venue_name)
        recipe = self._recipe_for(venue_name)

        connector: Optional[LiveConnector] = None
        if descriptor.credential_model is not None:
            connector = self._pool.session(venue_name, account_id, spec)
            connector.connect()

        try:
            record = self._connect_and_verify(
                spec, descriptor, recipe, connector, venue_name, account_id)
        except Exception:
            # A bring-up that opened a session and then failed must not leave that session
            # open: the account is unroutable, so nothing will ever use it, and an
            # authenticated socket with no owner is exactly the abandoned resource this
            # redesign removes. Closing only THIS pair's session leaves every other
            # account untouched.
            if connector is not None:
                self._pool.close_session(venue_name, account_id)
            raise

        self._routing[key] = record.adapter
        self._online[key] = record
        self.logger.info(
            "Brought venue account (%s, %s) online", venue_name, account_id)
        # Re-evaluate the ONE feed's borrowed connection, so a runtime provision binds the
        # feed with no restart. A boot's per-row bring_online binds on the first streaming
        # account and no-ops on the rest.
        self.rebind_feed()
        return record

    def _connect_and_verify(
        self,
        spec: AccountSpec,
        descriptor: VenueDescriptor,
        recipe: ExchangeRecipe,
        connector: Optional[LiveConnector],
        venue_name: str,
        account_id: str,
    ) -> OnlineAccount:
        """Build, connect, identity-check and arm one account's adapter.

        Everything ``bring_online`` must complete BEFORE the account is registered. Split
        out so the failure path has one place to release the session, and so the routing
        write in ``bring_online`` reads as the single last statement it is.
        """
        adapter = recipe(spec=spec, connector=connector, ctx=self._ctx)
        result = adapter.connect()
        if not result.success:
            raise RuntimeError(
                f"venue account ({venue_name!r}, {account_id!r}) failed to connect: "
                f"{result.error_message}")

        uid_outcome = assert_venue_uid(
            descriptor=descriptor,
            adapter=adapter,
            venue_name=venue_name,
            account_id=account_id,
            store=self._store,
            alert_sink=self._alert_sink,
            # Wall clock is correct here: this is a LIVE session-identity observation, not
            # an engine-path business time, and the store is clock-free by design.
            at=datetime.now(UTC),
        )
        if uid_outcome.reason == REASON_MISMATCH_ALERTED:
            # The guard itself stays observe-only — it alerts and reports, it never halts
            # the engine, because a venue reporting its UID differently across endpoints
            # must not take a whole deployment offline. Refusing to make THIS ONE account
            # routable is the proportionate response, and registration being the last step
            # is what makes it expressible: the pair stays unroutable and its session is
            # released, while every other account stays online.
            raise ValidationError(
                "venue_uid",
                account_id,
                f"Venue account ({venue_name!r}, {account_id!r}) reported a DIFFERENT "
                f"account identity than the one recorded on its first connect. Refusing "
                f"to bring it online: the session may be authenticated with another "
                f"account's credentials, so every order routed to this pair would reach a "
                f"different real venue balance while reconciliation succeeded cleanly "
                f"against it.",
            )

        if connector is not None:
            on_down, on_up = self._stream_state_listener
            adapter.set_halt_signal(self._halt_signal)
            adapter.set_stream_state_listener(on_down, on_up)
            connector.set_halt_signal(self._halt_signal)

        return OnlineAccount(
            spec=spec, adapter=adapter, connector=connector, uid_outcome=uid_outcome)

    def bring_offline(self, venue_name: str, account_id: str) -> None:
        """Retire ONE online account: its adapter, its session, its routing entry.

        Scoped to this account and nothing else. Tearing down the whole pool to retire one
        account would close every OTHER account's session too, so accounts that were not
        retired would stop receiving fills while still reporting online.

        The routing entry goes first, so an account whose disconnect raises is already
        unroutable rather than routable against a half-torn-down session. A pair that is
        not online is a clean no-op — teardown runs on every path, including one where
        bring-up never completed.
        """
        key = (venue_name, account_id)
        record = self._online.pop(key, None)
        self._routing.pop(key, None)
        if record is None:
            return
        try:
            record.adapter.disconnect()
        except Exception:
            self.logger.error(
                "venue adapter disconnect failed for account (%s, %s)",
                venue_name, account_id, exc_info=True)
        if record.connector is not None:
            self._pool.close_session(venue_name, account_id)
        self.logger.info(
            "Brought venue account (%s, %s) offline", venue_name, account_id)
        self.rebind_feed()

    def _descriptor_for(self, venue_name: str) -> VenueDescriptor:
        """This venue's catalogue entry, or a ``KeyError`` naming what IS supported."""
        try:
            return self._catalog[venue_name]
        except KeyError:
            raise KeyError(
                f"unsupported venue {venue_name!r} — the catalogue supports "
                f"{sorted(self._catalog)}") from None

    def _recipe_for(self, venue_name: str) -> ExchangeRecipe:
        """This venue's execution-adapter recipe, or a ``KeyError`` naming what IS built."""
        try:
            return self._recipes[venue_name]
        except KeyError:
            raise KeyError(
                f"no execution-adapter recipe for venue {venue_name!r} — this system "
                f"builds {sorted(self._recipes)}") from None

    # ------------------------------------------------------------------ feed binding

    def rebind_feed(self) -> None:
        """Re-point the ONE live feed at a valid venue connection.

        Called from ``bring_online`` / ``bring_offline``, so a runtime provision or retire
        binds without a restart, and once by the boot after its bring-up loop, so a
        zero-account boot still logs the unbound-feed warning. Idempotent — a valid,
        unchanged binding is a no-op.
        """
        self._feed_binder.rebind(self._streaming_available())

    def _streaming_available(self) -> list[tuple[str, str, AccountSpec]]:
        """The online accounts whose connection the feed may borrow, in bring-up order.

        A candidate is an online pair carrying a live SESSION (paper carries none) AND whose
        durable row is still ENABLED — a disabled account is retired, so the feed must
        re-borrow off it. Insertion order is preserved (dict order = bring-up order = the
        store's ``account_id`` ASC), so the borrowed connection is reproducible.
        """
        available: list[tuple[str, str, AccountSpec]] = []
        for (venue_name, account_id), record in self._online.items():
            if record.connector is None:
                continue
            row = self._store.get(venue_name, account_id)
            if row is None or not row["enabled"]:
                continue
            available.append((venue_name, account_id, record.spec))
        return available

    @property
    def feed_provider(self) -> Any:
        """The provider currently bound to the ONE feed, or ``None``.

        Read by the halt-signal wiring and by the live session's warmup/subscribe step, so
        the account domain stays the single answer to "which connection is the feed on".
        Both readers None-guard it — a zero-account boot leaves it None.
        """
        return self._feed_binder.feed_provider

    # ------------------------------------------------------------------ config merge

    def merge_account_config(
        self,
        venue_name: str,
        account_id: str,
        config: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate and merge one account's ``config_json`` overrides.

        The ONLY reader ``venue_accounts.config_json`` has. Three steps, in this order:

        1. **REFUSE any key outside the allowlist** — see ``_MERGEABLE_CONFIG_KEYS`` for why
           a silently-dropped ``sandox`` typo is a live-order misroute rather than a harmless
           default.
        2. **REFUSE an out-of-vocabulary value** for the keys whose bad value would fail
           SILENTLY (``_assert_config_values``).
        3. **MERGE, account over venue**, through the shared ``recursive_merge`` helper. The
           overlay is flat today, but that helper is the tree's ONE merge mechanism and
           hand-rolling a second is exactly the drift it was promoted to prevent.

        ``None`` (an out-of-band writer left ``config_json`` NULL) and ``{}`` are
        INDISTINGUISHABLE here: both mean "this account names no overrides", both leave every
        venue default in force, and neither raises. Making one an error would render a valid
        row un-bringable depending on which writer created it.

        Returns the keyword overrides for ``AccountSpec``, every unnamed key carrying
        ``None`` — the spec's own "no override" value.
        """
        account_config = dict(config) if config else {}
        unknown = set(account_config) - _MERGEABLE_CONFIG_KEYS
        if unknown:
            raise UnknownVenueAccountConfigKeyError(
                venue_name, account_id,
                sorted(unknown), sorted(_MERGEABLE_CONFIG_KEYS))
        self._assert_config_values(venue_name, account_id, account_config)
        # Account OVER venue, one direction only.
        return recursive_merge(_VENUE_LEVEL_CONFIG, account_config)

    def _assert_config_values(
        self,
        venue_name: str,
        account_id: str,
        account_config: dict[str, Any],
    ) -> None:
        """Refuse an allowlisted key whose VALUE would fail silently.

        The allowlist stops a key the engine does not understand; this stops a key it
        understands carrying something it cannot act on. Only the keys whose bad value is
        SILENT are checked — a loud failure downstream is a better guard than a duplicated
        one:

        * ``market_type`` — the execution adapter selects its position-truth channel from
          it, so ``"spott"`` sails through AS a derivative and a spot account's holdings are
          read from a channel that is always empty, with nothing raising.
        * ``sandbox`` — a JSON column holds the STRING ``"false"`` happily, and every Python
          truthiness test then reads it as ``True``, flipping an account between the demo and
          the PRODUCTION host.

        ``region`` is deliberately NOT checked: its vocabulary belongs to the venue
        (``OkxSettings.region`` is a ``Literal`` that raises on anything else), and restating
        an OKX-specific entity list in the venue-agnostic account domain is a copy that
        drifts the day a venue adds a region.
        """
        market_type = account_config.get("market_type")
        if market_type is not None and market_type not in _LEGAL_MARKET_TYPES:
            raise ValidationError(
                "market_type",
                str(market_type),
                f"Venue account ({venue_name!r}, {account_id!r}) names an unknown "
                f"market_type; the legal values are {list(_LEGAL_MARKET_TYPES)}. "
                f"Refusing it: an unrecognised value would be treated as a derivative when "
                f"the execution adapter reads venue truth, so a spot account's position "
                f"would be read from a channel that is always empty — reporting FLAT while "
                f"the account holds coins.",
            )

        sandbox = account_config.get("sandbox")
        # ``isinstance(True, int)`` is True, so the check is on ``bool`` specifically — a
        # JSON ``1``/``0`` is not a boolean and must not be coerced into one here.
        if sandbox is not None and not isinstance(sandbox, bool):
            raise ValidationError(
                "sandbox",
                str(sandbox),
                f"Venue account ({venue_name!r}, {account_id!r}) names a non-boolean "
                f"sandbox. Refusing it: a JSON string such as 'false' is TRUTHY, so the "
                f"account would connect to the opposite host from the one configured — "
                f"demo instead of production, or production instead of demo.",
            )

    # ------------------------------------------------------------------ resolution

    def assert_available(self, venue_name: str, account_id: str) -> None:
        """Assert this pair is PROVISIONED and ENABLED — raise otherwise.

        The VALIDATION half of the venue-account authority, WITHOUT constructing a leaf. The
        live portfolio factory calls this to GATE portfolio creation and rehydrate, so a
        portfolio naming no account, a not-provisioned account, or a DISABLED one raises —
        the durable-invariant guarantee that every live portfolio is backed by a real,
        enabled ``venue_accounts`` row.

        **Scoped to EXISTS + ENABLED, deliberately NOT "brought online".** The live portfolio
        sits on a COMPUTE leaf carrying its real pair, and a compute leaf needs no assembled
        venue session. Requiring "brought online" here would therefore be over-strict: it
        would crash a single-venue live boot on a validly-provisioned FOREIGN-venue portfolio
        — a ``binance`` portfolio in an ``okx`` boot, whose venue this process never brings
        up.

        ``account_id`` is matched by EXACT STRING (no case-folding, trimming or coercion).
        """
        row = self._store.get(venue_name, account_id)
        if row is None:
            raise VenueAccountNotProvisionedError(
                venue_name, account_id,
                VenueAccountNotProvisionedError.NOT_PROVISIONED)
        if not row["enabled"]:
            raise VenueAccountNotProvisionedError(
                venue_name, account_id,
                VenueAccountNotProvisionedError.DISABLED)
