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
	- ``emit`` — ``order`` resolved; the caller mints + emits the FillEvent OUTSIDE the lock.
	- ``duplicate`` — the ``trade['id']`` was already seen (reconnect re-send); no-op.
	- ``buffered`` — uncorrelated but has a ``venue_id``; buffered for late correlation.
	- ``uncorrelated`` — no ``venue_id`` to key a buffer on; the caller skips-and-logs.
	"""

	order: Optional[OrderEvent]
	venue_id: Optional[str]
	outcome: str


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

	# --- resolution (read path — connector loop thread, atomic) ---------------

	def resolve(self, trade: Any) -> ResolveResult:
		"""Correlate one streamed venue fill to its OrderEvent — atomic under the lock.

		Preserves the exact ``_handle_trade`` semantics in one lock hold (WR-03): dedup on
		``trade['id']`` (a re-send is a ``duplicate`` no-op), resolve ``trade['order']`` ->
		OrderEvent with the clOrdId fallback, BUFFER an uncorrelated fill that carries a
		``venue_id`` (``buffered``) else report ``uncorrelated``, and mark a resolved trade id
		seen INSIDE the lock so a concurrent re-send dedupes against it. The caller mints +
		emits OUTSIDE the lock (the FillEvent mint touches no map).
		"""
		trade_id = trade.get("id") if isinstance(trade, dict) else None
		venue_id = trade.get("order") if isinstance(trade, dict) else None
		with self._correlation_lock:
			if trade_id is not None and trade_id in self._seen_trade_ids:
				return ResolveResult(None, venue_id, "duplicate")
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
			if trade_id is not None:
				self._mark_seen_locked(trade_id)
			return ResolveResult(order, venue_id, "emit")

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

	# --- release-on-terminal (R2 — fill-driven; body lands in Task 3) ----------

	def record_fill(self, venue_id: str, order: OrderEvent, filled_qty: Decimal) -> bool:
		"""Feed the per-``venue_id`` cumulative-filled counter; report terminal (WR05-D1).

		Body lands in Task 3 (R2 release-on-terminal wiring).
		"""
		return False

	def release(self, venue_id: str) -> Tuple[Optional[OrderEvent], List[Any]]:
		"""Drain-then-evict a terminalized order's correlation (WR05-D3).

		Body lands in Task 3 (R2 release-on-terminal wiring).
		"""
		return None, []

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
