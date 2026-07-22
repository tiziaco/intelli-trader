"""Unit contract for assemble_venue — resolve the shared bundle + wrap it in a lifecycle (05-06, VENUE-06, D-06).

Drives ``assemble_venue(spec, connectors, bundles)`` against an okx-shaped spec AND a
paper-shaped spec using a REAL ``VenueBundles`` memo over REAL registries populated
with the REAL plugins (05-05) — proving venue assembly standalone WITHOUT standing up
a ``LiveTradingSystem`` (D-06). No ccxt / creds: the OKX concretions only BIND the
injected fake connector at construction (no network), so a trivial fake
``ConnectorProvider`` suffices; paper never touches the provider at all (D-05).

Proves, beyond the 05-06 contract:
  - **D-14 / WR-07 — assembly builds NO data provider.** ``assemble_venue`` used to
    call ``build_provider`` for every account and the composition root discarded all
    but the primary's. Each construction resolves that account's OWN credentials
    through the ``CredentialResolver``, so a discarded provider is a live
    credential-bearing object with no owner, no lifecycle and no halt path — WR-07.
    The counter assertions below are the mechanical proof, and they are the assertions
    this file did NOT have, which is why WR-07 shipped. Only the PRIMARY lifecycle
    carries the ONE provider the composition root builds and hands in.
  - **D-08 — one bundle per ``(venue, account_id)``, tree-wide.** ``assemble_venue``
    resolves its bundle THROUGH the shared ``VenueBundles`` memo instead of calling
    ``build_bundle`` on the registry itself. Asserted by object IDENTITY plus the
    plugin's build count: "a bundle exists" passes identically whether one or two were
    built, so it cannot gate a duplicate-construction defect.

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


def _paper_exchange_config() -> Any:
    """The RUN-DERIVED ExchangeConfig the paper plugin builds its exchange from (D-17).

    11.1-07: ``PaperVenuePlugin`` no longer takes a pre-built exchange — it takes the
    config and mints its own, symmetric with ``OkxVenuePlugin``.
    """
    from itrader.config import ExchangeConfig

    return ExchangeConfig.default()


def _fake_ctx() -> SimpleNamespace:
    """A fake EngineContext exposing ``bus`` + ``config`` (OKX) and ``rng`` (paper, D-07)."""
    import random

    from itrader.config import ITraderConfig

    return SimpleNamespace(
        bus=object(), config=ITraderConfig(), rng=random.Random(42))


def _spec(execution_venue: str, data_provider: str, account_id: str | None = None) -> SimpleNamespace:
    """A lightweight spec exposing the three venue selectors assemble/plugins read."""
    return SimpleNamespace(
        execution_venue=execution_venue,
        data_provider=data_provider,
        account_id=account_id,
    )


def _okx_registry() -> Any:
    from itrader.venues.okx_plugin import OkxVenuePlugin
    from itrader.venues.registry import ExecutionVenueRegistry

    exec_reg = ExecutionVenueRegistry()
    exec_reg.register("okx", OkxVenuePlugin())
    return exec_reg


def _okx_bundles(connectors: Any) -> Any:
    """The shared ``VenueBundles`` memo over an okx-only registry (11.1-05, D-08)."""
    from itrader.venues.bundles import VenueBundles

    return VenueBundles(_okx_registry(), connectors, _fake_ctx())


def _paper_bundles(connectors: Any, exchange_config: Any) -> Any:
    """The shared memo over a paper-only registry (D-17: the plugin holds the config)."""
    from itrader.venues.bundles import VenueBundles
    from itrader.venues.paper_plugin import PaperVenuePlugin
    from itrader.venues.registry import ExecutionVenueRegistry

    exec_reg = ExecutionVenueRegistry()
    exec_reg.register("paper", PaperVenuePlugin(exchange_config))
    return VenueBundles(exec_reg, connectors, _fake_ctx())


def _count_okx_provider_builds(monkeypatch: Any) -> list[int]:
    """Count EVERY ``OkxDataPlugin.build_provider`` call, wherever it originates (D-14/WR-07).

    Patched on the CLASS, not on an instance handed to assemble, so the counter fires
    even for a provider built through a registry assembly reached for itself. A counter
    on an object assembly never sees would be vacuous.
    """
    from itrader.venues.okx_plugin import OkxDataPlugin

    calls: list[int] = []
    original = OkxDataPlugin.build_provider

    def _counting(self: Any, ctx: Any, spec: Any, connectors: Any) -> Any:
        calls.append(1)
        return original(self, ctx, spec, connectors)

    monkeypatch.setattr(OkxDataPlugin, "build_provider", _counting)
    return calls


def test_assemble_okx_returns_bundle_and_lifecycle() -> None:
    """okx spec: assemble resolves the okx plugin, returns an OkxExchange bundle + lifecycle."""
    from itrader.execution_handler.exchanges.okx import OkxExchange
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.lifecycle import VenueLifecycle

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)
    spec = _spec("okx", "okx", account_id=None)

    bundle, lifecycle = assemble_venue(spec, connectors, bundles)

    assert isinstance(bundle, VenueBundle)
    assert isinstance(bundle.exchange, OkxExchange)
    assert isinstance(lifecycle, VenueLifecycle)
    # lifecycle exposes the bundle it orchestrates.
    assert lifecycle.bundle is bundle
    # D-14: assembly builds NO provider; the composition root hands one in for the
    # primary account only.
    assert lifecycle.provider is None


def test_assemble_okx_borrows_the_memoized_connector() -> None:
    """The exec bundle borrows ONE memoized connector for its (venue, account_id) (D-03).

    Post-D-14 the data arm no longer borrows a second time from here, so exactly ONE
    ``ConnectorProvider.get`` call is made per assembled account.
    """
    from itrader.venues.assemble import assemble_venue

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)
    spec = _spec("okx", "okx", account_id=None)

    bundle, _lifecycle = assemble_venue(spec, connectors, bundles)

    assert connectors.calls == [("okx", "default", spec)]
    assert bundle.connector is connectors._memo[("okx", "default")]


def test_assemble_venue_resolves_the_bundle_through_the_shared_memo() -> None:
    """D-08: the bundle is the memo's, and the plugin built it exactly ONCE.

    Identity is the load-bearing half. ``assemble_venue`` used to call
    ``exec_registry.get(venue).build_bundle(...)`` directly, so the venue-assembly arm
    and ``ExecutionHandler``/``PortfolioHandler`` (which read ``VenueBundles``) held two
    different exchanges for one ``(venue, account_id)``. Two ``OkxExchange`` objects for
    one authenticated account double-spawn ``_stream_fills`` / ``_stream_orders``. An
    assertion that "a bundle exists" passes identically under one build or two.
    """
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.bundles import VenueBundles
    from itrader.venues.registry import ExecutionVenueRegistry

    class _CountingVenuePlugin:
        def __init__(self) -> None:
            self.build_calls = 0

        @property
        def credential_model(self) -> type[Any] | None:
            return None

        def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> Any:
            from itrader.venues.bundle import VenueBundle

            self.build_calls += 1
            return VenueBundle(
                exchange=SimpleNamespace(build_seq=self.build_calls),  # type: ignore[arg-type]
                account_factory=lambda *a, **k: object(),
                connector=None,
            )

        def new_account(self, portfolio_ref: Any, config: Any) -> Any:  # pragma: no cover
            raise AssertionError("assemble must not mint accounts")

    plugin = _CountingVenuePlugin()
    registry = ExecutionVenueRegistry()
    registry.register("okx", plugin)  # type: ignore[arg-type]
    connectors = _FakeConnectorProvider()
    bundles = VenueBundles(registry, connectors, _fake_ctx())
    spec = _spec("okx", "okx", account_id="acct-a")

    # A prior reader (the execution arm) already asked the memo for this pair.
    pre_built = bundles.get("okx", "acct-a", spec)
    bundle, lifecycle = assemble_venue(spec, connectors, bundles)

    assert bundle is pre_built
    assert lifecycle.bundle is pre_built
    assert bundle.exchange is pre_built.exchange
    assert plugin.build_calls == 1


def test_assemble_venue_takes_no_data_registry() -> None:
    """D-14, structurally: assembly cannot build a provider — it holds no data registry.

    The strongest form of the WR-07 mitigation is that the capability is absent, not
    merely unused. A signature check is how that stays true: re-introducing the
    parameter is the first step of restoring the eager per-account build.
    """
    import inspect

    from itrader.venues.assemble import assemble_venue, assemble_venues

    for func in (assemble_venue, assemble_venues):
        parameters = inspect.signature(func).parameters
        assert "data_registry" not in parameters, (
            f"{func.__name__} must not take a data registry (D-14): assembly builds no "
            "provider, so a per-account credential-bearing provider cannot be built and "
            "discarded (WR-07)"
        )


def test_assemble_venue_builds_no_data_provider(monkeypatch: Any) -> None:
    """D-14/WR-07: ZERO ``build_provider`` calls during a single-account assembly."""
    from itrader.venues.assemble import assemble_venue

    build_calls = _count_okx_provider_builds(monkeypatch)
    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)

    _bundle, lifecycle = assemble_venue(
        _spec("okx", "okx", account_id="acct-a"), connectors, bundles)

    assert build_calls == []
    assert lifecycle.provider is None


def test_assemble_venues_over_two_accounts_builds_no_providers(monkeypatch: Any) -> None:
    """D-14/WR-07: ZERO ``build_provider`` calls across a TWO-account assembly.

    The two-account case is the one WR-07 describes: N accounts produced N providers
    and N-1 were discarded. The count is asserted, not the wiring — a test that only
    checked "the primary's provider reached the feed" passes while N-1 credential-
    bearing objects are constructed behind it.
    """
    from itrader.venues.assemble import assemble_venues

    build_calls = _count_okx_provider_builds(monkeypatch)
    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)
    specs = [_spec("okx", "okx", "acct-a"), _spec("okx", "okx", "acct-b")]

    lifecycles = assemble_venues(specs, connectors, bundles)

    assert build_calls == []
    assert [lc.provider for lc in lifecycles.values()] == [None, None]


def test_assemble_venues_hands_the_one_provider_to_the_primary_only() -> None:
    """D-14: the ONE provider goes to the FIRST spec's lifecycle and to no other.

    ONE feed means ONE provider. The primary is the first spec (the ordering contract
    ``assemble_venues`` documents), so a map that lost insertion order would silently
    re-point the market-data source between restarts.
    """
    from itrader.venues.assemble import assemble_venues

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)
    provider = object()
    specs = [_spec("okx", "okx", "acct-a"), _spec("okx", "okx", "acct-b")]

    lifecycles = assemble_venues(
        specs, connectors, bundles, primary_provider=provider)  # type: ignore[arg-type]

    assert lifecycles["acct-a"].provider is provider
    assert lifecycles["acct-b"].provider is None


def test_assemble_paper_returns_connectorless_bundle_and_no_provider() -> None:
    """paper spec: assemble builds a connector=None bundle and NO provider (D-05/D-14)."""
    from itrader.execution_handler.exchanges.simulated import SimulatedExchange
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.lifecycle import VenueLifecycle

    exchange_config = _paper_exchange_config()
    # paper never touches the ConnectorProvider (D-05) — an exploding one proves it.
    connectors = _ExplodingConnectorProvider()
    bundles = _paper_bundles(connectors, exchange_config)
    spec = _spec("paper", "replay", account_id=None)

    bundle, lifecycle = assemble_venue(spec, connectors, bundles)

    assert isinstance(bundle, VenueBundle)
    # 11.1-07 (D-06/D-17): the plugin BUILDS its own SimulatedExchange from the
    # injected config — nothing is handed in pre-built any more.
    assert isinstance(bundle.exchange, SimulatedExchange)
    assert bundle.exchange.config is exchange_config
    assert bundle.connector is None
    assert isinstance(lifecycle, VenueLifecycle)
    assert lifecycle.provider is None


def test_assemble_unregistered_execution_venue_fails_loud() -> None:
    """An unregistered execution_venue raises KeyError (fail loud, D-01)."""
    import pytest

    from itrader.venues.assemble import assemble_venue

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)
    spec = _spec("binance", "okx", account_id=None)

    with pytest.raises(KeyError):
        assemble_venue(spec, connectors, bundles)


def test_an_unregistered_venue_memoizes_nothing() -> None:
    """The failed lookup leaves the shared memo untouched — no half-wired venue (D-01)."""
    import pytest

    from itrader.venues.assemble import assemble_venue

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)

    with pytest.raises(KeyError):
        assemble_venue(_spec("binance", "okx", "acct-a"), connectors, bundles)

    assert bundles._memo == {}


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

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)
    specs = [_spec("okx", "okx", "acct-a"), _spec("okx", "okx", "acct-b")]

    lifecycles = assemble_venues(specs, connectors, bundles)

    assert set(lifecycles) == {"acct-a", "acct-b"}
    assert all(isinstance(v, VenueLifecycle) for v in lifecycles.values())
    assert (lifecycles["acct-a"].bundle.connector
            is not lifecycles["acct-b"].bundle.connector)
    # D-08: two accounts are two bundles — the memo must not over-collapse.
    assert lifecycles["acct-a"].bundle is not lifecycles["acct-b"].bundle


def test_assemble_venues_preserves_spec_order_so_the_primary_is_deterministic() -> None:
    """Insertion order IS the primary contract — the first spec is the primary.

    The facade binds ONE data provider to the ONE feed and the composition root builds
    it for the first spec, so an order-losing implementation (a set, or a sorted key)
    would silently re-point the feed at a different account's stream between boots.
    """
    from itrader.venues.assemble import assemble_venues

    connectors = _FakeConnectorProvider()
    specs = [_spec("okx", "okx", "z-last"), _spec("okx", "okx", "a-first")]

    lifecycles = assemble_venues(specs, connectors, _okx_bundles(connectors))

    assert list(lifecycles) == ["z-last", "a-first"]


def test_assemble_venues_normalizes_an_unnamed_account_to_default() -> None:
    """``account_id=None`` keys under "default" — the same key the plugins memoize on.

    The venue plugins, ``ExecutionHandler.exchanges``, ``VenueBundles`` and the UID
    guard all apply ``account_id or "default"``. Keying differently here would make the
    lifecycle map disagree with the exchange registry for exactly the unnamed
    single-account run that is the most common deployment.
    """
    from itrader.venues.assemble import assemble_venues

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)

    lifecycles = assemble_venues(
        [_spec("okx", "okx", None)], connectors, bundles)

    assert list(lifecycles) == ["default"]
    # The SAME normalization reached the shared memo — one account key, tree-wide.
    assert list(bundles._memo) == [("okx", "default")]


def test_assemble_venues_on_an_empty_spec_list_is_a_clean_empty_map() -> None:
    """No specs -> no lifecycles, no bundles, and no exception (VENUE-07 empty edge).

    A live boot with ZERO accounts is the normal fresh-deployment state (D-09), not a
    misconfiguration, so assembly must degrade to an empty map rather than raise.
    """
    from itrader.venues.assemble import assemble_venues

    connectors = _FakeConnectorProvider()
    bundles = _okx_bundles(connectors)

    assert assemble_venues([], connectors, bundles) == {}
    assert bundles._memo == {}


def test_assemble_venues_propagates_an_unregistered_venue_loudly() -> None:
    """One bad spec fails the whole assembly (D-01) — no partial, half-wired venue map."""
    import pytest

    from itrader.venues.assemble import assemble_venues

    connectors = _FakeConnectorProvider()
    specs = [_spec("okx", "okx", "acct-a"), _spec("binance", "okx", "acct-b")]

    with pytest.raises(KeyError):
        assemble_venues(specs, connectors, _okx_bundles(connectors))
