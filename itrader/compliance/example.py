import pandas as pd
import datetime
import os
import csv
from itrader.outils.price_parser import PriceParser

from .base import AbstractCompliance


class ExampleCompliance(AbstractCompliance):
    """
    A basic compliance module which writes trades to a
    CSV file in the output directory.
    """

    def __init__(self, config, engine):
        """
        Wipe the existing trade log for the day, leaving only
        the headers in an empty CSV.

        It allows for multiple backtests to be run
        in a simple way, but quite likely makes it unsuitable for
        a production environment that requires strict record-keeping.
        """
        self.config = config
        self.engine = engine
        # Remove the previous CSV file
        today = datetime.datetime.utcnow().date()
        self.csv_filename = "Tradelog.csv"# + today.strftime("%Y-%m-%d") + ".csv"
        self._remove_table_SQL(engine)

        try:
            fname = os.path.expanduser(os.path.join(config.OUTPUT_DIR, self.csv_filename))
            os.remove(fname)
        except (IOError, OSError):
            print("No tradelog files to clean.")

        # Write new file header
        fieldnames = [
            "timestamp", "ticker",
            "action", "quantity",
            "exchange", "price",
            "commission"
        ]
        fname = os.path.expanduser(os.path.join(self.config.OUTPUT_DIR, self.csv_filename))
        with open(fname, 'a') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
    
    def _remove_table_SQL(self, engine):
        qry_str = f'DROP TABLE IF EXISTS trades;'
        engine.execute(qry_str)

    def record_trade(self, fill):
        """
        Append all details about the FillEvent to the CSV trade log.
        """
        fname = os.path.expanduser(os.path.join(self.config.OUTPUT_DIR, self.csv_filename))
        with open(fname, 'a') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                fill.timestamp, fill.ticker,
                fill.action, fill.quantity,
                fill.exchange, PriceParser.display(fill.price, 4),
                PriceParser.display(fill.commission, 4)
            ])
        
        # Test save orders in SQL .db
        mydict={'timestamp':[fill.timestamp],
                'exchange':[fill.exchange], 
                'ticker':[fill.ticker],
                'action':[fill.action], 
                'quantity':[fill.quantity], 
                'price':[PriceParser.display(fill.price, 4)],
                'commission':[PriceParser.display(fill.commission, 4)]}
        df = pd.DataFrame(mydict, index=[0])
        df.to_sql('trades', self.engine, index = False, if_exists='append')
