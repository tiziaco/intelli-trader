"""Contract tests for the D-01 rehydrate seam — ``store x catalog x codec -> Strategy``.

**D-01** — rehydrate INSTANTIATES strategy instances from the store. It does not re-apply
state onto a roster hardcoded in composition code: the store is the source of truth for
WHAT TRADES. Strategy *types* are code (injected via the catalog); strategy *instances*
are data.

**D-02** — ``strategy_name`` is the only restart-stable identity. A duplicate name is a
LOUD reject (it would otherwise silently overwrite another instance's persisted state), and
the rehydrated instance mints a FRESH ephemeral ``strategy_id`` UUIDv7 per construction.

**D-16** — a ``PairStrategy`` row rehydrates like any other instance; no special case.

**D-19** — the two-arm failure split:

* PER-INSTANCE (unknown ``strategy_type``, undecodable ``config_json``) -> SKIP that
  instance, CRITICAL alert, continue with the healthy ones, and NEVER mutate the row. One
  stale row must not become a self-inflicted outage, and flipping ``enabled=False`` would
  destroy the operator's declared intent so that fixing the class + restarting would leave
  the strategy dark.
* INFRASTRUCTURE (rows exist but no catalog was injected; the store is unreadable) -> FAIL
  LOUD. Booting with silently zero strategies is worse than not booting.

**D-21** — an EMPTY registry is a valid first-start state: a silent, error-free no-op.

Assertions go against the injected ``alert_sink`` test double, never through log capture:
``make test`` exports ``ITRADER_DISABLE_LOGS=true``, which would break a log-capture
assertion. The double is green under both runners.

4-space indentation (matches ``tests/unit/strategy/*``). NO ``__init__.py`` in this dir
(package-collision hazard). Folder-derived ``unit`` marker.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from queue import Queue
from typing import Any
from uuid import UUID

import pytest
from uuid_utils.compat import uuid7

from itrader.config.sql import SqlSettings
from itrader.core.enums import ErrorSeverity
from itrader.core.exceptions import UnknownParamError
from itrader.core.ids import PortfolioId
from itrader.core.sizing import FractionOfCash
from itrader.price_handler.feed.cache_registration import UnwarmableTimeframeError
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.registry import StrategyConfigError, UnknownStrategyTypeError
from itrader.strategy_handler.registry.rehydrate import (
    RehydrateInfrastructureError,
    build_strategy,
    rehydrate_strategies,
)
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategy
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import EthBtcPairStrategy
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from tests.support.schema import provision_schema
from tests.support.strategy_catalog import seeded_registry_rows, test_catalog

pytestmark = pytest.mark.unit

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _StubFeed:
    """A minimal BarFeed stand-in — add_strategy never touches the feed.

    This variant has NO ``base_timeframe``, so rehydrate's F-1 warmability check
    skips cleanly (the backtest/in-memory degrade). The ``_StubFeedWithBase``
    variant below carries one and exercises the finer-than-base quarantine arm.
    """

    def symbols(self) -> list[str]:
        return ["BTCUSD"]


class _StubFeedWithBase:
    """A LIVE-feed stand-in carrying ``base_timeframe`` (mirrors ``_StubFeed``).

    Rehydrate resolves the base cadence via ``getattr(feed, "base_timeframe",
    None)`` — the exact seam ``add``/``reconfigure`` use — so a feed exposing one
    makes the F-1 warmability check RUN, quarantining a finer-than-base row.
    """

    def __init__(self, base_timeframe: timedelta) -> None:
        self.base_timeframe = base_timeframe

    def symbols(self) -> list[str]:
        return ["BTCUSD"]


class _RecordingAlertSink:
    """Recording ``AlertSink`` double (the P8 structural-fake seam).

    ``alert_sink.alert(event)`` takes an ``ErrorEvent``; the double keeps every event so a
    test can assert on COUNT and on the payload's declared fields. Asserting here rather
    than through log capture is deliberate — see the module docstring.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    def alert(self, event: Any) -> None:
        self.events.append(event)


def _make_handler(
    *, allow_short_selling: bool = False, enable_margin: bool = False
) -> StrategiesHandler:
    """A handler for rehydrate to register onto.

    The SHORT-01/D-07 flags default OFF, matching production defaults. A pair strategy is
    ``LONG_SHORT``, so rehydrating one requires BOTH flags on — the registration gate is
    upstream of rehydrate and applies to a reconstructed instance exactly as it does to a
    hand-added one (see ``test_pair_row_needs_the_short_flags_like_any_other_instance``).
    """
    return StrategiesHandler(
        Queue(),
        _StubFeed(),
        InMemorySignalStore(),
        allow_short_selling=allow_short_selling,
        enable_margin=enable_margin,
    )


def _make_pair_handler() -> StrategiesHandler:
    """A handler that admits the ``LONG_SHORT`` pair strategy (SHORT-01/D-07 both flags on)."""
    return _make_handler(allow_short_selling=True, enable_margin=True)


def _make_handler_with_base(base_timeframe: timedelta) -> StrategiesHandler:
    """A handler over a feed exposing ``base_timeframe`` — the LIVE warmability arm.

    The default (both-off) short flags match production; only the feed differs from
    ``_make_handler`` so rehydrate's F-1 check runs against a real base cadence.
    """
    return StrategiesHandler(
        Queue(),
        _StubFeedWithBase(base_timeframe),
        InMemorySignalStore(),
    )


def _make_store() -> StrategyRegistryStore:
    """An in-memory SQLite registry store — schema-pure, so provision explicitly (WR-03)."""
    store = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    return store


def _seed(store: StrategyRegistryStore, strategies: Any, *, enabled: bool = True) -> None:
    """Seed well-formed registry + portfolio-subscription rows for ``strategies``.

    Reuses Plan 04's ``seeded_registry_rows`` (the shared fixture) and writes them through
    the store's real verbs, so the rows under test are exactly what a production writer
    would have produced.
    """
    registry_rows, subscription_rows = seeded_registry_rows(strategies, enabled=enabled)
    for row in registry_rows:
        store.upsert(
            row["strategy_name"],
            row["strategy_type"],
            row["config_json"],
            row["enabled"],
            _AT,
        )
    for row in subscription_rows:
        store.add_portfolio_subscription(row["strategy_name"], row["portfolio_id"])


def _sma(name: str = "sma_macd", **kwargs: Any) -> SMAMACDStrategy:
    strategy = SMAMACDStrategy(timeframe="1d", tickers=["BTCUSD"], **kwargs)
    strategy.name = name
    return strategy


def _empty(name: str = "empty") -> EmptyStrategy:
    strategy = EmptyStrategy(
        timeframe="1h",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.5")),
    )
    strategy.name = name
    return strategy


# --------------------------------------------------------------------------------------
# Happy path (D-01)
# --------------------------------------------------------------------------------------


def test_rehydrate_registers_seeded_instances_with_params_and_subscriptions() -> None:
    """D-01 — two seeded rows become two registered instances from store x catalog x codec.

    The load-bearing assertion is that the STORE drove the roster: nothing in this test
    hands the handler a strategy object.
    """
    store = _make_store()
    try:
        sma = _sma(sizing_policy=FractionOfCash(Decimal("0.75")))
        sma.subscribe_portfolio(11)
        sma.subscribe_portfolio(22)
        empty = _empty()
        empty.subscribe_portfolio(33)
        _seed(store, [sma, empty])

        handler = _make_handler()
        sink = _RecordingAlertSink()

        quarantined = rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=sink,
        )

        assert quarantined == []
        by_name = {s.name: s for s in handler.strategies}
        assert set(by_name) == {"sma_macd", "empty"}

        rebuilt_sma = by_name["sma_macd"]
        assert type(rebuilt_sma) is SMAMACDStrategy
        assert rebuilt_sma.tickers == ["BTCUSD"]
        assert rebuilt_sma.timeframe_alias == "1d"
        # A NON-default sizing policy: a defaults-only assertion would pass even against a
        # codec that dropped the field entirely.
        assert rebuilt_sma.sizing_policy == FractionOfCash(Decimal("0.75"))
        assert sorted(str(p) for p in rebuilt_sma.subscribed_portfolios) == ["11", "22"]

        rebuilt_empty = by_name["empty"]
        assert type(rebuilt_empty) is EmptyStrategy
        assert rebuilt_empty.timeframe_alias == "1h"
        assert [str(p) for p in rebuilt_empty.subscribed_portfolios] == ["33"]
    finally:
        store.dispose()


def test_rehydrate_round_trips_decimal_params_as_decimal_not_str() -> None:
    """D-04/money — a Decimal param rehydrates as a **Decimal**, asserted on TYPE.

    This fails SILENTLY when it regresses: ``_COERCE`` covers only ``timeframe``/
    ``direction``, so a dropped Decimal arm lands the param on the instance as a ``str``
    and ``validate()``'s comparisons become lexicographic (``'0.5' < '2'`` is True). The
    corruption then surfaces far away, in the alpha. NON-default values throughout — a
    defaults-only test passes against a codec that drops the field.
    """
    store = _make_store()
    try:
        pair = EthBtcPairStrategy(
            timeframe="1d",
            entry_z=Decimal("3"),
            exit_z=Decimal("0.25"),
        )
        pair.name = "pair"
        _seed(store, [pair])

        handler = _make_pair_handler()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        rebuilt = handler.strategies[0]
        assert type(rebuilt.entry_z) is Decimal
        assert type(rebuilt.exit_z) is Decimal
        assert rebuilt.entry_z == Decimal("3")
        assert rebuilt.exit_z == Decimal("0.25")
    finally:
        store.dispose()


def test_rehydrate_reconstructs_disabled_rows_present_but_dark() -> None:
    """CR-01 — ``read_all()`` loads the FULL roster: an ``enabled=False`` row is reconstructed
    present-but-dark (``is_active`` False), re-enable-able, NOT dropped.

    Dropping disabled rows would orphan their positions and make the strategy unreachable
    after a restart; ``enabled`` is honored as ``is_active``, not used as a load filter.
    """
    store = _make_store()
    try:
        _seed(store, [_sma()], enabled=True)
        _seed(store, [_empty()], enabled=False)

        handler = _make_handler()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        by_name = {s.name: s for s in handler.strategies}
        # BOTH rows reconstructed — the disabled one is not silently dropped.
        assert set(by_name) == {"sma_macd", "empty"}
        assert by_name["sma_macd"].is_active is True
        assert by_name["empty"].is_active is False

        # Present-but-dark means re-enable-able: activate_strategy() flips it back.
        by_name["empty"].activate_strategy()
        assert by_name["empty"].is_active is True
    finally:
        store.dispose()


def test_uuid_portfolio_subscription_rehydrates_as_a_portfolio_id_not_a_str() -> None:
    """The fan-out id round-trips through the String column back to a UUID PortfolioId.

    Asserted on TYPE. The runtime portfolio handle is always a UUIDv7-backed
    ``PortfolioId`` (``strategies_handler`` FL-02), but the durable column is a ``String``.
    Handing the raw string back would sail through the fan-out's ``cast`` and reach the
    portfolio lookup as an id matching NOTHING — the strategy would look healthy and trade
    into the void. A string-vs-UUID assertion is the only thing that catches it.
    """
    store = _make_store()
    try:
        portfolio_id = PortfolioId(uuid7())
        sma = _sma()
        sma.subscribe_portfolio(portfolio_id)
        _seed(store, [sma])

        handler = _make_handler()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        subscriptions = handler.strategies[0].subscribed_portfolios
        assert subscriptions == [portfolio_id]
        assert isinstance(subscriptions[0], UUID)
        assert not isinstance(subscriptions[0], str)
    finally:
        store.dispose()


def test_malformed_portfolio_subscription_quarantines_the_instance() -> None:
    """A fan-out id that parses as neither UUID nor int quarantines the whole instance.

    Registering it half-wired would be worse than skipping it: it would trade with a
    silently truncated portfolio set.
    """
    store = _make_store()
    try:
        _seed(store, [_sma()])
        store.add_portfolio_subscription("sma_macd", "not-an-id")

        handler = _make_handler()
        sink = _RecordingAlertSink()

        quarantined = rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=sink,
        )

        assert quarantined == ["sma_macd"]
        assert handler.strategies == []  # NOT registered half-wired
        assert len(sink.events) == 1
    finally:
        store.dispose()


def test_finer_than_base_timeframe_row_is_quarantined_at_rehydrate_not_crash_boot() -> None:
    """WR-01 re-review — a finer-than-base row is QUARANTINED at rehydrate, not raised.

    A stored row whose timeframe is FINER than the feed base cadence can never warm from
    the base-bar ring (F-1). Before Option A this raised ``UnwarmableTimeframeError`` out of
    ``register_strategy_warmup`` and crashed the ENTIRE live boot — one stale row becomes a
    self-inflicted outage. Now it takes the SAME per-instance D-19 quarantine the codec /
    param failures already get: skip + one CRITICAL alert + continue, the healthy sibling
    loads, boot does NOT raise, and the row is NEVER mutated (enabled stays True).

    ``read_all()`` orders name-ASC, so "empty" (1h, finer than the 1d base) is processed
    before "sma_macd" (1d == base): the sibling loading proves the quarantine did not abort.
    """
    store = _make_store()
    try:
        _seed(store, [_sma(), _empty()])  # sma_macd @ 1d (== base), empty @ 1h (finer)

        handler = _make_handler_with_base(timedelta(days=1))
        sink = _RecordingAlertSink()

        quarantined = rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=sink,
        )

        assert quarantined == ["empty"]
        # The healthy 1d sibling still loaded — boot did not abort on the bad row.
        assert [s.name for s in handler.strategies] == ["sma_macd"]
        assert len(sink.events) == 1
        assert sink.events[0].error_type == UnwarmableTimeframeError.__name__
        assert sink.events[0].severity is ErrorSeverity.CRITICAL
        # D-19 — the row is UNTOUCHED; enabled stays True so it reloads once the base
        # cadence can serve it (never silently flipped to disabled).
        assert store.get("empty")["enabled"] is True
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# D-21 — the empty registry is a valid first-start state
# --------------------------------------------------------------------------------------


def test_empty_registry_rehydrates_to_zero_strategies_silently() -> None:
    """D-21 — a fresh DB: zero strategies, empty quarantine, no raise, NO alert.

    The engine boots, trades nothing, and waits. There is no seed-from-config path and no
    manual-DB-insert path, so this is the DEFAULT state of every existing live test.
    """
    store = _make_store()
    try:
        handler = _make_handler()
        sink = _RecordingAlertSink()

        quarantined = rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=sink,
        )

        assert quarantined == []
        assert handler.strategies == []
        assert sink.events == []
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# D-19 — per-instance quarantine
# --------------------------------------------------------------------------------------


def test_quarantine_skips_bad_rows_keeps_healthy_and_never_mutates_the_row() -> None:
    """D-19 — one stale row must never block every healthy strategy.

    Three rows: healthy / retired class (absent from the catalog) / param drift (an unknown
    key in the blob). The healthy one loads; the two bad ones are skipped, named in the
    return, and alerted CRITICAL. Crucially the DB rows are UNCHANGED — the runtime reports
    "could not load it" and never rewrites the operator's declared intent.
    """
    store = _make_store()
    try:
        _seed(store, [_sma()])

        # A retired class: the row's strategy_type is absent from the injected catalog.
        retired = _empty(name="retired")
        rows, _ = seeded_registry_rows([retired])
        blob = dict(rows[0]["config_json"])
        blob["strategy_type"] = "RetiredStrategy"
        store.upsert("retired", "RetiredStrategy", blob, True, _AT)

        # Param drift: the blob carries a param this build's class no longer declares.
        drifted = _empty(name="drifted")
        rows, _ = seeded_registry_rows([drifted])
        blob = dict(rows[0]["config_json"])
        blob["removed_knob"] = 7
        store.upsert("drifted", "EmptyStrategy", blob, True, _AT)

        handler = _make_handler()
        sink = _RecordingAlertSink()

        quarantined = rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=sink,
        )

        # The healthy sibling loaded; the two bad ones did not.
        assert [s.name for s in handler.strategies] == ["sma_macd"]
        assert sorted(quarantined) == ["drifted", "retired"]
        assert len(sink.events) == 2
        assert all(e.severity is ErrorSeverity.CRITICAL for e in sink.events)

        # The rows are UNTOUCHED — enabled still True, config_json still the stored blob.
        for name in ("retired", "drifted"):
            row = store.get(name)
            assert row is not None
            assert row["enabled"] is True, (
                f"{name}: quarantine must NEVER flip enabled=False — the DB holds the "
                "operator's declared INTENT (D-19)"
            )
        assert store.get("drifted")["config"]["removed_knob"] == 7
    finally:
        store.dispose()


def test_quarantine_alert_names_the_strategy_and_error_kind_and_leaks_no_config() -> None:
    """D-19 — the CRITICAL alert carries ``strategy_name`` + the error KIND, nothing else.

    The P8 declared-fields-only precedent: no config values, no stack-embedded secrets.
    ``0.987654321`` is a distinctive stored value; it must appear nowhere in the payload.
    """
    store = _make_store()
    try:
        secretish = _sma(name="leaky", sizing_policy=FractionOfCash(Decimal("0.987654321")))
        rows, _ = seeded_registry_rows([secretish])
        blob = dict(rows[0]["config_json"])
        blob["strategy_type"] = "RetiredStrategy"
        store.upsert("leaky", "RetiredStrategy", blob, True, _AT)

        sink = _RecordingAlertSink()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=_make_handler(),
            alert_sink=sink,
        )

        assert len(sink.events) == 1
        event = sink.events[0]
        assert event.error_type == UnknownStrategyTypeError.__name__
        rendered = f"{event.source}|{event.error_type}|{event.error_message}|{event.details}"
        assert "leaky" in rendered
        assert "0.987654321" not in rendered, (
            "the alert must not carry config values (P8 declared-fields-only precedent)"
        )
    finally:
        store.dispose()


def test_pair_row_rehydrates_with_no_special_case() -> None:
    """D-16 — an ``EthBtcPairStrategy`` row takes the identical path, extras intact.

    Excluding pairs would mean pairs do not survive restart, gutting STRAT-01 for the pair
    case. Non-default extras, deliberately.
    """
    store = _make_store()
    try:
        # entry_units is declared ``Decimal`` on EthBtcPairStrategy — an int would be
        # refused at the codec's money boundary (float/int for money is a defect).
        pair = EthBtcPairStrategy(
            timeframe="1d", entry_units=Decimal("2"), use_log_prices=False
        )
        pair.name = "eth_btc"
        pair.subscribe_portfolio(9)
        _seed(store, [pair])

        handler = _make_pair_handler()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        rebuilt = handler.strategies[0]
        assert type(rebuilt) is EthBtcPairStrategy
        assert rebuilt.name == "eth_btc"
        assert type(rebuilt.entry_units) is Decimal
        assert rebuilt.entry_units == Decimal("2")
        assert rebuilt.use_log_prices is False
        assert [str(p) for p in rebuilt.subscribed_portfolios] == ["9"]
    finally:
        store.dispose()


def test_pair_row_needs_the_short_flags_like_any_other_instance() -> None:
    """D-16 x SHORT-01/D-07 — the registration gate applies to a REBUILT instance too.

    A pair is ``LONG_SHORT``, so registering one onto a handler without both shorts flags
    raises. This is NOT quarantined: an unadmissible direction means the engine is
    misconfigured for the roster it was asked to run, which is a system-level problem the
    operator must see — not a bad row to skip past.
    """
    store = _make_store()
    try:
        pair = EthBtcPairStrategy(timeframe="1d")
        pair.name = "eth_btc"
        _seed(store, [pair])

        with pytest.raises(ValueError, match="allow_short_selling"):
            rehydrate_strategies(
                store=store,
                catalog=test_catalog(),
                strategies_handler=_make_handler(),  # both flags OFF (production default)
                alert_sink=_RecordingAlertSink(),
            )
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# D-19 — the infrastructure arm (loud)
# --------------------------------------------------------------------------------------


def test_rows_with_no_catalog_raises_infrastructure_error() -> None:
    """D-19 — rows + no catalog is a WIRING bug: fail loud, never boot with zero strategies.

    ``-k no_catalog``. This must not skip, must not degrade clean: a live engine that
    appears healthy and trades nothing is worse than one that refuses to boot.
    """
    store = _make_store()
    try:
        _seed(store, [_sma()])
        handler = _make_handler()

        with pytest.raises(RehydrateInfrastructureError):
            rehydrate_strategies(
                store=store,
                catalog=None,
                strategies_handler=handler,
                alert_sink=_RecordingAlertSink(),
            )

        assert handler.strategies == []
    finally:
        store.dispose()


def test_empty_registry_with_no_catalog_does_not_raise() -> None:
    """D-21/D-19 interaction — zero rows + no catalog: nothing to instantiate, no wiring bug.

    ``-k no_catalog``. This is the state of every existing live test, which is what makes
    construction-time rehydrate safe to land.
    """
    store = _make_store()
    try:
        handler = _make_handler()

        quarantined = rehydrate_strategies(
            store=store,
            catalog=None,
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        assert quarantined == []
        assert handler.strategies == []
    finally:
        store.dispose()


def test_unreadable_store_propagates_and_is_not_degrade_cleaned() -> None:
    """D-19 — a store failure PROPAGATES: rehydrate is not blanket-wrapped in a swallow.

    A blanket ``except`` around the whole function would invert the loud-infrastructure arm
    into exactly the silent boot-with-zero-strategies D-19 calls "worse".
    """

    class _BrokenStore:
        def read_all(self) -> list[Any]:
            raise RuntimeError("registry unreadable")

    with pytest.raises(RuntimeError, match="registry unreadable"):
        rehydrate_strategies(
            store=_BrokenStore(),
            catalog=test_catalog(),
            strategies_handler=_make_handler(),
            alert_sink=_RecordingAlertSink(),
        )


# --------------------------------------------------------------------------------------
# D-02 — duplicate-name loud reject; ephemeral strategy_id
# --------------------------------------------------------------------------------------


def test_rehydrating_twice_rejects_the_duplicate_name() -> None:
    """D-02 idempotency — a second pass rejects loudly rather than double-registering.

    A silent double-register would fan every decision out twice.
    """
    store = _make_store()
    try:
        _seed(store, [_sma()])
        handler = _make_handler()
        sink = _RecordingAlertSink()

        rehydrate_strategies(
            store=store, catalog=test_catalog(), strategies_handler=handler, alert_sink=sink
        )

        with pytest.raises(ValueError, match="sma_macd"):
            rehydrate_strategies(
                store=store,
                catalog=test_catalog(),
                strategies_handler=handler,
                alert_sink=sink,
            )
    finally:
        store.dispose()


def test_row_colliding_with_a_hand_added_strategy_rejects_naming_the_collision() -> None:
    """D-02 — a name collision would silently overwrite another instance's persisted state."""
    store = _make_store()
    try:
        _seed(store, [_sma()])
        handler = _make_handler()
        handler.add_strategy(_sma())  # same name, hand-added first

        with pytest.raises(ValueError, match="sma_macd"):
            rehydrate_strategies(
                store=store,
                catalog=test_catalog(),
                strategies_handler=handler,
                alert_sink=_RecordingAlertSink(),
            )
    finally:
        store.dispose()


def test_rehydrated_instance_mints_a_fresh_ephemeral_strategy_id() -> None:
    """D-02 — a FRESH UUIDv7 per construction; no second durable id was introduced.

    ``strategy_name`` is the only restart-stable identity: keying durability on the
    ephemeral id would corrupt rehydrate across a restart.
    """
    store = _make_store()
    try:
        original = _sma()
        _seed(store, [original])

        handler = _make_handler()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        rebuilt = handler.strategies[0]
        assert rebuilt.strategy_id != original.strategy_id
        assert UUID(str(rebuilt.strategy_id)).version == 7
        # The id appears nowhere in the durable row.
        row = store.get("sma_macd")
        assert str(original.strategy_id) not in str(row)
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# Ordering (IN-01)
# --------------------------------------------------------------------------------------


def test_registration_order_follows_read_all_name_ordering() -> None:
    """IN-01 — ``read_all()`` is ``strategy_name`` ASC, so registration order is stable.

    Registration order drives ``min_timeframe`` derivation and universe membership, so an
    unordered SELECT would make both irreproducible across runs.
    """
    store = _make_store()
    try:
        # Seeded deliberately out of alphabetical order.
        _seed(store, [_sma(name="zulu"), _empty(name="alpha"), _sma(name="mike")])

        handler = _make_handler()
        rehydrate_strategies(
            store=store,
            catalog=test_catalog(),
            strategies_handler=handler,
            alert_sink=_RecordingAlertSink(),
        )

        assert [s.name for s in handler.strategies] == ["alpha", "mike", "zulu"]
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# build_strategy — the per-row leaf (errors propagate; the caller owns quarantine)
# --------------------------------------------------------------------------------------


def test_build_strategy_propagates_decode_errors_for_the_caller_to_quarantine() -> None:
    """``build_strategy`` never swallows — ``rehydrate_strategies`` owns the D-19 decision."""
    store = _make_store()
    try:
        _seed(store, [_sma()])
        rec = store.list_active()[0]
        catalog = test_catalog()

        # Sanity: the well-formed row builds.
        assert type(build_strategy(rec, catalog=catalog, policy_registry=None)) is SMAMACDStrategy

        bad_type = dict(rec)
        bad_type["strategy_type"] = "RetiredStrategy"
        with pytest.raises(UnknownStrategyTypeError):
            build_strategy(bad_type, catalog=catalog, policy_registry=None)

        bad_param = dict(rec)
        bad_param["config"] = {**rec["config"], "removed_knob": 7}
        with pytest.raises(UnknownParamError):
            build_strategy(bad_param, catalog=catalog, policy_registry=None)

        bad_blob = dict(rec)
        bad_blob["config"] = {**rec["config"], "config_version": 999}
        with pytest.raises(StrategyConfigError):
            build_strategy(bad_blob, catalog=catalog, policy_registry=None)
    finally:
        store.dispose()
