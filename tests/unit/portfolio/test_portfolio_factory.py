"""PortfolioFactory — the composition-owned definition→runtime mapping (D-24, 11.2-08).

**The oracle CANNOT cover this path.** ``test_backtest_oracle.py`` drives the LEGACY
construction arm (``scripts/run_backtest.py``), so a factory-only edit goes
false-green. These tests assert the factory DIRECTLY, with an identity sentinel (the
exact account object ``VenueBundles.account_for`` returned) rather than a call
counter, so a materialize that quietly substituted a compute leaf of its own would
fail here.

What is pinned:

* ``materialize`` attaches the account resolved through ``VenueBundles.account_for``
  (D-21) — identity, not just "an account was built".
* it builds and passes a real id-scoped ``state_storage`` (never omits it — plan 01
  made that a ``TypeError``).
* cash enters the Decimal domain at the boundary (``to_money``).
* an ``account_for`` refusal PROPAGATES — the factory never falls back to a compute
  leaf of its own (the ACCT-03 posture the plan-09 authority layer builds on).
* the factory has NO ``Optional`` collaborator: ``venue_bundles`` is a REQUIRED
  construction dependency, so there is no ``is None`` refusal counterpart.
"""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal
from typing import Any

import pytest

from itrader.core.exceptions import ValidationError
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_factory import PortfolioFactory
from itrader.venues.registry import DEFAULT_ACCOUNT_ID
from tests.support.venue_wiring import compute_account


_CASH = Decimal("100000")


class _RecordingBundles:
    """A ``VenueBundles`` double whose ``account_for`` returns a fixed SENTINEL.

    Records every call so the test can prove which ``(venue, account_id)`` the memo
    was asked for and which portfolio-args were forwarded onto the leaf.
    """

    def __init__(self, account: Any) -> None:
        self._account = account
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def account_for(
        self, venue: str, account_id: str, *, spec: Any = None, **portfolio_args: Any
    ) -> Any:
        self.calls.append((venue, account_id, portfolio_args))
        return self._account


class _RefusingBundles:
    """A ``VenueBundles`` double whose ``account_for`` RAISES (the ACCT-03 posture)."""

    def account_for(
        self, venue: str, account_id: str, *, spec: Any = None, **portfolio_args: Any
    ) -> Any:
        raise ValidationError(
            "account_id", account_id,
            "no such enabled venue account (ACCT-03 refusal surrogate)",
        )


def _factory(bundles: Any) -> PortfolioFactory:
    return PortfolioFactory(
        venue_bundles=bundles,
        environment="backtest",
        sql_engine=None,
        compute_venue="paper",
    )


# ---------------------------------------------------------------------------
# materialize attaches the account_for account — identity sentinel
# ---------------------------------------------------------------------------


def test_materialize_attaches_the_account_from_account_for() -> None:
    """D-21/D-24: the leaf is the EXACT object ``account_for`` returned, not a fallback."""
    sentinel = compute_account(_CASH)
    bundles = _RecordingBundles(sentinel)

    portfolio = _factory(bundles).materialize(
        name="pf", exchange="paper", cash=_CASH, venue_name="paper")

    assert isinstance(portfolio, Portfolio)
    assert portfolio.account is sentinel


def test_materialize_resolves_the_compute_venue_and_forwards_the_pair() -> None:
    """The memo is asked for (compute_venue, account_id); venue_name rides onto the leaf."""
    sentinel = compute_account(_CASH, account_id="acct-a", venue_name="okx")
    bundles = _RecordingBundles(sentinel)

    _factory(bundles).materialize(
        name="pf", exchange="okx", cash=_CASH,
        account_id="acct-a", venue_name="okx")

    assert len(bundles.calls) == 1
    venue, account_id, portfolio_args = bundles.calls[0]
    assert venue == "paper"          # the compute venue, not the trading venue
    assert account_id == "acct-a"    # uncoerced portfolio account id
    assert portfolio_args["venue_name"] == "okx"


def test_materialize_normalizes_an_absent_account_id_to_default() -> None:
    """An unnamed account normalizes to DEFAULT_ACCOUNT_ID in exactly one place."""
    bundles = _RecordingBundles(compute_account(_CASH))

    _factory(bundles).materialize(name="pf", exchange="paper", cash=_CASH)

    _, account_id, _ = bundles.calls[0]
    assert account_id == DEFAULT_ACCOUNT_ID


# ---------------------------------------------------------------------------
# the persistence seam is built and passed (never omitted); cash is Decimal
# ---------------------------------------------------------------------------


def test_materialize_passes_a_real_state_storage_to_the_leaf() -> None:
    """Plan 01: the id-scoped state_storage is built and forwarded, never omitted."""
    bundles = _RecordingBundles(compute_account(_CASH))

    _factory(bundles).materialize(name="pf", exchange="paper", cash=_CASH)

    _, _, portfolio_args = bundles.calls[0]
    assert portfolio_args["state_storage"] is not None


def test_materialize_enters_the_decimal_domain_at_the_boundary() -> None:
    """D-12: cash reaches the leaf resolution as a Decimal produced by to_money."""
    bundles = _RecordingBundles(compute_account(_CASH))

    _factory(bundles).materialize(name="pf", exchange="paper", cash=100000.0)

    _, _, portfolio_args = bundles.calls[0]
    assert type(portfolio_args["initial_cash"]) is Decimal


def test_materialize_reattaches_a_supplied_portfolio_id() -> None:
    """F-1: a supplied id is reattached verbatim (rehydrate stability), never re-minted."""
    from itrader import idgen
    from itrader.core.ids import PortfolioId

    existing = PortfolioId(idgen.generate_portfolio_id())
    portfolio = _factory(_RecordingBundles(compute_account(_CASH))).materialize(
        name="pf", exchange="paper", cash=_CASH, portfolio_id=existing)

    assert portfolio.portfolio_id == existing


# ---------------------------------------------------------------------------
# an account_for refusal propagates — no compute-leaf fallback
# ---------------------------------------------------------------------------


def test_materialize_propagates_an_account_for_refusal() -> None:
    """D-21: a refusal from account_for is NOT swallowed into a fallback leaf."""
    with pytest.raises(ValidationError):
        _factory(_RefusingBundles()).materialize(
            name="pf", exchange="paper", cash=_CASH, account_id="ghost")


# ---------------------------------------------------------------------------
# no Optional collaborator — venue_bundles is a REQUIRED construction dep
# ---------------------------------------------------------------------------


def test_venue_bundles_is_a_required_construction_dependency() -> None:
    """D-24: no Optional collaborator, so there is no `is None` refusal counterpart.

    The factory is built with real deps at composition; a missing ``venue_bundles``
    is a construction-time ``TypeError``, not a per-call ``is None`` guard.
    """
    with pytest.raises(TypeError):
        PortfolioFactory(environment="backtest", compute_venue="paper")  # type: ignore[call-arg]
