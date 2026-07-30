"""The restart bootstrap's ORDER is load-bearing, so it is asserted directly (design §7.5).

Turning a durable database back into a running engine has one correct order, and getting it
wrong is SILENT rather than loud:

  - **bring-up before rehydrate.** A portfolio rehydrated before its account came online
    resolves against a manager whose online set is still empty. Nothing raises there — the
    live ``AccountFactory`` validator asserts the account row is PROVISIONED and ENABLED,
    deliberately not that it is online (an okx-only boot must not crash on a validly
    provisioned binance portfolio it never brings up). So the ordering has no runtime
    tripwire of its own and needs a gate of its own; this is it.
  - **rehydrate before config layering.** The layering pass iterates the portfolios the
    rehydrate materialized. Run first, it iterates an EMPTY collection, drops every stored
    per-portfolio override, and boots a healthy-looking engine on default config.

Both are asserted against the PRODUCTION functions — ``bootstrap_session`` and the live
root's ``_restart_sequence`` — over recording doubles, so a future edit that reorders the
statements fails here rather than at the next restart.

This directory is package-less (NO ``__init__.py``). 4-space indentation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from itrader.trading_system.live.bootstrap import bootstrap_session


class _RecordingManager:
    """A venue-account manager double appending each verb it is asked for."""

    def __init__(self, calls: list[str], rows: list[dict[str, Any]]) -> None:
        self._calls = calls
        self._rows = rows

    def read_enabled_for(self, venue_name: str) -> list[dict[str, Any]]:
        return list(self._rows)

    def bring_online(self, row: dict[str, Any]) -> Any:
        self._calls.append(f"bring_online:{row['account_id']}")
        return MagicMock(name="online_record")


class _RecordingDefinitionStore:
    """A definition store double appending its read, so the sequence is observable."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def read_all(self) -> list[dict[str, Any]]:
        self._calls.append("read_definitions")
        return []


@pytest.fixture
def sequence() -> list[str]:
    return []


@pytest.fixture
def sql_engine(monkeypatch: Any, sequence: list[str]) -> Any:
    """A spine whose ``portfolios`` table exists, so the boot runs its full sequence."""
    engine = MagicMock(name="sql_engine")
    monkeypatch.setattr(
        "itrader.trading_system.live.bootstrap.sa_inspect",
        lambda _engine: MagicMock(has_table=lambda _name: True))
    monkeypatch.setattr(
        "itrader.trading_system.live.bootstrap.assert_distinct_accounts",
        lambda **_kwargs: None)

    def _rehydrate(*, store: Any, portfolio_handler: Any) -> None:
        sequence.append("rehydrate_portfolios")

    monkeypatch.setattr(
        "itrader.trading_system.live.bootstrap.rehydrate_portfolios", _rehydrate)
    return engine


def test_every_account_comes_online_before_any_portfolio_rehydrates(
    sql_engine: Any, sequence: list[str]
) -> None:
    """The ordering gate: assembly is complete BEFORE the first portfolio materializes.

    A portfolio materialized against a manager whose online set is still empty sits on a
    compute leaf that looks perfectly healthy — it has cash, it accepts orders, and its
    orders route to a ``(venue, account_id)`` pair nothing registered. The failure surfaces
    as an unroutable order much later, nowhere near the boot that caused it.
    """
    manager = _RecordingManager(
        sequence,
        [{"venue_name": "okx", "account_id": "acct-a"},
         {"venue_name": "okx", "account_id": "acct-b"}])
    portfolio_handler = MagicMock(name="portfolio_handler")
    portfolio_handler.definition_store = _RecordingDefinitionStore(sequence)

    bootstrap_session(
        sql_engine=sql_engine,
        venue_manager=manager,
        portfolio_handler=portfolio_handler,
        execution_venue="okx",
        alert_sink=MagicMock(name="alert_sink"),
    )

    assert sequence.index("rehydrate_portfolios") > sequence.index("bring_online:acct-b")
    assert sequence == [
        "read_definitions",
        "bring_online:acct-a",
        "bring_online:acct-b",
        "rehydrate_portfolios",
    ]


def test_a_quarantined_account_does_not_stop_the_remaining_bring_ups(
    sql_engine: Any, sequence: list[str]
) -> None:
    """One unreachable account must not take a multi-account deployment offline.

    The skip is safe precisely because ``bring_online`` registers LAST: the failed pair is
    unroutable, so quarantining leaves nothing half-online behind it.
    """
    class _OneRaising(_RecordingManager):
        def bring_online(self, row: dict[str, Any]) -> Any:
            if row["account_id"] == "acct-a":
                raise RuntimeError("venue unreachable")
            return super().bring_online(row)

    manager = _OneRaising(
        sequence,
        [{"venue_name": "okx", "account_id": "acct-a"},
         {"venue_name": "okx", "account_id": "acct-b"}])
    portfolio_handler = MagicMock(name="portfolio_handler")
    portfolio_handler.definition_store = _RecordingDefinitionStore(sequence)
    alert_sink = MagicMock(name="alert_sink")

    bootstrap_session(
        sql_engine=sql_engine,
        venue_manager=manager,
        portfolio_handler=portfolio_handler,
        execution_venue="okx",
        alert_sink=alert_sink,
    )

    assert sequence == [
        "read_definitions", "bring_online:acct-b", "rehydrate_portfolios"]
    # Never silent: the alert is what tells an operator an account they believe is trading
    # is not.
    assert alert_sink.alert.call_count == 1


def test_the_restart_sequence_layers_config_after_the_portfolios_exist(
    monkeypatch: Any, sequence: list[str]
) -> None:
    """The live root's restart sequence runs bootstrap -> layer -> strategy roster.

    Driven against the REAL ``_restart_sequence`` the builder binds, because the ordering is
    the builder's decision. Running the layering first is the silent variant: it iterates an
    empty portfolio collection and every stored per-portfolio override is dropped, with
    nothing raising anywhere.
    """
    from itrader.trading_system.live import build as _build

    monkeypatch.setattr(
        _build, "bootstrap_session",
        lambda **_kwargs: sequence.append("bootstrap_session"))
    monkeypatch.setattr(
        _build, "layer_persisted_overrides",
        lambda _config, **_kwargs: sequence.append("layer_persisted_overrides"))
    monkeypatch.setattr(
        _build, "rehydrate_strategies",
        lambda **_kwargs: (sequence.append("rehydrate_strategies"), [])[1])

    engine = MagicMock(name="engine")
    _build._restart_sequence(
        sql_engine=MagicMock(name="sql_engine"),
        venue_manager=MagicMock(name="venue_manager"),
        engine=engine,
        config=MagicMock(name="config"),
        execution_venue="okx",
        alert_sink=MagicMock(name="alert_sink"),
        system_store=MagicMock(name="system_store"),
        venue_store=MagicMock(name="venue_store"),
        strategy_catalog=None,
    )

    assert sequence == [
        "bootstrap_session", "layer_persisted_overrides", "rehydrate_strategies"]
