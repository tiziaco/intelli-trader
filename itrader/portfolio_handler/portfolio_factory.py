"""PortfolioFactory — the composition-owned definition→runtime-graph mapping.

A ``Portfolio`` is a runtime graph: an id-scoped ``PortfolioStateStorage`` seam, a
built ``Account`` leaf, and the domain object that binds them. ``PortfolioFactory``
owns that mapping so a Handler stays a queue-and-lifecycle layer, not an account
builder.

The factory is constructed with a single REQUIRED ``authority`` (the mode-agnostic
account seam) plus the run-mode ``environment`` / ``sql_engine`` selectors, and owns
``materialize(...)``: resolve the account leaf through
``self._authority.account_for(...)`` and construct the ``Portfolio`` over it. The
account authority is the WHOLE of the mode difference — there is NO ``if backtest``
branch inside ``materialize``:

* the LIVE arm injects a ``VenueValidatedComputeAuthority`` (below), which asks a real
  ``VenueAccountManager`` to validate the pair (provisioned + enabled + brought-online)
  and RAISES ``VenueAccountNotProvisionedError`` at ``materialize`` on any failure
  (ACCT-03) — a live portfolio never trades against a fabricated balance. On SUCCESS it
  builds a COMPUTE leaf carrying the real pair: a leaf whose balance is venue truth
  cannot be the construction-time leaf, because its balance raises until the first
  venue snapshot while ``Portfolio.__init__`` reads balance (the venue-truth swap is
  deferred, COMP-07);
* the BACKTEST / in-memory arm injects ``ComputeAccountAuthority`` (below) — no
  validation, and it NEVER raises.

**No ``Optional`` collaborator, no ``None``-then-assign, no post-construction setter.**
The factory holds a REAL authority at construction: a dependency that genuinely cannot
be satisfied is a construction-time refusal, not a per-call ``is None`` check.

Both authorities carry their own direct assertions
(``tests/unit/portfolio/test_portfolio_factory.py``) as well as riding the oracle, so a
factory-only regression cannot go false-green against either alone.

Indentation: 4-SPACE, matching ``portfolio_handler.py`` and the ``account/`` modules,
not the TAB-indented ``portfolio.py`` this factory constructs. ``authority`` /
``sql_engine`` are typed ``Any`` so naming ``VenueAccountManager`` / ``SqlEngine``
concretely never drags the venue substrate or sqlalchemy onto this backtest-hot-path
module's import graph (GATE-01).
"""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from itrader import idgen
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.portfolio_handler.account.simulated import build_compute_account
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.storage import PortfolioStateStorageFactory
from itrader.venues.registry import DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
    # Typing-only: never evaluated at runtime, so this import pulls no concretion (GATE-01).
    from itrader.portfolio_handler.account.base import Account


class ComputeAccountAuthority:
    """The COMPUTE account authority — builds a compute leaf, never raises.

    It holds no ``VenueAccountManager`` and therefore no existence/enabled authority to
    consult: a compute leaf is always constructible, so ``account_for`` never raises.
    Which authority a ``PortfolioFactory`` holds is the only place the mode difference
    lives — there is no ``if backtest`` branch inside ``materialize``.

    It builds through ``build_compute_account`` — the ONE compute-leaf constructor,
    beside the leaves it selects between — so the margin-vs-cash rule has a single home.

    ``account_for`` mirrors ``VenueAccountManager.account_for``'s call shape
    (``authority.account_for(venue_name, account_id, **portfolio_args)``, no ``spec=``)
    so the factory reaches both authorities the same way.
    """

    def account_for(
        self, venue_name: Optional[str], account_id: Optional[str], **portfolio_args: Any
    ) -> Account:
        """Build the compute leaf for this portfolio; never raises.

        A compute venue serves exactly ONE account, so a portfolio that names none names
        THAT one — ``DEFAULT_ACCOUNT_ID``, the account half of the pair the compute
        exchange is registered under. Naming it here is what lets order routing be
        uniform: the execution handler reads every order's account off its portfolio and
        finds a registered exchange on every path, with no mode-dependent default.

        The fallback is unreachable from the live path: ``VenueValidatedComputeAuthority``
        runs ``assert_available`` first, and a ``None`` account is refused there — so this
        never turns an unnamed live account into the default one (MPORT-07).
        """
        account: Account = build_compute_account(
            account_id=account_id if account_id is not None else DEFAULT_ACCOUNT_ID,
            venue_name=venue_name,
            **portfolio_args)
        return account


class VenueValidatedComputeAuthority:
    """The LIVE account authority — validate via VenueAccountManager, build a COMPUTE leaf.

    ``account_for`` asks the ``VenueAccountManager`` to assert the pair is provisioned +
    enabled + brought-online, so a portfolio naming a not-provisioned / disabled /
    not-online account raises ``VenueAccountNotProvisionedError`` at ``materialize``
    (ACCT-03) — never trading against a fabricated balance.

    On SUCCESS it builds a COMPUTE leaf carrying the portfolio's real ``(venue_name,
    account_id)``. A leaf whose balance is venue truth cannot be the construction-time
    leaf: that balance is unreadable until a venue read completes, while
    ``Portfolio.__init__`` reads the balance at construction. So a live portfolio sits on a
    compute leaf carrying its real pair, gated by the ACCT-03 raise, and venue truth is
    read separately through the execution adapter that owns the session.

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
        """Gate on ACCT-03, then build a compute leaf carrying the real pair."""
        self._manager.assert_available(venue_name, account_id)
        account: Account = self._compute.account_for(
            venue_name, account_id, **portfolio_args)
        return account


class PortfolioFactory:
    """Owns the definition→runtime-graph mapping, built with its real deps.

    Constructed at the composition roots with the shared ``venue_bundles`` memo and
    the run-mode selectors; ``materialize`` builds one ``Portfolio`` — its id-scoped
    state-storage seam, its ``Account`` leaf, and the domain object over them.
    """

    def __init__(
        self,
        *,
        authority: Any,
        environment: str = "backtest",
        sql_engine: Any = None,
    ) -> None:
        """Build the factory over its real, mode-agnostic collaborators.

        Parameters
        ----------
        authority
            The REQUIRED account authority. LIVE: the real ``VenueAccountManager``
            (raises ACCT-03 on a missing/disabled/not-online account). BACKTEST /
            in-memory: ``ComputeAccountAuthority`` (never raises, ``account_id`` stays
            ``None``). No ``Optional`` arm: which authority is injected is the only
            place the mode difference lives — ``materialize`` has no ``if backtest``
            branch. Typed ``Any`` so this hot-path module's import graph never picks
            up the venue substrate (GATE-01).
        environment
            Selects the state-storage backend: "backtest" (default) builds the
            in-memory oracle-dark backend; "live" (with ``sql_engine``) binds the
            durable SQL ledger scoped per ``portfolio_id``.
        sql_engine
            The shared ``SqlEngine`` for the "live" backend; typed ``Any`` to keep
            sqlalchemy off this module's import graph (GATE-01).
        """
        self._authority = authority
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
        """Build one ``Portfolio`` from its definition data.

        Resolves the account leaf through ``self._authority.account_for(...)`` with no
        ``if backtest`` branch and no ``or DEFAULT_ACCOUNT_ID`` coercion of the leaf
        identity — the portfolio's real ``(venue_name, account_id)`` is passed straight
        through, so the leaf reports the portfolio's own account. ``spec=`` is
        deliberately not passed: ``VenueAccountManager.account_for`` has no ``spec``
        parameter (it derives the spec internally from the online record), so passing
        one would land in ``portfolio_args`` and collide.

        Passes the SAME ``opening_cash`` to both the leaf and the portfolio so the two
        cannot drift (``Portfolio`` re-checks and refuses if they do). Parameters mirror
        ``PortfolioHandler.add_portfolio`` one-for-one.

        Returns
        -------
        Portfolio
            Built over the resolved account leaf. Raises
            ``VenueAccountNotProvisionedError`` instead of returning when the live
            authority refuses the account.
        """
        resolved_id = (
            portfolio_id if portfolio_id is not None
            else PortfolioId(idgen.generate_portfolio_id())
        )
        # Built HERE, before the account, so the account and the portfolio's other
        # managers adopt the SAME state_storage instance.
        state_storage = PortfolioStateStorageFactory.create(
            self._environment,
            sql_engine=self._sql_engine,
            portfolio_id=resolved_id,
        )
        opening_cash = to_money(cash)
        # The config driving leaf selection must be the config the portfolio runs on —
        # mirrors Portfolio.__init__'s own default resolution.
        resolved_config = config or get_portfolio_preset("default")
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
