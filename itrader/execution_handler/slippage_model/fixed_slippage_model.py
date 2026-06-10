"""
Fixed slippage model - constant slippage percentage regardless of order size
(Decimal-native, D-12).
"""

import random
from decimal import Decimal
from typing import Dict, Any

from itrader.core.money import to_money

from .base import SlippageModel


class FixedSlippageModel(SlippageModel):
    """
    Fixed slippage model that applies a constant slippage percentage.

    This model applies the same slippage percentage to all orders
    regardless of size, with optional random variation.

    Money (D-12): the returned factor is Decimal. The seeded RNG jitter is
    drawn as a float (Phase 2 D-11 seam — deterministic given the seed) and
    enters the Decimal domain exactly once via ``to_money``.
    """

    def __init__(self, slippage_pct: float | Decimal = 0.01,
                 random_variation: bool = True,
                 rng: random.Random | None = None):
        """
        Initialize the fixed slippage model.

        Parameters
        ----------
        slippage_pct : float | Decimal
            Fixed slippage percentage to apply; a configured Decimal is accepted
            unchanged and enters the Decimal domain via ``to_money`` (WR-02:
            avoids the Decimal->float->Decimal repr-artifact round-trip).
        random_variation : bool
            Whether to apply random variation around the fixed rate
        rng : random.Random | None
            Injected seeded RNG for deterministic slippage jitter (D-11). When
            None, a fresh ``random.Random()`` is used; the engine wiring passes a
            seeded instance so backtests are reproducible.
        """
        super().__init__()
        self.slippage_pct = slippage_pct
        self.random_variation = random_variation
        self._rng: random.Random = rng or random.Random()

    def calculate_slippage_factor(self, quantity: Decimal, price: Decimal,
                                  side: str = "buy", order_type: str = "market") -> Decimal:
        """
        Calculate slippage factor based on fixed percentage.

        Parameters
        ----------
        quantity : Decimal
            Order quantity (ignored for fixed model)
        price : Decimal
            Order price (ignored for fixed model)
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

        # Calculate slippage
        if self.random_variation:
            # Seeded float jitter (D-11 seam) enters Decimal ONCE via to_money.
            # The RNG jitter bound is the float seam itself (not money), so
            # coercing the stored rate to float here is correct, not a round-trip.
            jitter_pct = float(self.slippage_pct)
            jitter = self._rng.uniform(-jitter_pct, jitter_pct)
            slippage = to_money(jitter) / Decimal("100")
        else:
            # Use fixed rate with direction based on order side
            if side.lower() == 'buy':
                slippage = to_money(self.slippage_pct) / Decimal("100")    # worse for buys
            else:  # sell
                slippage = -to_money(self.slippage_pct) / Decimal("100")  # worse for sells

        return Decimal("1") + slippage

    def get_slippage_info(self) -> Dict[str, Any]:
        """
        Get information about the fixed slippage model.

        Returns
        -------
        Dict[str, Any]
            Model information
        """
        return {
            'model_type': 'fixed',
            'name': 'Fixed Slippage Model',
            'description': 'Constant slippage percentage for all orders',
            'parameters': {
                'slippage_pct': self.slippage_pct,
                'random_variation': self.random_variation
            },
            'supports_order_types': ['market', 'limit'],
            'supports_sides': ['buy', 'sell']
        }
