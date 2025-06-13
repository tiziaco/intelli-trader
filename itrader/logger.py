import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def drop_color_message_key(_, __, event_dict: EventDict) -> EventDict:
    """
    Uvicorn logs the message a second time in the extra `color_message`, but we don't
    need it. This processor drops the key from the event dict if it exists.
    """
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(json_logs: bool = False, log_level: str = "INFO"):
    """Configure structlog for the itrader package"""
    
    # Check if structlog is already configured by looking at the current configuration
    try:
        # Try to get the current structlog configuration
        current_config = structlog.get_config()
        if current_config and current_config.get('processors'):
            # structlog is already configured, don't reconfigure
            return
    except (AttributeError, RuntimeError):
        # structlog is not configured yet, proceed with setup
        pass
    
    # Check if the root logger already has StreamHandlers with structlog formatters
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if (isinstance(handler, logging.StreamHandler) and 
            isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)):
            # structlog is already set up, don't interfere
            return
    
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        drop_color_message_key,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        # Format the exception only for JSON logs, as we want to pretty-print them when
        # using the ConsoleRenderer
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    log_renderer: structlog.types.Processor
    if json_logs:
        log_renderer = structlog.processors.JSONRenderer()
    else:
        log_renderer = structlog.dev.ConsoleRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        # These run ONLY on `logging` entries that do NOT originate within
        # structlog.
        foreign_pre_chain=shared_processors,
        # These run on ALL entries after the pre_chain is done.
        processors=[
            # Remove _record & _from_structlog.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            log_renderer,
        ],
    )

    # Only configure the root logger if it hasn't been configured yet
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    # Clear any existing handlers and add our structured logging handler
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())


class ITraderStructLogger:
    """
    Structured logger for the iTrader package.
    Uses context variables to bind data that will be automatically included in all log messages.
    """
    
    def __init__(self, log_name: str = "itrader"):
        self.logger = structlog.stdlib.get_logger(log_name)

    @staticmethod
    def _to_snake_case(name):
        """Convert CamelCase to snake_case"""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    def bind(self, *args, **new_values: Any):
        """
        Bind values to the logger context. 
        
        Args:
            *args: Objects that have an 'id' attribute (will be converted to snake_case)
            **new_values: Key-value pairs to bind to the context
        """
        for arg in args:
            # Check if the object has an id attribute
            if hasattr(arg, 'id'):
                key = self._to_snake_case(type(arg).__name__)
                structlog.contextvars.bind_contextvars(**{key: arg.id})
            else:
                self.logger.error(
                    "Unsupported argument when trying to log.",
                    f"Unnamed argument must have an 'id' attribute. Invalid argument: {type(arg).__name__}"
                )

        structlog.contextvars.bind_contextvars(**new_values)

    @staticmethod
    def unbind(*keys: str):
        """Unbind keys from the logger context"""
        structlog.contextvars.unbind_contextvars(*keys)

    def debug(self, event: str | None = None, *args: Any, **kw: Any):
        self.logger.debug(event, *args, **kw)

    def info(self, event: str | None = None, *args: Any, **kw: Any):
        self.logger.info(event, *args, **kw)

    def warning(self, event: str | None = None, *args: Any, **kw: Any):
        self.logger.warning(event, *args, **kw)

    warn = warning

    def error(self, event: str | None = None, *args: Any, **kw: Any):
        self.logger.error(event, *args, **kw)

    def critical(self, event: str | None = None, *args: Any, **kw: Any):
        self.logger.critical(event, *args, **kw)

    def exception(self, event: str | None = None, *args: Any, **kw: Any):
        self.logger.exception(event, *args, **kw)


def init_logger(config):
    """
    Initialize the structured logger for itrader package.
    
    Args:
        config: Configuration object with logging settings
        
    Returns:
        ITraderStructLogger: Configured structured logger instance
    """
    # Determine log level based on config
    log_level = "DEBUG" if config.DEBUG else "INFO"
    
    # Setup structured logging
    setup_logging(json_logs=False, log_level=log_level)
    
    # Create and return the structured logger
    return ITraderStructLogger("itrader")

