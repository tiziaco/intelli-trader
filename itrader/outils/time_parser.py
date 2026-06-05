import re
import pytz
import pandas as pd
from typing import Union, cast
from datetime import datetime, timedelta, timezone
from itrader import config

def get_timenow_awere() -> datetime:
	time_zone = pytz.timezone(config.TIMEZONE)
	# Get the current UTC time
	now = pd.to_datetime(datetime.now(tz=timezone.utc))
	# Make it timezone aware
	now = now.replace(tzinfo=pytz.utc).astimezone(time_zone)

	return cast(datetime, now)

# Getting the frequency hours and minutes
def get_last_available_timestamp(current_time: datetime, frequency: timedelta) -> datetime:
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

	Case-insensitive (`1H`/`1h`, `1D`/`1d`, `1W`/`1w` all parse). Supports
	week (`w`) as a fixed 7-day timedelta. Raises a clear month-specific
	`ValueError` on `M`/`m`-as-month (a month is not a fixed timedelta) and
	on any unknown unit — never returns a silent `None`.

	Parameters
	----------
	timeframe: `str`
		Timeframe of the strategy

	Returns
	-------
	delta: `TimeDelta` object
		The time delta corresponding to the timeframe.
	"""
	# Guard None up front: a None timeframe must fail loudly here, not crash
	# opaquely downstream in re.match / resample.
	if timeframe is None:
		raise ValueError("Timeframe is None; expected a string like '1d', '1h', '1W'.")

	# Splitting text and number in the string
	match = re.match(r"(\d+)([a-zA-Z]+)", timeframe)
	if match:
		quantity, raw_unit = match.groups()
		# Month is special and ambiguous with minutes: by convention an
		# UPPERCASE 'M' means month (NOT a fixed timedelta), while lowercase
		# 'm' means minutes. Reject month explicitly with a specific message
		# BEFORE case-folding, so '1M' raises while '1m' stays minutes.
		if raw_unit == 'M' or raw_unit.lower() == 'mo':
			raise ValueError(
				f"Month timeframe '{timeframe}' is not supported: a month is "
				f"not a fixed timedelta (it varies 28-31 days). Use a fixed "
				f"unit (d/h/m/w)."
			)
		unit = raw_unit.lower()  # case-insensitive: '1H' parses like '1h'
		attributes = {'d': 'days', 'h': 'hours', 'm': 'minutes', 'w': 'weeks'}

		if unit in attributes:
			return timedelta(**{attributes[unit]: int(quantity)})
		# Any other unit is unknown — fail loudly, never return a silent None.
		raise ValueError(
			f"Unsupported timeframe unit '{raw_unit}' in '{timeframe}'. "
			f"Supported units: {sorted(attributes)}."
		)
	raise ValueError(f"Could not parse timeframe '{timeframe}'.")

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

def _aligned(ts: datetime, tf: timedelta) -> bool:
	"""
	Single replaceable alignment seam (D-06): is `ts` on the Unix-epoch grid
	of period `tf`?

	Uses `int(ts.timestamp()) % int(tf.total_seconds()) == 0`. The Unix-epoch
	anchor is DST-immune and, for the golden daily bars at 00:00 UTC, COINCIDES
	with the previous midnight-of-day-UTC anchor — so the behavioral oracle is
	unchanged. Isolating the anchor here lets a future session/exchange-calendar
	anchor (stocks) replace it without rewriting any firing logic.

	Parameters
	----------
	ts: `datetime`
		The (timezone-aware) event time.
	tf: `timedelta`
		The timeframe period to align against.
	"""
	return int(ts.timestamp()) % int(tf.total_seconds()) == 0

def check_timeframe(time: datetime, timeframe: timedelta) -> bool:
	"""
	Check if the current time is a multiple of the strategy's timeframe.
	In that case return True and go on calculating the signals.

	Delegates to the single `_aligned` epoch seam (D-06) — callers never
	re-implement alignment.

	Parameters
	----------
	time: `datetime`
		Event time (timezone-aware).
	timeframe: `timedelta`
		Timeframe of the strategy.
	"""
	return _aligned(time, timeframe)