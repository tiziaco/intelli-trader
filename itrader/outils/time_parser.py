import re
from datetime import timedelta

def to_timedelta(timeframe: str) -> timedelta:
	"""
	Transform the timeframe string in a `timedelta` object.

	Parameters
	----------
	timeframe: `str`
		Timeframe of the strategy

	Returns
	-------
	delta: `TimeDelta` object
		The time delta corresponding to the timeframe.
	"""
	
	# Splitting text and number in thestring
	match = re.match(r"(\d+)([a-zA-Z]+)", timeframe)
	if match:
		quantity, unit = match.groups()
		attributes = {'d': 'days', 'h': 'hours', 'm': 'minutes'}

		if unit in attributes:
			return timedelta(**{attributes[unit]: int(quantity)})
	return None

def format_timeframe(timeframe: str) -> str:
	"""
	Replace 'm' with 'min' in the timeframe string.
	"""
	# Splitting text and number in string
	temp = re.compile("([0-9]+)([a-zA-Z]+)")
	res = temp.match(timeframe).groups()
	if res[1] == 'm':
		return (res[0] + 'min')
	else:
		return timeframe