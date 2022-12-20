from .base import AbstractRiskManager
from ..order.orders import LimitOrder
from ..order.orders import StopOrder
from ..event import OrderEvent
from qstrader.price_parser import PriceParser

import sys

import logging
logger = logging.getLogger()

class StopLossRiskManager(AbstractRiskManager):
    """
        This RiskManager object calculate the StopLoss price
        of the sized order through, creates the corresponding
        OrderEvent object and adds it to a list.
        """

    def __init__(self, order_type = 'mkt', apply_sl=False, apply_tp=False, stop_level=0.003):
        self.order_type = order_type
        self.apply_sl = apply_sl
        self.apply_tp = apply_tp
        self.stop_level = stop_level  #Stop loss level: 5%
        self.order_id = 0

        logger.info('RISK MANAGER: Advanced Risk Manager => OK')


    def refine_orders(self, portfolio, sized_order):
        """
        Calculate the StopLoss level annd create a OrderEvent.
        """
        # Initialize market and limit order queue
        order_event, limit_order = [], []

        ### Check if enough cash in the portfolio
        if PriceParser.display(portfolio.cur_cash) < 30:
            logger.info('  RISK MANAGER: Not enough cash to trade')
            return order_event, limit_order

        ### Redifine order
        if self.order_type == 'limit':
            if sized_order.ticker not in portfolio.positions.keys():
                # check if it is a new order
                self.order_id += 1
                price = 1 #TODO: definire una regola per definire limit price

                lim_order = LimitOrder(
                    id = self.order_id,
                    ticker = sized_order.ticker,
                    status = 'active',
                    time = sized_order.time,
                    action = sized_order.action,
                    price = price,
                    quantity = sized_order.quantity
                )
            limit_order.append(lim_order)
        else:
            # Position already opened or market order
            # Send a market order directly into the events queue
            self.order_id += 1

            mkt_order_event = OrderEvent(
                sized_order.time,
                sized_order.ticker,
                sized_order.action,
                sized_order.quantity,
                price = self._get_order_price(portfolio.price_handler, sized_order)
            )
            order_event.append(mkt_order_event)
        logger.info('  RISK MANAGER: Order refined')

        ### Apply SL and TP
        if sized_order.ticker not in portfolio.positions.keys():
            # Check if the ticker already has an opened position

            if self.apply_sl:   # Calculate stop loss price
                self.order_id += 1
                stop_loss = self._calculate_sl(portfolio, sized_order)

                sl_order = StopOrder(
                    id = self.order_id,
                    ticker = sized_order.ticker,
                    status = 'active',
                    time = sized_order.time,
                    action = self._get_stop_order_direction(sized_order),
                    price = stop_loss,
                    quantity = sized_order.quantity
                )
                limit_order.append(sl_order)
                logger.info('  ORDER MANAGER: Stop loss order added: %s, %s', sl_order.ticker, PriceParser.display(sl_order.price))

            if self.apply_tp:   # Calculate take profit price
                self.order_id += 1
                take_profit = self._calculate_tp(portfolio, sized_order)

                tp_order = LimitOrder(
                    id = self.order_id,
                    ticker = sized_order.ticker,
                    status = 'active',
                    time = sized_order.time,
                    action = self._get_stop_order_direction(sized_order),
                    price = take_profit,
                    quantity = sized_order.quantity
                )
                limit_order.append(tp_order)
                logger.info('  ORDER MANAGER: Take profit order added: %s, %s', tp_order.ticker, PriceParser.display(tp_order.price))

        #logger.info('  RISK MANAGER: OK Proceed')
        return order_event, limit_order


    def _calculate_sl(self, portfolio, sized_order):
        last_close = portfolio.price_handler.get_last_close(sized_order.ticker)

        # Define stopLoss level (on the last close)
        if sized_order.action == 'BOT':
            #LONG direction: sl lower
            stop_loss = last_close * (1-self.stop_level)
        elif sized_order.action == 'SLD':
            #SHORT direction: sl higher
            stop_loss = last_close * (1+self.stop_level)
        #logger.info('  RISK MANAGER: Define StopLoss: %s',PriceParser.display(stop_loss))
        return stop_loss


    def _calculate_tp(self, portfolio, sized_order):
        last_close = portfolio.price_handler.get_last_close(sized_order.ticker)

        # Define takeProfit level (on the last close)
        if sized_order.action == 'BOT':
            #LONG direction: tp higher
            take_profit = last_close * (1+self.stop_level)
        elif sized_order.action == 'SLD':
            #SHORT direction: tp lower
            take_profit = last_close * (1-self.stop_level)
        #logger.info('  RISK MANAGER: Define StopLoss: %s',PriceParser.display(take_profit))
        return take_profit


    def _get_stop_order_direction(self, sized_order):
        if sized_order.action == 'BOT':
            action = 'SLD'
        else:
            action = 'BOT'
        return action
    
    def _get_order_price(self, price_handler, sized_order):
        # Obtain the order price
        if price_handler.istick():
            bid, ask = price_handler.get_best_bid_ask(sized_order.ticker)
            if sized_order.action == "BOT":
                fill_price = ask
            else:
                fill_price = bid
        else:
            close_price = price_handler.get_last_close(sized_order.ticker)
            fill_price = close_price
        return fill_price
        
