"""M5-08/TC6 — membership stub coverage (Plan 07-02, D-20/D-21).

``derive_membership`` is the ONE pure function the collapsed ``universe/``
package exports: the union of every strategy's traded tickers (tuple-pair
flattening included — the pairs-trading shape) and the screener set,
deduplicated. The multi-strategy union IS the membership union (D-21).
"""

import pytest

from itrader.universe import derive_membership

pytestmark = pytest.mark.unit


class StrategyStub:
    """Minimal strategy shape: only the ``tickers`` attribute matters."""

    def __init__(self, tickers):
        self.tickers = tickers


# -- Union semantics (the get_strategies_universe logic, relocated) -----------

def test_union_of_strategy_and_screener_tickers_flattens_pairs():
    strategies = [StrategyStub(["BTCUSDT"]), StrategyStub([("A", "B")])]
    result = derive_membership(strategies, screener_tickers=["ETHUSDT"])
    assert set(result) == {"BTCUSDT", "A", "B", "ETHUSDT"}


def test_tuple_pair_flattening_produces_both_legs():
    # Acceptance lock: [("A","B")] tickers produce BOTH "A" and "B".
    result = derive_membership([StrategyStub([("A", "B")])])
    assert set(result) == {"A", "B"}


def test_empty_inputs_return_empty_list():
    assert derive_membership([], []) == []


def test_deduplication_across_strategies_and_screeners():
    strategies = [
        StrategyStub(["BTCUSDT", "ETHUSDT"]),
        StrategyStub(["ETHUSDT"]),
    ]
    result = derive_membership(strategies, screener_tickers=["BTCUSDT"])
    assert sorted(result) == ["BTCUSDT", "ETHUSDT"]
    assert len(result) == len(set(result))


def test_screener_tickers_default_to_empty():
    assert set(derive_membership([StrategyStub(["X"])])) == {"X"}


def test_screener_only_membership():
    assert set(derive_membership([], ["SOLUSDT"])) == {"SOLUSDT"}
