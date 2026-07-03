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

import asyncio
import threading
from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Awaitable, Callable, Dict, List, Optional

from itrader.connectors.base import LiveConnector
from itrader.core.enums import ErrorSeverity, OrderCommand, OrderType, Side
from itrader.core.enums.execution import ExchangeConnectionStatus, ExecutionErrorCode
from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.events_handler.events import ErrorEvent, FillEvent, OrderEvent
from itrader.logger import get_itrader_logger

from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult
from .base import AbstractExchange


# 05-08 (RES-01/D-19/D-20) reconnect-supervisor tuning — named module constants,
# documented [ASSUMED] and tunable from sandbox behaviour (research A3; anchored to
# nautilus defaults: open_check_missing_retries=5 / position_check_retries=3). A
# transient socket drop reconnects with exponential backoff (staying running,
# publish-and-continue); the debounce keeps a sub-second blip from escalating to a
# pause (D-19); the retry ceiling bounds the retry loop so it never spins forever ->
# HALT on exhaustion (D-20).
_STREAM_RECONNECT_DEBOUNCE_SECONDS = 0.25    # A3 [ASSUMED] sub-second blip -> no pause
_STREAM_RECONNECT_BACKOFF_BASE_SECONDS = 1.0  # A3 [ASSUMED] first backoff step
_STREAM_RECONNECT_BACKOFF_CAP_SECONDS = 30.0  # A3 [ASSUMED] exponential backoff ceiling
_STREAM_RECONNECT_RETRY_CEILING = 6           # A3 [ASSUMED] retries exhausted -> HALT (D-20)

# WR-04: OKX clOrdId charset. The client order id is the fast-fill-race
# correlation key (``_orders_by_clOrdId``) and MUST be unique per order.
# Base62 of the order id's 128 bits is LOSSLESS (a bijection on the 16 raw
# UUID bytes) and renders to <=22 chars, so ``"it"`` + token stays under
# OKX's 32-char alphanumeric clOrdId limit with the full 128-bit entropy
# preserved. The old ``("it" + hex_token)[:32]`` dropped the UUID tail bits,
# so two orders differing only there collided on one clOrdId (wrong-order
# fill correlation).
_CLORDID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


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

		# Venue-id correlation: a streamed fill (watch_my_trades) carries the venue order id;
		# resolve it back to the originating OrderEvent so FillEvent.new_fill carries the
		# order_id/strategy_id/portfolio_id audit chain (D-12).
		# WR-03: the correlation maps are written on the ENGINE thread (submit /
		# cancel, via connector.call) and read on the CONNECTOR LOOP thread (streamed
		# fills, via _handle_trade). Guard every write/read with this lock so the
		# cross-thread dict access is synchronised. The fast-fill race (a fill pushed
		# before create_order returns the venue id) is now closed by the clOrdId
		# pre-correlation + unmatched-fill buffer below (D-12, Pitfall 11) — a lock
		# alone did not suffice.
		self._correlation_lock = threading.Lock()
		self._orders_by_venue_id: Dict[str, OrderEvent] = {}
		self._venue_id_by_order_id: Dict[OrderId, str] = {}

		# D-12 / Pitfall 11 (RECON-02): fill-ID dedup + fast-fill-race close-out.
		# Three maps, all guarded by _correlation_lock (cross-thread: engine-thread
		# submit vs connector-loop-thread fills):
		# - _seen_trade_ids dedupes a reconnect re-send — the same venue
		#   ``trade['id']`` seen twice is an idempotent no-op, never double-counted;
		# - _orders_by_clOrdId is the pending correlation keyed by the CLIENT order
		#   id, registered BEFORE the create_order RPC (and echoed back on the fill),
		#   so a fill that streams back before the RPC returns the venue id still
		#   resolves its originating OrderEvent;
		# - _pending_fills_by_venue_id BUFFERS a fill that arrived before its
		#   venue-id correlation landed — _submit_order re-drains it once the
		#   venue-id map is written, closing the fast-fill race instead of the old
		#   silent drop (D-13 — never lose a real fill).
		self._seen_trade_ids: set[str] = set()
		self._orders_by_clOrdId: Dict[str, OrderEvent] = {}
		self._pending_fills_by_venue_id: Dict[str, List[Any]] = {}

		# Spawned stream-task handles (cancelled by the connector on disconnect).
		self._stream_handles: List[Any] = []

		# 05-08 (RES-01/D-19/D-20): reconnect-supervisor state. Each stream
		# consume-loop runs under a bounded-retry supervisor — a transient socket
		# drop reconnects with exponential backoff instead of the task dying
		# silently, a fatal error or an exhausted retry ceiling halts the engine
		# (D-20), and a sustained disconnect pauses new order submission until the
		# stream reconnects + a fresh REST reconcile completes (D-19).
		self._reconnect_attempts: Dict[str, int] = {}
		self._streams_down: set[str] = set()
		# Per-instance tuning seeded from the module defaults so a test (or a
		# sandbox tune) can shrink the debounce/backoff without monkeypatching the
		# module — the module constants stay the documented [ASSUMED] anchor.
		self._reconnect_debounce_s = _STREAM_RECONNECT_DEBOUNCE_SECONDS
		self._reconnect_backoff_base_s = _STREAM_RECONNECT_BACKOFF_BASE_SECONDS
		self._reconnect_backoff_cap_s = _STREAM_RECONNECT_BACKOFF_CAP_SECONDS
		self._reconnect_ceiling = _STREAM_RECONNECT_RETRY_CEILING
		# Injected seams (composition root, 05-08 Task 2): the 05-04 freeze-in-place
		# halt entrypoint (fatal / exhausted -> HALTED + CRITICAL alert) and the
		# pause/resume-on-disconnect callbacks (D-19). All None on the paper/backtest
		# path (streams never start there).
		self._halt_signal: Optional[Callable[[str], None]] = None
		self._on_stream_down: Optional[Callable[[str], None]] = None
		self._on_stream_up: Optional[Callable[[str], None]] = None

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
			# SUBMIT failure: keep the existing reconciliation contract (mirrored
			# by SimulatedExchange's _emit_rejection) — a submit that never reached
			# the venue flows back as FillEvent(REFUSED) so OrderHandler.on_fill /
			# ReconcileManager transitions the stored mirror PENDING->REJECTED.
			# Only logging would leave the mirror stuck at PENDING forever. Emit
			# REFUSED with the order's own (Decimal) price/quantity and commission
			# Decimal("0") (never settled); no time= so it inherits the order's
			# decision time (admission-time outcome, D-01/D-13).
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
		with self._correlation_lock:  # WR-03: cross-thread write guard
			self._orders_by_clOrdId[client_order_id] = event

		response = self._connector.call(
			client.create_order(symbol, otype, side, amount, price, params=params))

		venue_id = response.get("id") if isinstance(response, dict) else None
		buffered: List[Any] = []
		if venue_id is not None:
			with self._correlation_lock:  # WR-03: cross-thread write guard
				self._orders_by_venue_id[venue_id] = event
				self._venue_id_by_order_id[event.order_id] = venue_id
				# Fast-fill race: drain any fills that streamed back before this
				# venue-id correlation existed (buffered by _handle_trade, never
				# dropped — Pitfall 11). Pop under the lock; re-drain outside it.
				buffered = self._pending_fills_by_venue_id.pop(venue_id, [])
		# Re-drain OUTSIDE the lock — _handle_trade re-acquires _correlation_lock
		# and threading.Lock is non-reentrant.
		for buffered_trade in buffered:
			self._handle_trade(buffered_trade)

	def _cancel_order(self, event: OrderEvent) -> None:
		"""Cancel the venue order correlated to ``event.order_id`` via the RPC."""
		symbol = self._to_symbol(event.ticker)
		with self._correlation_lock:  # WR-03: cross-thread read guard
			venue_id = self._venue_id_by_order_id.get(event.order_id)
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
		buffered: List[Any] = []
		with self._correlation_lock:  # WR-03: cross-thread write guard
			self._orders_by_venue_id[venue_id] = event
			self._venue_id_by_order_id[event.order_id] = venue_id
			self._orders_by_clOrdId[self._client_order_id(event)] = event
			# Drain any fills buffered before this correlation landed (mirrors the
			# _submit_order fast-fill-race drain). Pop under the lock; re-drain
			# outside it.
			buffered = self._pending_fills_by_venue_id.pop(venue_id, [])
		# Re-drain OUTSIDE the lock — _handle_trade re-acquires _correlation_lock
		# and threading.Lock is non-reentrant.
		for buffered_trade in buffered:
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
		trade_id = trade.get("id") if isinstance(trade, dict) else None
		venue_id = trade.get("order") if isinstance(trade, dict) else None
		with self._correlation_lock:  # WR-03: cross-thread map guard
			# Dedup (Pitfall 11): an already-seen venue trade id is a re-send.
			if trade_id is not None and trade_id in self._seen_trade_ids:
				return
			order = (self._orders_by_venue_id.get(venue_id)
			         if venue_id is not None else None)
			if order is None:
				# Fast-fill race: fall back to the clOrdId pending correlation
				# registered BEFORE the submit RPC (the venue echoes clOrdId).
				clordid = self._extract_client_order_id(trade)
				if clordid is not None:
					order = self._orders_by_clOrdId.get(clordid)
			if order is None:
				# Still uncorrelated: BUFFER for late correlation rather than drop
				# (Pitfall 11). _submit_order re-drains once the venue-id map lands.
				# Only buffer when there is a venue id to key the drain on.
				if venue_id is not None:
					self._pending_fills_by_venue_id.setdefault(venue_id, []).append(trade)
					self.logger.warning(
						"Fill for not-yet-correlated venue order %s — buffered for late correlation",
						venue_id)
				else:
					self.logger.warning("Fill with no venue order id — skipping")
				return
			# Correlated: mark the trade id seen INSIDE the lock so a concurrent
			# re-send dedupes against it.
			if trade_id is not None:
				self._seen_trade_ids.add(trade_id)
		# Mint + emit OUTSIDE the lock (the FillEvent mint touches no correlation map).
		self._emit_fill(trade, order, venue_id)

	@staticmethod
	def _extract_client_order_id(trade: Any) -> Optional[str]:
		"""Pull the echoed client order id (clOrdId) off a ccxt-unified trade.

		ccxt surfaces it as ``clientOrderId`` at the top level, or the raw OKX
		``clOrdId``/``clientOrderId`` under ``info``. Returns None when neither is
		present so the caller falls through to the buffer path.
		"""
		if not isinstance(trade, dict):
			return None
		cid = trade.get("clientOrderId")
		if cid is None:
			info = trade.get("info")
			if isinstance(info, dict):
				cid = info.get("clOrdId") or info.get("clientOrderId")
		return str(cid) if cid else None

	def _emit_fill(self, trade: Any, order: OrderEvent, venue_id: Any) -> None:
		"""Mint the FillEvent for a correlated venue trade and put it on ``global_queue``.

		Preserves the CONN-05 Decimal edge (``to_money(str(x))``), the WR-01
		commission None-guard + ``abs()`` magnitude normalisation, and the
		``_ms_to_dt`` business-time stamp verbatim.
		"""
		price = trade.get("price")
		amount = trade.get("amount")
		timestamp = trade.get("timestamp")
		if price is None or amount is None or timestamp is None:
			self.logger.warning(
				"Malformed fill payload for order %s (missing price/amount/timestamp) — skipping",
				venue_id)
			return
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
			venue_trade_id=venue_trade_id)
		# D-07: the EXCHANGE emits the fill; MPSC-safe put from the connector loop thread (D-19).
		self.global_queue.put(fill)

	# --- reconnect supervisor (RES-01/D-19/D-20) -------------------------------

	def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
		"""Inject the 05-04 freeze-in-place halt entrypoint (D-20).

		Called with reason ``'connector-fatal'`` when a stream hits a fatal connector
		error (auth/permission) OR exhausts the reconnect retry ceiling. The halt
		entrypoint owns the CRITICAL alert emission and binds only declared ErrorEvent
		fields; the arm passes NO exception text so no secret leaks (Pitfall 16, T-05-27).
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

	async def _run_stream_supervisor(
		self, consume: Callable[[str], Awaitable[None]], stream_name: str
	) -> None:
		"""Bounded-retry reconnect supervisor wrapping a stream consume-loop (D-19/D-20).

		Runs ``consume`` (a forever ``while True: await watch_*()`` loop that only
		returns by raising) under a bounded-retry wrapper:

		- **transient** (``ccxt.NetworkError``/``RequestTimeout``/``DDoSProtection``) ->
		  reconnect with exponential backoff (cap) after a short debounce, staying
		  running (publish-and-continue). A sustained drop (past the debounce) pauses new
		  submission (D-19); a sub-second blip that clears on the first retry does not.
		- **fatal** (``ccxt.AuthenticationError``/``PermissionDenied``) OR the retry
		  ceiling exhausted -> escalate to the injected halt entrypoint (HALTED +
		  CRITICAL alert, reason ``'connector-fatal'``), never spin forever (D-20).

		``asyncio.CancelledError`` is re-raised untouched so the connector's disconnect
		can cancel the task cleanly (Pitfall 4 — no swallowed cancellation).
		"""
		import ccxt  # lazy: ccxt already transitively imported on the live path only
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
				self._escalate_connector_halt(stream_name, exc, "fatal auth/permission error")
				return
			except transient as exc:
				attempt = self._reconnect_attempts.get(stream_name, 0) + 1
				self._reconnect_attempts[stream_name] = attempt
				if attempt > self._reconnect_ceiling:
					self._escalate_connector_halt(
						stream_name, exc, "reconnect retry ceiling exhausted")
					return
				# Debounce first: a blip that clears on the first retry never pauses.
				await asyncio.sleep(self._reconnect_debounce_s)
				if attempt > 1:
					# Still failing past the debounce window -> pause (D-19).
					self._mark_stream_down(stream_name)
				backoff = min(
					self._reconnect_backoff_base_s * (2 ** (attempt - 1)),
					self._reconnect_backoff_cap_s)
				# Scrub (T-05-27): log the exception TYPE only, never str(exc) — a
				# connector error may carry request context / a secret.
				self.logger.warning(
					"OKX %s stream dropped (%s) — reconnecting "
					"(attempt %d/%d, backoff %.1fs)",
					stream_name, type(exc).__name__, attempt,
					self._reconnect_ceiling, backoff)
				await asyncio.sleep(backoff)

	def _escalate_connector_halt(self, stream_name: str, exc: BaseException, cause: str) -> None:
		"""Halt the engine on an unrecoverable connector failure (D-20).

		Scrub (T-05-27): the log carries the exception TYPE + a fixed cause string, never
		``str(exc)``; the halt entrypoint is called with the fixed reason
		``'connector-fatal'`` (no exception text), so no secret can reach the CRITICAL alert.
		"""
		self.logger.error(
			"OKX %s stream unrecoverable (%s: %s) — halting engine",
			stream_name, type(exc).__name__, cause)
		if self._halt_signal is not None:
			self._halt_signal("connector-fatal")

	def _mark_stream_down(self, stream_name: str) -> None:
		"""Record a sustained disconnect and pause new submission once (D-19)."""
		if stream_name in self._streams_down:
			return
		self._streams_down.add(stream_name)
		self.logger.warning(
			"OKX %s stream disconnected — pausing new order submission", stream_name)
		if self._on_stream_down is not None:
			self._on_stream_down(stream_name)

	def _on_stream_healthy(self, stream_name: str) -> None:
		"""A successful ``watch_*`` batch: reset backoff and resume if we were paused (D-19).

		Called by a consume-loop after each successful venue read. Resets the attempt
		counter; on the transition out of a paused state it fires ``on_stream_up`` so the
		composition root can resume submission only after a fresh REST reconcile.
		"""
		self._reconnect_attempts[stream_name] = 0
		if stream_name in self._streams_down:
			self._streams_down.discard(stream_name)
			self.logger.info(
				"OKX %s stream reconnected — resuming after REST reconcile", stream_name)
			if self._on_stream_up is not None:
				self._on_stream_up(stream_name)

	async def _stream_fills(self) -> None:
		"""Consume the venue fill stream under the reconnect supervisor (D-07/D-19/D-20)."""
		await self._run_stream_supervisor(self._consume_fills, "fills")

	async def _consume_fills(self, stream_name: str) -> None:
		"""Forever-loop: emit a FillEvent per venue trade (D-07); reconnect-supervised."""
		while True:
			trades = await self._connector.client.watch_my_trades()
			# First success (incl. after a drop) resets backoff + resumes submission (D-19).
			self._on_stream_healthy(stream_name)
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
		await self._run_stream_supervisor(self._consume_orders, "orders")

	async def _consume_orders(self, stream_name: str) -> None:
		"""Forever-loop: log venue order-status updates; reconnect-supervised."""
		while True:
			orders = await self._connector.client.watch_orders()
			self._on_stream_healthy(stream_name)
			for order in orders:
				self.logger.debug("OKX order update: %s", order)

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
		"""Consult the connector client's loaded markets when available; else accept.

		``load_markets`` runs in the connector, so a loaded ``markets`` map is the source of
		truth. When markets are not (yet) a dict we cannot check — accept and let the venue
		reject a bad symbol at submit time.

		IN-01: normalise through the SAME ``_to_symbol`` helper the submit path uses before
		the membership check, so a caller-form vs markets-key mismatch cannot inconsistently
		accept/reject a symbol. ``_to_symbol`` is pass-through today (callers pass the
		ccxt-unified ``BTC/USDT`` form that keys the loaded ``markets`` map); routing the
		check through it keeps validate and submit on one normalisation as that helper grows.
		"""
		markets = getattr(self._connector.client, "markets", None)
		if isinstance(markets, dict):
			return self._to_symbol(symbol) in markets
		return True
