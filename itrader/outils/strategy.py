from typing import Any

import pandas as pd


def cross_up(present_val: Any, past_val: Any, limit: Any) -> Any:
	return ((present_val > limit) & (past_val <= limit))


def cross_down(present_val: Any, past_val: Any, limit: Any) -> Any:
	return ((present_val < limit) & (past_val >= limit))


def price_cross_up(bar: Any, indicator: Any, lockback: Any) -> Any:
	return ((bar['Close'].values > indicator[lockback]) & (bar['Open'].values < indicator[lockback]))


def price_cross_down(bar: Any, indicator: Any, lockback: Any) -> Any:
	return ((bar['Close'].values < indicator[lockback]) & (bar['Open'].values > indicator[lockback]))
