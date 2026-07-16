import json
import logging
import os
import sys
import uuid
from typing import Any

import structlog
from structlog.types import EventDict, Processor


# Export only what's needed for the simple approach
__all__ = [
    'ITraderStructLogger',
    'get_itrader_logger',
    'init_logger',
    'setup_logging'
]

# Sentinel attribute set on handlers installed by this module so that repeated
# setup calls only replace OUR handler — never handlers installed by embedding
# applications or pytest (guarded, idempotent init).
_ITRADER_HANDLER_FLAG = "_itrader_handler"


def _env_log_level() -> str:
    """Resolve the log level from ``ITRADER_LOG_LEVEL`` (default ``INFO``).

    Read directly from ``os.environ`` — do NOT construct a ``RuntimeSettings``
    instance here: the logger must not instantiate any config/settings model at
    import time, keeping ``import itrader`` side-effect-free (Pitfall 8). The env
    name matches the pydantic-settings ``ITRADER_`` prefix so
    ``RuntimeSettings.log_level`` stays the documented knob.
    """
    return os.environ.get("ITRADER_LOG_LEVEL", "INFO")


def _env_json_logs() -> bool:
    """Resolve JSON rendering from ``ITRADER_JSON_LOGS`` (default off)."""
    raw = os.environ.get("ITRADER_JSON_LOGS", "false")
    return raw.strip().lower() in ("1", "true", "yes")


def _env_disable_logs() -> bool:
    """Resolve the D-08 full-off kill-switch from ``ITRADER_DISABLE_LOGS`` (default off).

    Mirrors the ``_env_json_logs`` idiom: read ``os.environ`` directly and never
    construct a ``RuntimeSettings`` instance here — the logger must not instantiate any
    config/settings model at import time, keeping ``import itrader`` side-effect-free
    (Pitfall 8). The env name matches the pydantic-settings ``ITRADER_`` prefix so
    ``RuntimeSettings.disable_logs`` stays the documented knob.
    """
    raw = os.environ.get("ITRADER_DISABLE_LOGS", "false")
    return raw.strip().lower() in ("1", "true", "yes")


# D-08: resolve the kill-switch ONCE at import into a module-level cached bool. The
# central guards check this FIRST (a cached bool, marginally cheaper than
# ``isEnabledFor``) to short-circuit ALL logging unconditionally. For a fully-silent
# backtest set ``ITRADER_DISABLE_LOGS=true``.
_DISABLE_LOGS: bool = _env_disable_logs()


def _json_default(obj: object) -> str:
    """Fallback serializer for ``JSONRenderer`` (WR-01).

    The single-UUIDv7 scheme (DEC-03) flows ``uuid.UUID`` values such as
    ``correlation_id`` / ``portfolio_id`` into the ERROR-route log context.
    ``json.dumps`` cannot serialize ``uuid.UUID`` natively, so stringify it
    at the serialization edge — never revert the UUID type at the call site.
    """
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _uuid_safe_json_serializer(obj: Any, **kw: Any) -> str:
    """``JSONRenderer`` serializer that tolerates ``uuid.UUID`` (WR-01).

    ``structlog.processors.JSONRenderer`` injects its own ``default`` handler
    into ``kw``. Pop it and chain it after ``_json_default`` so both the
    UUID coercion and structlog's native fallback keep working — passing our
    own ``default`` alongside structlog's would raise a duplicate-kwarg
    ``TypeError``.
    """
    structlog_default = kw.pop("default", None)

    def _default(value: object) -> str:
        try:
            return _json_default(value)
        except TypeError:
            if structlog_default is not None:
                return structlog_default(value)  # type: ignore[no-any-return]
            # WR-04: a log sink must never crash on a stray field. When structlog
            # injected no chained default (future structlog version, or a direct
            # call), repr-coerce instead of re-raising so a single
            # non-serializable context value (Decimal/datetime/custom object) on
            # the ERROR route cannot crash the last-resort error sink.
            return repr(value)

    return json.dumps(obj, default=_default, **kw)


def drop_color_message_key(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """
    Uvicorn logs the message a second time in the extra `color_message`, but we don't
    need it. This processor drops the key from the event dict if it exists.
    """
    event_dict.pop("color_message", None)
    return event_dict


def reorder_fields_for_console(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """
    Reorder fields to show: timestamp, level, logger_name.component, message
    This makes the logger name with component appear before the main message with blue color.
    """
    if "logger" in event_dict:
        # Store the logger name and remove it from the dict temporarily
        logger_name = event_dict.pop("logger")
        
        # Check if there's a component field to include in the logger name.
        # Explicit None check (D-20): a falsy-but-legitimate value (e.g. "")
        # must not silently fall through to the bare logger name.
        component = event_dict.pop("component", None)
        if component is not None:
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


def setup_logging(json_logs: bool = False, log_level: str = "INFO") -> None:
    """Configure structlog for the itrader package"""

    # Simple, working configuration that displays logger names
    processors: list[Processor] = [
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
    log_renderer: Processor
    if json_logs:
        # UUID-safe serializer (WR-01): keep the single-UUIDv7 scheme intact
        # and stringify uuid.UUID values only at the JSON serialization edge.
        log_renderer = structlog.processors.JSONRenderer(
            serializer=_uuid_safe_json_serializer
        )
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
    setattr(handler, _ITRADER_HANDLER_FLAG, True)

    # Guarded handler swap: only remove handlers THIS module installed
    # (tracked via the sentinel attribute). Handlers installed by embedding
    # applications or pytest are left untouched, and repeated setup calls
    # are idempotent (no duplicate-handler stacking).
    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        if getattr(existing, _ITRADER_HANDLER_FLAG, False):
            root_logger.removeHandler(existing)
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
        # D-02: cache the stdlib logger so each wrapper method can short-circuit
        # below-level calls via ``isEnabledFor`` BEFORE the 9-processor structlog
        # pipeline runs (hotspot #4 — the pipeline runs on below-level calls today).
        self._stdlib = logging.getLogger(log_name)

    def bind(self, **new_values: Any) -> "ITraderStructLogger":
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
        # D-02: bind() builds via __new__ which skips __init__, so the cached
        # stdlib reference MUST be carried over explicitly — otherwise the gate on
        # the bound instance would AttributeError on its first call. The stdlib
        # logger name is unchanged by bind() (only structlog context is bound), so
        # reuse the same cached reference.
        new_logger._stdlib = self._stdlib

        return new_logger

    def debug(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        # D-08 kill-switch first (cached bool), then D-02 level-gate.
        if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.DEBUG):
            return
        self.logger.debug(event, *args, **kw)

    def info(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.INFO):
            return
        self.logger.info(event, *args, **kw)

    def warning(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.WARNING):
            return
        self.logger.warning(event, *args, **kw)

    warn = warning

    def error(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.ERROR):
            return
        self.logger.error(event, *args, **kw)

    def critical(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.CRITICAL):
            return
        self.logger.critical(event, *args, **kw)

    def exception(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        # exception() is an always-emit path: exceptions are logged regardless of
        # level (D-02 leaves it routed straight through). The D-08 kill-switch still
        # applies for a true full-off.
        if _DISABLE_LOGS:
            return
        self.logger.exception(event, *args, **kw)


def init_logger(config: Any = None) -> "ITraderStructLogger":
    """
    Initialize the structured logger for itrader package.

    Log level and JSON rendering are environment-driven (M3-03 / D-20):
    ``ITRADER_LOG_LEVEL`` (default ``INFO``) and ``ITRADER_JSON_LOGS``
    (default off). Read via ``os.environ`` directly — never by constructing
    a ``RuntimeSettings`` instance, keeping ``import itrader`` side-effect-free
    (Pitfall 8).

    Args:
        config: Accepted for backward compatibility; ignored. Logging
            configuration comes from the environment.

    Returns:
        ITraderStructLogger: Configured structured logger instance
    """
    # Setup structured logging from the environment
    setup_logging(json_logs=_env_json_logs(), log_level=_env_log_level())

    # Create and return the structured logger
    return ITraderStructLogger("itrader")


# Global logger instance for simple usage
_global_logger: "ITraderStructLogger | None" = None


def get_itrader_logger() -> "ITraderStructLogger":
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
