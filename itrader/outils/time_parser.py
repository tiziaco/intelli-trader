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

# Getting the frequency hours and minutes
def get_last_available_timestamp(current_time: datetime, frequency: timedelta):
	"""
	Calculate the last available timestamp based on the current time 
	and the specified frequency.

	Parameters:
	- current_time (datetime): The current time as a datetime object.
	- frequency (timedelta): The frequency or timeframe for the last available timestamp.

	Returns:
	- last_available_time (datetime): The last available timestamp.
	"""
	# Calculate the number of minutes in the frequency
	frequency_minutes = frequency.total_seconds() // 60

	# Calculate the number of minutes elapsed since midnight
	current_minutes = current_time.hour * 60 + current_time.minute

	# Calculate the number of minutes since the last available timestamp
	minutes_since_last_timestamp = current_minutes % frequency_minutes

	# Subtract the minutes since the last timestamp from the current time
	last_available_time = current_time - timedelta(minutes=minutes_since_last_timestamp,
												seconds=current_time.second,
												microseconds=current_time.microsecond)
	return last_available_time

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
		time = time.astimezone(pytz.utc).replace(second=0, microsecond=0)
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

def round_timestamp_to_frequency(timestamp : datetime, frequency: timedelta):
    """
    Round a timestamp to the closest frequency.

    Parameters:
    - timestamp: datetime object representing the timestamp
    - frequency: timedelta object representing the frequency

    Returns:
    - rounded_timestamp: datetime object representing the rounded timestamp
    """
    # Convert timestamp to Unix timestamp (seconds since epoch)
    timestamp_unix = int(timestamp.timestamp())

    # Convert frequency to seconds
    frequency_seconds = int(frequency.total_seconds())

    # Round the Unix timestamp to the closest multiple of frequency
    rounded_timestamp_unix = round(timestamp_unix / frequency_seconds) * frequency_seconds

    # Convert rounded Unix timestamp back to datetime object
    rounded_timestamp = datetime.fromtimestamp(rounded_timestamp_unix)

    return rounded_timestamp