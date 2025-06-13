import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict


# Export only what's needed for the simple approach
__all__ = [
    'ITraderStructLogger',
    'get_itrader_logger',
    'init_logger',
    'setup_logging'
]


def drop_color_message_key(_, __, event_dict: EventDict) -> EventDict:
    """
    Uvicorn logs the message a second time in the extra `color_message`, but we don't
    need it. This processor drops the key from the event dict if it exists.
    """
    event_dict.pop("color_message", None)
    return event_dict


def reorder_fields_for_console(logger, method_name, event_dict):
    """
    Reorder fields to show: timestamp, level, logger_name.component, message
    This makes the logger name with component appear before the main message with blue color.
    """
    if "logger" in event_dict:
        # Store the logger name and remove it from the dict temporarily
        logger_name = event_dict.pop("logger")
        
        # Check if there's a component field to include in the logger name
        component = event_dict.pop("component", None)
        if component:
            # Show as [itrader.ComponentName] instead of just [itrader]
            display_name = f"{logger_name}.{component}"
        else:
            display_name = logger_name
            
        # Create a new event message that includes the enhanced logger name with blue color
        # Using ANSI color codes: \033[34m for blue, \033[0m for reset
        original_event = event_dict.get("event", "")
        colored_logger_name = f"\033[34m[{display_name}]\033[0m"
        event_dict["event"] = f"{colored_logger_name} {original_event}"

    return event_dict


def setup_logging(json_logs: bool = False, log_level: str = "INFO"):
    """Configure structlog for the itrader package"""

    # Simple, working configuration that displays logger names
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        drop_color_message_key,
        structlog.processors.TimeStamper(fmt="iso"),
        reorder_fields_for_console,  # Add our custom field reordering
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        processors.append(structlog.processors.format_exc_info)

    processors.append(structlog.stdlib.ProcessorFormatter.wrap_for_formatter)

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set up the formatter - this is the key part that makes logger names work
    if json_logs:
        log_renderer = structlog.processors.JSONRenderer()
    else:
        log_renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=25,  # Pad the event message for alignment
            repr_native_str=False,
        )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=log_renderer,
    )

    # Configure root logger
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Clear any existing handlers and add our structured logging handler
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())


class ITraderStructLogger:
    """
    Simplified structured logger for the iTrader package.
    Designed for the simple .bind() approach.
    
    Usage:
        from itrader.logger import get_itrader_logger
        
        class YourClass:
            def __init__(self):
                self.logger = get_itrader_logger().bind(component="YourClass")
                
            def your_method(self):
                self.logger.info("Operation completed", key=value)
    """

    def __init__(self, log_name: str = "itrader"):
        self.logger = structlog.stdlib.get_logger(log_name)

    def bind(self, **new_values: Any):
        """
        Bind values to create a new logger with bound context.
        This is the core method for the simple approach.

        Args:
            **new_values: Key-value pairs to bind to the context
            
        Returns:
            ITraderStructLogger: New logger instance with bound context
            
        Example:
            self.logger = get_itrader_logger().bind(component="PortfolioHandler")
        """
        # Create a new bound logger using structlog's bind method
        bound_structlog = self.logger.bind(**new_values)
        
        # Create a new ITraderStructLogger instance with the bound logger
        new_logger = ITraderStructLogger.__new__(ITraderStructLogger)
        new_logger.logger = bound_structlog
        
        return new_logger

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
    # Determine log level from config
    log_level = getattr(config, "LOG_LEVEL", "INFO")

    # Setup structured logging
    setup_logging(json_logs=False, log_level=log_level)

    # Create and return the structured logger
    return ITraderStructLogger("itrader")


# Global logger instance for simple usage
_global_logger = None


def get_itrader_logger():
    """
    Get the global itrader logger instance.
    This is the RECOMMENDED approach for simple, efficient logging.
    
    Usage:
        from itrader.logger import get_itrader_logger
        
        class MyClass:
            def __init__(self):
                self.logger = get_itrader_logger().bind(component="MyClass")
                
            def my_method(self):
                self.logger.info("Operation completed", result="success")
    
    Returns:
        ITraderStructLogger: Global itrader logger instance
    """
    global _global_logger
    if _global_logger is None:
        _global_logger = ITraderStructLogger("itrader")
    return _global_logger
