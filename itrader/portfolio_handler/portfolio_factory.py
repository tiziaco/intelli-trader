"""PortfolioFactory — the composition-owned definition→runtime-graph mapping (D-24).

A ``Portfolio`` is a runtime graph: an id-scoped ``PortfolioStateStorage`` seam, a
built ``Account`` leaf, and the domain object that binds them. Until this phase that
mapping lived INSIDE ``PortfolioHandler`` (``_new_compute_account`` + a held
``VenueBundles``), so a Handler — whose job in this codebase is the queue seam, the
registry and lifecycle — was also constructing account leaves. D-24 moves the
mapping out: composition constructs collaborators with their REAL dependencies and
injects them; objects receive them.

``PortfolioFactory`` is that collaborator. It is constructed with its real deps —
``venue_bundles`` (the mode-agnostic ``(venue, account_id)`` bundle memo), the
run-mode ``environment`` / ``sql_engine`` selectors and the ``compute_venue`` name —
and owns ``materialize(...)``: resolve the account through the mode-agnostic D-21
primitive ``VenueBundles.account_for`` and construct the ``Portfolio`` over it.

**No ``Optional`` collaborator, no ``None``-then-assign, no post-construction
setter.** The ``if self._venue_bundles is None: raise`` guard that lived in
``PortfolioHandler._new_compute_account`` existed ONLY because that collaborator was
``Optional``; it has NO counterpart here — the factory is built with real deps at
composition, so a dependency that genuinely cannot be satisfied is a construction-
time refusal, not a per-call ``is None`` check.

**Scope (11.2-08, owner sign-off).** This plan lands the mode-agnostic STRUCTURE:
the factory resolves accounts through ``VenueBundles.account_for`` (D-21), the pair
gets one storage site on the leaf (D-23), and the compute leaves carry their
identity. The LIVE authority path — a ``PortfolioFactory`` holding the real
``VenueAccountManager`` and calling ``VenueAccountManager.account_for`` at a
``create`` / ``materialize`` split that runs AFTER the manager is online — is
deferred to plan 09. Wiring THIS factory as the account builder ``add_portfolio``
calls is deferred with it: ``add_portfolio`` keeps ``_new_compute_account`` this
wave, so the live in-memory arm (which builds no manager) is never stranded. The
oracle drives the LEGACY construction arm, so this factory carries its OWN direct
assertions (``tests/unit/portfolio/test_portfolio_factory.py``) — a factory-only
edit would otherwise go false-green.

Indentation: 4-SPACE. This module is a composition-adjacent collaborator that most
resembles ``portfolio_handler.py`` and the ``account/`` modules (all 4-space), not
the TAB-indented ``portfolio.py`` it constructs. ``mypy --strict`` applies (new
code). GATE-01: ``venue_bundles`` / ``sql_engine`` are typed ``Any`` so naming
``VenueBundles`` / ``SqlEngine`` concretely never drags the venue substrate or
sqlalchemy onto this backtest-hot-path module's import graph.
"""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal
from typing import Any, Optional

from itrader import idgen
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.storage import PortfolioStateStorageFactory
from itrader.venues.registry import DEFAULT_ACCOUNT_ID


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
        venue_bundles: Any,
        environment: str = "backtest",
        sql_engine: Any = None,
        compute_venue: str,
    ) -> None:
        # The SAME ``(venue, account_id)`` bundle memo ``ExecutionHandler`` /
        # ``PortfolioHandler`` hold — one memo, so the account view and the exchange
        # view are provably the same bundle per pair (D-08). Typed ``Any`` for the
        # GATE-01 reason: naming ``VenueBundles`` would put the venue substrate on
        # this hot-path module's import graph. REQUIRED — there is no ``Optional``
        # arm and therefore no ``is None`` refusal counterpart (the anti-pattern
        # D-24 deletes one level up).
        self._venue_bundles = venue_bundles
        # D-07: the durable state-storage selectors. "backtest" (default) builds the
        # in-memory oracle-dark backend; "live" + the shared ``SqlEngine`` bind the
        # durable SQL ledger scoped per ``portfolio_id``. ``sql_engine`` is typed
        # ``Any`` to keep sqlalchemy off this module's import graph (GATE-01).
        self._environment = environment
        self._sql_engine = sql_engine
        # D-02/D-03: the venue whose plugin mints every portfolio's construction-time
        # COMPUTE leaf — the compute venue, on every path (a venue-truth account
        # needs a per-account spec that does not exist at portfolio-creation time).
        self._compute_venue = compute_venue

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

        Resolves the account leaf through the mode-agnostic D-21 primitive
        ``VenueBundles.account_for`` — CONSTRUCTION lives there; the live
        existence/enabled AUTHORITY (``VenueAccountManager.account_for``) is layered
        on top in plan 09 and is deliberately NOT reached here. Builds the id-scoped
        ``state_storage`` explicitly (plan 01 made omitting it a ``TypeError``) and
        passes the SAME ``opening_cash`` to both the leaf and the portfolio, so the
        two cannot drift (``Portfolio`` re-checks and refuses if they do).

        Parameters mirror ``PortfolioHandler.add_portfolio`` one-for-one. The account
        the leaf is minted under is the ``compute_venue`` bundle; the leaf CARRIES the
        portfolio's own ``(venue_name, account_id)`` (D-23) so ``Portfolio.venue_name``
        / ``.account_id`` report the portfolio's real account.
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
        # D-21: the mode-agnostic construction primitive. ``account_id`` is UNCOERCED
        # into the memo key here — the caller applies ``or DEFAULT_ACCOUNT_ID``, the
        # same rule ``assemble_venue`` / the exchange registry follow, so an unnamed
        # account normalizes in exactly one place. ``venue_name`` rides in the
        # portfolio-args so the built leaf carries the pair (D-23). An account row that
        # a later ``VenueAccountManager`` authority would refuse propagates that refusal
        # from within ``account_for`` — this construction primitive never substitutes a
        # fallback leaf of its own.
        account = self._venue_bundles.account_for(
            self._compute_venue,
            account_id or DEFAULT_ACCOUNT_ID,
            initial_cash=opening_cash,
            enable_margin=resolved_config.trading_rules.enable_margin,
            state_storage=state_storage,
            venue_name=venue_name,
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
