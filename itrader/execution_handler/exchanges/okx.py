"""OkxExchange — the live sibling of ``SimulatedExchange`` (order arm).

Same ``AbstractExchange`` seam as ``SimulatedExchange``, so it drops straight into
``ExecutionHandler.on_order``. Unlike the simulated exchange it does NOT match orders — the
OKX venue is the matching engine — and is pure translation across the venue boundary:
submit/cancel through ``connector.call``, and stream order-status + fills via
``connector.spawn`` on ``watch_orders`` / ``watch_my_trades`` (the fill stream is the
my-trades channel, NOT a fills channel, which ccxt.pro does not expose). The arm ``put``s
each translated ``FillEvent`` on ``global_queue`` itself, from the connector loop thread;
portfolio state still mutates only on the engine thread via ``on_fill``.

Decimal edge (this is its single written home): every inbound venue float crosses via
``to_money(str(x))``; outbound quantities/prices round to OKX lot/tick via the ccxt string
helpers ``amount_to_precision`` / ``price_to_precision``. NEVER ``Decimal(<venue float>)``.
Every event ``time`` is stamped from the venue timestamp, never wall-clock.

``LiveConnector`` is imported from the ccxt-free ``itrader.connectors.base``, NOT the
``itrader.connectors`` barrel — the barrel eagerly imports ``OkxConnector`` (and therefore
``ccxt.pro``), so importing the Protocol from ``base`` keeps this import ccxt-free.

Indentation: this tree is TAB-indented (a mixed-indent diff breaks the file).
"""

from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Callable, Dict, List, Optional

from itrader.connectors.base import LiveConnector
from itrader.core.enums import ErrorSeverity, OrderCommand, OrderType, Side
from itrader.core.enums.execution import ExchangeConnectionStatus, ExecutionErrorCode
from itrader.core.exceptions import ValidationError
from itrader.core.instrument import Instrument
from itrader.core.money import precision_to_scale, to_money
from itrader.events_handler.events import ErrorEvent, FillEvent, OrderAckEvent, OrderEvent
from itrader.logger import get_itrader_logger

from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult
from .base import AbstractExchange
from .venue_correlation import VenueCorrelationIndex


# OKX clOrdId charset. Base62 of the order id's 128 bits is a bijection on the 16 raw
# UUID bytes and renders to <=22 chars, fitting OKX's 32-char alphanumeric limit with
# full entropy. Truncating a hex render instead drops the UUID tail bits, collapsing two
# orders onto one clOrdId — and the clOrdId is the fast-fill-race correlation key.
_CLORDID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Bounded missed-fill catch-up page size (ccxt's okx caps a fetch_my_trades page at 100).
# ``{symbol}:{trade_id}`` dedup makes a re-fetched trade an idempotent no-op, so an
# under-sized page only defers the tail to the next reconcile, never double-settles.
_CATCHUP_TRADE_LIMIT = 100

# Bound on the fill-translation ErrorEvent from BOTH drain paths (``_consume_fills`` and
# ``catch_up_missed_fills``). A raw venue trade dict may carry request context / secrets,
# so the event binds ``type(exc).__name__`` + this fixed literal ONLY — never ``str(exc)``
# or the payload. Classified FILL_TRANSLATION -> SETTLEMENT halt-on-first downstream.
_FILL_TRANSLATION_ERROR_MSG = (
	"OKX fill translation failed — venue fill skipped, deferred to reconcile")

# ccxt-unified terminal statuses that reconcile the mirror via a FillEvent — a venue-side
# cancel/expiry the engine did NOT command (an OKX MMP cancel, a post-only reject, a GTD
# expiry). ``closed`` (FILLED) is deliberately absent: that money already crosses on
# ``watch_my_trades``, so translating it here would double-settle. Keys are lower-cased.
_ORDER_STATUS_TO_FILL: Dict[str, str] = {
	"canceled": "CANCELLED",
	"cancelled": "CANCELLED",
	"expired": "EXPIRED",
}


class OkxExchange(AbstractExchange):
	"""Live OKX order arm implementing ``AbstractExchange`` against an injected session.

	Constructor mirrors ``SimulatedExchange`` (positional ``global_queue`` first) and takes
	the injected ``LiveConnector`` session Protocol — the seam, not the concretion.
	"""

	def __init__(self, global_queue: "Queue[Any]", connector: "LiveConnector") -> None:
		"""Bind the queue + injected session; no venue socket is opened here.

		Parameters
		----------
		global_queue : Queue
			The trading system's shared event queue — the exchange ``put``s FillEvents here
			itself. The ``put`` may fire from the connector's asyncio thread; that is safe
			(``queue.Queue`` is MPSC-safe).
		connector : LiveConnector
			The injected session/transport Protocol. The arm drives ``create_order`` /
			``cancel_order`` via ``connector.call`` and the ``watch_*`` streams via
			``connector.spawn``, and reads the shared ``ccxt.pro`` client for the precision
			helpers — it never imports the connector concretion.
		"""
		self.logger = get_itrader_logger().bind(component="OkxExchange")
		self.global_queue = global_queue
		self._connector = connector

		self._exchange_name = "okx"
		self._connected = False
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED

		# All venue-correlation state (the venue-id / order-id / clOrdId maps, the late-fill
		# buffer, the dedup ring, the cumulative-filled counter, the cross-thread lock) lives
		# on VenueCorrelationIndex; a streamed fill's venue order id resolves back through it
		# to the originating OrderEvent. The index guards every read+write with its own lock:
		# writes land on the ENGINE thread via submit/cancel, reads on the CONNECTOR LOOP
		# thread via _handle_trade.
		self._index = VenueCorrelationIndex()

		# Spawned stream-task handles (cancelled by the connector on disconnect).
		self._stream_handles: List[Any] = []

		# Halt entrypoint + pause/resume-on-disconnect callbacks. All None on the
		# paper/backtest path (streams never start there); the supervisor's closures
		# late-bind them so a setter after construction still takes effect.
		self._halt_signal: Optional[Callable[[str], None]] = None
		self._on_stream_down: Optional[Callable[[str], None]] = None
		self._on_stream_up: Optional[Callable[[str], None]] = None

		# Missed-fill catch-up state. Every submitted/adopted order's symbol is tracked so
		# the resume catch-up knows which to re-fetch (over-including one is a dedup-safe
		# no-op). On a stream drop the last venue ms processed becomes the re-fetch floor;
		# on resume the ENGINE thread calls ``catch_up_missed_fills``. Business time only —
		# never wall-clock. The floor is ARM state, not supervisor state.
		self._active_symbols: set[str] = set()
		self._last_venue_ts_ms: Optional[int] = None
		self._disconnect_ts_ms: Optional[int] = None

		# The one shared reconnect ladder. Notable config: reconnect_on_clean_return=False
		# (a forever-loop returning cleanly is a stop, not a reconnect), payload-gated reset
		# (the _consume_* loops call reset_budget only on a delivered payload), and
		# on_down=_on_stream_down_with_floor so the catch-up floor is snapshotted once per
		# down transition. ccxt + the supervisor class are lazy-imported HERE, never at
		# module top, so the module's import graph stays lean.
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
			on_down=self._on_stream_down_with_floor,
			on_up=lambda n: (
				self._on_stream_up(n) if self._on_stream_up is not None else None),
			logger=self.logger,
			label="OKX")

	# --- symbol / time helpers ------------------------------------------------

	def _to_symbol(self, ticker: str) -> str:
		"""Venue symbol for a ticker. Pass-through: the OrderEvent carries the venue symbol."""
		return ticker

	@staticmethod
	def _client_order_id(event: OrderEvent) -> str:
		"""Client order id (clOrdId) for the fast-fill-race pre-correlation.

		OKX requires an alphanumeric clOrdId (<=32 chars). The engine order id (a UUIDv7) is
		base62-encoded LOSSLESSLY with an ``it`` prefix, so distinct order ids yield distinct
		clOrdIds and the venue-echoed clOrdId maps straight back to the pending correlation
		registered before the submit RPC. ``order_id`` is a ``uuid.UUID`` on every live path
		(``.bytes``); the ``int`` fallback keeps the encoder total for int-id test doubles.

		Raises
		------
		ValidationError
			When the rendering would violate the venue's charset/length contract. A REAL
			raise, not a strippable ``assert``: ``python -O`` strips asserts, leaving the
			only guard on a venue-bound identifier absent in an optimized production run.
		"""
		oid = event.order_id
		n = (int.from_bytes(oid.bytes, "big")
		     if hasattr(oid, "bytes") else int(oid))
		if n == 0:
			token = "0"
		else:
			digits: List[str] = []
			while n > 0:
				n, rem = divmod(n, 62)
				digits.append(_CLORDID_ALPHABET[rem])
			token = "".join(reversed(digits))
		clordid = "it" + token
		# A full 128-bit base62 token is <=22 chars, so "it" + token <=24.
		if not clordid.isalnum() or len(clordid) > 32:
			raise ValidationError(
				field="clOrdId", value=clordid,
				message=(
					"rendered client order id violates the OKX clOrdId contract "
					"(must be ASCII alphanumeric and at most 32 characters — the "
					f"venue's own limit; got {len(clordid)} characters, "
					f"alphanumeric={clordid.isalnum()}). This identifier is bound "
					"for a live venue and is the only handle correlating a fill "
					"back to an engine order, so it is REFUSED rather than "
					"submitted or silently truncated."))
		return clordid

	@staticmethod
	def _ms_to_dt(ts: Any) -> datetime:
		"""Convert a venue millisecond timestamp to a tz-aware UTC datetime (business time)."""
		return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)

	# --- order I/O (AbstractExchange core) ------------------------------------

	def on_order(self, event: OrderEvent) -> None:
		"""Translate an ``OrderEvent`` into a venue create/cancel call.

		NEW submits through ``connector.call(create_order(...))``; CANCEL routes through
		``connector.call(cancel_order(...))``. Matching itself is the venue's job — nothing
		fills here; fills arrive asynchronously on the ``watch_my_trades`` stream.
		"""
		try:
			if event.command is OrderCommand.CANCEL:
				self._cancel_order(event)
			else:
				# Preflight as defense-in-depth BEFORE any venue call, mirroring simulated.py.
				# A preflight failure is DEFINITIVE (invalid params/symbol — the order can
				# never rest), so it takes the FillEvent(REFUSED) path, not the
				# in-flight/ambiguous one (reserved for transport ambiguity).
				preflight = self.validate_order(event)
				if not preflight.is_valid:
					self._refuse_preflight(
						event, preflight.error_message or "order failed preflight validation")
					return
				if not self.validate_symbol(event.ticker):
					self._refuse_preflight(
						event, f"unknown symbol {event.ticker}")
					return
				self._submit_order(event)
		except Exception as exc:  # boundary swallow (matches the execution-layer policy)
			self.logger.error(
				"OKX order op failed for %s %s: %s",
				event.action, event.ticker, str(exc), exc_info=True)
			if event.command is OrderCommand.CANCEL:
				# A failed cancel-ack leaves the venue order very likely STILL RESTING.
				# FillEvent(REFUSED) here would drive ReconcileManager._apply_refused ->
				# REJECTED, terminalizing a live resting order — a later real fill then
				# arrives against an order the engine believes is dead. Leave the mirror
				# resting and publish an ErrorEvent (ERROR route -> ErrorHandler.on_error)
				# so the failed cancel is auditable; the next reconcile settles true venue
				# state. Bind the exception TYPE only, never ``str(exc)`` — a connector
				# error may carry request context / a secret.
				self.global_queue.put(ErrorEvent(
					time=event.time,
					source="okx_exchange",
					error_type=type(exc).__name__,
					error_message=(
						f"OKX cancel failed for order {event.order_id} "
						f"({event.ticker}) — mirror left resting, "
						"deferred to reconcile"),
					operation="cancel_order",
					severity=ErrorSeverity.ERROR))
				return
			# SUBMIT failure. Branch on the error CLASS BEFORE any REFUSED emit.
			#
			# AMBIGUOUS transport error (a ``TimeoutError`` from
			# ``connector.call(...).result(timeout=...)``, whose alias also covers the
			# asyncio / concurrent.futures timeouts on 3.11+, or a ccxt ``NetworkError``):
			# the submit MAY have REACHED the venue and be resting / partially filled — only
			# the ack was lost. ``FillEvent(REFUSED)`` here would drive ReconcileManager ->
			# REJECTED, terminalizing a mirror whose order might be live, so a later real
			# fill arrives against an order the engine believes is dead (position + cash
			# drift, unhedged risk). Leave the mirror IN-FLIGHT: it stays PENDING with no
			# terminal FillEvent. The ``clOrdId`` pending correlation still resolves a fill
			# that streams in, and the next ``VenueReconciler`` sweep settles venue truth.
			import ccxt  # lazy: ccxt is transitively imported on the live path only
			ambiguous_transport: tuple[type[BaseException], ...] = (
				TimeoutError, ccxt.NetworkError)
			if isinstance(exc, ambiguous_transport):
				self.logger.warning(
					"OKX submit for order %s (%s) hit an ambiguous transport error "
					"(%s) — mirror left IN-FLIGHT (stays PENDING) pending "
					"fetch_order / reconcile, NOT terminalized to REJECTED",
					event.order_id, event.ticker, type(exc).__name__)
				return
			# DEFINITIVE venue rejection (e.g. ccxt.InvalidOrder — refused outright, never
			# reached the book): flow it back as FillEvent(REFUSED), mirroring
			# SimulatedExchange._emit_rejection, so ReconcileManager transitions the stored
			# mirror PENDING->REJECTED. Only logging would leave it stuck at PENDING forever.
			# The order never rested, so also release the pending clOrdId correlation — NOT
			# done on the ambiguous branch above, which returns early because that order may
			# still be resting and needs the correlation for a streamed fill to resolve.
			self._index.release_pending(self._client_order_id(event))
			self.global_queue.put(FillEvent.new_fill(
				"REFUSED", event, price=event.price, quantity=event.quantity,
				commission=Decimal("0")))

	def _refuse_preflight(self, event: OrderEvent, reason: str) -> None:
		"""Emit a DEFINITIVE FillEvent(REFUSED) for a preflight-rejected order.

		A preflight rejection (non-positive quantity, unknown symbol) means the order never
		reached the venue and can never rest. Mirrors the definitive venue-rejection emit so
		ReconcileManager transitions the mirror PENDING->REJECTED; only logging would leave
		it stuck at PENDING. No pending clOrdId correlation exists yet (registered inside
		``_submit_order``, which never ran), so nothing to release.
		"""
		self.logger.warning(
			"OKX preflight rejected order %s (%s): %s — not submitted",
			event.order_id, event.ticker, reason)
		self.global_queue.put(FillEvent.new_fill(
			"REFUSED", event, price=event.price, quantity=event.quantity,
			commission=Decimal("0")))

	def _submit_order(self, event: OrderEvent) -> None:
		"""Round outbound qty/price to OKX lot/tick (string helpers) and submit via the RPC."""
		# Only MARKET and LIMIT are translated. STOP / TRAILING_STOP carry their trigger in
		# ``event.price`` but the ccxt trigger-param translation is not wired; submitting
		# ``type="stop"`` with ``price=None`` would drop the trigger and let the venue
		# reject or mis-fill, so fail loud and let the on_order boundary turn this into a
		# FillEvent(REFUSED) the mirror can reconcile.
		if event.order_type not in (OrderType.MARKET, OrderType.LIMIT):
			raise NotImplementedError(
				f"OKX arm does not yet translate {event.order_type.value} orders "
				"(trigger-price submission lands with the live order path)")

		symbol = self._to_symbol(event.ticker)
		client = self._connector.client
		# Pass the Decimal's STRING form, not float(), so the outbound value never enters
		# binary float; ccxt re-rounds to lot/tick and returns the authoritative string.
		amount = client.amount_to_precision(symbol, str(event.quantity))
		otype = event.order_type.value.lower()
		side = event.action.value.lower()
		price: Optional[str] = None
		if event.order_type is OrderType.LIMIT and event.price is not None:
			price = client.price_to_precision(symbol, str(event.price))

		# ccxt's okx defaults ``createMarketBuyOrderRequiresPrice = True``, under which a spot
		# market BUY needs a price to derive cost or it raises InvalidOrder. The arm already
		# submits ``amount`` as the BASE quantity, so disable that mode for market buys.
		# Market sells and limit orders are unaffected (empty params).
		params: Dict[str, Any] = {}
		if event.order_type is OrderType.MARKET and event.action is Side.BUY:
			params["createMarketBuyOrderRequiresPrice"] = False

		# Fast-fill-race pre-correlation: register the pending correlation keyed by clOrdId
		# BEFORE the create_order RPC. OKX echoes clOrdId back on the fill, so a fill that
		# streams in before the RPC returns the venue id still resolves its OrderEvent.
		client_order_id = self._client_order_id(event)
		params["clOrdId"] = client_order_id
		self._index.register_pending(client_order_id, event)
		# Track the symbol BEFORE the RPC so an ambiguous submit timeout (mirror left
		# in-flight) still contributes its symbol to the resume catch-up.
		self._active_symbols.add(event.ticker)

		response = self._connector.call(
			client.create_order(symbol, otype, side, amount, price, params=params))

		venue_id = response.get("id") if isinstance(response, dict) else None
		if venue_id is not None:
			# ``register`` drains fills that streamed back before the venue id landed under the
			# index lock and RETURNS them; re-drain OUTSIDE it, since _handle_trade re-acquires
			# the non-reentrant index lock.
			for buffered_trade in self._index.register(venue_id, event, client_order_id):
				self._handle_trade(buffered_trade)
			# Persist the venue ack: the in-memory index alone is lost across a restart, so emit
			# an ORDER-ACK — OrderHandler.on_order_ack persists venue_order_id onto the stored
			# mirror. Queue-only: the exchange never writes the order store directly, and the
			# raw venue payload never rides onto the event.
			self.global_queue.put(OrderAckEvent.new_order_ack(event, str(venue_id)))

	def _cancel_order(self, event: OrderEvent) -> None:
		"""Cancel the venue order correlated to ``event.order_id`` via the RPC."""
		symbol = self._to_symbol(event.ticker)
		venue_id = self._index.venue_id_for(event.order_id)
		if venue_id is None:
			self.logger.warning(
				"Cancel for order %s has no known venue id — skipping", event.order_id)
			return
		self._connector.call(self._connector.client.cancel_order(venue_id, symbol))

	def adopt_venue_correlation(self, order: Any) -> None:
		"""Restart-rehydration correlation seam.

		A pre-restart Order never went through ``_submit_order``, the only path that populates
		the correlation index — so without adoption a post-restart fill for a rehydrated
		resting order resolves to no OrderEvent and is buffered forever (silently lost), and a
		cancel of that order is a silent no-op. ``VenueReconciler.reconcile`` calls this during
		restart rehydration for each working-set order (and re-linked bracket leg) carrying a
		persisted ``venue_order_id``.
		"""
		venue_id = order.venue_order_id
		if venue_id is None:
			# An order the venue never acknowledged — nothing to correlate.
			return
		event = OrderEvent.new_order_event(order)
		venue_id = str(venue_id)
		# A rehydrated resting order is active — track its symbol for the resume catch-up.
		self._active_symbols.add(event.ticker)
		# ``adopt`` RETURNS any fills buffered before this correlation landed. Re-drain
		# OUTSIDE the index lock — _handle_trade re-acquires it and it is non-reentrant.
		for buffered_trade in self._index.adopt(
			venue_id, event, self._client_order_id(event)):
			self._handle_trade(buffered_trade)

	def on_market_data(self, bar: Any) -> None:
		"""No-op: the venue matches resting orders, not us. A bar never produces a fill on the
		live path — fills stream back on ``watch_my_trades``. Present for the seam."""
		return None

	# --- streaming (the exchange emits FillEvents itself) ---------------------

	def _handle_trade(self, trade: Any) -> None:
		"""Translate one venue fill (ccxt-unified trade) into a ``FillEvent``.

		Idempotent + race-safe: a reconnect re-send carries the same ``trade['id']`` and is a
		no-op, and a fill arriving before its ``create_order`` RPC returns the venue id is
		resolved via the ``clOrdId`` pending correlation or BUFFERED for late correlation
		(drained by ``_submit_order`` once the venue-id map lands) — never silently dropped.
		"""
		# The index resolves + dedups + buffers under its own lock; this arm mints and emits
		# OUTSIDE it (the FillEvent mint touches no correlation map).
		result = self._index.resolve(trade)
		if result.outcome == "duplicate":
			return
		if result.outcome == "buffered":
			# Uncorrelated but keyable: _submit_order / adopt_venue_correlation re-drain
			# once the venue-id map lands (never dropped).
			self.logger.warning(
				"Fill for not-yet-correlated venue order %s — buffered for late correlation",
				result.venue_id)
			return
		if result.outcome == "uncorrelated":
			# No venue id to key a buffer on — skip-and-log.
			self.logger.warning("Fill with no venue order id — skipping")
			return
		assert result.order is not None  # narrowed by outcome == "emit"
		emitted = self._emit_fill(trade, result.order, result.venue_id)
		# Consume the dedup slot ONLY after a True emit — ``resolve`` deliberately did NOT mark
		# the key seen, so a malformed payload leaves the slot free and a corrected re-send of
		# the same {ticker}:{trade_id} still emits.
		if emitted and result.dedup_key is not None:
			self._index.mark_seen(result.dedup_key)
		# Feed the cumulative-filled counter and, once this fill terminalizes the order,
		# self-release its correlation entries so the maps stay bounded over a long session.
		# Gate on an actual emit + a keyable venue_id: a skipped fill must not advance the
		# counter, and a clOrdId-only resolve has no venue-id-keyed entry to release.
		if emitted and result.venue_id is not None:
			amount = trade.get("amount") if isinstance(trade, dict) else None
			if amount is not None and self._index.record_fill(
				result.venue_id, result.order, to_money(str(amount))):
				self.release_venue_correlation(result.venue_id)

	def _emit_fill(self, trade: Any, order: OrderEvent, venue_id: Any) -> bool:
		"""Mint the FillEvent for a correlated venue trade and put it on ``global_queue``.

		Returns
		-------
		bool
			True when a FillEvent was emitted; False when the payload was malformed and
			skipped, so the caller does NOT advance the cumulative-filled counter for a fill
			that never settled.
		"""
		price = trade.get("price")
		amount = trade.get("amount")
		timestamp = trade.get("timestamp")
		if price is None or amount is None or timestamp is None:
			self.logger.warning(
				"Malformed fill payload for order %s (missing price/amount/timestamp) — skipping",
				venue_id)
			return False
		# Advance the catch-up floor so a later stream drop re-fetches only from the last fill
		# actually processed, not from epoch.
		self._last_venue_ts_ms = int(timestamp)
		# ccxt frequently emits ``fee: {"cost": None, ...}``, so ``fee.get("cost", 0)`` returns
		# None (the key IS present) and ``to_money(str(None))`` would raise InvalidOperation,
		# killing the whole fill stream — guard None/missing BEFORE the Decimal edge.
		# Commission is a MAGNITUDE: portfolio_handler/validators.py hard-rejects a negative
		# one. ccxt's ``okx.parse_trade`` normally sign-flips the raw fee positive, but a
		# raw/non-unified payload or a ccxt convention change can yield a negative cost that
		# would crash the fill at the portfolio boundary and drop it.
		fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
		fee_cost = fee.get("cost")
		commission = abs(to_money(str(fee_cost))) if fee_cost is not None else Decimal("0")
		# OKX charges the spot BUY taker fee in the pair's BASE asset, so the venue credits
		# ``amount - base_fee``. Dropping the currency makes the engine record the full
		# ``amount``, overstating the position by the fee and tripping the on-fill drift halt.
		fee_currency = fee.get("currency")
		fee_currency = str(fee_currency) if fee_currency is not None else None

		# Cross-emitter idempotency key. The index's dedup ring catches a stream re-send
		# BEFORE mint; stamping the venue trade id here lets the portfolio settlement
		# chokepoint ALSO dedup the same economic trade adopted by the restart
		# VenueReconciler, which bypasses that ring.
		trade_id = trade.get("id") if isinstance(trade, dict) else None
		venue_trade_id = str(trade_id) if trade_id is not None else None

		fill = FillEvent.new_fill(
			"EXECUTED", order,
			price=to_money(str(price)),
			quantity=to_money(str(amount)),
			commission=commission,
			time=self._ms_to_dt(timestamp),
			venue_trade_id=venue_trade_id,
			fee_currency=fee_currency)
		# The EXCHANGE emits the fill; MPSC-safe put from the connector loop thread.
		self.global_queue.put(fill)
		return True

	def release_venue_correlation(self, venue_id: str) -> None:
		"""Release a terminalized order's venue correlation — the OUTBOUND twin of
		``adopt_venue_correlation``.

		Drain buffered late fills through the FULL ``_handle_trade`` → ``resolve`` path BEFORE
		the index drops the correlation — NOT raw ``_emit_fill``, which bypasses the dedup
		ring so a re-delivered buffered fill would double-count. ``take_pending`` empties the
		buffer while the correlation is still present so each drained fill re-resolves to its
		order; ``release`` then evicts the drained entries. Idempotent: an unknown /
		already-released ``venue_id`` drains nothing and drops nothing.
		"""
		for buffered_trade in self._index.take_pending(venue_id):
			self._handle_trade(buffered_trade)
		self._index.release(venue_id)

	def catch_up_missed_fills(self) -> None:
		"""Recover fills that settled while the fill stream was down.

		Runs on the ENGINE / resume path — NOT the connector loop thread. It bridges the async
		``fetch_my_trades`` through the blocking ``connector.call``, which does
		``run_coroutine_threadsafe(...).result()``; calling that FROM the loop thread would
		deadlock.

		For each active-order symbol it fetches the venue's trades since the disconnect floor
		(a venue-ms business timestamp captured at the stream-down transition) and routes each
		through ``_handle_trade``. Safe to re-run, and safe against the live stream ALSO
		redelivering the same trade: ``{symbol}:{trade_id}`` dedup makes a re-fetched trade an
		idempotent no-op, so the missed fill settles EXACTLY once. Bounded to a SINGLE page
		with an explicit ``limit`` — no ccxt auto-pagination — honoring the venue's ~3-month /
		100-per-page window. A fetch or translation failure is swallow-and-logged, with the
		next reconcile sweep as backstop, so the resume path never crashes on catch-up.
		"""
		symbols = sorted(self._active_symbols)
		if not symbols:
			# Clear the floor unconditionally: ``_on_stream_down_with_floor`` only re-arms it
			# when it is ``None``, so a stale value left here would suppress re-arming on the
			# next disconnect. No active symbols means no missed fills, so nothing is lost.
			self._disconnect_ts_ms = None
			return
		since = self._disconnect_ts_ms
		client = self._connector.client
		for symbol in symbols:
			try:
				trades = self._connector.call(client.fetch_my_trades(
					self._to_symbol(symbol), since=since, limit=_CATCHUP_TRADE_LIMIT))
			except Exception:
				# The connector error may carry request context — log via exc_info (the
				# sink scrubs), never str(exc) into the message.
				self.logger.error(
					"OKX missed-fill catch-up fetch failed for %s — deferred to reconcile",
					symbol, exc_info=True)
				continue
			for trade in trades or []:
				# A single malformed trade must not abort the remaining catch-up.
				try:
					self._handle_trade(trade)
				except Exception as exc:
					# A skipped catch-up fill is as silent a settlement loss as one
					# skipped on the live drain path, so emit the same counted
					# FILL_TRANSLATION ErrorEvent rather than log-only.
					self.logger.error(
						"OKX missed-fill catch-up translation failed — skipping trade",
						exc_info=True)
					self.global_queue.put(ErrorEvent(
						# Wall clock: the trade did NOT translate, so no business time exists.
						time=datetime.now(timezone.utc),
						source="okx_exchange",
						error_type=type(exc).__name__,
						error_message=_FILL_TRANSLATION_ERROR_MSG,
						operation="fill-translation",
						severity=ErrorSeverity.ERROR))
		# Floor consumed — a subsequent disconnect re-arms it (idempotent re-run otherwise).
		self._disconnect_ts_ms = None

	# --- reconnect supervisor --------------------------------------------------

	def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
		"""Inject the connector-fatal halt signal.

		Called with reason ``'connector-fatal'`` when a stream hits a fatal connector error
		(auth/permission) or exhausts the reconnect retry ceiling. It runs on the connector
		ASYNCIO LOOP thread, so the injected signal MUST be non-blocking: the composition root
		wires ``_request_connector_halt`` (a thread-safe flag setter), NOT ``halt()``, whose
		blocking durable ``record_halt`` SQL write would stall every stream sharing the loop.
		The engine thread drains the flag and runs the blocking halt off the loop. The arm
		passes no exception text, only the fixed reason, so no secret leaks.
		"""
		self._halt_signal = halt_signal

	def set_stream_state_listener(
		self,
		on_down: Callable[[str], None],
		on_up: Callable[[str], None],
	) -> None:
		"""Inject the pause/resume-on-disconnect callbacks.

		``on_down`` fires when a stream stays disconnected past the debounce window (pause NEW
		order submission); ``on_up`` fires on reconnect and owns the
		resume-only-after-fresh-REST-reconcile discipline. Both fire from the connector loop
		thread, so neither may perform blocking venue I/O — the wiring flips a flag only.
		"""
		self._on_stream_down = on_down
		self._on_stream_up = on_up

	def is_streaming_healthy(self) -> bool:
		"""True iff this arm's stream set (fills+orders) is fully up.

		Delegates to the shared ``StreamSupervisor``. Read by
		``StreamRecoveryHandler._all_venue_streams_healthy`` on the ENGINE thread while the
		connector loop mutates the supervisor's down-set — a GIL-atomic emptiness read taken
		without a lock, since any staleness self-heals via the re-fired resume Event.
		"""
		return self._supervisor.is_healthy()

	def _on_stream_down_with_floor(self, stream_name: str) -> None:
		"""Supervisor ``on_down``: snapshot the catch-up floor, then pause.

		The floor is ARM state, not supervisor state — only the OKX order arm has one — so it
		is snapshotted in this wrapper rather than inside the shared supervisor.
		``mark_down`` dedups, firing ``on_down`` exactly once per down transition, so the
		floor is taken once per drop from the last processed venue ms (never wall-clock).
		Runs on the connector loop thread — flag-only, no blocking venue I/O. Only the first
		drop sets the floor; it clears once the catch-up consumes it.
		"""
		if self._disconnect_ts_ms is None:
			self._disconnect_ts_ms = self._last_venue_ts_ms
		if self._on_stream_down is not None:
			self._on_stream_down(stream_name)

	async def _stream_fills(self) -> None:
		"""Consume the venue fill stream under the reconnect supervisor."""
		await self._supervisor.run(self._consume_fills, "fills")

	async def _consume_fills(self, stream_name: str) -> None:
		"""Forever-loop: emit a FillEvent per venue trade; reconnect-supervised."""
		while True:
			trades = await self._connector.client.watch_my_trades()
			# Subscribe/ack: resume submission if we were paused.
			self._supervisor.mark_up(stream_name)
			# Only a delivered payload resets the retry budget — a subscribe-then-close storm
			# must never keep the ceiling from tripping.
			if trades:
				self._supervisor.reset_budget(stream_name)
			for trade in trades:
				# A single malformed trade must not kill the forever-loop and silently
				# drop every subsequent fill — swallow-and-log per trade instead.
				try:
					self._handle_trade(trade)
				except Exception as exc:
					# A skipped venue fill is a SILENT settlement loss, so emit a counted
					# ErrorEvent onto the ERROR route (funnelling to FILL_TRANSLATION ->
					# SETTLEMENT halt-on-first), not log-only.
					self.logger.error(
						"OKX fill translation failed — skipping trade", exc_info=True)
					self.global_queue.put(ErrorEvent(
						# Wall clock: the trade did NOT translate, so no business time exists.
						time=datetime.now(timezone.utc),
						source="okx_exchange",
						error_type=type(exc).__name__,
						error_message=_FILL_TRANSLATION_ERROR_MSG,
						operation="fill-translation",
						severity=ErrorSeverity.ERROR))

	async def _stream_orders(self) -> None:
		"""Consume the order-status stream under the reconnect supervisor (status only).

		The fill money crosses on ``watch_my_trades``; this loop never mints money.
		"""
		await self._supervisor.run(self._consume_orders, "orders")

	async def _consume_orders(self, stream_name: str) -> None:
		"""Forever-loop: reconcile venue order-status updates; reconnect-supervised.

		Per-row swallow-and-log (matching ``_consume_fills``) so one malformed row never kills
		the forever-loop and silently drops every subsequent order update.
		"""
		while True:
			orders = await self._connector.client.watch_orders()
			self._supervisor.mark_up(stream_name)
			# Payload-gated retry-budget reset (>=1 order update).
			if orders:
				self._supervisor.reset_budget(stream_name)
			for order in orders:
				try:
					self._handle_order_update(order)
				except Exception:
					self.logger.error(
						"OKX order-update translation failed — skipping", exc_info=True)

	def _handle_order_update(self, order: Any) -> None:
		"""Translate one venue order-status row into a mirror-reconciling event.

		A venue-side CANCELLED/EXPIRED (a cancel/expiry the engine did NOT command — an OKX
		MMP cancel, a post-only reject, a GTD expiry) must reconcile the mirror, else the
		order sits PENDING forever; a ``FillEvent(CANCELLED/EXPIRED)`` on ``global_queue``
		drives it terminal through ``OrderHandler.on_fill``. Every other status stays
		log-only: ``closed`` (FILLED) is the money path that already crosses on
		``watch_my_trades``, so translating it here would double-settle. An uncorrelated row
		is deferred to the reconcile sweep.
		"""
		if not isinstance(order, dict):
			self.logger.debug("OKX order update (non-dict) — skipping: %s", order)
			return
		status = order.get("status")
		fill_status = (_ORDER_STATUS_TO_FILL.get(str(status).lower())
		               if status is not None else None)
		if fill_status is None:
			# Non-terminal / FILLED (money crosses on watch_my_trades) — log only.
			self.logger.debug("OKX order update: %s", order)
			return
		venue_id = order.get("id")
		event = (self._index.order_for_venue_id(str(venue_id))
		         if venue_id is not None else None)
		if event is None:
			self.logger.warning(
				"Venue %s for order %s has no correlated OrderEvent — deferred to reconcile",
				fill_status, venue_id)
			return
		timestamp = order.get("timestamp")
		if timestamp is not None:
			self._last_venue_ts_ms = int(timestamp)
		fill_time = self._ms_to_dt(timestamp) if timestamp is not None else None
		# Commission Decimal("0"): a cancel/expiry never settles money.
		self.global_queue.put(FillEvent.new_fill(
			fill_status, event, price=event.price, quantity=event.quantity,
			commission=Decimal("0"), time=fill_time))

	# --- connection lifecycle -------------------------------------------------

	def connect(self) -> ConnectionResult:
		"""Spawn the venue streams and mark connected (the connector owns the loop lifecycle).

		The connector already owns the asyncio loop on its daemon thread; this launches the
		two long-running ``watch_*`` consume-loops via ``connector.spawn`` — never
		``.result()``-awaited, since they loop forever — and records the handles so the
		connector can cancel them on its own ``disconnect``.
		"""
		try:
			self._stream_handles = [
				self._connector.spawn(self._stream_fills()),
				self._connector.spawn(self._stream_orders()),
			]
			self._connected = True
			self._connection_status = ExchangeConnectionStatus.CONNECTED
			self.logger.info("OKX exchange streams spawned")
			return ConnectionResult(
				success=True,
				status=ExchangeConnectionStatus.CONNECTED,
				exchange_name=self._exchange_name)
		except Exception as exc:
			self._connection_status = ExchangeConnectionStatus.ERROR
			self.logger.error("Failed to spawn OKX streams: %s", str(exc), exc_info=True)
			return ConnectionResult(
				success=False,
				status=ExchangeConnectionStatus.ERROR,
				exchange_name=self._exchange_name,
				error_code=ExecutionErrorCode.NETWORK_ERROR,
				error_message=str(exc))

	def disconnect(self) -> ConnectionResult:
		"""Mark disconnected. Stream-task cancellation is owned by the connector's disconnect."""
		self._connected = False
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED
		self._stream_handles = []
		self.logger.info("OKX exchange disconnected")
		return ConnectionResult(
			success=True,
			status=ExchangeConnectionStatus.DISCONNECTED,
			exchange_name=self._exchange_name)

	def is_connected(self) -> bool:
		"""Whether the arm has spawned its streams and considers itself live."""
		return (self._connected and
		        self._connection_status is ExchangeConnectionStatus.CONNECTED)

	# --- health / config / validation -----------------------------------------

	def health_check(self) -> HealthStatus:
		"""Report basic connection health (no synchronous venue ping on the arm)."""
		return HealthStatus(
			exchange_name=self._exchange_name,
			connected=self._connected,
			status=self._connection_status)

	def configure(self, config: Dict[str, Any]) -> bool:
		"""No arm-local config today — venue credentials/routing live on the connector."""
		return True

	def validate_order(self, event: OrderEvent) -> OrderPreflightResult:
		"""Execution-domain preflight: reject a non-positive quantity, else pass."""
		if event.quantity <= Decimal("0"):
			return OrderPreflightResult(
				is_valid=False,
				error_code=ExecutionErrorCode.INVALID_ORDER,
				error_message="order quantity must be positive")
		return OrderPreflightResult(is_valid=True)

	def validate_symbol(self, symbol: str) -> bool:
		"""Consult the connector client's loaded markets; FAIL-CLOSED on a cold cache.

		``load_markets`` runs in the connector, so a loaded ``markets`` map is the source of
		truth. When it is NOT yet a loaded dict the symbol cannot be verified, so this returns
		**False**: failing OPEN would let a delisted/invalid symbol slip through the pre-load
		window. That does not dark the initial universe — initial membership comes from
		``derive_membership``, and ``_initialize_live_session`` precedes
		``connect()``/``load_markets``, so the universe poll (the sole caller) runs
		post-connect with ``markets`` loaded.

		The check normalises through the SAME ``_to_symbol`` helper the submit path uses, so a
		caller-form vs markets-key mismatch cannot inconsistently accept/reject a symbol as
		that helper grows.
		"""
		markets = getattr(self._connector.client, "markets", None)
		if isinstance(markets, dict):
			return self._to_symbol(symbol) in markets
		# Fail-closed: markets not yet loaded -> cannot verify -> reject.
		return False

	def resolve_precision(self, symbol: str) -> "Instrument | None":
		"""Resolve a poll-added symbol's venue precision from the loaded-markets map.

		Reads the SAME ccxt loaded-markets precision the submit path consumes via
		``price_to_precision`` / ``amount_to_precision``, converting the venue tick sizes into
		an ``Instrument`` through ``core/money.precision_to_scale``.

		Returns ``None`` when markets aren't loaded / the symbol is absent / a precision entry
		is unusable, so ``UniverseHandler.on_poll`` falls to ``Universe.apply``'s
		``_DEFAULT_*`` ladder and a cold markets map cannot crash the poll. ``Universe`` stays
		connector-free: every connector read happens HERE.
		"""
		connector = getattr(self, "_connector", None)
		client = getattr(connector, "client", None)
		markets = getattr(client, "markets", None)
		if not isinstance(markets, dict):
			return None
		# Normalise through the SAME _to_symbol helper validate_symbol uses.
		key = self._to_symbol(symbol)
		market = markets.get(key)
		if not isinstance(market, dict):
			return None
		precision = market.get("precision")
		if not isinstance(precision, dict):
			return None
		price_scale = precision_to_scale(precision.get("price"))
		quantity_scale = precision_to_scale(precision.get("amount"))
		if price_scale is None or quantity_scale is None:
			return None
		# Inert margin defaults (mirror instruments.derive_instruments — unused on the spot
		# path; present so every constructed Instrument is well-formed).
		return Instrument(
			symbol=symbol.upper(),
			price_precision=price_scale,
			quantity_precision=quantity_scale,
			maintenance_margin_rate=Decimal("0.005"),
			max_leverage=Decimal("1"),
		)
