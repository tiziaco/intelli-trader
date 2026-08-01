"""Contract tests for the strategy-status read surface.

``StrategiesHandler.get_strategies_status()`` is where "which of my strategies are actually
trading" is answered, mirroring ``VenueAccountManager.get_accounts_status()``. It crosses
two independent facts — the registry row's ``enabled`` and whether an instance is on the
roster — and ``StrategyStatus.state`` derives the label so the two cannot disagree.

The load-bearing properties under test:

* the four labels are reachable, including the two an "is it on the roster?" read cannot
  see (QUARANTINED: row with no instance; UNTRACKED: instance with no row);
* the pair that names nothing (no row AND no instance) is REFUSED at construction rather
  than being given a lie for a label;
* registering a name CLEARS its quarantine — a name cannot be both;
* the facade no longer carries any of it.

The registry store is a plain fake with ``read_all()``: the handler reads it duck-typed, so
nothing here needs SQL.

Folder-derived ``unit`` marker only (tests/conftest.py applies it).
"""

from decimal import Decimal
from queue import Queue
from typing import Any, Mapping

import pytest

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.status import StrategyState, StrategyStatus
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit


class _StubFeed:
    """A minimal BarFeed stand-in — none of these paths touch the feed."""

    def symbols(self) -> list[str]:
        return ["BTCUSD"]


class _FakeRegistry:
    """The read-only slice the status surface uses: ``read_all()`` over seeded rows."""

    def __init__(self, rows: dict[str, bool]) -> None:
        self._rows = rows

    def read_all(self) -> list[Mapping[str, Any]]:
        return [
            {"strategy_name": name, "enabled": enabled}
            for name, enabled in self._rows.items()
        ]


def _handler(rows: "dict[str, bool] | None" = None) -> StrategiesHandler:
    """A handler over a fake registry; ``None`` rows means no durable registry at all."""
    return StrategiesHandler(
        Queue(),
        _StubFeed(),
        InMemorySignalStore(),
        registry_store=_FakeRegistry(rows) if rows is not None else None,
    )


def _strategy(name: str) -> SMAMACDStrategy:
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.5")),
    )
    strategy.name = name
    return strategy


# --------------------------------------------------------------------------------------
# StrategyStatus — the derivation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "registered", "is_active", "expected"),
    [
        (True, True, True, StrategyState.ACTIVE),
        (False, True, False, StrategyState.INACTIVE),
        (True, True, False, StrategyState.INACTIVE),
        (True, False, False, StrategyState.QUARANTINED),
        (False, False, False, StrategyState.QUARANTINED),
        (None, True, True, StrategyState.UNTRACKED),
    ],
)
def test_state_is_derived_from_the_raw_facts(
    enabled: "bool | None", registered: bool, is_active: bool, expected: StrategyState
) -> None:
    """The label follows from (row x roster) — it is never stored alongside them."""
    status = StrategyStatus(
        strategy_name="s",
        enabled=enabled,
        registered=registered,
        is_active=is_active,
    )

    assert status.state is expected


def test_no_row_and_no_instance_is_refused_rather_than_labelled() -> None:
    """The pair that names nothing has no member in the vocabulary, so it is unconstructible.

    Mirrors ``AccountStatus.__post_init__``: refusing here is what keeps ``state`` TOTAL
    instead of returning a lie for an input it cannot label.
    """
    with pytest.raises(ValueError, match="does not exist"):
        StrategyStatus(
            strategy_name="ghost", enabled=None, registered=False, is_active=False
        )


# --------------------------------------------------------------------------------------
# get_strategies_status — the handler surface
# --------------------------------------------------------------------------------------


def test_enabled_row_with_a_live_instance_is_active() -> None:
    handler = _handler({"sma": True})
    handler.add_strategy(_strategy("sma"))

    status = handler.get_strategies_status()["sma"]

    assert status.state is StrategyState.ACTIVE
    assert (status.enabled, status.registered, status.quarantine_reason) == (
        True, True, None)


def test_disabled_row_loaded_present_but_dark_is_inactive() -> None:
    """CR-01 — a disabled row is registered then deactivated; it still owns its positions."""
    handler = _handler({"sma": False})
    strategy = _strategy("sma")
    handler.add_strategy(strategy)
    strategy.deactivate_strategy()

    assert handler.get_strategies_status()["sma"].state is StrategyState.INACTIVE


def test_row_with_no_instance_is_quarantined_and_carries_the_error_kind() -> None:
    """D-19 — the row is untouched, so a quarantined strategy presents as row-without-runtime."""
    handler = _handler({"retired": True})
    handler.quarantine_strategy("retired", "UnknownStrategyTypeError")

    status = handler.get_strategies_status()["retired"]

    assert status.state is StrategyState.QUARANTINED
    # Intent intact, runtime absent — the two facts that make the row self-recovering.
    assert status.enabled is True
    assert status.quarantine_reason == "UnknownStrategyTypeError"


def test_instance_with_no_row_is_untracked() -> None:
    """The backtest shape too: no registry at all means nothing durable knows the instance."""
    handler = _handler()
    handler.add_strategy(_strategy("hand_added"))

    status = handler.get_strategies_status()["hand_added"]

    assert status.state is StrategyState.UNTRACKED
    assert status.enabled is None


def test_registering_a_quarantined_name_clears_the_quarantine() -> None:
    """A name cannot be both QUARANTINED and ACTIVE — quarantine means "no instance"."""
    handler = _handler({"sma": True})
    handler.quarantine_strategy("sma", "StrategyConfigError")

    handler.add_strategy(_strategy("sma"))

    status = handler.get_strategies_status()["sma"]
    assert status.state is StrategyState.ACTIVE
    assert status.quarantine_reason is None


def test_a_rejected_registration_leaves_the_quarantine_intact() -> None:
    """The clear happens only on a SUCCESSFUL add, so a refusal cannot erase the reason.

    The SHORT-01/D-07 gate supplies the refusal: a ``LONG_SHORT`` strategy with both
    shorts-enabling flags off never reaches the roster, so the name still has no instance
    and must still read QUARANTINED.
    """
    handler = _handler({"shorty": True})
    handler.quarantine_strategy("shorty", "StrategyConfigError")
    rejected = _strategy("shorty")
    rejected.direction = TradingDirection.LONG_SHORT

    with pytest.raises(ValueError, match="allow_short_selling"):
        handler.add_strategy(rejected)

    status = handler.get_strategies_status()["shorty"]
    assert status.state is StrategyState.QUARANTINED
    assert status.quarantine_reason == "StrategyConfigError"


def test_quarantine_for_a_deleted_row_is_dropped_not_reported() -> None:
    """With the row gone the name denotes nothing, and no status can be built for it."""
    handler = _handler({})
    handler.quarantine_strategy("deleted", "StrategyConfigError")

    assert handler.get_strategies_status() == {}


def test_the_roster_and_the_registry_are_merged_and_name_sorted() -> None:
    """One entry per known name, ordered so two reads diff without roster order leaking in."""
    handler = _handler({"beta": True, "alpha": True})
    handler.add_strategy(_strategy("zeta"))
    handler.add_strategy(_strategy("alpha"))
    handler.quarantine_strategy("beta", "StrategyConfigError")

    status = handler.get_strategies_status()

    assert list(status) == ["alpha", "beta", "zeta"]
    assert status["alpha"].state is StrategyState.ACTIVE
    assert status["beta"].state is StrategyState.QUARANTINED
    assert status["zeta"].state is StrategyState.UNTRACKED


def test_status_is_a_snapshot_not_a_live_view() -> None:
    """Frozen and rebuilt per call — a held status never silently updates itself."""
    handler = _handler({"sma": True})
    strategy = _strategy("sma")
    handler.add_strategy(strategy)
    held = handler.get_strategies_status()["sma"]

    strategy.deactivate_strategy()

    assert held.state is StrategyState.ACTIVE
    assert handler.get_strategies_status()["sma"].state is StrategyState.INACTIVE
