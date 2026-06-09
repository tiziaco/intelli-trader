"""M5-08/TC6 — membership stub coverage (Plan 07-02, D-20/D-21).

``derive_membership`` is the ONE pure function the collapsed ``universe/``
package exports: the union of every strategy's traded tickers (tuple-pair
flattening included — the pairs-trading shape) and the screener set,
deduplicated. The multi-strategy union IS the membership union (D-21).
"""

from datetime import datetime

import pytest

from itrader.universe import active_membership, derive_membership, is_active

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


# -- UNIV-01 availability primitive: span model (D-01, D-03) -------------------
# Pure-function unit tests. Span bounds and `asof` are built naive and
# consistently — the pure primitive only requires they share tz-ness; tz-aware
# stamps are exercised in the feed/integration paths (Plans 02/03), not here.


def test_active_only_within_span():
    # D-01: active iff first_bar <= asof <= last_bar, inclusive BOTH ends.
    spans = {"ETH": (datetime(2021, 1, 1), datetime(2026, 1, 8))}
    assert is_active(spans, "ETH", datetime(2021, 1, 1)) is True   # listing day inclusive
    assert is_active(spans, "ETH", datetime(2026, 1, 8)) is True   # end day inclusive
    assert is_active(spans, "ETH", datetime(2020, 12, 31)) is False  # day before listing
    assert is_active(spans, "ETH", datetime(2026, 1, 9)) is False   # day after end


def test_mid_life_gap_still_active():
    # D-01: an internal gap day is STILL a member (span model, not bar-presence).
    spans = {"X": (datetime(2021, 1, 1), datetime(2021, 12, 31))}
    assert is_active(spans, "X", datetime(2021, 6, 15)) is True


def test_unknown_ticker_is_not_active():
    # Sparse contract: a ticker absent from the span map is never active.
    assert is_active({}, "NOPE", datetime(2021, 1, 1)) is False


def test_active_membership_set_over_differing_spans():
    # Differing spans: BTC long, ETH/AAVE shorter and ending earlier. Assert the
    # live SET at three distinct T points (set-equality only — never order).
    spans = {
        "BTC": (datetime(2018, 1, 1), datetime(2026, 6, 3)),
        "ETH": (datetime(2021, 1, 1), datetime(2026, 1, 8)),
        "AAVE": (datetime(2021, 7, 15), datetime(2026, 1, 8)),
    }
    # Early T: only the first-listed ticker is live.
    assert active_membership(spans, datetime(2020, 1, 1)) == {"BTC"}
    # Mid T: all three are within their spans.
    assert active_membership(spans, datetime(2021, 8, 1)) == {"BTC", "ETH", "AAVE"}
    # Late T: ETH/AAVE have ended, only the still-running ticker remains.
    assert active_membership(spans, datetime(2026, 3, 1)) == {"BTC"}


def test_active_membership_empty_spans_is_empty_set():
    assert active_membership({}, datetime(2021, 1, 1)) == set()
