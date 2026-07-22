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
    # TEST-01/D-18: the offline replay provider LEFT the itrader package for the test
    # harness (tests/support/replay_harness) — production paper re-points to the OKX
    # live feed (D-21). The module is gone from itrader, so it can never leak here; the
    # stronger post-D-21 invariant (production registers no 'replay' data provider) is
    # asserted below in the register-vs-build block.
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
    # Phase 5 (05-05, VENUE-02 inertness gate): the concrete OKX + paper venue/data/
    # connector plugin modules are LIVE-ONLY — they are registered at the LTS root
    # (in build_live_system, P6) and their OKX concretion imports + OkxSettings()
    # construction live INSIDE build*() (D-04 triple-deferral). The backtest
    # composition root must pull NEITHER: paper_plugin now holds ONLY PaperVenuePlugin
    # (the replay data plugin/provider left for tests/, D-18), and okx_plugin pulls the
    # ccxt/OkxConnector stack only inside build*(). If a future edit hoists a plugin's
    # concretion import to module scope (or pulls a plugin module onto the backtest path)
    # this probe fails loudly, protecting the oracle byte-exactness + the W1/W2 perf gate.
    "itrader.venues.okx_plugin",
    "itrader.venues.paper_plugin",
    # Phase 11 (11-04, D-02 credentials boundary): the CredentialResolver seam is
    # LIVE-ONLY — it is constructed inside build_live_system and reached by PATH import
    # (mirroring okx_settings), never through the config barrel. Listing it here makes
    # "do not barrel-export the resolver" STRUCTURAL rather than prose: the moment a
    # future edit adds it to itrader/config/__init__.py, importing itrader (which the
    # backtest root does) pulls it onto the hot path and this probe fails loudly. The
    # module itself is pure (os + pydantic) — this guards the barrel discipline, not a
    # heavy import.
    "itrader.config.credential_resolver",
)
leaked = [name for name in _FORBIDDEN if name in sys.modules]
assert not leaked, (
    "CONN-04 INERTNESS VIOLATION: the backtest import path pulled the OKX/async "
    "stack: " + repr(leaked) + " (must be lazy-imported inside the live path only)"
)

# Phase 10.1 (DECOMP-02): GATE-01's REAL invariant, asserted POSITIVELY.
#
# The _FORBIDDEN tuple above is a hardcoded NAME LIST, so it can only catch a
# regression that arrives through a module someone already thought to list. This
# assertion instead states the property the gate actually exists to protect: the
# backtest import graph pulls NO SQL, no matter which module carries it. Strictly
# stronger, and it needs no maintenance as modules are added.
#
# Matching on the TOP-LEVEL package (split on "." and take element 0) rather than
# exact names is the point: "sqlalchemy.orm" and "sqlalchemy.engine.base" must both
# trip the gate, and a submodule-only import is exactly how a regression sneaks in.
#
# ⚠ WHY itrader.strategy_handler.lifecycle.manager IS DELIBERATELY *NOT* IN
# _FORBIDDEN — do not "restore" it. Phase 10.1 moved the STRATEGY_COMMAND control
# plane into that module and hoisted its five formerly function-local import blocks
# to module top; StrategiesHandler constructs StrategyLifecycleManager
# UNCONDITIONALLY in __init__ from a module-top import, so the module IS on the
# backtest import graph BY DESIGN and a _FORBIDDEN entry would redden this gate the
# moment it landed. The old lazy-import comments claimed those imports "would pull
# SQL onto the BACKTEST import graph"; that was re-tested in a clean interpreter
# during 10.1-03 and is false — registry/ reaches the store through an INJECTED
# handle, never an import. The invariant those comments were reaching for is
# SQL-absence, which this assertion states directly.
_SQL_ROOTS = (
    "sqlalchemy",
    "psycopg2",
    "alembic",
)
_sql_leaked = sorted({name.split(".")[0] for name in sys.modules} & set(_SQL_ROOTS))
assert not _sql_leaked, (
    "DECOMP-02 INERTNESS VIOLATION: the backtest import path pulled the SQL stack: "
    + repr(_sql_leaked)
    + " — the backtest composition root must reach no sqlalchemy/psycopg2/alembic at "
    "import (the durable stores are live-only and reached through INJECTED handles, "
    "never a module-top import)"
)

# Phase 06.1 (SEAM-04, D-12): the trading_system barrel DROPPED the live surface
# entirely — importing the backtest root (above) pulls ONLY the backtest composition
# root, so the live module itself must be ABSENT from sys.modules at this point. Before
# the barrel drop, `trading_system/__init__.py` eagerly imported LiveTradingSystem /
# build_live_system, silently dragging the whole live module onto the backtest import
# graph (the root cause of the pervasive lazy-imports-inside-methods). The later
# explicit `from itrader.trading_system.live_trading_system import build_live_system`
# (in the P6 register-vs-build block below) runs AFTER this assertion and legitimately
# pulls the module for the register-vs-build check — it does not weaken this guard.
assert "itrader.trading_system.live_trading_system" not in sys.modules, (
    "SEAM-04/D-12 INERTNESS VIOLATION: importing the backtest root pulled "
    "itrader.trading_system.live_trading_system onto the backtest import graph — the "
    "trading_system barrel must NOT re-import (or re-export) the live module (D-12)"
)

# Phase 1 (CFG-02, D-05/D-06 register-vs-build): importing itrader runs
# ITraderConfig() (itrader/__init__.py). The lazy `sql` cached_property must
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
# 06.1-01 (D-01/D-03): the EngineContext now carries a REQUIRED ``feed`` + Optional
# ``store``. The probe builds a PURE BacktestBarFeed over a CsvPriceStore — both are
# already on the backtest import graph, so the register-vs-build inertness assertion
# below (no ccxt.pro/SQL pulled, `sql` cached_property unresolved) still holds.
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.outils.time_parser import to_timedelta
import random
_bus = FifoEventBus()
_store = CsvPriceStore()
_feed = BacktestBarFeed(_store, to_timedelta("1d"))
# 11.1-04 (D-07): the ctx now carries a REQUIRED ``rng``. ``random`` is stdlib, so the
# field adds nothing to the import graph and the register-vs-build assertion below is
# unaffected — the gate stays green at 4 passed.
_ctx = EngineContext(
    bus=_bus, config=_cfg, environment="backtest",
    feed=_feed, rng=random.Random(42), store=_store, sql_engine=None)
_heavy = [name for name in ("sqlalchemy", "ccxt") if name in sys.modules]
assert not _heavy, (
    "P2 register-vs-build inertness violation: constructing FifoEventBus/"
    "EngineContext(feed=BacktestBarFeed, sql_engine=None) pulled a heavy backend: "
    + repr(_heavy)
)
assert "sql" not in _cfg.__dict__, (
    "P2 register-vs-build inertness violation: building the EngineContext resolved "
    "the lazy `sql` cached_property on the config singleton (must stay unbuilt)"
)

# Phase 5 (05-05, VENUE-02 register-vs-build): importing the CONCRETE OKX + paper
# plugin modules and registering the plugin OBJECTS in the venue/data registries must
# pull NO ccxt.pro / ccxt / OkxConnector concretion — the heavy import happens ONLY
# inside a plugin's build*() method, which this probe deliberately NEVER calls (calling
# it would legitimately pull ccxt + require OKX creds). This is the register != build
# proof (D-04 triple-deferral): if a future edit HOISTS a plugin's `import ccxt.pro` /
# `from itrader.connectors.okx import OkxConnector` / `OkxSettings()` to module top,
# importing the plugin module here pulls the OKX stack and this assertion fails loudly.
#
# NOTE — the ConnectorProvider (itrader.connectors.provider) is INSIDE this ccxt-absent
# window as of Phase 11.1 (RESEARCH F-2). It used to be excluded, on the premise that
# importing anything under the `itrader.connectors` package runs connectors/__init__.py,
# which eagerly re-exported `OkxConnector` and therefore pulled ccxt. That barrel
# re-export is GONE — the barrel now exports only the `LiveConnector` Protocol — so the
# exclusion has no premise left. Folding the provider in is not cosmetic: Phase 11.1's
# D-04 puts a REAL, EMPTY `ConnectorProvider({})` on the BACKTEST wiring path (absence is
# modelled as an empty collection, never as `None`), and the assertion below is the only
# mechanical proof that that wiring stays inert. If a future edit re-introduces a
# concretion re-export in `connectors/__init__.py` (or hoists a ccxt import into
# `connectors/provider.py`), importing the provider here pulls the OKX stack and the
# assertion fails loudly. The OkxConnectorPlugin recipe's own laziness is proven by the
# plugin MODULE staying inert to import (asserted here) plus its build-body unit contract
# (tests/unit/venues/test_okx_plugin.py).
from itrader.venues.okx_plugin import (
    OkxConnectorPlugin,
    OkxDataPlugin,
    OkxVenuePlugin,
)
from itrader.venues.paper_plugin import PaperVenuePlugin
from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry
from itrader.connectors.provider import ConnectorProvider

_exec_registry = ExecutionVenueRegistry()
_data_registry = DataProviderRegistry()
# Register the concrete plugin OBJECTS (store-only — no build*): the OKX venue/data
# plugins + the paper EXECUTION venue plugin (constructed WITH a dummy simulated exchange,
# since it reuses an injected exchange AS-IS). TEST-01/D-18: paper_plugin no longer holds
# a replay DATA plugin (it left for tests/); production paper selects the OKX data feed
# (D-21). OkxConnectorPlugin is constructed too (an inert object; build() never called).
_exec_registry.register("okx", OkxVenuePlugin())
_exec_registry.register("paper", PaperVenuePlugin(object()))
_data_registry.register("okx", OkxDataPlugin())
_okx_connector_plugin = OkxConnectorPlugin()
# Phase 11.1 (D-04): the BACKTEST wiring passes a REAL, EMPTY ConnectorProvider — never
# None. Constructing it is register-only (no plugin build*), so it must pull no ccxt.
_connectors = ConnectorProvider({})

_okx_leaked = [
    name
    for name in ("ccxt.pro", "ccxt", "itrader.connectors.okx")
    if name in sys.modules
]
assert not _okx_leaked, (
    "P5/11.1 register-vs-build inertness violation (VENUE-02/VENUE-03): importing + "
    "registering the OKX/paper venue/data plugins, and importing + constructing the "
    "ConnectorProvider({}) the backtest wires (D-04), pulled the OKX/ccxt stack: "
    + repr(_okx_leaked)
    + " (the ccxt.pro import + OkxSettings() must stay inside a plugin's build*, never "
    "at module or register time — D-04 triple-deferral; and itrader/connectors/__init__.py "
    "must re-export no connector concretion — RESEARCH F-2)"
)

# Phase 6 (06-06, RUN-01/RUN-03 register-vs-build): the new live composition-root
# surface — the ``build_live_system`` factory + the ``LiveRunner`` runtime (which
# composes ``WorkerSupervisor`` + the minimal ``ErrorPolicy``) + the
# ``LiveRouteRegistrar`` + ``SessionInitializer`` — must stay import-inert on the
# backtest path. All their live/venue/SQL wiring lives INSIDE ``build_live_system``'s
# body (never at module or import time), so IMPORTING them (register, not build) pulls
# NO ccxt.pro / ccxt and constructs NO ``SqlSettings`` (the `sql` cached_property stays
# unresolved). This is the register-vs-build proof for the P6 decomposition: if a future
# edit hoists a venue/connector/ccxt/SqlSettings import to module scope in any of these
# modules (or into ``build_live_system``'s top-level), importing them here pulls the OKX/
# SQL stack and this assertion fails loudly — protecting the oracle + the W1/W2 perf gate.
from itrader.trading_system.live_trading_system import build_live_system  # noqa: F401
from itrader.trading_system.live_runner import LiveRunner  # noqa: F401
from itrader.trading_system.worker_supervisor import WorkerSupervisor  # noqa: F401
from itrader.events_handler.error_policy import ErrorPolicy  # noqa: F401
from itrader.trading_system.route_registrar import LiveRouteRegistrar  # noqa: F401
from itrader.trading_system.session_initializer import SessionInitializer  # noqa: F401

_p6_heavy = [name for name in ("ccxt.pro", "ccxt", "itrader.connectors.okx") if name in sys.modules]
assert not _p6_heavy, (
    "P6 register-vs-build inertness violation (RUN-01/RUN-03): importing the new live "
    "factory/runner/registrar surface (build_live_system / LiveRunner / WorkerSupervisor "
    "/ ErrorPolicy / LiveRouteRegistrar / SessionInitializer) pulled the OKX/ccxt stack: "
    + repr(_p6_heavy)
    + " — the venue/connector/ccxt imports must stay INSIDE build_live_system's body "
    "(register != build, D-04)"
)
assert "sql" not in _cfg.__dict__, (
    "P6 register-vs-build inertness violation (RUN-01): importing build_live_system / "
    "LiveRunner resolved the lazy `sql` cached_property on the config singleton — the "
    "live sql_engine must be built INSIDE build_live_system, never at import"
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
    *references* handler attributes (e.g. ``self.strategies_handler.on_bar``); it
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
        error_policy=MagicMock(),
        error_handler=MagicMock(),
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
    # D-06 — the P4 ``strategy_subscriptions`` (venue, symbol, timeframe) child was dropped;
    # ``strategy_portfolio_subscriptions`` models the portfolio fan-out edge instead.
    assert set(registry_tables) == {
        "strategy_registry",
        "strategy_portfolio_subscriptions",
    }

    # The 3 registrars registered EXACTLY the 4 expected table names on the bare MetaData —
    # no connection, no LogConfig(), no SqlEngine constructed anywhere in the call chain.
    assert set(metadata.tables) == {
        "system_store",
        "venue_store",
        "strategy_registry",
        "strategy_portfolio_subscriptions",
    }


def test_production_build_live_system_registers_no_replay_data_provider() -> None:
    """TEST-01/D-21: production ``build_live_system`` registers NO ``'replay'`` data provider.

    The stronger post-D-21 invariant that replaces the old replay-plugin-import
    assertion: the offline replay DATA apparatus LEFT the ``itrader`` package for the test
    harness (D-18), and production ``paper`` re-points to the OKX live data feed (D-21). So
    the ONE live composition root must register EXACTLY the ``'okx'`` data provider — never
    a ``'replay'`` one — and select ``'okx'`` for the paper venue. Asserted by static source
    inspection (``inspect.getsource``) so it is CI-safe (no OKX creds, no build): building
    the paper→okx system would require credentials, but the registration/selection SOURCE is
    the load-bearing invariant. A future edit that re-registers ``'replay'`` in production (or
    re-points the paper map back to ``'replay'``) reddens this loudly.

    SEAM-03/D-11: the ``{'okx':'okx','paper':'okx'}`` default-provider map was centralized
    into the shared ``build_venue_spec`` builder (``trading_system/venue_spec.py``) — its
    SOLE home — which BOTH ``for_exchange`` and ``build_live_system`` call. The paper→okx
    selection invariant is therefore asserted against ``build_venue_spec``'s source now (the
    inline ``SimpleNamespace`` + map in ``build_live_system`` was deleted); the registration
    assertions still inspect ``build_live_system`` where ``data_registry.register`` lives.
    """
    import inspect

    from itrader.trading_system import live_trading_system as _lts
    from itrader.trading_system import venue_spec as _venue_spec

    source = inspect.getsource(_lts.build_live_system)

    # Production registers the OKX data provider and NO replay/test data provider.
    assert "data_registry.register('okx'" in source, (
        "production build_live_system must register the 'okx' data provider (paper→okx, D-21)"
    )
    assert "register('replay'" not in source and 'register("replay"' not in source, (
        "production build_live_system must register NO 'replay' data provider — the replay "
        "harness left itrader for tests/ (D-18); a test fixture injects it via data_plugins"
    )
    # The paper venue selects the OKX live data feed (D-21), never the replay feed. Since
    # SEAM-03/D-11 the default-provider map lives in the shared build_venue_spec builder.
    builder_source = inspect.getsource(_venue_spec.build_venue_spec)
    assert "'paper': 'okx'" in builder_source or '"paper": "okx"' in builder_source, (
        "build_venue_spec must map paper→'okx' (the OKX live data feed, D-21/D-11)"
    )
    assert "'paper': 'replay'" not in builder_source and '"paper": "replay"' not in builder_source, (
        "build_venue_spec must NOT map paper→'replay' (the replay feed left production for "
        "the test fixture, D-21)"
    )
