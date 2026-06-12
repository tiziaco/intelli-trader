from itrader.core.sizing import SignalIntent
from itrader.strategy_handler.base import Strategy


class EmptyStrategy(Strategy):
	"""
	Minimal no-op strategy: never signals. Used by tests to exercise the
	shared base behaviour (pure-alpha contract, D-12).

	Class-attr authoring surface (D-02): max_window is a class attr; warmup
	stays the base default 0 (no warmup gating, D-15). sizing_policy / direction
	are supplied by the caller as kwargs (no strategy-specific defaults).
	"""

	# Fetch width (bars); warmup stays 0 (no warmup gating, D-15).
	max_window: int = 1

	def generate_signal(self, ticker: str) -> SignalIntent | None:
		return None
