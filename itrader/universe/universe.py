from abc import ABC
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
	from ..events_handler.events import BarEvent, TimeEvent


class Universe(ABC):
	"""
	Interface specification for an Asset Universe.

	Real ABC (D-07): the dead ``__metaclass__ = ABCMeta`` Py2 no-op is removed so
	this is a genuine abstract base. ``get_assets`` is intentionally NOT marked
	``@abstractmethod`` here: ``DynamicUniverse`` (the live impl) does not provide
	it, and reconciling the universe interface is the deferred universe collapse
	(M5b #33). Minimal conformance only — the method keeps its current
	NotImplementedError contract.
	"""

	def get_assets(self, dt: Any) -> Any:
		raise NotImplementedError(
			"Should implement get_assets()"
		)

	def generate_bar_event(self, time_event: "TimeEvent") -> "Optional[BarEvent]":
		"""Generate the per-tick BarEvent for the run path.

		Declared on the base so the run-path reference (``universe.generate_bar_event``)
		type-resolves against the abstract ``Universe`` type; ``DynamicUniverse``
		provides the live implementation.
		"""
		raise NotImplementedError(
			"Should implement generate_bar_event()"
		)
