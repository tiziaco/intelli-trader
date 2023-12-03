from .fee_model import FeeModel


class PercentFeeModel(FeeModel):
    """
    A FeeModel subclass that produces a percentage cost
    for tax and commission.

    Parameters
    ----------
    commission_pct : `float`, optional
        The percentage commission applied to the consideration.
        0-100% is in the range [0.0, 1.0]. Hence, e.g. 0.1% is 0.001
    tax_pct : `float`, optional
        The percentage tax applied to the consideration.
        0-100% is in the range [0.0, 1.0]. Hence, e.g. 0.1% is 0.001
    """

    def __init__(self, commission_pct=0.007, tax_pct=0.0):
        #super().__init__()
        self.commission_pct = commission_pct
        self.tax_pct = tax_pct
        self.tax_pct = tax_pct

    def _calc_commission(self, quantity, price):
        """
        Returns the percentage commission from the consideration.

        Parameters
        ----------
        quantity : `int`
            The quantity of assets.
        consideration : `float`
            Price times quantity of the order.

        Returns
        -------
        `float`
            The percentage commission.
        """
        return self.commission_pct * abs(price * quantity)

    def _calc_tax(self, quantity, price):
        """
        Returns the percentage tax from the consideration.

        Parameters
        ----------
        quantity : `int`
            The quantity of assets.
        consideration : `float`
            Price times quantity of the order.

        Returns
        -------
        `float`
            The percentage tax.
        """
        return self.tax_pct * abs(price * quantity)

    def calc_total_commission(self, quantity, price):
        """
        Calculate the total of any commission and/or tax
        for the trade of size 'consideration'.

        Parameters
        ----------
        quantity : `int`
            The quantity of assets (needed for InteractiveBrokers
            style calculations).
        consideration : `float`
            Price times quantity of the order.

        Returns
        -------
        `float`
            The total commission and tax.
        """
        commission = self._calc_commission(quantity, price)
        tax = self._calc_tax(quantity, price)
        return commission + tax
