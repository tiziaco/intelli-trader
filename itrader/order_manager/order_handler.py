from .order_base import OrderBase
from ..outils.price_parser import PriceParser

from .position_sizer.variable_sizer import DynamicSizer
from .risk_manager.advanced_risk_manager import RiskManager

from ..instances.event import OrderEvent
from ..instances.orders import *

import logging
logger = logging.getLogger()



class OrderHandler(OrderBase):
    """
    The OrderHandler class manage the signal event coming from the 
    strategy class.

    It transforms the Signal event in a Suggested order, then send it
    to te Risk Manager (cash check, calculate sl and tp) and finally
    calculate the position size with the Position Sizer

    It is able to manage stop and limit order and it has a pending 
    order queue for active and inactive orders.

    When an order is filled it is sended to the execution handler

    Parameters
    ----------
    events_queue : `Queue object`
        The events queue of the trading system
    portfolio_handler : `PortfolioHandler object`
        The portfolio handler queue of the trading system
    type : `str`
        Order type ('market' or 'limit')
    apply_sl: `boolean`
        Define if apply the stop loss
    apply_tp: `boolean`
        Define if apply the take profit
    portfolio_handler: `portfolio_handle object`
        The portfolio handler used in the td

    """
    def __init__(self, events_queue, portfolio_handler, 
        type='market', 
        integer_size = False, max_allocation = 0.8, 
        apply_sl = False, apply_tp = False):
        super().__init__(events_queue, portfolio_handler)
        self.type = type
        self.position_sizer = DynamicSizer(integer_size, max_allocation)
        self.risk_manager = RiskManager(apply_sl, apply_tp)
        self.pending_orders = []
        self.inactive_orders = []
        self.order_id = 0


    def check_pending_orders(self, event):
        """
        Check the activation conditions of the orders in the
        pending orders list.
        """
        if self.pending_orders != []:
            for order in self.pending_orders:
                last_close = event.price #TODO: non va bene!! da modificare bar event

                if order.type == OrderType.STOP:
                    if order.action == 'SLD':
                        if last_close < order.price: # SL of a long position
                            logger.info('  ORDER MANAGER: Stop Loss reached: %s',order.ticker)
                            self._send_event_order(order)
                            self.remove_orders(order.ticker)

                    elif order.action == 'BOT':
                        if last_close > order.price: # SL of a short position
                            logger.info('  ORDER MANAGER: Stop Loss reached: %s',order.ticker)
                            self._send_event_order(order)
                            self.remove_orders(order.ticker)

                elif order.type == OrderType.LIMIT:
                    if order.action == 'SLD':
                        if last_close > order.price: # TP of a long position
                            logger.info('  ORDER MANAGER: Limit order filled: %s',order.ticker)
                            self._send_event_order(order)
                            self.remove_orders(order.ticker)

                    elif order.action == 'BOT':
                        if last_close < order.price: # TP of a short position
                            logger.info('  ORDER MANAGER: Limit order filled: %s',order.ticker)
                            self._send_event_order(order)
                            self.remove_orders(order.ticker)

    
    def on_signal(self, signal_event):
        """
        This is called by the backtester or live trading architecture
        to process the initial orders from the SignalEvent.

        These orders are sized by the PositionSizer object and then
        sent to the RiskManager to verify, modify or eliminate it.

        Once received from the RiskManager they are converted into
        full OrderEvent objects and sent back to the events queue.
        """
        # Create the initial order list from a signal event
        initial_order = self._create_order_from_signal(signal_event)

        # Size the quantity of the initial order with PositionSizer
        sized_order = self.position_sizer.size_order(initial_order)

        # Validate or eliminate the order via the risk manager overlay
        validated_order = self.risk_manager.refine_orders(sized_order)
        
        if validated_order is not None:
            self._apply_sl_tp()
            self._send_event_order(validated_order)

    

    
    def _apply_sl_tp(self, sized_order):
        """
        Add sl and tp orders to the pending_orders list
        """
        if sized_order.sl > 0:   # Calculate stop loss price
            self._add_stop_loss_order(sized_order)

        if sized_order.tp > 0:   # Calculate take profit price
            self._add_take_profit_order(sized_order)


    def _create_order_from_signal(self, signal_event):
        """
        Take a SignalEvent object and use it to form a
        SuggestedOrder object. These are not OrderEvent objects,
        as they have yet to be sent to the RiskManager object.
        At this stage they are simply "suggestions" that the
        RiskManager will either verify, modify or eliminate.
        """
        order = SuggestedOrder(
            signal_event.time,
            self.type,
            signal_event.ticker,
            signal_event.action,
            signal_event.price)
        return order
    

    def _add_stop_loss_order(self, sized_order):
        """
        Add a stop order in the pending order queue
        """
        self._generate_id()

        sl_order = StopOrder(
            id = self.order_id,
            ticker = sized_order.ticker,
            status = 'active',
            time = sized_order.time,
            action = self._get_stop_order_direction(sized_order),
            price = sized_order.sl,
            quantity = sized_order.quantity)

        self.add_new_order(sl_order)
        logger.info('  ORDER MANAGER: Stop loss order added: %s, %s', sl_order.ticker, PriceParser.display(sl_order.price))


    def _add_take_profit_order(self, sized_order):
        """
        Add a limit order in the pending order queue
        """
        self._generate_id()

        tp_order = LimitOrder(
            id = self.order_id,
            ticker = sized_order.ticker,
            status = 'active',
            time = sized_order.time,
            action = self._get_stop_order_direction(sized_order),
            price = sized_order.tp,
            quantity = sized_order.quantity)

        self.add_new_order(tp_order)
        logger.info('  ORDER MANAGER: Take profit order added: %s, %s', tp_order.ticker, PriceParser.display(tp_order.price))


    def _send_event_order(self, order):
        """
        When a stop/limit order is filled or whe a market order is set,
        create an order event to be added to the global events que. 

        Later this order will be treated by the execution handler.
        """
        order_event= OrderEvent(
            order.time,
            order.ticker,
            order.action,
            order.quantity,
            order.price
            )
        self.events_queue.put(order_event)


    
    def _get_stop_order_direction(self, sized_order):
        """
        Get direction for the stop/limit order according to the
        position's action
        """
        if sized_order.action == 'BOT':
            action = 'SLD'
        else:
            action = 'BOT'
        return action

    def _generate_id(self):
        """
        Generate an ID for the order
        """
        self.order_id += 1
    
    def _update_portfolio_info(self):
        #TODO : da implementare
        # self.open_positions = self.portfolio_handler.get_open_positions(portfolio_id)
        # self.cash = self.portfolio_handler.get_cash(portfolio_id)
        pass

    def add_new_order(self, limit_order):
        """
        Add new stop or limit order after the suggested order has been 
        refined by the risk manager
        """
        self.pending_orders.append(limit_order)
    
    def remove_orders(self, ticker):
        """
        Remove all the pending orders with the same ticker of the
        order who has been filled 
        """
        for order in self.pending_orders:
            if (order.ticker == ticker): # and (order.status =='active')
                self.pending_orders.remove(order)
    
    def modify_order(self, ticker):
        """
        Modify the filling price of an opened Stop or Limit order
        Usefull for trailing stops (da implementare)
        """
        # TODO: da implementare
        return

    

