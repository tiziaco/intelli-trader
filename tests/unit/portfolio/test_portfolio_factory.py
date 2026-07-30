"""PortfolioFactory — the composition-owned definition→runtime mapping (D-24, 11.2-09).

**The oracle CANNOT fully cover this path.** ``test_backtest_oracle.py`` drives the
LEGACY construction arm, so a factory-only edit could go false-green. These assert the
factory DIRECTLY, with an identity sentinel (the exact account object the injected
``AccountFactory`` returned) rather than a call counter, so a materialize that quietly
substituted a compute leaf of its own would fail here.

What is pinned:

* ``materialize`` attaches the account the injected ``AccountFactory`` returned —
  identity, not just "an account was built" — and forwards the portfolio's REAL
  ``(venue_name, account_id)`` pair UNCOERCED. There is NO compute-venue resolution and no
  default account named in ``PortfolioFactory``: the account factory owns that.
* it builds and passes a real id-scoped ``state_storage`` (never omits it — plan 01 made
  that a ``TypeError``); cash enters the Decimal domain at the boundary; a supplied id is
  reattached verbatim.
* BOTH account-factory arms: a refusing (live / ACCT-03) validator PROPAGATES — the
  factory never falls back to a compute leaf of its own; a validator-LESS
  ``AccountFactory`` yields a compute leaf naming the compute venue's one account and
  never raises.
* **the compute-venue default naming is gated on there being NO validator.** A
  validator-bearing factory REFUSES an unnamed account instead of naming it — naming it
  would silently coerce a live portfolio onto the default account while every lookup above
  it still read correct (MPORT-07).
* the factory has NO ``Optional`` collaborator: ``account_factory`` is a REQUIRED
  construction dependency, so there is no ``is None`` refusal counterpart.

This directory is package-less (NO ``__init__.py``). 4-SPACE indentation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from itrader.core.exceptions import (
    ValidationError,
    VenueAccountNotProvisionedError,
)
from itrader.portfolio_handler.account import SimulatedCashAccount
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_factory import (
    AccountFactory,
    PortfolioFactory,
)
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from tests.support.venue_wiring import compute_account


_CASH = Decimal("100000")


class _RecordingAuthority:
    """An account authority double whose ``account_for`` returns a fixed SENTINEL.

    Mirrors ``AccountFactory``'s seam: ``account_for(venue_name, account_id,
    **portfolio_args)``. Records every call so the test can prove which pair the factory
    forwarded and which portfolio-args rode onto the leaf.
    """

    def __init__(self, account: Any) -> None:
        self._account = account
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []

    def account_for(
        self, venue_name: Any, account_id: Any, **portfolio_args: Any
    ) -> Any:
        self.calls.append((venue_name, account_id, portfolio_args))
        return self._account


class _RefusingAuthority:
    """A live-arm authority double whose ``account_for`` RAISES (the ACCT-03 posture)."""

    def account_for(
        self, venue_name: Any, account_id: Any, **portfolio_args: Any
    ) -> Any:
        raise ValidationError(
            "account_id", account_id,
            "no such enabled venue account (ACCT-03 refusal surrogate)",
        )


def _factory(account_factory: Any) -> PortfolioFactory:
    return PortfolioFactory(
        account_factory=account_factory,
        environment="backtest",
        sql_engine=None,
    )


# ---------------------------------------------------------------------------
# materialize attaches the authority's account — identity sentinel
# ---------------------------------------------------------------------------


def test_materialize_attaches_the_account_from_the_authority() -> None:
    """D-24: the leaf is the EXACT object ``authority.account_for`` returned, not a fallback."""
    sentinel = compute_account(_CASH)
    authority = _RecordingAuthority(sentinel)

    portfolio = _factory(authority).materialize(
        name="pf", exchange="paper", cash=_CASH, venue_name="paper")

    assert isinstance(portfolio, Portfolio)
    assert portfolio.account is sentinel


def test_materialize_forwards_the_real_pair_uncoerced_and_no_spec() -> None:
    """The factory forwards the portfolio's REAL (venue_name, account_id), and no ``spec=``.

    No compute-venue resolution and no default account named in the factory — the
    authority owns that. And ``spec`` must NOT be forwarded (concern 3):
    ``VenueAccountManager.account_for`` has no such parameter, so a stray ``spec=`` would
    land in ``portfolio_args`` and collide.
    """
    authority = _RecordingAuthority(compute_account(_CASH, account_id="acct-a", venue_name="okx"))

    _factory(authority).materialize(
        name="pf", exchange="okx", cash=_CASH,
        account_id="acct-a", venue_name="okx")

    assert len(authority.calls) == 1
    venue_name, account_id, portfolio_args = authority.calls[0]
    assert venue_name == "okx"        # the portfolio's REAL venue, not the compute venue
    assert account_id == "acct-a"     # uncoerced
    assert "spec" not in portfolio_args


def test_materialize_forwards_a_none_account_id_uncoerced() -> None:
    """An unnamed account is passed to the authority as ``None`` — coercion is the authority's."""
    authority = _RecordingAuthority(compute_account(_CASH))

    _factory(authority).materialize(name="pf", exchange="paper", cash=_CASH, venue_name="paper")

    _, account_id, _ = authority.calls[0]
    assert account_id is None


# ---------------------------------------------------------------------------
# the persistence seam is built and passed (never omitted); cash is Decimal
# ---------------------------------------------------------------------------


def test_materialize_passes_a_real_state_storage_to_the_authority() -> None:
    """Plan 01: the id-scoped state_storage is built and forwarded, never omitted."""
    authority = _RecordingAuthority(compute_account(_CASH))

    _factory(authority).materialize(name="pf", exchange="paper", cash=_CASH, venue_name="paper")

    _, _, portfolio_args = authority.calls[0]
    assert portfolio_args["state_storage"] is not None


def test_materialize_enters_the_decimal_domain_at_the_boundary() -> None:
    """D-12: cash reaches the authority as a Decimal produced by to_money."""
    authority = _RecordingAuthority(compute_account(_CASH))

    _factory(authority).materialize(
        name="pf", exchange="paper", cash=100000.0, venue_name="paper")

    _, _, portfolio_args = authority.calls[0]
    assert type(portfolio_args["initial_cash"]) is Decimal


def test_materialize_reattaches_a_supplied_portfolio_id() -> None:
    """F-1: a supplied id is reattached verbatim (rehydrate stability), never re-minted."""
    from itrader import idgen
    from itrader.core.ids import PortfolioId

    existing = PortfolioId(idgen.generate_portfolio_id())
    portfolio = _factory(_RecordingAuthority(compute_account(_CASH))).materialize(
        name="pf", exchange="paper", cash=_CASH, venue_name="paper", portfolio_id=existing)

    assert portfolio.portfolio_id == existing


# ---------------------------------------------------------------------------
# BOTH authority arms
# ---------------------------------------------------------------------------


def test_a_refusing_authority_propagates_no_fallback_leaf() -> None:
    """The LIVE / ACCT-03 posture: a refusal from the authority is NOT swallowed.

    The factory never substitutes a compute leaf of its own — a portfolio naming a
    not-provisioned / disabled / not-online account gets the raise, never a silent
    ``SimulatedCashAccount`` with ``is_venue_truth=False``.
    """
    with pytest.raises(ValidationError):
        _factory(_RefusingAuthority()).materialize(
            name="pf", exchange="okx", cash=_CASH,
            account_id="ghost", venue_name="okx")


def test_a_validatorless_account_factory_names_the_default_account() -> None:
    """The BACKTEST arm over the REAL ``AccountFactory``: default account, no raise.

    A compute venue serves exactly ONE account, so a portfolio that names none names that
    one. It is what makes order routing uniform — the execution handler resolves every
    order's account off its portfolio and finds the registered ``(paper, default)``
    exchange — so a leaf reverting to ``account_id=None`` would silently refuse every
    backtest order. Proven end to end against the real authority, not a double.
    """
    portfolio = PortfolioFactory(
        account_factory=AccountFactory(), environment="backtest").materialize(
            name="pf", exchange="paper", cash=_CASH, venue_name="paper")

    assert portfolio.account.account_id == DEFAULT_ACCOUNT_ID
    assert portfolio.account.balance == Decimal("100000.00")


def test_a_portfolio_naming_its_own_account_keeps_that_account() -> None:
    """The default is a fallback for an unnamed account, never an override of a named one."""
    portfolio = PortfolioFactory(
        account_factory=AccountFactory(), environment="backtest").materialize(
            name="pf", exchange="paper", cash=_CASH, venue_name="paper",
            account_id="paper-acct-a")

    assert portfolio.account.account_id == "paper-acct-a"


# ---------------------------------------------------------------------------
# The VALIDATOR-BEARING AccountFactory — the LIVE arm: ACCT-03 raise + compute leaf
# (venue-truth leaf deferred to COMP-07 / Phase 12, owner decision wave 5)
# ---------------------------------------------------------------------------


class _FakeManager:
    """A VenueAccountManager stand-in exposing only ``assert_available``.

    ``available=False`` reproduces a refused account: the check RAISES with ``cause`` and no
    leaf is built (ACCT-03). ``available=True`` passes the gate. ``cause`` defaults to
    NOT_PROVISIONED (the missing-row case) and can be set to DISABLED to model an
    ``enabled=False`` row — the two causes must stay distinguishable at the factory.
    """

    def __init__(
        self, *, available: bool,
        cause: str = VenueAccountNotProvisionedError.NOT_PROVISIONED,
    ) -> None:
        self._available = available
        self._cause = cause
        self.checked: list[tuple[str, str]] = []

    def assert_available(self, venue_name: str, account_id: str) -> None:
        self.checked.append((venue_name, account_id))
        if not self._available:
            raise VenueAccountNotProvisionedError(
                venue_name, account_id, self._cause)


def _live_authority(
    *, available: bool,
    cause: str = VenueAccountNotProvisionedError.NOT_PROVISIONED,
) -> tuple[AccountFactory, _FakeManager]:
    manager = _FakeManager(available=available, cause=cause)
    return AccountFactory(validate=manager.assert_available), manager


def test_live_authority_raises_on_a_missing_account_and_builds_no_leaf() -> None:
    """ACCT-03: a live portfolio naming a not-provisioned/disabled/not-online account RAISES.

    This is the whole security guarantee — a live portfolio never trades against a
    fabricated balance. The RAISE comes from the manager's ``assert_available``; no leaf is
    constructed on the failure path.
    """
    authority, manager = _live_authority(available=False)

    with pytest.raises(VenueAccountNotProvisionedError):
        _factory(authority).materialize(
            name="pf", exchange="okx", cash=_CASH,
            account_id="ghost", venue_name="okx")

    # The gate was consulted for the real pair.
    assert manager.checked == [("okx", "ghost")]


def test_live_authority_distinguishes_a_missing_from_a_disabled_account() -> None:
    """ACCT-03 causes stay distinguishable at the factory: NOT_PROVISIONED != DISABLED.

    A missing row and a deliberately-disabled row are two different operator actions
    (provision vs re-enable). Collapsing them would send an operator to re-provision an
    account that already exists — which then refuses as a duplicate (D-11), leaving two
    contradictory errors and no true one.
    """
    for cause in (
        VenueAccountNotProvisionedError.NOT_PROVISIONED,
        VenueAccountNotProvisionedError.DISABLED,
    ):
        authority, _ = _live_authority(available=False, cause=cause)
        with pytest.raises(VenueAccountNotProvisionedError) as excinfo:
            _factory(authority).materialize(
                name="pf", exchange="okx", cash=_CASH,
                account_id="acct", venue_name="okx")
        assert excinfo.value.cause == cause


def test_live_authority_builds_a_compute_leaf_carrying_the_real_pair_on_success() -> None:
    """On a provisioned+enabled+online account, materialize SUCCEEDS on a COMPUTE leaf.

    The venue-truth ``VenueAccount`` leaf is DEFERRED to COMP-07 / Phase 12 (owner decision,
    wave 5, 2026-07-24) — a venue-truth balance is unreadable at construction. So this
    asserts the leaf carries the real ``(venue_name, account_id)`` identity and is a compute
    (``SimulatedCashAccount``) leaf, NOT ``is_venue_truth is True``.
    """
    authority, manager = _live_authority(available=True)

    portfolio = _factory(authority).materialize(
        name="pf", exchange="okx", cash=_CASH,
        account_id="acct-a", venue_name="okx")

    assert manager.checked == [("okx", "acct-a")]
    # The compute leaf carries the portfolio's REAL pair (D-23) ...
    assert portfolio.account_id == "acct-a"
    assert portfolio.venue_name == "okx"
    # ... and is a compute leaf (venue-truth swap is COMP-07/Phase 12), balance readable.
    assert isinstance(portfolio.account, SimulatedCashAccount)
    assert portfolio.account.balance == Decimal("100000.00")


# ---------------------------------------------------------------------------
# no Optional collaborator — authority is a REQUIRED construction dep
# ---------------------------------------------------------------------------


def test_the_account_factory_is_a_required_construction_dependency() -> None:
    """D-24: no Optional collaborator, so there is no `is None` refusal counterpart.

    The factory is built with a real ``AccountFactory`` at composition; a missing one is a
    construction-time ``TypeError``, not a per-call ``is None`` guard.
    """
    with pytest.raises(TypeError):
        PortfolioFactory(environment="backtest")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# The compute-venue default naming is GATED on the absence of a validator
# ---------------------------------------------------------------------------


def test_a_validator_bearing_factory_refuses_an_unnamed_account_rather_than_naming_it(
) -> None:
    """MPORT-07: a LIVE portfolio naming no account must RAISE, never inherit the default.

    The compute arm names ``DEFAULT_ACCOUNT_ID`` for a portfolio that names none, which is
    what makes single-account routing uniform. Merging the two former authority classes put
    that naming one line away from the live path, and it is a SILENT defect if it leaks: the
    portfolio would be built, its leaf would report the default account, its orders would
    reach the default account's exchange, and every lookup above it would still read
    correct.

    The gate is structural — the naming lives inside the validator-LESS return — so this
    asserts the OUTCOME rather than the shape: the validator runs on the real
    ``(None, None)`` pair and its refusal propagates, with no leaf built.
    """
    factory, manager = _live_authority(available=False)

    with pytest.raises(VenueAccountNotProvisionedError):
        _factory(factory).materialize(
            name="pf", exchange="okx", cash=_CASH,
            account_id=None, venue_name="okx")

    # The pair reached the validator VERBATIM — an unnamed account is not renamed on
    # its way to the check either.
    assert manager.checked == [("okx", None)]


def test_a_validator_that_accepts_an_unnamed_account_still_builds_an_unnamed_leaf(
) -> None:
    """The naming cannot leak even past a permissive validator.

    Belt and braces for the same defect: if a future validator were ever to allow an
    unnamed pair, the leaf must still report ``account_id=None`` — unroutable, which fails
    loud at the execution boundary — rather than the default account, which is routable to
    somebody ELSE'S money.
    """
    factory, _manager = _live_authority(available=True)

    portfolio = _factory(factory).materialize(
        name="pf", exchange="okx", cash=_CASH, account_id=None, venue_name="okx")

    assert portfolio.account.account_id is None
