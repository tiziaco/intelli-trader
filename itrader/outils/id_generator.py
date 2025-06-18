import threading
import time


class IDGenerator:
	"""
	A class for generating unique integer IDs for transactions, 
	portfolios, positions, and orders.
	
	Uses timestamp + counter approach for guaranteed uniqueness
	across application restarts and high-frequency generation.
	Thread-safe implementation optimized for trading system performance.
	"""
	def __init__(self):
		self.transaction_counter = 0
		self.portfolio_counter = 0
		self.position_counter = 0
		self.order_counter = 0
		self.strategy_counter = 0
		self.screener_counter = 0
		self._lock = threading.Lock()
		
		# Cache last timestamp to handle same-microsecond requests
		self._last_timestamp = 0

	def _generate_unique_id(self, counter_attr: str, type_prefix: int) -> int:
		"""
		Generate a unique integer ID using timestamp + type + counter approach.
		
		Format: TYPE_UNIX_TIMESTAMP_MICROSECONDS_COUNTER
		Example: 1_1750228534516_001 (type:1, timestamp:1750228534516, counter:001)
		
		Type prefixes:
		1 = Transaction, 2 = Portfolio, 3 = Position, 4 = Order, 5 = Strategy, 6 = Screener
		
		This ensures:
		- Uniqueness across application restarts (timestamp)
		- Uniqueness within same microsecond (counter)
		- Uniqueness across different types (type prefix)
		- Still integer type for maximum performance
		"""
		with self._lock:
			# Get current timestamp in microseconds
			current_timestamp = int(time.time() * 1_000_000)
			
			# If same timestamp as last call, increment counter
			if current_timestamp == self._last_timestamp:
				counter = getattr(self, counter_attr) + 1
				setattr(self, counter_attr, counter)
			else:
				# New timestamp, reset counter
				counter = 1
				setattr(self, counter_attr, counter)
				self._last_timestamp = current_timestamp
			
			# Combine type prefix + timestamp + counter
			# Format: TYPE(1) + TIMESTAMP(13-16 digits) + COUNTER(3 digits)
			return type_prefix * 10**19 + current_timestamp * 1000 + counter

	def generate_transaction_id(self) -> int:
		"""Generate unique transaction ID."""
		return self._generate_unique_id('transaction_counter', 1)

	def generate_portfolio_id(self) -> int:
		"""Generate unique portfolio ID."""
		return self._generate_unique_id('portfolio_counter', 2)

	def generate_position_id(self) -> int:
		"""Generate unique position ID."""
		return self._generate_unique_id('position_counter', 3)

	def generate_order_id(self) -> int:
		"""Generate unique order ID.
		
		Optimized for high-performance trading systems.
		Guarantees uniqueness across application restarts.
		"""
		return self._generate_unique_id('order_counter', 4)
	
	def generate_strategy_id(self) -> int:
		"""Generate unique strategy ID."""
		return self._generate_unique_id('strategy_counter', 5)

	def generate_screener_id(self) -> int:
		"""Generate unique screener ID."""
		return self._generate_unique_id('screener_counter', 6)