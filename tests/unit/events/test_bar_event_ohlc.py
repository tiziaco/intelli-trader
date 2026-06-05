import unittest
import pandas as pd
from datetime import datetime
from itrader.events_handler.event import BarEvent


class TestBarEventOHLC(unittest.TestCase):
	def setUp(self):
		bars = {'BTCUSDT': pd.DataFrame(
			{'open': [30], 'high': [60], 'low': [20], 'close': [40], 'volume': [1000]})}
		self.bar = BarEvent(time=datetime(2024, 1, 1), bars=bars)

	def test_get_last_high(self):
		self.assertEqual(self.bar.get_last_high('BTCUSDT'), 60.0)

	def test_get_last_low(self):
		self.assertEqual(self.bar.get_last_low('BTCUSDT'), 20.0)

	def test_missing_ticker_returns_none(self):
		self.assertIsNone(self.bar.get_last_high('ETHUSDT'))
		self.assertIsNone(self.bar.get_last_low('ETHUSDT'))
