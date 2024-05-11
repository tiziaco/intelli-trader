import re
import pytz
import pandas as pd
from typing import Union
from datetime import datetime, timedelta, timezone
from itrader import config

def get_timenow_awere():
	time_zone = pytz.timezone(config.TIMEZONE)
	# Get the current UTC time
	now = pd.to_datetime(datetime.now(tz=timezone.utc))
	# Make it timezone aware
	now = now.replace(tzinfo=pytz.utc).astimezone(time_zone)

	return now

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

def timedelta_to_str(delta: timedelta) -> Union[str, None]:
	"""
	Convert a timedelta object into a string representation of the equivalent timeframe.

	Parameters
	----------
	delta: `timedelta`
		The timedelta object to be converted.

	Returns
	-------
	timeframe: `str` or `None`
		The string representation of the equivalent timeframe if successful, otherwise None.
	"""
	total_seconds = delta.total_seconds()

	days, remainder = divmod(total_seconds, 86400)
	hours, remainder = divmod(remainder, 3600)
	minutes, seconds = divmod(remainder, 60)

	parts = []
	if days:
		parts.append(f"{int(days)}d")
	if hours:
		parts.append(f"{int(hours)}h")
	if minutes:
		parts.append(f"{int(minutes)}m")
	if seconds:
		parts.append(f"{int(seconds)}s")

	return ' '.join(parts) if parts else None

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

def check_timeframe(time: datetime, timeframe: timedelta) -> bool:
		"""
		Check if the current time of is a multiple of the
		strategy's timeframe.
		In that case return True end go on calculating the signals.

		Parameters
		----------
		time: `timestamp`
			Event time
		timeframe: `timedelta object`
			Timeframe of the strategy
		"""
		# Calculate the number of seconds in the timestamp
		time = time.astimezone(pytz.utc)
		seconds = (time - time.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()

		# Check if the number of seconds is a multiple of the delta
		if seconds % timeframe.total_seconds() == 0:
			# The timestamp IS a multiple of the timeframe
			return True
		else:
			# The timestamp IS NOT a multiple of the timeframe
			return False

def elapsed_time(cure_time: datetime,  past_time: datetime):
	return cure_time - past_time