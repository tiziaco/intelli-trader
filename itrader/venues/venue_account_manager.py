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
from typing import TYPE_CHECKING, Any, Mapping

from itrader.core.exceptions import VenueAccountNotProvisionedError
from itrader.logger import get_itrader_logger
from itrader.venues.assemble import assemble_venue

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.portfolio_handler.account.base import Account
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.trading_system.venue_spec import VenueSpec
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.bundles import VenueBundles
    from itrader.venues.lifecycle import VenueLifecycle

#: The one table name the D-34 fresh-deployment probe tests for. Narrow BY DESIGN.
_ACCOUNTS_TABLE = "venue_accounts"


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

    def bring_online(self, row: Mapping[str, Any]) -> OnlineVenueAccount:
        """Turn ONE durable account row into a live, routable venue account (D-27).

        The single implementation. Boot is its bulk case
        (``for row in read_enabled_for(venue): bring_online(row)``), and a runtime
        provision is the same call on one row — there is no second assembly path to drift
        from this one.

        Four steps:

        1. Build this account's ``VenueSpec``, carrying the ``secret_ref`` read off ITS OWN
           row. This is the relocated ``_read_account_secret_ref`` logic and it is the
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
        spec = build_venue_spec(
            venue_name,
            account_id=account_id,
            secret_ref=str(secret_ref) if secret_ref else None,
        )
        # SEAM (plan 06): D-38's config-precedence merge belongs HERE, between reading the
        # row's ``config`` and building the spec — the account-domain owner, one place.
        # D-40's per-pair venue-UID guard-outcome flag belongs on the record built below.
        # Both are deliberately NOT implemented in this plan.

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
