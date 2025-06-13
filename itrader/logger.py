import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict


def drop_color_message_key(_, __, event_dict: EventDict) -> EventDict:
    """
    Uvicorn logs the message a second time in the extra `color_message`, but we don't
    need it. This processor drops the key from the event dict if it exists.
    """
    event_dict.pop("color_message", None)
    return event_dict


def reorder_fields_for_console(logger, method_name, event_dict):
    """
    Reorder fields to show: timestamp, level, logger_name, message
    This makes the logger name appear before the main message with blue color.
    """
    if "logger" in event_dict:
        # Store the logger name and remove it from the dict temporarily
        logger_name = event_dict.pop("logger")
        # Create a new event message that includes the logger name with blue color
        # Using ANSI color codes: \033[34m for blue, \033[0m for reset
        original_event = event_dict.get("event", "")
        colored_logger_name = f"\033[34m[{logger_name}]\033[0m"
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
            if hasattr(arg, "id"):
                key = self._to_snake_case(type(arg).__name__)
                structlog.contextvars.bind_contextvars(**{key: arg.id})
            else:
                self.logger.error(
                    "Unsupported argument when trying to log.",
                    f"Unnamed argument must have an 'id' attribute. Invalid argument: {type(arg).__name__}",
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
    # Determine log level from config
    log_level = getattr(config, "LOG_LEVEL", "INFO")

    # Setup structured logging
    setup_logging(json_logs=False, log_level=log_level)

    # Create and return the structured logger
    return ITraderStructLogger("itrader")

