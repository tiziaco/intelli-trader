import unittest
from itrader.core.enums import OrderCommand, order_command_map


class TestOrderCommand(unittest.TestCase):
	def test_members_exist(self):
		self.assertEqual({m.name for m in OrderCommand}, {"NEW", "CANCEL", "MODIFY"})

	def test_map_resolves_strings(self):
		self.assertIs(order_command_map["NEW"], OrderCommand.NEW)
		self.assertIs(order_command_map["CANCEL"], OrderCommand.CANCEL)
		self.assertIs(order_command_map["MODIFY"], OrderCommand.MODIFY)
