import pandas as pd

@staticmethod
def cross_up(present_val, past_val, limit) -> bool:
	return ((present_val > limit) & (past_val <= limit))
	
@staticmethod
def cross_down(present_val, past_val, limit) -> bool:
	return ((present_val < limit) & (past_val >= limit))

@staticmethod
def price_cross_up(bar, indicator, lockback)  -> bool:
	return ((bar['Close'].values > indicator[lockback]) & (bar['Open'].values < indicator[lockback]))

@staticmethod
def price_cross_down(bar, indicator, lockback) -> bool:
	return ((bar['Close'].values < indicator[lockback]) & (bar['Open'].values > indicator[lockback]))