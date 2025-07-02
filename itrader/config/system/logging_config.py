"""
System logging configuration.

This module provides specialized logging configuration for the system domain,
including structured logging, log rotation, and performance monitoring.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from enum import Enum


class LogFormat(Enum):
    """Log format types."""
    TEXT = "text"
    JSON = "json"
    STRUCTURED = "structured"


class LogRotation(Enum):
    """Log rotation strategies."""
    SIZE = "size"
    TIME = "time"
    BOTH = "both"
    NONE = "none"


@dataclass
class LogHandler:
    """Configuration for a log handler."""
    name: str
    level: str = "INFO"
    format_type: LogFormat = LogFormat.TEXT
    output: str = "console"  # console, file, syslog, etc.
    file_path: Optional[str] = None
    max_size_mb: int = 100
    backup_count: int = 5
    enabled: bool = True


@dataclass
class LoggingConfig:
    """
    Comprehensive logging configuration.
    
    This class provides detailed logging configuration including
    handlers, formatters, rotation policies, and performance settings.
    """
    
    # Basic settings
    global_level: str = "INFO"
    enable_console: bool = True
    enable_file: bool = True
    enable_structured: bool = False
    
    # File settings
    log_directory: str = "logs"
    log_filename: str = "itrader.log"
    max_file_size_mb: int = 100
    max_backup_files: int = 10
    
    # Rotation settings
    rotation_strategy: LogRotation = LogRotation.SIZE
    rotation_time_when: str = "midnight"  # for time-based rotation
    rotation_time_interval: int = 1
    
    # Format settings
    console_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    
    # Performance settings
    enable_async_logging: bool = False
    buffer_size: int = 1000
    flush_interval_seconds: float = 1.0
    
    # Component-specific log levels
    component_levels: Dict[str, str] = None
    
    # Handlers
    handlers: List[LogHandler] = None
    
    # Advanced settings
    enable_correlation_ids: bool = True
    enable_context_logging: bool = True
    enable_performance_logging: bool = False
    enable_error_tracking: bool = True
    
    def __post_init__(self):
        """Initialize default values after creation."""
        if self.component_levels is None:
            self.component_levels = {
                'itrader.portfolio': 'INFO',
                'itrader.trading': 'INFO',
                'itrader.data': 'INFO',
                'itrader.config': 'WARNING',
                'itrader.events': 'INFO'
            }
        
        if self.handlers is None:
            self.handlers = [
                LogHandler(
                    name="console",
                    level=self.global_level,
                    format_type=LogFormat.TEXT,
                    output="console",
                    enabled=self.enable_console
                ),
                LogHandler(
                    name="file",
                    level=self.global_level,
                    format_type=LogFormat.TEXT,
                    output="file",
                    file_path=f"{self.log_directory}/{self.log_filename}",
                    max_size_mb=self.max_file_size_mb,
                    backup_count=self.max_backup_files,
                    enabled=self.enable_file
                )
            ]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            # Basic settings
            'global_level': self.global_level,
            'enable_console': self.enable_console,
            'enable_file': self.enable_file,
            'enable_structured': self.enable_structured,
            
            # File settings
            'log_directory': self.log_directory,
            'log_filename': self.log_filename,
            'max_file_size_mb': self.max_file_size_mb,
            'max_backup_files': self.max_backup_files,
            
            # Rotation settings
            'rotation_strategy': self.rotation_strategy.value,
            'rotation_time_when': self.rotation_time_when,
            'rotation_time_interval': self.rotation_time_interval,
            
            # Format settings
            'console_format': self.console_format,
            'file_format': self.file_format,
            'date_format': self.date_format,
            
            # Performance settings
            'enable_async_logging': self.enable_async_logging,
            'buffer_size': self.buffer_size,
            'flush_interval_seconds': self.flush_interval_seconds,
            
            # Component-specific log levels
            'component_levels': self.component_levels,
            
            # Handlers
            'handlers': [
                {
                    'name': handler.name,
                    'level': handler.level,
                    'format_type': handler.format_type.value,
                    'output': handler.output,
                    'file_path': handler.file_path,
                    'max_size_mb': handler.max_size_mb,
                    'backup_count': handler.backup_count,
                    'enabled': handler.enabled
                }
                for handler in self.handlers
            ],
            
            # Advanced settings
            'enable_correlation_ids': self.enable_correlation_ids,
            'enable_context_logging': self.enable_context_logging,
            'enable_performance_logging': self.enable_performance_logging,
            'enable_error_tracking': self.enable_error_tracking
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LoggingConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        # Basic settings
        config.global_level = data.get('global_level', config.global_level)
        config.enable_console = data.get('enable_console', config.enable_console)
        config.enable_file = data.get('enable_file', config.enable_file)
        config.enable_structured = data.get('enable_structured', config.enable_structured)
        
        # File settings
        config.log_directory = data.get('log_directory', config.log_directory)
        config.log_filename = data.get('log_filename', config.log_filename)
        config.max_file_size_mb = data.get('max_file_size_mb', config.max_file_size_mb)
        config.max_backup_files = data.get('max_backup_files', config.max_backup_files)
        
        # Rotation settings
        if 'rotation_strategy' in data:
            config.rotation_strategy = LogRotation(data['rotation_strategy'])
        config.rotation_time_when = data.get('rotation_time_when', config.rotation_time_when)
        config.rotation_time_interval = data.get('rotation_time_interval', config.rotation_time_interval)
        
        # Format settings
        config.console_format = data.get('console_format', config.console_format)
        config.file_format = data.get('file_format', config.file_format)
        config.date_format = data.get('date_format', config.date_format)
        
        # Performance settings
        config.enable_async_logging = data.get('enable_async_logging', config.enable_async_logging)
        config.buffer_size = data.get('buffer_size', config.buffer_size)
        config.flush_interval_seconds = data.get('flush_interval_seconds', config.flush_interval_seconds)
        
        # Component-specific log levels
        config.component_levels = data.get('component_levels', config.component_levels)
        
        # Handlers
        if 'handlers' in data:
            config.handlers = [
                LogHandler(
                    name=handler_data['name'],
                    level=handler_data.get('level', 'INFO'),
                    format_type=LogFormat(handler_data.get('format_type', 'text')),
                    output=handler_data.get('output', 'console'),
                    file_path=handler_data.get('file_path'),
                    max_size_mb=handler_data.get('max_size_mb', 100),
                    backup_count=handler_data.get('backup_count', 5),
                    enabled=handler_data.get('enabled', True)
                )
                for handler_data in data['handlers']
            ]
        
        # Advanced settings
        config.enable_correlation_ids = data.get('enable_correlation_ids', config.enable_correlation_ids)
        config.enable_context_logging = data.get('enable_context_logging', config.enable_context_logging)
        config.enable_performance_logging = data.get('enable_performance_logging', config.enable_performance_logging)
        config.enable_error_tracking = data.get('enable_error_tracking', config.enable_error_tracking)
        
        return config


def get_default_logging_config() -> LoggingConfig:
    """Get default logging configuration."""
    return LoggingConfig()


def get_production_logging_config() -> LoggingConfig:
    """Get production-optimized logging configuration."""
    return LoggingConfig(
        global_level="WARNING",
        enable_console=False,
        enable_file=True,
        enable_structured=True,
        max_file_size_mb=500,
        max_backup_files=20,
        rotation_strategy=LogRotation.BOTH,
        enable_async_logging=True,
        enable_performance_logging=True,
        component_levels={
            'itrader.portfolio': 'INFO',
            'itrader.trading': 'INFO',
            'itrader.data': 'WARNING',
            'itrader.config': 'ERROR',
            'itrader.events': 'INFO'
        }
    )


def get_debug_logging_config() -> LoggingConfig:
    """Get debug logging configuration."""
    return LoggingConfig(
        global_level="DEBUG",
        enable_console=True,
        enable_file=True,
        enable_structured=False,
        max_file_size_mb=50,
        max_backup_files=5,
        enable_performance_logging=True,
        enable_context_logging=True,
        component_levels={
            'itrader': 'DEBUG'
        }
    )
