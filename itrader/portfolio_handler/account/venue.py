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
balance/position cache, an async push writer that mirrors the venue's
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
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

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

    def __init__(
        self,
        connector: "LiveConnector",
        quote_currency: str = "USDT",
        *,
        market_type: Literal["spot", "derivative"] = "derivative",
        symbol: str | None = None,
    ) -> None:
        """Bind the injected session and stand up the venue cache (D-04 / D-14 / D-03).

        The composition root builds the concrete ``OkxConnector`` once and injects
        the ``LiveConnector`` session here; this leaf holds it for the cached-venue
        body. No stream is started here — the root wires and starts it via
        ``start_streaming`` (05-04) so lifecycle stays at the root.

        Per-market-type venue truth (D-03): OKX SPOT has NO position rows
        (``fetch_positions``/``watch_positions`` return ``[]``), so the wired spot
        pair's per-symbol position truth is DERIVED from the base-currency balance
        total (``total[BASE]``) rather than the derivatives positions channel; a
        ``derivative`` market type keeps the unchanged ``_extract_positions`` channel.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol (never the concretion, D-04).
        quote_currency : str
            The quote-currency key read out of the ccxt-unified balance payloads
            (``total``/``free`` maps). The default ``"USDT"`` is a fallback only —
            the composition root threads the WIRED pair's real quote (e.g. USDC for
            the EEA/MiCA BTC/USDC pair, D-03); the root wiring lands in 05.1-08.
        market_type : {"spot", "derivative"}
            Selects the position-truth channel (D-03). ``"derivative"`` (default,
            backward-compatible) reads ``fetch_positions``/``watch_positions``;
            ``"spot"`` derives the per-symbol holding from ``total[BASE]``.
        symbol : str | None
            The wired traded pair (e.g. ``"BTC/USDC"``). Required for spot truth —
            the derived base holding is keyed under this symbol and the base currency
            is taken from its left leg (``BTC``). Unused for derivative market types.
        """
        # D-04: the injected session Protocol, NOT the concretion.
        self._connector = connector
        self._quote = quote_currency

        # D-03: per-market-type venue-truth channel. ``_base`` is the base-currency
        # key read out of ``total`` for spot position truth (left leg of the pair).
        self._market_type = market_type
        self._symbol = symbol
        self._base = symbol.split("/")[0] if symbol is not None else None

        # D-14/D-15: RLock-guarded venue cache. Written ONLY on the connector loop
        # thread (async push) or on a snapshot call; read on the engine thread. All
        # None/empty until first snapshotted — a read before then surfaces loud.
        self._lock = threading.RLock()
        self._venue_balance: Decimal | None = None
        self._venue_positions: dict[str, Decimal] = {}  # symbol -> signed qty

        # Open Question 1: local pending-reservation overlay keyed by order id.
        # The venue owns the real reservation; this keeps the admission gate
        # working pre-fill and is reconciled to venue truth on the next snapshot.
        self._pending: dict[str, Decimal] = {}

        # D-01 (ARCH-1) locally-ledgered settlement: the venue is source of truth
        # but we do NOT recompute from it on every read (cache-not-recompute,
        # D-14). ``_ledger_delta`` is the signed sum of locally-applied fill cash
        # flows since the last venue reconcile — settled cash = cached venue
        # balance + this delta. ``apply_fill_cash_flow`` mutates it (so a fill
        # settles into the account exploiting the 1:1 VenueAccount<->portfolio
        # topology, live_trading_system.py:554); ``snapshot()`` resets it to zero
        # (the fresh REST balance already reflects the settled fills — reconcile).
        self._ledger_delta: Decimal = Decimal("0")

        # Spawned stream-task handles (cancelled by the connector on disconnect).
        self._stream_handles: list[Any] = []

    # --- Decimal-edge parsers (None/missing guarded BEFORE the edge) -----------

    def _extract_balance(self, payload: Any) -> Decimal | None:
        """Extract the settled ``total`` for the quote currency from a ccxt balance payload.

        Returns the quote ``total`` as ``Decimal``, or ``None`` when the venue did
        not carry it. Every venue float crosses the Decimal boundary via
        ``to_money(str(x))``; None/missing keys are guarded BEFORE the edge so a
        missing value never becomes ``Decimal("None")`` (money policy, Pitfall 6).

        WR-03: the venue ``free`` map is deliberately NOT parsed. Admission is
        governed by the local pending-reservation overlay (Open Question 1), so
        ``available_balance`` nets against the settled ``balance`` — never the venue
        ``free`` field — and the parsed venue-free value had no reader.
        """
        total_map = payload.get("total") if isinstance(payload, dict) else None
        total_raw = total_map.get(self._quote) if isinstance(total_map, dict) else None
        return to_money(str(total_raw)) if total_raw is not None else None

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

    def _extract_spot_position(self, payload: Any) -> dict[str, Decimal]:
        """Derive spot per-symbol position truth from the BASE-currency balance total (D-03).

        OKX SPOT reports NO position rows (``fetch_positions``/``watch_positions``
        return ``[]``): the real per-symbol holding lives in the balance payload's
        ``total[BASE]`` map. Reads ``total[self._base]`` — guarding None/missing keys
        BEFORE the ``to_money(str(x))`` edge (never ``Decimal(float)``) — and keys it
        under the wired ``symbol``. A zero (or absent) base total is a FLAT position,
        surfaced as an empty map (no row), mirroring the derivative channel which
        reports no row when flat. Returns ``{}`` when the spot pair is unconfigured
        (``symbol``/``base`` unset) so an unwired leaf is structurally inert.
        """
        if self._symbol is None or self._base is None:
            return {}
        total_map = payload.get("total") if isinstance(payload, dict) else None
        base_raw = total_map.get(self._base) if isinstance(total_map, dict) else None
        if base_raw is None:
            return {}
        qty = to_money(str(base_raw))  # Decimal edge
        if qty == 0:
            return {}
        return {self._symbol: qty}

    def _spot_positions_from_balance(self, payload: Any) -> dict[str, Decimal] | None:
        """Derive the spot holding to WRITE, or ``None`` to leave the cache intact (WR-02).

        A partial/quote-only ``watch_balance`` push that OMITS the base key must NOT
        clobber the derived holding to flat — returning ``None`` tells the caller to
        keep the prior cache (else the next drift sweep reads venue-qty=0 vs a live
        engine position and spuriously halts). A frame that DOES carry the base key
        is authoritative: it returns the derived map (an empty ``{}`` when the base
        total is zero — a real FLAT that correctly clears the holding). Returns
        ``None`` for an unwired leaf (``symbol``/``base`` unset) too.
        """
        if self._symbol is None or self._base is None:
            return None
        total_map = payload.get("total") if isinstance(payload, dict) else None
        if not isinstance(total_map, dict) or self._base not in total_map:
            return None
        return self._extract_spot_position(payload)

    # --- async push (D-14 push writer — cache-write ONLY, never compare/halt) ---

    async def _stream_account(self) -> None:
        """Consume the venue balance stream forever, writing the cache ONLY (D-15).

        Mirrors ``OkxExchange._stream_fills``: cache-write on the connector loop
        thread, NEVER a drift compare and NEVER a halt (the compare lives on the
        engine thread in 05-04). Each venue float crosses the Decimal edge in
        ``_write_balance_stream``; a missing field leaves the prior cache value intact.
        """
        while True:
            update = await self._connector.client.watch_balance()
            self._write_balance_stream(update)

    def _write_balance_stream(self, update: Any) -> None:
        """Apply a venue balance push to the cache — POSITIONS only, NEVER the cash baseline.

        Root cause ``okx-venue-cash-double-count``: cash is the two-term surface
        ``balance = _venue_balance + _ledger_delta`` where ``apply_fill_cash_flow``
        (the shared Account-ABC settlement primitive, ``portfolio.py`` spot/margin
        settle) moves ``_ledger_delta`` for EVERY fill. If the balance stream ALSO
        refreshed ``_venue_balance`` to the fill-inclusive venue push, the same fill
        would be counted TWICE — once in the stream-pushed venue balance, once in the
        local ledger — a 2x cash debit (position, which has no ledger overlay, stayed
        single-counted). Resetting the ledger on the stream write is NOT a fix: on the
        live path the venue ``watch_balance`` push routinely LEADS the engine-thread
        ``on_fill`` apply (queue latency), so a reset-then-apply double-counts in the
        opposite order. Cash must be single-channel.

        D-01 keeps ``snapshot()`` as the SOLE cash-reconcile point: it atomically
        re-baselines ``_venue_balance`` AND resets ``_ledger_delta``. Between snapshots
        the local ledger is the only channel that moves cash, so ordering can never
        double-count. The stream's remaining live job is spot position liveness for the
        drift compare (D-03): on spot the per-symbol holding rides the BALANCE stream
        (there is no positions channel), derived from ``total[BASE]``. Derivative
        positions arrive via ``_stream_positions`` instead (unchanged). WR-02:
        ``_spot_positions_from_balance`` returns ``None`` for a base-absent partial
        frame so the guard below leaves the prior holding intact (never a spurious
        clobber-to-flat that would trip the drift halt).
        """
        spot_positions = (
            self._spot_positions_from_balance(update)
            if self._market_type == "spot" else None
        )
        with self._lock:
            if spot_positions is not None:
                self._venue_positions = spot_positions

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

        D-03: a spot leaf does NOT spawn the positions stream — spot has no positions
        channel (``watch_positions`` yields ``[]`` and would clobber the base-derived
        holding). Spot position truth rides ``_stream_account`` (the balance stream);
        only derivative leaves consume ``_stream_positions``.
        """
        handles = [self._connector.spawn(self._stream_account())]
        if self._market_type != "spot":
            handles.append(self._connector.spawn(self._stream_positions()))
        self._stream_handles = handles

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

        D-03: on spot the position truth is DERIVED from the balance payload's
        ``total[BASE]`` (``fetch_positions`` returns ``[]`` for spot), so the
        derivatives positions RPC is skipped and the holding read from ``bal``;
        derivative leaves keep the unchanged ``fetch_positions`` channel.
        """
        bal = self._connector.call(self._connector.client.fetch_balance())
        balance = self._extract_balance(bal)
        if self._market_type == "spot":
            positions = self._extract_spot_position(bal)
        else:
            pos = self._connector.call(self._connector.client.fetch_positions())
            positions = self._extract_positions(pos)
        with self._lock:
            if balance is not None:
                self._venue_balance = balance
                # D-01: the fresh REST balance is venue truth AFTER settlement —
                # reconcile the local fill-delta back to zero (never double-count
                # a fill that the venue snapshot already reflects).
                self._ledger_delta = Decimal("0")
            self._venue_positions = positions

    # --- engine-thread reads (D-15 — surface unsnapshotted loud, never 0) -------

    @property
    def balance(self) -> Decimal:
        """Settled cash balance — cached venue balance + local fill-delta (D-01/D-14).

        ``cached_venue_balance + _ledger_delta`` (cache-not-recompute): the venue
        snapshot/stream is the source of the cached balance; locally-applied fills
        move ``_ledger_delta`` so a fill settles into the account (1:1
        VenueAccount<->portfolio topology). Raises ``StateError`` when the cache is
        still unsnapshotted (never a silent 0 that could authorize a bad order —
        T-05-07).
        """
        with self._lock:
            if self._venue_balance is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="balance",
                )
            return self._venue_balance + self._ledger_delta

    @property
    def available_balance(self) -> Decimal:
        """Settled balance net of the local pending-reservation overlay (D-01/D-14).

        ``balance − Σ local_pending`` (Open Question 1) so the order-admission gate
        keeps working pre-fill. This is the D-01 settlement-surface member (renamed
        from the old ``available``); it nets against the settled ``balance`` — NOT
        the venue ``free`` field — so ``available_balance == balance`` when no
        reservations are outstanding (the admission-read invariant). Raises
        ``StateError`` when the cache is still unsnapshotted (never a silent 0 —
        T-05-07).
        """
        with self._lock:
            if self._venue_balance is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="available_balance",
                )
            return self._venue_balance + self._ledger_delta - self._pending_total()

    @property
    def reserved_balance(self) -> Decimal:
        """Total cash reserved by the local pending-reservation overlay (D-01).

        ``Σ local_pending`` — a clean ``Decimal('0')`` when nothing is reserved. The
        venue owns the real reservation; this is the local admission-overlay figure
        read by ``Portfolio.to_dict``.
        """
        with self._lock:
            return self._pending_total()

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

    # --- settlement surface (D-01 — locally-ledgered, ARCH-1) ------------------

    def assert_funds_invariant(self, required: Decimal) -> None:
        """D-01/D-10 engine-bug guard: raise BEFORE any mutation on a bad debit.

        Compares ``required`` against the settled ``balance`` (cached venue balance
        + local fill-delta) — NOT the reservation-adjusted buying power (the fill
        settles portfolio-first, so the order's own un-released reservation would
        false-positive here, mirroring ``SimulatedCashAccount``). The D-02
        admission reservation gate should have prevented this state; if it fires it
        is an engine bug and the caller stops loudly. Raising here (before
        ``apply_fill_cash_flow`` mutates the ledger) is what keeps a failed
        settlement from leaving a partial mutation (T-05.1-01).

        Args:
            required: The actual net cash cost of the settlement debit.

        Raises:
            InsufficientFundsError: When ``required`` exceeds the settled balance.
            StateError: When the cache is still unsnapshotted (cannot settle
                against an unknown balance).
        """
        with self._lock:
            if self._venue_balance is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="assert_funds_invariant",
                )
            balance = self._venue_balance + self._ledger_delta
        if required > balance:
            raise InsufficientFundsError(
                required_cash=required,
                available_cash=balance,
            )

    def apply_fill_cash_flow(self, amount: Decimal, fee: Decimal, description: str,
                             reference_id: str, timestamp: datetime) -> None:
        """Apply a fill settlement's signed, full-precision cash delta (D-01/D-05/D-06).

        The ONE trade-path cash primitive on the venue leaf: mutates the local
        ``_ledger_delta`` by the SIGNED net cash delta so the fill settles into the
        account (negative for a BUY outflow, positive for a SELL inflow). Full
        precision — deliberately NO 2dp quantize (Pitfall 1: a mid-stream quantize
        would shift the equity curve). ``fee`` is the commission portion already
        included in ``amount`` (single net delta, no separate debit). The delta is
        reconciled back to zero on the next ``snapshot()`` (the fresh REST balance
        already reflects the settled fill).

        Args:
            amount: Signed full-precision net cash delta. No quantization.
            fee: Commission portion already included in ``amount``.
            description: Audit description (unused on the cache leaf — the
                transaction record is the audit home).
            reference_id: Reference id (e.g. transaction id).
            timestamp: Event-derived time (transaction/fill time).
        """
        with self._lock:
            self._ledger_delta += amount

    # --- reserve / release (Open Question 1 — local pending overlay) -----------

    def reserve(self, order_id: OrderId, amount: Decimal) -> None:
        """Reserve ``amount`` for a pending order via the local overlay (D-14, OQ1).

        The venue is the TRUE owner of the reservation; this is a LOCAL admission
        aid that lets the order-admission gate work pre-fill. Validates ``amount``
        against ``available_balance`` (settled ``balance − Σ local_pending``,
        copying the ``SimulatedCashAccount.reserve`` validation/raise shape) and
        records the pending entry keyed by ``order_id`` at FULL precision. The
        overlay is reconciled to venue truth on the next ``snapshot()``.

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
            if self._venue_balance is None:
                raise StateError(
                    "venue-account",
                    "unsnapshotted",
                    required_state="snapshotted (call snapshot() or start_streaming())",
                    operation="reserve",
                )
            available = self._venue_balance + self._ledger_delta - self._pending_total()
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
