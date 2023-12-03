from itrader.execution_handler.fee_model.fee_model import FeeModel


class ZeroFeeModel(FeeModel):
    """
    A FeeModel subclass that produces no commission, fees
    or taxes. This is the default fee model for simulated
    brokerages within iTrader.
    """

    def _calc_commission(self, quantity, price):
        """
        Returns zero commission.

        Parameters
        ----------
        quantity : `int`
            The quantity of assets 
        price : `float`
            Price times quantity of the order.

        Returns
        -------
        `float`
            The zero-cost commission.
        """
        return 0.0

    def _calc_tax(self, quantity, price):
        """
        Returns zero tax.

        Parameters
        ----------
        quantity : `int`
            The quantity of assets 
        price : `float`
            Price times quantity of the order.

        Returns
        -------
        `float`
            The zero-cost tax.
        """
        return 0.0

    def calc_total_commission(self, quantity, price):
        """
        Calculate the total of any commission and/or tax
        for the trade of size 'consideration'.

        Parameters
        ----------
        quantity : `int`
            The quantity of assets 
        price : `float`
            Price times quantity of the order.

        Returns
        -------
        `float`
            The zero-cost total commission and tax.
        """
        commission = self._calc_commission(quantity, price)
        tax = self._calc_tax(quantity, price)
        return commission + tax
