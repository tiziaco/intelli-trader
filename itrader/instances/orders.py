from enum import Enum

from itrader.events_handler.event import SignalEvent

OrderType = Enum("OrderType", "MARKET STOP LIMIT")
type_mapping = {
    "MARKET": OrderType.MARKET,
    "STOP": OrderType.STOP,
    "LIMIT": OrderType.LIMIT
}

class OrderEvent(object):
    """
    An Order object is generated by the OrderHandler in respons to
    a signal event who has been validated by the the PositionSizer 
    and RiskManager object.

    It is then sent to the ExecutionHandler who send the order
    to the exchange.
    """
    def __init__(
        self,
        time: str,   #TODO da definire
        type: OrderType, 
        ticker: str, 
        side: str, 
        action: str, 
        price: float,
        quantity: float, 
        stop_loss: float, 
        take_profit: float, 
        strategy_id: int, 
        portfolio_id: int
    ):
        self.time = time
        self.type = type
        self.ticker = ticker
        self.side = side
        self.action = action
        self.price = price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id
    
    def __str__(self):
        return f"Order-{self.type.value} ({self.ticker}, {self.action}, {self.quantity})"

    def __repr__(self):
        return str(self)
    
    @classmethod
    def new_order(cls, type: str, signal: SignalEvent):
        """
        Generate a new Order object with the specified type.

        Parameters
        ----------
        type (OrderType): The type of the order to be generated.
            Supported types:
                - MARKET: A market order.
                - STOP: A stop order.
                - LIMIT: A limit order.

        Returns
        -------
        Order: A new Order object with the specified type.
        """

        order_type = type_mapping.get(type)
        if order_type is None:
            raise ValueError('Value %s not supported', type)
        return cls(
            signal.time,
            OrderType.MARKET,
            signal.ticker,
            signal.side,
            signal.action,
            signal.price,
            None,       #da verificare
            signal.stop_loss,
            signal.take_profit,
            signal.strategy_id,
            signal.portfolio_id
        )
