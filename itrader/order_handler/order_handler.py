from .order_base import OrderBase
from ..outils.price_parser import PriceParser

from .compliance_manager.basic_compliance_manager import BasicComplianceManager
from .position_sizer.variable_sizer import DynamicSizer
from .risk_manager.advanced_risk_manager import RiskManager

from ..events_handler.event import OrderEvent, SignalEvent
from ..instances.orders import *

import logging
logger = logging.getLogger('TradingSystem')

from datetime import timedelta



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
    """
    def __init__(self, events_queue, portfolio_handler, price_handler,
        type='market',
        integer_size = False):
        """
        Parameters
        ----------
        events_queue: `Queue object`
            The events queue of the trading system
        portfolio_handler: `PortfolioHandler object`
            The portfolio handler queue of the trading system
        type: `str`
            Order type ('market' or 'limit')
        integer_size: `boolean`
            Calculate the position as an integer value
        """

        super(OrderHandler, self).__init__(events_queue, portfolio_handler)
        self.type = type
        logger.info('ORDER HANDLER: Default => OK')
        self.compliance = BasicComplianceManager()
        self.position_sizer = DynamicSizer(integer_size)
        self.risk_manager = RiskManager(price_handler)
        
        self.pending_orders = {}
        self.order_id = 0


    def check_pending_orders(self, bar_event):
        """
        Check the activation conditions of the limit orders in 
        the pending orders list.

        Parameters
        ----------
        bar_event : `Bar object`
            The bar event generated from the Universe module
        """
        if bool(self.pending_orders):
            for portfolio_id, pd_orders in list(self.pending_orders.items()):
                for order_id, order in list(pd_orders.items()):
                    last_close = bar_event.bars[order.ticker]['close']

                    if order.type == OrderType.STOP:
                        if order.direction == 'SLD':
                            if last_close < order.price: # SL of a long position
                                logger.info('  ORDER MANAGER: Stop Loss order filled: %s',order.ticker)
                                order.time = bar_event.time
                                self._send_event_order(order)
                                self.remove_orders(order.ticker, order.portfolio_id)

                        elif order.direction == 'BOT':
                            if last_close > order.price: # SL of a short position
                                logger.info('  ORDER MANAGER: Stop Loss filled: %s',order.ticker)
                                order.time = bar_event.time
                                self._send_event_order(order)
                                self.remove_orders(order.ticker, order.portfolio_id)

                    elif order.type == OrderType.LIMIT:
                        if order.direction == 'SLD':
                            if last_close > order.price: # TP of a long position
                                logger.info('  ORDER MANAGER: Limit order filled: %s',order.ticker)
                                order.time = bar_event.time
                                self._send_event_order(order)
                                self.remove_orders(order.ticker, order.portfolio_id)

                        elif order.direction == 'BOT':
                            if last_close < order.price: # TP of a short position
                                logger.info('  ORDER MANAGER: Limit order filled: %s',order.ticker)
                                order.time = bar_event.time
                                self._send_event_order(order)
                                self.remove_orders(order.ticker, order.portfolio_id)
    


    def check_max_duration(self, bar_event, max_duration= timedelta(days=2)):
        self._update_portfolio_data()
        for portfolio_id, positions in self.open_positions.items():
            for ticker, position in positions.items():
                duration = bar_event.time - position['entry_time']
                if duration > max_duration:
                    # TODO : vedere se riesco a fare tutto direttamente con orderEvent
            #         suggested_order = SuggestedOrder( 
            #             time = bar_event.time,
            #             type = self.type,
            #             ticker = ticker,
            #             direction = self._get_stop_order_direction(position.action),
            #             action = 'EXIT',
            #             price= bar_event.bars[ticker]['close'],
            #             strategy_id='',
            #             portfolio_id=portfolio_id
            # )
                    signal = SignalEvent(
                        time=bar_event.time,
                        ticker=ticker, 
                        direction = self._get_stop_order_direction(position['action']),
                        action = 'EXIT',
                        price=bar_event.bars[ticker]['close'],
                        strategy_id='ZscorePairs_strategy1h'     # TODO: da parametrizzare            
                    )
                    self.events_queue.put(signal)

                    logger.info('ORDER HANDLER: Max duration reached for for %s => %s %s, %s$', 
                    signal.ticker, signal.direction, signal.action, round(signal.price,4))
    
    def _delete_pending_orders(self, validated_order):
        # Check if I am closing a position
        if validated_order.action != 'EXIT':
            return
        # Check if I have pending limit order 
        if not bool(self.pending_orders):
            return
        
        self._update_portfolio_data()
        pd_orders = self.pending_orders[validated_order.portfolio_id]
        for order_id, order in list(pd_orders.items()):
            # Check if the position is definitively closed
            if order.ticker not in self.open_positions[validated_order.portfolio_id]:
                self.remove_orders(order.ticker, validated_order.portfolio_id)

    
    def on_signal(self, signal_event):
        """
        This is called by the backtester or live trading architecture
        to process the initial orders from the SignalEvent.

        These orders are sized by the PositionSizer object and then
        sent to the RiskManager to verify, modify or eliminate it.

        Once received from the RiskManager they are converted into
        full OrderEvent objects and sent back to the events queue.

        Parameters
        ----------
        signal_event : `Signal object`
            The signal event generated from the strategy module
        """
        logger.info('ORDER HANDLER: processing the signal for %s => %s %s, %s$', 
                    signal_event.ticker, signal_event.direction, signal_event.action, round(signal_event.price,4))
        # Initialize portfolio data
        self._update_portfolio_data() #TODO: da aggiungere action e quantity OK

        # Create the initial order list from a signal event
        initial_order = self._create_order_from_signal(signal_event)

        # Check the compliance to the defined rules
        if initial_order is not None:
            verified_order = self.compliance.check_compliance(initial_order)
        else: return

        # Size the quantity of the initial order with PositionSizer
        if verified_order is not None:
            sized_order = self.position_sizer.size_order(verified_order)
        else: return

        # Validate or eliminate the order via the risk manager overlay
        if sized_order is not None:
            validated_order = self.risk_manager.refine_orders(sized_order)
        else: return
        
        if validated_order is not None:
            self._apply_sl_tp(validated_order)
            self._send_event_order(validated_order)
            self._delete_pending_orders(validated_order)
    

    
    def _apply_sl_tp(self, validated_order):
        """
        Add sl and tp orders to the pending_orders list
        """
        if validated_order.sl > 0:   # Calculate stop loss price
            self._add_stop_loss_order(validated_order)

        if validated_order.tp > 0:   # Calculate take profit price
            self._add_take_profit_order(validated_order)


    def _create_order_from_signal(self, signal_event):
        """
        Take a SignalEvent object and use it to form a
        SuggestedOrder object. These are not OrderEvent objects,
        as they have yet to be sent to the RiskManager object.
        At this stage they are simply "suggestions" that the
        RiskManager will either verify, modify or eliminate.

        Parameters
        ----------
        signal_event: `Signal object`
            The signal event generated from the strategy module
        """
        suggested_order = SuggestedOrder(
            time = signal_event.time,
            type = self.type,
            ticker = signal_event.ticker,
            direction = signal_event.direction,
            action= signal_event.action,
            price= signal_event.price,
            strategy_id=signal_event.strategy_id,
            portfolio_id=OrderBase.strategies_setting[signal_event.strategy_id]['portfolio_id']
            )
        return suggested_order
    
    def add_new_order(self, limit_order):
        """
        Add new stop or limit order after the suggested order has been 
        refined by the risk manager.

        Parameters
        ----------
        limit_order: `LimitOrder object`
            The stop/limit order object for a specific ticker
        """
        self.pending_orders.setdefault(limit_order.portfolio_id, {}).setdefault(limit_order.order_id, limit_order)
    
    def remove_orders(self, ticker, portfolio_id):
        """
        Remove all the pending orders with the same ticker of the
        order who has been filled

        Parameters
        ----------
        ticker: `str`
            The ticker of the order to be removed
        """
        pd_orders = self.pending_orders[portfolio_id]
        for order_id, order in list(pd_orders.items()):
            if order.ticker == ticker:
                logger.debug('  ORDER MANAGER: Pending order %s, %s removed',
                    order.direction, ticker)
                del self.pending_orders[portfolio_id][order_id]
    
    def modify_order(self, ticker):
        """
        Modify the filling price of an opened Stop or Limit order
        Usefull for trailing stops.

        Parameters
        ----------
        ticker: `str`
            The ticker of the order to be modified
        """
        # TODO: da implementare
        return


    def _add_stop_loss_order(self, sized_order):
        """
        Add a stop order in the pending order queue

        Parameters
        ----------
        sized_order: `Order object`
            The sized order generated from the position sizer module
        """
        self._generate_id()

        sl_order = StopOrder(
            order_id = self.order_id,
            portfolio_id= sized_order.portfolio_id,
            ticker = sized_order.ticker,
            status = 'active',
            time = sized_order.time,
            direction = self._get_stop_order_direction(sized_order.direction),
            action = self._get_stop_order_action(sized_order.action),
            price = sized_order.sl,
            quantity = sized_order.quantity)
        self.add_new_order(sl_order)
        logger.info('  ORDER MANAGER: Stop loss order added: %s, %s $', sl_order.ticker, sl_order.price) #PriceParser.display(sl_order.price)


    def _add_take_profit_order(self, sized_order):
        """
        Add a limit order in the pending order queue

        Parameters
        ----------
        sized_order: `Order object`
            The sized order generated from the position sizer module
        """
        self._generate_id()

        tp_order = LimitOrder(
            order_id = self.order_id,
            portfolio_id= sized_order.portfolio_id,
            ticker = sized_order.ticker,
            status = 'active',
            time = sized_order.time,
            direction = self._get_stop_order_direction(sized_order.direction),
            action = self._get_stop_order_action(sized_order.action),
            price = sized_order.tp,
            quantity = sized_order.quantity)
        self.add_new_order(tp_order)
        logger.info('  ORDER MANAGER: Take profit order added: %s, %s $', tp_order.ticker, tp_order.price) #PriceParser.display(tp_order.price))

    def _send_event_order(self, order):
        """
        When a stop/limit order is filled or when a market order is set,
        create an order event to be added to the global events que. 

        Later this order will be treated by the execution handler.
        """
        
        order_event= OrderEvent(
            time= order.time,
            order_type= order.type,
            ticker= order.ticker,
            direction= order.direction,
            action= order.action,
            quantity= order.quantity,
            price= order.price,
            portfolio_id= order.portfolio_id
            )
        self.events_queue.put(order_event)
        logger.debug('  ORDER MANAGER: order sended to the execution handler')

    def _get_stop_order_direction(self, direction):
        """
        Get direction for the stop/limit order according to the
        position's action
        """
        if direction == 'BOT':
            return str('SLD')
        elif direction == 'SLD':
            return str('BOT')
        else:
            raise ValueError('Value %s not supported', direction)

    def _get_stop_order_action(self, action):
        """
        Get direction for the stop/limit order according to the
        position's action
        """
        if action == 'ENTRY':
            return 'EXIT'
        else:
            raise ValueError('Value %s not supported', action)

    def _generate_id(self):
        """
        Generate an ID for the order
        """
        self.order_id += 1