from decimal import Decimal
from typing import List, Tuple, Union, Dict, Any, Optional
from .base import FeeModel


class TieredFeeModel(FeeModel):
    """
    Fee model implementing tiered fee structure based on trading volume.
    
    Many exchanges offer volume-based fee discounts where traders with higher
    30-day trading volumes get reduced fees. This model supports configurable
    volume tiers with separate maker/taker rates.
    """

    def __init__(self, fee_tiers: Optional[List[Tuple[float, float, float]]] = None, current_volume: float = 0.0):
        """
        Initialize the tiered fee model.
        
        Parameters
        ----------
        fee_tiers : List[Tuple[float, float, float]], optional
            List of (volume_threshold, maker_rate, taker_rate) tuples.
            Default creates a realistic crypto exchange tier structure.
        current_volume : float, optional
            Current 30-day trading volume (default: 0.0)
            
        Raises
        ------
        ValueError
            If fee tiers are invalid or current volume is negative
        """
        if current_volume < 0:
            raise ValueError(f"Current volume must be non-negative, got {current_volume}")
            
        if fee_tiers is None:
            # Default tier structure similar to major exchanges (volume, maker_rate, taker_rate)
            fee_tiers = [
                (0, 0.0015, 0.0015),        # Tier 0: < $0 - 0.15%/0.15%
                (10000, 0.0014, 0.0015),    # Tier 1: $10K+ - 0.14%/0.15%
                (50000, 0.0012, 0.0014),    # Tier 2: $50K+ - 0.12%/0.14%
                (100000, 0.0010, 0.0012),   # Tier 3: $100K+ - 0.10%/0.12%
                (250000, 0.0008, 0.0010),   # Tier 4: $250K+ - 0.08%/0.10%
                (500000, 0.0006, 0.0008),   # Tier 5: $500K+ - 0.06%/0.08%
                (1000000, 0.0004, 0.0006),  # Tier 6: $1M+ - 0.04%/0.06%
            ]
        
        self.fee_tiers = self._validate_and_sort_tiers(fee_tiers)
        self.current_volume = Decimal(str(current_volume))
        self._current_tier = self._determine_current_tier()

    def _validate_and_sort_tiers(self, tiers: List[Tuple[float, float, float]]) -> List[Tuple[Decimal, Decimal, Decimal]]:
        """
        Validate and sort volume tiers.
        
        Parameters
        ----------
        tiers : List[Tuple[float, float, float]]
            Raw tier data (volume_threshold, maker_rate, taker_rate)
            
        Returns
        -------
        List[Tuple[Decimal, Decimal, Decimal]]
            Validated and sorted tiers
        """
        if not tiers:
            raise ValueError("Fee tiers cannot be empty")
        
        validated_tiers = []
        for i, tier in enumerate(tiers):
            if len(tier) != 3:
                raise ValueError(f"Each tier must have 3 values (volume, maker_rate, taker_rate), got {len(tier)} at tier {i}")
            
            volume, maker_rate, taker_rate = tier
            
            if volume < 0:
                raise ValueError(f"Volume threshold must be non-negative, got {volume} at tier {i}")
            if maker_rate < 0:
                raise ValueError(f"Maker rate must be non-negative, got {maker_rate} at tier {i}")
            if taker_rate < 0:
                raise ValueError(f"Taker rate must be non-negative, got {taker_rate} at tier {i}")
            
            validated_tiers.append((Decimal(str(volume)), Decimal(str(maker_rate)), Decimal(str(taker_rate))))
        
        # Sort by volume threshold
        validated_tiers.sort(key=lambda x: x[0])
        
        # First tier should start at 0
        if validated_tiers[0][0] != Decimal('0'):
            raise ValueError("First tier must start at volume 0")
        
        return validated_tiers

    def _determine_current_tier(self) -> int:
        """
        Determine the current tier based on trading volume.
        
        Returns
        -------
        int
            Index of the current tier
        """
        for i in range(len(self.fee_tiers) - 1, -1, -1):
            volume_threshold, _, _ = self.fee_tiers[i]
            if self.current_volume >= volume_threshold:
                return i
        return 0  # Default to first tier

    def calculate_fee(
        self, 
        quantity: Union[int, float, Decimal], 
        price: Union[float, Decimal], 
        side: str = "buy",
        order_type: str = "market",
        **kwargs
    ) -> Decimal:
        """
        Calculate tiered fee for an order.
        
        Parameters
        ----------
        quantity : Union[int, float, Decimal]
            Number of units to trade
        price : Union[float, Decimal]
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type ("market", "limit", etc.)
        **kwargs
            Additional parameters (e.g., is_maker override, current_volume override)
            
        Returns
        -------
        Decimal
            Fee amount based on current tier and maker/taker status
        """
        self.validate_inputs(quantity, price, side, order_type)
        
        # Convert to Decimal for precision
        quantity_decimal = Decimal(str(quantity))
        price_decimal = Decimal(str(price))
        trade_value = abs(quantity_decimal * price_decimal)
        
        # Allow volume override for specific calculations
        volume_to_use = kwargs.get('current_volume', self.current_volume)
        if volume_to_use != self.current_volume:
            # Temporarily calculate tier for different volume
            temp_tier = self._determine_tier_for_volume(Decimal(str(volume_to_use)))
            _, maker_rate, taker_rate = self.fee_tiers[temp_tier]
        else:
            # Use current tier
            _, maker_rate, taker_rate = self.fee_tiers[self._current_tier]
        
        # Determine if this is a maker or taker order
        is_maker = self._is_maker_order(order_type, **kwargs)
        
        # Apply appropriate fee
        if is_maker:
            return trade_value * maker_rate
        else:
            return trade_value * taker_rate

    def _is_maker_order(self, order_type: str, **kwargs) -> bool:
        """
        Determine if an order is a maker order.
        
        Parameters
        ----------
        order_type : str
            Order type
        **kwargs
            Additional parameters (e.g., is_maker override)
            
        Returns
        -------
        bool
            True if this is a maker order
        """
        # Allow explicit override
        if "is_maker" in kwargs:
            return bool(kwargs["is_maker"])
        
        # Default classification based on order type
        order_type_lower = order_type.lower()
        
        # Market orders are typically takers
        if order_type_lower in ("market", "market_order"):
            return False
        
        # Limit orders are typically makers (though not always)
        if order_type_lower in ("limit", "limit_order"):
            return True
        
        # Conservative default: assume taker (higher fee)
        return False

    def _determine_tier_for_volume(self, volume: Decimal) -> int:
        """Determine tier for a specific volume."""
        for i in range(len(self.fee_tiers) - 1, -1, -1):
            volume_threshold, _, _ = self.fee_tiers[i]
            if volume >= volume_threshold:
                return i
        return 0

    def update_volume(self, new_volume: Union[float, Decimal]) -> None:
        """
        Update the current trading volume and recalculate tier.
        
        Parameters
        ----------
        new_volume : Union[float, Decimal]
            New 30-day trading volume
            
        Raises
        ------
        ValueError
            If new volume is negative
        """
        new_volume_decimal = Decimal(str(new_volume))
        if new_volume_decimal < 0:
            raise ValueError(f"Volume must be non-negative, got {new_volume}")
        
        self.current_volume = new_volume_decimal
        self._current_tier = self._determine_current_tier()

    def add_to_volume(self, trade_value: Union[float, Decimal]) -> None:
        """
        Add trade value to current volume.
        
        Parameters
        ----------
        trade_value : Union[float, Decimal]
            Value of the completed trade to add to volume
        """
        trade_value_decimal = Decimal(str(trade_value))
        self.current_volume += abs(trade_value_decimal)
        self._current_tier = self._determine_current_tier()

    def reset_volume(self) -> None:
        """Reset the volume tracker (e.g., for new trading period)."""
        self.current_volume = Decimal('0')
        self._current_tier = 0

    def get_current_tier_info(self) -> Dict[str, Any]:
        """
        Get information about the current tier.
        
        Returns
        -------
        Dict[str, Any]
            Current tier information
        """
        volume_threshold, maker_rate, taker_rate = self.fee_tiers[self._current_tier]
        
        # Calculate next tier info
        next_tier_info = None
        if self._current_tier < len(self.fee_tiers) - 1:
            next_volume_threshold, next_maker_rate, next_taker_rate = self.fee_tiers[self._current_tier + 1]
            volume_needed = next_volume_threshold - self.current_volume
            next_tier_info = {
                "tier": self._current_tier + 1,
                "volume_threshold": float(next_volume_threshold),
                "maker_rate": float(next_maker_rate),
                "taker_rate": float(next_taker_rate),
                "volume_needed": float(volume_needed) if volume_needed > 0 else 0
            }
        
        return {
            "current_tier": self._current_tier,
            "volume_threshold": float(volume_threshold),
            "current_volume": float(self.current_volume),
            "maker_rate": float(maker_rate),
            "taker_rate": float(taker_rate),
            "maker_rate_pct": f"{float(maker_rate) * 100:.4f}%",
            "taker_rate_pct": f"{float(taker_rate) * 100:.4f}%",
            "next_tier": next_tier_info
        }

    def get_fee_info(self) -> Dict[str, Any]:
        """Get information about this tiered fee model."""
        base_info = super().get_fee_info()
        base_info.update({
            "description": "Volume-based tiered fee structure with maker/taker rates",
            "total_tiers": len(self.fee_tiers),
            "current_tier_info": self.get_current_tier_info(),
            "all_tiers": [
                {
                    "tier": i,
                    "volume_threshold": float(volume),
                    "maker_rate": float(maker_rate),
                    "taker_rate": float(taker_rate),
                    "maker_rate_pct": f"{float(maker_rate) * 100:.4f}%",
                    "taker_rate_pct": f"{float(taker_rate) * 100:.4f}%"
                }
                for i, (volume, maker_rate, taker_rate) in enumerate(self.fee_tiers)
            ]
        })
        return base_info

    def calculate_maker_fee(self, quantity: Union[int, float, Decimal], price: Union[float, Decimal]) -> Decimal:
        """Calculate fee for a maker order at current tier."""
        return self.calculate_fee(quantity, price, order_type="limit", is_maker=True)
    
    def calculate_taker_fee(self, quantity: Union[int, float, Decimal], price: Union[float, Decimal]) -> Decimal:
        """Calculate fee for a taker order at current tier."""
        return self.calculate_fee(quantity, price, order_type="market", is_maker=False)
