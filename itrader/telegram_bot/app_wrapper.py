import requests
import json
import threading
from flask import Response

from itrader.trading_system.backtest_trading_system import TradingSystem
from itrader.telegram_bot.telegram_bot import TelegramBot
from itrader.telegram_bot.responses import Responses

from itrader.strategy_handler.empty_strategy import Empty_strategy
from itrader.strategy_handler.scalping.VWAP_BB_RSI_scalping_strategy import VWAP_BB_RSI_scalping_strategy

from itrader.screeners_handler.screeners.most_performing import MostPerformingScreener
from itrader.screeners_handler.screeners.volume_spyke import VolumeSpykeScreener


from .const import TOKEN, URL, CHAT_ID

class FlaskAppWrapper(object):

    def __init__(self, app, **configs):
        self.app = app
        self.bot = TelegramBot(TOKEN, URL)
        self.trading_system = TradingSystem(exchange='binance', 
                                            universe = 'static',
                                            session_type='live')
        self.configs(**configs)
        self.initialise_endpoints()
        self.initialise_trading_system()


# Server commands
    def configs(self, **configs):
        for config, value in configs:
            self.app.config[config.upper()] = value

    def add_endpoint(self, endpoint=None, endpoint_name=None, handler=None, methods=['GET'], *args, **kwargs):
        self.app.add_url_rule(endpoint, endpoint_name, handler, methods=methods, *args, **kwargs)

    def initialise_trading_system(self):
        tickers = ['BTCUSDT']
        timeframe = '1h'
        frequency = '1h'

        ### Add screeners
        screener_volume = VolumeSpykeScreener(
            tickers,
            timeframe,
            window=10
        )
        screener = MostPerformingScreener(
            tickers,
            frequency,
            window=26
        )
        self.trading_system.add_screener(screener)  

        ### Add strategies
        strategy = Empty_strategy(timeframe='1m', tickers=tickers)
        strategy_setting = {
            'portfolio_id': '01',
            'timeframe': '1m',
            'max_allocation': 0.8,
            'max_positions': 1,
            'integer_size': False,
            'apply_sl': False,
            'apply_tp': False}
        self.trading_system.add_strategy(strategy, strategy_setting)
        return

    def initialise_endpoints(self):
        self.add_endpoint('/status', 'status', self.status, methods=['GET'])
        self.add_endpoint('/portfolios', 'portfolios', self.portfolios, methods=['GET'])
        self.add_endpoint('/positions', 'positions', self.positions, methods=['GET'])
        self.add_endpoint('/start_streaming', 'start_streaming', self.start_streaming, methods=['GET'])
    
    def run(self, **kwargs):
        self.app.run(**kwargs)


# App Commands
    def status(self):
        """
        Send informations about the global status of the trading system.
        """
        text = Responses.status(self.trading_system._is_running,
                                len(self.trading_system.screeners_handler.screeners),
                                len(self.trading_system.strategies_handler.strategies),
                                len(self.trading_system.engine.portfolio_handler.portfolios))
        self.bot.send_message(CHAT_ID, text)
        return Response('ok', status=200)
    
    def portfolios(self):
        """
        Send the main metrics of evry traded portfolio.
        """
        text = Responses.portfolios(self.trading_system.engine.portfolio_handler.portfolios)
        self.bot.send_message(CHAT_ID, text)
        return Response('ok', status=200)
    
    def positions(self):
        """
        Send all the open positions for every portfolio.
        """
        text = Responses.positions(self.trading_system.engine.portfolio_handler.get_positions_info())
        self.bot.send_message(CHAT_ID, text)
        return Response('ok', status=200)
    
    def start_streaming(self):
        """
        Start the system.
        """
        if not self.trading_system._is_running:
            ts_thread = threading.Thread(target=self.trading_system.start)
            ts_thread.start()
            self.bot.send_message(CHAT_ID, 'System started')
        else:
            self.bot.send_message(CHAT_ID, 'The system is already running')
        return Response('ok', status=200)
    
    def statistics(self):
        return
    
    def pause(self):
        return
    
    def reboot(self):
        return




# Responses
    def get_response(self, input_text):
        """
        Responses for the Telegram bot webhook
        """
        user_message= str(input_text)
        if user_message in ('/status'):
            response = requests.get(URL+'/status')
        elif user_message in ('/portfolios'):
            response = requests.get(URL+'/portfolios')
        elif user_message in ('/positions'):
            response = requests.get(URL+'/positions')
        elif user_message in ('/start_streaming'):
            response = requests.get(URL+'/start_streaming')
        else:
            self.bot.send_message(CHAT_ID, 'Command not implemented')
            return('Command not implemented')