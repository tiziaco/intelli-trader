"""Opt-in slow OKX-demo reconciliation suite (Phase 5 / RECON-06, D-09).

This is the real order -> fill -> reconcile -> restart loop against the OKX **demo** host.
It is opt-in and network-gated: the whole module SKIPS unless demo credentials
(``OKX_API_KEY`` / ``OKX_API_SECRET`` / ``OKX_API_PASSPHRASE``) are present in the
environment (mirrors the Phase-2 ``tests/integration/test_okx_smoke.py`` guard). In CI and
credential-free checkouts it COLLECTS and SKIPS cleanly — no import errors, no network, no
session left open. The gating OFFLINE reconciliation suite (the shared ``FakeLiveConnector``
in ``tests/support``) is what runs credential-free; this file never gates it.

Real-money execution stays gated: the demo host only (``wspap.okx.com`` / REST
``x-simulated-trading``), routed off the connector's single ``sandbox`` flag — never a
production venue (T-05-04 mitigation). EVERY live test asserts ``connector.sandbox is True``
BEFORE any order submission or venue-mutating action; that enforced sandbox routing is what
keeps the demo keys real-money-free.

The three test bodies below are LIVE end-to-end assertions (no scaffold skips remain):

* ``test_demo_order_produces_real_fill_event`` — a tiny demo MARKET order flows through the
  sandbox-routed OKX live stack, a real ``FillEvent`` streams back and terminalizes the order
  mirror to FILLED, and venue-trade-id dedup holds (RECON-01/02; reachable only because the
  05-10 CR-01 wiring spawns the live fill stream in ``start()``).
* ``test_venue_account_reconciles_post_fill_within_tolerance`` — after the demo fill a fresh
  ``VenueAccount`` REST snapshot reconciles engine-vs-venue per-symbol position WITHIN the
  drift tolerance band with NO spurious halt, under 1 account : 1 portfolio (RECON-03/04, LX-04).
* ``test_restart_rehydrate_then_venue_reconcile_no_spurious_halt`` — a restart rehydrate +
  two-sided venue reconcile against the OKX-demo REST snapshot adopts in-band deltas with NO
  halt-and-alert, and a post-restart fill for a rehydrated resting order reaches the mirror
  instead of being silently buffered (RECON-05/RES-01; via the 05-11 adopt_venue_correlation seam).

All connector/system imports are LAZY (inside the test/helper bodies) so a credential-free
collection never touches connector code (``ccxt.pro``). 4-space indentation throughout.
"""

import os
import pathlib
import queue
import time
from decimal import Decimal

import pytest

_OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
_HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)

# The folder-derived TYPE marker (``e2e``) is auto-applied by the root conftest; ``slow`` +
# ``live`` are added by hand here because this suite makes a real network round-trip against
# OKX demo. ``slow`` keeps it selectable via ``-m slow`` (the ``make test-live`` file target);
# ``live`` is what makes ``make test`` (``-m "not live"``) STRUCTURALLY exclude it — the
# credential skip-gate alone is not a network guard once ``.env`` creds are exported, so the
# ``live`` marker is the real "default run never touches the venue" fence (D-20 CONF-B). The
# single online GREEN gate is human-triggered via ``-m live`` (or the ``-m slow`` file target).
pytestmark = [
    pytest.mark.slow,
    pytest.mark.live,
    pytest.mark.skipif(
        not _HAS_OKX_CREDS,
        reason=(
            "OKX demo credentials absent — opt-in sandbox reconciliation suite skipped "
            "(D-09/RECON-06). Set OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (demo "
            "env) to enable."
        ),
    ),
]

# --- Pinned demo-order parameters (min-size, liquid demo symbol — T-05-12-02) ---
_OKX_SYMBOL = "BTC/USDC"          # must equal _OKX_STREAM_SYMBOL (drives strategy tickers ->
                                  # universe.members AND the order symbol). BTC/USDC, not USDT:
                                  # OKX EEA restricts USDT spot pairs under MiCA (sCode 51155).
_MIN_DEMO_QTY = Decimal("0.0001")  # tiny base quantity, comfortably above the venue min lot
_PRICE_ESTIMATE = Decimal("100000")  # cosmetic decision-price estimate (market fill uses venue px)
_DEMO_PORTFOLIO_CASH = 100_000     # superseded by the VenueAccount cache on start()

# Bounded observation windows — a live venue round-trip, never a blocking queue.get.
_FILL_TIMEOUT_S = 30.0
_POLL_S = 0.5
_STOP_TIMEOUT_S = 10.0
_POSITION_PRECISION = 8            # BTC amount precision for the drift-tolerance epsilon

# --- CONF-B settlement / ARCH-3 finalization capture (D-20) ------------------
# The CONF-B extension asserts a real demo fill SETTLES (position + cash + not-HALTED
# + spot venue truth) — the blind spot the pre-05.1 suite lacked (it asserted only the
# order mirror + emitted fills, which let V17-01 pass 8/8). Assertions are
# tolerance-banded, never exact-float: an OKX spot BUY may deduct the fee from the base
# asset received (delta ≈ cost) OR from quote (delta ≈ cost*(1+fee)), and the true
# fee-currency behaviour is exactly what the human-gated online run records.
_SETTLE_QTY_FEE_BAND = Decimal("0.01")   # base-fee deduction floor on settled qty / cost
_SETTLE_CASH_FEE_BAND = Decimal("0.02")  # quote-fee ceiling on the cash decrease
_QUOTE_CCY = "USDC"                       # _OKX_SYMBOL quote (BTC/USDC — NOT the USDT default)
_BASE_CCY = "BTC"                         # _OKX_SYMBOL base

# The four ARCH-3 finalization points land here (D-20). SECURITY (T-05.1-16): the
# capture records payload SHAPES / ids / counts ONLY — never OKX_API_* secrets and never
# a raw ``info`` dump. Written ONLY on the human-triggered online run (inside a test body,
# never at collection).
_CAPTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / ".planning" / "debug"


# --------------------------------------------------------------------------- helpers


def _build_live_okx_stack():
    """Lazily compose the live OKX stack (sandbox connector + arms) WITHOUT starting it.

    Mirrors ``scripts/run_live_paper.py::_compose`` — the golden SMA_MACD strategy plus one
    portfolio — but the portfolio's exchange arm is ``"okx"`` (the demo order target) rather
    than the paper ``"simulated"`` exchange. Returns the un-started system so the TEST owns the
    start()/stop() lifecycle and teardown stays in the test (Pitfall 4 — no leaked authenticated
    session). ALL connector/system imports are LAZY here so a credential-free collection never
    touches connector code.
    """
    from itrader.core.sizing import FractionOfCash, TradingDirection
    from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
    from itrader.trading_system.live_trading_system import LiveTradingSystem

    system = LiveTradingSystem(exchange="okx")
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=[_OKX_SYMBOL],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="okx_demo_pf",
        exchange="okx",
        cash=_DEMO_PORTFOLIO_CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)
    return system, portfolio_id


def _assert_sandbox_routed(system) -> None:
    """T-05-04 guard: the OKX connector MUST be sandbox-routed before any order submission.

    The demo host (``wspap.okx.com`` / REST ``x-simulated-trading``) is what keeps the demo
    keys real-money-free; a ``sandbox=False`` misroute placing a real-money order is the
    phase's highest-severity threat. Every live test calls this BEFORE submitting.
    """
    assert system._okx_connector is not None, "OKX arm not composed — no connector to route"
    assert system._okx_connector.sandbox is True


def _install_emit_spy(system):
    """Wrap ``OkxExchange._emit_fill`` to record every emitted fill (observe, never steal).

    The spy records the raw venue trade + the correlated OrderEvent + venue id, then calls the
    original ``_emit_fill`` (which ``put``s the FillEvent on the queue). It observes at the
    exchange emit seam, so it never intercepts the ``queue.get`` the daemon loop drains. Returns
    the mutable record list.
    """
    emitted = []
    exchange = system._okx_exchange
    original = exchange._emit_fill

    def spy(trade, order, venue_id):
        emitted.append({"trade": trade, "order": order, "venue_id": venue_id})
        return original(trade, order, venue_id)

    exchange._emit_fill = spy
    return emitted


def _submit_min_demo_order(system, portfolio_id):
    """Store a tiny MARKET-BUY demo order in the mirror and enqueue its OrderEvent (NEW).

    The Order entity is added to the storage mirror (PENDING) so ``OrderHandler.on_fill`` can
    reconcile it to FILLED when the real venue fill streams back; the ``OrderEvent`` is enqueued
    onto ``global_queue`` so the daemon loop routes it via ``ExecutionHandler.on_order`` ->
    ``OkxExchange._submit_order`` (the direct-event path skips the sizing/admission gate).
    Returns the stored Order.
    """
    from datetime import datetime, timezone

    import uuid_utils.compat as uc

    from itrader.core.enums import OrderCommand, OrderStatus, OrderType, Side
    from itrader.core.ids import StrategyId
    from itrader.events_handler.events import OrderEvent
    from itrader.order_handler.order import Order

    order = Order(
        time=datetime.now(timezone.utc),
        type=OrderType.MARKET,
        status=OrderStatus.PENDING,
        ticker=_OKX_SYMBOL,
        action=Side.BUY,
        price=_PRICE_ESTIMATE,
        quantity=_MIN_DEMO_QTY,
        exchange="okx",
        strategy_id=StrategyId(uc.uuid7()),
        portfolio_id=portfolio_id,
    )
    system._order_storage.add_order(order)
    system.global_queue.put(OrderEvent.new_order_event(order, OrderCommand.NEW))
    return order


def _wait_for_fill(system, order):
    """Poll the stored order mirror until it terminalizes to FILLED (bounded timeout).

    Polls ``OrderHandler.get_order_by_id`` — the observation seam that does NOT intercept the
    queue the daemon loop is draining. Returns the latest Order snapshot (the caller asserts the
    terminal state); returns ``None`` only if the mirror lookup misses entirely.
    """
    from itrader.core.enums import OrderStatus

    deadline = time.monotonic() + _FILL_TIMEOUT_S
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = system.order_handler.get_order_by_id(order.id)
        if snapshot is not None and snapshot.status == OrderStatus.FILLED:
            return snapshot
        time.sleep(_POLL_S)
    return snapshot


def _assert_trade_id_dedup(system, emitted) -> None:
    """Exercise ``_seen_trade_ids``: re-delivering a seen venue trade yields NO second fill.

    Picks a captured raw venue trade with an id, asserts it was emitted exactly once, then
    re-invokes ``_handle_trade`` with the SAME trade — the dedup set must make it an idempotent
    no-op (no new FillEvent emitted). This is a deterministic, no-network dedup check.
    """
    def _count(trade_id):
        return sum(
            1 for r in emitted
            if isinstance(r["trade"], dict) and r["trade"].get("id") == trade_id
        )

    dedupable = [
        r for r in emitted
        if isinstance(r["trade"], dict) and r["trade"].get("id")
    ]
    assert dedupable, "no venue trade id captured to exercise dedup"
    trade = dedupable[0]["trade"]
    trade_id = trade["id"]
    assert _count(trade_id) == 1, "a single venue trade id was emitted more than once"

    # Re-deliver the exact same venue trade — _seen_trade_ids must dedup it.
    system._okx_exchange._handle_trade(trade)
    time.sleep(1.0)
    assert _count(trade_id) == 1, "duplicate venue trade id yielded a second FillEvent (dedup broken)"


def _cleanup_and_stop(system) -> None:
    """Cancel any resting demo order the test left, then stop the system (teardown-safe).

    Best-effort: enqueue a CANCEL OrderEvent for every still-active order, give the loop a beat
    to drain it, then ``stop()`` unconditionally so no authenticated socket leaks under
    ``filterwarnings=["error"]`` (T-05-12-02).
    """
    from itrader.core.enums import OrderCommand
    from itrader.events_handler.events import OrderEvent

    try:
        for order in system.order_handler.get_active_orders():
            system.global_queue.put(OrderEvent.new_order_event(order, OrderCommand.CANCEL))
        time.sleep(1.0)
    finally:
        system.stop(timeout=_STOP_TIMEOUT_S)


# --- restart-reconcile helpers (test (iii) — mirror test_two_sided_restart's shape) ---

_OPERATIONAL_TABLES = ("order_state_changes", "orders", "signals")


class _HaltRecorder:
    """Records every ``halt(reason)`` call so the test can assert no spurious halt fired."""

    def __init__(self) -> None:
        self.reasons: list = []

    def __call__(self, reason: str) -> None:
        self.reasons.append(reason)


def _build_demo_connector():
    """Lazily construct + connect a sandbox-routed ``OkxConnector`` (network I/O)."""
    from itrader.config.okx_settings import OkxSettings
    from itrader.connectors.okx import OkxConnector

    connector = OkxConnector(OkxSettings())  # type: ignore[call-arg]
    connector.connect()
    return connector


def _seed_believed_position_to_venue(system, portfolio_id):
    """TEST-ONLY: seed the engine's believed BTC/USDC position to the LIVE venue balance.

    The only OKX demo account available is NON-FLAT: OKX pre-seeds ~1 BTC and the EEA/MiCA
    account cannot be sold flat (sells blocked by a price-floor > best-bid). On such an
    account ``_run_session_baseline_guard`` (live_trading_system.py:579) reads a base-asset
    residual and latches ``halt('baseline-residual')`` inside ``start()`` — the two online
    start()-driven tests never reach RUNNING.

    This helper reads the live venue BTC balance READ-ONLY (via an independent sandbox
    connector — the system connector is not yet connected pre-``start()``) and seeds the
    believed BTC/USDC position to match it BEFORE ``start()``, so the guard reads
    ``engine_qty == venue_qty`` and lets the session reach RUNNING. The read places NO order.
    ``set_position`` is a pure position-only dict write (``PositionManager`` is cash-agnostic,
    D-06), so ``cash_before`` — snapshotted after ``start()`` — is unaffected by the seed.

    On a genuinely FLAT account (venue base total 0 or absent) the seed is a no-op and the
    original flat-start behavior is unchanged. Returns the seeded ``venue_qty`` (Decimal).
    All imports are LAZY (inside this body) so credential-free collection never touches
    connector code.
    """
    from datetime import datetime, timezone

    import uuid_utils.compat as uc

    from itrader.core.enums import TransactionType
    from itrader.core.ids import TransactionId
    from itrader.core.money import to_money
    from itrader.portfolio_handler.position.position import Position
    from itrader.portfolio_handler.transaction.transaction import Transaction

    # READ-ONLY: read the live venue BTC balance via a throwaway sandbox connector.
    connector = _build_demo_connector()
    try:
        bal = connector.call(connector.client.fetch_balance())
        total = bal.get("total", {}) if isinstance(bal, dict) else {}
        base_raw = total.get(_BASE_CCY) if isinstance(total, dict) else None
    finally:
        try:
            connector.disconnect()
        except Exception:
            pass

    if base_raw is None:
        return Decimal("0")   # no venue balance key — genuinely flat, seed is a no-op.

    # Decimal edge — never Decimal(float); matches the guard's venue_qty byte-for-byte.
    venue_qty = to_money(str(base_raw))
    if venue_qty == 0:
        return Decimal("0")   # flat account — original flat-start path intact.

    txn = Transaction(
        time=datetime.now(timezone.utc),
        type=TransactionType.BUY,
        ticker=_OKX_SYMBOL,
        price=_PRICE_ESTIMATE,
        quantity=venue_qty,
        commission=Decimal("0"),
        portfolio_id=portfolio_id,
        id=TransactionId(uc.uuid7()),
        fill_id=uc.uuid7(),
    )
    position = Position.open_position(txn)
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    portfolio.position_manager._storage.set_position(_OKX_SYMBOL, position)
    return venue_qty


def _start_pg_container():
    """Start a testcontainers Postgres (rehydrate substrate); skip if Docker is absent (D-11)."""
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
    return container, container.get_connection_url()


def _make_backend(pg_url):
    """Build a fresh ``SqlBackend`` bound to the container DB."""
    from pydantic import SecretStr

    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage import SqlBackend

    return SqlBackend(SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        url=SecretStr(pg_url),
    ))


def _fresh_cached_store(backend):
    """Build a ``CachedSqlOrderStorage`` over the backend (idempotent schema create)."""
    from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
    from itrader.order_handler.storage.sql_storage import SqlOrderStorage

    store = SqlOrderStorage(backend)
    backend.metadata.create_all(backend.engine, checkfirst=True)
    return CachedSqlOrderStorage(store)


def _drop_operational_tables(pg_url) -> None:
    """Drop the operational tables so the shared container DB is left pristine."""
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            for table in _OPERATIONAL_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    finally:
        engine.dispose()


def _drain_queue(gq) -> None:
    """Empty the queue, discarding contents (clears reconciling fills before the drain check)."""
    while True:
        try:
            gq.get_nowait()
        except queue.Empty:
            break


def _drain_fills(gq):
    """Drain every ``FillEvent`` currently on the queue."""
    from itrader.events_handler.events import FillEvent

    fills = []
    while True:
        try:
            event = gq.get_nowait()
        except queue.Empty:
            break
        if isinstance(event, FillEvent):
            fills.append(event)
    return fills


# ------------------------------------------------ CONF-B settlement + ARCH-3 (D-20)


def _order_fills(emitted, order):
    """Raw venue trade dicts the emit spy captured for the submitted order."""
    return [
        r["trade"] for r in emitted
        if r["order"].order_id == order.id and isinstance(r["trade"], dict)
    ]


def _sum_filled_qty(order_trades):
    """Total venue-reported base quantity across the order's fills (Decimal edge)."""
    return sum((Decimal(str(t["amount"])) for t in order_trades), Decimal("0"))


def _sum_fill_cost(order_trades):
    """Total quote notional (price*amount) across the order's fills (Decimal edge)."""
    return sum(
        (Decimal(str(t["price"])) * Decimal(str(t["amount"])) for t in order_trades),
        Decimal("0"),
    )


def _assert_settlement(system, portfolio_id, order, emitted, cash_before, position_before):
    """D-20 CONF-B: the four Wave-1 settlement assertions the pre-05.1 suite lacked.

    The prior suite asserted only the order mirror + emitted fills, NEVER the portfolio
    position/cash — the exact blind spot that let V17-01 pass 8/8. These four HARD
    assertions prove a real demo fill SETTLES. Tolerance-banded (never exact float
    equality): an OKX spot BUY may deduct the fee from the base asset received, so the
    settled qty / cash-delta straddle a cost..cost*(1+fee) band. Returns the measured
    values so the ARCH-3 capture can record them without a second network round-trip.

    The POSITION check asserts the BUY's DELTA (``pos.net_quantity - position_before``),
    not the absolute post-fill net_quantity — the online proof runs against a NON-FLAT
    demo account pre-seeded to the venue baseline (see ``_seed_believed_position_to_venue``),
    so only the fill-induced delta is meaningful.
    """
    from itrader.core.enums import SystemStatus

    order_trades = _order_fills(emitted, order)
    assert order_trades, (
        "no venue trade captured for the submitted order — cannot assert settlement")
    filled_qty = _sum_filled_qty(order_trades)
    fill_cost = _sum_fill_cost(order_trades)

    # (1) POSITION settled: non-None with the fill DELTA ≈ the venue-filled qty (within a
    #     base-fee band — a spot BUY fee is frequently taken from the BTC received). The
    #     delta is relative to the pre-seeded non-flat baseline, not the absolute qty.
    pos = system.portfolio_handler.get_position(portfolio_id, _OKX_SYMBOL)
    assert pos is not None, (
        f"portfolio has no {_OKX_SYMBOL} position after a real demo fill — settlement "
        f"never reached the portfolio (V17-01 blind spot)")
    delta_qty = pos.net_quantity - position_before
    assert delta_qty > 0
    assert delta_qty <= filled_qty
    assert delta_qty >= filled_qty * (Decimal("1") - _SETTLE_QTY_FEE_BAND), (
        f"settled qty delta {delta_qty} below the fee-band floor of venue-filled "
        f"{filled_qty}")

    # (2) CASH decreased by ≈ cost+fee — settlement debited the ledger.
    cash_after = system.portfolio_handler.available_cash(portfolio_id)
    delta = cash_before - cash_after
    assert delta > 0, (
        f"portfolio cash did not decrease after a real BUY fill (before={cash_before} "
        f"after={cash_after}) — settlement did not debit cash")
    assert delta >= fill_cost * (Decimal("1") - _SETTLE_QTY_FEE_BAND)
    assert delta <= fill_cost * (Decimal("1") + _SETTLE_CASH_FEE_BAND), (
        f"cash decrease {delta} exceeds cost {fill_cost} + fee band — unexpected debit")

    # (3) STATUS is NOT latched HALTED — a clean settle must not have halted the engine.
    status = system.get_status()
    assert status["status"] != SystemStatus.HALTED.value, (
        f"engine HALTED after a clean demo fill: {status.get('halt_reason')!r}")

    # (4) SPOT venue truth: fetch_positions() is [] for the spot pair (V17-04 — spot
    #     holdings are balances, not positions; the derivatives channel is structurally
    #     blind here). This is also ARCH-3 finalization point #3.
    positions_payload = system._okx_connector.call(
        system._okx_connector.client.fetch_positions([_OKX_SYMBOL]))
    assert positions_payload == [], (
        f"fetch_positions({_OKX_SYMBOL}) returned {positions_payload!r}, expected [] "
        f"for a spot pair (V17-04)")

    return {
        "filled_qty": filled_qty,
        "fill_cost": fill_cost,
        "position_qty": pos.net_quantity,
        "position_before": position_before,
        "position_delta": delta_qty,
        "cash_before": cash_before,
        "cash_after": cash_after,
        "cash_delta": delta,
        "status": status["status"],
        "fetch_positions": positions_payload,
    }


def _venue_order_id_softcheck(system, order, emitted):
    """RECORDED soft-check (pending D-06 / Phase 05.2) — records, never hard-fails.

    The stored order's ``venue_order_id`` is EXPECTED to be non-NULL post-fill, but the
    venue-ack persistence path (D-06) lands in Phase 05.2 — so this RECORDS its result
    into the CONF-B artifact rather than hard-failing the Wave-1 settlement gate
    (xfail-strict=False semantics expressed as a soft-check so the surrounding HARD
    settlement assertions still run and gate). Its Wave-1 value is DATA, not a blocker.
    """
    stored = system.order_handler.get_order_by_id(order.id)
    stored_vid = getattr(stored, "venue_order_id", None) if stored is not None else None
    emitted_vid = next(
        (r["venue_id"] for r in emitted
         if r["order"].order_id == order.id and r.get("venue_id")),
        None,
    )
    resolved = stored_vid is not None
    return {
        "stored_venue_order_id": stored_vid,
        "emitted_venue_id": emitted_vid,
        "resolved": resolved,
        "status": "RESOLVED" if resolved else "PENDING (expected until D-06 / Phase 05.2)",
    }


def _capture_arch3_finalization(system, order, settlement, venue_id_check):
    """Record the four ARCH-3 CONF-B finalization points to ``.planning/debug/`` (D-20).

    SECURITY (T-05.1-16): records payload SHAPES / ids / counts ONLY — NEVER the
    OKX_API_* secrets and NEVER a raw ccxt ``info`` dump. The four points that finalize
    the provisional ARCH-3 posture for Phase 05.2:
      1. fetch_my_trades window / pagination / id presence
      2. balance payload shape (quote-keyed totals + base-key)
      3. spot fetch_positions() == []  (measured in _assert_settlement, threaded in)
      4. post-fill venue / order id

    Writes ``.planning/debug/05.1-confb-<date>.md`` (the D-20 artifact path). Runs ONLY
    on the human-triggered online run — never at collection.
    """
    from datetime import datetime, timezone

    connector = system._okx_connector

    # --- Point 1: fetch_my_trades window / pagination / id presence ------------
    since_ms = int(order.time.timestamp() * 1000)
    trades = connector.call(
        connector.client.fetch_my_trades(_OKX_SYMBOL, since_ms, None, {"paginate": True}))
    trades = trades or []
    all_have_id = all(t.get("id") for t in trades)
    all_have_order = all(t.get("order") for t in trades)
    any_client_oid = any(t.get("clientOrderId") for t in trades)

    # --- Point 2: balance payload shape (quote-keyed totals + base-key) --------
    bal = connector.call(connector.client.fetch_balance())
    total = bal.get("total", {}) if isinstance(bal, dict) else {}
    free = bal.get("free", {}) if isinstance(bal, dict) else {}
    used = bal.get("used", {}) if isinstance(bal, dict) else {}
    # SCRUB: only the base/quote figures + the currency key-set — never the raw payload.
    currency_keys = sorted(k for k in total.keys()) if isinstance(total, dict) else []

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    out = _CAPTURE_DIR / f"05.1-confb-{date}.md"

    lines = [
        f"# CONF-B (D-20) online settlement + ARCH-3 finalization — {date}",
        "",
        "> Auto-captured by `tests/e2e/test_okx_sandbox_recon.py` on the human-triggered",
        "> online run. Payload SHAPES / ids / counts only — no OKX_API_* secrets (T-05.1-16).",
        "",
        "## Wave-1 settlement assertions (GREEN gate)",
        "",
        f"- position qty (settled): `{settlement['position_qty']}`",
        f"- position before (seeded baseline): `{settlement['position_before']}`",
        f"- position delta (fill-induced): `{settlement['position_delta']}`",
        f"- venue-filled qty: `{settlement['filled_qty']}`",
        f"- fill cost (quote notional): `{settlement['fill_cost']}`",
        f"- cash before / after: `{settlement['cash_before']}` -> `{settlement['cash_after']}`",
        f"- cash delta (cost+fee): `{settlement['cash_delta']}`",
        f"- system status: `{settlement['status']}` (must NOT be `halted`)",
        f"- fetch_positions({_OKX_SYMBOL}): `{settlement['fetch_positions']!r}` (expected `[]`)",
        "",
        "## ARCH-3 finalization point 1 — fetch_my_trades (window / pagination / ids)",
        "",
        f"- since (ms, oldest = order submit): `{since_ms}`",
        "- pagination: `params={'paginate': True}` (since disables `limit` — ccxt quirk)",
        f"- trades returned: `{len(trades)}`",
        f"- all have unified `id` (tradeId): `{all_have_id}`",
        f"- all have unified `order` (ordId): `{all_have_order}`",
        f"- any top-level `clientOrderId` present: `{any_client_oid}`",
        "",
        "## ARCH-3 finalization point 2 — balance payload shape",
        "",
        f"- currency keys in `total`: `{currency_keys}`",
        f"- quote `total[{_QUOTE_CCY}]`: `{total.get(_QUOTE_CCY)}`  "
        f"free: `{free.get(_QUOTE_CCY)}`  used: `{used.get(_QUOTE_CCY)}`",
        f"- base `total[{_BASE_CCY}]`: `{total.get(_BASE_CCY)}`  "
        f"free: `{free.get(_BASE_CCY)}`  used: `{used.get(_BASE_CCY)}`",
        "",
        "## ARCH-3 finalization point 3 — spot fetch_positions() == []",
        "",
        f"- fetch_positions({_OKX_SYMBOL}): `{settlement['fetch_positions']!r}` "
        "(structurally `[]` — spot instType excluded)",
        "",
        "## ARCH-3 finalization point 4 — post-fill venue / order id",
        "",
        f"- stored order.venue_order_id: `{venue_id_check['stored_venue_order_id']}`",
        f"- emitted venue_id (from fill stream): `{venue_id_check['emitted_venue_id']}`",
        f"- resolved: `{venue_id_check['resolved']}` — {venue_id_check['status']}",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- tests


def test_demo_order_produces_real_fill_event() -> None:
    """(i) A tiny demo order flows to a real ``FillEvent`` from the live OKX-demo path (RECON-01/02).

    Builds the sandbox-routed live stack, submits ONE minimum-size demo MARKET order, and asserts
    a real FillEvent streams back, the order mirror terminalizes to FILLED, and venue-trade-id
    dedup holds — reachable only because the 05-10 CR-01 wiring spawns the live fill stream.
    """
    from itrader.core.enums import OrderStatus, SystemStatus

    system, portfolio_id = _build_live_okx_stack()
    _assert_sandbox_routed(system)
    # Seed the believed BTC/USDC position to the live (non-flat) venue balance BEFORE
    # start() so the baseline guard reads engine_qty == venue_qty and reaches RUNNING
    # instead of latching halt('baseline-residual'). No-op on a genuinely flat account.
    _seed_believed_position_to_venue(system, portfolio_id)
    emitted = _install_emit_spy(system)
    try:
        # T-05-04: final routing guard — the connector MUST be sandbox is True before we submit.
        assert system._okx_connector.sandbox is True
        assert system.start() is True
        assert system.get_status()["status"] == SystemStatus.RUNNING.value

        # D-20: snapshot buying power BEFORE the order so the settlement assertion can
        # prove a real fill DEBITED the ledger (not merely produced a FillEvent).
        cash_before = system.portfolio_handler.available_cash(portfolio_id)
        # Snapshot the pre-order believed position (non-flat after the venue seed) so the
        # settlement proof asserts the BUY's DELTA, not the absolute post-fill net_quantity.
        _pos_before = system.portfolio_handler.get_position(portfolio_id, _OKX_SYMBOL)
        position_before = _pos_before.net_quantity if _pos_before is not None else Decimal("0")

        order = _submit_min_demo_order(system, portfolio_id)
        filled = _wait_for_fill(system, order)

        # (a) a real FillEvent for the submitted order was observed within the bounded window.
        order_fills = [r for r in emitted if r["order"].order_id == order.id]
        assert order_fills, "no FillEvent observed for the submitted demo order within timeout"
        # (b) the order mirror terminalized to FILLED.
        assert filled is not None
        assert filled.status == OrderStatus.FILLED
        # (c) dedup holds — a re-sent venue trade id does not yield a second FillEvent.
        _assert_trade_id_dedup(system, emitted)

        # (d) D-20 CONF-B — the SETTLEMENT proof the pre-05.1 suite lacked: a real demo
        #     fill lands in the portfolio (position + cash), does not HALT, and the spot
        #     venue-truth channel is []. These four are the Wave-1 GREEN exit gate.
        settlement = _assert_settlement(
            system, portfolio_id, order, emitted, cash_before, position_before)
        # (e) RECORDED soft-check (pending D-06 / Phase 05.2) — records the post-fill
        #     venue_order_id result without hard-failing the Wave-1 gate.
        venue_id_check = _venue_order_id_softcheck(system, order, emitted)
        # (f) Record the four ARCH-3 finalization points to .planning/debug/ — the input
        #     that finalizes the provisional ARCH-3 posture for Phase 05.2.
        _capture_arch3_finalization(system, order, settlement, venue_id_check)
    finally:
        _cleanup_and_stop(system)


def test_venue_account_reconciles_post_fill_within_tolerance() -> None:
    """(ii) ``VenueAccount`` position reconciles against OKX demo within tolerance (RECON-03/04).

    Reuses the demo-fill flow, then takes a FRESH ``VenueAccount.snapshot()`` (REST venue truth)
    and asserts the engine-computed vs venue per-symbol position diff is WITHIN the drift
    tolerance band via ``is_within_single_unit_tolerance`` (the same predicate
    ``_compare_symbol_drift`` uses) with NO spurious halt, under 1 account : 1 portfolio (LX-04).
    Tolerance-based, never exact float equality.
    """
    from itrader.core.enums import OrderStatus, SystemStatus
    from itrader.portfolio_handler.reconcile.drift import is_within_single_unit_tolerance

    system, portfolio_id = _build_live_okx_stack()
    _assert_sandbox_routed(system)
    # Seed the believed BTC/USDC position to the live (non-flat) venue balance BEFORE
    # start() so the baseline guard reaches RUNNING (see test (i)); the reconcile below
    # still holds because engine and venue both move by the same fill delta from this
    # seeded baseline. No-op on a genuinely flat account.
    _seed_believed_position_to_venue(system, portfolio_id)
    try:
        # T-05-04: final routing guard — the connector MUST be sandbox is True before we submit.
        assert system._okx_connector.sandbox is True
        assert system.start() is True

        order = _submit_min_demo_order(system, portfolio_id)
        filled = _wait_for_fill(system, order)
        assert filled is not None
        assert filled.status == OrderStatus.FILLED

        # Fresh REST snapshot of venue truth (post-fill).
        system._venue_account.snapshot()
        venue_positions = system._venue_account.positions

        # Per-symbol engine-vs-venue drift WITHIN one least-significant unit — never beyond band.
        for symbol, venue_qty in venue_positions.items():
            engine_view = system.portfolio_handler.get_position(portfolio_id, symbol)
            engine_qty = engine_view.net_quantity if engine_view is not None else Decimal("0")
            assert is_within_single_unit_tolerance(
                engine_qty, venue_qty, _POSITION_PRECISION
            ), f"engine-vs-venue drift for {symbol} beyond tolerance: {engine_qty} vs {venue_qty}"

        # No spurious halt: 1:1 acct:portfolio within-band reconcile must not HALT (RECON-04).
        status = system.get_status()
        assert status["status"] != SystemStatus.HALTED.value
        assert status["halt_reason"] is None
    finally:
        _cleanup_and_stop(system)


def test_restart_rehydrate_then_venue_reconcile_no_spurious_halt() -> None:
    """(iii) Restart rehydrate + two-sided venue reconcile yields no spurious halt (RECON-05/RES-01).

    Parallels the OFFLINE ``tests/integration/test_two_sided_restart.py`` shape but against the
    REAL demo connector: stand up a rehydrate-capable CachedSql store holding a pre-restart
    resting order carrying a ``venue_order_id``, then construct/drive
    ``VenueReconciler.reconcile()`` against the OKX-demo REST snapshot. Asserts (a) in-band venue
    deltas adopt cleanly with NO halt-and-alert (no ``reconciliation-unresolved``), and (b) via
    the 05-11 ``adopt_venue_correlation`` seam, a post-restart fill for the rehydrated resting
    order reaches the mirror (a FillEvent emits) instead of being silently buffered in the
    unmatched-fill overflow. Requires Docker (testcontainers Postgres) — skips if absent.
    """
    from datetime import datetime, timezone

    import uuid_utils.compat as uc

    from itrader.core.enums import OrderStatus, OrderType, Side
    from itrader.core.ids import PortfolioId, StrategyId
    from itrader.execution_handler.exchanges.okx import OkxExchange
    from itrader.order_handler.order import Order
    from itrader.portfolio_handler.account.venue import VenueAccount
    from itrader.portfolio_handler.reconcile.venue_reconciler import VenueReconciler

    container, pg_url = _start_pg_container()
    backend = _make_backend(pg_url)
    connector = None
    try:
        # Store side (INTENT truth): a pre-restart resting order with a persisted venue id.
        store = _fresh_cached_store(backend)
        venue_ord = "IT-DEMO-REHYDRATE-0001"
        order = Order(
            time=datetime.now(timezone.utc),
            type=OrderType.LIMIT,
            status=OrderStatus.PENDING,
            ticker=_OKX_SYMBOL,
            action=Side.BUY,
            price=Decimal("10000"),   # deep out-of-the-money — it rests, never fills on the venue
            quantity=_MIN_DEMO_QTY,
            exchange="okx",
            strategy_id=StrategyId(uc.uuid7()),
            portfolio_id=PortfolioId(uc.uuid7()),
            venue_order_id=venue_ord,
        )
        store.add_order(order)

        # Venue side (real demo connector): the REST snapshot the reconcile reads.
        connector = _build_demo_connector()
        assert connector.sandbox is True   # T-05-04 — demo host only, before any venue read

        gq: "queue.Queue" = queue.Queue()
        okx_exchange = OkxExchange(gq, connector)
        venue_account = VenueAccount(connector)
        halt = _HaltRecorder()
        reconciler = VenueReconciler(
            store=store,
            venue_account=venue_account,
            connector=connector,
            global_queue=gq,
            halt_signal=halt,
            exchange=okx_exchange,
        )

        # Two-sided restart reconcile against the OKX-demo REST snapshot.
        reconciler.reconcile()

        # (a) in-band deltas adopt cleanly — NO halt-and-alert.
        assert "reconciliation-unresolved" not in halt.reasons

        # (b) the 05-11 adopt seam repopulated the correlation map for the rehydrated order.
        with okx_exchange._index._correlation_lock:
            adopted = okx_exchange._index._venue_id_by_order_id.get(order.id)
        assert adopted == venue_ord

        # A post-restart fill for the rehydrated resting order now RESOLVES (emits a FillEvent)
        # instead of being silently buffered — the ``adopt_venue_correlation`` seam repopulated
        # the correlation above, so ``_handle_trade`` matches the venue id to the OrderEvent and
        # mints the fill (the mirror advances) rather than dropping it into the overflow buffer.
        _drain_queue(gq)   # clear any reconciling fills first
        post_restart_trade = {
            "id": "IT-DEMO-TRADE-REHYDRATE-0001",
            "order": venue_ord,
            "price": 10000.0,
            "amount": float(_MIN_DEMO_QTY),
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "fee": {"cost": 0.0},
        }
        okx_exchange._handle_trade(post_restart_trade)
        fills = _drain_fills(gq)
        assert len(fills) == 1               # resolved + emitted, NOT silently buffered
        assert fills[0].order_id == order.id
    finally:
        if connector is not None:
            try:
                connector.disconnect()
            except Exception:
                pass
        _drop_operational_tables(pg_url)
        backend.dispose()
        container.stop()
