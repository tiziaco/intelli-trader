

class OrderBase(object):
	"""
	The OrderBase class offer basic order handler functionalities
	like keeping track of the portfolio updates, check the limit
	orders and fill them. 
	"""

	def __init__(self, events_queue, portfolios = {}):
		self.events_queue = events_queue
		self.portfolios = portfolios
