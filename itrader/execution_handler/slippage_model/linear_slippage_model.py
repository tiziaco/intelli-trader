"""
Linear slippage model - slippage increases linearly with order size
(Decimal-native, D-12).
"""

import random
from decimal import Decimal
from typing import Dict, Any

from itrader.core.money import to_money

from .base import SlippageModel


class LinearSlippageModel(SlippageModel):
    """
    Linear slippage model that simulates slippage proportional to order size.

    This model combines base slippage (random market noise) with size impact
    that increases linearly with order value.

    Money (D-12): the returned factor is Decimal. The seeded RNG noise is
    drawn as a float (Phase 2 D-11 seam — deterministic given the seed) and
    enters the Decimal domain exactly once via ``to_money``; the size-impact
    and capping arithmetic is pure Decimal.
    """

    def __init__(self, base_slippage_pct: float | Decimal = 0.01,
                 size_impact_factor: float | Decimal = 0.00001,
                 max_slippage_pct: float | Decimal = 0.1,
                 rng: random.Random | None = None):
        """
        Initialize the linear slippage model.

        Parameters
        ----------
        base_slippage_pct : float | Decimal
            Base slippage percentage (random component); a configured Decimal is
            accepted unchanged and enters the Decimal domain via ``to_money``
            (WR-02: avoids the Decimal->float->Decimal repr-artifact round-trip).
        size_impact_factor : float | Decimal
            Factor for size impact calculation
        max_slippage_pct : float | Decimal
            Maximum slippage percentage cap
        rng : random.Random | None
            Injected seeded RNG for deterministic slippage jitter (D-11). When
            None, a fresh ``random.Random()`` is used; the engine wiring passes a
            seeded instance so backtests are reproducible.
        """
        super().__init__()
        self.base_slippage_pct = base_slippage_pct
        self.size_impact_factor = size_impact_factor
        self.max_slippage_pct = max_slippage_pct
        self._rng: random.Random = rng or random.Random()

    def calculate_slippage_factor(self, quantity: Decimal, price: Decimal,
                                  side: str = "buy", order_type: str = "market") -> Decimal:
        """
        Calculate slippage factor based on linear model.

        Parameters
        ----------
        quantity : Decimal
            Order quantity
        price : Decimal
            Order price
        side : str
            Order side ('buy' or 'sell')
        order_type : str
            Order type

        Returns
        -------
        Decimal
            Slippage factor to multiply with price

        Raises
        ------
        ValidationError
            On invalid inputs — there is no silent neutral-factor fallback
            (plan 06-04, T-06-13)
        """
        self.validate_inputs(quantity, price, side, order_type)

        # Base slippage — seeded float noise (D-11 seam) enters Decimal ONCE
        # via to_money. The RNG jitter bound is the float seam itself (not money),
        # so coercing the stored rate to float here is correct, not a money round-trip.
        base_pct = float(self.base_slippage_pct)
        noise = self._rng.uniform(-base_pct, base_pct)
        base_slippage = to_money(noise) / Decimal("100")

        # Size impact — proportional to order value, pure Decimal.
        order_value = quantity * price
        max_slippage = to_money(self.max_slippage_pct) / Decimal("100")
        size_impact = min(
            max_slippage,
            order_value * to_money(self.size_impact_factor) / Decimal("100")
        )

        # Apply slippage direction based on order side
        # Buy orders get positive slippage (worse price)
        # Sell orders get negative slippage (worse price)
        if side.lower() == 'buy':
            total_slippage = base_slippage + size_impact
        else:  # sell
            total_slippage = base_slippage - size_impact

        # Cap total slippage
        total_slippage = max(-max_slippage, min(max_slippage, total_slippage))

        return Decimal("1") + total_slippage

    def get_slippage_info(self) -> Dict[str, Any]:
        """
        Get information about the linear slippage model.

        Returns
        -------
        Dict[str, Any]
            Model information
        """
        return {
            'model_type': 'linear',
            'name': 'Linear Slippage Model',
            'description': 'Slippage increases linearly with order size',
            'parameters': {
                'base_slippage_pct': self.base_slippage_pct,
                'size_impact_factor': self.size_impact_factor,
                'max_slippage_pct': self.max_slippage_pct
            },
            'supports_order_types': ['market', 'limit'],
            'supports_sides': ['buy', 'sell']
        }
