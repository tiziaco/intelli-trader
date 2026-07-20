"""Isolation contract tests for ``ManagedStrategies`` — the single roster owner.

DECOMP-01 (phase 10.1, plan 02). ``ManagedStrategies`` owns ``strategies``,
``min_timeframe``, ``_pending_removals``, and the SHORT-01/D-07 two-flag
registration gate. The genuine test-surface win of the extraction is that every
roster rule below is exercised by constructing the collaborator **directly** —
no ``StrategiesHandler``, no ``EventBus``, no feed, no store.

The rules under test are behaviour-preserving code motion out of
``strategies_handler.py``; the monolith-level suites
(``test_strategies_handler_registration.py`` et al.) remain the
behaviour-preservation evidence and are untouched.

SHORT-01/D-07 — a non-``LONG_ONLY`` direction is admissible ONLY when BOTH
``allow_short_selling`` AND ``enable_margin`` are on. Both default off, so the
golden ``LONG_ONLY`` path (SMA_MACD) is unaffected and the oracle stays
byte-exact (134 / ``46189.87730727451``).

IN-06 — ``min_timeframe`` seeds to ``None`` (not a magic sentinel) and returns
to ``None`` on an empty roster.

D-11 — a name in ``_pending_removals`` stops CONTRIBUTING to the derived
universe while its instance stays in the roster.

Folder-derived ``unit`` marker only (tests/conftest.py applies it).
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.managed_strategies import ManagedStrategies
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy

pytestmark = pytest.mark.unit


class _StubLogger:
    """Records ``info`` calls so the moved ``add_strategy`` log is observable."""

    def __init__(self) -> None:
        self.infos: list[str] = []

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.infos.append(message)


def _strategy(
    direction: TradingDirection = TradingDirection.LONG_ONLY,
    *,
    name: str = "SMA_MACD",
    timeframe: str = "1d",
    tickers: list[str] | None = None,
) -> SMAMACDStrategy:
    """Construct a reference strategy carrying the requested roster attributes.

    The registration gate keys off ``strategy.direction`` alone and the roster
    rules key off ``name`` / ``timeframe`` / ``tickers`` — the concrete strategy
    class is irrelevant, SMA_MACD is reused as the proven analog.
    """
    return SMAMACDStrategy(
        timeframe=timeframe,
        tickers=tickers if tickers is not None else ["BTCUSDT"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=direction,
        allow_increase=False,
        name=name,
    )


def _managed(
    *, allow_short_selling: bool = False, enable_margin: bool = False
) -> ManagedStrategies:
    return ManagedStrategies(
        allow_short_selling=allow_short_selling,
        enable_margin=enable_margin,
        logger=_StubLogger(),
    )


# --- SHORT-01/D-07 two-flag gate ------------------------------------------


def test_direction_admissible_long_only_ignores_both_flags() -> None:
    """LONG_ONLY is admissible under every flag combination."""
    for allow, margin in ((False, False), (True, False), (False, True), (True, True)):
        managed = _managed(allow_short_selling=allow, enable_margin=margin)
        assert managed.direction_admissible(TradingDirection.LONG_ONLY) is True


@pytest.mark.parametrize(
    "allow_short_selling, enable_margin, expected",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, True),
    ],
)
def test_direction_admissible_long_short_requires_both_flags(
    allow_short_selling: bool, enable_margin: bool, expected: bool
) -> None:
    """D-07: a non-LONG_ONLY direction needs BOTH flags — all four combinations."""
    managed = _managed(
        allow_short_selling=allow_short_selling, enable_margin=enable_margin
    )

    assert (
        managed.direction_admissible(TradingDirection.LONG_SHORT) is expected
    )


def test_add_strategy_rejects_non_long_only_with_flags_off() -> None:
    """D-07: the gate raises a ValueError naming both flags."""
    managed = _managed()

    with pytest.raises(ValueError) as exc:
        managed.add_strategy(_strategy(TradingDirection.SHORT_ONLY))

    message = str(exc.value)
    assert "allow_short_selling" in message
    assert "enable_margin" in message
    assert managed.strategies == []


def test_add_strategy_admits_non_long_only_with_both_flags_on() -> None:
    """D-07: both flags on -> a LONG_SHORT strategy registers."""
    managed = _managed(allow_short_selling=True, enable_margin=True)
    strategy = _strategy(TradingDirection.LONG_SHORT)

    managed.add_strategy(strategy)

    assert strategy in managed.strategies


# --- D-02 duplicate-name reject -------------------------------------------


def test_add_strategy_rejects_duplicate_name() -> None:
    """D-02: strategy_name is the durable identity — a collision rejects loudly."""
    managed = _managed()
    managed.add_strategy(_strategy(name="alpha"))

    with pytest.raises(ValueError) as exc:
        managed.add_strategy(_strategy(name="alpha"))

    assert "alpha" in str(exc.value)
    assert len(managed.strategies) == 1


# --- IN-06 / IN-01 min_timeframe derivation --------------------------------


def test_min_timeframe_seeds_none_then_tracks_running_min() -> None:
    """IN-06: None seed; the first strategy establishes the baseline, then min()."""
    managed = _managed()
    assert managed.min_timeframe is None

    managed.add_strategy(_strategy(name="slow", timeframe="1d"))
    assert managed.min_timeframe == timedelta(days=1)

    managed.add_strategy(_strategy(name="fast", timeframe="4h"))
    assert managed.min_timeframe == timedelta(hours=4)

    # A slower late arrival does not raise the running minimum.
    managed.add_strategy(_strategy(name="slower", timeframe="1w"))
    assert managed.min_timeframe == timedelta(hours=4)


def test_recompute_min_timeframe_empty_roster_returns_to_none_seed() -> None:
    """IN-06: an EMPTY roster returns min_timeframe to the legal None seed."""
    managed = _managed()
    strategy = _strategy(name="only", timeframe="4h")
    managed.add_strategy(strategy)
    assert managed.min_timeframe == timedelta(hours=4)

    managed.remove(strategy)
    managed.recompute_min_timeframe()

    assert managed.strategies == []
    assert managed.min_timeframe is None


def test_recompute_min_timeframe_after_dropping_the_minimum() -> None:
    """IN-01: dropping the strategy AT the minimum re-derives from the roster."""
    managed = _managed()
    slow = _strategy(name="slow", timeframe="1d")
    fast = _strategy(name="fast", timeframe="4h")
    managed.add_strategy(slow)
    managed.add_strategy(fast)
    assert managed.min_timeframe == timedelta(hours=4)

    managed.remove(fast)
    managed.recompute_min_timeframe()

    assert managed.min_timeframe == timedelta(days=1)


# --- universe derivation ---------------------------------------------------


def test_get_universe_returns_deduplicated_union() -> None:
    """The derived universe is the de-duplicated union of every roster ticker."""
    managed = _managed()
    managed.add_strategy(_strategy(name="a", tickers=["BTCUSDT", "ETHUSDT"]))
    managed.add_strategy(_strategy(name="b", tickers=["ETHUSDT", "SOLUSDT"]))

    assert sorted(managed.get_universe()) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_get_universe_excludes_pending_removal_but_keeps_shared_ticker() -> None:
    """D-11: a pending name stops contributing; a SHARED ticker survives via the other."""
    managed = _managed()
    pending = _strategy(name="pending", tickers=["BTCUSDT", "ETHUSDT"])
    keeper = _strategy(name="keeper", tickers=["ETHUSDT"])
    managed.add_strategy(pending)
    managed.add_strategy(keeper)

    managed.mark_pending("pending")

    universe = managed.get_universe()
    # BTCUSDT was contributed ONLY by the pending strategy -> unmembered.
    assert "BTCUSDT" not in universe
    # ETHUSDT is shared with a non-pending strategy -> still a member.
    assert "ETHUSDT" in universe
    # The instance STAYS in the roster (its row is kept until flat).
    assert pending in managed.strategies


# --- pending-removal accessors --------------------------------------------


def test_pending_accessors_mark_discard_and_query() -> None:
    """mark_pending / is_pending / discard_pending wrap the set operations."""
    managed = _managed()

    assert managed.is_pending("alpha") is False
    managed.mark_pending("alpha")
    assert managed.is_pending("alpha") is True
    assert "alpha" in managed._pending_removals

    managed.discard_pending("alpha")
    assert managed.is_pending("alpha") is False
    # discard is idempotent — a second discard is not an error.
    managed.discard_pending("alpha")
    assert managed._pending_removals == set()


# --- by_name ---------------------------------------------------------------


def test_by_name_returns_fresh_mapping_over_current_roster() -> None:
    """by_name() replaces the three identical inline dict comprehensions."""
    managed = _managed()
    alpha = _strategy(name="alpha")
    beta = _strategy(name="beta")
    managed.add_strategy(alpha)
    managed.add_strategy(beta)

    mapping = managed.by_name()

    assert mapping == {"alpha": alpha, "beta": beta}
    # Fresh each call — mutating the returned mapping does not touch the roster.
    mapping.pop("alpha")
    assert managed.by_name() == {"alpha": alpha, "beta": beta}


# --- remove ----------------------------------------------------------------


def test_remove_is_guarded_and_mutates_in_place() -> None:
    """remove() drops a present strategy and is a no-op for an absent one."""
    managed = _managed()
    strategy = _strategy(name="alpha")
    managed.add_strategy(strategy)
    roster = managed.strategies

    managed.remove(strategy)
    assert strategy not in managed.strategies
    # Same object, mutated in place — never rebound.
    assert managed.strategies is roster

    # Removing an absent strategy is a guarded no-op, not a ValueError.
    managed.remove(strategy)
    assert managed.strategies == []


# --- same-object guarantee (oracle-adjacent; selectable with -k same_object) --


def test_strategies_is_the_same_object_across_calls_and_after_add() -> None:
    """The roster list is assigned once and mutated in place — NEVER rebound.

    21 test sites mutate the handler's ``strategies`` in place
    (``.append`` / ``.extend``), so a copy-returning accessor anywhere on this
    seam would silently neuter them. Identity must hold across calls AND across
    a mutation.
    """
    managed = _managed()
    first = managed.strategies

    assert managed.strategies is first

    managed.add_strategy(_strategy(name="alpha"))

    assert managed.strategies is first
    assert first == managed.strategies


def test_pending_removals_is_the_same_object_across_calls_and_after_mark() -> None:
    """The pending-removal set is likewise assigned once and mutated in place."""
    managed = _managed()
    first = managed._pending_removals

    managed.mark_pending("alpha")

    assert managed._pending_removals is first


# --- injected logger -------------------------------------------------------


def test_add_strategy_logs_through_the_injected_logger() -> None:
    """The log lives INSIDE the moved body so 10.1-03's repoint cannot drop it."""
    stub = _StubLogger()
    managed = ManagedStrategies(
        allow_short_selling=False, enable_margin=False, logger=stub
    )

    managed.add_strategy(_strategy(name="alpha"))

    assert any("alpha" in message for message in stub.infos)
