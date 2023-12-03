import requests
import json
from itrader.telegram_bot.const import CHAT_ID, TOKEN, URL

class TelegramBot():
    """
    Telegram Bot class which connect the trading system with the bot.
    It allows to send and recive command from telegram.

    Parameters
    ----------
    None
    """

    def __init__(self):
        self._base_url = 'https://api.telegram.org/bot'+TOKEN
        self._url = URL
        self._chat_id = CHAT_ID

    def set_webhook(self):
        """
        Set a weebhook between the telegram bot and a server.

        Returns
        -------
        `list[str]`
            The list of Asset symbols in the static Universe.
        """
        webhook=self._base_url + '/setWebhook?url=' + self._url
        response = requests.get(webhook)
        if response.ok:
            return 'WebHook connected'
    
    def send_message(self, chat_id = CHAT_ID, text=''):
        """
        Send a message to the telegram chat.

        Returns
        -------
        `list[str]`
            The list of Asset symbols in the static Universe.
        """
        command = self._base_url + '/sendMessage?chat_id='+chat_id+'&text='+text
        response = requests.post(command)
        if response.ok:
            return 'Message sent'
    
    def write_json(self, msg, filename='response.json'):
        with open(filename, 'w') as f:
            json.dump(msg, f, indent=4, ensure_ascii=False)