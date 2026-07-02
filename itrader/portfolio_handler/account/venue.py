"""
VenueAccount — venue-cached leaf of the ``Account`` ABC (D-11 seam, RECON-01 body).

``VenueAccount`` is the venue-cached sibling of the ``Simulated*`` leaves: where
``SimulatedCashAccount`` / ``SimulatedMarginAccount`` *compute* balance/margin
truth, ``VenueAccount`` *caches* the venue's truth (balances / positions streamed
or polled from the connector). Its stable contract comes from the ``Account`` ABC
(D-01) — **not** from the connector — so it does not need a rich ``LiveConnector``
signature (D-11 avoids the premature-interface trap of freezing connector
signatures before the integration exists).

Phase 5 lands the cached-venue body (RECON-01 / D-14 / D-15): an RLock-guarded
balance/available/position cache, an async push writer that mirrors the venue's
private stream (cache-write ONLY on the connector loop thread — it NEVER compares
and NEVER halts, D-15 single-writer discipline), a REST ``snapshot()`` for
startup / restart / gap recovery (D-14/D-19), engine-thread reads that surface a
typed ``StateError`` when the cache is still unsnapshotted (never a silent 0), and
a local pending-reservation overlay for ``reserve`` / ``release`` (Open Question 1
resolution — the venue owns the real reservation; the overlay keeps the
order-admission gate working pre-fill). The drift COMPARE and the halt DECISION do
NOT live here — they run on the engine thread in a later plan (05-04). The venue is
the source of truth in live: it CACHES, it does not RECOMPUTE (Pitfall 10).

Import discipline (inertness gate, CONN-04): this leaf is re-exported from the
``account`` barrel, which the backtest hot path imports (``SimulatedCashAccount``).
``LiveConnector`` is therefore imported ONLY under ``TYPE_CHECKING`` — a runtime
import of the ``itrader.connectors`` barrel would pull it (and ``ccxt.pro``) onto
the backtest import path and fail the hot-path inertness gate.
IN-01 (defence in depth): the type-only import is sourced from the ccxt-free
``itrader.connectors.base`` module, not the barrel, so even if this guard were
ever relaxed to a runtime import it would still not couple the hot path to
``ccxt.pro``.
"""

import threading
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError,
    StateError,
)
from itrader.core.ids import OrderId
from itrader.core.money import to_money

from .base import Account

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector


class VenueAccount(Account):
    """
    Venue-cached ``Account`` leaf — caches venue truth, never recomputes (D-14).

    Satisfies the ``Account`` ABC (``balance`` / ``available`` /
    ``reserve(order_id, amount)`` / ``release(order_id)``) by CACHING the venue's
    streamed / polled truth rather than computing it. The async push writer
    (``_stream_account`` / ``_stream_positions``) writes the RLock-guarded cache
    ONLY on the connector loop thread and never compares/halts (D-15); the REST
    ``snapshot()`` populates the cache for startup / restart / gap (D-14/D-19).
    Engine-thread reads raise ``StateError`` when the cache is still unsnapshotted
    (never a silent 0). ``reserve`` / ``release`` keep a local pending-reservation
    overlay on top of cached venue-available (the venue owns the real reservation;
    the overlay keeps the admission gate working pre-fill — Open Question 1).

    Money (D-12): every venue float crosses the Decimal boundary via
    ``to_money(str(x))`` (never ``Decimal(float)``); None/missing keys are guarded
    BEFORE the edge (mirrors the ``okx.py`` fee-guard).
    """

    def __init__(self, connector: "LiveConnector", quote_currency: str = "USDT") -> None:
        """Bind the injected session and stand up the venue cache (D-04 / D-14).

        The composition root builds the concrete ``OkxConnector`` once and injects
        the ``LiveConnector`` session here; this leaf holds it for the cached-venue
        body. No stream is started here — the root wires and starts it via
        ``start_streaming`` (05-04) so lifecycle stays at the root.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol (never the concretion, D-04).
        quote_currency : str
            The quote-currency key read out of the ccxt-unified balance payloads
            (``total``/``free`` maps). Defaults to ``"USDT"`` (the OKX spot quote).
        """
        # D-04: the injected session Protocol, NOT the concretion.
        self._connector = connector
        self._quote = quote_currency

        # D-14/D-15: RLock-guarded venue cache. Written ONLY on the connector loop
        # thread (async push) or on a snapshot call; read on the engine thread. All
        # None/empty until first snapshotted — a read before then surfaces loud.
        self._lock = threading.RLock()
        self._venue_balance: Decimal | None = None
        self._venue_available: Decimal | None = None
        self._venue_positions: dict[str, Decimal] = {}  # symbol -> signed qty

        # Open Question 1: local pending-reservation overlay keyed by order id.
        # The venue owns the real reservation; this keeps the admission gate
        # working pre-fill and is reconciled to venue truth on the next snapshot.
        self._pending: dict[str, Decimal] = {}

        # Spawned stream-task handles (cancelled by the connector on disconnect).
        self._stream_handles: list[Any] = []

    # --- Decimal-edge parsers (None/missing guarded BEFORE the edge) -----------

    def _extract_balance(self, payload: Any) -> tuple[Decimal | None, Decimal | None]:
        """Extract ``(total, free)`` for the quote currency from a ccxt balance payload.

        Returns a ``(balance, available)`` pair, each ``None`` when the venue did
        not carry that field. Every venue float crosses the Decimal boundary via
        ``to_money(str(x))``; None/missing keys are guarded BEFORE the edge so a
        missing value never becomes ``Decimal("None")`` (money policy, Pitfall 6).
        """
        total_map = payload.get("total") if isinstance(payload, dict) else None
        free_map = payload.get("free") if isinstance(payload, dict) else None
        total_raw = total_map.get(self._quote) if isinstance(total_map, dict) else None
        free_raw = free_map.get(self._quote) if isinstance(free_map, dict) else None
        balance = to_money(str(total_raw)) if total_raw is not None else None
        available = to_money(str(free_raw)) if free_raw is not None else None
        return balance, available

    def _extract_positions(self, payload: Any) -> dict[str, Decimal]:
        """Extract ``symbol -> signed qty`` from a ccxt positions payload.

        A ``short`` side flips the sign so the cache carries a signed quantity.
        Entries missing a symbol or contract size are skipped; every contract size
        crosses the Decimal edge via ``to_money(str(x))`` (never ``Decimal(float)``).
        """
        result: dict[str, Decimal] = {}
        if not isinstance(payload, list):
            return result
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            symbol = entry.get("symbol")
            contracts = entry.get("contracts")
            if symbol is None or contracts is None:
                continue
            qty = to_money(str(contracts))  # Decimal edge
            if entry.get("side") == "short":
                qty = -qty
            result[str(symbol)] = qty
        return result

    # --- async push (D-14 push writer — cache-write ONLY, never compare/halt) ---

    async def _stream_account(self) -> None:
        """Consume the venue balance stream forever, writing the cache ONLY (D-15).

        Mirrors ``OkxExchange._stream_fills``: cache-write on the connector loop
        thread, NEVER a drift compare and NEVER a halt (the compare lives on the
        engine thread in 05-04). Each venue float crosses the Decimal edge in
        ``_extract_balance``; a missing field leaves the prior cache value intact.
        """
        while True:
            update = await self._connector.client.watch_balance()
            balance, available = self._extract_balance(update)
            with self._lock:
                if balance is not None:
                    self._venue_balance = balance
                if available is not None:
                    self._venue_available = available

    async def _stream_positions(self) -> None:
        """Consume the venue positions stream forever, writing the cache ONLY (D-15).

        Same single-writer discipline as ``_stream_account`` — cache-write on the
        connector loop thread only, never compare/halt.
        """
        while True:
            update = await self._connector.client.watch_positions()
            positions = self._extract_positions(update)
            with self._lock:
                self._venue_positions = positions

    def start_streaming(self) -> None:
        """Spawn the venue push streams via the injected connector (root-wired, 05-04).

        The composition root calls this AFTER ``connect()`` so the connector owns
        the loop lifecycle (the spawned handles are cancelled by the connector on
        ``disconnect``). Not started in ``__init__`` — wiring stays at the root.
        """
        self._stream_handles = [
            self._connector.spawn(self._stream_account()),
            self._connector.spawn(self._stream_positions()),
        ]

    # --- REST snapshot (D-14/D-19 — startup / restart / gap recovery) ----------

    def snapshot(self) -> None:
        """Populate the cache from a REST snapshot (startup / restart / gap, D-14/D-19).

        A synchronous RPC via ``connector.call`` (like ``okx_provider`` backfill):
        fetch the venue balance + positions and write the cache under the lock.
        Every venue float crosses the Decimal edge in the parsers; a missing
        balance field leaves the prior cache value intact rather than clobbering it.
        The positions cache is fully replaced (the REST snapshot is authoritative)
        and the pending-reservation overlay is naturally reconciled to venue truth
        as the next admission cycle reads the refreshed available.
        """
        bal = self._connector.call(self._connector.client.fetch_balance())
        pos = self._connector.call(self._connector.client.fetch_positions())
        balance, available = self._extract_balance(bal)
        positions = self._extract_positions(pos)
        with self._lock:
            if balance is not None:
                self._venue_balance = balance
            if available is not None:
                self._venue_available = available
            self._venue_positions = positions

    # --- engine-thread reads (D-15 — surface unsnapshotted loud, never 0) -------

    @property
    def balance(self) -> Decimal:
        """Cached venue balance (D-14) — reads the cache under the lock.

        Raises ``StateError`` when the cache is still unsnapshotted (never a silent
        0 that could authorize a bad order — T-05-07).
        """
        with self._lock:
            if self._venue_balance is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="balance",
                )
            return self._venue_balance

    @property
    def available(self) -> Decimal:
        """Cached venue available net of the local pending-reservation overlay (D-14).

        ``cached_venue_available − Σ local_pending`` (Open Question 1) so the
        order-admission gate keeps working pre-fill. Raises ``StateError`` when the
        cache is still unsnapshotted (never a silent 0 — T-05-07).
        """
        with self._lock:
            if self._venue_available is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="available",
                )
            return self._venue_available - self._pending_total()

    @property
    def positions(self) -> dict[str, Decimal]:
        """Cached venue positions (symbol -> signed qty) — a copy read under the lock.

        An empty map means the venue reported no open positions (or the cache is
        not yet snapshotted). Positions are a set-membership read, so unlike
        balance/available an empty map is a valid answer, not a silent-0 hazard.
        """
        with self._lock:
            return dict(self._venue_positions)

    def _pending_total(self) -> Decimal:
        """Sum the local pending-reservation overlay (caller holds the lock)."""
        total = Decimal("0")
        for amount in self._pending.values():
            total += amount
        return total

    # --- reserve / release (Open Question 1 — local pending overlay) -----------

    def reserve(self, order_id: OrderId, amount: Decimal) -> None:
        """Reserve ``amount`` for a pending order via the local overlay (D-14, OQ1).

        The venue is the TRUE owner of the reservation; this is a LOCAL admission
        aid that lets the order-admission gate work pre-fill. Validates ``amount``
        against ``cached_venue_available − Σ local_pending`` (copying the
        ``SimulatedCashAccount.reserve`` validation/raise shape) and records the
        pending entry keyed by ``order_id`` at FULL precision. The overlay is
        reconciled to venue truth on the next ``snapshot()``.

        Raises
        ------
        InvalidTransactionError
            When ``amount`` is not positive.
        InsufficientFundsError
            When ``amount`` exceeds cached available (nothing is reserved).
        StateError
            When the cache is still unsnapshotted.
        """
        amount_decimal = to_money(amount)
        if amount_decimal <= 0:
            raise InvalidTransactionError(
                "Amount for reservation must be positive",
                {"amount": str(amount_decimal)},
            )
        with self._lock:
            if self._venue_available is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="reserve",
                )
            available = self._venue_available - self._pending_total()
            if available < amount_decimal:
                raise InsufficientFundsError(
                    required_cash=amount_decimal,
                    available_cash=available,
                )
            self._pending[str(order_id)] = amount_decimal

    def release(self, order_id: OrderId) -> None:
        """Release the local pending reservation keyed by ``order_id`` (D-14, OQ1).

        Idempotent: releasing an unknown or already-released reference is a silent
        no-op (mirrors ``SimulatedCashAccount.release``). The venue owns the real
        reservation; this only clears the local admission overlay.
        """
        with self._lock:
            self._pending.pop(str(order_id), None)
