class IDGenerator:
	"""
	A class for generating unique IDs for transactions, 
	portfolios, positions, and orders.
	"""
	def __init__(self):
		self.transaction_counter = 0
		self.portfolio_counter = 0
		self.position_counter = 0
		self.order_counter = 0

	def generate_transaction_id(self):
		self.transaction_counter += 1
		return self.transaction_counter

	def generate_portfolio_id(self):
		self.portfolio_counter += 1
		return self.portfolio_counter

	def generate_position_id(self):
		self.position_counter += 1
		return self.position_counter

	def generate_order_id(self):
		self.order_counter += 1
		return self.order_counter