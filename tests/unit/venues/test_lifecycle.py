"""Unit contract for VenueLifecycle — fixed connector start/stop order, None-guards (05-06, VENUE-06, D-10).

Drives ``VenueLifecycle.start()`` / ``stop()`` against two bundle SHAPES without
standing up a ``LiveTradingSystem`` (D-06 standalone testability):

  - an okx-shaped bundle (``connector`` PRESENT) → ``start`` calls ``connect``,
    ``stop`` tears the connector down (``ConnectorProvider.close_all`` when a
    provider is passed, else the bundle connector's ``disconnect``);
  - a paper-shaped bundle (``connector=None``) → ``start`` / ``stop`` no-op the
    connector step and NEVER raise on the absent member (D-10 structural
    None-guard, not a venue-string check).

No ccxt / creds are needed: the lifecycle only drives ``connect`` / ``disconnect``
/ ``close_all`` on injected fakes.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _FakeConnector:
    """Records ``connect`` / ``disconnect`` so the lifecycle order is observable."""

    def __init__(self) -> None:
        self.connected = 0
        self.disconnected = 0

    def connect(self) -> None:
        self.connected += 1

    def disconnect(self) -> None:
        self.disconnected += 1


class _FakeConnectorProvider:
    """Records ``close_all`` — the ConnectorProvider teardown path."""

    def __init__(self) -> None:
        self.closed = 0

    def close_all(self) -> None:
        self.closed += 1


def _bundle(connector: Any) -> SimpleNamespace:
    """A fake VenueBundle exposing only the ``connector`` member the lifecycle reads."""
    return SimpleNamespace(connector=connector)


def _provider() -> SimpleNamespace:
    """A fake LiveDataProvider — the lifecycle only holds the ref."""
    return SimpleNamespace()


def test_start_connects_when_connector_present() -> None:
    """okx-shaped bundle (connector present): start() drives connector.connect()."""
    from itrader.venues.lifecycle import VenueLifecycle

    connector = _FakeConnector()
    lifecycle = VenueLifecycle(_bundle(connector), _provider())

    lifecycle.start()

    assert connector.connected == 1
    assert connector.disconnected == 0


def test_stop_closes_via_provider_when_present() -> None:
    """stop() prefers ConnectorProvider.close_all when a provider is injected."""
    from itrader.venues.lifecycle import VenueLifecycle

    connector = _FakeConnector()
    connectors = _FakeConnectorProvider()
    lifecycle = VenueLifecycle(_bundle(connector), _provider(), connectors=connectors)

    lifecycle.stop()

    assert connectors.closed == 1
    # close_all owns the disconnect fan-out — the bundle connector is not
    # disconnected a second time directly.
    assert connector.disconnected == 0


def test_stop_disconnects_bundle_connector_without_provider() -> None:
    """stop() falls back to bundle.connector.disconnect when no provider is passed."""
    from itrader.venues.lifecycle import VenueLifecycle

    connector = _FakeConnector()
    lifecycle = VenueLifecycle(_bundle(connector), _provider())

    lifecycle.stop()

    assert connector.disconnected == 1


def test_paper_bundle_start_stop_noop_connector_step() -> None:
    """paper-shaped bundle (connector=None): start/stop no-op the connector step, never raise."""
    from itrader.venues.lifecycle import VenueLifecycle

    lifecycle = VenueLifecycle(_bundle(None), _provider())

    # Absent connector -> structural None-guard, no AttributeError.
    lifecycle.start()
    lifecycle.stop()


def test_paper_bundle_with_provider_stop_is_safe_noop() -> None:
    """paper bundle + an (empty-memo) ConnectorProvider: stop() close_all is a safe no-op."""
    from itrader.venues.lifecycle import VenueLifecycle

    connectors = _FakeConnectorProvider()
    lifecycle = VenueLifecycle(_bundle(None), _provider(), connectors=connectors)

    lifecycle.start()
    lifecycle.stop()

    # close_all is still called (it iterates the empty memo -> no-op), never raising.
    assert connectors.closed == 1


def test_bundle_and_provider_are_exposed_read_only() -> None:
    """The composition root reads .bundle / .provider off the lifecycle."""
    from itrader.venues.lifecycle import VenueLifecycle

    bundle = _bundle(_FakeConnector())
    provider = _provider()
    lifecycle = VenueLifecycle(bundle, provider)

    assert lifecycle.bundle is bundle
    assert lifecycle.provider is provider
