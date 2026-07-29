"""ConnectorPool: the memo, the session-identity guard, public sessions, teardown.

The invariants here are the ones that decide whether a live order reaches the account it
was meant for. Each is asserted against real consequences rather than call counts alone:

  - **One session per pair.** Two sessions for one account means two ccxt clients, two
    loops and two websocket sessions where the system believes there is one — and, for an
    execution account, a doubled fill stream.
  - **A same-pair identity disagreement is REFUSED.** The spec is read only on a memo
    MISS, so a silent hit would hand the second caller credentials and/or a host it did not
    ask for while every lookup above it still looked correct.
  - **Different accounts are unconstrained.** The guard must not turn per-account routing
    into a conflict; that would refuse the very isolation it exists to protect.
  - **Public sessions carry no identity.** No account, no spec, no credentials — nothing to
    disagree about.
  - **Teardown drops the identity shadow with the memo.** A surviving identity entry would
    refuse the NEXT run's legitimate first build.

The threading-contract test covers the ``call``/``spawn`` idiom generically: ``call`` is a
synchronous RPC that returns a value, ``spawn`` schedules a task and is never awaited for a
result. Written against the shared ``FakeLiveConnector`` so it constrains the CONTRACT
rather than the OKX implementation.

This directory is package-less (NO ``__init__.py``); the ``unit`` marker is folder-derived.
Indentation: 4-space.
"""

import asyncio
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.connectors.pool import ConnectorPool
from itrader.core.exceptions import ValidationError
from itrader.venues.catalog import CATALOG


class _FakeSession:
    """A stand-in session recording teardown; carries no credentials and opens no I/O."""

    def __init__(self, descriptor: Any = None, spec: Any = None) -> None:
        self.descriptor = descriptor
        self.spec = spec
        self.disconnected = 0

    def disconnect(self) -> None:
        self.disconnected += 1


def _pool(*, recipes: dict[str, Any] | None = None, resolver: Any = None) -> tuple[
        ConnectorPool, list[dict[str, Any]]]:
    """A pool over a recording recipe, plus the list of kwargs each build received."""
    builds: list[dict[str, Any]] = []

    def _recipe(**kwargs: Any) -> _FakeSession:
        builds.append(kwargs)
        return _FakeSession(kwargs.get("descriptor"), kwargs.get("spec"))

    pool = ConnectorPool(
        catalog=CATALOG,
        resolver=resolver,
        recipes=recipes if recipes is not None else {"okx": _recipe, "paper": _recipe},
    )
    return pool, builds


def _spec(**fields: Any) -> Any:
    """An account-shaped spec naming only the routing fields a test cares about."""
    return SimpleNamespace(**fields)


# --------------------------------------------------------------------------- #
# The memo
# --------------------------------------------------------------------------- #
def test_one_session_per_pair_is_built_once_and_shared() -> None:
    """Two asks for one pair yield the SAME object, built once.

    Object identity, not just a build count: a count of one with two different objects
    reaching two callers would still be the defect.
    """
    pool, builds = _pool()
    spec = _spec(secret_ref="env:A", sandbox=True, region="global")

    first = pool.session("okx", "acct-a", spec)
    second = pool.session("okx", "acct-a", spec)

    assert first is second
    assert len(builds) == 1


def test_two_accounts_on_one_venue_get_two_distinct_sessions() -> None:
    """Per-account isolation: distinct accounts are distinct sessions."""
    pool, builds = _pool()

    a = pool.session("okx", "acct-a", _spec(secret_ref="env:A", sandbox=True))
    b = pool.session("okx", "acct-b", _spec(secret_ref="env:B", sandbox=True))

    assert a is not b
    assert len(builds) == 2


def test_the_recipe_receives_the_venue_descriptor_and_the_spec() -> None:
    """A recipe derives its required credential set from the descriptor, so it must get it."""
    pool, builds = _pool()
    spec = _spec(secret_ref="env:A")

    pool.session("okx", "acct-a", spec)

    assert builds[0]["descriptor"] is CATALOG["okx"]
    assert builds[0]["spec"] is spec


def test_an_unknown_venue_names_what_the_pool_can_build() -> None:
    """The refusal has to be actionable — which venues DO have a recipe."""
    pool, _ = _pool(recipes={"okx": lambda **kw: _FakeSession()})
    with pytest.raises(KeyError) as excinfo:
        pool.session("bybit", "acct-a", _spec())
    assert "bybit" in str(excinfo.value)
    assert "okx" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# The session-identity guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("field", "first", "second"),
    [
        ("secret_ref", "env:A", "env:B"),
        ("sandbox", True, False),
        ("region", "global", "eea"),
    ],
)
def test_a_same_pair_identity_disagreement_is_refused(
    field: str, first: Any, second: Any,
) -> None:
    """Each identity field is load-bearing: credentials, demo-vs-production, entity host.

    Parametrized over all three because the guard exists to catch precisely the field a
    future edit forgets — and ``sandbox`` is the one whose silent reuse would route a
    production order at a demo host or the reverse.
    """
    pool, _ = _pool()
    pool.session("okx", "acct-a", _spec(**{field: first}))

    with pytest.raises(ValidationError) as excinfo:
        pool.session("okx", "acct-a", _spec(**{field: second}))
    assert field in str(excinfo.value)


def test_the_refusal_names_fields_but_never_values() -> None:
    """A message built out of spec values is how a credential reaches a log line."""
    pool, _ = _pool()
    pool.session("okx", "acct-a", _spec(secret_ref="env:REAL_KEY_POINTER"))

    with pytest.raises(ValidationError) as excinfo:
        pool.session("okx", "acct-a", _spec(secret_ref="env:OTHER_POINTER"))
    message = str(excinfo.value)
    assert "secret_ref" in message
    assert "REAL_KEY_POINTER" not in message
    assert "OTHER_POINTER" not in message


def test_fields_that_do_not_change_the_session_do_not_conflict() -> None:
    """``market_type``/``data_provider`` do not select a session, so they cannot conflict.

    Including them in the identity would refuse perfectly legitimate re-asks — the guard
    would then be a source of outages rather than a protection.
    """
    pool, builds = _pool()
    pool.session("okx", "acct-a", _spec(secret_ref="env:A", market_type="spot"))
    pool.session("okx", "acct-a", _spec(secret_ref="env:A", market_type="swap"))
    assert len(builds) == 1


def test_a_spec_naming_no_routing_fields_never_conflicts() -> None:
    """An object naming no routing cannot disagree about it — a stable all-None identity."""
    pool, builds = _pool()
    pool.session("paper", "acct-a", _spec(account_id="acct-a"))
    pool.session("paper", "acct-a", _spec(account_id="acct-a"))
    assert len(builds) == 1


# --------------------------------------------------------------------------- #
# Public sessions
# --------------------------------------------------------------------------- #
def test_a_public_session_is_memoized_per_venue() -> None:
    """One public session per venue: nothing about it is caller-specific."""
    pool, builds = _pool()
    first = pool.public_session("okx")
    second = pool.public_session("okx")
    assert first is second
    assert len(builds) == 1


def test_a_public_session_is_built_with_no_spec() -> None:
    """``spec is None`` is how a recipe is asked for a credential-free session."""
    pool, builds = _pool()
    pool.public_session("okx")
    assert builds[0]["spec"] is None


def test_a_public_session_is_distinct_from_every_authenticated_one() -> None:
    """The public session must not BE an account's session — that is the borrow, renamed."""
    pool, _ = _pool()
    authenticated = pool.session("okx", "acct-a", _spec(secret_ref="env:A"))
    public = pool.public_session("okx")
    assert public is not authenticated


def test_a_public_session_does_not_collide_with_the_account_memo() -> None:
    """Public and authenticated sessions live in separate memos, keyed differently."""
    pool, builds = _pool()
    pool.public_session("okx")
    pool.session("okx", "acct-a", _spec(secret_ref="env:A"))
    assert len(builds) == 2


# --------------------------------------------------------------------------- #
# Teardown
# --------------------------------------------------------------------------- #
def test_close_all_disconnects_every_session_including_public_ones() -> None:
    """Teardown covers what the pool BUILT — an abandoned session has no owner."""
    pool, _ = _pool()
    a = pool.session("okx", "acct-a", _spec(secret_ref="env:A"))
    b = pool.session("okx", "acct-b", _spec(secret_ref="env:B"))
    public = pool.public_session("okx")

    pool.close_all()

    assert a.disconnected == 1
    assert b.disconnected == 1
    assert public.disconnected == 1


def test_a_raising_disconnect_does_not_strand_the_remaining_sessions() -> None:
    """One venue's failed teardown must not leave the others connected."""
    built: list[_FakeSession] = []

    def _recipe(**kwargs: Any) -> _FakeSession:
        session = _FakeSession()
        if not built:
            def _boom() -> None:
                raise RuntimeError("disconnect failed")
            session.disconnect = _boom  # type: ignore[method-assign]
        built.append(session)
        return session

    pool = ConnectorPool(
        catalog=CATALOG, resolver=None, recipes={"okx": _recipe})
    pool.session("okx", "acct-a", _spec(secret_ref="env:A"))
    pool.session("okx", "acct-b", _spec(secret_ref="env:B"))

    pool.close_all()

    assert built[1].disconnected == 1


def test_close_all_drops_the_identity_shadow_so_the_next_build_is_allowed() -> None:
    """A surviving identity entry would refuse the NEXT run's legitimate first build."""
    pool, builds = _pool()
    pool.session("okx", "acct-a", _spec(secret_ref="env:A"))
    pool.close_all()

    # A DIFFERENT identity for the same pair, which would have conflicted before teardown.
    pool.session("okx", "acct-a", _spec(secret_ref="env:B"))
    assert len(builds) == 2


# --------------------------------------------------------------------------- #
# The generic threading contract every session obeys
# --------------------------------------------------------------------------- #
def test_call_is_a_synchronous_rpc_and_spawn_is_never_awaited(
    fake_connector: Any,
) -> None:
    """``call`` returns a value; ``spawn`` schedules a stream and is not result-awaited.

    The contract, not the implementation: pooled sessions are the only sanctioned
    async-to-sync bridge, and a caller that ``.result()``-awaited a ``spawn`` handle would
    block forever on a stream that never terminates.
    """
    connector = fake_connector

    async def _rpc() -> str:
        return "pong"

    assert connector.call(_rpc()) == "pong"

    async def _stream() -> None:
        await asyncio.sleep(3600)

    handle = connector.spawn(_stream())
    assert handle is not None
    assert not handle.done(), "a spawned stream task must not have been awaited"


# --------------------------------------------------------------------------- #
# Import-inertness — what lets a backtest root hold a real, empty pool
# --------------------------------------------------------------------------- #
_INERTNESS_PROBE = r"""
import sys

import itrader.connectors.pool  # noqa: F401

_FORBIDDEN_ROOTS = ("ccxt", "sqlalchemy", "psycopg2", "alembic")
leaked = sorted({name.split(".")[0] for name in sys.modules} & set(_FORBIDDEN_ROOTS))
assert not leaked, "the connector pool must be import-inert; it pulled " + repr(leaked)
assert "itrader.connectors.okx" not in sys.modules, (
    "the pool pulled the OKX connector concretion — build knowledge lives in RECIPES the "
    "root hands in, so the pool itself must reach no session implementation"
)
print("POOL_INERT_OK")
"""


def test_importing_the_pool_pulls_no_ccxt_and_no_concretion() -> None:
    """The pool holds the memo, never build knowledge — so importing it must be cheap.

    This is what lets a composition root that needs an empty pool hold a REAL one instead
    of ``None``: an inert pool cannot drag a session implementation onto a graph that must
    stay free of it. A subprocess, because this pytest session has already imported ccxt
    via other suites and an in-process check would pass vacuously.
    """
    result = subprocess.run(
        [sys.executable, "-c", _INERTNESS_PROBE],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, (
        f"pool inertness probe failed:\nstdout={result.stdout}\nstderr={result.stderr}")
    assert "POOL_INERT_OK" in result.stdout
