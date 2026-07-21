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
from itrader.core.exceptions import StrategyValidationError
from itrader.core.sizing import FractionOfCash, PercentFromDecision
from itrader.events_handler.events import (
    ErrorEvent,
    StrategyCommandEvent,
    UniversePollEvent,
)
from itrader.core.enums.severity import ErrorSeverity
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.base import Strategy
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


class _LogSpy:
    """Records ``warning``/``error`` calls so the TIER is assertable without ``caplog``.

    A DELIBERATE CLONE of the spy in ``test_strategy_command_verbs.py``, not a shared
    import: these unit dirs are package-less BY DESIGN (two same-named top-level test
    packages break full-suite collection), so a shared helper would have to move to
    ``tests/support/``. Duplicating ~15 lines is the cheaper trade.

    The module docstring bans log-capture assertions because ``make test`` exports
    ``ITRADER_DISABLE_LOGS=true``, which would false-green a ``caplog`` assertion.
    Replacing the lifecycle manager's ``logger`` object records calls deterministically
    under BOTH runners, independent of any logging configuration, while still proving
    WARNING (bad operator payload) is distinct from ERROR (a defect in our own path).
    """

    def __init__(self) -> None:
        self.warnings: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.errors: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self.warnings.append((args, kwargs))

    def error(self, *args: Any, **kwargs: Any) -> None:
        self.errors.append((args, kwargs))


_BOOM_NAME = "INIT_BOOM"
_BOOM_KINDS: dict[str, type[Exception]] = {
    "value_error": ValueError,
    "type_error": TypeError,
    "key_error": KeyError,
}


class _InitBoomStrategy(Strategy):
    """A catalog strategy whose ``init()`` raises ONLY when its ``boom`` param is armed.

    The conditional arming is what makes it usable at the reconfigure TRIAL site: the
    INITIAL construction (``boom="none"``) succeeds, so the instance registers normally;
    the reconfigure delta ``{"boom": "value_error"}`` then arms ``init()`` and the
    THROWAWAY ``cls(**params)`` raises.

    The raise stays a BARE ``ValueError``/``TypeError``/``KeyError``: ``init()`` runs
    inside ``_run_init()``, deliberately OUTSIDE the ``StrategyValidationError`` wrap in
    ``Strategy.__init__``/``Strategy.reconfigure``. That is precisely why a narrowed
    ``except StrategyAdmissionError`` cannot see it — ``init()`` is arbitrary
    user-authored ``my_strategies/`` code and the exception set escaping it is UNBOUNDED
    BY CONSTRUCTION.
    """

    name = _BOOM_NAME
    sizing_policy = FractionOfCash(Decimal("0.5"))
    boom: str = "none"

    def init(self) -> None:
        kind = _BOOM_KINDS.get(self.boom)
        if kind is None:
            return
        raise kind("arbitrary failure inside user-authored init()")

    def generate_signal(self, ticker: str) -> Any:
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


def _boom_handler(registry: Any) -> tuple[StrategiesHandler, "_InitBoomStrategy"]:
    """A handler holding a live ``_InitBoomStrategy``, with the class in the catalog.

    The catalog key must be ``type(strategy).__name__`` because that is what the
    reconfigure verb stamps into the ``rec`` it hands ``decode_strategy_config``.
    """
    handler = StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore())
    handler.registry_store = registry
    catalog = test_catalog()
    catalog[_InitBoomStrategy.__name__] = _InitBoomStrategy
    handler.strategy_catalog = catalog
    strategy = _InitBoomStrategy(timeframe="1d", tickers=[_TICKER])
    handler.add_strategy(strategy)
    return handler, strategy


def _reconfigure_named(
    handler: StrategiesHandler, name: str, config: dict[str, Any],
) -> None:
    handler.on_strategy_command(
        StrategyCommandEvent.reconfigure(strategy_name=name, config=config, time=_T))


def _reconfigure(handler: StrategiesHandler, config: dict[str, Any]) -> None:
    _reconfigure_named(handler, _NAME, config)


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
        # IN2-02 — the double must raise what the REAL collaborator raises. A validation
        # refusal escaping ``Strategy.reconfigure`` is now typed as
        # ``StrategyValidationError`` by the wrap around its _apply_params + validate()
        # span; a bare ``ValueError`` here would be a shape the production path can no
        # longer produce, and would false-fail against the narrowed APPLY-site catch.
        raise StrategyValidationError("simulated apply failure")

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


# --- D-10 zone guards: an arbitrary init() raise never escapes the verb ------
#
# `init()` is arbitrary user-authored code reached via `_run_init()`, which sits OUTSIDE
# the `StrategyValidationError` wrap — so the exception set escaping it is UNBOUNDED and
# a narrowed `except StrategyAdmissionError` cannot see a bare ValueError/TypeError/
# KeyError. An escape from `on_strategy_command` is not a mere failed command: it reaches
# ErrorPolicy.record_failure -> the failure-rate tripwire -> halt(), which has NO legal
# exit but an operator reset_halt(). The guard SHAPE follows the ZONE — zone 1 (pre-persist
# trial) refuses as a loud no-op; zone 2 (post-persist apply) routes into the designed
# CRITICAL path.

def test_trial_init_bare_value_error_is_a_loud_no_op(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ZONE 1 — a bare ``ValueError`` from ``init()`` during the TRIAL is a loud no-op."""
    handler, strategy = _boom_handler(store)
    spy = _LogSpy()
    monkeypatch.setattr(handler._lifecycle, "logger", spy)
    before = encode_strategy_config(strategy)

    _reconfigure_named(handler, _BOOM_NAME, {"boom": "value_error"})

    assert strategy.boom == "none", "the live instance must NOT be mutated"
    assert encode_strategy_config(strategy) == before
    assert store.get(_BOOM_NAME) is None, "the trial precedes the upsert — nothing persists"
    assert [e for e in _drain(handler.global_queue) if isinstance(e, ErrorEvent)] == []
    assert spy.errors, "the zone-1 tier-2 arm logs at ERROR (an unexpected kind)"


@pytest.mark.parametrize("kind", ["type_error", "key_error"])
def test_trial_init_arbitrary_exception_is_a_loud_no_op(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    """ZONE 1 — coverage that never existed: NON-``ValueError`` kinds are caught too.

    The pre-``ra5`` ``(StrategyAdmissionError, ValueError)`` tuple caught exactly ONE
    arbitrary member of an infinite set; ``TypeError``/``KeyError`` always escaped. This is
    the case that proves a zone guard beats a type tuple.
    """
    handler, strategy = _boom_handler(store)
    spy = _LogSpy()
    monkeypatch.setattr(handler._lifecycle, "logger", spy)
    before = encode_strategy_config(strategy)

    _reconfigure_named(handler, _BOOM_NAME, {"boom": kind})

    assert strategy.boom == "none"
    assert encode_strategy_config(strategy) == before
    assert store.get(_BOOM_NAME) is None
    assert [e for e in _drain(handler.global_queue) if isinstance(e, ErrorEvent)] == []
    assert spy.errors


def test_apply_init_bare_value_error_routes_to_the_critical_path(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ZONE 2 — a bare ``ValueError`` from apply routes into the designed CRITICAL path.

    Driven with the file's ESTABLISHED double idiom (monkeypatching ``reconfigure``) rather
    than a payload: the trial runs the same params FIRST and would reject them, so the apply
    arm is unreachable through the payload.
    """
    handler, strategy = _handler(store)
    _warm(strategy)

    def _boom(**kwargs: Any) -> None:
        raise ValueError("bare ValueError out of _run_init -> init()")

    monkeypatch.setattr(strategy, "reconfigure", _boom)

    _reconfigure(handler, {"long_window": 120})

    row = store.get(_NAME)
    assert row is not None
    assert row["config"]["long_window"] == 120, "D-13 — the DB HOLDS THE NEW config"
    assert strategy.long_window == 100, "apply threw — the live instance is unmodified"
    criticals = [
        e for e in _drain(handler.global_queue)
        if isinstance(e, ErrorEvent) and e.severity is ErrorSeverity.CRITICAL
    ]
    assert len(criticals) == 1
    assert criticals[0].error_type == "ValueError"
    assert criticals[0].details is not None
    assert criticals[0].details.get("strategy_name") == _NAME


@pytest.mark.parametrize("kind", [TypeError, KeyError])
def test_apply_arbitrary_exception_routes_to_the_critical_path(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch, kind: type[Exception],
) -> None:
    """ZONE 2 — arbitrary NON-``ValueError`` kinds route identically. Never an escape."""
    handler, strategy = _handler(store)
    _warm(strategy)

    def _boom(**kwargs: Any) -> None:
        raise kind("arbitrary failure out of _run_init -> init()")

    monkeypatch.setattr(strategy, "reconfigure", _boom)

    _reconfigure(handler, {"long_window": 120})

    row = store.get(_NAME)
    assert row is not None
    assert row["config"]["long_window"] == 120
    assert strategy.long_window == 100
    criticals = [
        e for e in _drain(handler.global_queue)
        if isinstance(e, ErrorEvent) and e.severity is ErrorSeverity.CRITICAL
    ]
    assert len(criticals) == 1
    assert criticals[0].error_type == kind.__name__


def test_trial_admission_error_still_takes_the_warning_tier(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ZONE 1 — tier-2 is a genuine FALLBACK, not a shadow of the tier-1 arm.

    ``short_window=200`` against ``long_window=100`` fails SMA_MACD's cross-field
    ``validate()``, which the wrap in ``Strategy.__init__`` types as
    ``StrategyValidationError`` — so it must keep taking the NARROW arm at WARNING and must
    NOT be laundered into the new ERROR tier. Clause order is what enforces this; if the
    two ever merged, operator junk would be reported as a defect in our own path.
    """
    handler, strategy = _handler(store)
    _warm(strategy)
    spy = _LogSpy()
    monkeypatch.setattr(handler._lifecycle, "logger", spy)

    _reconfigure(handler, {"short_window": 200})

    assert strategy.short_window == 50, "the live instance must NOT be torn"
    assert store.get(_NAME) is None
    assert spy.warnings, "a StrategyAdmissionError takes the tier-1 WARNING arm"
    assert spy.errors == [], "and must NOT reach the tier-2 ERROR arm"


def test_apply_store_fault_still_propagates() -> None:
    """D-19 — widening the APPLY catch does NOT swallow an infrastructure fault.

    WHY this stays loud after the zone guards land: ``registry_store.upsert`` sits OUTSIDE
    the widened ``try``, whose body is the SINGLE ``strategy.reconfigure(...)`` call and
    contains no store call. A store fault therefore still propagates out of the verb
    unchanged, exactly as the ``_add_strategy_verb`` / rehydrate fail-loud precedent
    requires. Do not widen either arm past those boundaries.
    """
    raising = _RaisingStore()
    handler, strategy = _handler(raising)
    _warm(strategy)

    with pytest.raises(RuntimeError):
        _reconfigure(handler, {"long_window": 120})

    assert raising.upsert_calls == 1
    assert strategy.long_window == 100, "persist precedes apply — live is untouched"
