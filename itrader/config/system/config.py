"""
System domain configuration classes.

This module defines configuration classes for system-level settings,
including application settings, performance tuning, and operational parameters.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


class Environment(Enum):
    """Environment types."""
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(Enum):
    """Logging levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class PerformanceSettings:
    """Performance tuning settings."""
    max_threads: int = 10
    max_processes: int = 4
    enable_multiprocessing: bool = False
    enable_async: bool = True
    connection_pool_size: int = 20
    timeout_seconds: int = 30
    enable_caching: bool = True
    cache_size_mb: int = 512


@dataclass
class SecuritySettings:
    """Security configuration."""
    enable_encryption: bool = True
    encryption_algorithm: str = "AES-256"
    enable_api_key_auth: bool = True
    session_timeout_minutes: int = 60
    max_login_attempts: int = 3
    enable_rate_limiting: bool = True
    rate_limit_requests_per_minute: int = 1000


@dataclass
class DatabaseSettings:
    """Database connection settings."""
    host: str = "localhost"
    port: int = 5432
    database: str = "itrader"
    username: str = "itrader"
    password: Optional[str] = None
    connection_pool_size: int = 10
    enable_ssl: bool = False
    timeout_seconds: int = 30


@dataclass
class NotificationSettings:
    """Notification system settings."""
    enable_email: bool = False
    email_smtp_host: Optional[str] = None
    email_smtp_port: int = 587
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    enable_slack: bool = False
    slack_webhook_url: Optional[str] = None
    enable_discord: bool = False
    discord_webhook_url: Optional[str] = None


@dataclass
class MonitoringSettings:
    """Monitoring and metrics settings."""
    enable_metrics: bool = True
    metrics_port: int = 9090
    enable_health_check: bool = True
    health_check_port: int = 8080
    enable_profiling: bool = False
    profiling_port: int = 8081
    enable_tracing: bool = False


@dataclass
class SystemConfig:
    """
    Main system configuration class.
    
    This class contains all system-level configuration parameters,
    including environment settings, performance tuning, and operational parameters.
    """
    
    # Basic settings
    name: str = "iTrader System"
    version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug_mode: bool = True
    
    # Directories and paths
    data_dir: str = "data"
    log_dir: str = "logs"
    config_dir: str = "settings"
    cache_dir: str = "cache"
    
    # Configuration objects
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)
    
    # Operational settings
    enable_auto_restart: bool = False
    auto_restart_delay_seconds: int = 10
    enable_graceful_shutdown: bool = True
    shutdown_timeout_seconds: int = 30
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            # Basic settings
            'name': self.name,
            'version': self.version,
            'environment': self.environment.value,
            'debug_mode': self.debug_mode,
            
            # Directories and paths
            'data_dir': self.data_dir,
            'log_dir': self.log_dir,
            'config_dir': self.config_dir,
            'cache_dir': self.cache_dir,
            
            # Performance settings
            'performance': {
                'max_threads': self.performance.max_threads,
                'max_processes': self.performance.max_processes,
                'enable_multiprocessing': self.performance.enable_multiprocessing,
                'enable_async': self.performance.enable_async,
                'connection_pool_size': self.performance.connection_pool_size,
                'timeout_seconds': self.performance.timeout_seconds,
                'enable_caching': self.performance.enable_caching,
                'cache_size_mb': self.performance.cache_size_mb
            },
            
            # Security settings
            'security': {
                'enable_encryption': self.security.enable_encryption,
                'encryption_algorithm': self.security.encryption_algorithm,
                'enable_api_key_auth': self.security.enable_api_key_auth,
                'session_timeout_minutes': self.security.session_timeout_minutes,
                'max_login_attempts': self.security.max_login_attempts,
                'enable_rate_limiting': self.security.enable_rate_limiting,
                'rate_limit_requests_per_minute': self.security.rate_limit_requests_per_minute
            },
            
            # Database settings
            'database': {
                'host': self.database.host,
                'port': self.database.port,
                'database': self.database.database,
                'username': self.database.username,
                'password': self.database.password,
                'connection_pool_size': self.database.connection_pool_size,
                'enable_ssl': self.database.enable_ssl,
                'timeout_seconds': self.database.timeout_seconds
            },
            
            # Notification settings
            'notifications': {
                'enable_email': self.notifications.enable_email,
                'email_smtp_host': self.notifications.email_smtp_host,
                'email_smtp_port': self.notifications.email_smtp_port,
                'email_username': self.notifications.email_username,
                'email_password': self.notifications.email_password,
                'enable_slack': self.notifications.enable_slack,
                'slack_webhook_url': self.notifications.slack_webhook_url,
                'enable_discord': self.notifications.enable_discord,
                'discord_webhook_url': self.notifications.discord_webhook_url
            },
            
            # Monitoring settings
            'monitoring': {
                'enable_metrics': self.monitoring.enable_metrics,
                'metrics_port': self.monitoring.metrics_port,
                'enable_health_check': self.monitoring.enable_health_check,
                'health_check_port': self.monitoring.health_check_port,
                'enable_profiling': self.monitoring.enable_profiling,
                'profiling_port': self.monitoring.profiling_port,
                'enable_tracing': self.monitoring.enable_tracing
            },
            
            # Operational settings
            'enable_auto_restart': self.enable_auto_restart,
            'auto_restart_delay_seconds': self.auto_restart_delay_seconds,
            'enable_graceful_shutdown': self.enable_graceful_shutdown,
            'shutdown_timeout_seconds': self.shutdown_timeout_seconds
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SystemConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        # Basic settings
        config.name = data.get('name', config.name)
        config.version = data.get('version', config.version)
        
        if 'environment' in data:
            config.environment = Environment(data['environment'])
        
        config.debug_mode = data.get('debug_mode', config.debug_mode)
        
        # Directories and paths
        config.data_dir = data.get('data_dir', config.data_dir)
        config.log_dir = data.get('log_dir', config.log_dir)
        config.config_dir = data.get('config_dir', config.config_dir)
        config.cache_dir = data.get('cache_dir', config.cache_dir)
        
        # Performance settings
        if 'performance' in data:
            perf_data = data['performance']
            config.performance = PerformanceSettings(
                max_threads=perf_data.get('max_threads', config.performance.max_threads),
                max_processes=perf_data.get('max_processes', config.performance.max_processes),
                enable_multiprocessing=perf_data.get('enable_multiprocessing', config.performance.enable_multiprocessing),
                enable_async=perf_data.get('enable_async', config.performance.enable_async),
                connection_pool_size=perf_data.get('connection_pool_size', config.performance.connection_pool_size),
                timeout_seconds=perf_data.get('timeout_seconds', config.performance.timeout_seconds),
                enable_caching=perf_data.get('enable_caching', config.performance.enable_caching),
                cache_size_mb=perf_data.get('cache_size_mb', config.performance.cache_size_mb)
            )
        
        # Security settings
        if 'security' in data:
            sec_data = data['security']
            config.security = SecuritySettings(
                enable_encryption=sec_data.get('enable_encryption', config.security.enable_encryption),
                encryption_algorithm=sec_data.get('encryption_algorithm', config.security.encryption_algorithm),
                enable_api_key_auth=sec_data.get('enable_api_key_auth', config.security.enable_api_key_auth),
                session_timeout_minutes=sec_data.get('session_timeout_minutes', config.security.session_timeout_minutes),
                max_login_attempts=sec_data.get('max_login_attempts', config.security.max_login_attempts),
                enable_rate_limiting=sec_data.get('enable_rate_limiting', config.security.enable_rate_limiting),
                rate_limit_requests_per_minute=sec_data.get('rate_limit_requests_per_minute', config.security.rate_limit_requests_per_minute)
            )
        
        # Database settings
        if 'database' in data:
            db_data = data['database']
            config.database = DatabaseSettings(
                host=db_data.get('host', config.database.host),
                port=db_data.get('port', config.database.port),
                database=db_data.get('database', config.database.database),
                username=db_data.get('username', config.database.username),
                password=db_data.get('password', config.database.password),
                connection_pool_size=db_data.get('connection_pool_size', config.database.connection_pool_size),
                enable_ssl=db_data.get('enable_ssl', config.database.enable_ssl),
                timeout_seconds=db_data.get('timeout_seconds', config.database.timeout_seconds)
            )
        
        # Notification settings
        if 'notifications' in data:
            notif_data = data['notifications']
            config.notifications = NotificationSettings(
                enable_email=notif_data.get('enable_email', config.notifications.enable_email),
                email_smtp_host=notif_data.get('email_smtp_host', config.notifications.email_smtp_host),
                email_smtp_port=notif_data.get('email_smtp_port', config.notifications.email_smtp_port),
                email_username=notif_data.get('email_username', config.notifications.email_username),
                email_password=notif_data.get('email_password', config.notifications.email_password),
                enable_slack=notif_data.get('enable_slack', config.notifications.enable_slack),
                slack_webhook_url=notif_data.get('slack_webhook_url', config.notifications.slack_webhook_url),
                enable_discord=notif_data.get('enable_discord', config.notifications.enable_discord),
                discord_webhook_url=notif_data.get('discord_webhook_url', config.notifications.discord_webhook_url)
            )
        
        # Monitoring settings
        if 'monitoring' in data:
            mon_data = data['monitoring']
            config.monitoring = MonitoringSettings(
                enable_metrics=mon_data.get('enable_metrics', config.monitoring.enable_metrics),
                metrics_port=mon_data.get('metrics_port', config.monitoring.metrics_port),
                enable_health_check=mon_data.get('enable_health_check', config.monitoring.enable_health_check),
                health_check_port=mon_data.get('health_check_port', config.monitoring.health_check_port),
                enable_profiling=mon_data.get('enable_profiling', config.monitoring.enable_profiling),
                profiling_port=mon_data.get('profiling_port', config.monitoring.profiling_port),
                enable_tracing=mon_data.get('enable_tracing', config.monitoring.enable_tracing)
            )
        
        # Operational settings
        config.enable_auto_restart = data.get('enable_auto_restart', config.enable_auto_restart)
        config.auto_restart_delay_seconds = data.get('auto_restart_delay_seconds', config.auto_restart_delay_seconds)
        config.enable_graceful_shutdown = data.get('enable_graceful_shutdown', config.enable_graceful_shutdown)
        config.shutdown_timeout_seconds = data.get('shutdown_timeout_seconds', config.shutdown_timeout_seconds)
        
        return config
