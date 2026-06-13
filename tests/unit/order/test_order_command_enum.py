from itrader.core.enums import OrderCommand, order_command_map


def test_members_exist():
    assert {m.name for m in OrderCommand} == {"NEW", "CANCEL", "MODIFY", "EXPIRE"}


def test_map_resolves_strings():
    assert order_command_map["NEW"] is OrderCommand.NEW
    assert order_command_map["CANCEL"] is OrderCommand.CANCEL
    assert order_command_map["MODIFY"] is OrderCommand.MODIFY
    assert order_command_map["EXPIRE"] is OrderCommand.EXPIRE
