"""Unit contract for the OKX venue/data/connector plugins (05-05, VENUE-02, D-04).

Drives ``OkxVenuePlugin.build_bundle`` / ``OkxDataPlugin.build_provider`` with a
FAKE ``ConnectorProvider`` (``get`` returns a trivial fake connector) + a fake
``ctx`` (``bus`` attr) + a fake ``spec`` (``account_id=None``), asserting:

  - the bundle shape (exchange is an ``OkxExchange`` wrapping the fake connector,
    ``account_factory`` is callable and mints a ``VenueAccount``, ``connector`` is
    the SAME fake instance, ``lifecycle`` is ``None``),
  - the data provider is an ``OkxDataProvider`` bound to the SAME memoized
    connector (both arms call ``connectors.get("okx", "default", spec)``),
  - importing ``itrader.venues.okx_plugin`` pulls NO ccxt at module scope (D-04
    triple-deferral — the concretion import lives inside ``build*``).

No creds / no ccxt.pro client are needed: the OKX concretion constructors only
BIND the injected connector (no network at construction), so a trivial fake
connector suffices. The register-vs-build inertness proof is the subprocess gate
in ``tests/integration/test_okx_inertness.py`` (Task 3).

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _FakeConnector:
    """Trivial ``LiveConnector`` stand-in — the OKX concretions only bind it."""


class _FakeConnectorProvider:
    """Records every ``get`` call and hands back ONE memoized fake connector.

    Mirrors the real ``ConnectorProvider.get(venue, account_id, spec)`` memo: the
    same ``(venue, account_id)`` key returns the SAME instance, proving both the
    exec bundle and the data provider borrow one connector (D-03).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self._memo: dict[tuple[str, str], _FakeConnector] = {}

    def get(self, venue: str, account_id: str, spec: Any) -> _FakeConnector:
        self.calls.append((venue, account_id, spec))
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = _FakeConnector()
        return self._memo[key]


def _fake_ctx() -> SimpleNamespace:
    """A fake ``EngineContext`` exposing the ``bus`` + ``config`` the plugin reads."""
    from itrader.config import ITraderConfig

    return SimpleNamespace(bus=object(), config=ITraderConfig())


def _fake_spec(account_id: str | None = None) -> SimpleNamespace:
    """A fake ``SystemSpec`` exposing only ``account_id`` (defaulted None)."""
    return SimpleNamespace(account_id=account_id)


def test_okx_plugin_module_imports_no_ccxt() -> None:
    """Importing the plugin module pulls no ccxt at MODULE scope (D-04 layer 1)."""
    import ast
    import pathlib

    import itrader.venues.okx_plugin as mod

    source = pathlib.Path(mod.__file__).read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        # Only inspect MODULE-LEVEL imports (direct children of the module body):
        # a lazy import inside a build* method body is exactly what D-04 requires.
        if isinstance(node, ast.Module):
            for child in node.body:
                if isinstance(child, ast.Import):
                    imported += [alias.name for alias in child.names]
                elif isinstance(child, ast.ImportFrom) and child.module:
                    imported.append(child.module)
    forbidden = [
        name
        for name in imported
        if any(
            tok in name
            for tok in ("ccxt", "itrader.connectors.okx", "okx_settings")
        )
    ]
    assert not forbidden, (
        "D-04 violation: itrader.venues.okx_plugin imports an OKX concretion / "
        f"ccxt at module scope: {forbidden!r} (must be lazy inside build*)"
    )


def test_okx_venue_plugin_builds_bundle_wrapping_the_connector() -> None:
    """build_bundle returns an OkxExchange-backed VenueBundle over the fake connector."""
    from itrader.execution_handler.exchanges.okx import OkxExchange
    from itrader.portfolio_handler.account import VenueAccount
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.okx_plugin import OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id=None)

    bundle = OkxVenuePlugin().build_bundle(ctx, spec, connectors)

    assert isinstance(bundle, VenueBundle)
    assert isinstance(bundle.exchange, OkxExchange)
    # account_id=None -> the "default" logical account key (D-07).
    assert connectors.calls == [("okx", "default", spec)]
    # The bundle carries the SAME connector the provider handed out.
    assert bundle.exchange._connector is connectors.get("okx", "default", spec)
    assert bundle.connector is connectors.get("okx", "default", spec)
    # lifecycle is built later (05-06) — the plugin leaves it None.
    assert bundle.lifecycle is None
    # account_factory mints a VenueAccount bound to the same connector.
    assert callable(bundle.account_factory)
    account = bundle.account_factory()
    assert isinstance(account, VenueAccount)
    assert account._connector is connectors.get("okx", "default", spec)


def test_okx_data_plugin_shares_the_same_connector() -> None:
    """build_provider returns an OkxDataProvider bound to the SAME memoized connector."""
    from itrader.price_handler.providers.okx_provider import OkxDataProvider
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id=None)

    bundle = OkxVenuePlugin().build_bundle(ctx, spec, connectors)
    provider = OkxDataPlugin().build_provider(ctx, spec, connectors)

    assert isinstance(provider, OkxDataProvider)
    # ONE connector for ("okx", "default") shared across BOTH builders (D-03):
    # two get() calls, one memoized instance.
    assert connectors.calls == [
        ("okx", "default", spec),
        ("okx", "default", spec),
    ]
    assert provider._connector is bundle.connector


def test_okx_plugins_honor_explicit_account_id() -> None:
    """A non-None spec.account_id keys the connector memo (per-account fan-out seam)."""
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin

    connectors = _FakeConnectorProvider()
    ctx = _fake_ctx()
    spec = _fake_spec(account_id="sub-7")

    OkxVenuePlugin().build_bundle(ctx, spec, connectors)
    OkxDataPlugin().build_provider(ctx, spec, connectors)

    assert connectors.calls == [
        ("okx", "sub-7", spec),
        ("okx", "sub-7", spec),
    ]


def test_okx_connector_plugin_is_runtime_checkable_connector_plugin() -> None:
    """OkxConnectorPlugin satisfies the ConnectorPlugin Protocol structurally."""
    from itrader.connectors.provider import ConnectorPlugin
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    assert isinstance(OkxConnectorPlugin(), ConnectorPlugin)


def test_okx_plugins_satisfy_venue_and_data_protocols() -> None:
    """The venue/data plugins structurally satisfy their build Protocols."""
    from itrader.venues.bundle import DataProviderPlugin, VenuePlugin
    from itrader.venues.okx_plugin import OkxDataPlugin, OkxVenuePlugin

    assert isinstance(OkxVenuePlugin(), VenuePlugin)
    assert isinstance(OkxDataPlugin(), DataProviderPlugin)
