"""Unit contract for the ConnectorProvider memo + ConnectorPlugin Protocol (05-04, VENUE-03, D-03/D-04).

Proves the one-connector-per-``(venue, account_id)`` invariant that keeps two
independent builders (the execution ``build_bundle`` and the data
``build_provider``) from each opening their own ``ccxt.pro`` client for the same
venue+account:

- ``get(venue, account_id, spec)`` twice for the SAME key returns the SAME object
  (``is``); the underlying ``ConnectorPlugin.build`` is called exactly ONCE.
- A different ``account_id`` builds a NEW connector (distinct memo key).
- ``close_all()`` calls ``disconnect()`` on every memoized connector exactly once.
- ``get`` for an unregistered venue fails loud (``KeyError``).

This directory is package-less (NO ``__init__.py``, per the connectors conftest).
"""

import pytest

from itrader.connectors.provider import ConnectorPlugin, ConnectorProvider


class _FakeConnector:
    """Minimal ``LiveConnector``-shaped double: counts ``disconnect`` calls."""

    def __init__(self) -> None:
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1


class _FakeConnectorPlugin:
    """Structural ``ConnectorPlugin``: ``build`` returns a fresh connector, counts calls."""

    def __init__(self) -> None:
        self.build_calls = 0

    def build(self, spec):  # noqa: ANN001, ANN201
        self.build_calls += 1
        return _FakeConnector()


class _RaisingConnector:
    """``LiveConnector``-shaped double whose ``disconnect`` raises after counting."""

    def __init__(self) -> None:
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        raise RuntimeError("boom during disconnect")


class _RaisingConnectorPlugin:
    """Structural ``ConnectorPlugin``: ``build`` returns a fresh raising connector."""

    def build(self, spec):  # noqa: ANN001, ANN201
        return _RaisingConnector()


def _make_provider() -> tuple[ConnectorProvider, _FakeConnectorPlugin]:
    plugin = _FakeConnectorPlugin()
    provider = ConnectorProvider({"okx": plugin})
    return provider, plugin


def test_connector_plugin_is_runtime_checkable_structural() -> None:
    assert isinstance(_FakeConnectorPlugin(), ConnectorPlugin)
    assert not isinstance(object(), ConnectorPlugin)


def test_same_venue_account_id_returns_same_instance_and_builds_once() -> None:
    provider, plugin = _make_provider()
    first = provider.get("okx", "default", spec=object())
    second = provider.get("okx", "default", spec=object())
    assert first is second
    assert plugin.build_calls == 1


def test_different_account_id_builds_a_new_connector() -> None:
    provider, plugin = _make_provider()
    default_conn = provider.get("okx", "default", spec=object())
    other_conn = provider.get("okx", "other", spec=object())
    assert default_conn is not other_conn
    assert plugin.build_calls == 2


def test_close_all_disconnects_each_memoized_connector_once() -> None:
    provider, _ = _make_provider()
    conn_a = provider.get("okx", "default", spec=object())
    conn_b = provider.get("okx", "other", spec=object())
    provider.close_all()
    assert conn_a.disconnect_calls == 1
    assert conn_b.disconnect_calls == 1


def test_get_unregistered_venue_fails_loud() -> None:
    provider, _ = _make_provider()
    with pytest.raises(KeyError):
        provider.get("nope", "default", spec=object())


def test_close_all_isolates_a_raising_disconnect_and_clears_the_memo() -> None:
    provider = ConnectorProvider(
        {"boom": _RaisingConnectorPlugin(), "okx": _FakeConnectorPlugin()}
    )
    # Memoize the raising connector FIRST so a naive loop would abort before the survivor.
    raising = provider.get("boom", "default", spec=object())
    survivor = provider.get("okx", "default", spec=object())

    provider.close_all()  # must NOT propagate the RuntimeError

    assert raising.disconnect_calls == 1  # the raise WAS attempted
    assert survivor.disconnect_calls == 1  # the loop CONTINUED past the raise
    assert provider._memo == {}  # the memo was cleared in the finally
