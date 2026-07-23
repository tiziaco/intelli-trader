"""Unit contract for the VenueBundles memo (11.1-05, VENUE-07, D-08).

Proves:
  - **D-08 build-once (the core contract).** Two ``get`` calls for the SAME
    ``(venue, account_id)`` return the SAME ``VenueBundle`` object and the
    plugin's ``build_bundle`` ran exactly ONCE. This is the mitigation for a real
    duplicate-session defect: two independent ``build_bundle`` calls produce two
    ``OkxExchange`` instances per account, and ``OkxExchange.connect()`` is the
    sole spawn site for ``_stream_fills`` / ``_stream_orders``, so a second bundle
    double-spawns the fill/order streams for one authenticated account.
  - **VENUE-07 no over-collapse.** Two accounts on ONE venue are two bundles —
    two accounts are two authenticated sessions.
  - **VENUE-07 adjacency edge.** Two DIFFERENT venues sharing one ``account_id``
    do not collide; a bare-``account_id`` key is the natural wrong implementation
    and this is the test that catches it.
  - **VENUE-07 empty edge.** An unregistered venue fails LOUD (``KeyError``) and
    adds nothing to the memo — never a silent default that routes real orders to
    the wrong venue.
  - **VENUE-07 ordering edge.** The memo is a plain ``dict``: insertion-ordered
    and stable; a repeated ``get`` never reorders or displaces an entry.
  - ``VenueBundles`` never READS the connectors object — it only threads the
    reference through to the plugin.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from itrader.venues.bundle import VenueBundle
from itrader.venues.bundles import VenueBundles
from itrader.venues.registry import ExecutionVenueRegistry


class _FakeVenuePlugin:
    """Structural ``VenuePlugin``: counts builds and returns a FRESH bundle per call.

    Two independent signals that a second build happened: the ``build_calls``
    counter AND a fresh ``exchange`` sentinel object per call (identity). A counter
    alone can be satisfied by a memo that returns the wrong entry.
    """

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.build_calls = 0
        self.received_connectors: Any = None

    @property
    def credential_model(self) -> type[Any] | None:
        return None

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        self.build_calls += 1
        self.received_connectors = connectors
        exchange = SimpleNamespace(built_by=self.name, build_seq=self.build_calls)
        return VenueBundle(
            exchange=exchange,  # type: ignore[arg-type]
            account_factory=lambda *a, **k: SimpleNamespace(venue=self.name),
            connector=None,
        )

    def new_account(self, portfolio_ref: Any, config: Any) -> Any:
        raise AssertionError("VenueBundles must not mint accounts itself")


class _ExplodingConnectorProvider:
    """A ConnectorProvider whose EVERY attribute access raises (the 'do not touch' idiom).

    ``VenueBundles`` only passes this reference to the plugin; reading anything off
    it — credential-bearing state included — is a defect, so any read explodes.
    """

    def __getattribute__(self, name: str) -> Any:
        raise AssertionError(
            f"VenueBundles must not read attribute {name!r} off the connectors "
            "object; it only threads the reference through to the plugin"
        )


def _fake_ctx() -> SimpleNamespace:
    return SimpleNamespace(bus=object())


def _fake_spec(account_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(account_id=account_id)


def _make_bundles(
    **plugins: _FakeVenuePlugin,
) -> tuple[VenueBundles, dict[str, _FakeVenuePlugin]]:
    registry = ExecutionVenueRegistry()
    for name, plugin in plugins.items():
        registry.register(name, plugin)  # type: ignore[arg-type]
    bundles = VenueBundles(registry, connectors=object(), ctx=_fake_ctx())
    return bundles, dict(plugins)


def test_repeated_get_returns_the_same_bundle_and_builds_once() -> None:
    """D-08 core contract: build once per key, hand the SAME object to every caller."""
    bundles, plugins = _make_bundles(paper=_FakeVenuePlugin("paper"))
    spec = _fake_spec()

    first = bundles.get("paper", "default", spec)
    second = bundles.get("paper", "default", spec)

    assert first is second
    assert first.exchange is second.exchange
    assert plugins["paper"].build_calls == 1


def test_distinct_accounts_on_one_venue_build_distinct_bundles() -> None:
    """The memo must NOT over-collapse: two accounts are two authenticated sessions."""
    bundles, plugins = _make_bundles(okx=_FakeVenuePlugin("okx"))

    account_a = bundles.get("okx", "a", _fake_spec("a"))
    account_b = bundles.get("okx", "b", _fake_spec("b"))

    assert account_a is not account_b
    assert account_a.exchange is not account_b.exchange
    assert plugins["okx"].build_calls == 2


def test_same_account_id_on_two_venues_does_not_collide() -> None:
    """VENUE-07 adjacency edge — the key is the PAIR, not the bare ``account_id``."""
    bundles, plugins = _make_bundles(
        okx=_FakeVenuePlugin("okx"), paper=_FakeVenuePlugin("paper")
    )

    okx_bundle = bundles.get("okx", "main", _fake_spec("main"))
    paper_bundle = bundles.get("paper", "main", _fake_spec("main"))

    assert okx_bundle is not paper_bundle
    # Each bundle came from its OWN plugin, not the other venue's.
    assert okx_bundle.exchange.built_by == "okx"
    assert paper_bundle.exchange.built_by == "paper"
    assert plugins["okx"].build_calls == 1
    assert plugins["paper"].build_calls == 1


def test_unknown_venue_fails_loud() -> None:
    """VENUE-07 empty edge — an unregistered venue raises, it never returns ``None``."""
    bundles = VenueBundles(
        ExecutionVenueRegistry(), connectors=object(), ctx=_fake_ctx()
    )

    with pytest.raises(KeyError):
        bundles.get("nope", "default", _fake_spec())

    # Nothing was memoized by the failed lookup.
    assert bundles._memo == {}


def test_connectors_object_is_threaded_through_untouched() -> None:
    """``VenueBundles`` passes the connectors reference on; it reads nothing off it."""
    plugin = _FakeVenuePlugin("okx")
    registry = ExecutionVenueRegistry()
    registry.register("okx", plugin)  # type: ignore[arg-type]
    exploding = _ExplodingConnectorProvider()

    # Constructing and calling ``get`` would raise AssertionError from
    # ``__getattribute__`` if VenueBundles read ANY attribute off the object.
    bundles = VenueBundles(registry, connectors=exploding, ctx=_fake_ctx())
    bundles.get("okx", "default", _fake_spec())

    assert plugin.received_connectors is exploding


def test_memo_iteration_order_is_stable_across_repeated_gets() -> None:
    """VENUE-07 ordering edge — a repeated ``get`` never reorders or displaces an entry."""
    bundles, _ = _make_bundles(
        okx=_FakeVenuePlugin("okx"), paper=_FakeVenuePlugin("paper")
    )
    keys = [("okx", "a"), ("paper", "a"), ("okx", "b")]

    built = [bundles.get(venue, account, _fake_spec(account)) for venue, account in keys]
    order_after_first_pass = list(bundles._memo)

    rebuilt = [bundles.get(venue, account, _fake_spec(account)) for venue, account in keys]

    assert order_after_first_pass == keys
    assert list(bundles._memo) == keys
    # No entry was displaced: every key still maps to its original bundle.
    assert all(a is b for a, b in zip(built, rebuilt, strict=True))
    assert [bundles._memo[k] for k in keys] == built
