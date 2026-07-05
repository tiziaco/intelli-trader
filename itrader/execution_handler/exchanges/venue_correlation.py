"""VenueCorrelationIndex — the OKX arm's venue-correlation state, encapsulated (WR-05).

WR-05 flagged the four insert-only correlation structures on ``OkxExchange`` — the three
venue-id / order-id / clOrdId maps plus the ``_seen_trade_ids`` dedup set — as *insert-only*:
nothing is ever removed, so over a long live session every order and trade id is retained
(unbounded memory). This class lifts that state (plus the ``_pending_fills_by_venue_id``
late-fill buffer and the ``_correlation_lock``) out of the exchange into ONE cohesive,
socket-free, unit-testable unit so the growth can be bounded and exercised without a socket:

- **R1 — encapsulation.** All correlation state + its lock live here; ``OkxExchange``
  delegates. ``register`` / ``register_pending`` / ``adopt`` write; ``resolve`` reads (the
  fill-correlation path, atomic under the lock — dedup + venue-id/clOrdId resolve + buffer +
  mark-seen in one hold, preserving the WR-03 cross-thread guarantee); ``mark_seen`` dedups.
- **R2 — release-on-terminal (fill-driven).** A per-``venue_id`` cumulative-filled ``Decimal``
  counter (``record_fill``) reports terminal when cumulative reaches ``order.quantity``
  (WR05-D1 — the index self-releases entirely inside the execution domain, NOT coupled to
  ``ReconcileManager``); ``release`` then drains any buffered late fills and drops the order's
  entries (drain-then-evict, WR05-D3), idempotent on an unknown / already-released venue_id.
- **R3 — bounded dedup ring.** ``_seen_trade_ids`` is a ``deque(maxlen=capacity)`` FIFO ring
  (mirroring the ``live_bar_feed.py`` ``deque(maxlen=cache_capacity())`` precedent) + a
  companion ``set`` for O(1) membership (WR05-D2); the oldest id is evicted past capacity. The
  durable ``venue_trade_id`` DB layer (CR-01) is the evicted-then-resent backstop.

Import discipline (backtest-inertness gate): stdlib + ``itrader.core.ids`` +
``itrader.events_handler.events`` ONLY — NO ccxt, NO connector concretion — so this module is
structurally inert on the backtest hot path.

Indentation: this tree is TAB-indented (a mixed-indent diff breaks the file).
"""

import threading
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Tuple

from itrader.core.ids import OrderId
from itrader.events_handler.events import OrderEvent

# WR05-D2: dedup-ring capacity. 10 000 >> a realistic reconnect re-send burst; the in-memory
# ring only needs to cover the reconnect window (an evicted-then-resent id is still deduped at
# the durable venue_trade_id DB layer — CR-01 backstop). Overridable per-instance via the
# constructor (mirrors the _STREAM_RECONNECT_* overridable-constant pattern in okx.py).
_DEDUP_RING_CAPACITY = 10000


@dataclass(frozen=True, slots=True)
class ResolveResult:
	"""Outcome of ``VenueCorrelationIndex.resolve`` for one streamed venue fill.

	``outcome`` ∈ ``{"emit", "duplicate", "buffered", "uncorrelated"}``:
	- ``emit`` — ``order`` resolved; the caller mints + emits the FillEvent OUTSIDE the lock,
	  THEN consumes the dedup slot via ``mark_seen(dedup_key)`` only after a True emit (WR-02).
	- ``duplicate`` — the ``trade['id']`` was already seen (reconnect re-send); no-op.
	- ``buffered`` — uncorrelated but has a ``venue_id``; buffered for late correlation.
	- ``uncorrelated`` — no ``venue_id`` to key a buffer on; the caller skips-and-logs.

	``dedup_key`` carries the symbol-scoped ``f"{ticker}:{trade_id}"`` for an ``emit`` verdict
	(``None`` on the other outcomes, and ``None`` for a trade with no ``trade['id']`` — the
	None-keyed backtest path). WR-02: ``resolve`` no longer consumes the slot itself; the caller
	feeds this key back to ``mark_seen`` ONLY after ``_emit_fill`` proves the fill emitted, so a
	malformed-then-corrected re-send is not silently dropped.
	"""

	order: Optional[OrderEvent]
	venue_id: Optional[str]
	outcome: str
	dedup_key: Optional[str] = None


def _extract_client_order_id(trade: Any) -> Optional[str]:
	"""Pull the echoed client order id (clOrdId) off a ccxt-unified trade.

	ccxt surfaces it as ``clientOrderId`` at the top level, or the raw OKX
	``clOrdId``/``clientOrderId`` under ``info``. Returns None when neither is present so the
	caller falls through to the buffer path.
	"""
	if not isinstance(trade, dict):
		return None
	cid = trade.get("clientOrderId")
	if cid is None:
		info = trade.get("info")
		if isinstance(info, dict):
			cid = info.get("clOrdId") or info.get("clientOrderId")
	return str(cid) if cid else None


class VenueCorrelationIndex:
	"""Cohesive owner of the OKX arm's venue-correlation state (WR-05 R1/R2/R3).

	All methods take ``_correlation_lock`` internally, preserving the WR-03 cross-thread
	guarantee (writes on the engine thread via ``register``/``adopt``; reads on the connector
	loop thread via ``resolve``). Buffered-fill emission + FillEvent mint happen OUTSIDE the
	lock in the caller (``resolve``/``release`` return the trades to emit) so a non-reentrant
	lock cannot deadlock and no fill is minted under the lock (drain-then-evict, WR05-D3).
	"""

	def __init__(self, capacity: int = _DEDUP_RING_CAPACITY) -> None:
		"""Construct an empty index. ``capacity`` bounds the trade-id dedup ring (WR05-D2)."""
		# WR-03: one lock guards every map/ring/counter read+write (engine-thread submit vs
		# connector-loop-thread fills). Keep the current cross-thread guarantee.
		self._correlation_lock = threading.Lock()

		# The three correlation maps (formerly inline on OkxExchange).
		self._orders_by_venue_id: Dict[str, OrderEvent] = {}
		self._venue_id_by_order_id: Dict[OrderId, str] = {}
		self._orders_by_clOrdId: Dict[str, OrderEvent] = {}
		# Buffered fills awaiting correlation (fast-fill race / pre-adoption).
		self._pending_fills_by_venue_id: Dict[str, List[Any]] = {}
		# WR05-D1: per-venue_id cumulative-filled counter driving fill-driven self-release.
		self._cumulative_filled_by_venue_id: Dict[str, Decimal] = {}
		# venue_id -> clOrdId, so ``release`` can drop the clOrdId map entry too (R2 bound).
		self._clordid_by_venue_id: Dict[str, str] = {}

		# R3 (WR05-D2): bounded dedup ring — deque(maxlen) FIFO eviction + companion set for
		# O(1) membership. ``_seen_trade_ids`` stays the membership set (test-observable name).
		self._capacity = capacity
		self._seen_ring: Deque[str] = deque(maxlen=capacity)
		self._seen_trade_ids: set[str] = set()

	# --- registration (write path — engine thread) ----------------------------

	def register_pending(self, clordid: str, order: OrderEvent) -> None:
		"""Pre-correlation keyed by clOrdId, registered BEFORE the create_order RPC (Pitfall 11).

		OKX echoes clOrdId back on the fill, so a fill that streams in before the RPC returns
		the venue id still resolves its OrderEvent via the clOrdId fallback in ``resolve``.
		"""
		with self._correlation_lock:
			self._orders_by_clOrdId[clordid] = order

	def register(self, venue_id: str, order: OrderEvent, clordid: str) -> List[Any]:
		"""Write the venue-id correlation after the RPC returns the venue id; return any
		fills buffered before it landed (the caller re-drains them OUTSIDE the lock).

		Pops + returns ``_pending_fills_by_venue_id[venue_id]`` (fast-fill race, Pitfall 11 —
		never the old silent drop).
		"""
		with self._correlation_lock:
			self._orders_by_venue_id[venue_id] = order
			self._venue_id_by_order_id[order.order_id] = venue_id
			self._clordid_by_venue_id[venue_id] = clordid
			return self._pending_fills_by_venue_id.pop(venue_id, [])

	def adopt(self, venue_id: str, order: OrderEvent, clordid: str) -> List[Any]:
		"""Restart-rehydration seam (WR-02): repopulate ALL three maps from a rehydrated order;
		return any pre-adoption buffered fills for the caller to re-drain OUTSIDE the lock.
		"""
		with self._correlation_lock:
			self._orders_by_venue_id[venue_id] = order
			self._venue_id_by_order_id[order.order_id] = venue_id
			self._orders_by_clOrdId[clordid] = order
			self._clordid_by_venue_id[venue_id] = clordid
			return self._pending_fills_by_venue_id.pop(venue_id, [])

	def venue_id_for(self, order_id: OrderId) -> Optional[str]:
		"""Resolve the venue order id for an engine order id (the cancel path)."""
		with self._correlation_lock:
			return self._venue_id_by_order_id.get(order_id)

	def order_for_venue_id(self, venue_id: str) -> Optional[OrderEvent]:
		"""Resolve the correlated OrderEvent for a venue order id (the order-status path, D-12).

		The venue-side order-status stream (``watch_orders``) carries the venue order id and a
		terminal status (CANCELLED/EXPIRED) the engine did not itself command; the arm needs the
		originating OrderEvent to mint a reconciling FillEvent. Read-only + lock-guarded (WR-03);
		returns None for an unknown / already-released venue id (deferred to the reconcile sweep).
		"""
		with self._correlation_lock:
			return self._orders_by_venue_id.get(venue_id)

	# --- resolution (read path — connector loop thread, atomic) ---------------

	def resolve(self, trade: Any) -> ResolveResult:
		"""Correlate one streamed venue fill to its OrderEvent — atomic under the lock.

		Preserves the exact ``_handle_trade`` semantics in one lock hold (WR-03): resolve
		``trade['order']`` -> OrderEvent with the clOrdId fallback, BUFFER an uncorrelated fill
		that carries a ``venue_id`` (``buffered``) else report ``uncorrelated``, dedup on the
		SYMBOL-scoped key ``f"{order.ticker}:{trade['id']}"`` (a re-send is a ``duplicate``
		no-op), and mark a resolved key seen INSIDE the lock so a concurrent re-send dedupes
		against it. The caller mints + emits OUTSIDE the lock (the FillEvent mint touches no map).

		D-08 / V17-12: the dedup key is the RESOLVED order's ticker + tradeId, NOT the raw
		tradeId — OKX tradeIds are unique only per-instrument, so two symbols sharing a numeric
		tradeId must BOTH settle. The gate therefore runs AFTER resolution (the ticker is not
		known before the order resolves); the buffer / uncorrelated branches are unchanged.

		WR-02: the ``emit`` verdict does NOT consume the dedup slot here — ``resolve`` only
		CHECKS for an already-seen key (``duplicate``) and returns the ``dedup_key`` for the
		caller to ``mark_seen`` AFTER a True ``_emit_fill``. Consuming the slot before the fill
		is proven emitted would drop a malformed-then-corrected re-send of the same key. A trade
		with no ``trade['id']`` (None-keyed backtest path) carries ``dedup_key = None`` → the
		caller's mark-seen is a clean skip, so the oracle path stays dark.
		"""
		trade_id = trade.get("id") if isinstance(trade, dict) else None
		venue_id = trade.get("order") if isinstance(trade, dict) else None
		with self._correlation_lock:
			order = (self._orders_by_venue_id.get(venue_id)
			         if venue_id is not None else None)
			if order is None:
				clordid = _extract_client_order_id(trade)
				if clordid is not None:
					order = self._orders_by_clOrdId.get(clordid)
			if order is None:
				if venue_id is not None:
					self._pending_fills_by_venue_id.setdefault(venue_id, []).append(trade)
					return ResolveResult(None, venue_id, "buffered")
				return ResolveResult(None, None, "uncorrelated")
			# D-08 / V17-12: symbol-scope the dedup key with the resolved order's ticker so a
			# numeric tradeId shared across instruments does not alias (two symbols both settle).
			dedup_key = f"{order.ticker}:{trade_id}" if trade_id is not None else None
			if dedup_key is not None and dedup_key in self._seen_trade_ids:
				return ResolveResult(None, venue_id, "duplicate")
			# WR-02: DO NOT mark seen here — the caller consumes the slot via mark_seen only
			# after _emit_fill returns True (a malformed fill must not burn the slot).
			return ResolveResult(order, venue_id, "emit", dedup_key)

	def mark_seen(self, trade_id: str) -> bool:
		"""Record a trade id in the bounded dedup ring; return True if it was newly seen.

		A second ``mark_seen`` of the same (still-resident) id is an idempotent no-op (False).
		Past capacity the oldest id is evicted (FIFO) and its membership flips back to
		not-seen (WR05-D2).
		"""
		with self._correlation_lock:
			return self._mark_seen_locked(trade_id)

	def _mark_seen_locked(self, trade_id: str) -> bool:
		"""Ring insert — caller MUST hold ``_correlation_lock``. Returns newly-seen."""
		if trade_id in self._seen_trade_ids:
			return False
		# deque(maxlen) auto-drops the oldest on append; keep the companion set in sync by
		# discarding the id that is about to be evicted.
		if self._capacity > 0 and len(self._seen_ring) >= self._capacity:
			self._seen_trade_ids.discard(self._seen_ring[0])
		self._seen_ring.append(trade_id)
		self._seen_trade_ids.add(trade_id)
		return True

	# --- release-on-terminal (R2 — fill-driven, WR05-D1/D3) --------------------

	def record_fill(self, venue_id: str, order: OrderEvent, filled_qty: Decimal) -> bool:
		"""Add a fill to the per-``venue_id`` cumulative-filled counter; report terminal.

		WR05-D1: the index owns the terminal decision entirely inside the execution domain
		(NOT coupled to ``ReconcileManager``) — it self-releases when the accumulated fill
		amount reaches ``order.quantity``. ``>=`` (not strict ``==``) so an over-fill still
		terminalizes; a partial (cumulative < quantity) reports False and the caller retains
		the entries. Decimal arithmetic throughout (money is Decimal end-to-end). The counter
		is fed by the exact same trades that drive the order mirror, so it agrees by
		construction; a drift is a cleanup concern only (fill/position/cash stay authoritative
		on the mirror + portfolio).
		"""
		with self._correlation_lock:
			cumulative = self._cumulative_filled_by_venue_id.get(venue_id, Decimal("0")) + filled_qty
			self._cumulative_filled_by_venue_id[venue_id] = cumulative
			return cumulative >= order.quantity

	def take_pending(self, venue_id: str) -> List[Any]:
		"""Pop + return a ``venue_id``'s buffered late fills WITHOUT dropping the correlation
		(WR-03 drain-through-resolve helper).

		``release_venue_correlation`` re-routes each drained fill through the FULL ``resolve``
		path (dedup + correlation) instead of raw ``_emit_fill`` — that re-resolution needs the
		correlation entries STILL present, so the buffer is emptied here first (correlation
		intact) and ``release`` evicts the now-drained entries afterwards. Idempotent: an unknown
		venue id returns ``[]``.
		"""
		with self._correlation_lock:
			return self._pending_fills_by_venue_id.pop(venue_id, [])

	def release(self, venue_id: str) -> Tuple[Optional[OrderEvent], List[Any]]:
		"""Drain-then-evict a terminalized order's correlation (WR05-D3); idempotent.

		Under the lock: pop + RETURN any ``_pending_fills_by_venue_id`` for ``venue_id`` FIRST
		(so the caller can emit those buffered late fills OUTSIDE the lock BEFORE the
		correlation is considered gone — no WR-02 regression), THEN drop the three correlation
		entries (``_orders_by_venue_id`` / ``_venue_id_by_order_id`` / ``_orders_by_clOrdId``),
		the per-``venue_id`` cumulative counter, and the clOrdId link — bounding the maps.
		Returns the released order + the drained buffered trades. Idempotent: an unknown /
		already-released ``venue_id`` returns ``(None, [])`` with no raise (empty drain).
		"""
		with self._correlation_lock:
			# Drain FIRST (WR05-D3) — surface buffered late fills before dropping entries.
			drained = self._pending_fills_by_venue_id.pop(venue_id, [])
			order = self._orders_by_venue_id.pop(venue_id, None)
			if order is not None:
				self._venue_id_by_order_id.pop(order.order_id, None)
			clordid = self._clordid_by_venue_id.pop(venue_id, None)
			if clordid is not None:
				self._orders_by_clOrdId.pop(clordid, None)
			self._cumulative_filled_by_venue_id.pop(venue_id, None)
			return order, drained

	# --- accessors ------------------------------------------------------------

	def __len__(self) -> int:
		"""Number of orders currently correlated by venue id (the R2 liveness measure)."""
		with self._correlation_lock:
			return len(self._orders_by_venue_id)

	def seen_count(self) -> int:
		"""Size of the bounded dedup set (<= capacity, R3)."""
		with self._correlation_lock:
			return len(self._seen_trade_ids)

	def pending_count(self, venue_id: str) -> int:
		"""Number of fills buffered awaiting correlation for ``venue_id``."""
		with self._correlation_lock:
			return len(self._pending_fills_by_venue_id.get(venue_id, []))
