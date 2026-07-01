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
it never imports the connector concretion. ``LiveConnector`` is imported from the top-level
``itrader.connectors`` barrel, exactly the way ``AbstractExchange`` is imported here.

Indentation: this tree is TAB-indented (a mixed-indent diff breaks the file).
"""

import threading
from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Dict, List, Optional

from itrader.connectors import LiveConnector
from itrader.core.enums import OrderCommand, OrderType
from itrader.core.enums.execution import ExchangeConnectionStatus, ExecutionErrorCode
from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.logger import get_itrader_logger

from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult
from .base import AbstractExchange


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
		# WR-03: the two correlation maps are written on the ENGINE thread (submit /
		# cancel, via connector.call) and read on the CONNECTOR LOOP thread (streamed
		# fills, via _handle_trade). Guard every write/read with this lock so the
		# cross-thread dict access is synchronised. NOTE (latent, streams not started
		# this phase): a lock alone does not close the fast-fill race — the venue can
		# push a fill before create_order returns the venue id, so the fill still
		# resolves to order=None and is dropped. The full fix (register a pending
		# correlation keyed by clOrdId BEFORE the submit RPC, and/or briefly buffer
		# unmatched fills for late correlation) lands with OkxExchange.connect() stream
		# wiring; this guard is the documented minimum until then.
		self._correlation_lock = threading.Lock()
		self._orders_by_venue_id: Dict[str, OrderEvent] = {}
		self._venue_id_by_order_id: Dict[OrderId, str] = {}

		# Spawned stream-task handles (cancelled by the connector on disconnect).
		self._stream_handles: List[Any] = []

	# --- symbol / time helpers ------------------------------------------------

	def _to_symbol(self, ticker: str) -> str:
		"""Venue symbol for a ticker. Pass-through today (the OrderEvent carries the venue
		symbol); a dedicated translation table lands with the data arm if needed."""
		return ticker

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

	def _submit_order(self, event: OrderEvent) -> None:
		"""Round outbound qty/price to OKX lot/tick (string helpers) and submit via the RPC.

		CONN-05: the outbound quantity/price go through ``amount_to_precision`` /
		``price_to_precision`` (ccxt reads OKX ``load_markets`` precision and returns a
		venue-correct STRING) — never ``Decimal(float)`` and never a hand-rolled quantize.
		"""
		symbol = self._to_symbol(event.ticker)
		client = self._connector.client
		# Outbound precision: venue-rounded STRINGS (CONN-05 — no Decimal(float)).
		amount = client.amount_to_precision(symbol, float(event.quantity))
		otype = event.order_type.value.lower()
		side = event.action.value.lower()
		price: Optional[str] = None
		if event.order_type is OrderType.LIMIT and event.price is not None:
			price = client.price_to_precision(symbol, float(event.price))

		response = self._connector.call(
			client.create_order(symbol, otype, side, amount, price))

		venue_id = response.get("id") if isinstance(response, dict) else None
		if venue_id is not None:
			with self._correlation_lock:  # WR-03: cross-thread write guard
				self._orders_by_venue_id[venue_id] = event
				self._venue_id_by_order_id[event.order_id] = venue_id

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

	def on_market_data(self, bar: Any) -> None:
		"""No-op for live: the venue matches resting orders, not us (D-06).

		A bar never produces a fill on the live path — fills stream back from the venue on
		``watch_my_trades``. Implemented to satisfy the ``AbstractExchange`` seam.
		"""
		return None

	# --- streaming (D-07 — the exchange emits FillEvents itself) ---------------

	def _handle_trade(self, trade: Any) -> None:
		"""Translate one venue fill (ccxt-unified trade) into a ``FillEvent`` on ``global_queue``.

		CONN-05: every inbound float crosses the Decimal boundary via ``to_money(str(x))``.
		Business time: ``FillEvent.time`` is stamped from the venue trade timestamp.
		Input validation (T-02-03-VALID): a fill for an unknown order, or one missing
		price/amount, is skipped-and-logged — never crashed.
		"""
		venue_id = trade.get("order") if isinstance(trade, dict) else None
		with self._correlation_lock:  # WR-03: cross-thread read guard
			order = self._orders_by_venue_id.get(venue_id) if venue_id is not None else None
		if order is None:
			self.logger.warning("Fill for unknown venue order %s — skipping", venue_id)
			return

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
		fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
		fee_cost = fee.get("cost")
		commission = to_money(str(fee_cost)) if fee_cost is not None else Decimal("0")

		fill = FillEvent.new_fill(
			"EXECUTED", order,
			price=to_money(str(price)),
			quantity=to_money(str(amount)),
			commission=commission,
			time=self._ms_to_dt(timestamp))
		# D-07: the EXCHANGE emits the fill; MPSC-safe put from the connector loop thread (D-19).
		self.global_queue.put(fill)

	async def _stream_fills(self) -> None:
		"""Consume the venue fill stream forever, emitting a FillEvent per trade (D-07)."""
		while True:
			trades = await self._connector.client.watch_my_trades()
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
		"""Consume the order-status stream for mirror reconciliation (status only).

		The fill money crosses on ``watch_my_trades`` (``_stream_fills``); this loop tracks
		order lifecycle transitions for logging/reconciliation and never mints money.
		"""
		while True:
			orders = await self._connector.client.watch_orders()
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
		"""
		markets = getattr(self._connector.client, "markets", None)
		if isinstance(markets, dict):
			return symbol in markets
		return True
