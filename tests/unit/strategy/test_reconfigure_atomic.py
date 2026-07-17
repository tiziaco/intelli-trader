"""D-12/D-13/D-14/P-4 atomic reconfiguration — trial-validate, persist, apply, re-warm.

The STRAT-03 atomicity contract. ``reconfigure`` trial-validates the FULL merged config on a
THROWAWAY instance BEFORE the live instance is touched, so a cross-field ``validate()`` failure
never leaves a live, trading strategy mutated into a state its own validator rejects (**D-13**).
The persisted blob is the trial's FULL post-merge authoring set, never the partial delta
(**P-4**). Open positions are KEPT — no force-flat (**D-12**).

**D-14 — CODE REALITY over the plan text.** ``Strategy.reconfigure`` -> ``_run_init``
UNCONDITIONALLY resets the per-symbol handle state (``base.py:409/426``), so an applied
reconfigure of a handle-bearing strategy goes DARK and re-warms through the WD-2 seam
(``mark_unwarm`` + ``_request_rewarm`` + the follow-on poll) — the SAME warm path
``enable``/``add`` use (WD-1: one warm path). The plan's "shrank/unchanged stays warm" premise
is FALSE against the live tree (verified: ``is_ready`` is ``False`` after any reconfigure);
preserving warmth would need a conditional ``_run_init`` on the base HOT PATH (oracle risk),
deferred. An IDENTICAL or EMPTY payload is a genuine no-op (nothing merges) and stays warm.

Assertions read STATE and the STORE, never log capture (``make test`` exports
``ITRADER_DISABLE_LOGS=true``, so a log-capture assertion would false-green). 4-space
indentation (matches the sibling ``on_strategy_command`` suites). NO ``__init__.py`` in this dir.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Iterator

import pandas as pd
import pytest

from itrader.config.sql import SqlSettings
from itrader.core.bar import Bar
from itrader.core.enums import TradingDirection
from itrader.core.sizing import PercentFromDecision
from itrader.events_handler.events import (
    ErrorEvent,
    StrategyCommandEvent,
    UniversePollEvent,
)
from itrader.core.enums.severity import ErrorSeverity
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.registry import encode_strategy_config
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from tests.support.schema import provision_schema
from tests.support.strategy_catalog import test_catalog

pytestmark = pytest.mark.unit

_T = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TICKER = "BTCUSD"
_NAME = "SMA_MACD"


class _StubFeed:
    """A minimal ``BarFeed`` stand-in with NO ``base_timeframe`` (backtest shape).

    Having no ``base_timeframe`` makes the reconfigure warmability gate skip cleanly — the
    atomic tests never exercise the timeframe arm (that is ``test_reconfigure_allowlist.py``).
    """

    def symbols(self) -> list[str]:
        return [_TICKER]

    def window(self, ticker, timeframe, max_window, asof):  # type: ignore[no-untyped-def]
        return pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], tz="UTC"),
        )


class _RaisingStore:
    """A registry store whose ``upsert`` raises — the D-13 persist-fail double."""

    def __init__(self) -> None:
        self.upsert_calls = 0

    def upsert(self, **kwargs: Any) -> None:
        self.upsert_calls += 1
        raise RuntimeError("simulated store failure")

    def get(self, strategy_name: str) -> None:
        return None


@pytest.fixture()
def store() -> Iterator[StrategyRegistryStore]:
    registry = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
    provision_schema(registry.backend)
    try:
        yield registry
    finally:
        registry.dispose()


def _bar(price: float, *, offset: int = 0) -> Bar:
    stamp = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
    return Bar(
        time=stamp,
        open=Decimal(str(price)),
        high=Decimal(str(price)),
        low=Decimal(str(price)),
        close=Decimal(str(price)),
        volume=Decimal("1"),
    )


def _warm(strategy: SMAMACDStrategy, ticker: str = _TICKER, n: int = 105) -> None:
    for i in range(n):
        strategy.update(ticker, _bar(100 + i, offset=i))


def _handler(
    registry: Any,
    *,
    allow_short: bool = False,
    margin: bool = False,
    sltp: Any = None,
) -> tuple[StrategiesHandler, SMAMACDStrategy]:
    handler = StrategiesHandler(
        Queue(), _StubFeed(), InMemorySignalStore(),
        allow_short_selling=allow_short, enable_margin=margin)
    handler.registry_store = registry
    handler.strategy_catalog = test_catalog()
    kwargs: dict[str, Any] = {"timeframe": "1d", "tickers": [_TICKER]}
    if sltp is not None:
        kwargs["sltp_policy"] = sltp
    strategy = SMAMACDStrategy(**kwargs)
    handler.add_strategy(strategy)
    return handler, strategy


def _reconfigure(handler: StrategiesHandler, config: dict[str, Any]) -> None:
    handler.on_strategy_command(
        StrategyCommandEvent.reconfigure(strategy_name=_NAME, config=config, time=_T))


def _drain(queue: "Queue[Any]") -> list[Any]:
    drained = []
    while not queue.empty():
        drained.append(queue.get(False))
    return drained


# --- the RED driver + D-13 tear-freedom ------------------------------------

def test_valid_reconfigure_applies_live_and_persists_the_full_set(
    store: StrategyRegistryStore,
) -> None:
    """A valid delta APPLIES to the live instance and persists (drives RED against the no-op)."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"long_window": 120})

    assert strategy.long_window == 120, "the delta must reach the live instance"
    row = store.get(_NAME)
    assert row is not None
    assert row["config"]["long_window"] == 120


def test_a_failing_validate_leaves_the_live_strategy_untorn(
    store: StrategyRegistryStore,
) -> None:
    """Test 1 (D-13) — a delta that passes _apply_params but FAILS cross-field validate().

    ``short_window=200`` with ``long_window=100`` passes ``_apply_params`` (200 is a valid
    int) but violates SMA_MACD's ``short_window < long_window``. The trial construction raises
    HERE, against a throwaway, so the LIVE instance is never mutated — no tear.
    """
    handler, strategy = _handler(store)
    _warm(strategy)
    before = encode_strategy_config(strategy)

    _reconfigure(handler, {"short_window": 200})

    assert strategy.short_window == 50, "the live instance must NOT be torn"
    assert encode_strategy_config(strategy) == before
    assert store.get(_NAME) is None, "a rejected reconfigure persists nothing"


def test_persist_failure_leaves_the_live_instance_unchanged() -> None:
    """Test 2 (D-13) — a persist failure never diverges the DB from the live instance.

    Persist precedes apply, so a persist failure propagates (the _add_strategy_verb / D-19
    infrastructure-fails-loud precedent) with the LIVE instance untouched — the DB and live
    never diverge in the applied-but-unpersisted direction.
    """
    raising = _RaisingStore()
    handler, strategy = _handler(raising)
    _warm(strategy)

    with pytest.raises(RuntimeError):
        _reconfigure(handler, {"long_window": 120})

    assert raising.upsert_calls == 1
    assert strategy.long_window == 100, "persist precedes apply — live is untouched"


def test_apply_failure_after_persist_alerts_critical_and_db_holds_new(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 3 (D-13) — persist OK + apply throws -> CRITICAL, DB correct, restart heals."""
    handler, strategy = _handler(store)
    _warm(strategy)

    def _boom(**kwargs: Any) -> None:
        raise ValueError("simulated apply failure")

    monkeypatch.setattr(strategy, "reconfigure", _boom)

    _reconfigure(handler, {"long_window": 120})

    row = store.get(_NAME)
    assert row is not None
    assert row["config"]["long_window"] == 120, "persist happened before apply — DB holds NEW"
    assert strategy.long_window == 100, "apply threw — the live instance is unmodified"
    criticals = [
        e for e in _drain(handler.global_queue)
        if isinstance(e, ErrorEvent) and e.severity is ErrorSeverity.CRITICAL
    ]
    assert criticals, "an apply-after-persist failure must alert CRITICAL"
    # T-10-58 declared-fields-only: the alert binds strategy_name + error KIND, never values.
    assert criticals[0].details is not None
    assert criticals[0].details.get("strategy_name") == _NAME


# --- P-4 merge semantics ---------------------------------------------------

def test_partial_payload_merges_and_persists_the_full_set_merge(
    store: StrategyRegistryStore,
) -> None:
    """Test 4 (P-4) — an omitted field keeps its prior instance value; persist is the full set."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"long_window": 130})

    assert strategy.long_window == 130
    assert strategy.short_window == 50, "an omitted field keeps its prior instance value"
    row = store.get(_NAME)
    assert row is not None
    # The persisted blob is the FULL post-merge authoring set, not the one-field delta.
    assert row["config"] == encode_strategy_config(strategy)
    assert row["config"]["short_window"] == 50


def test_explicit_none_resets_where_omission_merges(
    store: StrategyRegistryStore,
) -> None:
    """Test 5 (P-4) — an EXPLICIT ``sltp_policy=None`` resets it; only omission merges."""
    sltp = PercentFromDecision(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.1"))
    handler, strategy = _handler(store, sltp=sltp)
    _warm(strategy)
    assert strategy.sltp_policy is not None

    _reconfigure(handler, {"sltp_policy": None})

    assert strategy.sltp_policy is None, "an explicitly-passed None overrides"


# --- D-14 re-warm (CODE REALITY: every applied reconfigure goes dark) -------

def test_reconfigure_config_change_goes_dark_and_rewarms(
    store: StrategyRegistryStore,
) -> None:
    """Test 6 (D-14) — an applied reconfigure resets handle state -> DARK -> re-warm seam."""
    handler, strategy = _handler(store)
    _warm(strategy)
    assert strategy.is_ready(_TICKER) is True

    _reconfigure(handler, {"max_positions": 3})

    assert strategy.max_positions == 3
    assert strategy.is_ready(_TICKER) is False, (
        "Strategy.reconfigure -> _run_init resets handle state: the instance goes dark")


def test_reconfigure_window_grow_goes_dark_and_rewarms(
    store: StrategyRegistryStore,
) -> None:
    """Test 7 (D-14) — a window grow past what is buffered goes dark and drives the re-warm."""
    handler, strategy = _handler(store)
    _warm(strategy)
    assert strategy.is_ready(_TICKER) is True

    _reconfigure(handler, {"long_window": 150})

    assert strategy.long_window == 150
    assert strategy.is_ready(_TICKER) is False


def test_reconfigure_rewarm_seam_emits_poll_and_darkens_warm(
    store: StrategyRegistryStore,
) -> None:
    """Test 8 (D-14/WD-2) — the applied reconfigure emits the follow-on poll (re-warm ride)."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"short_window": 40})

    assert strategy.short_window == 40
    assert strategy.is_ready(_TICKER) is False
    polls = [e for e in _drain(handler.global_queue) if isinstance(e, UniversePollEvent)]
    assert polls, "a real reconfigure emits a UniversePollEvent so the CR-02 retry re-warms"


# --- D-13 idempotency / empty (genuine no-ops, stay warm) ------------------

def test_idempotent_reconfigure_does_not_go_dark_or_churn(
    store: StrategyRegistryStore,
) -> None:
    """Test 9 (D-13) — identical params merge to an identical blob: no-op, warm, no churn."""
    handler, strategy = _handler(store)
    _warm(strategy)
    assert strategy.is_ready(_TICKER) is True

    _reconfigure(handler, {"long_window": 100})  # already 100

    assert store.get(_NAME) is None, "an idempotent no-op must not persist"
    assert _drain(handler.global_queue) == [], "an idempotent no-op must not emit a poll"
    assert strategy.is_ready(_TICKER) is True, "an idempotent no-op must not go dark"


def test_empty_payload_is_a_no_op(store: StrategyRegistryStore) -> None:
    """Test 10 (D-13) — an empty ``config`` mutates nothing, persists nothing, stays warm."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {})

    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []
    assert strategy.is_ready(_TICKER) is True


# --- D-12 no force-flat -----------------------------------------------------

def test_reconfigure_does_not_force_flat_keeps_the_strategy_registered(
    store: StrategyRegistryStore,
) -> None:
    """Test 11 (D-12) — reconfigure never enters the remove/force-flat path."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"long_window": 120})

    assert strategy in handler.strategies
    assert _NAME not in handler._pending_removals
