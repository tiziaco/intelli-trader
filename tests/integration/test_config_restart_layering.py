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
D-25 storage mechanics: config persists to the portfolio's ``portfolios`` DEFINITION row
(D-09) and a subsequent ``save_account_state`` — which rewrites the whole
``portfolio_account_state`` row — cannot touch it, because the two blobs now live in
different tables.

**11-08 removed the legacy zero-sentinel arm.** ``save_config`` used to fall back to
INSERT-ing a ``portfolio_account_state`` row with zero-sentinel accumulators when the
portfolio had no definition row. That arm existed ONLY because nothing wrote the
``portfolios`` table yet; 11-08's writer
(``PortfolioHandler._persist_definition``) created that guarantee, so a missing
definition row is now a wiring bug and ``save_config`` raises. These tests therefore
provision a real definition row via ``seed_portfolio_definitions`` — the same test-side
seam the strategy-subscription tests use — instead of exercising the deleted arm.

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
from tests.support.schema import provision_schema, seed_portfolio_definitions

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
    # 11-08: the D-09 config blob lives on the ``portfolios`` DEFINITION row, and the
    # legacy zero-sentinel account-state arm that used to cover a missing one is gone.
    # A portfolio with no definition row is now a wiring bug, so seed the row (with its
    # ``venue_accounts`` FK parent) exactly as production's writer would have.
    seed_portfolio_definitions(engine, [portfolio_id])
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
    wiring.venue_store.upsert("paper", {"fee_model": "zero"}, True, _NOW)
    # (order) persist an override via the ORDER store's OWN save_config (NOT SystemStore).
    wiring.order_store.save_config({"market_execution": "next_bar"}, _NOW)
    # (portfolio) persist an override via the Portfolio's OWN bound state_storage — BEFORE any
    # account-state row exists. Post-11-08 this writes the ``portfolios`` DEFINITION row
    # (D-09), which the fixture seeded; the account-state table is untouched.
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

    The D-09 separation is what makes this hold post-11-08: the config blob lives on the
    ``portfolios`` DEFINITION row while ``save_account_state`` rewrites the
    ``portfolio_account_state`` STATE row, so a fill structurally cannot clobber the
    persisted config. (Before the rehome both shared one row and the property depended on
    an explicit carry-forward in the delete-then-insert.)

    Also pins that config can be written BEFORE any account-state row exists — the
    restart-layering path only READS ``load_config``, so a portfolio's first config write
    is construction-time or a runtime ``portfolio:{id}`` ConfigUpdateEvent, and both can
    precede its first fill.
    """
    store = wiring.portfolio_store
    # A seeded definition row with a NULL config_json reads back as "no override".
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


def test_boot_degrades_clean_on_invalid_persisted_override(wiring):
    """WR-03: a present-but-INVALID persisted override is skipped, boot does NOT crash.

    A stored value that no longer validates (schema evolution / model-field tightening / a
    poisoned row) raises ``pydantic.ValidationError`` (a ValueError subclass) when the layering
    ``setattr`` re-coerces it under ``validate_assignment`` — NOT a ``SQLAlchemyError``. The
    per-scope degrade-clean guard must swallow it (log + skip) so build_live_system does not
    hard-fail, and per-scope isolation means a good scope still applies.
    """
    # (system) persist a NOW-INVALID value — auto_restart_delay_seconds is an int; a
    # non-coercible string fails validate_assignment on re-apply (poisoned-row analogue).
    wiring.system_store.upsert(
        "config.system.auto_restart_delay_seconds", {"value": "not-an-int"}, _NOW
    )
    # (order) a perfectly VALID override on a DIFFERENT scope — must still apply (isolation).
    wiring.order_store.save_config({"market_execution": "next_bar"}, _NOW)

    order_handler = _OrderHandlerDouble(wiring.order_store)
    exec_handler = _ExecHandlerDouble()
    portfolio = _PortfolioDouble(wiring.portfolio_id, wiring.portfolio_store)
    portfolio_handler = _PortfolioHandlerDouble({wiring.portfolio_id: portfolio})

    config = ITraderConfig()

    # MUST NOT raise — the invalid system override degrades clean.
    _layer_persisted_overrides(
        config,
        system_store=wiring.system_store,
        venue_store=wiring.venue_store,
        order_handler=order_handler,
        portfolio_handler=portfolio_handler,
        execution_handler=exec_handler,
    )

    # (system) the bad override was SKIPPED — the field kept its fresh default.
    assert config.system.auto_restart_delay_seconds == 10
    # (order) the good, isolated scope STILL applied despite the system scope failing.
    assert config.order.market_execution is MarketExecution.NEXT_BAR
    assert order_handler.pushed == {"market_execution": "next_bar"}
