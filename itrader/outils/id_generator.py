import uuid

import uuid_utils.compat as uuid_compat


class IDGenerator:
	"""
	A class for generating unique UUIDv7 IDs for transactions,
	portfolios, positions, orders, strategies, screeners, and signals.

	Single UUIDv7 scheme (D-12/D-13/D-14): every id is a stdlib ``uuid.UUID``
	produced by ``uuid_utils.compat.uuid7()`` (the compat module returns the
	*native* ``uuid.UUID`` type, not the custom ``uuid_utils.UUID`` — Pitfall 1).

	UUIDv7 is time-ordered (RFC 9562), collision-safe, and index-friendly. The
	entity type is NO LONGER encoded in the value (D-13): the previous
	type-prefix + timestamp + counter integer scheme — which overflowed BIGINT —
	has been deleted. The type is implicit in the field that
	holds the id, never in the id itself.
	"""

	def _uuid7(self) -> uuid.UUID:
		"""Generate a single time-ordered UUIDv7 as a stdlib ``uuid.UUID``."""
		return uuid_compat.uuid7()

	def generate_transaction_id(self) -> uuid.UUID:
		"""Generate unique transaction ID."""
		return self._uuid7()

	def generate_portfolio_id(self) -> uuid.UUID:
		"""Generate unique portfolio ID."""
		return self._uuid7()

	def generate_position_id(self) -> uuid.UUID:
		"""Generate unique position ID."""
		return self._uuid7()

	def generate_order_id(self) -> uuid.UUID:
		"""Generate unique order ID."""
		return self._uuid7()

	def generate_strategy_id(self) -> uuid.UUID:
		"""Generate unique strategy ID."""
		return self._uuid7()

	def generate_screener_id(self) -> uuid.UUID:
		"""Generate unique screener ID."""
		return self._uuid7()

	def generate_signal_id(self) -> uuid.UUID:
		"""Generate unique signal ID (D-10 — single UUIDv7 scheme)."""
		return self._uuid7()
