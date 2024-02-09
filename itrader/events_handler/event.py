from enum import Enum

EventType = Enum("EventType", "PING BAR SIGNAL ORDER FILL")
type_mapping = {
    "PING": EventType.MARKET,
    "BAR": EventType.LIMIT,
    "SIGNAL": EventType.FILLED,
    "ORDER": EventType.CANCELLED,
    "FILL": EventType.FILL
}


class PingEvent(object):
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


class BarEvent(object):
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


class SignalEvent(object):
    """
     Signal event generated from a Strategy object.
    This is received by the Order handler object that validate and
    send the order to the Execution handler object.

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
    def __init__(
        self, 
        time: str, 
        ticker: str, 
        side: str, 
        action: str, 
        price: float,
        stop_loss: float, 
        take_profit: float,
        strategy_id: int,
        portfolio_id: int
    ):
        self.type = EventType.SIGNAL
        self.time = time
        self.ticker = ticker
        self.side = side
        self.action = action
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id
    
    def __str__(self):
        return f"{self.type.value} ({self.ticker}, {self.side}, {self.action}, \
            {round(self.price, 4)} $)"

    def __repr__(self):
        return str(self)


class FillEvent(object):
    """
    Encapsulates the notion of a filled order, as returned
    from the ExecutionHandler in response to an executed order. 
    Stores the price and quantity and commission confirmed by 
    the exchange.

    Parameters
    ----------
    time: `timestamp`
        Event time
    ticker: `str`
        The ticker symbol, e.g. 'BTCUSD'.
    side:
        'LONG' or 'SHORT'
    action: `str`
        'BOT' (for long) or 'SLD' (for short)
    quantity: `float`
        Quantity transacted
    exchange: `str`
        The exchange where to transact, e.g. 'binance'.
    portfolio_id: `str`
        Poertfolio id where transact the position
    price: `float`
        Last close price for the instrument
    commission: `float`
        Transaction fee
    """

    def __init__(
        self, 
        time, 
        ticker, 
        side,
        action, 
        quantity,
        price,
        commission,
        exchange, 
        portfolio_id  
    ):
        self.type = EventType.FILL
        self.time = time
        self.ticker = ticker
        self.side = side
        self.action = action
        self.quantity = quantity
        self.price = price
        self.commission = commission
        self.exchange = exchange
        self.portfolio_id = portfolio_id

    def __str__(self):
        return f"{self.type.value} ({self.ticker}, {self.side}, {self.action}, \
            {round(self.quantity, 4)}, {round(self.price, 4)} $)"

    def __repr__(self):
        return str(self)
