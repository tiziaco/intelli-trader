"""D-42 / ACCT-09: the two new ExecutionErrorCode members that name the two
surviving fail-closed causes in ``ExecutionHandler.on_order``.

Before this phase ``ExecutionErrorCode`` had no member that fits either an
"order names a portfolio the engine does not know" refusal or a "no exchange is
registered for this ``(venue, account_id)`` pair" refusal — the nearest
(``INVALID_ORDER`` / ``EXCHANGE_ERROR`` / ``PERMISSION_DENIED``) are all
misnomers. Distinct, greppable codes are what make those two failures
diagnosable, and each implies a different operator fix. These assertions pin
their existence, their distinctness, and the total member count so a silent
rename or collision fails loudly.
"""

from itrader.core.enums.execution import ExecutionErrorCode


def test_two_new_members_exist() -> None:
    """The two D-42 members are present under greppable names."""
    assert ExecutionErrorCode.UNKNOWN_PORTFOLIO
    assert ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT


def test_member_count_is_seventeen() -> None:
    """Fifteen historical members plus the two D-42 additions."""
    assert len(list(ExecutionErrorCode)) == 17


def test_all_member_values_unique() -> None:
    """No two members share a string value (set-size assertion)."""
    values = [member.value for member in ExecutionErrorCode]
    assert len(set(values)) == len(values)


def test_new_members_distinct_from_each_other_and_from_misnomers() -> None:
    """The two new codes differ from each other and from the near-miss codes
    D-42 rejected as misnomers."""
    assert (
        ExecutionErrorCode.UNKNOWN_PORTFOLIO
        is not ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT
    )
    for misnomer in (
        ExecutionErrorCode.INVALID_ORDER,
        ExecutionErrorCode.EXCHANGE_ERROR,
        ExecutionErrorCode.PERMISSION_DENIED,
    ):
        assert ExecutionErrorCode.UNKNOWN_PORTFOLIO is not misnomer
        assert ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT is not misnomer
