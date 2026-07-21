"""Shared P10 strategy-catalog + registry-row test fixtures (D-01/D-04/D-05/D-20).

Placed in ``tests/support/`` (the ``replay_harness.py`` precedent) rather than a
``conftest.py`` under ``tests/unit/strategy/``: those unit trees are deliberately
package-less (MEMORY: two same-named top-level test packages break full-suite
collection), so shared helpers live here and are imported by path.

**D-01 — the asymmetry this module embodies.** ``test_catalog()`` imports the three
shipped concrete strategy classes and maps them by ``__name__``. THE TEST imports them;
``itrader`` NEVER does. That asymmetry IS the decision: strategy *types* are code and are
handed to the engine by the application (the owner's proprietary strategies live in a
private submodule repo the future FastAPI app injects), while strategy *instances* are
DATA whose source of truth is the store. ``resolve_strategy_class`` is a plain lookup in
this injected allowlist — so this dict is exactly the shape an app supplies in production.

Public surface:

* ``test_catalog`` — the injected ``StrategyCatalog`` over the three shipped strategies.
* ``build_shipped_strategies`` — one constructed instance per shipped strategy, with the
  required kwargs each one needs.
* ``seeded_registry_rows`` — well-formed ``strategy_registry`` +
  ``strategy_portfolio_subscriptions`` rows for a set of instances, for reuse by Plan 05's
  rehydrate tests and Plan 09's restart lifecycle test.
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from itrader.core.sizing import FractionOfCash
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.registry import StrategyCatalog, encode_strategy_config
from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategy
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import EthBtcPairStrategy
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy

__all__ = [
    "build_shipped_strategies",
    "seeded_registry_rows",
    "test_catalog",
]

# D-22 (pytest-collection guard): ``test_catalog`` is a NON-test function whose name
# matches pytest's ``test_*`` collection pattern. Without this marker pytest collects it
# as a test, and its non-None return raises a ``PytestReturnNotNoneWarning`` — a HARD
# failure under ``filterwarnings=["error"]``. Same reflex as replay_harness's
# ``__test__ = False`` on its ``Test*`` classes.
def test_catalog() -> StrategyCatalog:
    """The injected D-01 allowlist over the three shipped strategies.

    Keyed on ``cls.__name__`` — the same key ``encode_strategy_config`` stamps as
    ``strategy_type`` and the ``strategy_registry.strategy_type`` column stores.
    """
    return {
        cls.__name__: cls
        for cls in (SMAMACDStrategy, EmptyStrategy, EthBtcPairStrategy)
    }


test_catalog.__test__ = False  # type: ignore[attr-defined]


def build_shipped_strategies() -> list[Strategy]:
    """One constructed instance per shipped strategy, with each one's required kwargs.

    ``timeframe``/``tickers``/``sizing_policy`` are the base's three BARE annotations
    (required — ``base.py:173-175``). ``SMAMACDStrategy`` and ``EthBtcPairStrategy`` pin
    ``sizing_policy`` (and the pair pins ``tickers``) as class attrs; ``EmptyStrategy``
    pins none of the three, so it is fully kwarg-supplied.
    """
    return [
        SMAMACDStrategy(timeframe="1d", tickers=["BTCUSD"]),
        EmptyStrategy(
            timeframe="1h",
            tickers=["BTCUSD"],
            sizing_policy=FractionOfCash(Decimal("0.5")),
        ),
        EthBtcPairStrategy(timeframe="1d"),
    ]


def seeded_registry_rows(
    strategies: Sequence[Strategy],
    *,
    enabled: bool = True,
    updated_at: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build well-formed registry + subscription rows for ``strategies`` (D-06 shape).

    Returns ``(registry_rows, subscription_rows)`` matching the two tables built by
    ``itrader/storage/strategy_registry_store.py::build_strategy_registry_tables``:

    * ``strategy_registry`` — ``strategy_name`` (natural PK, D-02), ``strategy_type``
      (the D-01 catalog key), ``enabled`` (D-06 runtime state in its OWN column, never
      inside ``config_json``), ``config_json`` (the D-04 authoring blob), ``updated_at``.
    * ``strategy_portfolio_subscriptions`` — ``(strategy_name, portfolio_id)``, the
      portfolio fan-out edge; ``portfolio_id`` is String because ``to_dict``
      serializes each handle via ``str(pid)`` and rehydrate parses it back
      (a ``Uuid`` column is open as B2, not decided).

    Trap 2 (D-02): ``strategy_name`` comes from ``strategy.name`` and the blob carries NO
    ``name`` key, so a row whose PK and blob disagree is unrepresentable by construction.
    """
    stamp = updated_at if updated_at is not None else datetime.now(timezone.utc)
    registry_rows: list[dict[str, Any]] = []
    subscription_rows: list[dict[str, Any]] = []
    for strategy in strategies:
        registry_rows.append(
            {
                "strategy_name": strategy.name,
                "strategy_type": type(strategy).__name__,
                "enabled": enabled,
                "config_json": encode_strategy_config(strategy),
                "updated_at": stamp,
            }
        )
        for portfolio_id in strategy.subscribed_portfolios:
            subscription_rows.append(
                {
                    "strategy_name": strategy.name,
                    "portfolio_id": str(portfolio_id),
                }
            )
    return registry_rows, subscription_rows
