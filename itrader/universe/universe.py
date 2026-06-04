from abc import ABC
from typing import Any


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
