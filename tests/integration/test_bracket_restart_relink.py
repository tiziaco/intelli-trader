"""RECON-05 / D-05 — bracket parent/child re-link on restart (05-07).

These integration tests exercise ``VenueReconciler._relink_brackets``: on restart a bracket's
still-resting protective legs are re-linked to the venue open orders so an open position never
sits without its live OCO legs.

Two scenarios:

* **confident re-link** — a bracket child whose persisted ``venue_order_id`` matches a venue
  resting order re-links (venue-id-first) and resumes OCO — NO halt.
* **unconfident leg** — a bracket child with no persisted venue id AND no attribute
  (symbol+side+price+qty) match escalates THAT bracket to halt-and-alert
  (reason='reconciliation-unresolved') rather than guessing (T-05-22).

Substrate: a module-scoped testcontainers Postgres (real ``CachedSqlOrderStorage`` rehydrate +
bracket FK derivation) + the shared credential-free ``fake_venue_connector`` fixture (its
``fetch_open_orders`` narrates a single resting SELL take-profit leg @ 45000). Container tests
SKIP (never hard-fail) when Docker is absent (D-11).

4-space indentation; NO ``__init__.py`` in this dir (auto-memory: package-collision hazard).
"""

import queue
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.order_handler.order import Order

_BT = datetime(2024, 1, 1, tzinfo=timezone.utc)

# The venue ids the canned recon fixture narrates: ORD-0001 = the filled entry (BTC/USDT buy
# 0.5), ORD-0002 = the single resting SELL take-profit leg @ 45000 (fetch_open_orders).
_VENUE_ENTRY = "PLACEHOLDER-ORD-0001"
_VENUE_LEG = "PLACEHOLDER-ORD-0002"
_VENUE_SYMBOL = "BTC/USDT"

_OPERATIONAL_TABLES = ("order_state_changes", "orders", "signals")


class _HaltSpy:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def __call__(self, reason: str) -> None:
        self.calls.append(reason)


@pytest.fixture(scope="module")
def pg_url():
    """Module-scoped testcontainers Postgres URL; skip if Dockerless (D-11)."""
    from testcontainers.postgres import PostgresContainer

    container = None
    try:
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        pytest.skip(f"PostgreSQL container unavailable — skipped (D-11): {exc}")

    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _make_backend(pg_url):
    from pydantic import SecretStr

    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage import SqlEngine

    return SqlEngine(SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        url=SecretStr(pg_url),
    ))


def _drop_operational_tables(pg_url):
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            for table in _OPERATIONAL_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    finally:
        engine.dispose()


def _fresh_store(backend):
    from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
    from itrader.order_handler.storage.sql_storage import SqlOrderStorage

    store = SqlOrderStorage(backend)
    backend.metadata.create_all(backend.engine, checkfirst=True)
    return CachedSqlOrderStorage(store)


def _make_entry_parent(pid) -> Order:
    """A FILLED entry (BTC/USDT buy 0.5) that anchors the bracket, resident via its live leg.

    NO ``venue_order_id`` hand-stamp — the mirror's venue id is persisted ONLY by the real
    D-06 ORDER-ACK path via ``_stamp_venue_ack`` (V17-02 anti-pattern guard).
    """
    return Order(
        time=_BT, type=OrderType.LIMIT, status=OrderStatus.FILLED,
        ticker=_VENUE_SYMBOL, action=Side.BUY,
        price=Decimal("42000"), quantity=Decimal("0.5"),
        filled_quantity=Decimal("0.5"),
        exchange="okx", strategy_id=StrategyId(uc.uuid7()), portfolio_id=pid,
    )


def _make_leg(pid, parent_id, *, price) -> Order:
    """A resting SELL take-profit leg linked to the parent (active — needs re-linking).

    NO ``venue_order_id`` hand-stamp — a leg with a venue ack gets it stamped via the real
    D-06 ORDER-ACK path (``_stamp_venue_ack``); a leg that legitimately has no ack in the
    scenario is left ``None`` (the unconfident case the halt guards).
    """
    return Order(
        time=_BT, type=OrderType.LIMIT, status=OrderStatus.PENDING,
        ticker=_VENUE_SYMBOL, action=Side.SELL,
        price=price, quantity=Decimal("0.5"),
        exchange="okx", strategy_id=StrategyId(uc.uuid7()), portfolio_id=pid,
        parent_order_id=parent_id,
    )


def _stamp_venue_ack(seed_store, order, venue_order_id: str) -> None:
    """Persist ``venue_order_id`` onto the seeded order via the REAL D-06 ORDER-ACK path.

    Never a fixture hand-stamp (V17-02): wire an ``OrderHandler`` over the seed store and
    drive an ``OrderAckEvent`` through ``on_order_ack`` -> ``OrderManager.stamp_venue_order_id``
    -> ``store.update_order``, exactly as ``OkxExchange._submit_order`` does pre-restart.
    Write-through persists to the backing DB so the ``restarted`` store rehydrates the stamp.
    """
    from unittest.mock import MagicMock

    from itrader.events_handler.events import OrderAckEvent
    from itrader.order_handler.order_handler import OrderHandler

    handler = OrderHandler(
        queue.Queue(), MagicMock(name="portfolio_read_model"), order_storage=seed_store)
    handler.on_order_ack(OrderAckEvent(
        time=_BT,
        order_id=order.id,
        venue_order_id=venue_order_id,
        portfolio_id=order.portfolio_id,
    ))


def _build_reconciler(store, connector, halt_spy):
    from itrader.portfolio_handler.account.venue import VenueAccount
    from itrader.portfolio_handler.reconcile.venue_reconciler import VenueReconciler

    gq: "queue.Queue[Any]" = queue.Queue()
    reconciler = VenueReconciler(
        store=store,
        venue_account=VenueAccount(connector),
        connector=connector,
        global_queue=gq,
        halt_signal=halt_spy,
    )
    return reconciler


def test_bracket_leg_relinks_by_venue_id_resumes_oco(pg_url, fake_venue_connector):
    """A bracket leg matching by persisted venue_order_id re-links — no halt (D-05)."""
    backend = _make_backend(pg_url)
    try:
        seed = _fresh_store(backend)
        pid = PortfolioId(uc.uuid7())
        parent = _make_entry_parent(pid)
        # The leg's persisted venue id matches the fixture's resting order (ORD-0002).
        leg = _make_leg(pid, parent.id, price=Decimal("45000"))
        seed.add_order(parent)      # FK: parent before child
        seed.add_order(leg)
        _stamp_venue_ack(seed, parent, _VENUE_ENTRY)   # real D-06 ack path
        _stamp_venue_ack(seed, leg, _VENUE_LEG)        # real D-06 ack path

        restarted = _fresh_store(backend)
        halt = _HaltSpy()
        reconciler = _build_reconciler(restarted, fake_venue_connector, halt)
        reconciler.reconcile()

        assert halt.calls == []     # confident venue-id re-link — no halt
        # The leg stays linked to its venue resting order.
        got = restarted.get_order_by_id(leg.id)
        assert got is not None
        assert got.venue_order_id == _VENUE_LEG
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()


def test_unconfident_bracket_leg_halts(pg_url, fake_venue_connector):
    """A bracket leg with no venue-id and no attribute match halts that bracket (D-05)."""
    backend = _make_backend(pg_url)
    try:
        seed = _fresh_store(backend)
        pid = PortfolioId(uc.uuid7())
        parent = _make_entry_parent(pid)
        # No persisted venue id AND a price no resting order carries (fixture rests @ 45000)
        # → neither venue-id nor attribute match → unconfident.
        leg = _make_leg(pid, parent.id, price=Decimal("99999"))
        seed.add_order(parent)
        seed.add_order(leg)
        _stamp_venue_ack(seed, parent, _VENUE_ENTRY)   # real D-06 ack path
        # The leg legitimately has NO venue ack in this scenario — left unstamped (None),
        # the unconfident case the halt guards (assert None, never a faked id).
        assert seed.get_order_by_id(leg.id).venue_order_id is None

        restarted = _fresh_store(backend)
        halt = _HaltSpy()
        reconciler = _build_reconciler(restarted, fake_venue_connector, halt)
        reconciler.reconcile()

        assert halt.calls == ["reconciliation-unresolved"]  # per-bracket halt
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()
