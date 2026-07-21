"""Unit contract for the venue substrate: the two registries + VenueBundle + plugin Protocols (05-04, VENUE-01/02).

Covers the D-01 explicit-map registration contract (register ≠ import a
concretion; ``get`` fails loud on an unknown venue), the D-02 execution-only
``VenueBundle`` shape (mandatory ``exchange`` + ``account_factory``; Optional
``connector`` / ``lifecycle`` defaulting to ``None``; frozen), and the
``runtime_checkable`` ``VenuePlugin`` / ``DataProviderPlugin`` structural seams.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from dataclasses import FrozenInstanceError

import pytest

from itrader.venues import (
    DataProviderPlugin,
    DataProviderRegistry,
    ExecutionVenueRegistry,
    VenueBundle,
    VenuePlugin,
)


class _FakeVenuePlugin:
    """Structural ``VenuePlugin`` — exposes the full Protocol surface (bodies irrelevant).

    11-04 widened ``VenuePlugin`` with ``credential_model`` (D-03) and
    ``fetch_venue_uid`` (D-04). ``isinstance`` against a ``runtime_checkable``
    Protocol is a hasattr check over EVERY member, so a fake that only implements
    ``build_bundle`` stops conforming the moment the Protocol grows — which is why
    both members are declared here in the same commit as the Protocol change.
    """

    credential_model = None

    def build_bundle(self, ctx, spec, connectors):  # noqa: ANN001, ANN201
        return None

    def fetch_venue_uid(self, connector):  # noqa: ANN001, ANN201
        return None


class _FakeDataProviderPlugin:
    """Structural ``DataProviderPlugin`` — exposes ``build_provider``."""

    def build_provider(self, ctx, spec, connectors):  # noqa: ANN001, ANN201
        return None


# --------------------------------------------------------------------------- #
# ExecutionVenueRegistry (D-01)
# --------------------------------------------------------------------------- #
def test_execution_registry_register_then_get_returns_same_plugin_identity() -> None:
    reg = ExecutionVenueRegistry()
    plugin = _FakeVenuePlugin()
    reg.register("okx", plugin)
    assert reg.get("okx") is plugin


def test_execution_registry_get_unknown_fails_loud() -> None:
    reg = ExecutionVenueRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_execution_registry_contains_and_names() -> None:
    reg = ExecutionVenueRegistry()
    reg.register("okx", _FakeVenuePlugin())
    assert "okx" in reg
    assert "nope" not in reg
    assert "okx" in reg.names()


# --------------------------------------------------------------------------- #
# DataProviderRegistry — independent instance (D-01 / VENUE-01)
# --------------------------------------------------------------------------- #
def test_data_registry_is_independent_from_execution_registry() -> None:
    exec_reg = ExecutionVenueRegistry()
    data_reg = DataProviderRegistry()
    okx_exec = _FakeVenuePlugin()
    replay_data = _FakeDataProviderPlugin()
    exec_reg.register("okx", okx_exec)
    data_reg.register("replay", replay_data)

    # Selecting exec "okx" + data "replay" resolves two different plugins independently.
    assert exec_reg.get("okx") is okx_exec
    assert data_reg.get("replay") is replay_data
    # The data registry never learned about the exec venue and vice-versa.
    assert "okx" not in data_reg
    assert "replay" not in exec_reg


def test_data_registry_get_unknown_fails_loud() -> None:
    reg = DataProviderRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


# --------------------------------------------------------------------------- #
# VenueBundle — execution-only shape, frozen (D-02)
# --------------------------------------------------------------------------- #
def test_venue_bundle_optional_arm_defaults_to_none() -> None:
    exchange = object()
    account_factory = lambda: None  # noqa: E731
    bundle = VenueBundle(exchange=exchange, account_factory=account_factory)
    assert bundle.exchange is exchange
    assert bundle.account_factory is account_factory
    # D-02: the optional live arm defaults to None (paper carries neither).
    assert bundle.connector is None
    assert bundle.lifecycle is None


def test_venue_bundle_is_frozen() -> None:
    bundle = VenueBundle(exchange=object(), account_factory=lambda: None)
    with pytest.raises(FrozenInstanceError):
        bundle.exchange = object()  # type: ignore[misc]


def test_venue_bundle_has_no_data_provider_field() -> None:
    # D-02: the data provider is built by DataProviderRegistry, NOT carried here.
    bundle = VenueBundle(exchange=object(), account_factory=lambda: None)
    assert not hasattr(bundle, "data_provider")
    assert not hasattr(bundle, "provider")


# --------------------------------------------------------------------------- #
# Plugin Protocols are runtime_checkable structural seams (VENUE-02 shape)
# --------------------------------------------------------------------------- #
def test_venue_plugin_is_runtime_checkable_structural() -> None:
    assert isinstance(_FakeVenuePlugin(), VenuePlugin)
    # An object without build_bundle is NOT a VenuePlugin.
    assert not isinstance(object(), VenuePlugin)


def test_data_provider_plugin_is_runtime_checkable_structural() -> None:
    assert isinstance(_FakeDataProviderPlugin(), DataProviderPlugin)
    assert not isinstance(object(), DataProviderPlugin)
