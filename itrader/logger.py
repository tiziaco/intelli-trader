import logging

logger = logging.getLogger('iTrader')
logger.setLevel(logging.DEBUG)  # Overall minimum logging level

stream_handler = logging.StreamHandler()  # Configure the logging messages displayed in the Terminal
formatter = logging.Formatter('%(levelname)s | %(message)s') # %(asctime)s 
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.DEBUG)  # Minimum logging level for the StreamHandler

# file_handler = logging.FileHandler('info.log')  # Configure the logging messages written to a file
# file_handler.setFormatter(formatter)
# file_handler.setLevel(logging.DEBUG)  # Minimum logging level for the FileHandler

logger.addHandler(stream_handler)
#logger.addHandler(file_handler)
