"""Restart-layering integration test (RTCFG-03 / D-10 / D-21 / D-25).

Proves the boot ``defaults <- YAML <- env <- persisted`` layering re-applies each scope's
persisted override on restart FROM ITS OWN MODULE STORE — never centralized into
``SystemStore`` for the order/portfolio scopes:

* ``system``    persisted -> ``SystemStore`` -> re-applied into ``config.system`` / ``config.universe``;
* ``order``     persisted -> the ORDER store's ``save_config`` -> re-applied into ``config.order`` + push;
* ``venue``     persisted -> ``VenueStore`` -> fee/slippage pushed to the execution handler;
* ``portfolio`` persisted -> the Portfolio's OWN bound ``state_storage`` -> re-applied via
  ``portfolio.update_config`` (the fourth D-21 scope, NOT ``SystemStore``);

plus the frozen-base guard (``rng_seed`` is NEVER persisted-overridden — RTCFG-04) and the
D-25 storage mechanics: the zero-sentinel INSERT-if-absent arm (config saved before any
account-state row) and the delete-then-insert CARRY-FORWARD clobber-safety (a subsequent
``save_account_state`` never drops the persisted ``config_json``).

Fully offline: the durable schema is provisioned via ``provision_schema`` on an in-memory
SQLite ``SqlEngine`` (never ``create_all`` on the run path — WR-03/D-14). Package-less dir.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from itrader.config.itrader_config import ITraderConfig
from itrader.config.sql import SqlSettings
from itrader.core.enums import MarketExecution
from itrader.order_handler.storage.sql_storage import SqlOrderStorage
from itrader.portfolio_handler.storage.cached_sql_storage import (
    CachedSqlPortfolioStateStorage,
)
from itrader.portfolio_handler.storage.sql_storage import SqlPortfolioStateStorage
from itrader.storage import SqlEngine
from itrader.storage.system_store import SystemStore
from itrader.storage.venue_store import VenueStore
from itrader.trading_system.live_trading_system import _layer_persisted_overrides
from tests.support.schema import provision_schema

_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


class _OrderHandlerDouble:
    """Order-handler stand-in: real ORDER store + a recording ``update_config`` push."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.pushed: Optional[Dict[str, Any]] = None

    def update_config(self, updates: Dict[str, Any]) -> None:
        self.pushed = updates


class _ExecHandlerDouble:
    """Execution-handler stand-in: records the venue fee/slippage push."""

    def __init__(self) -> None:
        self.pushed: Optional[Dict[str, Any]] = None

    def update_config(self, updates: Dict[str, Any]) -> None:
        self.pushed = updates


class _PortfolioDouble:
    """Portfolio stand-in: a real bound ``state_storage`` + a recording ``update_config``."""

    def __init__(self, portfolio_id: Any, state_storage: Any) -> None:
        self.portfolio_id = portfolio_id
        self.state_storage = state_storage
        self.applied_config: Optional[Dict[str, Any]] = None

    def update_config(self, updates: Dict[str, Any]) -> None:
        self.applied_config = updates


class _PortfolioHandlerDouble:
    """Portfolio-handler stand-in: the ``_portfolios`` map the restart helper iterates."""

    def __init__(self, portfolios: Dict[Any, Any]) -> None:
        self._portfolios = portfolios

    def get_portfolio(self, portfolio_id: Any) -> Any:
        return self._portfolios[portfolio_id]


@pytest.fixture()
def wiring():
    """A shared in-memory SqlEngine with all four owning stores provisioned."""
    engine = SqlEngine(SqlSettings.default())
    order_store = SqlOrderStorage(engine)
    system_store = SystemStore(engine)
    venue_store = VenueStore(engine)
    portfolio_id = uuid.uuid4()
    base_portfolio_store = SqlPortfolioStateStorage(engine, portfolio_id)
    portfolio_store = CachedSqlPortfolioStateStorage(base_portfolio_store)
    provision_schema(engine)
    return SimpleNamespace(
        engine=engine,
        order_store=order_store,
        system_store=system_store,
        venue_store=venue_store,
        portfolio_id=portfolio_id,
        portfolio_store=portfolio_store,
    )


def test_restart_layering_reapplies_every_scope_from_its_own_store(wiring):
    """Each scope's persisted override re-applies on boot from its OWN store; base untouched."""
    # (system) persist an override for a mutable SystemSettings + a UniverseConfig field.
    wiring.system_store.upsert(
        "config.system.auto_restart_delay_seconds", {"value": 99}, _NOW
    )
    wiring.system_store.upsert("config.universe.poll_cadence_s", {"value": 30.0}, _NOW)
    # (venue) persist a simulated-venue fee override into VenueStore.
    wiring.venue_store.upsert("simulated", {"fee_model": "zero"}, True, _NOW)
    # (order) persist an override via the ORDER store's OWN save_config (NOT SystemStore).
    wiring.order_store.save_config({"market_execution": "next_bar"}, _NOW)
    # (portfolio) persist an override via the Portfolio's OWN bound state_storage — BEFORE any
    # account-state row exists (exercises the zero-sentinel INSERT-if-absent arm, D-25).
    portfolio_override = {"limits": {"max_positions": 7}}
    wiring.portfolio_store.save_config(portfolio_override, _NOW)

    order_handler = _OrderHandlerDouble(wiring.order_store)
    exec_handler = _ExecHandlerDouble()
    portfolio = _PortfolioDouble(wiring.portfolio_id, wiring.portfolio_store)
    portfolio_handler = _PortfolioHandlerDouble({wiring.portfolio_id: portfolio})

    # A FRESH config — the restart boot instance (empty overrides, defaults resolved).
    config = ITraderConfig()
    assert config.system.auto_restart_delay_seconds == 10
    assert config.universe.poll_cadence_s == 60.0
    assert config.order.market_execution is MarketExecution.IMMEDIATE
    assert config.rng_seed == 42

    _layer_persisted_overrides(
        config,
        system_store=wiring.system_store,
        venue_store=wiring.venue_store,
        order_handler=order_handler,
        portfolio_handler=portfolio_handler,
        execution_handler=exec_handler,
    )

    # (system) mutable sub-model fields reflect the persisted values.
    assert config.system.auto_restart_delay_seconds == 99
    assert config.universe.poll_cadence_s == 30.0
    # (order) re-applied into config.order + pushed through the handler (from the ORDER store).
    assert config.order.market_execution is MarketExecution.NEXT_BAR
    assert order_handler.pushed == {"market_execution": "next_bar"}
    # (venue) fee pushed to the execution handler.
    assert exec_handler.pushed == {"fee_model": "zero"}
    # (portfolio) re-applied via portfolio.update_config from the Portfolio's OWN store.
    assert portfolio.applied_config == portfolio_override
    # (frozen base) rng_seed is NEVER persisted-overridden (RTCFG-04 / D-10).
    assert config.rng_seed == 42


def test_portfolio_config_survives_a_subsequent_fill_carry_forward(wiring):
    """save_config (no account row) -> save_account_state -> load_config STILL returns config.

    Proves the D-25 delete-then-insert carry-forward clobber-safety: a fill's
    ``save_account_state`` rewrites the whole ``portfolio_account_state`` row but carries the
    persisted ``config_json`` forward, so the portfolio config is not dropped before restart.
    Also proves the zero-sentinel INSERT-if-absent arm (config saved before any fill).
    """
    store = wiring.portfolio_store
    # No account-state row yet — the zero-sentinel INSERT-if-absent arm.
    assert store.load_config() is None
    override = {"risk_management": {"max_concentration_pct": 25.0}}
    store.save_config(override, _NOW)
    assert store.load_config() == override
    # A later fill supplies the real accumulators — config must survive (carry-forward).
    store.save_account_state(
        cash_balance=Decimal("1000"),
        realized_pnl=Decimal("50"),
        total_equity=Decimal("1050"),
        peak_equity=Decimal("1050"),
        open_positions_count=3,
        updated_time=_NOW,
    )
    assert store.load_config() == override, "save_account_state dropped the persisted config"
    state = store.load_account_state()
    assert state is not None
    assert state["cash_balance"] == Decimal("1000")
    assert state["open_positions_count"] == 3


def test_layering_is_a_noop_with_no_persisted_overrides(wiring):
    """An empty store set leaves the fresh config's defaults untouched (clean boot)."""
    order_handler = _OrderHandlerDouble(wiring.order_store)
    exec_handler = _ExecHandlerDouble()
    portfolio = _PortfolioDouble(wiring.portfolio_id, wiring.portfolio_store)
    portfolio_handler = _PortfolioHandlerDouble({wiring.portfolio_id: portfolio})

    config = ITraderConfig()
    _layer_persisted_overrides(
        config,
        system_store=wiring.system_store,
        venue_store=wiring.venue_store,
        order_handler=order_handler,
        portfolio_handler=portfolio_handler,
        execution_handler=exec_handler,
    )

    assert config.system.auto_restart_delay_seconds == 10
    assert config.universe.poll_cadence_s == 60.0
    assert config.order.market_execution is MarketExecution.IMMEDIATE
    assert order_handler.pushed is None
    assert exec_handler.pushed is None
    assert portfolio.applied_config is None
