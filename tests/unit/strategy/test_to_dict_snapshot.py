"""Snapshot-drift lock for the per-instance to_dict static cache (Req 4 / D-06 / 08-03).

`Strategy.to_dict` (base.py) caches the serialized STATIC portion of its snapshot
PER INSTANCE (stash on `self`), refreshing only the two genuinely runtime-mutable
fields — `is_active` and `subscribed_portfolios` — in place so key ordering is
unchanged. This file is the dedicated equivalence/drift test (08-PATTERNS "Audit-the-
invariant + dedicated drift test"):

- snapshot_byte_identical: cached output equals a clean rebuild (same keys, same
  order, same values).
- runtime_fields_refresh: after subscribe / activate mutate state, to_dict reflects
  the NEW values (cache does not freeze them stale) while static fields are unchanged.
- key_order_preserved: list(to_dict().keys()) identical across calls (in-place
  overwrite preserves position).
- per_instance_isolation: two instances with different declared windows each produce
  their OWN static values (no per-class cross-instance leak — the correctness bug
  D-06 calls out).
- invalidation_seam: _invalidate_to_dict_cache() forces a rebuild on next to_dict.
"""

from decimal import Decimal

import pytest
from uuid_utils.compat import uuid7

from itrader.core.ids import PortfolioId
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy

pytestmark = pytest.mark.unit

# Portfolio handles are ALWAYS UUIDv7-backed ``PortfolioId`` values (FL-02).
_PID_A = PortfolioId(uuid7())
_PID_B = PortfolioId(uuid7())
_PID_KEY_ORDER = PortfolioId(uuid7())


def _make(short_window: int = 50, long_window: int = 100) -> SMAMACDStrategy:
    return SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSDT"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
        short_window=short_window,
        long_window=long_window,
    )


def test_snapshot_byte_identical() -> None:
    """Two consecutive to_dict() calls on the same instance are byte-identical
    (the cached static portion + the in-place runtime refresh)."""
    strat = _make()
    first = strat.to_dict()
    second = strat.to_dict()
    assert list(first.keys()) == list(second.keys())
    assert first == second
    # The cached dict must be COPIED out — mutating the returned dict must not
    # poison the next call's cache.
    second["short_window"] = -999
    third = strat.to_dict()
    assert third["short_window"] == 50


def test_key_order_preserved() -> None:
    """The static cache + in-place overwrite of the two runtime keys preserves
    snapshot key ordering across calls."""
    strat = _make()
    keys_before = list(strat.to_dict().keys())
    strat.activate_strategy()
    strat.subscribe_portfolio(_PID_KEY_ORDER)
    keys_after = list(strat.to_dict().keys())
    assert keys_before == keys_after


def test_runtime_fields_refresh() -> None:
    """After subscribe / deactivate mutate runtime state, to_dict() reflects the
    NEW is_active + subscribed_portfolios while every static field is unchanged."""
    strat = _make()
    snap0 = strat.to_dict()
    assert snap0["is_active"] is True
    assert snap0["subscribed_portfolios"] == []

    strat.subscribe_portfolio(_PID_A)
    strat.subscribe_portfolio(_PID_B)
    strat.deactivate_strategy()
    snap1 = strat.to_dict()

    assert snap1["is_active"] is False
    assert snap1["subscribed_portfolios"] == [str(_PID_A), str(_PID_B)]
    # Static fields untouched by the runtime mutation.
    for key in snap0:
        if key in ("is_active", "subscribed_portfolios"):
            continue
        assert snap0[key] == snap1[key], f"static field {key} drifted"


def test_per_instance_isolation() -> None:
    """Two instances with different declared windows each produce their OWN
    static values — the cache is per-INSTANCE, never per-class (D-06 leak bug)."""
    a = _make(short_window=10, long_window=30)
    b = _make(short_window=20, long_window=60)
    # Prime both caches.
    sa = a.to_dict()
    sb = b.to_dict()
    assert sa["short_window"] == 10
    assert sa["long_window"] == 30
    assert sb["short_window"] == 20
    assert sb["long_window"] == 60
    # Re-read in interleaved order — no cross-instance bleed.
    assert a.to_dict()["short_window"] == 10
    assert b.to_dict()["short_window"] == 20


def test_invalidation_seam() -> None:
    """_invalidate_to_dict_cache() drops the cached static dict so the next
    to_dict() rebuilds it (seam works, even though backtest never calls it)."""
    strat = _make()
    strat.to_dict()  # prime the cache
    assert strat._to_dict_static_cache is not None
    strat._invalidate_to_dict_cache()
    assert strat._to_dict_static_cache is None
    # Next call rebuilds and is still byte-identical.
    rebuilt = strat.to_dict()
    assert strat._to_dict_static_cache is not None
    assert rebuilt["short_window"] == 50


def test_reconfigure_invalidates_cache() -> None:
    """reconfigure() mutates declared params — it MUST invalidate the static
    cache so to_dict() reflects the new declared values (no stale static)."""
    strat = _make(short_window=50, long_window=100)
    assert strat.to_dict()["short_window"] == 50
    strat.reconfigure(short_window=30)
    assert strat.to_dict()["short_window"] == 30
