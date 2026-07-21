"""Unit contract for assemble_venue — resolve plugins, build bundle + provider + lifecycle (05-06, VENUE-06, D-06).

Drives ``assemble_venue(ctx, spec, connectors, exec_registry, data_registry)``
against an okx-shaped spec AND a paper-shaped spec using REAL registries populated
with the REAL plugins (05-05) — proving venue assembly standalone WITHOUT standing
up a ``LiveTradingSystem`` (D-06). No ccxt / creds: the OKX concretions only BIND
the injected fake connector at construction (no network), so a trivial fake
``ConnectorProvider`` suffices; paper never touches the provider at all (D-05).

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _FakeConnector:
    """Trivial ``LiveConnector`` stand-in — the OKX concretions only bind it."""


class _FakeConnectorProvider:
    """Memoizes ONE fake connector per (venue, account_id) — the D-03 shared-connector shape."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self._memo: dict[tuple[str, str], _FakeConnector] = {}

    def get(self, venue: str, account_id: str, spec: Any) -> _FakeConnector:
        self.calls.append((venue, account_id, spec))
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = _FakeConnector()
        return self._memo[key]

    def close_all(self) -> None:  # pragma: no cover - not exercised by assemble
        self._memo.clear()


class _ExplodingConnectorProvider:
    """A ConnectorProvider whose ``get`` MUST NOT be called on the paper path (D-05)."""

    def get(self, venue: str, account_id: str, spec: Any) -> Any:
        raise AssertionError(
            "the paper venue must not touch the ConnectorProvider (D-05, connector=None)"
        )

    def close_all(self) -> None:  # pragma: no cover - defensive
        raise AssertionError("paper path must not touch the ConnectorProvider")


class _FakeSimulatedExchange:
    """A stand-in for the compose-built 'simulated' SimulatedExchange (reused AS-IS)."""


def _fake_ctx() -> SimpleNamespace:
    """A fake EngineContext exposing the ``bus`` + ``config`` the OKX plugin reads."""
    from itrader.config import ITraderConfig

    return SimpleNamespace(bus=object(), config=ITraderConfig())


def _spec(execution_venue: str, data_provider: str, account_id: str | None = None) -> SimpleNamespace:
    """A lightweight spec exposing the three venue selectors assemble/plugins read."""
    return SimpleNamespace(
        execution_venue=execution_venue,
        data_provider=data_provider,
        account_id=account_id,
    )


def _okx_registries() -> tuple[Any, Any]:
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin
    from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry

    exec_reg = ExecutionVenueRegistry()
    data_reg = DataProviderRegistry()
    exec_reg.register("okx", OkxVenuePlugin())
    data_reg.register("okx", OkxDataPlugin())
    return exec_reg, data_reg


def _paper_registries(simulated: Any) -> tuple[Any, Any]:
    from itrader.venues.paper_plugin import PaperVenuePlugin
    from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry

    from tests.support.replay_harness import TestDataPlugin

    exec_reg = ExecutionVenueRegistry()
    data_reg = DataProviderRegistry()
    exec_reg.register("paper", PaperVenuePlugin(simulated))
    # TEST-01/D-18: the replay data plugin left production for the test harness; the
    # paper↔replay pairing survives ONLY here in the fixture (production paper → OKX, D-21).
    data_reg.register("replay", TestDataPlugin())
    return exec_reg, data_reg


def test_assemble_okx_returns_bundle_and_lifecycle() -> None:
    """okx spec: assemble resolves the okx plugins, builds an OkxExchange bundle + lifecycle."""
    from itrader.execution_handler.exchanges.okx import OkxExchange
    from itrader.price_handler.providers.okx_provider import OkxDataProvider
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.lifecycle import VenueLifecycle

    exec_reg, data_reg = _okx_registries()
    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _spec("okx", "okx", account_id=None)

    bundle, lifecycle = assemble_venue(ctx, spec, connectors, exec_reg, data_reg)

    assert isinstance(bundle, VenueBundle)
    assert isinstance(bundle.exchange, OkxExchange)
    assert isinstance(lifecycle, VenueLifecycle)
    assert isinstance(lifecycle.provider, OkxDataProvider)
    # lifecycle exposes the bundle it orchestrates.
    assert lifecycle.bundle is bundle


def test_assemble_okx_shares_one_connector_across_exec_and_data() -> None:
    """The exec bundle and data provider borrow the SAME memoized connector (D-03)."""
    from itrader.venues.assemble import assemble_venue

    exec_reg, data_reg = _okx_registries()
    connectors = _FakeConnectorProvider()
    spec = _spec("okx", "okx", account_id=None)

    bundle, lifecycle = assemble_venue(_fake_ctx(), spec, connectors, exec_reg, data_reg)

    # ONE connector for ("okx", "default") shared by BOTH builders: two get() calls,
    # one memoized instance carried on both arms.
    assert connectors.calls == [
        ("okx", "default", spec),
        ("okx", "default", spec),
    ]
    assert bundle.connector is lifecycle.provider._connector


def test_assemble_paper_returns_connectorless_bundle_and_replay_provider() -> None:
    """paper spec: assemble builds a connector=None bundle + a TestLiveDataProvider lifecycle.

    The paper↔replay pairing is a TEST-only fixture now (D-18/D-21): the relocated
    ``TestDataPlugin`` is registered under ``'replay'`` in ``_paper_registries``.
    """
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.lifecycle import VenueLifecycle

    from tests.support.replay_harness import TestLiveDataProvider

    simulated = _FakeSimulatedExchange()
    exec_reg, data_reg = _paper_registries(simulated)
    # paper never touches the ConnectorProvider (D-05) — an exploding one proves it.
    connectors = _ExplodingConnectorProvider()
    spec = _spec("paper", "replay", account_id=None)

    bundle, lifecycle = assemble_venue(_fake_ctx(), spec, connectors, exec_reg, data_reg)

    assert isinstance(bundle, VenueBundle)
    # D-05: reuse the injected simulated exchange AS-IS, no live connector.
    assert bundle.exchange is simulated
    assert bundle.connector is None
    assert isinstance(lifecycle, VenueLifecycle)
    assert isinstance(lifecycle.provider, TestLiveDataProvider)


def test_assemble_unregistered_execution_venue_fails_loud() -> None:
    """An unregistered execution_venue raises KeyError (fail loud, D-01)."""
    import pytest

    from itrader.venues.assemble import assemble_venue

    exec_reg, data_reg = _okx_registries()
    connectors = _FakeConnectorProvider()
    spec = _spec("binance", "okx", account_id=None)

    with pytest.raises(KeyError):
        assemble_venue(_fake_ctx(), spec, connectors, exec_reg, data_reg)


# --------------------------------------------------------------------------- #
# assemble_venues — the PLURAL form (11-09)
#
# Driven here, with NO LiveTradingSystem, for exactly the reason the singular form is:
# the assembly logic is authored ONCE in venues/assemble.py, and a plural form that
# could only be exercised through the live composition root would put it back in the
# facade in everything but name.
# --------------------------------------------------------------------------- #


def test_assemble_venues_returns_one_lifecycle_per_account() -> None:
    """Two account specs -> two lifecycles, keyed by account id, over two connectors.

    The DISTINCT-connector assertion is the load-bearing half. Two entries in a map
    prove only that the loop ran twice; two accounts sharing one authenticated session
    would satisfy that while routing account B's orders through account A's credentials.
    """
    from itrader.venues.assemble import assemble_venues
    from itrader.venues.lifecycle import VenueLifecycle

    exec_reg, data_reg = _okx_registries()
    connectors = _FakeConnectorProvider()
    specs = [_spec("okx", "okx", "acct-a"), _spec("okx", "okx", "acct-b")]

    lifecycles = assemble_venues(_fake_ctx(), specs, connectors, exec_reg, data_reg)

    assert set(lifecycles) == {"acct-a", "acct-b"}
    assert all(isinstance(v, VenueLifecycle) for v in lifecycles.values())
    assert (lifecycles["acct-a"].bundle.connector
            is not lifecycles["acct-b"].bundle.connector)


def test_assemble_venues_preserves_spec_order_so_the_primary_is_deterministic() -> None:
    """Insertion order IS the primary contract — the first spec is the primary.

    The facade binds ONE data provider to the ONE feed and reads it off the first
    entry, so an order-losing implementation (a set, or a sorted key) would silently
    re-point the feed at a different account's stream between boots.
    """
    from itrader.venues.assemble import assemble_venues

    exec_reg, data_reg = _okx_registries()
    specs = [_spec("okx", "okx", "z-last"), _spec("okx", "okx", "a-first")]

    lifecycles = assemble_venues(
        _fake_ctx(), specs, _FakeConnectorProvider(), exec_reg, data_reg)

    assert list(lifecycles) == ["z-last", "a-first"]


def test_assemble_venues_normalizes_an_unnamed_account_to_default() -> None:
    """``account_id=None`` keys under "default" — the same key the plugins memoize on.

    The venue plugins, ``ExecutionHandler.exchanges`` and the UID guard all apply
    ``account_id or "default"``. Keying differently here would make the lifecycle map
    disagree with the exchange registry for exactly the unnamed single-account run that
    is the most common deployment.
    """
    from itrader.venues.assemble import assemble_venues

    exec_reg, data_reg = _okx_registries()

    lifecycles = assemble_venues(
        _fake_ctx(), [_spec("okx", "okx", None)], _FakeConnectorProvider(),
        exec_reg, data_reg)

    assert list(lifecycles) == ["default"]


def test_assemble_venues_on_an_empty_spec_list_is_a_clean_empty_map() -> None:
    """No specs -> no lifecycles, and no exception. The unregistered-venue edge."""
    from itrader.venues.assemble import assemble_venues

    exec_reg, data_reg = _okx_registries()

    assert assemble_venues(
        _fake_ctx(), [], _FakeConnectorProvider(), exec_reg, data_reg) == {}


def test_assemble_venues_propagates_an_unregistered_venue_loudly() -> None:
    """One bad spec fails the whole assembly (D-01) — no partial, half-wired venue map."""
    import pytest

    from itrader.venues.assemble import assemble_venues

    exec_reg, data_reg = _okx_registries()
    specs = [_spec("okx", "okx", "acct-a"), _spec("binance", "okx", "acct-b")]

    with pytest.raises(KeyError):
        assemble_venues(
            _fake_ctx(), specs, _FakeConnectorProvider(), exec_reg, data_reg)


def test_assemble_unregistered_data_provider_fails_loud() -> None:
    """An unregistered data_provider raises KeyError (fail loud, D-01)."""
    import pytest

    from itrader.venues.assemble import assemble_venue

    exec_reg, data_reg = _okx_registries()
    connectors = _FakeConnectorProvider()
    spec = _spec("okx", "nope", account_id=None)

    with pytest.raises(KeyError):
        assemble_venue(_fake_ctx(), spec, connectors, exec_reg, data_reg)
