

class Responses():
    def status(system, screeners, strategies, portfolios):
        text = """
        -- System status --
        Active: %s
        Screeners: %s
        Strategies: %s
        Portfolios: %s
        """%(system, screeners, strategies, portfolios)
        return text
    
    def portfolios(portfolios):
        text = '-- Portfolios --'
        for id, portfolio in portfolios.items():
            por = """
        ID: %s
        Cash: %s
        Opened pos: %s

            """%(id, portfolio.cash, len(portfolio.pos_handler.positions))
            text += por
        return text
    
    def positions(portfolios, indent='  '):
        text = f'-- Open Positions --\n'
        for portfolio, positions in portfolio.items():
            if portfolio:
                text += f'Portfolio: {portfolio}\n'
                if positions:
                    for ticker, position in positions.items():
                        # BTCUSDT - BUY, 100.0$ 
                        text += f'{indent}{ticker} - {position["action"]}, {round(position["unrealised_pnl"], 2)}$ \n'
                else:
                    text += f'{indent}No positions\n'  # Add string when positions dictionary is empty
            else:
                text += 'No portfolio presents'
        return text