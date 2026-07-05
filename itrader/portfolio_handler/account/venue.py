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

import asyncio
import threading
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError,
    StateError,
)
from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger

from .base import Account

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector


# D-11 (RES-01/D-19/D-20) reconnect-supervisor tuning — mirrors the okx.py donor
# constants (``OkxExchange._run_stream_supervisor``). The venue balance/position
# streams are wrapped in the same bounded-retry supervisor so a transient socket
# drop is survived (publish-and-continue) and an unknown error escalates to a
# fail-safe HALT rather than silently killing the cache writer (V17-07). Named
# constants, [ASSUMED] and tunable from sandbox behaviour.
_STREAM_RECONNECT_DEBOUNCE_SECONDS = 0.25
_STREAM_RECONNECT_BACKOFF_BASE_SECONDS = 1.0
_STREAM_RECONNECT_BACKOFF_CAP_SECONDS = 30.0
_STREAM_RECONNECT_RETRY_CEILING = 6


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
        self.logger = get_itrader_logger().bind(component="VenueAccount")
        # D-04: the injected session Protocol, NOT the concretion.
        self._connector = connector
        self._quote = quote_currency

        # D-03: per-market-type venue-truth channel. ``_base`` is the base-currency
        # key read out of ``total`` for spot position truth (left leg of the pair).
        self._market_type = market_type
        self._symbol = symbol
        self._base = symbol.split("/")[0] if symbol is not None else None

        # D-24 (CR-01): does this leaf's cash channel actually net a venue-side hold
        # into ``_venue_balance``? Only then may ``drop_pending`` drop the local
        # ``_pending`` overlay on ack without OVER-stating buying power. On the wired
        # single-channel SPOT leaf ``_write_balance_stream`` is positions-only and
        # ``_venue_balance`` is re-baselined solely by ``snapshot()`` — the overlay is
        # the SOLE tracker of a resting order's hold, so it must be held until terminal
        # ``release``. The derivative/margin leaf DOES net holds (stream-refreshed cash),
        # so D-15's drop-on-ack stays valid there.
        self._cash_stream_nets_holds = market_type != "spot"

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

        # D-11 (V17-07): bounded-retry supervisor state for the balance/position
        # streams (mirrors the okx.py donor). A transient drop reconnects with
        # backoff; an unknown error escalates to a fail-safe HALT — never the bare
        # ``while True`` that died silently on the first raise. The halt/pause seams
        # default to no-op (None) so an unwired leaf still supervises without halting.
        self._reconnect_attempts: dict[str, int] = {}
        self._streams_down: set[str] = set()
        self._reconnect_debounce_s = _STREAM_RECONNECT_DEBOUNCE_SECONDS
        self._reconnect_backoff_base_s = _STREAM_RECONNECT_BACKOFF_BASE_SECONDS
        self._reconnect_backoff_cap_s = _STREAM_RECONNECT_BACKOFF_CAP_SECONDS
        self._reconnect_ceiling = _STREAM_RECONNECT_RETRY_CEILING
        self._halt_signal: Callable[[str], None] | None = None
        self._on_stream_down: Callable[[str], None] | None = None

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
        """Consume the venue balance stream under the reconnect supervisor (D-15/D-11).

        Mirrors ``OkxExchange._stream_fills``: cache-write on the connector loop
        thread, NEVER a drift compare and NEVER a halt on a NORMAL push (the compare
        lives on the engine thread in 05-04). Each venue float crosses the Decimal edge
        in ``_write_balance_stream``; a missing field leaves the prior cache value
        intact. D-11 (V17-07): the forever ``while True`` consume body is now wrapped in
        the bounded-retry supervisor so a transient socket drop is survived and an
        UNKNOWN error escalates to a fail-safe HALT — the bare loop died silently on the
        first raise, freezing the balance/position cache forever.
        """
        async def _consume(_stream_name: str) -> None:
            while True:
                update = await self._connector.client.watch_balance()
                self._write_balance_stream(update)

        await self._run_stream_supervisor(_consume, "account")

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
        """Consume the venue positions stream under the reconnect supervisor (D-15/D-11).

        Same single-writer discipline as ``_stream_account`` — cache-write on the
        connector loop thread only, never compare/halt on a NORMAL push. D-11 (V17-07):
        the forever ``while True`` consume body is wrapped in the same bounded-retry
        supervisor so a transient drop is survived and an unknown error escalates to a
        fail-safe HALT rather than silently killing the position-cache writer.
        """
        async def _consume(_stream_name: str) -> None:
            while True:
                update = await self._connector.client.watch_positions()
                positions = self._extract_positions(update)
                with self._lock:
                    self._venue_positions = positions

        await self._run_stream_supervisor(_consume, "positions")

    # --- reconnect supervisor (D-11 — wrap the bare venue loops, V17-07) --------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the freeze-in-place halt entrypoint (D-11/D-20).

        Called with the fixed reason ``'connector-fatal'`` on a fatal connector error,
        an exhausted retry ceiling, or an UNKNOWN error on a supervised stream. The
        halt entrypoint owns the CRITICAL alert; the venue passes NO exception text so
        no secret can leak (T-05-27 / V7). Optional — an unwired leaf supervises (retries
        transients) but escalation is a no-op until a halt signal is injected.
        """
        self._halt_signal = halt_signal

    async def _run_stream_supervisor(
        self, consume: Callable[[str], Awaitable[None]], stream_name: str
    ) -> None:
        """Bounded-retry reconnect supervisor wrapping a stream consume-loop (D-11).

        Ladder mirrors the ``OkxExchange._run_stream_supervisor`` donor:

        - ``asyncio.CancelledError`` is re-raised untouched (cooperative teardown —
          never swallow cancellation, Pitfall 4).
        - **transient** (``ccxt.NetworkError``/``RequestTimeout``/``DDoSProtection``) ->
          reconnect with exponential backoff after a debounce, staying running.
        - **fatal** (``ccxt.AuthenticationError``/``PermissionDenied``) OR the retry
          ceiling exhausted OR an **unknown** (unclassified) error -> escalate to the
          injected halt entrypoint (fail-safe HALT, reason ``'connector-fatal'``). The
          catch-all is what closes V17-07: the old bare ``while True`` let any raise
          kill the cache writer silently.
        """
        import ccxt  # lazy: ccxt only needed on the live stream path (hot-path inert).
        transient: tuple[type[BaseException], ...] = (
            ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection)
        fatal: tuple[type[BaseException], ...] = (
            ccxt.AuthenticationError, ccxt.PermissionDenied)
        while True:
            try:
                await consume(stream_name)
                return  # a forever-loop returning cleanly is not expected — stop.
            except asyncio.CancelledError:
                raise  # cooperative teardown — never swallow.
            except fatal as exc:
                self._escalate_connector_halt(
                    stream_name, exc, "fatal auth/permission error")
                return
            except transient as exc:
                attempt = self._reconnect_attempts.get(stream_name, 0) + 1
                self._reconnect_attempts[stream_name] = attempt
                if attempt > self._reconnect_ceiling:
                    self._escalate_connector_halt(
                        stream_name, exc, "reconnect retry ceiling exhausted")
                    return
                await asyncio.sleep(self._reconnect_debounce_s)
                if attempt > 1:
                    self._mark_stream_down(stream_name)
                backoff = min(
                    self._reconnect_backoff_base_s * (2 ** (attempt - 1)),
                    self._reconnect_backoff_cap_s)
                # Scrub (T-05-27): log the exception TYPE only, never str(exc).
                self.logger.warning(
                    "OKX venue %s stream dropped (%s) — reconnecting "
                    "(attempt %d/%d, backoff %.1fs)",
                    stream_name, type(exc).__name__, attempt,
                    self._reconnect_ceiling, backoff)
                await asyncio.sleep(backoff)
            except Exception as exc:
                # D-11 (V17-07): an UNCLASSIFIED error is neither transient nor fatal.
                # Fail safe — escalate to a HALT instead of letting it propagate out of
                # the consume loop and kill the cache writer silently.
                self._escalate_connector_halt(stream_name, exc, "unexpected error")
                return

    def _escalate_connector_halt(
        self, stream_name: str, exc: BaseException, cause: str
    ) -> None:
        """Halt the engine on an unrecoverable venue-stream failure (D-11/D-20).

        Scrub (T-05-27 / V7): the log carries the exception TYPE + a fixed cause string,
        never ``str(exc)``; the halt entrypoint is called with the fixed reason
        ``'connector-fatal'`` so no secret can reach the CRITICAL alert.
        """
        self.logger.error(
            "OKX venue %s stream unrecoverable (%s: %s) — halting engine",
            stream_name, type(exc).__name__, cause)
        if self._halt_signal is not None:
            self._halt_signal("connector-fatal")

    def _mark_stream_down(self, stream_name: str) -> None:
        """Record a sustained venue-stream disconnect once (D-11/D-19)."""
        if stream_name in self._streams_down:
            return
        self._streams_down.add(stream_name)
        self.logger.warning(
            "OKX venue %s stream disconnected past debounce", stream_name)
        if self._on_stream_down is not None:
            self._on_stream_down(stream_name)

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

    # --- restart restore (CR-01 — venue snapshot is authoritative for cash) ----

    def restore_cash(self, balance: Decimal) -> None:
        """Documented NO-OP: venue snapshot is authoritative for cash (CR-01/D-14).

        The live restart path calls ``CachedSqlPortfolioStateStorage.rehydrate`` ->
        ``account.restore_cash(cash_balance)`` unconditionally when a persisted
        account-state row exists. For a venue-CACHED account this scalar must NOT be
        applied: ``snapshot()`` (called at ``start()`` BEFORE rehydrate) already
        re-read the venue's AUTHORITATIVE balance via the REST fetch, so writing the
        STALE persisted engine scalar over it would clobber venue truth — exactly the
        "cache, not recompute" violation D-14 forbids. The venue is the source of cash
        truth in live; the engine's persisted cash scalar intentionally DEFERS to it.

        This override therefore accepts ``balance`` and does nothing to the cache. It
        exists to (a) fix the CR-01 crash — the inherited ``Account.restore_cash``
        raised ``NotImplementedError``, failing every live restart with persisted
        account state — and (b) encode the correct semantics explicitly. The base
        ABC's raising default is deliberately UNCHANGED (an unimplemented leaf must
        still fail loud); ``VenueAccount`` now overrides it on purpose.

        Note the position and dedup-ledger restore still happen on the venue path
        (positions surface through the snapshotted cache; the dedup ledger seeds from
        the durable transaction history) — ONLY the cash scalar defers to venue truth.

        Parameters
        ----------
        balance : Decimal
            The persisted engine cash scalar. Accepted and intentionally not applied
            (the venue snapshot owns the cash baseline).
        """
        # Intentionally a no-op — see docstring (CR-01 / D-14).

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

    def drop_pending(self, order_id: OrderId) -> None:
        """Drop the local pending overlay on ack — ONLY when the cash channel nets holds (D-15/D-24).

        D-15 (V17-13) closes a buying-power double-count on a cash channel that nets
        the venue-side hold into ``_venue_balance``: there ``_pending`` and the
        stream-refreshed venue balance BOTH carry the hold between ack and terminal
        release, so dropping the overlay on ack removes the duplicate.

        D-24 (CR-01) gates that drop. On the WIRED single-channel SPOT leaf
        ``_write_balance_stream`` is positions-only and ``_venue_balance`` is
        re-baselined solely by ``snapshot()`` (D-01) — so the ``_pending`` overlay is
        the SOLE tracker of a resting order's cash hold for its entire life. There was
        never a double-count for D-15 to remove; dropping the overlay on ack would snap
        ``available_balance`` back to the full settled balance while the order is still
        open on the venue — a buying-power OVER-statement admitting a second order
        against already-committed cash. So on the spot leaf this is a NO-OP: the overlay
        is held until terminal ``release``. D-15's drop-on-ack stays dormant-valid for a
        future margin/swap leaf whose cash channel refreshes ``_venue_balance``.

        The guard is the intent-revealing ``_cash_stream_nets_holds`` predicate
        (False on spot, True on derivative). When it is False the overlay is held —
        negation-first early return, no overlay pop.

        This is a NON-terminal drop: on the netting leaf it pops ONLY the admission
        overlay entry and NEVER touches the settled ledger (``_ledger_delta``) — the
        fill still settles later through the normal ``apply_fill_cash_flow`` path.
        Idempotent (a ``KeyError``-free ``pop``), keyed by ``str(order_id)`` to match
        the ``reserve`` write key, and taken under the same lock ``reserve``/``release``
        hold. Terminal ``release`` still pops unconditionally on BOTH leaves, so the
        spot hold is released at terminal, never leaked.
        """
        if not self._cash_stream_nets_holds:
            # D-24 (CR-01): single-channel spot leaf — hold the overlay until terminal
            # release (dropping it here over-states buying power).
            return
        with self._lock:
            self._pending.pop(str(order_id), None)
