from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Mapping, Protocol, runtime_checkable

from itrader.events_handler.events import OrderEvent
from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult

if TYPE_CHECKING:
	# Type-only import (VENUE-04/D-09): keeps this Protocol module import-lean
	# on the live path — ``resolve_precision``'s return type is resolved for
	# mypy without pulling ``core.instrument`` into the runtime import graph.
	from itrader.core.instrument import Instrument


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
	"""One venue account's truth at an instant, as reported by the venue.

	The execution adapter already owns the authenticated session, the market-type
	knowledge and the symbol mapping for its account, so it is the only object that
	can ask the venue what it holds. This is what it answers with: a flat,
	engine-agnostic value object carrying no cache, no lock and no lifecycle.

	Everything is ``Decimal`` — a venue balance compared against engine state with
	float arithmetic anywhere in the path is a correctness defect, and this value sits
	directly on the drift-compare path.

	Attributes
	----------
	balances : Mapping[str, Decimal]
		Currency to SETTLED total, as the venue reports it. A map rather than one
		quote scalar because which currency matters is the caller's question, not the
		adapter's, and a spot account's base leg is a balance too.

		The venue's ``free`` figure is deliberately absent: admission is governed by
		the engine's own pending reservations, so available funds are derived from the
		settled total and never from a venue-side free field.
	positions : Mapping[str, Decimal]
		Symbol to SIGNED quantity — negative is short. Per-market-type derivation
		happens in the adapter, so a consumer never asks "was this spot or a
		derivative?": on a derivative account these are the venue's position rows, and
		on a spot account they are derived from the base-currency balance.

		A FLAT position is an ABSENT key, never a zero entry. Both channels agree on
		that: the derivative channel reports no row when flat, and the spot derivation
		omits a zero base total.
	"""

	balances: Mapping[str, Decimal]
	positions: Mapping[str, Decimal]

	@classmethod
	def empty(cls) -> "AccountSnapshot":
		"""A snapshot reporting nothing — the shape a venue-less exchange returns."""
		return cls(balances={}, positions={})


@runtime_checkable
class AbstractExchange(Protocol):
	"""
	Structural interface (D-07) for exchange operations including connection
	management, order execution, health monitoring, and error handling.

	This is a ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes
	the swap-a-fake structural seam that both simulated and live exchanges must
	satisfy, with consistent error handling and monitoring capabilities.
	"""

	# Core execution methods
	def on_order(self, event: OrderEvent) -> None:
		"""
		Route an order event (NEW/CANCEL/MODIFY) for execution or resting.

		Concrete exchanges decide immediate execution vs. resting in an order book.
		"""
		...

	def on_market_data(self, bar: "Any") -> None:
		"""
		Drive resting-order matching against a new market-data bar.

		Concrete exchanges evaluate resting orders and emit fills/
		cancellations. This is the ONLY place fills happen (D-13 single
		matching path): ``execute_order`` is gone — a NEW order admitted
		by ``on_order`` rests in the book and fills on a later bar
		(next-bar-open convention for market orders, D-01/D-13).
		"""
		...

	# Connection management
	def connect(self) -> ConnectionResult:
		"""Establish connection to the exchange."""
		...

	def disconnect(self) -> ConnectionResult:
		"""Disconnect from the exchange."""
		...

	def is_connected(self) -> bool:
		"""Check if currently connected to exchange."""
		...

	# Health and monitoring
	def health_check(self) -> HealthStatus:
		"""Perform comprehensive health check of the exchange."""
		...

	# Configuration
	def configure(self, config: Dict[str, Any]) -> bool:
		"""Configure exchange with settings and credentials."""
		...

	# Validation methods
	def validate_order(self, event: OrderEvent) -> OrderPreflightResult:
		"""Run pre-trade checks before execution (OQ3: execution-domain
		preflight, distinct from the order-domain ValidationResult)."""
		...

	def validate_symbol(self, symbol: str) -> bool:
		"""Check if symbol is valid for trading on this exchange."""
		...

	def snapshot(self) -> AccountSnapshot:
		"""Read this account's balances and positions from the venue, right now.

		Venue truth belongs to whatever owns the authenticated session, which is this
		adapter: it holds the connector, knows the account's market type and maps
		symbols for it. Asking anything else to fetch it means giving that thing a
		second session or a copy of the mapping knowledge.

		Blocking venue I/O, so it runs on the ENGINE thread via the connector's
		synchronous RPC — never on the connector's own loop, where it would block the
		streams it is trying to reconcile against.

		An exchange with no venue behind it returns ``AccountSnapshot.empty()``. The
		contract is uniform on purpose: a consumer that had to ask "does this exchange
		support snapshots?" would be re-deriving account KIND from the adapter type,
		which is the coupling this surface removes.
		"""
		...

	def fetch_venue_uid(self) -> "str | None":
		"""The venue's own account UID for this adapter's session, or ``None``.

		The one external piece of evidence that a session belongs to the account the
		engine believes it does, read through the session this adapter already owns.
		The trust-on-first-use guard compares and alerts; the adapter knows its venue's
		endpoint and field.

		``None`` means "this venue exposes no account UID" — the clean no-op for a venue
		with no credentials at all. MUST NOT raise: the guard is observe-only, so an
		exception here would abort an otherwise-healthy bring-up.
		"""
		...

	def resolve_precision(self, symbol: str) -> "Instrument | None":
		"""Resolve the venue-precision ``Instrument`` for ``symbol`` (VENUE-04/D-09).

		Returns an ``Instrument`` carrying Decimal price/quantity scales read from
		the venue, or ``None`` when precision is unresolvable (no markets map /
		absent symbol / unusable entry) so callers fall to the ``_DEFAULT_*`` ladder.
		"""
		...
