"""VenueAccount — venue-cached leaf of the ``Account`` ABC.

Where the simulated leaves *compute* balance and margin truth, this one *caches* the
venue's (balances / positions streamed or polled from the connector). The venue is the
source of truth in live: this leaf CACHES, it does not RECOMPUTE.

Single-writer discipline: the async push writer mirrors the venue's private stream and
writes the RLock-guarded cache ONLY on the connector loop thread. It never compares and
never halts — the drift COMPARE and the halt DECISION run on the engine thread.

Per-market-type position truth: OKX SPOT reports NO position rows
(``fetch_positions``/``watch_positions`` return ``[]``), so a ``spot`` leaf DERIVES the
per-symbol holding from the balance payload's ``total[BASE]`` and never spawns the
positions stream. A ``derivative`` leaf reads the positions channel.

Import discipline: this leaf is re-exported from the ``account`` barrel, which the
backtest hot path imports. ``LiveConnector`` is therefore imported ONLY under
``TYPE_CHECKING`` and sourced from the ccxt-free ``itrader.connectors.base`` rather than
the barrel — a runtime import of the barrel would pull ``ccxt.pro`` onto the backtest
import path and fail the inertness gate.
"""

import threading
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Literal

from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError,
    StateError,
    ValidationError,
)
from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger

from .base import Account

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector


class VenueAccount(Account):
    """Venue-cached ``Account`` leaf — caches venue truth, never recomputes.

    The REST ``snapshot()`` populates the cache for startup / restart / gap.
    Engine-thread reads raise ``StateError`` while the cache is still unsnapshotted —
    never a silent 0 that could authorize a bad order. ``reserve`` / ``release`` keep a
    local pending-reservation overlay on top of cached venue-available: the venue owns
    the real reservation, the overlay keeps the admission gate working pre-fill.

    Money: every venue float crosses the Decimal boundary via ``to_money(str(x))``,
    never ``Decimal(float)``, with None/missing keys guarded BEFORE the edge.
    """

    def __init__(
        self,
        connector: "LiveConnector",
        quote_currency: str = "USDT",
        *,
        account_id: str,
        venue_name: str | None = None,
        market_type: Literal["spot", "derivative"] = "derivative",
        symbol: str | None = None,
    ) -> None:
        """Bind the injected session and stand up the venue cache.

        No stream is started here — the composition root wires and starts it via
        ``start_streaming``, so lifecycle stays at the root.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol, never the concretion.
        quote_currency : str
            The quote-currency key read out of the ccxt-unified balance payloads. The
            default is a fallback only — the composition root threads the WIRED pair's
            real quote (e.g. USDC for the EEA/MiCA BTC/USDC pair).
        account_id : str
            REQUIRED keyword with NO default — the venue account this leaf caches truth
            for. The missing default is THE structural guard that makes an unscoped
            venue account inexpressible: if it defaulted, a caller could absorb a
            portfolio argument and hand back one SHARED account, conflating two real
            accounts' buying power and positions behind a green suite.
        venue_name : str | None
            The venue half of the ``(venue_name, account_id)`` reference.
        market_type : {"spot", "derivative"}
            Selects the position-truth channel (see module docstring).
        symbol : str | None
            The wired traded pair (e.g. ``"BTC/USDC"``). Required for spot truth — the
            derived holding is keyed under it and the base currency is its left leg.
            Unused for derivative market types.

        Raises
        ------
        ValidationError
            When ``account_id`` is empty or ``None``.
        """
        # A required keyword-only parameter stops the caller who FORGETS, but does not
        # reject an EXPLICIT None arriving from an Optional field. Both must be loud at
        # construction.
        if not account_id:
            raise ValidationError(
                "account_id",
                str(account_id),
                "A VenueAccount must name the venue account it caches truth for; "
                "there is no legitimate unscoped/default venue account (D-11)",
            )

        self.logger = get_itrader_logger().bind(component="VenueAccount")
        self._connector = connector
        self._quote = quote_currency
        # This leaf is the ONE storage site for the pair; Portfolio reads it back.
        self.account_id = account_id
        self.venue_name = venue_name

        # ``_base`` is the base-currency key read out of ``total`` for spot position
        # truth (the left leg of the pair).
        self._market_type = market_type
        self._symbol = symbol
        self._base = symbol.split("/")[0] if symbol is not None else None

        # Does this leaf's cash channel net a venue-side hold into ``_venue_balance``?
        # Only then may ``drop_pending`` drop the overlay on ack without OVER-stating
        # buying power — see ``drop_pending``.
        self._cash_stream_nets_holds = market_type != "spot"

        # RLock-guarded venue cache. Written ONLY on the connector loop thread or by a
        # snapshot call; read on the engine thread. None/empty until first snapshotted.
        self._lock = threading.RLock()
        self._venue_balance: Decimal | None = None
        self._venue_positions: dict[str, Decimal] = {}  # symbol -> signed qty

        # Local pending-reservation overlay keyed by order id, reconciled to venue
        # truth on the next snapshot.
        self._pending: dict[str, Decimal] = {}

        # The signed sum of locally-applied fill cash flows since the last venue
        # reconcile, so settled cash = cached venue balance + this delta.
        # ``snapshot()`` resets it to zero, the fresh REST balance already reflecting
        # those fills.
        self._ledger_delta: Decimal = Decimal("0")

        # Spawned stream-task handles (cancelled by the connector on disconnect).
        self._stream_handles: list[Any] = []

        # Default to no-op so an unwired leaf still retries transients without halting.
        # The supervisor's closures late-bind them, so a setter after construction
        # still takes effect.
        self._halt_signal: Callable[[str], None] | None = None
        self._on_stream_down: Callable[[str], None] | None = None

        # The ONE shared reconnect ladder, with reconnect_on_clean_return=False since a
        # forever-loop returning cleanly is a stop. The REDUCED surface is deliberate,
        # not an oversight: the consume loops never call mark_up / reset_budget and
        # there is no on_up, so this leaf pauses-down but never resumes-up.
        #
        # ccxt and the supervisor are lazy-imported HERE, never at module top: a
        # module-scope import would pull ccxt.pro onto the backtest import path.
        import ccxt

        from itrader import config
        from itrader.connectors.stream_supervisor import StreamSupervisor
        self._supervisor = StreamSupervisor(
            config.stream,
            transient_exceptions=(
                ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection),
            fatal_exceptions=(ccxt.AuthenticationError, ccxt.PermissionDenied),
            reconnect_on_clean_return=False,
            halt_signal=lambda r: (
                self._halt_signal(r) if self._halt_signal is not None else None),
            on_down=lambda n: (
                self._on_stream_down(n) if self._on_stream_down is not None else None),
            on_up=None,
            logger=self.logger,
            label="OKX venue")

    # --- Decimal-edge parsers (None/missing guarded BEFORE the edge) -----------

    def _extract_balance(self, payload: Any) -> Decimal | None:
        """The settled quote ``total``, or ``None`` when the venue did not carry it.

        None/missing keys are guarded BEFORE the ``to_money(str(x))`` edge, so a
        missing value never becomes ``Decimal("None")``.

        The venue ``free`` map is deliberately NOT parsed: admission is governed by the
        local pending overlay, so ``available_balance`` nets against the settled
        ``balance`` — never the venue ``free`` field.
        """
        total_map = payload.get("total") if isinstance(payload, dict) else None
        total_raw = total_map.get(self._quote) if isinstance(total_map, dict) else None
        return to_money(str(total_raw)) if total_raw is not None else None

    def _extract_positions(self, payload: Any) -> dict[str, Decimal]:
        """Extract ``symbol -> signed qty`` from a ccxt positions payload.

        A ``short`` side flips the sign. Entries missing a symbol or contract size are
        skipped; every size crosses the Decimal edge via ``to_money(str(x))``.
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
        """Derive spot per-symbol position truth from the BASE-currency balance total.

        A zero or absent base total is a FLAT position, surfaced as an empty map —
        mirroring the derivative channel, which reports no row when flat. Returns ``{}``
        for an unconfigured pair, so an unwired leaf is structurally inert.
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
        """Derive the spot holding to WRITE, or ``None`` to leave the cache intact.

        A partial/quote-only ``watch_balance`` push that OMITS the base key must NOT
        clobber the derived holding to flat, or the next drift sweep reads venue-qty=0
        against a live engine position and spuriously halts — hence ``None`` for
        "keep the prior cache". A frame that DOES carry the base key is authoritative,
        including an empty ``{}`` for a real FLAT that correctly clears the holding.
        """
        if self._symbol is None or self._base is None:
            return None
        total_map = payload.get("total") if isinstance(payload, dict) else None
        if not isinstance(total_map, dict) or self._base not in total_map:
            return None
        return self._extract_spot_position(payload)

    # --- async push writer (cache-write ONLY, never compare/halt) --------------

    async def _stream_account(self) -> None:
        """Consume the venue balance stream under the reconnect supervisor.

        Cache-write on the connector loop thread; never a drift compare, never a halt
        on a normal push. The forever consume body is wrapped in the bounded-retry
        supervisor because an unwrapped loop dies silently on the first raise and
        freezes the cache forever.
        """
        async def _consume(_stream_name: str) -> None:
            while True:
                update = await self._connector.client.watch_balance()
                self._write_balance_stream(update)

        await self._supervisor.run(_consume, "account")

    def _write_balance_stream(self, update: Any) -> None:
        """Apply a venue balance push to the cache — POSITIONS only, NEVER cash.

        Cash is the two-term surface ``balance = _venue_balance + _ledger_delta``, and
        ``apply_fill_cash_flow`` moves the delta for EVERY fill. If this also refreshed
        ``_venue_balance`` to the fill-inclusive venue push, the same fill would count
        TWICE — a 2x cash debit. Resetting the ledger here is NOT a fix either: the
        venue push routinely LEADS the engine-thread ``on_fill`` apply, so
        reset-then-apply double-counts in the opposite order. Cash must be
        single-channel, and ``snapshot()`` is its SOLE reconcile point.

        What remains is spot position liveness: on spot the per-symbol holding rides
        the BALANCE stream, there being no positions channel.
        """
        spot_positions = (
            self._spot_positions_from_balance(update)
            if self._market_type == "spot" else None
        )
        with self._lock:
            if spot_positions is not None:
                self._venue_positions = spot_positions

    async def _stream_positions(self) -> None:
        """Consume the venue positions stream — same discipline as ``_stream_account``."""
        async def _consume(_stream_name: str) -> None:
            while True:
                update = await self._connector.client.watch_positions()
                positions = self._extract_positions(update)
                with self._lock:
                    self._venue_positions = positions

        await self._supervisor.run(_consume, "positions")

    # --- reconnect supervision (delegated to StreamSupervisor) -----------------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the freeze-in-place halt entrypoint.

        Called with a FIXED reason literal on a fatal connector error, an exhausted
        retry ceiling, or an UNKNOWN error on a supervised stream — never exception
        text, so no secret can leak. Optional: an unwired leaf still retries
        transients, but escalation is a no-op until a halt signal is injected.

        Parameters
        ----------
        halt_signal : Callable[[str], None]
            The halt entrypoint, which owns the CRITICAL alert.
        """
        self._halt_signal = halt_signal

    def start_streaming(self) -> None:
        """Spawn the venue push streams via the injected connector.

        Called by the composition root AFTER ``connect()``, so the connector owns the
        loop lifecycle and cancels the spawned handles on ``disconnect``.

        A spot leaf does NOT spawn the positions stream: ``watch_positions`` yields
        ``[]`` on spot and would clobber the base-derived holding, which instead rides
        ``_stream_account``.
        """
        handles = [self._connector.spawn(self._stream_account())]
        if self._market_type != "spot":
            handles.append(self._connector.spawn(self._stream_positions()))
        self._stream_handles = handles

    # --- REST snapshot (startup / restart / gap recovery) ----------------------

    def snapshot(self) -> None:
        """Populate the cache from a REST snapshot (startup / restart / gap).

        A synchronous RPC via ``connector.call``. A missing balance field leaves the
        prior cache intact rather than clobbering it; the positions cache is fully
        replaced, the REST snapshot being authoritative. On spot the position truth is
        derived from the balance payload, so the positions RPC is skipped.
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
                # The fresh REST balance is venue truth AFTER settlement, so the local
                # fill-delta must reconcile to zero or every fill it already reflects
                # would be counted twice.
                self._ledger_delta = Decimal("0")
            self._venue_positions = positions

    # --- restart restore (venue snapshot is authoritative for cash) ------------

    def restore_cash(self, balance: Decimal) -> None:
        """Documented NO-OP: the venue snapshot is authoritative for cash.

        The live restart path calls ``restore_cash`` unconditionally when a persisted
        account-state row exists. For a venue-CACHED account that scalar must NOT be
        applied: ``snapshot()`` runs at ``start()`` BEFORE rehydrate and has already
        re-read the venue's authoritative balance, so writing the stale persisted
        scalar over it would clobber venue truth. Position and dedup-ledger restore
        still happen — ONLY the cash scalar defers. The base ABC's raising default is
        deliberately unchanged, so an unimplemented leaf still fails loud.

        Parameters
        ----------
        balance : Decimal
            The persisted engine cash scalar. Accepted and intentionally not applied.
        """
        # Intentionally a no-op — see docstring.

    # --- engine-thread reads (surface unsnapshotted loud, never 0) -------------

    @property
    def is_venue_truth(self) -> bool:
        """Venue-truth KIND — the reconciliation coordinator's discriminator.

        Overrides the ABC default so the startup reconcile keys on account KIND rather
        than ``exchange == 'okx'``; only this leaf reaches the venue reconcile.
        """
        return True

    @property
    def connector(self) -> "LiveConnector":
        """The authenticated session this leaf caches truth over.

        READ-ONLY, and that is the point. The reconciliation coordinator resolves the
        connector FROM the account it is reconciling rather than taking it as a
        separate parameter, because a second source can disagree — which is exactly how
        portfolio A's reconcile ends up reading account B's session. No setter either:
        swapping the session underneath a populated cache would silently re-point
        cached venue truth at a different real account.
        """
        return self._connector

    @property
    def balance(self) -> Decimal:
        """Settled cash balance — cached venue balance + local fill-delta.

        Raises
        ------
        StateError
            When the cache is still unsnapshotted. Never a silent 0.
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
        """Settled balance net of the local pending-reservation overlay.

        Nets against the settled ``balance``, NOT the venue ``free`` field, so
        ``available_balance == balance`` whenever no reservations are outstanding.

        Raises
        ------
        StateError
            When the cache is still unsnapshotted. Never a silent 0.
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
        """Total cash reserved by the local pending-reservation overlay.

        Returns
        -------
        Decimal
            ``Σ local_pending``, a clean ``Decimal('0')`` when nothing is reserved.
            The venue owns the real reservation; this is the local overlay figure.
        """
        with self._lock:
            return self._pending_total()

    @property
    def positions(self) -> dict[str, Decimal]:
        """Cached venue positions — a copy read under the lock.

        Returns
        -------
        dict[str, Decimal]
            symbol -> signed qty. Empty means the venue reported no open positions, or
            the cache is not yet snapshotted. Positions are a set-membership read, so
            unlike balance an empty map is a valid answer, not a silent-0 hazard.
        """
        with self._lock:
            return dict(self._venue_positions)

    def _pending_total(self) -> Decimal:
        """Sum the local pending-reservation overlay (caller holds the lock)."""
        total = Decimal("0")
        for amount in self._pending.values():
            total += amount
        return total

    # --- settlement surface (locally-ledgered) ---------------------------------

    def assert_funds_invariant(self, required: Decimal) -> None:
        """Engine-bug guard: raise BEFORE any mutation on a bad debit.

        Compares against the settled ``balance``, NOT the reservation-adjusted buying
        power: the fill settles portfolio-first, so the order's own un-released
        reservation would false-positive here. Raising before ``apply_fill_cash_flow``
        mutates the ledger is what keeps a failed settlement from leaving a partial
        mutation. The admission gate should have prevented this state; if it fires it
        is an engine bug.

        Args:
            required: The actual net cash cost of the settlement debit.

        Raises:
            InsufficientFundsError: When ``required`` exceeds the settled balance.
            StateError: When the cache is still unsnapshotted.
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
        """Apply a fill settlement's signed, full-precision cash delta.

        The ONE trade-path cash primitive on this leaf: negative for a BUY outflow,
        positive for a SELL inflow. Deliberately NO 2dp quantize — a mid-stream
        quantize would shift the equity curve. The delta reconciles to zero on the next
        ``snapshot()``.

        Args:
            amount: Signed full-precision net cash delta. No quantization.
            fee: Commission portion already included in ``amount`` (single net
                delta, no separate debit).
            description: Audit description (unused on the cache leaf — the
                transaction record is the audit home).
            reference_id: Reference id (e.g. transaction id).
            timestamp: Event-derived time (transaction/fill time).
        """
        with self._lock:
            self._ledger_delta += amount

    # --- reserve / release (local pending overlay) -----------------------------

    def reserve(self, order_id: OrderId, amount: Decimal) -> None:
        """Reserve ``amount`` for a pending order via the local overlay.

        The venue TRULY owns the reservation; this is a local admission aid so the gate
        works pre-fill. Validates against ``available_balance`` and records the entry
        keyed by ``order_id`` at FULL precision, reconciled to venue truth on the next
        ``snapshot()``.

        Parameters
        ----------
        order_id : OrderId
            Key for the overlay entry; the same key ``release`` / ``drop_pending`` pop.
        amount : Decimal
            Cash to reserve. Must be positive.

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
        """Release the local pending reservation keyed by ``order_id``.

        Idempotent — releasing an unknown or already-released reference is a silent
        no-op. Clears only the local admission overlay.
        """
        with self._lock:
            self._pending.pop(str(order_id), None)

    def drop_pending(self, order_id: OrderId) -> None:
        """Drop the local pending overlay on ack — ONLY when the cash channel nets holds.

        Where the cash channel nets the venue-side hold into ``_venue_balance``, both
        ``_pending`` and the stream-refreshed balance carry that hold between ack and
        terminal release, so dropping the overlay removes the duplicate.

        The spot leaf is NOT such a channel: ``_write_balance_stream`` is
        positions-only there and ``_venue_balance`` is re-baselined solely by
        ``snapshot()``, so ``_pending`` is the SOLE tracker of a resting order's cash
        hold for its whole life. There is no double-count to remove, and dropping the
        overlay would snap ``available_balance`` back to the full settled balance while
        the order is still open on the venue — a buying-power OVER-statement admitting
        a second order against already-committed cash. So on spot this is a NO-OP and
        the overlay is held until terminal ``release``.

        A NON-terminal drop: on the netting leaf it pops ONLY the overlay entry and
        never touches ``_ledger_delta``, so the fill still settles through
        ``apply_fill_cash_flow``. Terminal ``release`` pops unconditionally on BOTH
        leaves, so the spot hold is never leaked.
        """
        if not self._cash_stream_nets_holds:
            # Single-channel spot leaf — hold the overlay until terminal release
            # (dropping it here over-states buying power).
            return
        with self._lock:
            self._pending.pop(str(order_id), None)
