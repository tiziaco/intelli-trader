"""D-36 — the ONE live feed borrows a venue CONNECTION, and re-borrows (11.2-07).

"Primary account" is deleted as a concept. The ``FeedConnectionBinder`` owns the ONE
feed's borrowed data connection: it binds the first available, re-borrows when that
account is retired or disabled, and warns + unbinds when none is left. These are the
four behaviours D-36 legislates, exercised directly on the binder with a fake feed and a
fake data registry (there is NO in-tree analog for a re-bindable provider, so the shape
is derived, not copied — 11.2-PATTERNS §"No Analog Found").

The second half proves the MANAGER drives the binder: ``bring_online`` re-evaluates the
binding, and a disabled account drops out of the available set so the feed re-borrows off
it (``_streaming_available`` filters by the store's ``enabled`` flag and by the streaming
``connector is not None`` discriminator).

This directory is package-less (NO ``__init__.py``). 4-space indentation; folder-derived
``unit`` marker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from itrader.config.sql import SqlSettings
from itrader.connectors.provider import ConnectorProvider
from itrader.storage import SqlEngine
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.venues.feed_binder import FeedConnectionBinder
from itrader.venues.venue_account_manager import VenueAccountManager
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_GQ = object()


# --------------------------------------------------------------------------- #
# Fakes — a re-bindable provider path with no socket and no credentials.
# --------------------------------------------------------------------------- #


class _FakeProvider:
    """A data provider that records the feed wiring it received."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.bar_sink: Any = None
        self.global_queue: Any = None

    def set_bar_sink(self, fn: Any) -> None:
        self.bar_sink = fn

    def set_global_queue(self, gq: Any) -> None:
        self.global_queue = gq


class _FakeDataRegistry:
    """``get(name).build_provider(ctx, spec, connectors)`` -> a per-account provider."""

    def get(self, name: str) -> Any:
        return SimpleNamespace(
            build_provider=lambda ctx, spec, connectors: _FakeProvider(spec.account_id))


class _FakeFeed:
    """The ONE feed. ``set_provider`` is the only bind seam; counts its calls."""

    def __init__(self) -> None:
        self.provider: Any = "UNSET"
        self.set_calls = 0

    def set_provider(self, provider: Any) -> None:
        self.provider = provider
        self.set_calls += 1

    def update(self, closed_bar: Any) -> None:  # the bar sink
        return None


def _candidate(account_id: str, *, venue: str = "okx") -> tuple[str, str, Any]:
    return (venue, account_id, SimpleNamespace(account_id=account_id, data_provider="okx"))


def _binder(feed: _FakeFeed) -> FeedConnectionBinder:
    return FeedConnectionBinder(
        feed=feed,
        data_registry=_FakeDataRegistry(),
        ctx=SimpleNamespace(),
        connectors=SimpleNamespace(),
        global_queue=_GQ,
    )


# --------------------------------------------------------------------------- #
# Binder behaviours (the four D-36 rules)
# --------------------------------------------------------------------------- #


def test_zero_accounts_leaves_the_feed_unbound_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-36/D-09 — a boot with no connection to borrow stays unbound, no exception."""
    feed = _FakeFeed()
    binder = _binder(feed)
    with caplog.at_level("WARNING"):
        binder.rebind([])
    assert binder.feed_provider is None
    assert feed.provider == "UNSET"  # never bound
    assert feed.set_calls == 0
    assert any(
        "UNBOUND" in r.getMessage() or "no venue connection" in r.getMessage()
        for r in caplog.records)


def test_the_first_account_online_binds_the_feed() -> None:
    """D-36 — the feed borrows the first available connection and is fully wired."""
    feed = _FakeFeed()
    binder = _binder(feed)
    binder.rebind([_candidate("acct-a")])
    assert binder.feed_provider is not None
    assert binder.feed_provider.account_id == "acct-a"
    assert feed.provider is binder.feed_provider
    assert feed.provider.bar_sink == feed.update
    assert feed.provider.global_queue is _GQ


def test_a_valid_binding_is_idempotent() -> None:
    """D-36 — re-evaluating an unchanged, valid binding rebuilds nothing."""
    feed = _FakeFeed()
    binder = _binder(feed)
    binder.rebind([_candidate("acct-a")])
    bound = binder.feed_provider
    binder.rebind([_candidate("acct-a")])
    assert binder.feed_provider is bound  # same object
    assert feed.set_calls == 1  # not re-set


def test_disabling_the_borrowed_account_re_borrows_and_logs_the_switch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-36 — when the borrowed account is gone, the feed re-borrows the next available."""
    feed = _FakeFeed()
    binder = _binder(feed)
    binder.rebind([_candidate("acct-a")])
    with caplog.at_level("INFO"):
        # acct-a is gone (retired/disabled); only acct-b is available now.
        binder.rebind([_candidate("acct-b")])
    assert binder.feed_provider.account_id == "acct-b"
    assert feed.provider is binder.feed_provider
    assert any("RE-BORROWED" in r.getMessage() for r in caplog.records)


def test_no_connection_left_unbinds_the_feed_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-36 — losing the last connection unbinds the feed and names the cause."""
    feed = _FakeFeed()
    binder = _binder(feed)
    binder.rebind([_candidate("acct-a")])
    with caplog.at_level("WARNING"):
        binder.rebind([])
    assert binder.feed_provider is None
    assert feed.provider is None  # explicitly unbound
    assert any("UNBOUND" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# The manager DRIVES the binder (bring_online + the disabled-account filter)
# --------------------------------------------------------------------------- #


class _RecordingBinder:
    """Records every ``rebind`` the manager makes."""

    feed_provider = None

    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str, Any]]] = []

    def rebind(self, available: Any) -> None:
        self.calls.append(list(available))


class _StreamingBundle:
    """A bundle that looks like a live (connector-bearing) venue."""

    exchange = object()
    connector = object()

    def account_factory(self, **kwargs: Any) -> Any:  # pragma: no cover - unused here
        return object()


class _StreamingBundles:
    """A ``VenueBundles`` stand-in whose ``get`` returns a streaming bundle."""

    def __init__(self) -> None:
        self._bundle = _StreamingBundle()

    def plugin_for(self, venue: str) -> Any:
        return object()

    def get(self, venue: str, account_id: str, spec: Any) -> Any:
        return self._bundle


def _streaming_manager() -> tuple[VenueAccountManager, VenueAccountStore, _RecordingBinder]:
    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    binder = _RecordingBinder()
    manager = VenueAccountManager(
        store,
        _StreamingBundles(),
        ConnectorProvider({}),
        {},  # D-43: the bare (venue, account_id) -> exchange registry
        alert_sink=LogAlertSink(),
        feed_binder=binder,
    )
    return manager, store, binder


def test_bring_online_drives_the_binder_with_the_streaming_account() -> None:
    """The manager re-evaluates the feed binding on every bring_online (D-36)."""
    manager, store, binder = _streaming_manager()
    try:
        store.upsert("okx", "acct-a", secret_ref=None, venue_uid=None,
                     enabled=True, config={}, at=_AT)
        manager.bring_online(store.get("okx", "acct-a"))
        # The last rebind saw exactly the streaming account just brought online.
        assert binder.calls
        last = binder.calls[-1]
        assert [(v, a) for v, a, _ in last] == [("okx", "acct-a")]
    finally:
        store.dispose()


def test_a_disabled_account_drops_out_of_the_available_set() -> None:
    """A retired/disabled account is filtered so the feed re-borrows off it (D-36)."""
    manager, store, binder = _streaming_manager()
    try:
        store.upsert("okx", "acct-a", secret_ref=None, venue_uid=None,
                     enabled=True, config={}, at=_AT)
        manager.bring_online(store.get("okx", "acct-a"))
        # Disable the account at the store, then re-evaluate: it must not be offered.
        store.upsert("okx", "acct-a", secret_ref=None, venue_uid=None,
                     enabled=False, config={}, at=_AT)
        manager.rebind_feed()
        assert binder.calls[-1] == []
    finally:
        store.dispose()
