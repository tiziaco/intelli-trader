from __future__ import print_function
from abc import ABCMeta, abstractmethod

class AbstractExchange(object):
    """
    AbstractExchange is a metaclass providing an interface for
    all subsequent (inherited) data providers (only historic).

    The goal of a (derived) Exchange object is to download price 
    data (OHLCV) from the data provider server.
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def get_all_symbols(self):
        raise NotImplementedError("Should implement get_all_symbols()")
    
    @abstractmethod
    def download_data(self):
        raise NotImplementedError("Should implement download_data()")

    @abstractmethod
    def _format_data(self, data):
        raise NotImplementedError("Should implement format_data()")
