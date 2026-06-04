from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AbstractPriceHandler(Protocol):
	"""
	Structural interface (D-07) for all subsequent (inherited) data handlers
	(both live and historic).

	The goal of a (derived) PriceHandler object is to output a set of
	TickEvents or BarEvents for each financial instrument and place
	them into an event queue.

	This will replicate how a live strategy would function as current
	tick/bar data would be streamed via a brokerage. Thus a historic and live
	system will be treated identically by the rest of the suite.
	"""

	def get_last_close(self, ticker: str) -> Any: ...

	def get_last_date(self, ticker: str) -> Any: ...

	def get_last_bar(self, ticker: str) -> Any: ...

	def get_bar(self, ticker: str, time: Any) -> Any: ...

	def get_bars(self, ticker: str, start_dt: Any, end_dt: Any) -> Any: ...

	def get_resampled_bars(self, time: Any, ticker: str, timeframe: Any, window: Any) -> Any: ...

	def load_data(self, ticker: str) -> Any: ...

	def update_data(self, ticker: str) -> Any: ...
