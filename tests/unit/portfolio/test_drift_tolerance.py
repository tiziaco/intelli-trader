"""
Unit tests for the precision-epsilon drift-tolerance helper (D-01, RECON-01/RECON-03).

``is_within_single_unit_tolerance`` is the reconciliation primitive every Phase-5
compare consumes: two Decimal values agree when their absolute difference is within
one least-significant-digit unit for the caller's instrument precision. Ported in
concept from nautilus ``live/reconciliation.py:52`` — the four behavior cases below
pin the precision keying (0 = exact integer, 8 = BTC quantity lotSz, 2 = cash/price).
"""

from decimal import Decimal

from itrader.portfolio_handler.reconcile import is_within_single_unit_tolerance


class TestIsWithinSingleUnitTolerance:
    def test_precision_zero_exact_equality_true(self) -> None:
        # precision==0 → integer quantities compare exactly
        assert is_within_single_unit_tolerance(Decimal("5"), Decimal("5"), 0) is True

    def test_precision_zero_off_by_one_false(self) -> None:
        assert is_within_single_unit_tolerance(Decimal("5"), Decimal("6"), 0) is False

    def test_precision_eight_within_tolerance_true(self) -> None:
        # precision==8 → tolerance 1e-8 (BTC quantity, 8dp lotSz)
        v1 = Decimal("1.00000000")
        v2 = Decimal("1.00000001")  # exactly 1e-8 apart
        assert is_within_single_unit_tolerance(v1, v2, 8) is True

    def test_precision_eight_beyond_tolerance_false(self) -> None:
        v1 = Decimal("1.00000000")
        v2 = Decimal("1.00000002")  # 2e-8 apart, beyond 1e-8
        assert is_within_single_unit_tolerance(v1, v2, 8) is False

    def test_precision_two_within_tolerance_true(self) -> None:
        # precision==2 → tolerance 0.01 (cash/price epsilon)
        assert (
            is_within_single_unit_tolerance(Decimal("100.00"), Decimal("100.01"), 2)
            is True
        )

    def test_precision_two_beyond_tolerance_false(self) -> None:
        assert (
            is_within_single_unit_tolerance(Decimal("100.00"), Decimal("100.02"), 2)
            is False
        )

    def test_zero_difference_true_at_every_precision(self) -> None:
        for precision in (0, 2, 8):
            assert (
                is_within_single_unit_tolerance(Decimal("42"), Decimal("42"), precision)
                is True
            )
