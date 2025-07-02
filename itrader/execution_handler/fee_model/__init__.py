"""
Modern fee model system for trading operations.

This package provides a unified interface for calculating trading fees
across different scenarios and exchange types.
"""

from .base import FeeModel
from .zero_fee_model import ZeroFeeModel
from .percent_fee_model import PercentFeeModel
from .maker_taker_fee_model import MakerTakerFeeModel
from .tiered_fee_model import TieredFeeModel

__all__ = [
    "FeeModel",
    "ZeroFeeModel", 
    "PercentFeeModel",
    "MakerTakerFeeModel",
    "TieredFeeModel"
]