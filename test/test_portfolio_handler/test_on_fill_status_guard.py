import unittest
from datetime import datetime
from queue import Queue

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import FillEvent, FillStatus
from itrader.core.enums import OrderType


class TestOnFillStatusGuard(unittest.TestCase):
    def setUp(self):
        self.queue = Queue()
        self.ptf = PortfolioHandler(self.queue)
        self.pid = self.ptf.add_portfolio(1, 'p', 'default', 100000)

    def _fill(self, status):
        return FillEvent(
            time=datetime(2024, 1, 1),
            status=FillStatus[status],
            ticker='BTCUSDT',
            action='BUY',
            price=40.0,
            quantity=1.0,
            commission=0.0,
            portfolio_id=self.pid,
        )

    def test_cancelled_fill_creates_no_transaction(self):
        result = self.ptf.on_fill(self._fill('CANCELLED'))
        self.assertFalse(result)  # ignored, no transaction
        portfolio = self.ptf.get_portfolio(self.pid)
        self.assertEqual(len(portfolio.positions), 0)
        self.assertEqual(len(portfolio.transactions), 0)

    def test_executed_fill_is_processed(self):
        result = self.ptf.on_fill(self._fill('EXECUTED'))
        self.assertTrue(result)  # processed normally
        portfolio = self.ptf.get_portfolio(self.pid)
        self.assertEqual(len(portfolio.positions), 1)
        self.assertEqual(len(portfolio.transactions), 1)
