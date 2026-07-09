"""Clean-interpreter import-inertness gate for the OKX live stack (CONN-04 / GATE-01).

This is the recurring milestone-gate proof for Phase 2: the OKX order/data
machinery must be **inert on the backtest hot path**. Importing the backtest
composition root (``itrader.trading_system.backtest_trading_system``) must pull
**NO** OKX connector concretion and **NO** ``ccxt.pro`` — those are lazy-imported
inside ``LiveTradingSystem.__init__`` only (Plan 02-05), so they never touch the
backtest import graph.

Why this matters (Pitfall / hot-path inertness, carried from v1.6): the backtest
path imports no async/connector code — that is what keeps the W1/W2 perf gate green
and the SMA_MACD oracle byte-exact. If a future edit hoists an OKX/ccxt import to
module scope (or re-exports the concretion from an ``__init__`` on the backtest
path), the backtest import path would silently start pulling asyncio + ccxt.pro
machinery it never uses — this test fails loudly when that happens.

Why a subprocess (NOT an in-process ``sys.modules`` assertion): the running pytest
session has already imported the OKX stack via the ``tests/unit/connectors`` and
``tests/unit/execution`` suites, so an in-process ``'ccxt.pro' not in sys.modules``
check would observe another test's import. The probe therefore runs in a **fresh**
interpreter via ``subprocess.run([sys.executable, "-c", PROBE])`` and asserts on a
clean module table.
"""

import subprocess
import sys

# Probe executed in a clean interpreter: import ONLY the backtest composition root,
# then assert the OKX connector concretion and ccxt.pro were never pulled. Prints a
# sentinel on success so the parent can assert on stdout.
_PROBE = r"""
import sys

# The backtest composition root — the hot path. Importing it must NOT pull the OKX
# stack (lazy-imported inside LiveTradingSystem.__init__, never on this path).
import itrader.trading_system.backtest_trading_system  # noqa: F401

_FORBIDDEN = (
    "itrader.connectors.okx",
    "ccxt.pro",
    "ccxt",
    # Phase 3 (FEED-05 inertness gate): LiveBarFeed is LAZY-imported inside
    # LiveTradingSystem.__init__ only — it must NEVER be pulled onto the backtest
    # hot path. If a future edit hoists it to module scope this probe fails loudly,
    # protecting the oracle byte-exactness + the W1/W2 perf gate.
    "itrader.price_handler.feed.live_bar_feed",
    # Phase 4 (D-12): the paper replay provider is lazy-imported inside the
    # LiveTradingSystem(exchange='paper') arm only — it must NEVER be pulled onto
    # the backtest hot path (protects the oracle byte-exactness + the W1/W2 perf gate).
    "itrader.price_handler.providers.replay_provider",
    # Phase 5 (D-17/RECON-05, inertness gate): the two-sided restart reconciler is
    # lazy-imported inside LiveTradingSystem.start()'s OKX arm ONLY — its live-arm
    # deps (LiveConnector / VenueAccount / CachedSqlOrderStorage) are TYPE_CHECKING-
    # only, but the MODULE must still never be pulled onto the backtest hot path (it
    # is the live-drive reconcile surface). If a future edit hoists it to module
    # scope this probe fails loudly. NOTE: the pure VenueAccount body
    # (itrader.portfolio_handler.account.venue) and the AlertSink
    # (itrader.trading_system.alert_sink) are deliberately NOT forbidden — they pull
    # no async/connector/SQLAlchemy (LiveConnector stays TYPE_CHECKING-only), so they
    # are inert-by-construction even when transitively imported.
    "itrader.portfolio_handler.reconcile.venue_reconciler",
    # Phase 6 (Plan 06-05, inertness gate): the live-only UniverseHandler (poll host
    # + add/remove consumer) and its poll-timer daemon are constructed inside
    # LiveTradingSystem._initialize_live_session / start() ONLY (LAZY-imported there).
    # The backtest TradingSystem builds its OWN EventHandler with the untouched
    # _routes literal (empty UNIVERSE_UPDATE route) and never constructs the handler
    # or starts the timer — so universe_handler must NEVER be pulled onto the backtest
    # hot path. The universe barrel (itrader.universe.__init__) deliberately does NOT
    # import it (membership/selection-model are pure), so importing Universe on the
    # backtest path stays handler-free. If a future edit hoists it to the backtest
    # composition root (or re-exports it from the barrel) this probe fails loudly,
    # protecting the oracle byte-exactness + the W1/W2 perf gate.
    "itrader.universe.universe_handler",
    # Phase 4 (04-03, STORE-05 inertness gate): the three new durable-store modules compose
    # SQLAlchemy and are LIVE-ONLY (constructed in P6/P9/P10, never on the backtest path).
    # The backtest composition root must pull NONE of them. If a future edit imports one on
    # the hot path (or re-exports it from a backtest-path barrel) this probe fails loudly,
    # protecting the oracle byte-exactness + the W1/W2 perf gate.
    "itrader.storage.system_store",
    "itrader.storage.venue_store",
    "itrader.storage.strategy_registry_store",
)
leaked = [name for name in _FORBIDDEN if name in sys.modules]
assert not leaked, (
    "CONN-04 INERTNESS VIOLATION: the backtest import path pulled the OKX/async "
    "stack: " + repr(leaked) + " (must be lazy-imported inside the live path only)"
)

# Phase 1 (CFG-02, D-05/D-06 register-vs-build): importing itrader runs
# SystemConfig.default() (itrader/__init__.py). The lazy `sql` cached_property must
# stay UNRESOLVED at import — its absence from the singleton's __dict__ proves zero
# SqlSettings (and thus no Postgres URL/credential resolution) was constructed at
# import. cached_property provably populates __dict__ only on first access.
from itrader import config as _cfg
assert "sql" not in _cfg.__dict__, (
    "CFG-02 INERTNESS VIOLATION: SqlSettings was BUILT at import (the `sql` "
    "cached_property resolved) — it must be lazy-constructed on first access only"
)

# Phase 2 (02-03, register-vs-build inertness): constructing the backtest bus +
# EngineContext(sql_engine=None) must REGISTER without BUILDING a heavy backend.
# FifoEventBus wraps a stdlib queue; EngineContext is a frozen infra dataclass —
# neither may pull SQLAlchemy/ccxt, and building the ctx must NOT resolve the lazy
# `sql` cached_property on the config singleton (closes the recurring eager-SQL
# import failure mode, GATE-01 lineage).
from itrader.events_handler.bus import FifoEventBus
from itrader.trading_system.engine_context import EngineContext
_bus = FifoEventBus()
_ctx = EngineContext(bus=_bus, config=_cfg, environment="backtest", sql_engine=None)
_heavy = [name for name in ("sqlalchemy", "ccxt") if name in sys.modules]
assert not _heavy, (
    "P2 register-vs-build inertness violation: constructing FifoEventBus/"
    "EngineContext(sql_engine=None) pulled a heavy backend: " + repr(_heavy)
)
assert "sql" not in _cfg.__dict__, (
    "P2 register-vs-build inertness violation: building the EngineContext resolved "
    "the lazy `sql` cached_property on the config singleton (must stay unbuilt)"
)

print("INERTNESS_OK")
"""


def test_backtest_path_imports_no_okx_stack() -> None:
    """Importing the backtest root pulls no OKX connector / ccxt.pro (CONN-04).

    Runs the probe in a fresh interpreter (``sys.executable``) so the assertion is
    not contaminated by the OKX stack already imported by sibling connector/
    execution tests in the same session.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )

    # Surface the probe's stderr on failure so an inertness break is debuggable.
    assert result.returncode == 0, (
        "OKX import-inertness probe failed (returncode "
        f"{result.returncode}).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "INERTNESS_OK" in result.stdout, (
        "inertness sentinel missing from probe stdout.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# The four Phase-7 control types whose consumers are wired LIVE-ONLY (Plan 07-07,
# _initialize_live_session). On the backtest EventHandler they MUST stay explicit-empty
# (the 3-step-flow inertness guarantee, RESEARCH OQ8).
_PHASE7_INERT_ROUTES = (
    "UNIVERSE_POLL",
    "STRATEGY_COMMAND",
    "BARS_LOADED",
    "BARS_LOAD_FAILED",
)


def test_backtest_event_handler_phase7_routes_are_inert_empty() -> None:
    """A freshly-built backtest EventHandler declares the four Phase-7 routes as empty lists.

    The other half of the oracle-inertness contract (RESEARCH OQ8): beyond keeping the
    live MODULES off the backtest import path (the subprocess probe above), the backtest
    builds its OWN ``EventHandler`` whose ``_routes`` literal declares ``UNIVERSE_POLL`` /
    ``STRATEGY_COMMAND`` / ``BARS_LOADED`` / ``BARS_LOAD_FAILED`` as EXPLICIT-EMPTY lists.
    The live consumers (``on_poll`` / ``on_strategy_command`` / ``on_bars_loaded`` /
    ``on_bars_load_failed``) are mutated onto a SEPARATE live EventHandler in
    ``_initialize_live_session`` (Plan 07-07) — never this literal. A non-empty list here
    would mean live routing leaked onto the backtest path (the T-07-07-ORACLE threat).

    Built with ``MagicMock`` collaborators + a real ``Queue``: the ``_routes`` literal only
    *references* handler attributes (e.g. ``self.strategies_handler.calculate_signals``); it
    never calls them at construction, so mocks are sufficient and no backtest data is loaded.
    """
    import queue as _queue
    from unittest.mock import MagicMock

    from itrader.core.enums import EventType
    from itrader.events_handler.full_event_handler import EventHandler

    handler = EventHandler(
        strategies_handler=MagicMock(),
        screeners_handler=MagicMock(),
        portfolio_handler=MagicMock(),
        order_handler=MagicMock(),
        execution_handler=MagicMock(),
        bar_event_source=MagicMock(),
        global_queue=_queue.Queue(),
    )

    for route_name in _PHASE7_INERT_ROUTES:
        event_type = EventType[route_name]
        assert handler.routes[event_type] == [], (
            f"{route_name} must be an EXPLICIT-EMPTY route on the backtest EventHandler — "
            "the live consumers are wired live-only in _initialize_live_session (Plan 07-07). "
            "A non-empty list here means live routing leaked onto the backtest path "
            "(T-07-07-ORACLE oracle-inertness violation)."
        )


def test_new_store_registrars_are_register_vs_build() -> None:
    """Phase 4 (04-03, STORE-05): the 3 new registrars are register-vs-BUILD (Table-only).

    The other half of the inertness contract (RESEARCH OQ3): beyond keeping the new store
    MODULES off the backtest import path (the ``_FORBIDDEN`` probe above), the ``build_*``
    registrars themselves must be register-vs-build — they construct only ``Table`` objects
    on a fresh ``MetaData``, pulling NO Engine and constructing NO ``SqlSettings`` /
    ``SqlEngine`` (mirrors the ``migrations/env.py`` register-vs-build discipline). That is
    what lets ``migrations/env.py`` import them at module scope while staying import-inert.

    Asserts the 3 registrars register EXACTLY the 4 expected table names on a bare
    ``MetaData`` and that no heavy backend (``SqlEngine`` engine / ``SqlSettings``) is built.
    """
    from sqlalchemy import Engine, MetaData

    from itrader.storage.engine import NAMING_CONVENTION
    from itrader.storage.strategy_registry_store import build_strategy_registry_tables
    from itrader.storage.system_store import build_system_store_table
    from itrader.storage.venue_store import build_venue_store_table

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    system_table = build_system_store_table(metadata)
    venue_table = build_venue_store_table(metadata)
    registry_tables = build_strategy_registry_tables(metadata)

    # Table-ONLY registration: the registrars return SQLAlchemy Table objects (no Engine).
    assert not isinstance(system_table, Engine)
    assert not isinstance(venue_table, Engine)
    assert set(registry_tables) == {"strategy_registry", "strategy_subscriptions"}

    # The 3 registrars registered EXACTLY the 4 expected table names on the bare MetaData —
    # no connection, no Settings(), no SqlEngine constructed anywhere in the call chain.
    assert set(metadata.tables) == {
        "system_store",
        "venue_store",
        "strategy_registry",
        "strategy_subscriptions",
    }
