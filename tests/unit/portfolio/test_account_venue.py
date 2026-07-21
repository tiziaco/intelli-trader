"""The D-11 structural guard: a VenueAccount cannot be minted without naming an account.

**What this locks and why it is the guard.** Plan 11-07 promoted account
construction onto the ``VenuePlugin`` Protocol as ``new_account``. That promotion
is NOT what prevents an unscoped account: a catch-all ``(*args, **kwargs)`` arm is
the universally-compatible signature under strict type checking and satisfies ANY
Protocol method, and ``VenuePlugin`` is STRUCTURAL (plugins do not subclass it), so
an arg-swallowing arm would type-check clean. Before this plan EVERY parameter
after ``connector`` had a default, which is exactly why the OKX arm could absorb a
portfolio argument and hand back ONE shared account with no error — two real venue
accounts' buying power and positions conflated behind a green suite (T-11-32).

The guard is the SIGNATURE: ``account_id`` is a required keyword-only parameter
with NO default, so forgetting it is a construction-time ``TypeError``. And because
a required keyword-only parameter does NOT reject an explicit ``None``, the
None/empty case is separately rejected with a typed ``ValidationError`` — an
``Optional[str]`` field threaded through from a spec would otherwise slip a bare
``None`` past the signature and mint exactly the unattributed account this exists
to prevent.

4-space indentation. NO ``__init__.py`` in this dir (package-collision hazard).
"""

import pytest

from itrader.core.exceptions import ValidationError
from itrader.portfolio_handler.account import VenueAccount


class _FakeSession:
    """A trivial ``LiveConnector`` stand-in — the constructor only binds it.

    A real connector is not needed: every assertion here is about the CONSTRUCTOR
    contract, which runs before any venue I/O. Using a stub keeps the guard test
    offline and independent of the ccxt surface.
    """


def test_account_id_is_stored_and_reported() -> None:
    """A named account constructs and reports the account it is scoped to."""
    account = VenueAccount(_FakeSession(), account_id="acct-a")

    assert account.account_id == "acct-a"


def test_constructing_without_an_account_id_raises_type_error() -> None:
    """THE guard (D-11): omitting ``account_id`` fails at construction.

    This is the assertion that makes an unscoped venue account inexpressible. If
    ``account_id`` ever regains a default 'for migration smoothness', this test is
    the one that goes red — which is the whole point, because the caller who forgets
    would otherwise silently get a shared account.
    """
    with pytest.raises(TypeError):
        VenueAccount(_FakeSession())  # type: ignore[call-arg]


def test_explicit_none_account_id_raises_a_typed_error() -> None:
    """An explicit ``account_id=None`` is REFUSED, not silently accepted.

    The required-keyword signature alone does not cover this: ``None`` satisfies the
    signature. This is the realistic failure — ``account_id`` is ``Optional[str]`` on
    both the portfolio and the venue spec, so a bare pass-through of an unset field
    arrives here as ``None``.
    """
    with pytest.raises(ValidationError):
        VenueAccount(_FakeSession(), account_id=None)  # type: ignore[arg-type]


def test_empty_account_id_raises_a_typed_error() -> None:
    """An empty-string account id is refused for the same reason ``None`` is.

    ``""`` is a legal ``str`` and would pass a type-only check, but it names no
    account — and it would key the connector memo and the exchange registry under a
    blank account, which is an unscoped account wearing a different disguise.
    """
    with pytest.raises(ValidationError):
        VenueAccount(_FakeSession(), account_id="")


def test_quote_currency_stays_positional_and_defaulted() -> None:
    """The pre-existing positional/defaulted parameters are UNCHANGED.

    ``account_id`` was inserted as a keyword-only parameter precisely so the
    existing positional call shape (``VenueAccount(connector, "USDC")``) keeps
    working — the migration is additive, not a re-ordering.
    """
    account = VenueAccount(_FakeSession(), "USDC", account_id="acct-b")

    assert account._quote == "USDC"
    assert account.account_id == "acct-b"
