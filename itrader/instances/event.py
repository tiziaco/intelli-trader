from __future__ import print_function

from ..outils.price_parser import PriceParser
from enum import Enum
import logging
logger = logging.getLogger()

EventType = Enum("EventType", "PING TICK BAR SIGNAL ORDER FILL SENTIMENT")


class Event(object):
    """
    Event is base class providing an interface for all subsequent
    (inherited) events, that will trigger further events in the
    trading infrastructure.
    """
    @property
    def typename(self):
        return self.type.name

class PingEvent(Event):
    """
    Handles the event of receiving a new market update tick,
    which is defined as a ticker symbol and associated best
    bid and ask from the top of the order book.
    """
    def __init__(self, time):
        """
        Initialises the TickEvent.

        Parameters:
        time - The timestamp of the ping
        """
        self.type = EventType.PING
        self.time = time

    def __str__(self):
        return "Type: %s, Time: %s" % (
            str(self.type), str(self.time)
        )

    def __repr__(self):
        return str(self)

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
    def __init__(self, time):
        """
        Initialises the BarEvent.

        Parameters:
        time - The timestamp of the bar
        """
        self.type = EventType.BAR
        self.time = time
        self.bars = {}
    
        #logger.debug('PING Event: %s', self.time)

    def __str__(self):
        return "Type: %s, Time: %s" % (
            str(self.type),
            str(self.time)
        )

    def __repr__(self):
        return str(self)


class SignalEvent(Event):
    """
    Handles the Signal event from a Strategy object.
    This is received by the Order handler object that validate and
    send the order to the Execution handler object.
    """
    def __init__(self, time, ticker, direction, action, price, strategy_id):
        """
        Initialises the SignalEvent.

        Parameters
        ----------
        time: `timestamp`
            Event time
        ticker: `str`
            The ticker symbol, e.g. 'BTCUSD'.
        direction: `str`
            Direction of the position.
            'BOT' (for long) or 'SLD' (for short)
        action: `str`
            'ENTRY' (for long) or 'EXIT' (for short)
        price: `float`
            Last close price for the instrument
        strategy_id: `str`
            The ID of the strategy who generated the signal
        """
        self.type = EventType.SIGNAL
        self.time = time
        self.ticker = ticker
        self.direction = direction
        self.action = action
        self.price = price
        self.strategy_id = strategy_id
        self.portfolio_id = None # TODO: da implementare
    
    def __str__(self):
        return "Type: %s, Ticker: %s, Time: %s, Action: %s %s, Price: %s" % (
            str(self.type), str(self.ticker),
            str(self.time), str(self.direction), str(self.action), str(self.price)
        )

    def __repr__(self):
        return str(self)



class OrderEvent(Event):
    """
    Handles the event of sending an Order to an execution system.
    The order contains a ticker (e.g. GOOG), action (BOT or SLD)
    and quantity.
    """
    def __init__(self, time, order_type, ticker, direction, action, quantity, price, portfolio_id, sl=0, tp=0):
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
        portfolio_id: `str`
            Portfolio where to execute the transaction
        sl: `float`
            Suggested stop loss price
        tp: `float` 
            Suggested take profit price
        """
        self.type = EventType.ORDER
        self.time = time
        self.order_type = order_type
        self.ticker = ticker
        self.direction = direction
        self.action = action
        self.quantity = quantity
        self.price = price
        self.portfolio_id = portfolio_id
        self.sl = sl
        self.tp = tp

    def __str__(self):
        return "Type: %s, Ticker: %s, Time: %s, Action: %s %s, Quantity: %s, Price: %s" % (
            str(self.type), str(self.ticker), str(self.time),
            str(self.direction), str(self.action), str(self.quantity), str(self.price)
        )

    def __repr__(self):
        return str(self)




class FillEvent(Event):
    """
    Encapsulates the notion of a filled order, as returned
    from a brokerage. Stores the quantity of an instrument
    actually filled and at what price. In addition, stores
    the commission of the trade from the brokerage.
    """

    def __init__(
        self, time, ticker, direction,
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
        direction:

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
        self.time = time
        self.ticker = ticker
        self.direction = direction
        self.action = action
        self.quantity = quantity
        self.exchange = exchange
        self.portfolio_id = portfolio_id
        self.price = price
        self.commission = commission

    def __str__(self):
        return "Type: %s, Ticker: %s, Time: %s, Action: %s %s, Quantity: %s, Price: %s" % (
            str(self.type), str(self.ticker), str(self.time),
            str(self.direction), str(self.action), str(self.quantity), str(self.price)
        )

    def __repr__(self):
        return str(self)


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
