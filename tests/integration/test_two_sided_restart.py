"""RECON-05 — two-sided restart rehydration: store rehydrate + venue REST reconcile (05-07).

These integration tests exercise ``VenueReconciler.reconcile`` (D-03): on restart the engine
reconstructs the working set from the store (INTENT truth) AND reconciles it against the live
venue REST snapshot (balance/position/fill truth) BEFORE it trades again.

Three scenarios:

* **agree** — a store order whose ``filled_quantity`` already equals the venue-filled qty
  produces NO phantom reconciling fill, and its symbol covers the venue position so there is
  NO halt.
* **downtime fill** — a store order the venue filled during downtime is ADOPTED as ONE
  reconciling ``FillEvent`` PER not-yet-applied venue trade (CR-01: per-trade granularity, each
  carrying its own ``venue_trade_id``), summing to ``venue_filled − order.filled``; re-running
  the reconcile after the delta is applied emits nothing (adopt-once, idempotent).
* **orphan position** — a venue position with NO matching stored intent (a hand-opened
  position) HALTS-and-alerts (reason='reconciliation-unresolved'), never auto-adopted.

Substrate: a module-scoped testcontainers Postgres (mirrors ``test_store_live_drive.py``) for
the real ``CachedSqlOrderStorage`` rehydrate + ``venue_order_id`` round-trip, plus the shared
credential-free ``fake_venue_connector`` fixture (canned ccxt-unified recon payloads). Container
tests SKIP (never hard-fail) when Docker is absent (D-11).

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker.
"""

import queue
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.events_handler.events import FillEvent
from itrader.order_handler.order import Order

# A business time (never wall clock) reused so derived timestamps are deterministic.
_BT = datetime(2024, 1, 1, tzinfo=timezone.utc)

# The venue order id the canned recon fixture's trades/positions narrate (BTC/USDT buy 0.5).
_VENUE_ORD = "PLACEHOLDER-ORD-0001"
_VENUE_SYMBOL = "BTC/USDT"

_OPERATIONAL_TABLES = ("order_state_changes", "orders", "signals")


class _HaltSpy:
    """Records every ``halt(reason)`` call so a test can assert the halt fired (or did not)."""

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
    """Build a fresh ``SqlEngine`` bound to the container DB."""
    from pydantic import SecretStr

    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage import SqlEngine

    return SqlEngine(SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        url=SecretStr(pg_url),
    ))


def _drop_operational_tables(pg_url):
    """Drop the operational tables so the shared session DB is left pristine."""
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            for table in _OPERATIONAL_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    finally:
        engine.dispose()


def _make_order(**overrides) -> Order:
    """Build an active ``Order`` for BTC/USDT (overridable per field).

    NO ``venue_order_id`` hand-stamp here — that is exactly the V17-02 anti-pattern the
    A2 gate guards against. The mirror's ``venue_order_id`` is stamped ONLY by the real
    D-06 ORDER-ACK path via ``_stamp_venue_ack`` (as ``OkxExchange`` would pre-restart).
    """
    base = dict(
        time=_BT,
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker=_VENUE_SYMBOL,
        action=Side.BUY,
        price=Decimal("42000"),
        quantity=Decimal("1.0"),
        exchange="okx",
        strategy_id=StrategyId(uc.uuid7()),
        portfolio_id=PortfolioId(uc.uuid7()),
    )
    base.update(overrides)
    return Order(**base)


def _stamp_venue_ack(seed_store, order, venue_order_id: str) -> Order:
    """Persist ``venue_order_id`` onto the seeded order via the REAL D-06 ORDER-ACK path.

    Never a fixture hand-stamp (V17-02): wire an ``OrderHandler`` over the seed store and
    drive an ``OrderAckEvent`` through ``on_order_ack`` -> ``OrderManager.stamp_venue_order_id``
    -> ``store.update_order``, exactly as ``OkxExchange._submit_order`` does in a live
    pre-restart session. Write-through persists to the backing DB, so the ``restarted``
    store rehydrates the stamp (the D-06 durability this suite exercises). Returns the
    re-read order so the caller's handle reflects the persisted stamp.
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
    return seed_store.get_order_by_id(order.id, order.portfolio_id)


def _fresh_store(backend):
    """Build a CachedSqlOrderStorage over the backend (idempotent schema create)."""
    from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
    from itrader.order_handler.storage.sql_storage import SqlOrderStorage

    store = SqlOrderStorage(backend)
    backend.metadata.create_all(backend.engine, checkfirst=True)
    return CachedSqlOrderStorage(store)


def _build_reconciler(store, connector, halt_spy):
    """Wire a VenueReconciler over a real store, a VenueAccount, and a fresh queue."""
    from itrader.portfolio_handler.account.venue import VenueAccount
    from itrader.portfolio_handler.reconcile.venue_reconciler import VenueReconciler

    gq: "queue.Queue[Any]" = queue.Queue()
    venue_account = VenueAccount(connector, account_id="acct-test")
    reconciler = VenueReconciler(
        store=store,
        venue_account=venue_account,
        connector=connector,
        global_queue=gq,
        halt_signal=halt_spy,
    )
    return reconciler, gq


def _drain_fills(gq) -> List[FillEvent]:
    """Drain every FillEvent currently on the queue."""
    fills: List[FillEvent] = []
    while True:
        try:
            event = gq.get_nowait()
        except queue.Empty:
            break
        if isinstance(event, FillEvent):
            fills.append(event)
    return fills


def test_store_and_venue_agree_no_halt_no_phantom_fill(pg_url, fake_venue_connector):
    """Store filled == venue filled → no reconciling fill, no halt (agree)."""
    backend = _make_backend(pg_url)
    try:
        seed = _fresh_store(backend)
        # Store already reflects the venue's 0.5 fill (PARTIALLY_FILLED, still active).
        order = _make_order(
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("0.5"),
        )
        seed.add_order(order)
        order = _stamp_venue_ack(seed, order, _VENUE_ORD)   # real D-06 ack path

        restarted = _fresh_store(backend)
        halt = _HaltSpy()
        reconciler, gq = _build_reconciler(restarted, fake_venue_connector, halt)
        reconciler.reconcile()

        assert _drain_fills(gq) == []          # no phantom fill
        assert halt.calls == []                # position covered by the stored order
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()


def test_downtime_fill_is_adopted_once(pg_url, fake_venue_connector):
    """A venue fill that landed during downtime is adopted PER venue trade (CR-01).

    The canned recon fixture narrates the 0.5 downtime fill as TWO venue trades
    (0.2 + 0.3). Post-CR-01 the reconciler emits ONE reconciling FillEvent per trade,
    each carrying its own ``venue_trade_id`` (so a stream re-delivery of the same trade
    dedups at the settlement chokepoint) — summing to the ``venue_filled − order.filled``
    delta. Re-running after the delta is applied emits nothing (adopt-once, idempotent).
    """
    backend = _make_backend(pg_url)
    try:
        seed = _fresh_store(backend)
        # Store thinks the order is still open (filled 0) — the venue filled 0.5 in downtime.
        order = _make_order(status=OrderStatus.PENDING, filled_quantity=Decimal("0"))
        seed.add_order(order)
        order = _stamp_venue_ack(seed, order, _VENUE_ORD)   # real D-06 ack path

        restarted = _fresh_store(backend)
        halt = _HaltSpy()
        reconciler, gq = _build_reconciler(restarted, fake_venue_connector, halt)
        reconciler.reconcile()

        fills = _drain_fills(gq)
        assert len(fills) == 2                             # one reconciling fill per venue trade
        assert all(f.order_id == order.id for f in fills)
        assert all(f.price == Decimal("42000") for f in fills)
        # Per-trade granularity: the two trades (0.2 + 0.3) sum to the 0.5 delta,
        # each carrying its OWN venue trade id (the CR-01 cross-emitter dedup key).
        assert sum(f.quantity for f in fills) == Decimal("0.5")
        assert {f.quantity for f in fills} == {Decimal("0.2"), Decimal("0.3")}
        assert {f.venue_trade_id for f in fills} == {
            "PLACEHOLDER-TRD-0001", "PLACEHOLDER-TRD-0002"}
        assert halt.calls == []                            # position is explained

        # Adopt-once: apply the delta to the store (engine-thread fill path analog),
        # then re-run the reconcile — the skip budget covers every trade, nothing re-emitted.
        order.filled_quantity = Decimal("0.5")
        order.status = OrderStatus.PARTIALLY_FILLED
        assert restarted.update_order(order) is True

        reconciler2, gq2 = _build_reconciler(restarted, fake_venue_connector, halt)
        reconciler2.reconcile()
        assert _drain_fills(gq2) == []                     # idempotent — no double-apply
        assert halt.calls == []
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()


def test_venue_position_without_stored_intent_halts(pg_url, fake_venue_connector):
    """A venue position with no matching stored order halts-and-alerts (never auto-adopts)."""
    backend = _make_backend(pg_url)
    try:
        seed = _fresh_store(backend)
        # A stored order for a DIFFERENT symbol — it does NOT explain the BTC/USDT position.
        order = _make_order(ticker="ETH/USDT")
        seed.add_order(order)
        order = _stamp_venue_ack(seed, order, "OTHER-VENUE-ID")   # real D-06 ack path

        restarted = _fresh_store(backend)
        halt = _HaltSpy()
        reconciler, gq = _build_reconciler(restarted, fake_venue_connector, halt)
        reconciler.reconcile()

        assert halt.calls == ["reconciliation-unresolved"]  # orphan position halted
        assert _drain_fills(gq) == []                        # nothing adopted for it
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()
