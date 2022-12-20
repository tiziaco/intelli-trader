from __future__ import print_function

from ..outils.price_parser import PriceParser
from enum import Enum
import logging
logger = logging.getLogger()

EventType = Enum("EventType", "TICK BAR SIGNAL ORDER FILL SENTIMENT")


class Event(object):
    """
    Event is base class providing an interface for all subsequent
    (inherited) events, that will trigger further events in the
    trading infrastructure.
    """
    @property
    def typename(self):
        return self.type.name


class TickEvent(Event):
    """
    Handles the event of receiving a new market update tick,
    which is defined as a ticker symbol and associated best
    bid and ask from the top of the order book.
    """
    def __init__(self, ticker, time, bid, ask):
        """
        Initialises the TickEvent.

        Parameters:
        ticker - The ticker symbol, e.g. 'GOOG'.
        time - The timestamp of the tick
        bid - The best bid price at the time of the tick.
        ask - The best ask price at the time of the tick.
        """
        self.type = EventType.TICK
        self.ticker = ticker
        self.time = time
        self.bid = bid
        self.ask = ask

    def __str__(self):
        return "Type: %s, Ticker: %s, Time: %s, Bid: %s, Ask: %s" % (
            str(self.type), str(self.ticker),
            str(self.time), str(self.bid), str(self.ask)
        )

    def __repr__(self):
        return str(self)


class BarEvent(Event):
    """
    Handles the event of receiving a new market
    open-high-low-close-volume bar, as would be generated
    via common data providers such as Yahoo Finance.
    """
    def __init__(
        self, ticker, time, period,
        open_price, high_price, low_price,
        close_price, volume, adj_close_price=None
    ):
        """
        Initialises the BarEvent.

        Parameters:
        ticker - The ticker symbol, e.g. 'GOOG'.
        time - The timestamp of the bar
        period - The time period covered by the bar in seconds
        open_price - The unadjusted opening price of the bar
        high_price - The unadjusted high price of the bar
        low_price - The unadjusted low price of the bar
        close_price - The unadjusted close price of the bar
        volume - The volume of trading within the bar
        adj_close_price - The vendor adjusted closing price
            (e.g. back-adjustment) of the bar
        """
        self.type = EventType.BAR
        self.ticker = ticker
        self.time = time
        self.period = period
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price
        self.volume = volume
        self.adj_close_price = adj_close_price
        self.period_readable = self._readable_period()
    
        logger.debug('BAR Event: %s - %s', self.ticker, self.time)

    def _readable_period(self):
        """
        Creates a human-readable period from the number
        of seconds specified for 'period'.

        For instance, converts:
        * 1 -> '1sec'
        * 5 -> '5secs'
        * 60 -> '1min'
        * 300 -> '5min'

        If no period is found in the lookup table, the human
        readable period is simply passed through from period,
        in seconds.
        """
        lut = {
            1: "1sec",
            5: "5sec",
            10: "10sec",
            15: "15sec",
            30: "30sec",
            60: "1min",
            300: "5min",
            600: "10min",
            900: "15min",
            1800: "30min",
            3600: "1hr",
            86400: "1day",
            604800: "1wk"
        }
        if self.period in lut:
            return lut[self.period]
        else:
            return "%ssec" % str(self.period)

    def __str__(self):
        format_str = "Type: %s, Ticker: %s, Time: %s, Period: %s, " \
            "Open: %s, High: %s, Low: %s, Close: %s, " \
            "Adj Close: %s, Volume: %s" % (
                str(self.type), str(self.ticker), str(self.time),
                str(self.period_readable), str(self.open_price),
                str(self.high_price), str(self.low_price),
                str(self.close_price), str(self.adj_close_price),
                str(self.volume)
            )
        return format_str

    def __repr__(self):
        return str(self)


class SignalEvent(Event):
    """
    Handles the Signal event from a Strategy object.
    This is received by the Order handler object that validate and
    send the order to the Execution handler object.
    """
    def __init__(self, time, ticker, action, price):
        """
        Initialises the SignalEvent.

        Parameters
        ----------
        time: `timestamp`
            Event time
        ticker: `str`
            The ticker symbol, e.g. 'BTCUSD'.
        action: `str`
            'BOT' (for long) or 'SLD' (for short)
        price: `float`
            Last close price for the instrument
        """
        self.type = EventType.SIGNAL
        self.time = time
        self.ticker = ticker
        self.action = action
        self.price = price

        # logger.debug('  Signal Event: %s, %s, Suggested qnt: %s', 
        #             self.ticker, self.action, PriceParser.display(self.suggested_quantity))



class OrderEvent(Event):
    """
    Handles the event of sending an Order to an execution system.
    The order contains a ticker (e.g. GOOG), action (BOT or SLD)
    and quantity.
    """
    def __init__(self, time, order_type, ticker, action, quantity, price, sl=0, tp=0):
        """
        Initialises the OrderEvent.

        Parameters:
        time: `timestamp`
            Validation time
        order_type: `str`
            Order type, e.g. 'market', 'stop', 'limit'
        ticker: `str`
            The ticker symbol, e.g. 'BTCUSD'.
        action: `str`
            'BOT' (for long) or 'SLD' (for short)
        quantity: `float`
            Quantity to transact
        price: `float`
            Last close price for the instrument
        sl: `float`
            Suggested stop loss price
        tp: `float` 
            Suggested take profit price
        """
        self.type = EventType.ORDER
        self.time = time
        self.order_type = order_type
        self.ticker = ticker
        self.action = action
        self.quantity = quantity
        self.price = price
        self.sl = sl
        self.tp = tp

        logger.info('  Order Event: %s, %s, Quantity: %s', 
                    self.ticker, self.action, PriceParser.display(self.quantity))



class FillEvent(Event):
    """
    Encapsulates the notion of a filled order, as returned
    from a brokerage. Stores the quantity of an instrument
    actually filled and at what price. In addition, stores
    the commission of the trade from the brokerage.

    TODO: Currently does not support filling positions at
    different prices. This will be simulated by averaging
    the cost.
    """

    def __init__(
        self, timestamp, ticker,
        action, quantity,
        exchange, portfolio_id,
        price, commission 
    ):
        """
        Initialises the FillEvent object.

        Parameters
        ----------
        time: `timestamp`
            Event time
        ticker: `str`
            The ticker symbol, e.g. 'BTCUSD'.
        action: `str`
            'BOT' (for long) or 'SLD' (for short)
        quantity: `float`
            Quantity to transact
        exchange: `str`
            The exchange where to transact, e.g. 'binance'.
        portfolio_id: `str`
            Poertfolio id where transact the position
        price: `float`
            Last close price for the instrument
        commission: `float`
            Transaction fee
        """
        self.type = EventType.FILL
        self.timestamp = timestamp
        self.ticker = ticker
        self.action = action
        self.quantity = quantity
        self.exchange = exchange
        self.portfolio_id = portfolio_id
        self.price = price
        self.commission = commission

        logger.info('  Fill Event: %s, %s, Quantity: %s $%s, Size: %s $', 
                    self.ticker, self.action, PriceParser.display(self.quantity,4), 
                    PriceParser.display(self.price), 
                    (PriceParser.display(self.price*self.quantity)))


class SentimentEvent(Event):
    """
    Handles the event of streaming a "Sentiment" value associated
    with a ticker. Can be used for a generic "date-ticker-sentiment"
    service, often provided by many data vendors.
    """
    def __init__(self, timestamp, ticker, sentiment):
        """
        Initialises the SentimentEvent.

        Parameters:
        timestamp - The timestamp when the sentiment was generated.
        ticker - The ticker symbol, e.g. 'GOOG'.
        sentiment - A string, float or integer value of "sentiment",
            e.g. "bullish", -1, 5.4, etc.
        """
        self.type = EventType.SENTIMENT
        self.timestamp = timestamp
        self.ticker = ticker
        self.sentiment = sentiment
