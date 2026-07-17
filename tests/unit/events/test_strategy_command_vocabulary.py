"""D-08 — the full D-09 verb vocabulary on ONE ``StrategyCommandEvent`` type.

``StrategyCommandEvent`` is a ``msgspec.Struct`` (``Event, frozen=True, kw_only=True,
gc=False``), NOT the frozen ``@dataclass`` CLAUDE.md describes, and ``type`` is a
``ClassVar`` rather than a field. ``kw_only=True`` relaxes the defaults-after-non-defaults
ordering, so ``symbol`` can be demoted to ``str | None = None`` and ``config`` added as an
optional payload WITHOUT breaking any existing construction.

**D-08** — ONE control event carries every verb (no separate typed event per command
family) with one factory classmethod per verb (the ``FillEvent.new_fill`` house
convention — never construct by hand).

**D-09** — the verb set is ``add`` / ``remove`` / ``enable`` / ``disable`` /
``reconfigure`` / ``subscribe_portfolio`` / ``unsubscribe_portfolio`` plus the existing
``add_ticker`` / ``remove_ticker``. Six of the nine carry NO symbol, which is why
``strategy_name`` — the durable per-instance identity (D-02) every verb addresses — is the
sole required anchor and ``symbol`` is a ticker-verb detail.

4-space indentation. NO ``__init__.py`` in this dir.
"""

from datetime import UTC, datetime

import msgspec
import pytest

from itrader.core.enums import EventType
from itrader.events_handler.events import StrategyCommandEvent

_T = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

# The six D-09 verbs that carry NO symbol, with the factory kwargs each needs.
_SYMBOL_LESS = [
    ("add", {"strategy_type": "SMAMACDStrategy", "config": {"timeframe": "1d"}}),
    ("remove", {}),
    ("enable", {}),
    ("disable", {}),
    ("reconfigure", {"config": {"entry_z": "3"}}),
    ("subscribe_portfolio", {"portfolio_id": "p1"}),
    ("unsubscribe_portfolio", {"portfolio_id": "p1"}),
]


@pytest.mark.parametrize("verb, kwargs", _SYMBOL_LESS)
def test_each_new_factory_builds_a_complete_event(verb: str, kwargs: dict) -> None:
    """Test 1 — every new factory stamps the right verb, name and ClassVar type (D-08)."""
    event = getattr(StrategyCommandEvent, verb)(strategy_name="s1", time=_T, **kwargs)

    assert event.verb == verb
    assert event.strategy_name == "s1"
    assert event.type is EventType.STRATEGY_COMMAND
    assert event.time == _T


def test_symbol_less_verbs_need_no_sentinel() -> None:
    """Test 2 — ``enable`` carries neither a symbol nor a config (D-08)."""
    event = StrategyCommandEvent.enable(strategy_name="s1", time=_T)

    assert event.symbol is None
    assert event.config is None


def test_ticker_factories_are_unchanged() -> None:
    """Test 3 — ``add_ticker``/``remove_ticker`` still require a symbol (backward compat)."""
    added = StrategyCommandEvent.add_ticker(strategy_name="s1", symbol="BTCUSD", time=_T)
    removed = StrategyCommandEvent.remove_ticker(
        strategy_name="s1", symbol="BTCUSD", time=_T)

    assert (added.verb, added.symbol, added.config) == ("add_ticker", "BTCUSD", None)
    assert (removed.verb, removed.symbol) == ("remove_ticker", "BTCUSD")


def test_add_and_reconfigure_carry_the_config_payload() -> None:
    """Test 4 — the payload rides in ``config``; ``add`` folds ``strategy_type`` into it (D-04)."""
    added = StrategyCommandEvent.add(
        strategy_name="s1", strategy_type="SMAMACDStrategy",
        config={"timeframe": "1d", "tickers": ["BTCUSD"]}, time=_T)

    assert added.config is not None
    assert added.config["strategy_type"] == "SMAMACDStrategy"
    assert added.config["timeframe"] == "1d"

    reconfigured = StrategyCommandEvent.reconfigure(
        strategy_name="s1", config={"entry_z": "3"}, time=_T)
    assert reconfigured.config == {"entry_z": "3"}


def test_add_does_not_mutate_the_callers_config_dict() -> None:
    """``add`` folds ``strategy_type`` into a COPY — the caller's dict is untouched."""
    caller_config = {"timeframe": "1d"}
    StrategyCommandEvent.add(
        strategy_name="s1", strategy_type="SMAMACDStrategy",
        config=caller_config, time=_T)

    assert "strategy_type" not in caller_config


def test_subscribe_verbs_put_the_portfolio_id_in_config() -> None:
    """Test 5 — D-08 locks ONE optional payload field, not a typed field per verb."""
    subscribe = StrategyCommandEvent.subscribe_portfolio(
        strategy_name="s1", portfolio_id="p1", time=_T)
    unsubscribe = StrategyCommandEvent.unsubscribe_portfolio(
        strategy_name="s1", portfolio_id="p1", time=_T)

    assert subscribe.config == {"portfolio_id": "p1"}
    assert unsubscribe.config == {"portfolio_id": "p1"}
    assert subscribe.symbol is None


@pytest.mark.parametrize("verb, kwargs", _SYMBOL_LESS)
def test_str_renders_every_verb_without_raising(verb: str, kwargs: dict) -> None:
    """Test 6 — ``__str__`` feeds logs; a symbol-less verb must not blow it up."""
    event = getattr(StrategyCommandEvent, verb)(strategy_name="s1", time=_T, **kwargs)

    rendered = str(event)
    assert verb in rendered
    assert "s1" in rendered


def test_str_omits_symbol_when_absent_and_never_prints_config_values() -> None:
    """``__str__`` marks config PRESENCE by key count — a payload value never reaches logs."""
    enabled = StrategyCommandEvent.enable(strategy_name="s1", time=_T)
    assert "symbol" not in str(enabled)

    added = StrategyCommandEvent.add_ticker(
        strategy_name="s1", symbol="BTCUSD", time=_T)
    assert "BTCUSD" in str(added)

    secretive = StrategyCommandEvent.reconfigure(
        strategy_name="s1", config={"api_key": "sk-do-not-log-me"}, time=_T)
    rendered = str(secretive)
    assert "sk-do-not-log-me" not in rendered
    assert "api_key" not in rendered
    assert "config=1" in rendered


def test_old_shaped_payload_still_decodes() -> None:
    """Test 7 — an old payload with neither new field round-trips (backward compat)."""
    old_shape = {
        "time": _T.isoformat(),
        "strategy_name": "s1",
        "verb": "add_ticker",
        "symbol": "BTCUSD",
    }
    decoded = msgspec.json.decode(
        msgspec.json.encode(old_shape), type=StrategyCommandEvent)

    assert decoded.symbol == "BTCUSD"
    assert decoded.config is None


def test_new_shaped_event_round_trips_through_msgspec() -> None:
    """A symbol-less, config-carrying event survives encode/decode."""
    event = StrategyCommandEvent.subscribe_portfolio(
        strategy_name="s1", portfolio_id="p1", time=_T)
    decoded = msgspec.json.decode(
        msgspec.json.encode(event), type=StrategyCommandEvent)

    assert decoded.verb == "subscribe_portfolio"
    assert decoded.symbol is None
    assert decoded.config == {"portfolio_id": "p1"}
