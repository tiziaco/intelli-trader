"""The relocated replay test-harness (TEST-01 / D-18) — the WHOLE replay apparatus
lives here in ``tests/`` now, NOT in the ``itrader`` production package.

Owner directive (2026-07-13): paper mode stays a **real live production mode** (D-20)
— only the offline replay DATA side is test infrastructure and leaves ``itrader/`` for
``tests/``. This module homes the four relocated concretions + a build helper:

  - ``TestLiveDataProvider`` — the verbatim ``ReplayDataProvider`` (renamed): replays the
    golden ``CsvPriceStore`` frame as confirm-gated ``ClosedBar`` dicts through the exact
    Phase-3 ``LiveBarFeed`` seam (``set_bar_sink`` / ``replay_bar`` / ``iter_closed_bars``
    / ``fetch_ohlcv_backfill`` + the no-op streaming seams).
  - ``TestDataPlugin`` — the verbatim ``ReplayDataPlugin`` (renamed): a
    ``DataProviderPlugin`` that builds a ``TestLiveDataProvider`` over the parity window;
    registered ONLY by the test build helper below (never by production
    ``build_live_system`` — production ``paper`` re-points to the OKX live feed, D-21).
  - ``TestRunner`` — the verbatim ``run_paper_replay`` drive (renamed): the OFFLINE,
    single-thread, synchronous per-bar driver that replays the golden bars through the
    real live feed→queue seam with backtest-faithful per-tick + run-end discipline. It is
    fail-fast BY DEFAULT (D-19) — it drives ``event_handler.process_events()`` DIRECTLY and
    NEVER calls ``start()`` / never installs the live publish-and-continue policy.
  - the ``PAPER_PARITY_*`` window/symbol/timeframe anchor (the single-source parity
    comparand — ``test_paper_parity`` imports it from HERE now).

D-22 (pytest-collection guard): every ``Test*``-named NON-test class here sets
``__test__ = False`` so pytest does NOT collect it as a test class — a
``PytestCollectionWarning`` would be a HARD failure under ``filterwarnings=["error"]``.

Landmine 2 (RESEARCH): ``TestRunner`` obtains the ``TestLiveDataProvider`` handle as a
CONSTRUCTOR ARG (from the fixture's ``TestDataPlugin``), NEVER off a facade attribute —
production no longer carries a ``_replay_provider`` handle.

Indentation: 4-SPACE (matched to the ``price_handler``/``venues`` trees the donors came
from). This module lives OUTSIDE mypy scope (``files = ["itrader"]``) but is written
strict-clean by hand.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Callable

from itrader.config.stream import FeedProviderSettings
from itrader.core.exceptions import ConfigurationError
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger
from itrader.price_handler.providers.okx_provider import ClosedBar
from itrader.price_handler.store.csv_store import CsvPriceStore

# D-18 (structural half — SINGLE SOURCE OF TRUTH for the paper/backtest parity anchor):
# the canonical golden window + symbol + timeframe. BOTH the replay store (constructed
# EXPLICITLY from these in TestDataPlugin.build_provider) AND the backtest comparand
# (test_paper_parity.py imports these) derive from THESE literals, so paper/backtest
# parity can never silently desync. WR-01: the golden parity grid's timeframe is its OWN
# anchor here, NOT the live-tunable StreamSettings.okx_stream_timeframe.
PAPER_PARITY_START_DATE = "2018-01-01"
PAPER_PARITY_END_DATE = "2026-06-03"
PAPER_PARITY_SYMBOL = "BTCUSD"
PAPER_PARITY_TIMEFRAME = "1d"


class TestLiveDataProvider:
    """Replay the golden ``CsvPriceStore`` frame as confirm-gated ``ClosedBar`` dicts.

    Relocated verbatim from ``itrader.price_handler.providers.replay_provider``'s
    ``ReplayDataProvider`` (rename only): the offline, synchronous stand-in for
    ``OkxDataProvider`` that replays the committed golden BTCUSD CSV through the exact
    Phase-3 ``LiveBarFeed`` seam. Constructed with the committed golden store plus the
    ``symbol``/``timeframe`` it stamps. It registers no sink at construction; the
    ``LiveBarFeed`` registers one via :meth:`set_bar_sink`, and ``TestRunner`` pushes each
    completed row synchronously via :meth:`replay_bar`.

    The confirm gate is satisfied by construction — every stored row is a completed bar.

    Uniform provider surface (VENUE-05 / D-10): implements the optional streaming/wiring
    seams (``set_global_queue`` / ``set_halt_signal`` / ``set_stream_state_listener`` /
    ``subscribe`` / ``unsubscribe`` / ``spawn_warmup`` / ``is_streaming_healthy`` →
    ``True``) DIRECTLY as no-ops, so the ``VenueLifecycle`` can call the streaming seams
    UNCONDITIONALLY on any provider. It keeps its own real ``set_bar_sink``, so
    ``isinstance(TestLiveDataProvider(...), LiveDataProvider)`` is True.

    D-22: ``__test__ = False`` so pytest never collects this ``Test*``-named class.
    """

    __test__ = False

    def __init__(
        self,
        store: CsvPriceStore | None = None,
        symbol: str = "BTCUSD",
        timeframe: str = "1d",
    ) -> None:
        """Bind the golden store + the stamping config; open no I/O beyond the store load.

        Parameters
        ----------
        store : CsvPriceStore, optional
            The golden price store. ``None`` defaults to ``CsvPriceStore()`` (the committed
            BTCUSD dataset, pinned window — byte-identical to the backtest store frame).
        symbol : str
            The universe-member ticker stamped into every ``ClosedBar`` (default
            ``"BTCUSD"``) — the form the strategy's ``window()`` queries, NOT ``"BTC/USDT"``.
        timeframe : str
            The bar timeframe stamped into every ``ClosedBar`` (default ``"1d"``).
        """
        self.logger = get_itrader_logger().bind(component="TestLiveDataProvider")
        self._store = store if store is not None else CsvPriceStore()
        self._symbol = symbol
        self._timeframe = timeframe
        # The LiveBarFeed registers the sink; until then bars are dropped-and-logged.
        self._bar_sink: Callable[[ClosedBar], None] | None = None

    # -- Phase-3 feed seam (mirror okx_provider.py:160-174) --------------------

    def set_bar_sink(self, sink: Callable[[ClosedBar], None]) -> None:
        """Register the closed-bar sink the Phase-3 ``LiveBarFeed`` consumes.

        Verbatim analog of ``OkxDataProvider.set_bar_sink``: the provider hands a raw
        ``ClosedBar`` dict; the feed owns ``BarEvent`` construction and the ring buffer.
        """
        self._bar_sink = sink

    def replay_bar(self, bar: ClosedBar) -> None:
        """Deliver one completed bar to the registered sink (drop-and-log if unset).

        The PUBLIC synchronous analog of ``OkxDataProvider._hand_closed_bar`` — ``TestRunner``
        interleaves these per-bar pushes with ``process_events`` (D-03). No sink registered
        is a legitimate (mis-wired) state: WARN and drop, never raise.
        """
        if self._bar_sink is None:
            self.logger.warning(
                "Closed bar dropped — no bar sink registered (set_bar_sink not called)")
            return
        self._bar_sink(bar)

    # -- Golden-CSV replay (NEW, replaces the async _stream_candles loop — D-03) --

    def iter_closed_bars(self) -> Iterator[ClosedBar]:
        """Yield the golden store rows as Decimal-edge ``ClosedBar`` dicts, in frame order.

        Each row's ``ts`` is the tz-aware ``date`` index value converted to epoch-ms
        verbatim (``int(index.value // 1_000_000)`` — the ms round-trip lands exactly on
        the backtest bar-open grid, D-09). Every OHLCV cell crosses the Decimal edge via
        ``to_money(str(cell))`` (never the Decimal-from-float constructor, never a bulk
        float cast). The ``symbol``/``timeframe`` routing keys are stamped from trusted
        provider config, NOT read off the row (D-12). Frame order/values are identical to
        the backtest read — the parity anchor (D-01).
        """
        frame = self._store.read_bars(self._symbol)
        for row in frame.itertuples():
            ts_ms = int(row.Index.value // 1_000_000)
            closed: ClosedBar = {
                "ts": ts_ms,
                "open": to_money(str(row.open)),
                "high": to_money(str(row.high)),
                "low": to_money(str(row.low)),
                "close": to_money(str(row.close)),
                "volume": to_money(str(row.volume)),
                "symbol": self._symbol,
                "timeframe": self._timeframe,
            }
            yield closed

    def fetch_ohlcv_backfill(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[ClosedBar]:
        """Return the golden bars for the Phase-3 warmup / gap-backfill seam.

        Mirrors ``OkxDataProvider.fetch_ohlcv_backfill``'s signature so
        ``LiveBarFeed.set_provider``/``warmup`` have a working ``_provider`` seam. Returns
        ``iter_closed_bars()`` filtered to ``since is None or cb["ts"] >= since`` and
        truncated to ``limit``. The golden 1d bars are contiguous so no gap-backfill fires
        on the parity path, but the method must exist and be Decimal-edge-correct.
        ``limit`` defaults to the folded backfill page size (CFG-03/D-08,
        ``FeedProviderSettings().backfill_page``) when not given.
        """
        if limit is None:
            limit = FeedProviderSettings().backfill_page
        bars = [
            cb for cb in self.iter_closed_bars()
            if since is None or cb["ts"] >= since
        ]
        return bars[:limit]

    # -- Optional streaming/wiring seams: inline no-ops (VENUE-05 / D-10) -------
    # Offline replay does NOT stream, so each of these is a DELIBERATE no-op. They
    # exist only so the VenueLifecycle (05-06) can call the streaming seams
    # UNCONDITIONALLY on any provider — no venue-string branch, no hasattr probe.

    def set_global_queue(self, global_queue: Any) -> None:
        """No-op: a non-streaming provider emits no async warmup events."""
        return None

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """No-op: a non-streaming provider raises no connector-fatal halt."""
        return None

    def set_stream_state_listener(
        self,
        on_down: Callable[[str], None],
        on_up: Callable[[str], None],
    ) -> None:
        """No-op: a non-streaming provider never goes down/up."""
        return None

    def subscribe(self, symbol: str) -> None:
        """No-op: a non-streaming provider has no per-symbol stream to subscribe."""
        return None

    def unsubscribe(self, symbol: str) -> None:
        """No-op: a non-streaming provider has no per-symbol stream to unsubscribe."""
        return None

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        """No-op: a non-streaming provider does no loop-native REST warmup."""
        return None

    def is_streaming_healthy(self) -> bool:
        """A non-streaming provider is trivially healthy."""
        return True


class TestDataPlugin:
    """The replay ``DataProviderPlugin`` — builds a ``TestLiveDataProvider`` (D-18).

    Relocated verbatim from ``itrader.venues.paper_plugin``'s ``ReplayDataPlugin``
    (rename only). ``build_provider`` constructs the replay provider from the shared
    ``PAPER_PARITY_*`` window (the paper-parity comparand). Registered ONLY by the test
    build helper (``build_paper_replay_system``), NEVER by production ``build_live_system``
    (production ``paper`` selects the OKX live feed, D-21).

    The last-built provider is stashed on ``self.provider`` so the fixture can hand the
    ``TestLiveDataProvider`` handle to ``TestRunner`` WITHOUT reading a facade attribute
    (RESEARCH Landmine 2).

    D-22: ``__test__ = False`` so pytest never collects this ``Test*``-named class.
    """

    __test__ = False

    def __init__(self) -> None:
        # The last-built provider handle (Landmine 2 — TestRunner takes it as a ctor arg).
        self.provider: TestLiveDataProvider | None = None

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> TestLiveDataProvider:
        """Build the ``TestLiveDataProvider`` over the golden parity window.

        Constructs the replay store EXPLICITLY from the shared parity window so the paper
        comparand and the backtest read ONE source and can never silently desync (WR-02).
        """
        provider = TestLiveDataProvider(
            store=CsvPriceStore(
                start_date=PAPER_PARITY_START_DATE, end_date=PAPER_PARITY_END_DATE
            ),
            symbol=PAPER_PARITY_SYMBOL,
            timeframe=PAPER_PARITY_TIMEFRAME,
        )
        self.provider = provider
        return provider


class TestRunner:
    """Drive the golden dataset E2E through the live-paper mechanism, synchronously.

    Relocated verbatim from ``LiveTradingSystem.run_paper_replay`` (D-16): the OFFLINE,
    single-thread paper driver that replays the golden bars one-by-one through the real
    Phase-3 live seam (replay provider → feed.update → BarEvent → queue) using the EXACT
    per-tick + run-end discipline of the backtest runner — but BAR-driven. There is NO
    daemon thread and NO ``start()``/``stop()`` call: ``TestRunner`` drives
    ``event_handler.process_events()`` DIRECTLY and NEVER installs the live
    publish-and-continue policy — fail-fast BY DEFAULT (D-19), so a handler failure aborts
    the replay loudly and the parity gate can't false-green.

    Landmine 2: the ``TestLiveDataProvider`` handle is a CONSTRUCTOR ARG (from the
    fixture's ``TestDataPlugin``), never read off ``system._replay_provider`` (production
    no longer carries that handle).

    D-22: ``__test__ = False`` so pytest never collects this ``Test*``-named class.
    """

    __test__ = False

    def __init__(self, system: Any, provider: TestLiveDataProvider) -> None:
        """Bind the factory-built paper ``system`` + the ``TestLiveDataProvider`` handle."""
        self._system = system
        self._provider = provider

    def run(self) -> None:
        """Replay the golden dataset synchronously through the live-paper seam.

        Determinism is by construction (D-09): the seeded random.Random already lives in
        the shared ExecutionHandler injected into the reused SimulatedExchange — identical
        to backtest — and every bar's time is the feed's own bar-open stamp, never
        wall-clock.
        """
        # WR-02 (assertion half): assert the replay store's effective window/symbol equals
        # the canonical golden window the backtest is constructed with — fail loudly HERE
        # with a clear ConfigurationError instead of a confusing count-equality diff.
        _store = self._provider._store
        if (_store.start_date != PAPER_PARITY_START_DATE
                or _store.end_date != PAPER_PARITY_END_DATE
                or self._provider._symbol != PAPER_PARITY_SYMBOL):
            raise ConfigurationError(
                config_key="paper_replay_window",
                config_value=(
                    f"({_store.start_date}, {_store.end_date}, "
                    f"{self._provider._symbol})"),
                reason=(
                    f"replay store window/symbol drifted from the backtest parity "
                    f"window: expected ({PAPER_PARITY_START_DATE}, {PAPER_PARITY_END_DATE}, "
                    f"{PAPER_PARITY_SYMBOL}) but got ({_store.start_date}, "
                    f"{_store.end_date}, {self._provider._symbol}). Align the "
                    "replay store window/symbol with the parity backtest."))

        # WR-01: the parity grid's timeframe must ALSO stay pinned to the anchor, not the
        # live-tunable StreamSettings.okx_stream_timeframe — else a live timeframe change
        # would silently re-grid the golden comparand past the window/symbol guard above.
        if self._provider._timeframe != PAPER_PARITY_TIMEFRAME:
            raise ConfigurationError(
                config_key="paper_replay_timeframe",
                config_value=str(self._provider._timeframe),
                reason=(
                    f"replay store timeframe drifted from the backtest parity grid: "
                    f"expected {PAPER_PARITY_TIMEFRAME!r} but got "
                    f"{self._provider._timeframe!r}. Pin the paper replay timeframe "
                    "to PAPER_PARITY_TIMEFRAME, not the live stream config."))

        # Step 1 — session init (ORDER-SENSITIVE): delegates to SessionInitializer
        # (wire_universe injects the Universe into the 'paper' exchange +
        # order/portfolio/strategies handlers and binds the feed; register_strategy_warmup
        # sizes cache_capacity() to the max strategy warmup — 100 for SMA_MACD; WITHOUT it
        # the ring collapses to 1 and the run yields zero trades, Pitfall 1). Session init
        # stays DEFERRED (06-06 kept the D-12 construction-time flip deferred), so
        # TestRunner invokes it here — behavior-preserving with the old run_paper_replay.
        self._system._initialize_live_session()

        # Step 2 — synchronous per-bar drive (mirror backtest_runner._run_backtest,
        # BAR-driven): per bar, in this order,
        #   (a) replay_bar -> registered sink self.feed.update -> BarEvent on queue,
        #   (b) process_events() drains BAR -> SIGNAL -> ORDER -> FILL in-thread,
        #   (c) a DIRECT record_metrics per active portfolio using the feed's own
        #       bar-open stamp (Trap 4 — backtest calls record_metrics directly).
        for cb in self._provider.iter_closed_bars():
            self._provider.replay_bar(cb)
            self._system.event_handler.process_events()
            newest = self._system.feed.newest_bar(PAPER_PARITY_SYMBOL)
            if newest is None:
                continue
            # WR-03: only record when the feed's newest-DELIVERED bar IS the bar replayed
            # THIS iteration. If the LiveBarFeed monotonic guard dropped this bar, newest
            # holds the PREVIOUS bar's stamp — recording it would re-stamp an
            # already-recorded timestamp. On the contiguous golden dataset no bar is ever
            # dropped, so newest always equals the replayed bar (byte-exact).
            if int(newest.time.timestamp() * 1000) != cb["ts"]:
                continue
            bar_time = newest.time
            for portfolio in self._system.portfolio_handler.get_active_portfolios():
                portfolio.record_metrics(bar_time)

        # Step 3 — run-end time-in-force sweep (byte-exact parity with the backtest
        # runner): expire every still-resting order, then ONE final process_events()
        # drain clears them through the exchange. No record_metrics after the sweep —
        # the last per-bar record_metrics was the final equity point.
        self._system.order_handler.expire_all_resting()
        self._system.event_handler.process_events()


def build_paper_replay_system(
    *,
    status_callback: Any = None,
    **overrides: Any,
) -> tuple[Any, TestLiveDataProvider]:
    """Build an OFFLINE paper ``LiveTradingSystem`` with the replay DATA feed injected.

    Production ``paper`` re-points to the OKX live data feed (D-21), so the ``paper`` ↔
    replay pairing survives ONLY here in the test fixture: this helper registers a
    ``TestDataPlugin`` on the factory's data registry (via the ``data_plugins`` injection
    seam) and selects it with ``data_provider="replay"``. Returns ``(system, provider)``
    where ``provider`` is the built ``TestLiveDataProvider`` handle — handed to
    ``TestRunner`` as a constructor arg (Landmine 2), never read off the facade.

    ``**overrides`` threads through to ``LiveTradingSystem.for_exchange`` (e.g. a bespoke
    ``account_id``); ``status_callback`` threads through unchanged.
    """
    from itrader.events_handler.error_policy import FailFastPolicy
    from itrader.trading_system.live_trading_system import LiveTradingSystem

    plugin = TestDataPlugin()
    system = LiveTradingSystem.for_exchange(
        "paper",
        status_callback=status_callback,
        data_provider="replay",
        data_plugins={"replay": plugin},
        **overrides,
    )
    # D-06/D-19 (08-03): the REPLAY parity gate is fail-fast BY DEFAULT — a handler failure
    # must abort the replay loudly so the gate can't false-green. build_live_system now
    # injects the live publish-and-continue ErrorPolicy at EventHandler construction (the
    # old start()-only monkeypatch is gone, and TestRunner never calls start()), so the
    # offline replay fixture OVERRIDES the injected policy back to a FailFastPolicy here —
    # honouring D-06's "backtest/replay inject FailFastPolicy; live injects ErrorPolicy".
    system.event_handler._error_policy = FailFastPolicy()
    assert plugin.provider is not None, (
        "TestDataPlugin.build_provider was never called — the paper data registry did not "
        "select the injected 'replay' plugin (check the data_plugins injection seam)")
    return system, plugin.provider
