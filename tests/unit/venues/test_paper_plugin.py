"""Unit contract for the paper EXECUTION venue plugin (05-05, VENUE-02, D-05/D-06/D-17).

Proves:
  - ``PaperVenuePlugin(exchange_config).build_bundle`` returns a ``VenueBundle``
    whose ``exchange`` is a ``SimulatedExchange`` the plugin BUILT ITSELF from the
    injected config (D-06 — symmetric with ``OkxVenuePlugin`` building its own
    ``OkxExchange``), sharing ``ctx.rng`` (D-07); ``connector`` is ``None``, there
    is no ``lifecycle`` field, and ``account_factory`` mints a compute account;
  - the config must be PASSED, not defaulted (D-17): a plugin holding
    ``ExchangeConfig.default()`` produces an exchange that REFUSES the golden
    ``BTCUSD`` ticker, which is why the run-derived config rides in from the factory;
  - the plugin is STATELESS — two ``build_bundle`` calls build two exchanges;
    single-instance-ness is ``VenueBundles``' memo's job (D-08);
  - the paper bundle NEVER touches the ``ConnectorProvider`` (the ``connectors``
    arg is unread — paper has no connector, D-05);
  - ``itrader.venues.paper_plugin`` no longer holds the replay DATA side (D-18):
    the module imports nothing heavy at module scope and defines only
    ``PaperVenuePlugin`` (the replay plugin/provider/parity window left for
    ``tests/support/replay_harness.py``; production paper re-points to OKX, D-21).

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

import random
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from tests.support.venue_wiring import compute_account


class _ExplodingConnectorProvider:
    """A ConnectorProvider whose ``get`` MUST NOT be called on the paper path (D-05)."""

    def get(self, venue: str, account_id: str, spec: Any) -> Any:
        raise AssertionError(
            "the paper venue must not touch the ConnectorProvider (D-05, connector=None)"
        )

    def close_all(self) -> None:  # pragma: no cover - defensive
        raise AssertionError("paper path must not touch the ConnectorProvider")


def _seeded_config(ticker: str = "BTCUSD") -> Any:
    """A RUN-DERIVED ExchangeConfig: the default preset UNION a distinctive ticker.

    This is the shape the backtest factory builds (``_seed_supported_symbols``) and
    the shape D-17 requires be passed to the plugin.
    """
    from itrader.config import ExchangeConfig

    config = ExchangeConfig.default()
    config.limits.supported_symbols = set(config.limits.supported_symbols) | {ticker}
    return config


def _fake_ctx(rng: random.Random | None = None) -> SimpleNamespace:
    """The two ctx fields ``build_bundle`` reads: the bus and the ONE seeded RNG (D-07)."""
    return SimpleNamespace(bus=object(), rng=rng if rng is not None else random.Random(42))


def _fake_spec(account_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(account_id=account_id)


def _fake_storage() -> SimpleNamespace:
    """A stand-in ``PortfolioStateStorage`` used only to prove the seam is forwarded.

    11.1-09 (D-03): the compute leaf routes reserved cash / locked margin / the
    cash-operation audit trail through this seam, and the live restart path
    repopulates the caches on the PORTFOLIO's instance — so a leaf that quietly
    builds its own backend loses every reservation across a restart while the
    backtest (which reads none of those containers elsewhere) stays byte-exact. The
    object is opaque on purpose: the assertion is IDENTITY, not behaviour.
    """
    return SimpleNamespace()


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


def test_paper_venue_plugin_builds_its_own_exchange_from_the_injected_config() -> None:
    """The plugin BUILDS a SimulatedExchange from its injected config (D-06/D-17/D-07).

    The inverse of the pre-11.1-07 contract: nothing is handed in pre-built. The
    plugin mints the exchange exactly as ``OkxVenuePlugin`` mints its ``OkxExchange``,
    from the RUN-DERIVED config it received at construction, sharing the ctx's ONE
    seeded RNG.
    """
    from itrader.execution_handler.exchanges.simulated import SimulatedExchange
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.paper_plugin import PaperVenuePlugin

    exchange_config = _seeded_config("BTCUSD")
    plugin = PaperVenuePlugin(exchange_config)
    rng = random.Random(7)
    ctx = _fake_ctx(rng)

    bundle = plugin.build_bundle(ctx, _fake_spec(), _ExplodingConnectorProvider())

    assert isinstance(bundle, VenueBundle)
    # D-06: a REAL SimulatedExchange the plugin built — not an injected stand-in.
    assert isinstance(bundle.exchange, SimulatedExchange)
    # D-17: built from THE injected config object (identity, not an equal copy) — so a
    # run-derived symbol set provably reaches the exchange.
    assert bundle.exchange.config is exchange_config
    assert "BTCUSD" in bundle.exchange._supported_symbols
    # D-07: the ONE seeded RNG, by IDENTITY. Equality of seed proves nothing — two
    # random.Random(42) instances look identical until the call ORDER diverges.
    assert bundle.exchange._rng is rng
    assert bundle.exchange.global_queue is ctx.bus
    # Paper has no live connector (D-05).
    assert bundle.connector is None
    # 11-09: the dead ``VenueBundle.lifecycle`` field is gone — the lifecycle is returned
    # beside the bundle by assemble_venue, never stored inside it.
    assert not hasattr(bundle, "lifecycle")
    # The connectors arg is untouched (the exploding provider was never called).
    assert callable(bundle.account_factory)


def test_two_build_bundle_calls_build_two_exchanges() -> None:
    """The PLUGIN is stateless — two calls build two exchanges (D-08 boundary).

    Single-instance-ness per ``(venue, account_id)`` is ``VenueBundles``' memo's job,
    NOT the plugin's. Conflating the two is exactly how a second, divergent memo gets
    hand-rolled inside a plugin — and a bundle memo that disagrees with the connector
    memo re-opens the duplicate-session defect D-08 exists to close.
    """
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_seeded_config())

    first = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())
    second = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())

    assert first.exchange is not second.exchange


def test_default_preset_config_refuses_the_golden_ticker() -> None:
    """VENUE-05 empty edge / D-17's decisive evidence, as a guard.

    ``ExchangeConfig.default()`` does NOT contain ``BTCUSD``. A plugin constructed
    with the preset therefore builds an exchange that REFUSES the golden ticker,
    while the run-derived (seeded) config admits it. This is why the config must be
    PASSED from the factory and must never be defaulted or imported plugin-side —
    the failure otherwise surfaces as refused orders far from its cause.
    """
    from itrader.config import ExchangeConfig
    from itrader.venues.paper_plugin import PaperVenuePlugin

    preset_exchange = PaperVenuePlugin(ExchangeConfig.default()).build_bundle(
        _fake_ctx(), _fake_spec(), _ExplodingConnectorProvider()).exchange
    seeded_exchange = PaperVenuePlugin(_seeded_config("BTCUSD")).build_bundle(
        _fake_ctx(), _fake_spec(), _ExplodingConnectorProvider()).exchange

    assert not preset_exchange.validate_symbol("BTCUSD")
    assert seeded_exchange.validate_symbol("BTCUSD")


def test_paper_account_factory_mints_a_compute_account() -> None:
    """account_factory mints a SimulatedCashAccount for a non-margin portfolio."""
    from itrader.portfolio_handler.account import SimulatedCashAccount
    from itrader.portfolio_handler.account.base import Account
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_seeded_config())
    bundle = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())

    account = bundle.account_factory(initial_cash=1000.0)
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

    plugin = PaperVenuePlugin(_seeded_config())

    assert plugin.credential_model is None
    assert plugin.fetch_venue_uid(object()) is None


def test_paper_plugins_satisfy_venue_and_data_protocols() -> None:
    """The paper execution plugin + the relocated data plugin satisfy their Protocols."""
    from itrader.venues.bundle import DataProviderPlugin, VenuePlugin
    from itrader.venues.paper_plugin import PaperVenuePlugin

    from tests.support.replay_harness import TestDataPlugin

    assert isinstance(PaperVenuePlugin(_seeded_config()), VenuePlugin)
    assert isinstance(TestDataPlugin(), DataProviderPlugin)


# --------------------------------------------------------------------------- #
# new_account — per-portfolio compute minting (11-07, D-10)
# --------------------------------------------------------------------------- #
def test_paper_new_account_mints_a_fresh_leaf_per_portfolio() -> None:
    """Two portfolios get two DISTINCT compute accounts (no shared leaf)."""
    from itrader.portfolio_handler.account import SimulatedCashAccount
    from itrader.venues.bundle import VenueAccountConfig
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_seeded_config())
    config = VenueAccountConfig(initial_cash=1000.0)

    account_a = plugin.new_account(config)
    account_b = plugin.new_account(config)

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

    plugin = PaperVenuePlugin(_seeded_config())

    # D-03 (11.1-09): the flag rides on the CONFIG, sourced from the owning
    # PortfolioConfig.trading_rules by PortfolioHandler.add_portfolio — it is no
    # longer read off a portfolio the plugin was handed.
    margin_config = VenueAccountConfig(initial_cash=1000.0, enable_margin=True)
    cash_config = VenueAccountConfig(initial_cash=1000.0, enable_margin=False)

    assert isinstance(plugin.new_account(margin_config), SimulatedMarginAccount)
    assert isinstance(plugin.new_account(cash_config), SimulatedCashAccount)


def test_paper_new_account_forwards_the_shared_state_storage_seam() -> None:
    """The leaf lands on the config's seam, never on a private backend (D-01/D-03).

    The account and its three sibling managers MUST share ONE
    ``PortfolioStateStorage``: the live restart path calls
    ``state_storage.rehydrate(account)`` and repopulates the reservation /
    locked-margin caches on the PORTFOLIO's instance. A leaf on its own backend
    silently loses every reservation across a restart — and stays byte-exact in
    backtest, where nothing else reads those containers, so no other test goes red.
    Asserted on BOTH arms because the margin superset takes the same seam.
    """
    from itrader.venues.bundle import VenueAccountConfig
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_seeded_config())
    seam = _fake_storage()

    cash_leaf = plugin.new_account(
        VenueAccountConfig(initial_cash=10.0, state_storage=seam))
    margin_leaf = plugin.new_account(VenueAccountConfig(
        initial_cash=10.0, enable_margin=True, state_storage=seam))

    assert cash_leaf._storage is seam
    assert margin_leaf._storage is seam


def test_paper_account_factory_delegates_to_new_account() -> None:
    """The retained bundle field is a thin adapter over the Protocol method."""
    from itrader.portfolio_handler.account import SimulatedCashAccount
    from itrader.venues.paper_plugin import PaperVenuePlugin

    plugin = PaperVenuePlugin(_seeded_config())
    bundle = plugin.build_bundle(_fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())

    account = bundle.account_factory(initial_cash=2500.0)

    assert isinstance(account, SimulatedCashAccount)


def test_paper_account_factory_is_keyword_only_and_has_no_catch_all() -> None:
    """The 11-07 removal of the ``(*args, **kwargs)`` catch-all is NOT reverted.

    An arg-swallowing arm type-checks clean against a STRUCTURAL Protocol while
    silently returning one shared unscoped account — a defect the type system cannot
    see. Asserted on the SIGNATURE so a future "convenience" widening fails here
    rather than in production.
    """
    import inspect

    from itrader.venues.paper_plugin import PaperVenuePlugin

    bundle = PaperVenuePlugin(_seeded_config()).build_bundle(
        _fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())
    parameters = inspect.signature(bundle.account_factory).parameters

    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    ), f"account_factory must be keyword-only: {parameters!r}"
    assert set(parameters) == {
        "initial_cash", "enable_margin", "account_id", "state_storage"}


def test_paper_account_factory_carries_every_knob_through_to_the_leaf() -> None:
    """The closure forwards ALL of its arguments — a dropped one is silent (D-03).

    ``enable_margin`` selects the leaf KIND and ``state_storage`` selects the
    persistence backend; both default, so a closure that accepted them and forgot to
    pass them on would mint a plausible-looking wrong account with nothing red.
    """
    from itrader.portfolio_handler.account import SimulatedMarginAccount
    from itrader.venues.paper_plugin import PaperVenuePlugin

    bundle = PaperVenuePlugin(_seeded_config()).build_bundle(
        _fake_ctx(), _fake_spec(), _ExplodingConnectorProvider())
    seam = _fake_storage()

    account = bundle.account_factory(
        initial_cash=4200.0, enable_margin=True, state_storage=seam)

    assert isinstance(account, SimulatedMarginAccount)
    assert account._storage is seam
    assert account.balance == Decimal("4200.00")
