"""PortfolioFactory — the composition-owned definition→runtime-graph mapping (D-24).

A ``Portfolio`` is a runtime graph: an id-scoped ``PortfolioStateStorage`` seam, a
built ``Account`` leaf, and the domain object that binds them. Until this phase that
mapping lived INSIDE ``PortfolioHandler`` (``_new_compute_account`` + a held
``VenueBundles``), so a Handler — whose job in this codebase is the queue seam, the
registry and lifecycle — was also constructing account leaves. D-24 moves the
mapping out: composition constructs collaborators with their REAL dependencies and
injects them; objects receive them.

``PortfolioFactory`` is that collaborator. It is constructed with its real deps — a
single REQUIRED ``authority`` (the mode-agnostic account seam) plus the run-mode
``environment`` / ``sql_engine`` selectors — and owns ``materialize(...)``: resolve the
account leaf through ``self._authority.account_for(...)`` and construct the ``Portfolio``
over it. The account authority is the WHOLE of the mode difference:

* the LIVE arm injects a ``VenueValidatedComputeAuthority`` (below) — it asks the real
  ``VenueAccountManager`` to VALIDATE the pair (provisioned + enabled + brought-online) and
  RAISES ``VenueAccountNotProvisionedError`` at ``materialize`` on any failure. **That RAISE
  is ACCT-03** (REQUIREMENTS.md: "a live portfolio naming no venue account RAISES at
  composition time") — the security guarantee that a live portfolio never trades against a
  fabricated balance. On SUCCESS it builds a COMPUTE leaf carrying the real pair: the
  venue-truth ``VenueAccount`` leaf CANNOT be the construction-time leaf (its balance raises
  until the first venue snapshot, T-05-07, while ``Portfolio.__init__`` reads balance), so
  that swap stays COMP-07 / Phase 12 (owner decision, wave 5, 2026-07-24);
* the BACKTEST / in-memory arm injects ``ComputeAccountAuthority`` (below) — bundles-only,
  ``account_id`` stays ``None``, no validation, and it NEVER raises.

There is NO ``if backtest`` branch inside ``materialize``: the mode lives ONLY in which
authority the composition root injects.

**No ``Optional`` collaborator, no ``None``-then-assign, no post-construction setter.**
The factory holds a REAL authority at construction — the LIVE root builds the
``VenueAccountManager`` BEFORE ``compose_engine`` (the D-43 exchange-registry extraction
cut the ``VAM -> execution_handler`` edge that used to force late-init), and the manager's
``_online`` map fills between construction and the first ``materialize`` at rehydrate:
ordinary object lifecycle, not deferred wiring. A dependency that genuinely cannot be
satisfied is a construction-time refusal, not a per-call ``is None`` check.

The oracle drives the LEGACY construction arm THROUGH ``compose_engine`` (which now builds
the default ``ComputeAccountAuthority`` factory), so this factory is exercised by the
oracle AND carries its OWN direct assertions
(``tests/unit/portfolio/test_portfolio_factory.py``) — a factory-only edit would otherwise
go false-green.

Indentation: 4-SPACE. This module is a composition-adjacent collaborator that most
resembles ``portfolio_handler.py`` and the ``account/`` modules (all 4-space), not
the TAB-indented ``portfolio.py`` it constructs. ``mypy --strict`` applies (new
code). GATE-01: ``authority`` / ``sql_engine`` (and ``ComputeAccountAuthority``'s
``venue_bundles``) are typed ``Any`` so naming ``VenueAccountManager`` / ``VenueBundles``
/ ``SqlEngine`` concretely never drags the venue substrate or sqlalchemy onto this
backtest-hot-path module's import graph.
"""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from itrader import idgen
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.storage import PortfolioStateStorageFactory
from itrader.venues.registry import DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
    # Typing-only (the module has ``from __future__ import annotations``, so these
    # annotations are never evaluated at runtime and pull no concretion — GATE-01).
    from itrader.portfolio_handler.account.base import Account


class ComputeAccountAuthority:
    """The BACKTEST / in-memory account authority — bundles-only, never raises (D-24).

    The mode-agnostic account seam's compute arm. It relocates
    ``PortfolioHandler._new_compute_account`` VERBATIM: resolve the COMPUTE-venue bundle
    (a fixed ``(compute_venue, DEFAULT_ACCOUNT_ID)`` memo key) and build the leaf carrying
    the portfolio's REAL ``(venue_name, account_id)`` pair (D-23) — ``account_id`` may be
    ``None`` on backtest and stays ``None`` on the leaf (the oracle invariant), NEVER
    coerced to the default.

    It has NO ``VenueAccountManager`` and therefore NO existence/enabled authority to
    consult: a compute leaf is always constructible, so ``account_for`` never raises. The
    LIVE authority (``VenueAccountManager``) is the raising one — and WHICH authority a
    ``PortfolioFactory`` holds is the ONLY place the mode difference lives (there is no
    ``if backtest`` branch inside ``materialize``).

    ``account_for`` mirrors ``VenueAccountManager.account_for``'s call shape so the factory
    reaches BOTH the same way (``authority.account_for(venue_name, account_id,
    **portfolio_args)``, no ``spec=``). ``venue_bundles`` is typed ``Any`` (GATE-01).
    """

    def __init__(self, *, venue_bundles: Any, compute_venue: str) -> None:
        # The SAME ``(venue, account_id)`` bundle memo ``ExecutionHandler`` /
        # ``PortfolioHandler`` hold (D-08). REQUIRED — no ``Optional`` arm.
        self._venue_bundles = venue_bundles
        # D-02/D-03: the venue whose plugin mints every portfolio's construction-time
        # COMPUTE leaf, on every path (a venue-truth account needs a per-account spec that
        # does not exist at portfolio-creation time).
        self._compute_venue = compute_venue

    def account_for(
        self, venue_name: Optional[str], account_id: Optional[str], **portfolio_args: Any
    ) -> Account:
        """Build the compute leaf for this portfolio; never raises (D-24).

        The MEMO KEY is the compute venue + the default-account half; the LEAF CARRIES the
        portfolio's real ``(venue_name, account_id)`` (D-23), so ``Portfolio.venue_name`` /
        ``.account_id`` report the portfolio's own account. ``account_id`` is NOT coerced
        into the memo key here — the compute bundle is resolved under
        ``DEFAULT_ACCOUNT_ID`` while the leaf keeps the real (possibly ``None``) id.
        """
        bundle = self._venue_bundles.get(
            self._compute_venue, DEFAULT_ACCOUNT_ID, None)
        account: Account = bundle.account_factory(
            account_id=account_id, venue_name=venue_name, **portfolio_args)
        return account


class VenueValidatedComputeAuthority:
    """The LIVE account authority — VALIDATE via VenueAccountManager, build a COMPUTE leaf.

    ACCT-03 delivered as the RAISE (REQUIREMENTS.md: "a live portfolio naming no venue
    account RAISES at composition time", owner decision wave 5, 2026-07-24). ``account_for``
    asks the ``VenueAccountManager`` to assert the pair is provisioned + enabled +
    brought-online, so a portfolio naming a not-provisioned / disabled / not-online account
    RAISES ``VenueAccountNotProvisionedError`` at materialize — never trading against a
    fabricated balance. That RAISE is the whole security guarantee this plan delivers.

    On SUCCESS it builds a COMPUTE leaf carrying the portfolio's real ``(venue_name,
    account_id)`` — NOT a venue-truth ``VenueAccount``. The venue-truth swap CANNOT happen
    at construction: ``VenueAccount.balance`` raises until its first venue snapshot (T-05-07)
    while ``Portfolio.__init__`` reads balance (``MetricsManager``). That swap remains
    COMP-07 / Phase 12 (owner-deferred 2026-07-22, reaffirmed wave 5, 2026-07-24). Until
    then the live portfolio sits on a compute leaf carrying its real pair — exactly as the
    pre-11.2-09 boot did, but now GATED by the ACCT-03 raise.

    Holds a REAL ``VenueAccountManager`` (for the check) and a REAL ``ComputeAccountAuthority``
    (for the leaf) at construction — no ``Optional``, no late-init, no post-construction set.
    Exposes the SAME ``account_for(venue_name, account_id, **portfolio_args) -> Account``
    shape as the backtest authority, so ``PortfolioFactory.materialize`` stays branch-free
    (no ``if backtest``). Typed ``Any`` (GATE-01).
    """

    def __init__(self, *, manager: Any, compute: Any) -> None:
        # The venue-ACCOUNT domain owner, used ONLY for the exists/enabled/online check.
        self._manager = manager
        # The compute-leaf builder — the SAME authority the backtest arm uses.
        self._compute = compute

    def account_for(
        self, venue_name: Optional[str], account_id: Optional[str], **portfolio_args: Any
    ) -> Account:
        """Gate on ACCT-03, then build a compute leaf carrying the real pair (D-24)."""
        # ACCT-03: raise on a not-provisioned / disabled / not-online account. The venue
        # authority is the only component that can tell the three causes apart (D-21).
        self._manager.assert_available(venue_name, account_id)
        # COMP-07 deferral: build the COMPUTE leaf carrying the real pair (not a venue-truth
        # VenueAccount, which cannot be balance-read at construction — see the class docstring).
        account: Account = self._compute.account_for(
            venue_name, account_id, **portfolio_args)
        return account


class PortfolioFactory:
    """Owns the definition→runtime-graph mapping, built with its real deps (D-24).

    Constructed at the composition roots with the shared ``venue_bundles`` memo and
    the run-mode selectors; ``materialize`` builds one ``Portfolio`` — its id-scoped
    state-storage seam, its ``Account`` leaf (resolved through the D-21 primitive),
    and the domain object over them.
    """

    def __init__(
        self,
        *,
        authority: Any,
        environment: str = "backtest",
        sql_engine: Any = None,
    ) -> None:
        # The ONE REQUIRED, mode-agnostic account authority (D-24). LIVE: the real
        # ``VenueAccountManager`` (ACCT-03 — raises on a missing/disabled/not-online
        # account). BACKTEST / in-memory: ``ComputeAccountAuthority`` (never raises,
        # ``account_id`` None). Typed ``Any`` for the GATE-01 reason: naming
        # ``VenueAccountManager`` would put the venue substrate on this hot-path module's
        # import graph. REQUIRED — there is NO ``Optional`` arm and therefore no ``is None``
        # refusal counterpart (the anti-pattern D-24 deletes), and no ``if backtest`` branch
        # in ``materialize``: the mode difference lives ONLY in which authority is injected.
        self._authority = authority
        # D-07: the durable state-storage selectors. "backtest" (default) builds the
        # in-memory oracle-dark backend; "live" + the shared ``SqlEngine`` bind the
        # durable SQL ledger scoped per ``portfolio_id``. ``sql_engine`` is typed
        # ``Any`` to keep sqlalchemy off this module's import graph (GATE-01).
        self._environment = environment
        self._sql_engine = sql_engine

    def materialize(
        self,
        *,
        name: str,
        exchange: str,
        cash: "float | Decimal",
        config: Optional[PortfolioConfig] = None,
        portfolio_id: Optional[PortfolioId] = None,
        account_id: Optional[str] = None,
        venue_name: Optional[str] = None,
        time: Optional[datetime] = None,
    ) -> Portfolio:
        """Build one ``Portfolio`` from its definition data (D-24).

        Resolves the account leaf through the REQUIRED, mode-agnostic authority
        (``self._authority.account_for(...)``) — with NO ``if backtest`` branch and NO
        ``or DEFAULT_ACCOUNT_ID`` coercion of the leaf identity. On the LIVE arm the
        authority is the real ``VenueAccountManager``: a portfolio naming a not-provisioned
        / disabled / not-online account RAISES ``VenueAccountNotProvisionedError`` here and
        no leaf is built (ACCT-03). On the BACKTEST arm the authority is
        ``ComputeAccountAuthority``: the leaf carries ``account_id=None`` and no raise. The
        portfolio's REAL ``(venue_name, account_id)`` is passed straight through, so the
        leaf reports the portfolio's own account (D-23).

        Builds the id-scoped ``state_storage`` explicitly (plan 01 made omitting it a
        ``TypeError``) and passes the SAME ``opening_cash`` to both the leaf and the
        portfolio, so the two cannot drift (``Portfolio`` re-checks and refuses if they do).
        Parameters mirror ``PortfolioHandler.add_portfolio`` one-for-one.

        ``spec=`` is deliberately NOT passed to the authority: ``VenueAccountManager.
        account_for`` has no ``spec`` parameter (it sets the spec internally from the
        online record), so passing one would land in ``portfolio_args`` and collide.
        """
        resolved_id = (
            portfolio_id if portfolio_id is not None
            else PortfolioId(idgen.generate_portfolio_id())
        )
        # D-07: the id-scoped durable seam, built HERE so the account (constructed a
        # few lines below, before any portfolio exists) lands on the SAME instance the
        # portfolio's three other managers will adopt.
        state_storage = PortfolioStateStorageFactory.create(
            self._environment,
            sql_engine=self._sql_engine,
            portfolio_id=resolved_id,
        )
        # D-12: the ONE entry into the Decimal domain on this path; the SAME value
        # reaches the ledger and the portfolio (T-11.1-42).
        opening_cash = to_money(cash)
        # The config that drives leaf SELECTION must be the config the portfolio runs
        # on — mirrors ``Portfolio.__init__``'s own default resolution.
        resolved_config = config or get_portfolio_preset("default")
        # D-24: the REQUIRED, mode-agnostic authority. The portfolio's REAL
        # ``(venue_name, account_id)`` is passed straight through — the live authority
        # RAISES ACCT-03 on a missing/disabled/not-online account and yields a venue-truth
        # leaf otherwise; the backtest authority builds a compute leaf carrying
        # ``account_id=None`` and never raises. No mode branch, no coercion, no ``spec=``.
        account = self._authority.account_for(
            venue_name,
            account_id,
            initial_cash=opening_cash,
            enable_margin=resolved_config.trading_rules.enable_margin,
            state_storage=state_storage,
        )
        return Portfolio(
            name=name,
            exchange=exchange,
            cash=opening_cash,
            time=time if time is not None else datetime.now(UTC),
            config=config,
            environment=self._environment,
            sql_engine=self._sql_engine,
            portfolio_id=resolved_id,
            account_id=account_id,
            venue_name=venue_name,
            account=account,
        )
