"""VenueAccountManager — the venue-ACCOUNT domain owner.

One durable ``venue_accounts`` row travels end to end through this class and nowhere
else: ``provision`` writes it, ``bring_online`` turns it into a live runtime (a
``VenueSpec``, an assembled bundle, a registered exchange under the exact
``(venue_name, account_id)`` pair), and ``account_for`` resolves it into a constructed
account leaf.

**WHY ``bring_online`` has exactly ONE implementation, with boot as its bulk case.** An
account provisioned at runtime must be usable in the SAME process, with no restart. The
natural wrong shape is a boot-time assembly path plus a second "also assemble this new
one" path beside it — two implementations that agree the day they are written and diverge
on every change after. Boot is instead
``for row in read_enabled_for(venue): bring_online(row)``. A half-built runtime is not
representable, and a provision interrupted between the durable write and ``bring_online``
leaves an enabled row the next boot brings online through that same single path.

**WHY provisioning lives HERE and not on the live facade.** It is reached as
``system.venue_accounts.provision(...)``, mirroring how scripts already reach
``system.portfolio_handler.add_portfolio(...)``. ``bring_online`` is a DIRECT inline call
with the same threading posture ``add_portfolio`` has, never a queued CONTROL event: a
queued provision would return before the account was usable, reintroducing the two-step
timing this class exists to remove.

**WHY the degrade policy lives in the MANAGER, not the store.** A missing
``venue_accounts`` table is the fresh-deployment state, not a fault, so
``read_enabled_for`` warns and returns ``[]``. ANY other fault propagates LOUD. The probe
is deliberately narrow — it tests for the TABLE and nothing else — because under
DB-as-sole-truth a swallowed read means zero accounts, and every persisted portfolio then
refuses: N derived errors hiding one real cause. Keeping the policy here rather than in
``VenueAccountStore`` also makes it unit-testable without booting a system.

**WHY it is not in the barrel.** ``venues/__init__.py`` is the GATE-01 acceptance
evidence: it imports no concretion, so importing ``itrader.venues`` pulls nothing heavy.
This module is imported DIRECTLY and is deliberately absent from that barrel, mirroring
``bundles.py`` and ``connectors/provider.py``. It composes SQLAlchemy through the store
and reaches ``trading_system`` for the spec builder, so a barrel entry would put both on
the backtest import graph the inertness gate protects. Every SQL / ``trading_system``
import below is LAZY and in-body for the same reason.

Manager convention: EXCLUSIVE ownership of its storage, no back-reference to a handler,
and NO events-queue access — layering is one-directional (facade → manager → storage).
Collaborators are RECEIVED at construction, never minted, and never ``Optional``, which
is why the mode-agnostic CONSTRUCTION primitive is ``VenueBundles.account_for`` (both
backtest arms already build a ``VenueBundles``) and this class is the LIVE AUTHORITY over
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Mapping, Optional

from itrader.core.exceptions import (
    DuplicateVenueAccountProvisionError,
    UnknownVenueAccountConfigKeyError,
    ValidationError,
    VenueAccountInUseError,
    VenueAccountNotProvisionedError,
)
from itrader.logger import get_itrader_logger
from itrader.outils.dict_merge import recursive_merge
from itrader.venues.assemble import assemble_venue

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.portfolio_handler.account.base import Account
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.trading_system.venue_spec import VenueSpec
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.bundles import VenueBundles
    from itrader.venues.lifecycle import VenueLifecycle
    from itrader.venues.venue_uid_guard import VenueUidGuardOutcome

#: The one table name the fresh-deployment probe tests for. Narrow BY DESIGN.
_ACCOUNTS_TABLE = "venue_accounts"

#: The EXHAUSTIVE set of ``venue_accounts.config_json`` keys ``bring_online`` merges
#: onto an account's ``VenueSpec``.
#:
#: **An EXPLICIT ALLOWLIST, and an unrecognised key RAISES.** These are the keys that
#: decide where an account's money goes: ``sandbox`` and ``region`` select the HOST an
#: authenticated session reaches (``region`` picks the regional entity — an EEA-issued key
#: answers 50119 on the global host — and ``sandbox`` picks demo vs PRODUCTION), while
#: ``market_type`` reaches ``VenueAccount`` and changes how cash is netted. So a
#: silently-dropped ``sandox`` typo does NOT degrade to a harmless default: it leaves the
#: account on whatever the ambient process environment says, routing a live order to the
#: production host while the operator believes the account is pinned to demo. The raise IS
#: the control; accepting a key that changes nothing would be worse still.
#:
#: PRECEDENCE is one-directional: the ACCOUNT overrides the venue, and a key the account
#: does not name leaves the venue/bundle default in force. A venue value is never restored
#: over an explicit account value.
_MERGEABLE_CONFIG_KEYS = frozenset({"sandbox", "region", "market_type"})

#: The VENUE-LEVEL baseline the account's own config is merged ONTO. Every value is
#: ``None`` — "this account names no override" — because the real defaults live with each
#: venue's own plugin and settings model; restating them here would be a second home that
#: drifts.
_VENUE_LEVEL_CONFIG: dict[str, Any] = {
    "sandbox": None,
    "region": None,
    "market_type": None,
}

#: The shared market-type vocabulary. Validated HERE, unlike ``region``, because a bad
#: value fails SILENTLY: ``"spott"`` is not ``"spot"``, so ``_cash_stream_nets_holds``
#: flips and the account's CASH ACCOUNTING changes with nothing raising. ``region``'s
#: vocabulary belongs to the VENUE (``OkxSettings.region`` is a ``Literal`` that fails
#: loud at build time), so a second copy here would only drift from it.
_LEGAL_MARKET_TYPES = ("spot", "derivative")


@dataclass(frozen=True)
class OnlineVenueAccount:
    """What ``bring_online`` built for one ``(venue_name, account_id)`` pair.

    Held together under the pair that owns them rather than shattered into parallel
    scalar maps, which is how one lifecycle ends up split across several aliases that
    disagree. ``spec`` rides alongside the bundle because it carries the account's
    ``secret_ref`` — the ONE record of which credentials this session was built with.
    """

    spec: VenueSpec
    bundle: VenueBundle
    lifecycle: VenueLifecycle


class VenueAccountManager:
    """Owns the venue-ACCOUNT domain: provision, bring online, resolve.

    Parameters
    ----------
    store :
        The durable ``VenueAccountStore``, EXCLUSIVELY owned and never ``None``.
    bundles :
        The shared ``VenueBundles`` memo — the same object ``ExecutionHandler`` and the
        portfolio arm hold, so exactly one exchange and one account factory exist per
        ``(venue, account_id)`` tree-wide.
    connectors :
        The shared ``ConnectorProvider``, threaded verbatim into ``assemble_venue``.
    registry :
        The composition-root-owned ``(venue_name, account_id) -> exchange`` map — the SAME
        object ``ExecutionHandler`` reads on order, which ``bring_online`` WRITES into
        under the row's pair. Injecting the bare map rather than the execution handler is
        what keeps the manager from reaching THROUGH it, dissolving the false
        ``VAM -> execution_handler`` construction edge. Typed ``Any`` because naming the
        concrete element type would drag ``AbstractExchange`` onto this import graph.
    alert_sink :
        The CRITICAL-escalation egress handed to each ``VenueLifecycle`` so the
        trust-on-first-use venue-identity guard can alert. Required, not optional: an
        account brought online with nowhere to escalate a venue-identity mismatch is a
        silently-disarmed guard.
    feed_binder :
        The ``FeedConnectionBinder`` this manager DRIVES; it owns the provider build, the
        feed wiring and the re-borrow rule. There is no "primary account" — the ONE feed
        borrows the first available venue CONNECTION and re-borrows when that account is
        retired or disabled. Required, not optional: a manager that could bring an account
        online with no feed to connect it to would silently ship a live boot that receives
        no bars.
    """

    def __init__(
        self,
        store: VenueAccountStore,
        bundles: VenueBundles,
        connectors: ConnectorProvider,
        registry: Any,
        *,
        alert_sink: Any,
        feed_binder: Any,
    ) -> None:
        self._store = store
        self._bundles = bundles
        self._connectors = connectors
        self._registry = registry
        self._alert_sink = alert_sink
        self._feed_binder = feed_binder
        # The DURABLE read backing the account-disable refusal, built over the SAME shared
        # ``SqlEngine`` this manager's store already owns — no new injected collaborator to
        # re-thread through the composition root. A READ-ONLY view: reading the block here
        # keeps the manager free of a portfolio-handler back-reference, preserving the
        # one-directional layering. ``build_portfolio_definition_tables`` registers
        # idempotently on the shared MetaData, so a second view over the same spine is safe.
        from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore

        self._portfolio_definitions = PortfolioDefinitionStore(store.backend)
        # Keyed on the PAIR, the same key the exchange registry, the connector memo and the
        # bundle memo all use. A second memo on any other key is how those registries end up
        # disagreeing about an account, so this map holds ONLY what bring_online built and
        # never re-derives a bundle itself.
        self._online: dict[tuple[str, str], OnlineVenueAccount] = {}
        self.logger = get_itrader_logger().bind(component="VenueAccountManager")

    # ------------------------------------------------------------------ reads

    def read_enabled_for(self, venue_name: str) -> list[Mapping[str, Any]]:
        """This venue's ENABLED account rows, or ``[]`` on a fresh deployment.

        The account SET is STORE-DERIVED and VENUE-SCOPED: read off durable rows rather
        than re-derived from a spec, and one venue never sees another's accounts
        (``account_id`` alone cannot derive its venue). Ordering follows the store's
        ``venue_name`` / ``account_id`` ASC contract, so bring-up order is reproducible
        across runs and dialects. Zero enabled rows is a SUPPORTED state: a fresh
        deployment comes up RUNNING and empty.

        The degrade is deliberately narrow. A missing ``venue_accounts`` TABLE is the
        fresh-deployment state — a new database, or an Alembic chain that has not run —
        so warn and return ``[]``. Every other fault PROPAGATES. Widening this to a
        catch-all over the base exception type would convert one real cause (an
        unreachable database, a permissions error) into zero accounts, and from there into
        a refusal for every persisted portfolio: N derived errors burying the one that
        matters.

        The warning goes through the bound structlog logger, never the stdlib warnings
        module — the suite runs under ``filterwarnings=["error"]``, so a stdlib warning on
        the fresh-deployment path would fail every test that reached it.
        """
        from sqlalchemy import inspect as sa_inspect

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

    def venue_uid_guard_active(
        self,
    ) -> dict[tuple[str, str], "VenueUidGuardOutcome"]:
        """The UID-guard outcome for EVERY online pair.

        Carries OUTCOME + REASON per ``(venue_name, account_id)`` rather than a bare
        boolean, because a boolean tells an operator the guard is off but not WHICH of its
        holes they have — and the holes need different fixes.

        Built LIVE from each online record's lifecycle rather than cached at
        ``bring_online``. Arming is a CONNECT-time event (``VenueLifecycle.start()`` runs
        the guard post-connect) and ``bring_online`` does not connect, so a value frozen at
        bring-up would report every pair as unarmed forever. Reading through the lifecycle
        also leaves it the single owner of that outcome, with no second copy to drift.

        In-memory only; nothing is persisted.
        """
        return {
            pair: record.lifecycle.venue_uid_guard_outcome
            for pair, record in self._online.items()
        }

    def online(self, venue_name: str, account_id: str) -> OnlineVenueAccount:
        """The runtime ``bring_online`` built for this pair; refuses when there is none.

        Fails loud rather than returning ``None`` — a caller that can silently receive "no
        runtime" is a caller that will proceed without one.
        """
        key = (venue_name, account_id)
        if key not in self._online:
            raise VenueAccountNotProvisionedError(
                venue_name, account_id,
                VenueAccountNotProvisionedError.NOT_ONLINE)
        return self._online[key]

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

        Create-only. A second ``provision`` of the same pair raises
        ``DuplicateVenueAccountProvisionError`` and writes NOTHING — the database's
        composite primary key is the arbiter and its ``IntegrityError`` is classified on
        the ERROR path. There is deliberately no pre-check ``SELECT``: a pre-check is
        TOCTOU and, decisively, cannot bind the out-of-band writers a durable table always
        has.

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
        # The write timestamp is minted at the CALL SITE: the store is clock-free and takes
        # a caller-supplied ``at``, the same idiom every durable-write caller uses.
        self._create_row(
            venue_name,
            account_id,
            secret_ref=secret_ref,
            config=dict(config) if config is not None else {},
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
        from sqlalchemy.exc import IntegrityError

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
            raise DuplicateVenueAccountProvisionError(
                venue_name, account_id) from exc

    def set_enabled(self, venue_name: str, account_id: str, enabled: bool) -> None:
        """Enable/disable a venue account durably, REFUSING a disable a live portfolio needs.

        Disabling an account no live portfolio references succeeds; disabling one a LIVE
        portfolio still depends on raises ``VenueAccountInUseError`` naming the account,
        the blocking portfolio ids, and the remediation. A disable that raises writes
        NOTHING — the check runs BEFORE the store write.

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
        integrations page writing the row directly, which this in-band refusal cannot bind
        — is simply never brought online: ``read_enabled_for`` skips it and
        ``assert_available`` raises DISABLED, so its portfolios hit the composition-time
        refusal and the boot fails LOUD rather than trading against a leaf with no venue
        truth. Enabling is never refused.
        """
        if not enabled:
            blocking = self._portfolio_definitions.live_portfolio_ids_for_account(
                venue_name, account_id)
            if blocking:
                raise VenueAccountInUseError(venue_name, account_id, list(blocking))
        self._store.set_enabled(venue_name, account_id, enabled, datetime.now(UTC))
        self.logger.info(
            "Set venue account (%s, %s) enabled=%s", venue_name, account_id, enabled)

    def bring_online(self, row: Mapping[str, Any]) -> OnlineVenueAccount:
        """Turn ONE durable account row into a live, routable venue account.

        The single implementation. Boot is its bulk case
        (``for row in read_enabled_for(venue): bring_online(row)``) and a runtime provision
        is the same call on one row, so there is no second assembly path to drift from
        this one.

        1. Build this account's ``VenueSpec``, carrying the ``secret_ref`` AND the
           allowlisted ``config_json`` overrides read off ITS OWN row. This is the
           highest-consequence step: without it every NAMED account silently reverts to
           the ambient ``OKX_API_*`` credentials and two accounts authenticate as one. A
           NULL ``secret_ref`` is NOT that fail-open case — it means "this account has no
           per-account credentials", the supported paper shape. A well-formed pointer
           resolving to no material raises inside the resolver and is never degraded here.
        2. Delegate to ``assemble_venue``. Assembly is NOT re-implemented; asking the
           shared memo is what keeps one exchange per pair.
        3. Register the exchange under the row's ``account_id`` VERBATIM, never falling
           back to the single-account default. This key must be byte-identical to the one
           ``ExecutionHandler._resolve_account_id`` builds when reading, or the venue
           registers an account the order path can never reach.
        4. Record the runtime under the same pair.

        Returns the ``OnlineVenueAccount`` so a caller can drive the lifecycle it built.
        """
        # LAZY in-body: importing the spec builder eagerly would put the
        # ``trading_system`` package — whose barrel pulls the backtest composition root —
        # on this module's import graph.
        from itrader.trading_system.venue_spec import build_venue_spec

        venue_name = str(row["venue_name"])
        account_id = str(row["account_id"])
        # (1) The account's OWN credential pointer, off its OWN row.
        secret_ref = row.get("secret_ref")
        # The account's own ``config_json`` overrides, validated and merged onto the
        # venue-level baseline BEFORE any assembly — so a refused config brings NOTHING
        # online. A refusal that had already registered the exchange would leave the pair
        # routable with a config the engine declined to understand.
        overrides = self._merge_account_config(
            venue_name, account_id, row.get("config"))
        spec = build_venue_spec(
            venue_name,
            account_id=account_id,
            secret_ref=str(secret_ref) if secret_ref else None,
            **overrides,
        )

        # (2) ``provider`` is left at its default: there is no "primary account", so no
        # account is privileged with the one data provider here.
        bundle, lifecycle = assemble_venue(
            spec,
            self._connectors,
            self._bundles,
            account_store=self._store,
            alert_sink=self._alert_sink,
        )
        # (3) The row's account id VERBATIM, no coercion, and registration is
        # UNCONDITIONAL: skipping it for a connector-less (paper) bundle leaves a NAMED
        # paper account unroutable, because ``on_order`` resolves the portfolio's real
        # account and the lookup then misses and fails closed.
        #
        # Written into the manager's OWN injected registry — the SAME map object
        # ``ExecutionHandler`` reads on order — never a reach-in through the handler.
        self._registry[(venue_name, account_id)] = bundle.exchange
        # (4)
        record = OnlineVenueAccount(spec=spec, bundle=bundle, lifecycle=lifecycle)
        self._online[(venue_name, account_id)] = record
        self.logger.info(
            "Brought venue account (%s, %s) online", venue_name, account_id)
        # (5) Re-evaluate the ONE feed's borrowed connection, so a runtime
        # provision-then-bring_online binds the feed with no restart. A boot's per-row
        # bring_online binds on the first streaming account and no-ops on the rest. The
        # feed binds to a CONNECTION, so this privileges no account.
        self.rebind_feed()
        return record

    def rebind_feed(self) -> None:
        """Re-point the ONE live feed at a valid venue connection.

        Called from ``bring_online``, so a runtime provision binds without a restart, and
        once by the boot after its bring-up loop, so a zero-account boot still logs the
        unbound-feed warning. Idempotent — a valid, unchanged binding is a no-op.
        """
        self._feed_binder.rebind(self._streaming_available())

    def _streaming_available(self) -> list[tuple[str, str, "VenueSpec"]]:
        """The online accounts whose connection the feed may borrow, in bring-up order.

        A candidate is an online pair whose execution bundle carries a live CONNECTOR
        (paper carries ``connector=None``) AND whose durable row is still ENABLED — a
        disabled account is retired, so the feed must re-borrow off it. Insertion order is
        preserved (dict order = bring-up order = the store's ``account_id`` ASC), so the
        borrowed connection is reproducible.
        """
        available: list[tuple[str, str, "VenueSpec"]] = []
        for (venue_name, account_id), record in self._online.items():
            if record.bundle.connector is None:
                continue
            row = self._store.get(venue_name, account_id)
            if row is None or not row["enabled"]:
                continue
            available.append((venue_name, account_id, record.spec))
        return available

    @property
    def feed_provider(self) -> Any:
        """The provider currently bound to the ONE feed, or ``None``.

        Read by the composition root's halt-signal wiring and by the live session's
        warmup/subscribe step, so the account domain stays the single answer to "which
        connection is the feed on". Both readers None-guard it — a zero-account boot
        leaves it None.
        """
        return self._feed_binder.feed_provider

    def _merge_account_config(
        self,
        venue_name: str,
        account_id: str,
        config: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate and merge one account's ``config_json`` overrides.

        The ONLY reader ``venue_accounts.config_json`` has. Three steps, in this order:

        1. **REFUSE any key outside the allowlist** — see ``_MERGEABLE_CONFIG_KEYS`` for
           why a silently-dropped ``sandox`` typo is a live-order misroute rather than a
           harmless default. Validation happens BEFORE the merge, so a refused config
           produces no spec and therefore nothing online.
        2. **REFUSE an out-of-vocabulary value** for the keys whose bad value would fail
           SILENTLY (``_assert_config_values``).
        3. **MERGE, account over venue**, through the shared ``recursive_merge`` helper.
           The overlay is flat today, but that helper is the tree's ONE merge mechanism and
           hand-rolling a second is exactly the drift it was promoted to prevent.

        ``None`` (an out-of-band writer left ``config_json`` NULL) and ``{}``
        (``provision``'s normalization) are INDISTINGUISHABLE here: both mean "this account
        names no overrides", both leave every venue default in force, and neither raises.
        Making one an error would render a valid row un-bringable depending on which writer
        created it.

        Returns the keyword overrides for ``build_venue_spec``, every unnamed key carrying
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

        * ``market_type`` — ``VenueAccount`` derives
          ``_cash_stream_nets_holds = market_type != "spot"``, so ``"spott"`` sails through
          AS a derivative and changes the account's CASH ACCOUNTING with nothing raising.
        * ``sandbox`` — a JSON column holds the STRING ``"false"`` happily, and every
          Python truthiness test then reads it as ``True``, flipping an account between the
          demo and the PRODUCTION host.

        ``region`` is deliberately NOT checked: its vocabulary belongs to the venue
        (``OkxSettings.region`` is a ``Literal`` that raises on anything else), and
        restating an OKX-specific entity list in the venue-agnostic account domain is a
        copy that drifts the day a venue adds a region.
        """
        market_type = account_config.get("market_type")
        if market_type is not None and market_type not in _LEGAL_MARKET_TYPES:
            raise ValidationError(
                "market_type",
                str(market_type),
                f"Venue account ({venue_name!r}, {account_id!r}) names an unknown "
                f"market_type; the legal values are {list(_LEGAL_MARKET_TYPES)}. "
                f"Refusing to bring it online: an unrecognised value would be treated "
                f"as a derivative by VenueAccount's "
                f"`_cash_stream_nets_holds = market_type != 'spot'`, silently changing "
                f"this account's cash accounting (D-38).",
            )

        sandbox = account_config.get("sandbox")
        # ``isinstance(True, int)`` is True, so the check is on ``bool`` specifically —
        # a JSON ``1``/``0`` is not a boolean and must not be coerced into one here.
        if sandbox is not None and not isinstance(sandbox, bool):
            raise ValidationError(
                "sandbox",
                str(sandbox),
                f"Venue account ({venue_name!r}, {account_id!r}) names a non-boolean "
                f"sandbox. Refusing to bring it online: a JSON string such as "
                f"'false' is TRUTHY, so the account would connect to the opposite "
                f"host from the one configured — demo instead of production, or "
                f"production instead of demo (D-38).",
            )

    # ------------------------------------------------------------------ resolution

    def assert_available(self, venue_name: str, account_id: str) -> None:
        """Assert this pair is PROVISIONED and ENABLED — raise otherwise.

        The VALIDATION half of the venue-account authority, WITHOUT constructing a leaf.
        The live ``PortfolioFactory`` authority (``VenueValidatedComputeAuthority``) calls
        this to GATE portfolio creation and rehydrate, so a portfolio naming no account, a
        not-provisioned account, or a DISABLED one raises — the durable-invariant guarantee
        that every live portfolio is backed by a real, enabled ``venue_accounts`` row.

        **Scoped to EXISTS + ENABLED, deliberately NOT "brought online".** The live
        portfolio sits on a COMPUTE leaf carrying its real pair, and a compute leaf needs no
        assembled venue session. Requiring "brought online" here would therefore be
        over-strict: it would crash a single-venue live boot on a validly-provisioned
        FOREIGN-venue portfolio — a ``binance`` portfolio in an ``okx`` boot, whose venue
        this process never assembles. The brought-online check lives on ``account_for``
        instead, where a real session IS a precondition.

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

    def account_for(
        self,
        venue_name: str,
        account_id: str,
        **portfolio_args: Any,
    ) -> Account:
        """Resolve this pair into a constructed venue-truth leaf.

        NOT yet reached from the live portfolio-creation path: a venue-truth leaf cannot be
        the construction-time leaf, because ``VenueAccount.balance`` raises until its first
        snapshot while ``Portfolio.__init__`` reads balance. The live ``PortfolioFactory``
        authority calls ``assert_available`` and builds a COMPUTE leaf instead. This stays
        as the resolution primitive to wire once the snapshot lifecycle lands.

        Asserts, in order, that the account EXISTS, is ENABLED, and was brought ONLINE in
        this process, then delegates construction to ``VenueBundles.account_for``. Only
        this class can tell those three apart — "no such account" from "deliberately
        disabled" from "provisioned after boot, never assembled" — which is why the
        authority lives here while the construction primitive lives one layer down, where
        both backtest arms can also reach it.

        Fail-loud, never a fallback: it raises and NEVER returns a compute leaf. A compute
        leaf carries ``is_venue_truth=False``, which silently disables the venue snapshot,
        the fill/order streams, ``VenueReconciler`` and the unexplained-residual HALT — the
        portfolio would trade against computed balances believing they were the venue's.

        ``account_id`` is matched by EXACT STRING: no case-folding, no trimming, no Unicode
        normalization, and no coercion of a missing id to a default. ``' okx-1'`` and
        ``'okx-1'`` are different accounts and neither resolves to the other.

        ``portfolio_args`` are forwarded verbatim to the venue plugin's account factory. Do
        NOT pass ``account_id`` among them — it comes from the pair, and the pair is the
        identity. ``venue_name`` IS forwarded into the factory args so the built leaf
        CARRIES its real pair (``Portfolio.venue_name`` reads it back off the leaf);
        ``VenueBundles.account_for``'s first parameter is ``venue``, not ``venue_name``, so
        the keyword lands in ``portfolio_args`` with no collision.
        """
        # EXISTS + ENABLED via the shared gate, then the ONLINE check — a venue-truth leaf
        # needs an assembled session, which the compute-leaf authority does not.
        self.assert_available(venue_name, account_id)
        record = self.online(venue_name, account_id)
        return self._bundles.account_for(
            venue_name, account_id, spec=record.spec,
            venue_name=venue_name, **portfolio_args)
