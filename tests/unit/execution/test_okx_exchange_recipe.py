"""Unit contract for ``build_okx_exchange`` — the OKX execution-adapter recipe.

The recipe is the ONE place an OKX account's adapter is constructed, and its whole job is
turning three inputs (an ``AccountSpec``, that account's session, the engine context) into
an adapter that knows WHICH account it reads venue truth for.

**Every derived value must be THREADED, not merely derived.** The failure this file exists
to catch is silent and total: the recipe computes the settlement currency, the market type
and the traded pair, and then constructs the adapter without passing them. The adapter
falls back to its constructor defaults — the wrong quote balance, an unknown base leg, and
spot truth read from the derivative channel, which answers ``[]`` — so the account reports
FLAT while it holds coins, and the drift sweep halts on it. Nothing raises, and a
unit-tested "the adapter derives correctly" suite stays green because it never asks who
wired it. So the assertions below read the adapter's OWN state, not the recipe's locals.

4-space indentation (``tests/unit/*`` convention); NO ``__init__.py`` in this dir.
"""

from __future__ import annotations

import queue
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.core.exceptions import ValidationError
from itrader.execution_handler.exchanges.okx import OkxExchange, build_okx_exchange
from itrader.venues.accounts import AccountSpec


class _FakeConnector:
    """A session stand-in — the recipe only hands it to the adapter, never reads it."""


def _ctx(symbol: str = "BTC/USDC") -> Any:
    """The two context reads the recipe makes: the shared bus and the stream config."""
    return SimpleNamespace(
        bus=queue.Queue(),
        config=SimpleNamespace(stream=SimpleNamespace(okx_stream_symbol=symbol)),
    )


def _spec(**overrides: Any) -> AccountSpec:
    base: dict[str, Any] = {"venue_name": "okx", "account_id": "acct-1"}
    base.update(overrides)
    return AccountSpec(**base)


def test_the_recipe_builds_an_adapter_over_the_session_it_is_given() -> None:
    """The adapter holds the session the pool resolved for THIS account, not a new one."""
    connector = _FakeConnector()
    ctx = _ctx()

    adapter = build_okx_exchange(spec=_spec(), connector=connector, ctx=ctx)

    assert isinstance(adapter, OkxExchange)
    assert adapter._connector is connector
    assert adapter.global_queue is ctx.bus


def test_every_derived_value_reaches_the_adapter() -> None:
    """quote / base / symbol / market_type are all READ BACK OFF the built adapter.

    Each one is derived by the recipe and consumed only by the adapter's venue read, so a
    value that is computed and dropped is invisible everywhere except here.
    """
    adapter = build_okx_exchange(
        spec=_spec(market_type="derivative"),
        connector=_FakeConnector(),
        ctx=_ctx("ETH/USDT"),
    )

    # The settlement currency is the wired pair's RIGHT leg — never a hardcoded default.
    assert adapter._quote == "USDT"
    # The base leg is the pair's LEFT leg; spot position truth is derived from its balance.
    assert adapter._base == "ETH"
    assert adapter._symbol == "ETH/USDT"
    assert adapter._market_type == "derivative"


def test_the_market_type_defaults_to_spot_when_the_account_names_none() -> None:
    """An account row with no ``market_type`` gets SPOT, not the adapter's own default.

    ``market_type`` selects which channel the adapter reads position truth from, and
    ``fetch_positions`` answers ``[]`` on a spot account — so falling through to a
    derivative default reports a coin-holding account as FLAT.
    """
    adapter = build_okx_exchange(
        spec=_spec(), connector=_FakeConnector(), ctx=_ctx())

    assert adapter._market_type == "spot"


def test_an_account_named_market_type_wins_over_the_venue_default() -> None:
    """The account's own row overrides the venue-level default, one direction only."""
    adapter = build_okx_exchange(
        spec=_spec(market_type="derivative"), connector=_FakeConnector(), ctx=_ctx())

    assert adapter._market_type == "derivative"


def test_a_spec_naming_no_account_is_refused() -> None:
    """An absent ``account_id`` RAISES rather than defaulting to a "default" account.

    Coercing it here while the registration side keys the real account differently is how
    a routing map and a session memo end up describing two different real accounts.
    """
    with pytest.raises(ValidationError) as excinfo:
        build_okx_exchange(
            spec=SimpleNamespace(account_id=None, market_type=None),
            connector=_FakeConnector(),
            ctx=_ctx(),
        )

    assert "account_id" in str(excinfo.value)


def test_a_missing_session_is_refused() -> None:
    """An OKX arm with no session accepts orders it can never submit."""
    with pytest.raises(ValidationError) as excinfo:
        build_okx_exchange(spec=_spec(), connector=None, ctx=_ctx())

    assert "acct-1" in str(excinfo.value)
