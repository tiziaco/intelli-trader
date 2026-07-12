"""OkxExchange — the live sibling of ``SimulatedExchange`` (order arm, CONN-02 / CONN-05).

``OkxExchange`` implements the same ``AbstractExchange`` structural seam ``SimulatedExchange``
satisfies, so it drops straight into ``ExecutionHandler.on_order`` (routed by
``event.exchange``). Unlike the simulated exchange it does NOT match orders itself — the OKX
venue is the matching engine. The arm's job is pure translation across the venue boundary:

- submit / cancel orders through the injected connector session (``connector.call`` RPC), and
- stream order-status + fills from the venue (``connector.spawn`` on ``watch_orders`` /
  ``watch_my_trades`` — the fill stream is the my-trades channel, NOT a fills channel, which
  ccxt.pro does not expose), translating each raw fill into a frozen ``FillEvent`` it puts on
  ``global_queue`` itself (D-07). The connector
  emits nothing; D-19 is preserved — portfolio state still mutates only on the engine thread via
  ``on_fill``, the arm only ``put``s onto the MPSC-safe ``queue.Queue`` from the connector loop
  thread.

Decimal edge (CONN-05): every inbound venue float crosses the Decimal boundary via
``to_money(str(x))``; outbound quantities/prices round to OKX lot/tick via the ccxt string
helpers ``amount_to_precision`` / ``price_to_precision`` (``load_markets`` already ran in the
connector). NEVER ``Decimal(<venue float>)``. Business time: ``FillEvent.time`` is stamped from
the venue fill timestamp, never wall-clock.

Dependency injection (D-04): the arm types against the ``LiveConnector`` session Protocol only —
it never imports the connector concretion. IN-01: ``LiveConnector`` is imported from the
ccxt-free ``itrader.connectors.base`` module, NOT the ``itrader.connectors`` barrel — the barrel
eagerly imports ``OkxConnector`` (and therefore ``ccxt.pro``), so importing the pure Protocol
from ``base`` keeps the Protocol import ccxt-free and cannot couple a consumer to ``ccxt.pro``.

Indentation: this tree is TAB-indented (a mixed-indent diff breaks the file).
"""

from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Callable, Dict, List, Optional

from itrader.config.stream import StreamSettings
from itrader.connectors.base import LiveConnector
from itrader.core.enums import ErrorSeverity, OrderCommand, OrderType, Side
from itrader.core.enums.execution import ExchangeConnectionStatus, ExecutionErrorCode
from itrader.core.instrument import Instrument
from itrader.core.money import precision_to_scale, to_money
from itrader.events_handler.events import ErrorEvent, FillEvent, OrderAckEvent, OrderEvent
from itrader.logger import get_itrader_logger

from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult
from .base import AbstractExchange
from .venue_correlation import VenueCorrelationIndex


# WR-04: OKX clOrdId charset. The client order id is the fast-fill-race
# correlation key (``_orders_by_clOrdId``) and MUST be unique per order.
# Base62 of the order id's 128 bits is LOSSLESS (a bijection on the 16 raw
# UUID bytes) and renders to <=22 chars, so ``"it"`` + token stays under
# OKX's 32-char alphanumeric clOrdId limit with the full 128-bit entropy
# preserved. The old ``("it" + hex_token)[:32]`` dropped the UUID tail bits,
# so two orders differing only there collided on one clOrdId (wrong-order
# fill correlation).
_CLORDID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# D-12 (V17-08): bounded missed-fill catch-up page size. On resume the arm
# re-fetches at most this many recent trades per active symbol via a SINGLE
# ``fetch_my_trades`` page (explicit ``limit``, NO ccxt auto-pagination) since the
# disconnect floor — enough to cover a realistic reconnect-window fill burst. D-08
# ``{symbol}:{trade_id}`` dedup makes any re-fetched (or live-redelivered) trade an
# idempotent no-op, so an under-sized page only defers the tail to the next
# reconcile, never double-settles. ccxt's okx caps a fetch_my_trades page at 100.
_CATCHUP_TRADE_LIMIT = 100

# D-12: ccxt-unified terminal order statuses that reconcile the mirror via a
# FillEvent — a venue-side cancel/expiry the engine did NOT itself command (an OKX
# MMP cancel, a post-only reject, a GTD expiry). ``closed`` (FILLED) is deliberately
# absent: that money already crosses on ``watch_my_trades``, so translating it here
# would double-settle. Keys are lower-cased before lookup.
_ORDER_STATUS_TO_FILL: Dict[str, str] = {
	"canceled": "CANCELLED",
	"cancelled": "CANCELLED",
	"expired": "EXPIRED",
}


class OkxExchange(AbstractExchange):
	"""Live OKX order arm implementing ``AbstractExchange`` against an injected session.

	Constructor mirrors ``SimulatedExchange`` (positional ``global_queue`` first) and takes
	the injected ``LiveConnector`` session Protocol (D-04 — the seam, not the concretion).
	The exchange keeps a small venue-id <-> ``OrderEvent`` correlation map so a fill streamed
	back from ``watch_my_trades`` can be resolved to its originating order for
	``FillEvent.new_fill`` (which carries order_id/strategy_id/portfolio_id off that order).
	"""

	def __init__(self, global_queue: "Queue[Any]", connector: "LiveConnector") -> None:
		"""Bind the queue + injected session; no venue socket is opened here.

		Parameters
		----------
		global_queue : Queue
			The trading system's shared event queue — the exchange ``put``s FillEvents here
			itself (D-07). The ``put`` may fire from the connector's asyncio thread; that is
			safe (``queue.Queue`` is MPSC-safe, D-19).
		connector : LiveConnector
			The injected session/transport Protocol (D-04). The arm drives ``create_order`` /
			``cancel_order`` via ``connector.call`` and the ``watch_*`` streams via
			``connector.spawn``, and reads the shared ``ccxt.pro`` client for the precision
			helpers — it never imports the connector concretion (types against the Protocol only).
		"""
		self.logger = get_itrader_logger().bind(component="OkxExchange")
		self.global_queue = global_queue
		# D-04: the injected session Protocol, NOT the concretion.
		self._connector = connector

		self._exchange_name = "okx"
		self._connected = False
		self._connection_status = ExchangeConnectionStatus.DISCONNECTED

		# Venue-id correlation (WR-05 R1): all venue-correlation state — the three
		# venue-id / order-id / clOrdId maps, the late-fill buffer, the bounded
		# trade-id dedup ring, the cumulative-filled counter, and the cross-thread
		# lock — lives on VenueCorrelationIndex; this arm DELEGATES to it. A streamed
		# fill (watch_my_trades) carries the venue order id; the index resolves it
		# back to the originating OrderEvent so FillEvent.new_fill carries the
		# order_id/strategy_id/portfolio_id audit chain (D-12).
		# WR-03: the index guards every map/ring/counter read+write with its own lock
		# (writes on the ENGINE thread via submit/cancel; reads on the CONNECTOR LOOP
		# thread via _handle_trade). The fast-fill race (a fill pushed before
		# create_order returns the venue id) is closed by the clOrdId pre-correlation
		# + unmatched-fill buffer inside the index (D-12, Pitfall 11); WR-05 R2/R3
		# additionally bound the state (fill-driven release-on-terminal + the dedup
		# ring) so it no longer grows without limit over a long live session.
		self._index = VenueCorrelationIndex()

		# Spawned stream-task handles (cancelled by the connector on disconnect).
		self._stream_handles: List[Any] = []

		# Injected seams (composition root, 05-08 Task 2): the 05-04 freeze-in-place
		# halt entrypoint (fatal / exhausted -> HALTED + CRITICAL alert) and the
		# pause/resume-on-disconnect callbacks (D-19). All None on the paper/backtest
		# path (streams never start there); the shared supervisor's closures late-bind
		# them so a setter after construction still takes effect.
		self._halt_signal: Optional[Callable[[str], None]] = None
		self._on_stream_down: Optional[Callable[[str], None]] = None
		self._on_stream_up: Optional[Callable[[str], None]] = None

		# D-12 (V17-08): missed-fill catch-up state. Every submitted/adopted order's
		# symbol is tracked so the resume catch-up knows WHICH symbols to re-fetch
		# (the venue universe is small, so a symbol that never terminalizes is
		# naturally bounded — over-including one is a dedup-safe no-op). When a stream
		# drops we snapshot the last venue-ms timestamp processed
		# (``_last_venue_ts_ms``) as the re-fetch floor (``_disconnect_ts_ms``); on
		# resume the ENGINE thread calls ``catch_up_missed_fills`` to recover trades
		# that settled during the gap. Business time only — never wall-clock. This
		# floor stays ARM state (D-12) — it is NOT supervisor state; the supervisor's
		# on_down callback (`_on_stream_down_with_floor`) snapshots it (05-01/D-08).
		self._active_symbols: set[str] = set()
		self._last_venue_ts_ms: Optional[int] = None
		self._disconnect_ts_ms: Optional[int] = None

		# 05-01 (D-08 / CF-4 / VENUE-07): the ONE shared reconnect ladder. This arm
		# HAS-A StreamSupervisor and delegates its consume-loop supervision to it (the
		# triplicated reconnect-supervisor fork is gone; _reconnect_attempts /
		# _streams_down / the reconnect tuning now live on the supervisor). The order
		# arm's EXACT donor config: the ccxt-only 3-type transient set,
		# reconnect_on_clean_return=False (a forever-loop returning cleanly is a stop),
		# payload-gated reset (the _consume_* loops call reset_budget on a delivered
		# payload), and on_down=_on_stream_down_with_floor so the D-12 catch-up floor is
		# snapshotted once per down transition (the supervisor's mark_down dedup ensures
		# it fires once). ccxt + the supervisor class are lazy-imported HERE (never at
		# module top) so the module's import graph stays lean on the live path.
		import ccxt

		from itrader.connectors.stream_supervisor import StreamSupervisor
		self._supervisor = StreamSupervisor(
			StreamSettings(),
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
		"""Venue symbol for a ticker. Pass-through today (the OrderEvent carries the venue
		symbol); a dedicated translation table lands with the data arm if needed."""
		return ticker

	@staticmethod
	def _client_order_id(event: OrderEvent) -> str:
		"""Client order id (clOrdId) for the Pitfall-11 fast-fill-race pre-correlation.

		OKX requires an alphanumeric clOrdId (<=32 chars). The engine order id
		(a UUIDv7 — the locked single-UUID-scheme decision) is rendered LOSSLESSLY
		to a compact alphanumeric token by base62-encoding its 128 bits, with an
		``it`` prefix. Lossless + deterministic (WR-04): distinct order ids yield
		distinct clOrdIds — no truncation collision — and the venue-echoed clOrdId
		maps straight back to the pending correlation registered before the submit
		RPC. ``order_id`` is a ``uuid.UUID`` on every live path (``.bytes``); the
		``int`` fallback keeps the encoder total for the int-id test doubles.
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
		# WR-04 rendering contract: alphanumeric + within OKX's 32-char clOrdId
		# limit. A full 128-bit base62 token is <=22 chars, so "it" + token <=24.
		assert clordid.isalnum() and len(clordid) <= 32, (
			f"clOrdId {clordid!r} violates the OKX charset/length contract")
		return clordid

	@staticmethod
	def _ms_to_dt(ts: Any) -> datetime:
		"""Convert a venue millisecond timestamp to a tz-aware UTC datetime (business time).

		Stamped from the venue's own fill timestamp — never the process wall-clock (which is
		contagious on the live path; business-time discipline).
		"""
		return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)

	# --- order I/O (AbstractExchange core) ------------------------------------

	def on_order(self, event: OrderEvent) -> None:
		"""Translate an ``OrderEvent`` into a venue create/cancel call (D-06).

		NEW submits through ``connector.call(create_order(...))``; CANCEL routes through
		``connector.call(cancel_order(...))``. Matching itself is the venue's job — nothing
		fills here; fills arrive asynchronously on the ``watch_my_trades`` stream.
		"""
		try:
			if event.command is OrderCommand.CANCEL:
				self._cancel_order(event)
			else:
				# D-18 (V17-16, ASVS V4/V5): run the execution-domain preflight as
				# defense-in-depth BEFORE any venue call, mirroring simulated.py's
				# validate_order/validate_symbol placement. A preflight failure is a
				# DEFINITIVE rejection (the order params/symbol are invalid — it can
				# never rest), so it flows back as FillEvent(REFUSED) exactly like the
				# ccxt.InvalidOrder branch below, NOT the D-13 in-flight/ambiguous path
				# (which is reserved for transport ambiguity where the order MAY be live).
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
			# WR-01: branch on the command — a failed CANCEL is NOT an execution
			# event and must not travel the fill/execution channel.
			if event.command is OrderCommand.CANCEL:
				# A cancel-ack failure is a command-ack failure: the venue order
				# is very likely STILL RESTING. Emitting FillEvent(REFUSED) here
				# would drive ReconcileManager._apply_refused -> REJECTED, wrongly
				# terminalizing a live resting order (later a real fill arrives
				# against an order the engine believes is dead). Leave the mirror
				# in its resting state and publish an ErrorEvent on the existing
				# operator/dead-letter channel (ERROR route -> _log_error_event) so
				# the failed cancel is AUDITABLE; the next reconcile / drift pass
				# reconciles true venue state. (Nautilus OrderCancelRejected leaves
				# order state untouched; a first-class OrderCancelRejected event is
				# the full-parity option, DEFERRED — ErrorEvent gets correctness
				# now.) Scrub (T-05-27): bind the exception TYPE only, never
				# ``str(exc)`` — a connector error may carry request context /
				# a secret.
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
			# SUBMIT failure. Branch on the error CLASS (D-13 / V17-09) BEFORE the
			# REFUSED emit — the disposition depends on whether the failure is a
			# DEFINITIVE venue rejection or an AMBIGUOUS transport outcome.
			#
			# AMBIGUOUS transport error: a ``TimeoutError`` (raised by
			# ``connector.call(...).result(timeout=_CALL_TIMEOUT)`` when the loop
			# future does not resolve in time — this alias also covers
			# ``asyncio.TimeoutError`` / ``concurrent.futures.TimeoutError`` on 3.11+)
			# or a ccxt ``NetworkError`` (``RequestTimeout`` / ``DDoSProtection`` /
			# ``ExchangeNotAvailable`` …). The submit MAY have REACHED the venue and be
			# resting / partially filled — the transport just lost the ack. Emitting
			# ``FillEvent(REFUSED)`` here would drive ReconcileManager -> REJECTED,
			# terminalizing a mirror whose order might be live: a later real fill then
			# arrives against an order the engine believes is dead (position + cash
			# drift, unhedged risk). Leave the mirror IN-FLIGHT / UNKNOWN — it simply
			# stays PENDING (no terminal FillEvent on the queue). Resolution is
			# deferred: the ``clOrdId`` pending correlation registered before the
			# submit still resolves a fill that streams in, and the next
			# ``VenueReconciler`` sweep (or a ``fetch_order(clOrdId)`` probe) settles
			# the true venue state. Scrub (T-05-27): bind the exception TYPE only,
			# never ``str(exc)``.
			import ccxt  # lazy: ccxt already transitively imported on the live path only
			ambiguous_transport: tuple[type[BaseException], ...] = (
				TimeoutError, ccxt.NetworkError)
			if isinstance(exc, ambiguous_transport):
				self.logger.warning(
					"OKX submit for order %s (%s) hit an ambiguous transport error "
					"(%s) — mirror left IN-FLIGHT (stays PENDING) pending "
					"fetch_order / reconcile, NOT terminalized to REJECTED",
					event.order_id, event.ticker, type(exc).__name__)
				return
			# DEFINITIVE venue rejection (e.g. ccxt.InvalidOrder — the order was
			# refused outright and never reached the book): keep the existing
			# reconciliation contract (mirrored by SimulatedExchange's
			# _emit_rejection) — flow it back as FillEvent(REFUSED) so
			# OrderHandler.on_fill / ReconcileManager transitions the stored mirror
			# PENDING->REJECTED. Only logging would leave the mirror stuck at PENDING
			# forever. Emit REFUSED with the order's own (Decimal) price/quantity and
			# commission Decimal("0") (never settled); no time= so it inherits the
			# order's decision time (admission-time outcome, D-01/D-13).
			#
			# WR-01: a DEFINITIVE rejection means the order never rested — release the pending
			# clOrdId correlation registered before the RPC so it does not leak (paired inverse
			# of register_pending). NOT done on the ambiguous-transport branch above, which
			# returns early: that order may still be resting/filling and needs its pending
			# correlation for a streamed fill to resolve via the clOrdId fallback.
			self._index.release_pending(self._client_order_id(event))
			self.global_queue.put(FillEvent.new_fill(
				"REFUSED", event, price=event.price, quantity=event.quantity,
				commission=Decimal("0")))

	def _refuse_preflight(self, event: OrderEvent, reason: str) -> None:
		"""Emit a DEFINITIVE FillEvent(REFUSED) for a preflight-rejected order (D-18).

		A preflight rejection (non-positive quantity, unknown symbol) means the order was
		refused before ever reaching the venue — it can never rest. Mirror the definitive
		venue-rejection emit (``ccxt.InvalidOrder`` branch) so OrderHandler.on_fill /
		ReconcileManager transitions the stored mirror PENDING->REJECTED (only logging would
		leave it stuck at PENDING). No pending clOrdId correlation exists yet (registered
		inside ``_submit_order``, which never ran), so nothing to release. Scrub (T-05-27):
		the log binds the fixed reason, never a connector payload.
		"""
		self.logger.warning(
			"OKX preflight rejected order %s (%s): %s — not submitted",
			event.order_id, event.ticker, reason)
		self.global_queue.put(FillEvent.new_fill(
			"REFUSED", event, price=event.price, quantity=event.quantity,
			commission=Decimal("0")))

	def _submit_order(self, event: OrderEvent) -> None:
		"""Round outbound qty/price to OKX lot/tick (string helpers) and submit via the RPC.

		CONN-05: the outbound quantity/price go through ``amount_to_precision`` /
		``price_to_precision`` (ccxt reads OKX ``load_markets`` precision and returns a
		venue-correct STRING) — never ``Decimal(float)`` and never a hand-rolled quantize.
		"""
		# WR-03: only MARKET and LIMIT are translated today. OrderType also defines
		# STOP and TRAILING_STOP (this framework's brackets are stop/limit children),
		# which carry their trigger in ``event.price`` — but the ccxt trigger-param
		# translation (triggerPrice/stopLossPrice) is not wired until the live order
		# path (Phase 4/5). Rather than silently submit ``type="stop"`` with
		# ``price=None`` (dropping the trigger, so the venue rejects or mis-fills),
		# fail loud here: the on_order boundary converts this into a
		# FillEvent(REFUSED) (WR-02) so the order mirror reconciles instead of the
		# trigger being silently dropped. Full STOP/TRAILING_STOP translation is
		# deferred to the live order path.
		if event.order_type not in (OrderType.MARKET, OrderType.LIMIT):
			raise NotImplementedError(
				f"OKX arm does not yet translate {event.order_type.value} orders "
				"(trigger-price submission lands with the live order path)")

		symbol = self._to_symbol(event.ticker)
		client = self._connector.client
		# Outbound precision: venue-rounded STRINGS (CONN-05 — no Decimal(float)).
		# IN-03: pass the Decimal's STRING form (not float()) so the outbound value
		# never enters binary float; ccxt re-rounds to lot/tick and returns the
		# authoritative string either way.
		amount = client.amount_to_precision(symbol, str(event.quantity))
		otype = event.order_type.value.lower()
		side = event.action.value.lower()
		price: Optional[str] = None
		if event.order_type is OrderType.LIMIT and event.price is not None:
			price = client.price_to_precision(symbol, str(event.price))

		# WR-04: ccxt's okx defaults ``createMarketBuyOrderRequiresPrice = True``,
		# under which a spot market BUY requires a price (to derive cost) or the
		# explicit override with ``amount`` as base quantity — otherwise ccxt raises
		# InvalidOrder. The arm already submits ``amount`` as the BASE quantity
		# (``event.quantity``), so disable that mode for market buys and let the
		# venue treat the amount as base size. Market sells and limit orders are
		# unaffected (empty params).
		params: Dict[str, Any] = {}
		if event.order_type is OrderType.MARKET and event.action is Side.BUY:
			params["createMarketBuyOrderRequiresPrice"] = False

		# Pitfall 11 fast-fill-race fix (D-12): attach a CLIENT order id and
		# register the pending correlation keyed by it BEFORE the create_order RPC.
		# OKX echoes clOrdId back on the fill, so a fill that streams in before the
		# RPC returns the venue id still resolves its OrderEvent in _handle_trade
		# (which consults _orders_by_clOrdId when the venue-id lookup misses).
		client_order_id = self._client_order_id(event)
		params["clOrdId"] = client_order_id
		# WR-05 R1: the index owns the pending-correlation write (guarded internally).
		self._index.register_pending(client_order_id, event)
		# D-12: track the symbol BEFORE the RPC so an ambiguous submit timeout (D-13,
		# mirror left in-flight) still contributes its symbol to the resume catch-up.
		self._active_symbols.add(event.ticker)

		response = self._connector.call(
			client.create_order(symbol, otype, side, amount, price, params=params))

		venue_id = response.get("id") if isinstance(response, dict) else None
		if venue_id is not None:
			# Write the venue-id correlation and pop any fills that streamed back
			# before it landed (fast-fill race, Pitfall 11 — never the old silent
			# drop). register drains under the index lock and RETURNS the buffered
			# trades; re-drain OUTSIDE it (_handle_trade re-acquires the index lock,
			# and the index lock is non-reentrant).
			for buffered_trade in self._index.register(venue_id, event, client_order_id):
				self._handle_trade(buffered_trade)
			# D-06 / V17-02: persist the venue ack. The in-memory index alone is
			# lost across a restart, so emit an ORDER-ACK on the shared queue —
			# OrderHandler.on_order_ack stamps + persists venue_order_id onto the
			# stored mirror. Queue-only: the exchange never writes the order store
			# directly (D-19). V5: bind ONLY order_id/venue_order_id/portfolio_id/
			# time — the raw venue payload never rides onto the event.
			self.global_queue.put(OrderAckEvent.new_order_ack(event, str(venue_id)))

	def _cancel_order(self, event: OrderEvent) -> None:
		"""Cancel the venue order correlated to ``event.order_id`` via the RPC."""
		symbol = self._to_symbol(event.ticker)
		# WR-05 R1: the index resolves the venue id (guarded internally, WR-03).
		venue_id = self._index.venue_id_for(event.order_id)
		if venue_id is None:
			self.logger.warning(
				"Cancel for order %s has no known venue id — skipping", event.order_id)
			return
		self._connector.call(self._connector.client.cancel_order(venue_id, symbol))

	def adopt_venue_correlation(self, order: Any) -> None:
		"""Restart-rehydration correlation seam (WR-02 / RECON-05 / D-12).

		A pre-restart Order never went through ``_submit_order`` — the ONLY writer
		of the three in-memory correlation maps (``_orders_by_venue_id`` /
		``_venue_id_by_order_id`` / ``_orders_by_clOrdId``). Consequence once the
		live fill stream is spawned (CR-01): a post-restart fill for a rehydrated
		resting order resolves to no OrderEvent and is BUFFERED under
		``_pending_fills_by_venue_id`` forever (silently lost), and a cancel of a
		rehydrated order is a silent no-op. ``VenueReconciler.reconcile`` calls this
		during restart rehydration for each working-set order (and each re-linked
		bracket leg) carrying a persisted ``venue_order_id``: it repopulates the maps
		exactly as ``_submit_order`` does, then re-drains any fills that streamed in
		before adoption — so the fill reaches the mirror and the cancel resolves.
		"""
		venue_id = order.venue_order_id
		if venue_id is None:
			# Nothing to correlate — an order the venue never acknowledged.
			return
		event = OrderEvent.new_order_event(order)
		venue_id = str(venue_id)
		# D-12: a rehydrated resting order is active — track its symbol for the resume catch-up.
		self._active_symbols.add(event.ticker)
		# WR-05 R1: the index repopulates all three maps and RETURNS any fills
		# buffered before this correlation landed (mirrors the _submit_order
		# fast-fill-race drain). Re-drain OUTSIDE the index lock — _handle_trade
		# re-acquires it and the index lock is non-reentrant.
		for buffered_trade in self._index.adopt(
			venue_id, event, self._client_order_id(event)):
			self._handle_trade(buffered_trade)

	def on_market_data(self, bar: Any) -> None:
		"""No-op for live: the venue matches resting orders, not us (D-06).

		A bar never produces a fill on the live path — fills stream back from the venue on
		``watch_my_trades``. Implemented to satisfy the ``AbstractExchange`` seam.
		"""
		return None

	# --- streaming (D-07 — the exchange emits FillEvents itself) ---------------

	def _handle_trade(self, trade: Any) -> None:
		"""Translate one venue fill (ccxt-unified trade) into a ``FillEvent`` (D-07, D-12).

		Idempotent + race-safe (RECON-02, Pitfall 11):
		- **fill-ID dedup** — a reconnect re-send carries the same ``trade['id']``
		  and is an idempotent no-op, never double-counted;
		- **fast-fill race** — a fill that arrives before its ``create_order`` RPC
		  returns the venue id is resolved via the ``clOrdId`` pending correlation
		  registered before the submit, or BUFFERED for late correlation (drained by
		  ``_submit_order`` once the venue-id map lands) — never the old silent drop.

		CONN-05: every inbound float crosses the Decimal boundary via ``to_money(str(x))``.
		Business time: ``FillEvent.time`` is stamped from the venue trade timestamp.
		Input validation (T-02-03-VALID): a fill missing price/amount/timestamp is
		skipped-and-logged — never crashed.
		"""
		# WR-05 R1: the index performs the atomic dedup + venue-id/clOrdId resolve +
		# buffer + mark-seen under its own lock (WR-03, Pitfall 11); this arm mints +
		# emits OUTSIDE the lock (the FillEvent mint touches no correlation map).
		result = self._index.resolve(trade)
		if result.outcome == "duplicate":
			# An already-seen venue trade id is a reconnect re-send — idempotent no-op.
			return
		if result.outcome == "buffered":
			# Uncorrelated but keyable: buffered for late correlation. _submit_order /
			# adopt_venue_correlation re-drain once the venue-id map lands (never dropped).
			self.logger.warning(
				"Fill for not-yet-correlated venue order %s — buffered for late correlation",
				result.venue_id)
			return
		if result.outcome == "uncorrelated":
			# No venue id to key a buffer on — skip-and-log.
			self.logger.warning("Fill with no venue order id — skipping")
			return
		# Correlated (outcome == "emit"): mint + emit OUTSIDE the lock.
		assert result.order is not None  # narrowed by outcome == "emit"
		emitted = self._emit_fill(trade, result.order, result.venue_id)
		# WR-02: consume the dedup slot ONLY after a True emit — resolve deliberately did
		# NOT mark the key seen, so a malformed payload (_emit_fill False) leaves the slot
		# free and a corrected re-send of the same {ticker}:{trade_id} still emits. A
		# None-keyed (backtest) trade carries dedup_key=None → clean skip (oracle-dark).
		if emitted and result.dedup_key is not None:
			self._index.mark_seen(result.dedup_key)
		# WR-05 R2 (WR05-D1): feed the per-venue_id cumulative-filled counter and, when
		# this fill terminalizes the order (cumulative reaches order.quantity), self-release
		# its correlation entries so the maps do not grow without limit over a long session
		# (drain-then-evict, WR05-D3). Gate on an actual emit + a keyable venue_id: a
		# malformed/skipped fill must not advance the counter, and a clOrdId-only resolve
		# (no venue id) has no venue-id-keyed entry to release.
		if emitted and result.venue_id is not None:
			amount = trade.get("amount") if isinstance(trade, dict) else None
			if amount is not None and self._index.record_fill(
				result.venue_id, result.order, to_money(str(amount))):
				self.release_venue_correlation(result.venue_id)

	def _emit_fill(self, trade: Any, order: OrderEvent, venue_id: Any) -> bool:
		"""Mint the FillEvent for a correlated venue trade and put it on ``global_queue``.

		Returns True when a FillEvent was emitted, False when the payload was malformed and
		skipped (so the caller does NOT advance the WR-05 cumulative-filled counter for a
		fill that never settled). Preserves the CONN-05 Decimal edge (``to_money(str(x))``),
		the WR-01 commission None-guard + ``abs()`` magnitude normalisation, and the
		``_ms_to_dt`` business-time stamp verbatim.
		"""
		price = trade.get("price")
		amount = trade.get("amount")
		timestamp = trade.get("timestamp")
		if price is None or amount is None or timestamp is None:
			self.logger.warning(
				"Malformed fill payload for order %s (missing price/amount/timestamp) — skipping",
				venue_id)
			return False
		# D-12: advance the catch-up floor (venue business ms) so a later stream drop
		# re-fetches only from the last fill actually processed, not from epoch.
		self._last_venue_ts_ms = int(timestamp)
		# WR-01: ccxt frequently emits ``fee: {"cost": None, ...}`` (fee not yet
		# known). ``fee.get("cost", 0)`` returns None because the key IS present, and
		# ``to_money(str(None))`` -> ``Decimal("None")`` raises InvalidOperation,
		# killing the whole fill stream. Guard the None/missing case BEFORE the
		# Decimal edge (money policy: never Decimal-parse a non-numeric).
		# WR-01 (sign): commission is a MAGNITUDE — the portfolio transaction
		# validator hard-rejects commission < 0 (portfolio_handler/validators.py).
		# ccxt's unified ``okx.parse_trade`` sign-flips the raw OKX fee so
		# ``fee.cost`` is normally positive, but a raw/non-unified payload, a
		# different channel, or a ccxt convention change can yield a negative cost
		# that would crash the fill at the portfolio boundary and drop it. ``abs()``
		# normalises to the non-negative magnitude the validator contract requires.
		fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
		fee_cost = fee.get("cost")
		commission = abs(to_money(str(fee_cost))) if fee_cost is not None else Decimal("0")
		# spot-base-fee-drift-halt: carry the fee CURRENCY too. OKX charges the
		# spot BUY taker fee in the pair's BASE asset (BTC), so the venue credits
		# ``amount - base_fee`` BTC — dropping the currency (as this path used to)
		# made the engine record the full ``amount`` and overstate the position by
		# the fee, tripping the on-fill drift halt. The portfolio settlement branch
		# reads this to net a base-denominated fee out of the position quantity.
		fee_currency = fee.get("currency")
		fee_currency = str(fee_currency) if fee_currency is not None else None

		# CR-01: carry the venue trade id onto the FillEvent as the cross-emitter
		# idempotency key. The exchange-local ``_seen_trade_ids`` dedups a stream
		# re-send BEFORE mint; stamping ``trade['id']`` here lets the portfolio
		# settlement chokepoint ALSO dedup the same economic trade adopted by the
		# restart VenueReconciler (which bypasses ``_seen_trade_ids``).
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
		# D-07: the EXCHANGE emits the fill; MPSC-safe put from the connector loop thread (D-19).
		self.global_queue.put(fill)
		return True

	def release_venue_correlation(self, venue_id: str) -> None:
		"""Release a terminalized order's venue correlation (WR-05 R2 — the OUTBOUND twin
		of ``adopt_venue_correlation``).

		WR-03: drain any buffered late fills through the FULL ``_handle_trade`` → ``resolve``
		path (dedup + correlation) BEFORE the index drops the correlation — NOT raw
		``_emit_fill``. Raw ``_emit_fill`` bypasses the dedup ring, so a re-delivered buffered
		fill would double-count; routing through ``resolve`` records the drained trade id in the
		ring (a later re-delivery dedups). ``take_pending`` empties the buffer while the
		correlation is still present so each drained fill re-resolves to its order; ``release``
		then evicts the (now-drained) correlation entries. Idempotent: an unknown /
		already-released ``venue_id`` drains nothing and drops nothing.
		"""
		for buffered_trade in self._index.take_pending(venue_id):
			self._handle_trade(buffered_trade)
		self._index.release(venue_id)

	def catch_up_missed_fills(self) -> None:
		"""Recover fills that settled while the fill stream was down (D-12 / V17-08).

		Called on the ENGINE / resume path — NOT the connector loop thread. It bridges
		the async ``fetch_my_trades`` through the blocking ``connector.call``, which does
		``run_coroutine_threadsafe(...).result()``; calling that FROM the loop thread
		would deadlock. The composition-root resume wiring (the injected ``on_stream_up``
		flips a thread-safe flag; the engine thread then runs the fresh REST reconcile)
		drives this alongside that reconcile, on resume and on the attempt==1 reconnect.

		For each active-order symbol it fetches the venue's trades since the disconnect
		floor (``_disconnect_ts_ms`` — a venue-ms business timestamp captured at the
		stream-down transition) and routes each through the EXISTING ``_handle_trade``,
		so a fill missed during the downtime settles the mirror. Safe to re-run, and safe
		against the live stream ALSO redelivering the same trade: D-08
		``{symbol}:{trade_id}`` dedup makes a re-fetched trade an idempotent no-op, so the
		missed fill settles EXACTLY once. Bounded (Pitfall-safe): a SINGLE page with an
		explicit ``limit`` — NO ccxt auto-pagination — honoring the venue's ~3-month /
		100-per-page window. A fetch or translation failure is swallow-and-logged (the
		next reconcile sweep is the backstop); the resume path never crashes on catch-up.
		Steady-state mid-session re-fetch is OUT of scope here (Phase-7 spec).
		"""
		since = self._disconnect_ts_ms
		symbols = sorted(self._active_symbols)
		if not symbols:
			return
		client = self._connector.client
		for symbol in symbols:
			try:
				trades = self._connector.call(client.fetch_my_trades(
					self._to_symbol(symbol), since=since, limit=_CATCHUP_TRADE_LIMIT))
			except Exception:
				# Scrub (T-05-27): the connector error may carry request context — log
				# via exc_info (the sink scrubs), never str(exc) into the message.
				self.logger.error(
					"OKX missed-fill catch-up fetch failed for %s — deferred to reconcile",
					symbol, exc_info=True)
				continue
			for trade in trades or []:
				# A single malformed trade must not abort the remaining catch-up.
				try:
					self._handle_trade(trade)
				except Exception:
					self.logger.error(
						"OKX missed-fill catch-up translation failed — skipping trade",
						exc_info=True)
		# Floor consumed — a subsequent disconnect re-arms it (idempotent re-run otherwise).
		self._disconnect_ts_ms = None

	# --- reconnect supervisor (RES-01/D-19/D-20) -------------------------------

	def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
		"""Inject the connector-fatal halt signal (D-20; flag handoff D-21/WR-02).

		Called with reason ``'connector-fatal'`` when a stream hits a fatal connector
		error (auth/permission) OR exhausts the reconnect retry ceiling. This runs on the
		connector ASYNCIO LOOP thread, so the injected signal MUST be non-blocking: the
		composition root wires ``_request_connector_halt`` (a thread-safe flag setter), NOT
		``halt()`` directly — ``halt()``'s blocking durable ``record_halt`` SQL write would
		stall every stream sharing the loop (WR-02 / Pitfall 9). The engine thread drains
		the flag and runs the blocking halt (CRITICAL alert + durable write) off the loop.
		The arm passes NO exception text, only the fixed reason, so no secret leaks
		(Pitfall 16, T-05-27).
		"""
		self._halt_signal = halt_signal

	def set_stream_state_listener(
		self,
		on_down: Callable[[str], None],
		on_up: Callable[[str], None],
	) -> None:
		"""Inject the pause/resume-on-disconnect callbacks (D-19).

		``on_down`` fires when a stream stays disconnected past the debounce window
		(pause NEW order submission); ``on_up`` fires when it reconnects (the callback
		owns the resume-only-after-fresh-REST-reconcile discipline). Both fire from the
		connector loop thread, so they must not perform blocking venue I/O (Pitfall 9) —
		the composition-root wiring flips a thread-safe flag only.
		"""
		self._on_stream_down = on_down
		self._on_stream_up = on_up

	def is_streaming_healthy(self) -> bool:
		"""True iff this arm's stream set (fills+orders) is fully up (D-28 / WR-03).

		Delegates to the shared ``StreamSupervisor`` (05-01/D-08), which owns
		``_streams_down``. Read by the engine's compound resume gate
		(``_all_venue_streams_healthy``) on the ENGINE thread while the connector loop
		mutates the supervisor's down-set (GIL-atomic emptiness read, no lock; any
		staleness self-heals via the re-fired resume Event).
		"""
		return self._supervisor.is_healthy()

	def _on_stream_down_with_floor(self, stream_name: str) -> None:
		"""Supervisor ``on_down``: snapshot the D-12 catch-up floor, then pause (D-12/D-19).

		The D-12 missed-fill catch-up floor (``_disconnect_ts_ms``) stays ARM state, NOT
		supervisor state — only the OKX order arm has it. This wrapper is passed as the
		shared supervisor's ``on_down`` callback; the supervisor's ``mark_down`` dedups
		(fires on_down exactly once per down transition), so the floor is snapshotted once
		per drop from the last processed venue ms (never wall-clock) so the resume
		``catch_up_missed_fills`` re-fetches trades that settled during the gap. It then
		forwards to the injected external pause listener (``_on_stream_down``) so NEW
		submission quiesces (D-19). Runs on the connector loop thread — flag-only, no
		blocking venue I/O (Pitfall 9). Only the first drop sets the floor; it clears once
		the catch-up consumes it.
		"""
		if self._disconnect_ts_ms is None:
			self._disconnect_ts_ms = self._last_venue_ts_ms
		if self._on_stream_down is not None:
			self._on_stream_down(stream_name)

	async def _stream_fills(self) -> None:
		"""Consume the venue fill stream under the reconnect supervisor (D-07/D-19/D-20)."""
		await self._supervisor.run(self._consume_fills, "fills")

	async def _consume_fills(self, stream_name: str) -> None:
		"""Forever-loop: emit a FillEvent per venue trade (D-07); reconnect-supervised."""
		while True:
			trades = await self._connector.client.watch_my_trades()
			# Subscribe/ack: resume submission if we were paused (D-19).
			self._supervisor.mark_up(stream_name)
			# WR-03: only a delivered payload (>=1 trade) resets the retry budget — a
			# subscribe-then-close storm must never keep the ceiling from tripping.
			if trades:
				self._supervisor.reset_budget(stream_name)
			for trade in trades:
				# WR-02: a single malformed trade must not kill the forever-loop and
				# silently drop every subsequent fill. Swallow-and-log per trade,
				# matching the on_order boundary policy — the stream keeps draining.
				try:
					self._handle_trade(trade)
				except Exception:
					self.logger.error(
						"OKX fill translation failed — skipping trade", exc_info=True)

	async def _stream_orders(self) -> None:
		"""Consume the order-status stream under the reconnect supervisor (status only).

		The fill money crosses on ``watch_my_trades`` (``_stream_fills``); this loop tracks
		order lifecycle transitions for logging/reconciliation and never mints money.
		"""
		await self._supervisor.run(self._consume_orders, "orders")

	async def _consume_orders(self, stream_name: str) -> None:
		"""Forever-loop: reconcile venue order-status updates; reconnect-supervised (D-12).

		A venue-side CANCELLED/EXPIRED row is translated into a FillEvent so the mirror
		reconciles (``_handle_order_update``); every other status stays log-only. Per-row
		swallow-and-log (matching ``_consume_fills``) so one malformed row never kills the
		forever-loop and silently drops every subsequent order update.
		"""
		while True:
			orders = await self._connector.client.watch_orders()
			self._supervisor.mark_up(stream_name)
			# WR-03: payload-gated retry-budget reset (>=1 order update).
			if orders:
				self._supervisor.reset_budget(stream_name)
			for order in orders:
				try:
					self._handle_order_update(order)
				except Exception:
					self.logger.error(
						"OKX order-update translation failed — skipping", exc_info=True)

	def _handle_order_update(self, order: Any) -> None:
		"""Translate one venue order-status row into a mirror-reconciling event (D-12 / V17-08).

		A venue-side CANCELLED/EXPIRED (a cancel/expiry the engine did NOT command — an OKX
		MMP cancel, a post-only reject, a GTD expiry) must reconcile the order mirror, else
		the order sits PENDING forever. Translate it into a ``FillEvent(CANCELLED/EXPIRED)``
		on ``global_queue`` (the ``:250`` REFUSED emit's donor shape) so ``OrderHandler.on_fill``
		drives the mirror terminal. Every other status stays log-only: ``closed`` (FILLED) is
		the money path that already crosses on ``watch_my_trades``, so translating it here would
		double-settle. Business time from the venue ms (never wall-clock); the OrderEvent is
		resolved from the venue order id via the correlation index — an uncorrelated row is
		deferred to the reconcile sweep.
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
		# Donor shape (:250): the order's own (Decimal) price/quantity + commission
		# Decimal("0") (a cancel/expiry never settles money); time from the venue ms.
		self.global_queue.put(FillEvent.new_fill(
			fill_status, event, price=event.price, quantity=event.quantity,
			commission=Decimal("0"), time=fill_time))

	# --- connection lifecycle -------------------------------------------------

	def connect(self) -> ConnectionResult:
		"""Spawn the venue streams and mark connected (the connector owns the loop lifecycle).

		The injected connector already owns the asyncio loop on its daemon thread; ``connect``
		here launches the two long-running ``watch_*`` consume-loops via ``connector.spawn``
		(never ``.result()``-awaited — they loop forever) and records the handles so the
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
		"""No arm-local config today — venue credentials/routing live on the connector (D-04)."""
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
		"""Consult the connector client's loaded markets; FAIL-CLOSED on a cold cache (CF-9/D-11).

		``load_markets`` runs in the connector, so a loaded ``markets`` map is the source of
		truth. CF-9 (D-11, threat T-05-04): when ``markets`` is NOT yet a loaded dict we
		CANNOT verify the symbol, so we return **False** (fail-closed) — a delisted/invalid
		symbol must NEVER pass validation on a cold markets cache (the old fail-OPEN return
		of ``True`` let an unvalidated symbol slip through the pre-load window). This does
		NOT dark the initial universe: initial membership comes from ``derive_membership``
		(never ``validate_symbol``), and ``_initialize_live_session`` precedes
		``connect()``/``load_markets``, so the universe poll — the sole ``validate_symbol``
		caller — runs post-connect with ``markets`` loaded. This reuses the SINGLE existing
		``validate_symbol → delta.removed → unsubscribe/force-close`` removal path (D-11); no
		second/parallel drop mechanism is added.

		IN-01: normalise through the SAME ``_to_symbol`` helper the submit path uses before
		the membership check, so a caller-form vs markets-key mismatch cannot inconsistently
		accept/reject a symbol. ``_to_symbol`` is pass-through today (callers pass the
		ccxt-unified ``BTC/USDT`` form that keys the loaded ``markets`` map); routing the
		check through it keeps validate and submit on one normalisation as that helper grows.
		"""
		markets = getattr(self._connector.client, "markets", None)
		if isinstance(markets, dict):
			return self._to_symbol(symbol) in markets
		# CF-9 fail-closed: markets not yet loaded -> cannot verify -> reject.
		return False

	def resolve_precision(self, symbol: str) -> "Instrument | None":
		"""Resolve a poll-added symbol's venue precision from the loaded-markets map (VENUE-04/D-09).

		Reads ``self._connector.client.markets[key]['precision']`` — the SAME ccxt
		loaded-markets precision the submit path consumes via ``price_to_precision`` /
		``amount_to_precision`` — and converts the venue tick sizes into an ``Instrument``
		carrying Decimal price/quantity scales via ``core/money.precision_to_scale`` (D-04
		string path, NEVER ``Decimal(float)``). Returns ``None`` when markets aren't loaded /
		the symbol is absent / a precision entry is unusable, so ``UniverseHandler.on_poll``
		falls to ``Universe.apply``'s ``_DEFAULT_*`` ladder — the same paper posture as
		``validate_symbol`` on a cold cache (threat T-05-06: a cold markets map cannot crash
		the poll). ``Universe`` stays connector-free (D-09): every connector read happens HERE.
		"""
		connector = getattr(self, "_connector", None)
		client = getattr(connector, "client", None)
		markets = getattr(client, "markets", None)
		if not isinstance(markets, dict):
			return None
		# Normalise through the SAME _to_symbol helper validate_symbol uses so a
		# caller-form vs markets-key mismatch resolves consistently.
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
		# Inert margin defaults (mirror instruments.derive_instruments — unused on the
		# spot path this phase; present so every constructed Instrument is well-formed).
		return Instrument(
			symbol=symbol.upper(),
			price_precision=price_scale,
			quantity_precision=quantity_scale,
			maintenance_margin_rate=Decimal("0.005"),
			max_leverage=Decimal("1"),
		)
