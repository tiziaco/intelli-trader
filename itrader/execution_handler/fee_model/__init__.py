"""
Decimal-native fee model system for trading operations (D-12).

This package provides a unified interface for calculating trading fees
across different scenarios and exchange types.
"""

from .base import FeeModel
from .zero_fee_model import ZeroFeeModel
from .percent_fee_model import PercentFeeModel
from .maker_taker_fee_model import MakerTakerFeeModel

__all__ = [
    "FeeModel",
    "ZeroFeeModel",
    "PercentFeeModel",
    "MakerTakerFeeModel",
]
