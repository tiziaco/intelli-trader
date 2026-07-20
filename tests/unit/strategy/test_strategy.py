"""Intent-contract tests for the pure-alpha Strategy ABC (07-04, D-12/D-22/M5-09).

The strategy is a pure function: ``generate_signal(ticker, bars) ->
SignalIntent | None`` — no queue, no event construction, no portfolio
knowledge. The handler (``StrategiesHandler.on_bar``) owns
stamping, policy attachment, per-portfolio fan-out, and enqueueing.

Covered behaviors:

- pure-function tests on ``SMA_MACD_strategy.generate_signal`` with
  hand-engineered synthetic OHLC frames (D-22): a bullish SMA/MACD
  crossover returns ``SignalIntent(action=Side.BUY)``; a too-short frame
  returns ``None``.
- handler-side fan-out: one subscribed portfolio -> exactly one
  ``SignalEvent`` stamped from the bar event; two portfolios -> two events.
- the D-08 registration guard: ``add_strategy`` rejects a LONG_SHORT
  strategy loudly (margin milestone required).
- the WR-12 sparse-ticker guard: a missing bar for the ticker produces no
  signal and no raise.
"""

from datetime import datetime, UTC
from decimal import Decimal
from queue import Queue

import numpy as np
import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import OrderType, Side
from itrader.core.money import to_money
from itrader.core.sizing import (
    FractionOfCash,
    SignalIntent,
    TradingDirection,
)
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler


_TICKER = "BTCUSDT"
_PORTFOLIO_A = 1
_PORTFOLIO_B = 2
# Midnight-aligned, tz-aware 1d tick: the check_timeframe seam is
# midnight-relative on the UTC grid and expects tz-aware times (D-06).
_EVENT_TIME = datetime(2024, 1, 2, tzinfo=UTC)


def _sma_kwargs() -> dict:
    """The golden SMA_MACD construction kwargs used across the pure-function tests.

    Migrated from the deleted pydantic config (D-05, no shim) — the **kwargs
    surface passes every param straight through to the base engine, byte-exact
    (``FractionOfCash(Decimal("0.95"))`` string-path verbatim).
    """
    return dict(
        timeframe="1d",
        tickers=[_TICKER],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )


# --- synthetic frames (D-22: hand-engineered, construction documented) -------


def _bullish_crossover_frame() -> pd.DataFrame:
    """A 120-bar daily close frame engineered for the SMA_MACD BUY trigger.

    Construction (verified numerically against the ta library):

    - a steady linear uptrend (100 -> 220 over 120 bars) keeps the short
      SMA (50) above the long SMA (100) at the last bar — the trend filter
      passes;
    - a shallow dip over the last ~8 bars (−14 linear) drives the MACD
      histogram (6/12/3) negative at bar -2;
    - a sharp +30 bounce on the final bar flips the histogram back >= 0 at
      bar -1 — the (hist[-1] >= 0 and hist[-2] < 0) bullish crossover.
    """
    base = np.linspace(100.0, 220.0, 120)
    prices = base.copy()
    prices[-9:-1] = prices[-9] - np.linspace(0, 14, 8)  # the dip
    prices[-1] = prices[-2] + 30  # the bounce that crosses the histogram
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"close": prices}, index=idx)


def _short_frame() -> pd.DataFrame:
    """A frame shorter than SMA_MACD's max_window (100) — must return None."""
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame({"close": np.linspace(100.0, 110.0, 10)}, index=idx)


# --- pure-function intent tests (D-22) ---------------------------------------


def test_bullish_crossover_returns_buy_intent():
    """A synthetic bullish SMA/MACD crossover frame yields a BUY SignalIntent."""
    strategy = SMAMACDStrategy(**_sma_kwargs())

    # Go through the evaluate() seam (D-06): it stashes self.bars/self.now and
    # repopulates the handles, which generate_signal(ticker) now reads.
    intent = strategy.evaluate(_TICKER, _bullish_crossover_frame())

    assert isinstance(intent, SignalIntent)
    assert intent.action is Side.BUY
    assert intent.ticker == _TICKER
    # No explicit SL/TP declared by SMA_MACD — the handler stamps the
    # legacy to_money(0) defaults at SignalEvent construction.
    assert intent.stop_loss is None
    assert intent.take_profit is None
    # Full exit is the structural default (D-07).
    assert intent.exit_fraction == Decimal("1")


def test_too_short_window_short_circuits_in_handler(handler_env):
    """D-15: a window shorter than the strategy's warmup is gated by the handler.

    The in-strategy ``if len(bars) < self.max_window: return None`` guard was
    removed from SMA_MACD and relocated to the framework short-circuit in
    ``StrategiesHandler.on_bar`` (guarding on ``strategy.warmup``).
    A too-short window therefore means the handler skips ``generate_signal``
    entirely — no SignalEvent is emitted (the byte-exact firing-tick behavior
    the old guard produced, HARD-04).
    """
    handler, q = handler_env  # the stub feed returns the 10-bar _short_frame()
    strategy = SMAMACDStrategy(**_sma_kwargs())  # warmup == 100
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)

    handler.on_bar(_bar_event())

    assert q.empty()  # warmup short-circuit fired — no signal


def test_golden_declarations_are_typed():
    """SMA_MACD declares the golden typed policy (D-03/D-08/D-10)."""
    strategy = SMAMACDStrategy(**_sma_kwargs())

    assert strategy.sizing_policy == FractionOfCash(Decimal("0.95"))
    assert strategy.direction is TradingDirection.LONG_ONLY
    assert strategy.allow_increase is False


def test_auto_derived_warmup_equals_max_window_100():
    """D-08 / Pitfall 3: the base auto-derives warmup == max_window == 100.

    The hand-set ``max_window: int = 100`` / ``warmup: int = 100`` class attrs
    were DELETED from SMAMACDStrategy; the post-init() pass derives both from the
    declared handles' min_period: ``max(SMA50->50, SMA100->100, MACDHist->15)``
    == 100. This is the HARD byte-exact anchor — drift here drifts the oracle off
    46189.87730727451. Selectable with ``-k warmup``.
    """
    strategy = SMAMACDStrategy(**_sma_kwargs())

    assert strategy.warmup == strategy.max_window == 100


def test_buy_sell_sugar_builds_intents():
    """buy()/sell() are thin sugar: SignalIntent only, to_money entry for SL/TP."""
    strategy = SMAMACDStrategy(**_sma_kwargs())

    buy = strategy.buy(_TICKER, sl=40.5, tp=50.25)
    sell = strategy.sell(_TICKER)

    assert buy.action is Side.BUY
    # D-04 string path: to_money(40.5) == Decimal("40.5"), no float artifact.
    assert buy.stop_loss == to_money(40.5)
    assert buy.take_profit == to_money(50.25)
    assert sell.action is Side.SELL
    assert sell.stop_loss is None and sell.take_profit is None


def test_validate_short_lt_long_rejection():
    """validate() rejects short_window >= long_window (HARD-02, D-09).

    Migrated from the pydantic ``test_short_window_ge_long_window_raises``:
    the cross-field rule now lives in the ``validate()`` hook and raises a
    plain ``ValueError`` (not a pydantic ``ValidationError``).
    """
    kwargs = _sma_kwargs()
    kwargs.update(short_window=100, long_window=50)
    with pytest.raises(ValueError, match="short_window must be < long_window"):
        SMAMACDStrategy(**kwargs)


def test_init_is_idempotent():
    """D-11: calling init() again leaves identical state (to_dict() ==)."""
    strategy = SMAMACDStrategy(**_sma_kwargs())

    before = strategy.to_dict()
    strategy.init()
    after = strategy.to_dict()

    assert before == after


def test_to_dict_is_json_serializable():
    """WR-04: to_dict() honours the documented json.dumps(...) contract.

    to_dict() exists to capture the FULL declared surface via introspection;
    its IN-03 docstring cites ``json.dumps(strategy.to_dict())`` as the
    serialization-edge contract. The generic introspection loop now coerces any
    non-JSON-native declared value to repr() at the edge, so the snapshot stays
    round-trippable regardless of the declared attr's type. Regression-lock it.
    """
    import json

    strategy = SMAMACDStrategy(**_sma_kwargs())

    # Must not raise "Object of type ... is not JSON serializable".
    dumped = json.dumps(strategy.to_dict())
    assert isinstance(dumped, str)


def test_to_dict_json_safe_for_nested_non_native_containers():
    """WR-01 (iter-2): json.dumps(to_dict()) survives nested non-native leaves.

    The original WR-04 fix only repr-coerced a SCALAR non-native value and
    classified a top-level ``list``/``dict`` as native by container type alone.
    A declared attr holding a ``list[Decimal]`` / ``dict[str, datetime]`` thus
    slipped past the gate and ``json.dumps(to_dict())`` still raised
    ``TypeError: Object of type Decimal/datetime is not JSON serializable``.
    The recursive ``_json_safe`` walk repr-coerces the offending LEAVES, so the
    contract is structural. Lock the nested case with a synthetic strategy that
    declares a ``list``-of-``Decimal`` and a ``dict``-of-``datetime`` attr.
    """
    import json

    class _NestedDeclaredStrategy(Strategy):
        # Declared (annotated) attrs whose CONTENTS are non-JSON-native — these
        # are exactly the case the top-level-container check missed.
        decimal_levels: list[Decimal] = [Decimal("1.5"), Decimal("2.5")]
        dated_map: dict[str, datetime] = {"start": datetime(2024, 1, 1, tzinfo=UTC)}

        def generate_signal(self, ticker: str):
            return None

    kwargs = _sma_kwargs()
    # Carry over only the required base params; drop SMA-specific knobs the
    # synthetic strategy does not declare (would raise UnknownParamError).
    strategy = _NestedDeclaredStrategy(
        timeframe=kwargs["timeframe"],
        tickers=kwargs["tickers"],
        sizing_policy=kwargs["sizing_policy"],
    )

    snapshot = strategy.to_dict()
    # The declared nested attrs are present and recursively repr-coerced.
    assert snapshot["decimal_levels"] == [repr(Decimal("1.5")), repr(Decimal("2.5"))]
    assert snapshot["dated_map"] == {"start": repr(datetime(2024, 1, 1, tzinfo=UTC))}

    # The whole snapshot must round-trip through json without raising.
    dumped = json.dumps(snapshot)
    assert isinstance(dumped, str)


def test_to_dict_snapshot_regression_full_surface():
    """D-07 (PERF-04): full to_dict snapshot is byte-identical after the cache swap.

    PERF-04 routed to_dict's ``get_type_hints(type(self))`` walk through the
    memoized ``_declared_hints`` helper. Because it is the SAME function (cached),
    the snapshot's keys + order + values are byte-identical by construction. The
    equivalence test locks the resolution; THIS test locks the full serialized
    snapshot end-to-end so any drift in the declared-surface introspection (key
    set, order, or a bespoke-serialization regression) fails loudly. ``strategy_id``
    is a per-run UUIDv7 — assert it is a stringified id, not a fixed value.
    """
    import json

    strategy = SMAMACDStrategy(**_sma_kwargs())
    snapshot = strategy.to_dict()

    # Full declared-surface key set + order (the property the cached helper must
    # preserve byte-exact). Introspected declared knobs come first (annotation
    # order across the MRO), then the identity/runtime fields appended by update().
    assert list(snapshot.keys()) == [
        "tickers",
        "sizing_policy",
        "direction",
        "allow_increase",
        "max_positions",
        "sltp_policy",
        "max_window",
        "warmup",
        "short_window",
        "long_window",
        "fast_window",
        "slow_window",
        "signal_window",
        "strategy_id",
        "strategy_name",
        "timeframe_alias",
        "subscribed_portfolios",
        "is_active",
    ]

    # Declared-surface values (the introspected snapshot the memoized helper feeds).
    assert snapshot["tickers"] == [_TICKER]
    assert snapshot["sizing_policy"] == repr(FractionOfCash(Decimal("0.95")))
    assert snapshot["direction"] == TradingDirection.LONG_ONLY.value
    assert snapshot["allow_increase"] is False
    assert snapshot["max_positions"] == 1
    assert snapshot["sltp_policy"] is None
    assert snapshot["max_window"] == 100
    assert snapshot["warmup"] == 100
    assert snapshot["short_window"] == 50
    assert snapshot["long_window"] == 100
    assert snapshot["fast_window"] == 6
    assert snapshot["slow_window"] == 12
    assert snapshot["signal_window"] == 3

    # Bespoke identity/runtime fields.
    assert snapshot["strategy_name"] == "SMA_MACD"
    assert snapshot["timeframe_alias"] == "1d"
    assert snapshot["subscribed_portfolios"] == []
    assert snapshot["is_active"] is True
    # strategy_id is a per-run UUIDv7 stringified at the serialization edge.
    assert isinstance(snapshot["strategy_id"], str)
    assert snapshot["strategy_id"] == str(strategy.strategy_id)

    # The full snapshot still round-trips through json (serialization contract).
    assert isinstance(json.dumps(snapshot), str)


def test_reconfigure_reapplies_and_revalidates():
    """D-12: reconfigure(**kwargs) re-applies + re-validates + preserves timeframe."""
    strategy = SMAMACDStrategy(**_sma_kwargs())
    prior_timeframe = strategy.timeframe
    prior_alias = strategy.timeframe_alias

    strategy.reconfigure(short_window=30)

    # The kwarg was re-applied.
    assert strategy.short_window == 30
    # validate() re-ran (30 < 100 holds, no raise) and the prior timeframe is
    # preserved (no timeframe kwarg supplied — falls back to the prior enum).
    assert strategy.timeframe == prior_timeframe
    assert strategy.timeframe_alias == prior_alias

    # A reconfigure that violates the cross-field rule re-raises through validate().
    with pytest.raises(ValueError, match="short_window must be < long_window"):
        strategy.reconfigure(short_window=200)


def test_reconfigure_omitted_field_keeps_prior_not_default():
    """WR-04: an OMITTED kwarg on reconfigure keeps the PRIOR value, not the default.

    RESEARCH Open Question 1 — the fallback is asymmetric: an explicitly-supplied
    kwarg overrides, but OMISSION freezes the last value and never resets to the
    class default. There is no way through an omitted kwarg to clear an optional
    field back to its default; the caller must pass it explicitly (e.g.
    ``reconfigure(sltp_policy=None)``). This pins that footgun so a future author
    who expects "omitted == default" sees it documented and tested.
    """
    strategy = SMAMACDStrategy(**_sma_kwargs())
    # The class default for short_window is NOT 30 — supply 30, then reconfigure
    # WITHOUT it: the prior 30 must survive (not snap back to the class default).
    strategy.reconfigure(short_window=30)
    assert strategy.short_window == 30

    # Omit short_window entirely — change an unrelated field instead.
    strategy.reconfigure(allow_increase=True)

    # Omission keeps the PRIOR value (30), it is NOT reset to the class default.
    assert strategy.short_window == 30
    assert strategy.allow_increase is True

    # Resettability is only available via an EXPLICIT kwarg (the documented path).
    default_short = type(strategy).short_window
    strategy.reconfigure(short_window=default_short)
    assert strategy.short_window == default_short


# --- handler-side fan-out (real StrategiesHandler + queue + stub feed) -------


class _AlwaysBuyStrategy(Strategy):
    """Minimal concrete strategy that always signals BUY (fan-out probe)."""

    name = "always_buy"
    # max_window wide enough for the stub frame; warmup stays 0 (no gating)
    # so the handler always reaches generate_signal in the fan-out tests.
    max_window: int = 1

    def __init__(
        self,
        direction: TradingDirection = TradingDirection.LONG_ONLY,
    ) -> None:
        # D-05: pass params straight through to the **kwargs surface (no shim).
        # Only the direction varies across the fan-out / registration-guard tests.
        super().__init__(
            timeframe="1d",
            tickers=[_TICKER],
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=direction,
        )

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return self.buy(ticker)


class _StubFeed:
    """BarFeed stand-in whose window() returns a fixed synthetic frame."""

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def window(self, ticker, timeframe, max_window, asof) -> pd.DataFrame:
        return self._frame


def _bar_event(time=_EVENT_TIME, ticker=_TICKER) -> BarEvent:
    return BarEvent(time=time, bars={
        ticker: Bar(time=time, open=Decimal("100"), high=Decimal("110"),
                    low=Decimal("90"), close=Decimal("105"), volume=Decimal("1000")),
    })


@pytest.fixture
def handler_env():
    """A real StrategiesHandler wired to a queue and a stub feed.

    Drains the queue on teardown (test_on_signal.py precedent) so nothing
    bleeds across tests under ``filterwarnings=["error"]``.
    """
    q = Queue()
    # Plan 05-03: the handler now requires an injected signal store (sink).
    handler = StrategiesHandler(q, _StubFeed(_short_frame()), InMemorySignalStore())

    yield handler, q

    while not q.empty():
        q.get_nowait()


def test_fan_out_single_portfolio_stamps_event(handler_env):
    """One subscribed portfolio -> exactly one SignalEvent, stamped handler-side."""
    handler, q = handler_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)
    event = _bar_event()

    handler.on_bar(event)

    signal: SignalEvent = q.get(False)
    assert q.empty()  # exactly one
    assert isinstance(signal, SignalEvent)
    # The handler stamps time/price from the bar event (relocated construction).
    assert signal.time == event.time
    assert signal.price == to_money(event.bars[_TICKER].close)
    # Absent SL/TP preserves the legacy default exactly: to_money(0).
    assert signal.stop_loss == Decimal("0")
    assert signal.take_profit == Decimal("0")
    # Typed policy/direction attached from the strategy object (D-01).
    assert signal.sizing_policy == FractionOfCash(Decimal("0.95"))
    assert signal.direction is TradingDirection.LONG_ONLY
    assert signal.allow_increase is False
    assert signal.exit_fraction == Decimal("1")
    assert signal.action is Side.BUY
    # HARD-03 / D-04: order_type is an OrderType enum end-to-end (no stringly
    # typed seam) — assert the type, not just the value.
    assert isinstance(signal.order_type, OrderType)
    assert signal.order_type is OrderType.MARKET
    assert signal.ticker == _TICKER
    assert signal.portfolio_id == _PORTFOLIO_A
    assert signal.strategy_id == strategy.strategy_id
    # The order/risk layer sizes the signal (D-10) — quantity stays None.
    assert signal.quantity is None


def test_fan_out_two_portfolios_two_events(handler_env):
    """Two subscribed portfolios -> two SignalEvents (fan-out preserved)."""
    handler, q = handler_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    strategy.subscribe_portfolio(_PORTFOLIO_B)
    handler.add_strategy(strategy)

    handler.on_bar(_bar_event())

    signals = []
    while not q.empty():
        signals.append(q.get(False))
    assert len(signals) == 2
    assert [s.portfolio_id for s in signals] == [_PORTFOLIO_A, _PORTFOLIO_B]
    # Same intent fanned out — identical stamping on both events.
    assert {s.action for s in signals} == {Side.BUY}
    assert {s.strategy_id for s in signals} == {strategy.strategy_id}


def test_sparse_ticker_guard_skips_silently(handler_env):
    """WR-12: a bar missing for the ticker -> no signal, no raise."""
    handler, q = handler_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)
    # The bar event carries a DIFFERENT ticker — the strategy's is absent.
    event = _bar_event(ticker="ETHUSDT")

    handler.on_bar(event)  # must not raise

    assert q.empty()


def test_long_short_registration_rejected(handler_env):
    """SHORT-01/D-07: a LONG_SHORT strategy is rejected when the flags default off.

    ``handler_env`` constructs the handler with both shorts-enabling flags off,
    so a non-LONG_ONLY strategy is rejected loudly naming both required flags.
    """
    handler, _q = handler_env
    strategy = _AlwaysBuyStrategy(direction=TradingDirection.LONG_SHORT)

    with pytest.raises(
        ValueError, match="allow_short_selling AND enable_margin"
    ):
        handler.add_strategy(strategy)

    assert handler.strategies == []


def test_short_only_registration_rejected(handler_env):
    """SHORT-01/D-07: a SHORT_ONLY strategy is rejected when the flags default off.

    With both flags off (the byte-exact default) registration rejects the
    capability loudly naming both required flags. SHORT_ONLY has no cover arm in
    ``_resolve_signal_quantity`` until the margin model is wired on, so the door
    stays closed unless ``allow_short_selling`` AND ``enable_margin`` are both on.
    """
    handler, _q = handler_env
    strategy = _AlwaysBuyStrategy(direction=TradingDirection.SHORT_ONLY)

    with pytest.raises(
        ValueError, match="allow_short_selling AND enable_margin"
    ):
        handler.add_strategy(strategy)

    assert handler.strategies == []


# --- Finding A: leverage survives the strategy -> SignalEvent fan-out (LEV-03) ---


class _LeverageStrategy(Strategy):
    """A minimal strategy that returns a hand-built BUY intent carrying an
    explicit ``leverage`` so the fan-out's leverage plumbing is exercised."""

    name = "lev_intent"
    max_window: int = 1

    def __init__(self, leverage: Decimal) -> None:
        self._leverage = leverage
        super().__init__(
            timeframe="1d",
            tickers=[_TICKER],
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
        )

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return SignalIntent(
            ticker=ticker,
            action=Side.BUY,
            order_type=OrderType.MARKET,
            leverage=self._leverage,
        )


def test_fan_out_carries_declared_leverage(handler_env):
    """Finding A (LEV-03): a strategy-declared leverage reaches the SignalEvent.

    A SignalIntent with leverage=Decimal("3") must fan out onto a SignalEvent
    carrying leverage == Decimal("3") — the field is no longer dropped.
    """
    handler, q = handler_env
    strategy = _LeverageStrategy(leverage=Decimal("3"))
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)

    handler.on_bar(_bar_event())

    signal: SignalEvent = q.get(False)
    assert q.empty()
    assert signal.leverage == Decimal("3")


def test_fan_out_default_leverage_stays_one(handler_env):
    """The default intent leverage Decimal("1") yields a Decimal("1") SignalEvent
    (oracle-dark — the spot fan-out is byte-exact)."""
    handler, q = handler_env
    strategy = _LeverageStrategy(leverage=Decimal("1"))
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)

    handler.on_bar(_bar_event())

    signal: SignalEvent = q.get(False)
    assert q.empty()
    assert signal.leverage == Decimal("1")
