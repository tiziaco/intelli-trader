"""Unit contract for the paper EXECUTION venue plugin (05-05, VENUE-02, D-05).

Proves:
  - ``PaperVenuePlugin(simulated_exchange).build_bundle`` returns a ``VenueBundle``
    whose ``exchange`` IS the injected simulated exchange (identity — D-05
    satisfied-by-reuse, NO new exchange/adapter), ``connector`` is ``None``,
    ``lifecycle`` is ``None``, and ``account_factory`` mints a compute account;
  - the paper bundle NEVER touches the ``ConnectorProvider`` (the ``connectors``
    arg is unused — paper has no connector, D-05);
  - ``itrader.venues.paper_plugin`` no longer holds the replay DATA side (D-18):
    the module imports nothing heavy at module scope and defines only
    ``PaperVenuePlugin`` (the replay plugin/provider/parity window left for
    ``tests/support/replay_harness.py``; production paper re-points to OKX, D-21).

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _ExplodingConnectorProvider:
    """A ConnectorProvider whose ``get`` MUST NOT be called on the paper path (D-05)."""

    def get(self, venue: str, account_id: str, spec: Any) -> Any:
        raise AssertionError(
            "the paper venue must not touch the ConnectorProvider (D-05, connector=None)"
        )

    def close_all(self) -> None:  # pragma: no cover - defensive
        raise AssertionError("paper path must not touch the ConnectorProvider")


class _FakeSimulatedExchange:
    """A stand-in for the compose-built paper SimulatedExchange (reused AS-IS)."""


def _fake_ctx() -> SimpleNamespace:
    return SimpleNamespace(bus=object())


def _fake_spec(account_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(account_id=account_id)


def _fake_portfolio() -> SimpleNamespace:
    """A minimal portfolio the compute-account factory needs (cash leaf, no margin)."""
    return SimpleNamespace(
        config=SimpleNamespace(trading_rules=SimpleNamespace(enable_margin=False)),
    )


def test_paper_plugin_module_holds_no_replay_symbol() -> None:
    """The production module carries NO replay DATA side at all (D-18/D-21).

    The replay plugin/provider left ``itrader`` for the test harness. The module must
    define ONLY ``PaperVenuePlugin`` (no ``ReplayDataPlugin``) and import no
    ``replay_provider`` / ``csv_store`` at module scope.
    """
    import ast
    import pathlib

    import itrader.venues.paper_plugin as mod

    source = pathlib.Path(mod.__file__).read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    class_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module):
            for child in node.body:
                if isinstance(child, ast.Import):
                    imported += [alias.name for alias in child.names]
                elif isinstance(child, ast.ImportFrom) and child.module:
                    imported.append(child.module)
                elif isinstance(child, ast.ClassDef):
                    class_names.append(child.name)
    forbidden = [
        name
        for name in imported
        if any(tok in name for tok in ("replay_provider", "csv_store"))
    ]
    assert not forbidden, (
        "D-04 violation: itrader.venues.paper_plugin imports the replay provider / "
        f"CSV store at module scope: {forbidden!r}"
    )
    # D-18: the replay data plugin left production — only the execution plugin remains.
    assert class_names == ["PaperVenuePlugin"], (
        "itrader.venues.paper_plugin must define ONLY PaperVenuePlugin (the replay data "
        f"plugin left for tests/support/replay_harness) — found {class_names!r}"
    )


def test_paper_venue_plugin_reuses_the_injected_simulated_exchange() -> None:
    """The paper bundle wraps the injected simulated exchange by IDENTITY (D-05)."""
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.paper_plugin import PaperVenuePlugin

    simulated = _FakeSimulatedExchange()
    plugin = PaperVenuePlugin(simulated)

    bundle = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())

    assert isinstance(bundle, VenueBundle)
    # D-05: reuse AS-IS — the bundle's exchange IS the injected instance (identity),
    # not a new exchange/adapter.
    assert bundle.exchange is simulated
    # Paper has no live connector (D-05).
    assert bundle.connector is None
    # 11-09: the dead ``VenueBundle.lifecycle`` field is gone — the lifecycle is returned
    # beside the bundle by assemble_venue, never stored inside it.
    assert not hasattr(bundle, "lifecycle")
    # The connectors arg is untouched (the exploding provider was never called).
    assert callable(bundle.account_factory)


def test_paper_account_factory_mints_a_compute_account() -> None:
    """account_factory mints a SimulatedCashAccount for a non-margin portfolio."""
    from itrader.portfolio_handler.account import SimulatedCashAccount
    from itrader.portfolio_handler.account.base import Account
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_FakeSimulatedExchange())
    bundle = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())

    account = bundle.account_factory(_fake_portfolio(), initial_cash=1000.0)
    assert isinstance(account, Account)
    assert isinstance(account, SimulatedCashAccount)


def test_relocated_test_data_plugin_builds_a_test_provider() -> None:
    """The RELOCATED TestDataPlugin (tests/support) builds a TestLiveDataProvider (D-18).

    The replay DATA plugin left ``itrader.venues.paper_plugin`` for the test harness;
    this proves the moved plugin still builds the offline replay provider.
    """
    from tests.support.replay_harness import TestDataPlugin, TestLiveDataProvider

    provider = TestDataPlugin().build_provider(
        _fake_ctx(), _fake_spec(), _ExplodingConnectorProvider()
    )
    assert isinstance(provider, TestLiveDataProvider)


def test_paper_venue_plugin_has_no_credential_model_and_no_venue_uid() -> None:
    """Paper exposes ``credential_model = None`` and ``fetch_venue_uid -> None`` (D-03/D-04).

    A paper account has no secret to point at and no venue-side account to assert
    against, so it is the clean no-op case for BOTH new Protocol members. The UID
    guard must therefore skip paper entirely rather than record a placeholder.
    """
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_FakeSimulatedExchange())

    assert plugin.credential_model is None
    assert plugin.fetch_venue_uid(object()) is None


def test_paper_plugins_satisfy_venue_and_data_protocols() -> None:
    """The paper execution plugin + the relocated data plugin satisfy their Protocols."""
    from itrader.venues.bundle import DataProviderPlugin, VenuePlugin
    from itrader.venues.paper_plugin import PaperVenuePlugin

    from tests.support.replay_harness import TestDataPlugin

    assert isinstance(PaperVenuePlugin(_FakeSimulatedExchange()), VenuePlugin)
    assert isinstance(TestDataPlugin(), DataProviderPlugin)


# --------------------------------------------------------------------------- #
# new_account — per-portfolio compute minting (11-07, D-10)
# --------------------------------------------------------------------------- #
def test_paper_new_account_mints_a_fresh_leaf_per_portfolio() -> None:
    """Two portfolios get two DISTINCT compute accounts (no shared leaf)."""
    from itrader.portfolio_handler.account import SimulatedCashAccount
    from itrader.venues.bundle import VenueAccountConfig
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_FakeSimulatedExchange())
    config = VenueAccountConfig(initial_cash=1000.0)

    account_a = plugin.new_account(_fake_portfolio(), config)
    account_b = plugin.new_account(_fake_portfolio(), config)

    assert isinstance(account_a, SimulatedCashAccount)
    assert isinstance(account_b, SimulatedCashAccount)
    assert account_a is not account_b


def test_paper_new_account_selects_the_margin_leaf_when_enabled() -> None:
    """The leaf selection is the pre-11-07 factory body VERBATIM (D-04).

    The non-margin branch is the SMA_MACD byte-exact oracle path, so this asserts
    the selection was copied rather than restructured — a reordered or
    'simplified' branch here is a silent oracle risk.
    """
    from itrader.portfolio_handler.account import (
        SimulatedCashAccount,
        SimulatedMarginAccount,
    )
    from itrader.venues.bundle import VenueAccountConfig
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_FakeSimulatedExchange())
    config = VenueAccountConfig(initial_cash=1000.0)

    margin_portfolio = _fake_portfolio()
    margin_portfolio.config.trading_rules.enable_margin = True
    cash_portfolio = _fake_portfolio()

    assert isinstance(plugin.new_account(margin_portfolio, config),
                      SimulatedMarginAccount)
    assert isinstance(plugin.new_account(cash_portfolio, config),
                      SimulatedCashAccount)


def test_paper_account_factory_delegates_to_new_account() -> None:
    """The retained bundle field is a thin adapter over the Protocol method."""
    from itrader.portfolio_handler.account import SimulatedCashAccount
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_FakeSimulatedExchange())
    bundle = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())

    account = bundle.account_factory(_fake_portfolio(), initial_cash=2500.0)

    assert isinstance(account, SimulatedCashAccount)
