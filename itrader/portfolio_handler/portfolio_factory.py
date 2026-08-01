"""PortfolioFactory — the composition-owned definition→runtime-graph mapping.

A ``Portfolio`` is a runtime graph: an id-scoped ``PortfolioStateStorage`` seam, a
built ``Account`` leaf, and the domain object that binds them. ``PortfolioFactory``
owns that mapping so a Handler stays a queue-and-lifecycle layer, not an account
builder.

The factory is constructed with a single REQUIRED ``AccountFactory`` (the mode-agnostic
account seam) plus the run-mode ``environment`` / ``sql_engine`` selectors, and owns
``materialize(...)``: resolve the account leaf through
``self._account_factory.account_for(...)`` and construct the ``Portfolio`` over it. Which
VALIDATOR that account factory holds is the WHOLE of the mode difference — there is NO
``if backtest`` branch inside ``materialize``:

* the LIVE root passes ``VenueAccountManager.assert_available``, so a portfolio naming a
  not-provisioned or disabled account RAISES ``VenueAccountNotProvisionedError`` at
  ``materialize`` (ACCT-03) — a live portfolio never trades against a fabricated balance;
* the BACKTEST root passes none, so nothing can refuse a compute leaf.

**No ``Optional`` collaborator, no ``None``-then-assign, no post-construction setter.**
The factory holds a REAL account factory at construction: a dependency that genuinely
cannot be satisfied is a construction-time refusal, not a per-call ``is None`` check.

Both arms carry their own direct assertions
(``tests/unit/portfolio/test_portfolio_factory.py``) as well as riding the oracle, so a
factory-only regression cannot go false-green against either alone.

Indentation: 4-SPACE, matching ``portfolio_handler.py`` and the ``account/`` modules,
not the TAB-indented ``portfolio.py`` this factory constructs. ``sql_engine`` is typed
``Any`` so naming ``SqlEngine`` concretely never drags sqlalchemy onto this
backtest-hot-path module's import graph (GATE-01).
"""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Optional

from itrader import idgen
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.core.ids import PortfolioId
from itrader.core.money import to_money
from itrader.portfolio_handler.account.simulated import build_compute_account
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.storage import build_portfolio_state_storage
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
    # Typing-only: never evaluated at runtime, so this import pulls no concretion (GATE-01).
    from itrader.portfolio_handler.account.base import Account


class AccountFactory:
    """The ONE account-leaf constructor, with an optional validator in front of it.

    Two arms used to be two classes that differed by a single call. They are now one class
    and one injected policy (design §4.7): the LIVE root passes
    ``manager.assert_available``, the backtest root passes none. Which validator a factory
    holds is the WHOLE of the mode difference — there is no ``if backtest`` branch below
    this seam, and no second place a leaf is built.

    It builds through ``build_compute_account`` — the one compute-leaf constructor, beside
    the leaves it selects between — so the margin-vs-cash rule keeps its single home. A leaf
    whose balance is venue truth cannot be the construction-time leaf: that balance is
    unreadable until a venue read completes, while ``Portfolio.__init__`` reads it. So a
    live portfolio sits on a compute leaf carrying its REAL pair, gated by the validator,
    and venue truth is read separately through the execution adapter that owns the session.
    """

    def __init__(
        self,
        *,
        validate: Optional[Callable[[Optional[str], Optional[str]], None]] = None,
    ) -> None:
        """Hold the optional account validator.

        Parameters
        ----------
        validate
            Called as ``validate(venue_name, account_id)`` BEFORE any leaf is built, and
            expected to RAISE (``VenueAccountNotProvisionedError``) when the pair is not
            provisioned or is disabled. ``None`` is the compute arm: a compute leaf is
            always constructible, so nothing can refuse it. Typed structurally so naming
            ``VenueAccountManager`` here never drags the venue substrate onto this
            backtest-hot-path module's import graph (GATE-01).
        """
        self._validate = validate

    def account_for(
        self, venue_name: Optional[str], account_id: Optional[str], **portfolio_args: Any
    ) -> Account:
        """Build this portfolio's account leaf, validating the pair first when asked to.

        **The two arms are separate statements on purpose.** A compute venue serves exactly
        ONE account, so a portfolio that names none names THAT one — ``DEFAULT_ACCOUNT_ID``,
        the account half of the pair the compute exchange is registered under. That naming
        is what lets order routing be uniform on a single-account system, and it must NEVER
        apply where a validator does: naming an unnamed LIVE account would silently coerce
        that portfolio onto the default account, and every lookup above it would still read
        correct while its orders reached a different real balance.

        Writing the naming inside the validator-LESS return, rather than resolving it once
        above the branch, is what makes that unreachable rather than merely unreached.
        """
        if self._validate is not None:
            self._validate(venue_name, account_id)
            validated: Account = build_compute_account(
                account_id=account_id, venue_name=venue_name, **portfolio_args)
            return validated
        computed: Account = build_compute_account(
            account_id=account_id if account_id is not None else DEFAULT_ACCOUNT_ID,
            venue_name=venue_name,
            **portfolio_args)
        return computed


class PortfolioFactory:
    """Owns the definition→runtime-graph mapping, built with its real deps.

    Constructed at the composition roots with an ``AccountFactory`` and the run-mode
    selectors; ``materialize`` builds one ``Portfolio`` — its id-scoped state-storage
    seam, its ``Account`` leaf, and the domain object over them.
    """

    def __init__(
        self,
        *,
        account_factory: AccountFactory,
        environment: str = "backtest",
        sql_engine: Any = None,
    ) -> None:
        """Build the factory over its real, mode-agnostic collaborators.

        Parameters
        ----------
        account_factory
            The REQUIRED account-leaf builder. LIVE: one carrying the real
            ``VenueAccountManager.assert_available`` validator, which raises ACCT-03 on a
            missing or disabled account. BACKTEST: one carrying none. No ``Optional`` arm:
            which validator it holds is the only place the mode difference lives —
            ``materialize`` has no ``if backtest`` branch.
        environment
            Selects the state-storage backend: "backtest" (default) builds the
            in-memory oracle-dark backend; "live" (with ``sql_engine``) binds the
            durable SQL ledger scoped per ``portfolio_id``.
        sql_engine
            The shared ``SqlEngine`` for the "live" backend; typed ``Any`` to keep
            sqlalchemy off this module's import graph (GATE-01).
        """
        self._account_factory = account_factory
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

        Resolves the account leaf through ``self._account_factory.account_for(...)``
        with no ``if backtest`` branch and no ``or DEFAULT_ACCOUNT_ID`` coercion of the
        leaf identity — the portfolio's real ``(venue_name, account_id)`` is passed
        straight through, so the leaf reports the portfolio's own account.

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
        state_storage = build_portfolio_state_storage(
            self._environment,
            sql_engine=self._sql_engine,
            portfolio_id=resolved_id,
        )
        opening_cash = to_money(cash)
        # The config driving leaf selection must be the config the portfolio runs on —
        # mirrors Portfolio.__init__'s own default resolution.
        resolved_config = config or get_portfolio_preset("default")
        account = self._account_factory.account_for(
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
