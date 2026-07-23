"""VenueAccountManager — the venue-ACCOUNT domain owner (11.2-05, ACCT-01/02/03, D-21/26/27/34).

One durable ``venue_accounts`` row travels end to end through this class and nowhere
else: ``provision`` writes it, ``bring_online`` turns it into a live runtime (a
``VenueSpec``, an assembled bundle, a registered exchange under the exact
``(venue_name, account_id)`` pair), and ``account_for`` resolves it into a constructed
account leaf. Four properties are load-bearing; each is a defect if inverted.

**WHY ``bring_online`` has exactly ONE implementation, with boot as its bulk case
(D-27).** An account provisioned at runtime must be usable in the SAME process, with no
restart. The natural wrong shape is a boot-time assembly path plus a second "also
assemble this new one" path beside it — two implementations that agree on the day they
are written and diverge on every change after. Boot is instead
``for row in read_enabled_for(venue): bring_online(row)``: the bulk case of the one
operation. A half-built runtime is therefore not representable, and a provision
interrupted between the durable write and ``bring_online`` leaves an enabled row the next
boot brings online through that same single path.

**WHY provisioning lives HERE and not on the live facade (D-26).** It is reached as
``system.venue_accounts.provision(...)``, mirroring how scripts already reach
``system.portfolio_handler.add_portfolio(...)``. There is no
``LiveTradingSystem.provision_venue_account`` and this milestone adds ZERO lines to
``live_trading_system.py`` — that file may only shrink (D-35). ``bring_online`` is a
DIRECT inline call with the same threading posture ``add_portfolio`` already has (D-28),
never a queued CONTROL event: a queued provision would return before the account was
usable and reintroduce the two-step timing this class exists to remove.

**WHY the degrade policy lives in the MANAGER, not the store (D-34).** A missing
``venue_accounts`` table is the fresh-deployment state, not a fault, so
``read_enabled_for`` warns and returns ``[]``. ANY other fault propagates LOUD. The probe
is deliberately narrow — it tests for the TABLE and nothing else — because under
DB-as-sole-truth a swallowed read means zero accounts, and every persisted portfolio then
fails ACCT-03: N derived errors hiding one real cause. Keeping the whole policy here (and
not in ``VenueAccountStore``) is what makes it unit-testable without booting a system.

**WHY it is not in the barrel.** ``venues/__init__.py`` is the GATE-01 acceptance
evidence — it "imports NO concretion … so importing ``itrader.venues`` pulls nothing
heavy". This module is imported DIRECTLY
(``from itrader.venues.venue_account_manager import VenueAccountManager``) and is
deliberately absent from that barrel, mirroring ``bundles.py`` and
``connectors/provider.py``. It composes SQLAlchemy (through the store) and reaches
``trading_system`` for the spec builder, so a barrel entry would put both on the backtest
import graph the inertness gate protects. Every SQL / ``trading_system`` import below is
LAZY and in-body for the same reason.

Manager convention (``order_manager.py``): EXCLUSIVE ownership of its storage, no
back-reference to a handler, and NO events-queue access — layering is one-directional
(facade → manager → storage). Collaborators are RECEIVED at construction, never minted,
and never ``Optional``: D-21 rejects ``VenueAccountManager(store=None)`` by name, which is
why the mode-agnostic CONSTRUCTION primitive is ``VenueBundles.account_for`` (both
backtest arms already build a ``VenueBundles``) and this class is the LIVE AUTHORITY over
it.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Mapping, Optional

from itrader.core.exceptions import (
    DuplicateVenueAccountProvisionError,
    UnknownVenueAccountConfigKeyError,
    ValidationError,
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

#: The one table name the D-34 fresh-deployment probe tests for. Narrow BY DESIGN.
_ACCOUNTS_TABLE = "venue_accounts"

#: The EXHAUSTIVE set of ``venue_accounts.config_json`` keys ``bring_online`` merges
#: onto an account's ``VenueSpec`` (11.2-06, D-38/D-12).
#:
#: **An EXPLICIT ALLOWLIST, and an unrecognised key RAISES.** These three keys are the
#: ones that decide where an account's money goes. ``sandbox`` and ``region`` select the
#: HOST an authenticated session reaches — ``region`` picks the regional entity (an
#: EEA-issued key answers 50119 on the global host) and ``sandbox`` picks demo vs
#: PRODUCTION — and ``market_type`` reaches ``VenueAccount``, where
#: ``_cash_stream_nets_holds = market_type != "spot"`` changes how cash is netted. So a
#: silently-dropped ``sandox`` typo does not degrade to a harmless default: it leaves the
#: account on whatever the ambient process environment says, routing a live order to the
#: production host while the operator believes the account is pinned to demo. The raise
#: IS the control (T-11.2-06-01); accepting a key that changes nothing would be worse
#: still (T-11.2-06-02), which is why the ``market_type='spot'`` hardcode in
#: ``okx_plugin.build_bundle`` was cleared in the same plan.
#:
#: PRECEDENCE is one-directional: the ACCOUNT overrides the venue, and a key the account
#: does not name leaves the venue/bundle default in force. A venue value is never
#: restored over an explicit account value.
_MERGEABLE_CONFIG_KEYS = frozenset({"sandbox", "region", "market_type"})

#: The VENUE-LEVEL baseline the account's own config is merged ONTO. Every value is
#: ``None`` — "this account names no override" — because ``VenueSpec`` deliberately
#: carries no concrete defaults: the real defaults live with each venue's own plugin and
#: settings model, and restating them here would be a second home for them that drifts.
_VENUE_LEVEL_CONFIG: dict[str, Any] = {
    "sandbox": None,
    "region": None,
    "market_type": None,
}

#: The shared market-type vocabulary (``VenueAccountConfig.market_type``). Validated
#: HERE, unlike ``region``, because a bad value fails SILENTLY rather than loudly:
#: ``"spott"`` is not ``"spot"``, so ``_cash_stream_nets_holds`` flips and the account's
#: CASH ACCOUNTING changes with nothing raising. ``region``'s vocabulary belongs to the
#: VENUE (``OkxSettings.region`` is a ``Literal`` that fails loud at build time), so it
#: is deliberately NOT restated here — a second copy would drift from the venue's own.
_LEGAL_MARKET_TYPES = ("spot", "derivative")


@dataclass(frozen=True)
class OnlineVenueAccount:
    """What ``bring_online`` built for one ``(venue_name, account_id)`` pair.

    Held so the runtime pieces of an account stay together under the pair that owns
    them, rather than being shattered into parallel scalar maps (the shape 11.1-08
    removed at the composition root, where one lifecycle had been split into six
    aliases). ``spec`` is kept alongside the bundle because it carries the account's
    ``secret_ref`` — the ONE record of which credentials this account's session was
    built with.
    """

    spec: VenueSpec
    bundle: VenueBundle
    lifecycle: VenueLifecycle


class VenueAccountManager:
    """Owns the venue-ACCOUNT domain: provision, bring online, resolve (D-21/26/27).

    Parameters
    ----------
    store :
        The durable ``VenueAccountStore``. EXCLUSIVELY owned and never ``None`` — the
        rejected manager-only design in D-21 needed a ``store=None`` arm on the backtest
        path, which is the ``Optional``-collaborator shape this milestone deletes.
    bundles :
        The shared ``VenueBundles`` memo (D-08) — the same object ``ExecutionHandler``
        and the portfolio arm hold, so exactly one exchange and one account factory exist
        per ``(venue, account_id)`` tree-wide.
    connectors :
        The shared ``ConnectorProvider``, threaded verbatim into ``assemble_venue``.
    execution_handler :
        The handler whose ``exchanges`` registry ``bring_online`` writes. Typed ``Any``
        for the reason ``bundles.py`` types its own collaborators ``Any``: naming the
        concrete handler would drag ``SimulatedExchange`` onto this module's import graph.
    alert_sink :
        The CRITICAL-escalation egress handed to each ``VenueLifecycle`` so the D-04
        trust-on-first-use venue-identity guard can alert. Required, not optional: an
        account brought online with nowhere to escalate a venue-identity mismatch is a
        silently-disarmed guard.
    """

    def __init__(
        self,
        store: VenueAccountStore,
        bundles: VenueBundles,
        connectors: ConnectorProvider,
        execution_handler: Any,
        *,
        alert_sink: Any,
    ) -> None:
        self._store = store
        self._bundles = bundles
        self._connectors = connectors
        self._execution_handler = execution_handler
        self._alert_sink = alert_sink
        # Keyed on the PAIR, the same key the exchange registry, the connector memo and
        # the bundle memo all use. A second memo on any other key is how those registries
        # end up disagreeing about an account (the defect D-08 exists to prevent), so this
        # map holds ONLY what bring_online built and never re-derives a bundle itself.
        self._online: dict[tuple[str, str], OnlineVenueAccount] = {}
        self.logger = get_itrader_logger().bind(component="VenueAccountManager")

    # ------------------------------------------------------------------ reads

    def read_enabled_for(self, venue_name: str) -> list[Mapping[str, Any]]:
        """This venue's ENABLED account rows, or ``[]`` on a fresh deployment (ACCT-01/D-34).

        The account SET is STORE-DERIVED and VENUE-SCOPED: it is read off durable rows
        rather than re-derived from a spec, and one venue never sees another's accounts
        (``account_id`` alone cannot derive its venue — D-01). Ordering is the store's
        ``venue_name`` ASC / ``account_id`` ASC contract, so bring-up order is
        reproducible across runs and dialects. Zero enabled rows is a SUPPORTED state, not
        an error: a fresh deployment comes up RUNNING and empty (D-09).

        D-34's degrade is deliberately narrow. A missing ``venue_accounts`` TABLE is the
        fresh-deployment state (a new database, or an Alembic chain that has not run):
        warn and return ``[]``. Every other fault PROPAGATES. Widening this to a catch-all
        handler over the base exception type would convert one real cause — an unreachable
        database, a permissions error — into zero accounts, and then into an ACCT-03
        refusal for every persisted portfolio: N derived errors burying the one that
        matters.

        The warning goes through the bound structlog logger, never the stdlib warnings
        module: the suite runs under ``filterwarnings=["error"]``, so a stdlib warning on
        the fresh-deployment path would fail every test that exercised it.
        """
        # GATE-01: the SQLAlchemy import is LAZY and in-body. This module is never
        # barrel-exported, but a module-top sqlalchemy import here would still put SQL one
        # import away from anything that reaches for the venue substrate.
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
        """The D-04 UID-guard outcome for EVERY online pair (11.2-06, D-15/D-40).

        D-15 named a ``venue_uid_guard_active`` flag; D-40 makes it carry OUTCOME +
        REASON per ``(venue_name, account_id)``, because a bare boolean tells an operator
        the guard is off but not WHICH of its six holes they have — and the holes need
        six different fixes.

        The map is built LIVE from each online record's lifecycle rather than cached at
        ``bring_online``, which is the deliberate reading of D-15's own condition that
        the flag reflect the guard's ACTUAL outcome. Arming is a CONNECT-time event
        (``VenueLifecycle.start()`` runs the guard post-connect), and ``bring_online``
        does not connect — so a value frozen at bring-up would report every pair as
        unarmed forever. Reading through the lifecycle means the surface tracks the guard
        as sessions actually start, and the lifecycle is the single owner of that
        outcome (no second copy to drift, D-08's own discipline).

        In-memory only; nothing new is persisted (D-40).
        """
        return {
            pair: record.lifecycle.venue_uid_guard_outcome
            for pair, record in self._online.items()
        }

    def online(self, venue_name: str, account_id: str) -> OnlineVenueAccount:
        """The runtime ``bring_online`` built for this pair; refuses when there is none.

        Fails loud with the ACCT-03 refusal rather than returning ``None`` — a caller that
        can silently receive "no runtime" is a caller that will proceed without one.
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
        """CREATE one durable ``venue_accounts`` row and return it (ACCT-02, D-11/D-26).

        Provisioning lives HERE and only here. It is reached as
        ``system.venue_accounts.provision(...)``, mirroring how scripts already reach
        ``system.portfolio_handler.add_portfolio(...)``; there is no
        ``LiveTradingSystem.provision_venue_account`` and this milestone adds no lines to
        that file (D-26/D-35).

        Create-only. A second ``provision`` of the same pair raises
        ``DuplicateVenueAccountProvisionError`` and writes NOTHING — the database's
        composite primary key is the arbiter and its ``IntegrityError`` is classified on
        the ERROR path. There is deliberately no pre-check ``SELECT``: a pre-check is
        TOCTOU and, decisively, does not bind the out-of-band writers a durable table
        always has. The same argument is already recorded for the sibling
        ``portfolio_definition_store``.

        It does NOT bring the account online. ``provision`` (the durable write) and
        ``bring_online`` (the runtime build) are two verbs by design (D-27): a caller that
        wants the account usable in this process performs both, explicitly, with no restart
        between them. The split is also what makes an interrupted provision safe — an
        enabled row with no runtime is exactly what the next boot brings online, through
        that same single path.

        The secret-key denylist is NOT re-implemented here. ``VenueAccountStore`` already
        runs the single recursive guard (REUSED from ``venue_store``) as the first
        statement of its write, before any transaction opens, so a ``config`` carrying a
        secret-looking key persists nothing. A second denylist in this class would be a
        drifting duplicate of the one control, which the store module forbids by name —
        membership is EXACT, so ``"credential"`` is denied while ``"credentials"`` passes
        by one letter.

        ``secret_ref`` is a POINTER at wherever the credential lives (``env:<PREFIX>``),
        never a credential itself.
        """
        # The write timestamp is minted at the CALL SITE: the store is clock-free by
        # decision (D-07) and takes a caller-supplied ``at``. This is the same idiom every
        # other durable-write caller in the tree uses.
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

        The classification sits on the ERROR path rather than in front of the write, which
        is the whole of D-11: the uniqueness decision belongs to the database, the one
        participant that sees every writer.
        """
        # GATE-01: the SQLAlchemy exception type is LAZY-imported in-body, like every other
        # SQL name this module touches.
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

    def bring_online(self, row: Mapping[str, Any]) -> OnlineVenueAccount:
        """Turn ONE durable account row into a live, routable venue account (D-27).

        The single implementation. Boot is its bulk case
        (``for row in read_enabled_for(venue): bring_online(row)``), and a runtime
        provision is the same call on one row — there is no second assembly path to drift
        from this one.

        Four steps:

        1. Build this account's ``VenueSpec``, carrying the ``secret_ref`` AND the
           allowlisted ``config_json`` overrides read off ITS OWN row (D-38 — see
           ``_merge_account_config``). This is the relocated
           ``_read_account_secret_ref`` logic and it is the
           highest-consequence line in the method: without it every NAMED account silently
           reverts to the ambient ``OKX_API_*`` credentials, so two accounts authenticate
           as one — the fail-open composite ACCT-02/WR-05 exists to close. A NULL
           ``secret_ref`` still means "this account has no per-account credentials" (the
           D-06 paper shape), which is a supported state and NOT the fail-open case: a
           well-formed pointer that resolves to no material raises inside the resolver and
           is never degraded here.
        2. Delegate to ``assemble_venue`` — the existing per-account primitive. Assembly is
           NOT re-implemented; asking the shared memo is what keeps one exchange per pair.
        3. Register the exchange under the row's ``account_id`` VERBATIM, never falling
           back to the single-account default. This key must be byte-identical to the one
           ``ExecutionHandler._resolve_account_id`` constructs when reading, or the venue
           registers an account the order path can never reach.
        4. Record the runtime under the same pair.

        Returns the ``OnlineVenueAccount`` so a caller can drive the lifecycle it built.
        """
        # The spec builder lives in ``trading_system`` (it is the live venue-selection
        # trio ``assemble_venue`` reads) and is LAZY-imported in-body: importing it eagerly
        # would put the ``trading_system`` package — whose barrel pulls the backtest
        # composition root — on this module's import graph.
        from itrader.trading_system.venue_spec import build_venue_spec

        venue_name = str(row["venue_name"])
        account_id = str(row["account_id"])
        # (1) The account's OWN credential pointer, off its OWN row (ACCT-02 / D-02).
        secret_ref = row.get("secret_ref")
        # 11.2-06 (D-38): the account's own ``config_json`` overrides, validated and
        # merged onto the venue-level baseline BEFORE the spec is built. It happens HERE
        # — the account-domain owner, one place — matching where every other account
        # decision landed, and it happens BEFORE any assembly so a refused config brings
        # NOTHING online (a refusal that had already registered the exchange would leave
        # the pair routable with a config the engine declined to understand).
        overrides = self._merge_account_config(
            venue_name, account_id, row.get("config"))
        spec = build_venue_spec(
            venue_name,
            account_id=account_id,
            secret_ref=str(secret_ref) if secret_ref else None,
            **overrides,
        )

        # (2) The existing per-account assembly primitive. ``provider`` is left at its
        # default: D-36 deletes "primary account" as a concept and moves feed binding out
        # of the composition root, so no account is privileged with the one data provider
        # here.
        bundle, lifecycle = assemble_venue(
            spec,
            self._connectors,
            self._bundles,
            account_store=self._store,
            alert_sink=self._alert_sink,
        )
        # (3) The row's account id VERBATIM — no coercion. The legacy boot loop skipped
        # registration for a connector-less (paper) bundle, which left a NAMED paper
        # account unroutable: ``on_order`` resolves the portfolio's real account, so the
        # lookup missed and failed closed. Registration here is unconditional.
        self._execution_handler.exchanges[(venue_name, account_id)] = bundle.exchange
        # (4)
        record = OnlineVenueAccount(spec=spec, bundle=bundle, lifecycle=lifecycle)
        self._online[(venue_name, account_id)] = record
        self.logger.info(
            "Brought venue account (%s, %s) online", venue_name, account_id)
        return record

    def _merge_account_config(
        self,
        venue_name: str,
        account_id: str,
        config: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate and merge one account's ``config_json`` overrides (11.2-06, D-38/D-12).

        The account-level half of D-12's precedence rule, and the ONLY reader
        ``venue_accounts.config_json`` has. Three steps, in this order:

        1. **REFUSE any key outside the allowlist.** See ``_MERGEABLE_CONFIG_KEYS`` for
           why a silently-dropped ``sandox`` typo is a live-order misroute rather than a
           harmless default. Validation happens BEFORE the merge, so a refused config
           produces no spec and therefore nothing online.
        2. **REFUSE an out-of-vocabulary value** for the keys whose bad value would fail
           SILENTLY (``_assert_config_values``).
        3. **MERGE, account over venue.** Through the shared
           ``outils/dict_merge.py::recursive_merge`` helper — never a hand-rolled merge.
           The overlay is flat today, but the helper is the tree's ONE merge mechanism
           and re-deriving a second one per caller is exactly the drift it was promoted
           to prevent.

        ``None`` (an out-of-band writer left ``config_json`` NULL) and ``{}``
        (``provision``'s normalization) are INDISTINGUISHABLE here: both mean "this
        account names no overrides", both leave every venue default in force, and
        neither raises. Making one of them an error would make a valid row un-bringable
        depending on which writer created it.

        Returns the keyword overrides for ``build_venue_spec``, every unnamed key
        carrying ``None`` — the spec's own "no override" value.
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
        """Refuse an allowlisted key whose VALUE would fail silently (11.2-06, D-38).

        The allowlist stops a key the engine does not understand; this stops a key it
        understands carrying something it cannot act on correctly. Only the two keys
        whose bad value is SILENT are checked here — a loud failure downstream is a
        better guard than a duplicated one:

        * ``market_type`` — ``VenueAccount`` derives
          ``_cash_stream_nets_holds = market_type != "spot"``, so ``"spott"`` sails
          through AS a derivative and changes the account's CASH ACCOUNTING with nothing
          raising anywhere.
        * ``sandbox`` — a JSON column holds the STRING ``"false"`` happily, and every
          truthiness test in Python then reads it as ``True``, flipping an account
          between the demo and the PRODUCTION host.

        ``region`` is deliberately NOT checked: its vocabulary belongs to the venue
        (``OkxSettings.region`` is a ``Literal`` that raises a pydantic
        ``ValidationError`` on anything else), and restating an OKX-specific entity list
        in the venue-agnostic account domain is a copy that drifts the day a venue adds
        a region.
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

    def account_for(
        self,
        venue_name: str,
        account_id: str,
        **portfolio_args: Any,
    ) -> Account:
        """Resolve this pair into a constructed account leaf — the LIVE authority (ACCT-03/D-21).

        Asserts, in order, that the account EXISTS, is ENABLED, and was brought ONLINE in
        this process, then delegates construction to ``VenueBundles.account_for``. Only
        this class can tell those three apart — "no such account" from "deliberately
        disabled" from "provisioned after boot, never assembled" — which is why the
        authority lives here and the construction primitive lives one layer down where
        both backtest arms can also reach it.

        Fail-loud, never a fallback: it raises ``VenueAccountNotProvisionedError`` and
        NEVER returns a compute leaf. A compute leaf carries ``is_venue_truth=False``,
        which silently disables the venue snapshot, the fill/order streams,
        ``VenueReconciler`` and the unexplained-residual HALT — the portfolio would trade
        against computed balances believing they were the venue's.

        ``account_id`` is matched by EXACT STRING: no case-folding, no trimming, no
        Unicode normalization, and no coercion of a missing id to a default. ``' okx-1'``
        and ``'okx-1'`` are different accounts and neither resolves to the other.

        ``portfolio_args`` are forwarded verbatim to the venue plugin's account factory.
        Do NOT pass ``account_id`` among them — it is forwarded from the pair, and the
        pair is the identity.
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
        record = self.online(venue_name, account_id)
        return self._bundles.account_for(
            venue_name, account_id, spec=record.spec, **portfolio_args)
