from ....outils.price_parser import PriceParser
import pandas_ta as ta


import logging
logger = logging.getLogger('TradingSystem')


class FixedPercentage():
    """
    This class calculate the sttop loss and take profit price.
    The limit prices are based on a fixed percentage of the 
    last price.
    """

    def calculate_sl(self, sized_order, sl_setting, bars):
        """
        Define stopLoss level at a % of the last close.

        Parameters
        ----------
        sl_level: `float`
            Stop loss level in % (default: 3%)
        """
        last_close = sized_order.price

        if sized_order.direction == 'BOT':
            # LONG direction: sl lower
            sized_order.sl = round(last_close * (1-sl_setting['sl_level']), 5)
        elif sized_order.direction == 'SLD':
            # SHORT direction: sl higher
            sized_order.sl  = round(last_close * (1+sl_setting['sl_level']), 5)
        return sized_order


    def calculate_tp(self, sized_order, tp_setting, bars):
        """
        Define stopLoss level at a % of the last close

        Parameters
        ----------
        tp_level: `float`
            Take profit level in % (default: 5%)
        """
        last_close = sized_order.price

        if sized_order.direction == 'BOT':
            # LONG direction: tp higher
            sized_order.tp = last_close * (1+tp_setting['tp_level'])
        elif sized_order.direction == 'SLD':
            # SHORT direction: tp lower
            sized_order.tp = last_close * (1-tp_setting['tp_level'])
        return sized_order
        
class Proportional():
    """
    This class calculate the take profit price.
    The limit price is proportional to the defined 
    stop loss price.
    """

    def calculate_tp(self, sized_order, tp_setting, bars):
        """
        Define stopLoss level at a % of the last close

        Parameters
        ----------
        tp_level: `float`
            Take profit level in % (default: 5%)
        """
        last_close = sized_order.price
        sl = sized_order.sl
        

        if sized_order.direction == 'BOT':
            # LONG direction: tp higher
            delta = last_close-sl
            sized_order.tp = last_close + tp_setting['multiplier']*delta
        elif sized_order.direction == 'SLD':
            # SHORT direction: tp lower
            delta = sl - last_close
            sized_order.tp = last_close - tp_setting['multiplier']*delta
        return sized_order


class ATRsltp():
    """
    This class calculate the stop loss and take profit price.
    The limit prices are based on the ATR indicator
    """

    def calculate_sl(self, sized_order, sl_setting, bars):
        """
        Define stopLoss level based on the ATR value.
        It is calculated on the open or close price of the bar,
        according to the direction of the trade.

        Parameters
        ----------
        sized_order:
            Sized order object
        window: `int`
            Lookback window for the ATR
        multiplier: `float`
            ATR multiplier (between 1 and 3)
        """
        atr = ta.atr(bars.high, bars.low, bars.close, sl_setting['window'], mamode='rma', drift=1)

        if sized_order.direction == 'BOT':
            # LONG direction: sl lower
            sized_order.sl = bars.open.iloc[-1] - atr.iloc[-1] * sl_setting['multiplier']
        elif sized_order.direction == 'SLD':
            # SHORT direction: sl higher
            sized_order.sl  = bars.close.iloc[-1] + atr.iloc[-1] * sl_setting['multiplier']
        return sized_order


    def calculate_tp(self, sized_order, tp_setting, bars):
        """
        Define stopLoss level based on the ATR value.
        It is calculated on the open or close price of the bar,
        according to the direction of the trade.

        Parameters
        ----------
        sized_order:
            Sized order object
        window: `int`
            Lookback window for the ATR
        multiplier: `float`
            ATR multiplier
        """
        atr = ta.atr(bars.high, bars.low, bars.close, tp_setting['window'], mamode='rma', drift=1)

        if sized_order.direction == 'BOT':
            # LONG direction: tp higher
            sized_order.tp = bars.close.iloc[-1] + atr.iloc[-1] * tp_setting['multiplier']
        elif sized_order.direction == 'SLD':
            # SHORT direction: tp lower
            sized_order.tp = bars.open.iloc[-1] - atr.iloc[-1] * tp_setting['multiplier']
        return sized_order
