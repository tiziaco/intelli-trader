"""OPS-03 / OPS-04 round-trip proof for ``SqlSignalStorage`` on testcontainers Postgres.

A ``SignalRecord`` written through ``SqlSignalStorage`` (the strategy/signal operational
backend on the shared SQL spine) must read back *losslessly* and field-wise *EQUAL* on
Postgres (D-10): the full record (incl. the ``config`` params dict), the indexed
``by_strategy``/``by_ticker`` filters (no cross-strategy/ticker bleed, T-03-15), exact-Decimal
money (Postgres-native ``Numeric``, OPS-04 / Pitfall 2 — money is Postgres-only), and a
value-equal UUIDv7 ``signal_id``.

Substrate: the ``pg_backend`` fixture (Plan 03-01 conftest) — a ``SqlEngine`` over the
session-scoped testcontainers Postgres DB. The arm SKIPS (never hard-fails) when Docker is
absent (D-11), inherited transitively from ``pg_engine``. The function-scoped ``pg_backend``
binds to the SAME Postgres database across tests, so every test uses FRESH unique
``strategy_id``/``ticker`` values and asserts through the indexed filter queries (never a
table-wide ``get_all``) to stay isolated from sibling tests' rows. The backend is disposed in
the fixture (WR-03 / Pitfall 4 — an undisposed engine trips a ResourceWarning under
``filterwarnings=["error"]``).

Threat coverage (03-04 register):
* T-03-13 (SQL injection) — filters cross via ``bindparam`` against constant ``Table``/``Column``.
* T-03-14 (money/precision loss) — exact-Decimal money asserted on the Postgres arm only.
* T-03-15 (cross-strategy/ticker bleed) — filter-isolation tests prove no bleed.

4-space indentation (matches ``tests/integration/*``).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import uuid_utils.compat as uc

from itrader.core.enums import OrderType, Side
from itrader.core.ids import StrategyId
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage.sql_storage import SqlSignalStorage

# A stable, JSON-safe params snapshot (the strategy.to_dict() shape, D-04). Decoded-dict
# equality is the contract (Pitfall 8 / A6), NOT JSON byte identity.
_CONFIG: dict[str, Any] = {
    "fast_window": 10,
    "slow_window": 50,
    "signal_window": 9,
    "name": "SMA_MACD",
}


def _make_record(
    strategy_id: StrategyId,
    ticker: str,
    *,
    time: datetime,
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
    quantity: Decimal | None = None,
    entry_price: Decimal | None = None,
) -> SignalRecord:
    """Build a ``SignalRecord`` (default signal_id) for the given strategy/ticker."""
    return SignalRecord(
        strategy_id=strategy_id,
        ticker=ticker,
        time=time,
        action=Side.BUY,
        order_type=OrderType.MARKET,
        stop_loss=stop_loss,
        take_profit=take_profit,
        exit_fraction=Decimal("1"),
        quantity=quantity,
        entry_price=entry_price,
        config=dict(_CONFIG),
    )


def test_signal_record_roundtrip_field_equal(pg_backend):
    """A full SignalRecord round-trips field-wise EQUAL incl. the config dict (OPS-03)."""
    store = SqlSignalStorage(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    record = _make_record(
        strategy_id,
        "BTCUSD",
        time=datetime(2018, 1, 1, tzinfo=timezone.utc),
        stop_loss=Decimal("100.50"),
        take_profit=Decimal("250.75"),
        quantity=Decimal("0.5"),
        entry_price=Decimal("199.99"),
    )

    store.add(record)
    fetched = store.by_strategy(strategy_id)

    assert len(fetched) == 1
    obj2 = fetched[0]
    assert obj2 == record  # field-wise msgspec equality (incl. config decoded-dict, A6)
    assert obj2.config == _CONFIG  # explicit decoded-dict value equality (Pitfall 8)
    # UUIDv7 signal_id read back value-equal as a native uuid.UUID (D-03).
    assert obj2.signal_id == record.signal_id
    assert isinstance(obj2.signal_id, uuid.UUID)


def test_money_fields_exact_decimal(pg_backend):
    """Money fields persist as Postgres-native Numeric and read back exact Decimal (OPS-04)."""
    store = SqlSignalStorage(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    record = _make_record(
        strategy_id,
        "ETHUSD",
        time=datetime(2019, 6, 15, tzinfo=timezone.utc),
        stop_loss=Decimal("1234.56789012"),
        take_profit=Decimal("9876.54321098"),
        quantity=Decimal("3.14159265"),
        entry_price=Decimal("4242.42424242"),
    )

    store.add(record)
    obj2 = store.by_strategy(strategy_id)[0]

    assert isinstance(obj2.stop_loss, Decimal)
    assert obj2.stop_loss == Decimal("1234.56789012")
    assert obj2.take_profit == Decimal("9876.54321098")
    assert obj2.quantity == Decimal("3.14159265")
    assert obj2.entry_price == Decimal("4242.42424242")
    assert obj2.exit_fraction == Decimal("1")


def test_nullable_money_roundtrips_none(pg_backend):
    """Absent optional money fields round-trip back as None (not 0 / Decimal)."""
    store = SqlSignalStorage(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    record = _make_record(
        strategy_id,
        "SOLUSD",
        time=datetime(2020, 3, 9, tzinfo=timezone.utc),
    )

    store.add(record)
    obj2 = store.by_strategy(strategy_id)[0]

    assert obj2.stop_loss is None
    assert obj2.take_profit is None
    assert obj2.quantity is None
    assert obj2.entry_price is None
    assert obj2 == record


def test_by_strategy_filter_isolation(pg_backend):
    """by_strategy returns only the matching strategy's records — no cross-strategy bleed."""
    store = SqlSignalStorage(pg_backend)
    strat_a = StrategyId(uc.uuid7())
    strat_b = StrategyId(uc.uuid7())
    rec_a = _make_record(
        strat_a, "BTCUSD", time=datetime(2021, 1, 1, tzinfo=timezone.utc)
    )
    rec_b = _make_record(
        strat_b, "BTCUSD", time=datetime(2021, 1, 2, tzinfo=timezone.utc)
    )

    store.add(rec_a)
    store.add(rec_b)

    got_a = store.by_strategy(strat_a)
    got_b = store.by_strategy(strat_b)

    assert [r.signal_id for r in got_a] == [rec_a.signal_id]
    assert [r.signal_id for r in got_b] == [rec_b.signal_id]
    assert all(r.strategy_id == strat_a for r in got_a)


def test_by_ticker_filter_isolation(pg_backend):
    """by_ticker returns only the matching ticker's records — no cross-ticker bleed."""
    store = SqlSignalStorage(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    # Unique tickers per test run so sibling tests' rows never collide.
    ticker_x = f"XCOIN-{uuid.uuid4().hex[:8]}"
    ticker_y = f"YCOIN-{uuid.uuid4().hex[:8]}"
    rec_x = _make_record(
        strategy_id, ticker_x, time=datetime(2022, 5, 1, tzinfo=timezone.utc)
    )
    rec_y = _make_record(
        strategy_id, ticker_y, time=datetime(2022, 5, 2, tzinfo=timezone.utc)
    )

    store.add(rec_x)
    store.add(rec_y)

    got_x = store.by_ticker(ticker_x)
    got_y = store.by_ticker(ticker_y)

    assert [r.signal_id for r in got_x] == [rec_x.signal_id]
    assert [r.signal_id for r in got_y] == [rec_y.signal_id]
    assert all(r.ticker == ticker_x for r in got_x)


def test_stable_insertion_order(pg_backend):
    """Records read back in stable ORDER BY (time, signal_id) order (get_all contract)."""
    store = SqlSignalStorage(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    rec_1 = _make_record(
        strategy_id, "BTCUSD", time=datetime(2023, 1, 1, tzinfo=timezone.utc)
    )
    rec_2 = _make_record(
        strategy_id, "BTCUSD", time=datetime(2023, 1, 2, tzinfo=timezone.utc)
    )
    rec_3 = _make_record(
        strategy_id, "BTCUSD", time=datetime(2023, 1, 3, tzinfo=timezone.utc)
    )

    # Insert out of time order; the ORDER BY must still yield chronological order.
    store.add(rec_2)
    store.add(rec_3)
    store.add(rec_1)

    got = store.by_strategy(strategy_id)

    assert [r.signal_id for r in got] == [
        rec_1.signal_id,
        rec_2.signal_id,
        rec_3.signal_id,
    ]
