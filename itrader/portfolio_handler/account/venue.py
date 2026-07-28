"""
VenueAccount — venue-cached leaf of the ``Account`` ABC.

Where ``SimulatedCashAccount`` / ``SimulatedMarginAccount`` *compute* balance and
margin truth, ``VenueAccount`` *caches* the venue's truth (balances / positions
streamed or polled from the connector). Its stable contract comes from the
``Account`` ABC, not from the connector, so it needs no rich ``LiveConnector``
signature. The venue is the source of truth in live: this leaf CACHES, it does not
RECOMPUTE.

Single-writer discipline: the async push writer mirrors the venue's private stream
and writes the RLock-guarded cache ONLY on the connector loop thread — it never
compares and never halts. The drift COMPARE and the halt DECISION run on the engine
thread, not here.

Per-market-type position truth: OKX SPOT reports NO position rows
(``fetch_positions``/``watch_positions`` return ``[]``), so a ``spot`` leaf DERIVES
the per-symbol holding from the balance payload's ``total[BASE]`` and never spawns
the positions stream. A ``derivative`` leaf reads the positions channel.

Import discipline (inertness gate, CONN-04): this leaf is re-exported from the
``account`` barrel, which the backtest hot path imports (``SimulatedCashAccount``).
``LiveConnector`` is therefore imported ONLY under ``TYPE_CHECKING``, and sourced
from the ccxt-free ``itrader.connectors.base`` module rather than the barrel — a
runtime import of the barrel would pull ``ccxt.pro`` onto the backtest import path
and fail the hot-path inertness gate.
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
    """
    Venue-cached ``Account`` leaf — caches venue truth, never recomputes.

    Satisfies the ``Account`` ABC (``balance`` / ``available_balance`` /
    ``reserve`` / ``release``) by CACHING the venue's streamed / polled truth rather
    than computing it. The REST ``snapshot()`` populates the cache for startup /
    restart / gap. Engine-thread reads raise ``StateError`` when the cache is still
    unsnapshotted (never a silent 0). ``reserve`` / ``release`` keep a local
    pending-reservation overlay on top of cached venue-available — the venue owns
    the real reservation; the overlay keeps the admission gate working pre-fill.

    Money: every venue float crosses the Decimal boundary via ``to_money(str(x))``
    (never ``Decimal(float)``); None/missing keys are guarded BEFORE the edge.
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

        The composition root builds the concrete connector once and injects the
        ``LiveConnector`` session here. No stream is started in the constructor —
        the root wires and starts it via ``start_streaming`` so lifecycle stays at
        the root.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol, never the concretion.
        account_id : str
            REQUIRED keyword with NO default — the venue account this leaf caches
            truth for. This is THE structural guard that makes an unscoped venue
            account inexpressible: if it defaulted, a caller could absorb a portfolio
            argument and hand back one SHARED account, conflating two real venue
            accounts' buying power and positions behind a green suite. With no
            default, forgetting it is a construction-time ``TypeError``.

            A required keyword-only parameter does NOT reject an EXPLICIT ``None``,
            so the empty/None case is additionally rejected below with a typed
            ``ValidationError``.
        quote_currency : str
            The quote-currency key read out of the ccxt-unified balance payloads
            (``total``/``free`` maps). The default is a fallback only — the
            composition root threads the WIRED pair's real quote (e.g. USDC for the
            EEA/MiCA BTC/USDC pair).
        market_type : {"spot", "derivative"}
            Selects the position-truth channel (see module docstring).
        symbol : str | None
            The wired traded pair (e.g. ``"BTC/USDC"``). Required for spot truth —
            the derived holding is keyed under this symbol and the base currency is
            taken from its left leg. Unused for derivative market types.
        """
        # The required keyword-only parameter stops the caller who FORGETS; this
        # stops the caller who passes ``account_id=None`` through from an Optional
        # field. Both must be loud at construction — see the docstring.
        if not account_id:
            raise ValidationError(
                "account_id",
                str(account_id),
                "A VenueAccount must name the venue account it caches truth for; "
                "there is no legitimate unscoped/default venue account (D-11)",
            )

        self.logger = get_itrader_logger().bind(component="VenueAccount")
        # The injected session Protocol, NOT the concretion.
        self._connector = connector
        self._quote = quote_currency
        # The account half of the ``(venue_name, account_id)`` reference the rest of
        # the system keys on; ``venue_name`` is the venue half, the ONE storage site
        # read back through ``Portfolio.venue_name``.
        self.account_id = account_id
        self.venue_name = venue_name

        # Per-market-type venue-truth channel. ``_base`` is the base-currency key
        # read out of ``total`` for spot position truth (left leg of the pair).
        self._market_type = market_type
        self._symbol = symbol
        self._base = symbol.split("/")[0] if symbol is not None else None

        # Does this leaf's cash channel net a venue-side hold into ``_venue_balance``?
        # Only then may ``drop_pending`` drop the local ``_pending`` overlay on ack
        # without OVER-stating buying power — see ``drop_pending`` for the argument.
        self._cash_stream_nets_holds = market_type != "spot"

        # RLock-guarded venue cache. Written ONLY on the connector loop thread (async
        # push) or on a snapshot call; read on the engine thread. All None/empty until
        # first snapshotted — a read before then surfaces loud.
        self._lock = threading.RLock()
        self._venue_balance: Decimal | None = None
        self._venue_positions: dict[str, Decimal] = {}  # symbol -> signed qty

        # Local pending-reservation overlay keyed by order id. The venue owns the
        # real reservation; this keeps the admission gate working pre-fill and is
        # reconciled to venue truth on the next snapshot.
        self._pending: dict[str, Decimal] = {}

        # Locally-ledgered settlement: the venue is source of truth but we do NOT
        # recompute from it on every read. ``_ledger_delta`` is the signed sum of
        # locally-applied fill cash flows since the last venue reconcile — settled
        # cash = cached venue balance + this delta. ``apply_fill_cash_flow`` mutates
        # it (so a fill settles into the account, exploiting the 1:1
        # VenueAccount<->portfolio topology); ``snapshot()`` resets it to zero, the
        # fresh REST balance already reflecting the settled fills.
        self._ledger_delta: Decimal = Decimal("0")

        # Spawned stream-task handles (cancelled by the connector on disconnect).
        self._stream_handles: list[Any] = []

        # Bounded-retry supervision seams for the balance/position streams. They
        # default to no-op (None) so an unwired leaf still supervises (retries
        # transients) without halting; the supervisor's closures late-bind them so a
        # setter after construction still takes effect.
        self._halt_signal: Callable[[str], None] | None = None
        self._on_stream_down: Callable[[str], None] | None = None

        # The ONE shared reconnect ladder: this leaf HAS-A StreamSupervisor and
        # delegates stream supervision to it. Its config is the ccxt-only 3-type
        # transient set and reconnect_on_clean_return=False (a forever-loop returning
        # cleanly is a stop). The REDUCED surface is deliberate, not an oversight: the
        # consume loops NEVER call mark_up / reset_budget and there is NO on_up — this
        # leaf pauses-down but never resumes-up nor resets the budget.
        #
        # ccxt + the supervisor class are lazy-imported HERE, never at module top: a
        # module-scope import of the connectors barrel would pull ccxt.pro onto the
        # backtest import path, so deferring it to construction (live-only) keeps the
        # leaf inert-by-import (CONN-04).
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
        """Extract the settled ``total`` for the quote currency from a ccxt balance payload.

        Returns the quote ``total`` as ``Decimal``, or ``None`` when the venue did
        not carry it. None/missing keys are guarded BEFORE the ``to_money(str(x))``
        edge so a missing value never becomes ``Decimal("None")``.

        The venue ``free`` map is deliberately NOT parsed: admission is governed by
        the local pending-reservation overlay, so ``available_balance`` nets against
        the settled ``balance`` — never the venue ``free`` field.
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
        """Derive spot per-symbol position truth from the BASE-currency balance total.

        Reads ``total[self._base]``, guarding None/missing keys BEFORE the
        ``to_money(str(x))`` edge, and keys it under the wired ``symbol``. A zero (or
        absent) base total is a FLAT position, surfaced as an empty map — mirroring
        the derivative channel, which reports no row when flat. Returns ``{}`` when
        the spot pair is unconfigured so an unwired leaf is structurally inert.
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
        clobber the derived holding to flat — returning ``None`` tells the caller to
        keep the prior cache (else the next drift sweep reads venue-qty=0 against a
        live engine position and spuriously halts). A frame that DOES carry the base
        key is authoritative: it returns the derived map (an empty ``{}`` when the
        base total is zero — a real FLAT that correctly clears the holding). Returns
        ``None`` for an unwired leaf too.
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

        Cache-write on the connector loop thread; NEVER a drift compare and NEVER a
        halt on a normal push. Each venue float crosses the Decimal edge in
        ``_write_balance_stream``; a missing field leaves the prior cache intact. The
        forever ``while True`` consume body is wrapped in the bounded-retry supervisor
        so a transient socket drop is survived and an UNKNOWN error escalates to a
        fail-safe HALT — an unwrapped loop dies silently on the first raise, freezing
        the cache forever.
        """
        async def _consume(_stream_name: str) -> None:
            while True:
                update = await self._connector.client.watch_balance()
                self._write_balance_stream(update)

        await self._supervisor.run(_consume, "account")

    def _write_balance_stream(self, update: Any) -> None:
        """Apply a venue balance push to the cache — POSITIONS only, NEVER the cash baseline.

        Cash is the two-term surface ``balance = _venue_balance + _ledger_delta``,
        and ``apply_fill_cash_flow`` moves ``_ledger_delta`` for EVERY fill. If the
        balance stream ALSO refreshed ``_venue_balance`` to the fill-inclusive venue
        push, the same fill would be counted TWICE — once in the stream-pushed venue
        balance, once in the local ledger — a 2x cash debit (position, which has no
        ledger overlay, stays single-counted). Resetting the ledger on the stream
        write is NOT a fix: the venue ``watch_balance`` push routinely LEADS the
        engine-thread ``on_fill`` apply (queue latency), so a reset-then-apply
        double-counts in the opposite order. Cash must be single-channel, and
        ``snapshot()`` is its SOLE reconcile point — it atomically re-baselines
        ``_venue_balance`` AND resets ``_ledger_delta``, so between snapshots the
        local ledger is the only channel that moves cash.

        The stream's remaining job is spot position liveness for the drift compare:
        on spot the per-symbol holding rides the BALANCE stream (there is no positions
        channel). ``_spot_positions_from_balance`` returns ``None`` for a base-absent
        partial frame so the guard below leaves the prior holding intact — never a
        spurious clobber-to-flat that would trip the drift halt.
        """
        spot_positions = (
            self._spot_positions_from_balance(update)
            if self._market_type == "spot" else None
        )
        with self._lock:
            if spot_positions is not None:
                self._venue_positions = spot_positions

    async def _stream_positions(self) -> None:
        """Consume the venue positions stream under the reconnect supervisor.

        Same single-writer discipline as ``_stream_account`` — cache-write on the
        connector loop thread only, never compare/halt on a normal push, forever loop
        wrapped in the same bounded-retry supervisor.
        """
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

        Called with the fixed reason ``'connector-fatal'`` on a fatal connector error,
        an exhausted retry ceiling, or an UNKNOWN error on a supervised stream. The
        halt entrypoint owns the CRITICAL alert; the venue passes NO exception text so
        no secret can leak. Optional — an unwired leaf still retries transients, but
        escalation is a no-op until a halt signal is injected.
        """
        self._halt_signal = halt_signal

    def start_streaming(self) -> None:
        """Spawn the venue push streams via the injected connector.

        The composition root calls this AFTER ``connect()`` so the connector owns the
        loop lifecycle (the spawned handles are cancelled on ``disconnect``). Not
        started in ``__init__`` — wiring stays at the root.

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

        A synchronous RPC via ``connector.call``: fetch the venue balance + positions
        and write the cache under the lock. A missing balance field leaves the prior
        cache value intact rather than clobbering it; the positions cache is fully
        replaced (the REST snapshot is authoritative) and the pending-reservation
        overlay reconciles to venue truth as the next admission cycle reads the
        refreshed available. On spot the position truth is derived from the balance
        payload instead, so the positions RPC is skipped.
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
                # The fresh REST balance is venue truth AFTER settlement — reconcile
                # the local fill-delta back to zero (never double-count a fill the
                # venue snapshot already reflects).
                self._ledger_delta = Decimal("0")
            self._venue_positions = positions

    # --- restart restore (venue snapshot is authoritative for cash) ------------

    def restore_cash(self, balance: Decimal) -> None:
        """Documented NO-OP: the venue snapshot is authoritative for cash.

        The live restart path calls ``rehydrate`` -> ``account.restore_cash(...)``
        unconditionally when a persisted account-state row exists. For a venue-CACHED
        account that scalar must NOT be applied: ``snapshot()`` (called at ``start()``
        BEFORE rehydrate) already re-read the venue's AUTHORITATIVE balance via the
        REST fetch, so writing the STALE persisted engine scalar over it would clobber
        venue truth — the "cache, not recompute" violation. The engine's persisted
        cash scalar intentionally DEFERS to the venue.

        The base ABC's raising default is deliberately UNCHANGED (an unimplemented leaf
        must still fail loud); this leaf overrides it on purpose. Position and
        dedup-ledger restore still happen on the venue path — ONLY the cash scalar
        defers.

        Parameters
        ----------
        balance : Decimal
            The persisted engine cash scalar. Accepted and intentionally not applied.
        """
        # Intentionally a no-op — see docstring.

    # --- engine-thread reads (surface unsnapshotted loud, never 0) -------------

    @property
    def is_venue_truth(self) -> bool:
        """Venue-cached leaf: venue-truth KIND — the coordinator's discriminator.

        Overrides the ``Account`` ABC default (``False``) so the startup
        ``ReconciliationCoordinator`` keys the venue reconcile on account KIND rather
        than ``exchange=='okx'``; only this leaf reaches the venue reconcile.
        """
        return True

    @property
    def connector(self) -> "LiveConnector":
        """The authenticated session this leaf caches truth over.

        READ-ONLY, and that is the point. The reconciliation coordinator needs the
        connector belonging to the account it is currently reconciling, resolved FROM
        that account rather than handed in beside it: exposing the connector the leaf
        already holds is one source of truth, while a separate parameter is a second
        one that can disagree — which is exactly how portfolio A's reconcile ends up
        reading account B's session.

        No setter: the session is injected at construction, and swapping it underneath
        a populated cache would silently re-point cached venue truth at a different
        real account.
        """
        return self._connector

    @property
    def balance(self) -> Decimal:
        """Settled cash balance — cached venue balance + local fill-delta.

        Cache-not-recompute: the venue snapshot/stream is the source of the cached
        balance; locally-applied fills move ``_ledger_delta`` so a fill settles into
        the account (1:1 VenueAccount<->portfolio topology). Raises ``StateError`` when
        the cache is still unsnapshotted — never a silent 0 that could authorize a bad
        order.
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

        ``balance − Σ local_pending``, so the order-admission gate keeps working
        pre-fill. It nets against the settled ``balance`` — NOT the venue ``free``
        field — so ``available_balance == balance`` when no reservations are
        outstanding (the admission-read invariant). Raises ``StateError`` when the
        cache is still unsnapshotted — never a silent 0.
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

        ``Σ local_pending`` — a clean ``Decimal('0')`` when nothing is reserved. The
        venue owns the real reservation; this is the local admission-overlay figure.
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

    # --- settlement surface (locally-ledgered) ---------------------------------

    def assert_funds_invariant(self, required: Decimal) -> None:
        """Engine-bug guard: raise BEFORE any mutation on a bad debit.

        Compares ``required`` against the settled ``balance`` (cached venue balance +
        local fill-delta) — NOT the reservation-adjusted buying power: the fill settles
        portfolio-first, so the order's own un-released reservation would false-positive
        here (mirroring ``SimulatedCashAccount``). The admission reservation gate should
        have prevented this state; if it fires it is an engine bug and the caller stops
        loudly. Raising before ``apply_fill_cash_flow`` mutates the ledger is what keeps
        a failed settlement from leaving a partial mutation.

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
        """Apply a fill settlement's signed, full-precision cash delta.

        The ONE trade-path cash primitive on the venue leaf: mutates the local
        ``_ledger_delta`` by the SIGNED net cash delta so the fill settles into the
        account (negative for a BUY outflow, positive for a SELL inflow). Full
        precision — deliberately NO 2dp quantize; a mid-stream quantize would shift the
        equity curve. The delta is reconciled back to zero on the next ``snapshot()``,
        whose fresh REST balance already reflects the settled fill.

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

        The venue is the TRUE owner of the reservation; this is a LOCAL admission aid
        that lets the order-admission gate work pre-fill. Validates ``amount`` against
        ``available_balance`` (settled ``balance − Σ local_pending``, mirroring the
        ``SimulatedCashAccount.reserve`` validation/raise shape) and records the pending
        entry keyed by ``order_id`` at FULL precision. The overlay is reconciled to
        venue truth on the next ``snapshot()``.

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

        Idempotent: releasing an unknown or already-released reference is a silent
        no-op. The venue owns the real reservation; this only clears the local
        admission overlay.
        """
        with self._lock:
            self._pending.pop(str(order_id), None)

    def drop_pending(self, order_id: OrderId) -> None:
        """Drop the local pending overlay on ack — ONLY when the cash channel nets holds.

        On a cash channel that nets the venue-side hold into ``_venue_balance``,
        ``_pending`` and the stream-refreshed venue balance BOTH carry the hold between
        ack and terminal release, so dropping the overlay on ack removes the duplicate.

        The spot leaf is not such a channel: there ``_write_balance_stream`` is
        positions-only and ``_venue_balance`` is re-baselined solely by ``snapshot()``,
        so ``_pending`` is the SOLE tracker of a resting order's cash hold for its
        entire life. There is no double-count to remove, and dropping the overlay on ack
        would snap ``available_balance`` back to the full settled balance while the
        order is still open on the venue — a buying-power OVER-statement admitting a
        second order against already-committed cash. So on spot this is a NO-OP and the
        overlay is held until terminal ``release``; the drop stays dormant-valid for a
        future margin/swap leaf whose cash channel refreshes ``_venue_balance``.

        This is a NON-terminal drop: on the netting leaf it pops ONLY the admission
        overlay entry and NEVER touches the settled ledger (``_ledger_delta``) — the
        fill still settles later through the normal ``apply_fill_cash_flow`` path.
        Idempotent, keyed by ``str(order_id)`` to match the ``reserve`` write key, and
        taken under the same lock ``reserve``/``release`` hold. Terminal ``release``
        pops unconditionally on BOTH leaves, so the spot hold is never leaked.
        """
        if not self._cash_stream_nets_holds:
            # Single-channel spot leaf — hold the overlay until terminal release
            # (dropping it here over-states buying power).
            return
        with self._lock:
            self._pending.pop(str(order_id), None)
