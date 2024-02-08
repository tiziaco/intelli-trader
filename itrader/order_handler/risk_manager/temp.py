"""
temporaneo. probabilmente utile in execution handler
"""
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
                # da aggiungere qui il tipo ordine 'mkt' o 'limit'
                # 
                sized_order.time,
                sized_order.ticker,
                sized_order.action,
                sized_order.quantity,
                price = self._get_order_price(portfolio.price_handler, sized_order)
            )
            order_event.append(mkt_order_event)