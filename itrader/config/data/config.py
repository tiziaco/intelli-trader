"""
Data domain configuration classes.

This module defines configuration classes for data management,
including data sources, feeds, storage, and processing settings.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


class DataSource(Enum):
    """Data source types."""
    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    YAHOO = "yahoo"
    ALPHA_VANTAGE = "alpha_vantage"
    IEX = "iex"
    QUANDL = "quandl"
    CSV = "csv"
    DATABASE = "database"


class DataFrequency(Enum):
    """Data frequency intervals."""
    TICK = "tick"
    SECOND = "1s"
    MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    THIRTY_MINUTE = "30m"
    HOUR = "1h"
    FOUR_HOUR = "4h"
    DAILY = "1d"
    WEEKLY = "1w"
    MONTHLY = "1M"


class StorageType(Enum):
    """Data storage types."""
    MEMORY = "memory"
    CSV = "csv"
    PARQUET = "parquet"
    HDF5 = "hdf5"
    DATABASE = "database"
    REDIS = "redis"


@dataclass
class DataSourceConfig:
    """Configuration for a data source."""
    name: str
    source_type: DataSource
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit: int = 10  # requests per second
    timeout: int = 30  # seconds
    retry_attempts: int = 3
    enabled: bool = True


@dataclass
class DataFeedConfig:
    """Configuration for a data feed."""
    symbol: str
    source: str
    frequency: DataFrequency
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    fields: List[str] = field(default_factory=lambda: ['open', 'high', 'low', 'close', 'volume'])
    enabled: bool = True


@dataclass
class StorageConfig:
    """Data storage configuration."""
    storage_type: StorageType = StorageType.PARQUET
    base_path: str = "data"
    compression: str = "snappy"
    max_file_size_mb: int = 100
    partition_by: Optional[str] = "date"
    retention_days: Optional[int] = None
    backup_enabled: bool = False
    backup_path: Optional[str] = None


@dataclass
class ProcessingConfig:
    """Data processing configuration."""
    enable_validation: bool = True
    enable_cleaning: bool = True
    enable_normalization: bool = False
    fill_missing_data: bool = True
    remove_outliers: bool = False
    outlier_threshold: float = 3.0
    enable_caching: bool = True
    cache_size_mb: int = 500


@dataclass
class RealTimeConfig:
    """Real-time data configuration."""
    enable_real_time: bool = False
    buffer_size: int = 1000
    update_frequency_ms: int = 1000
    enable_heartbeat: bool = True
    heartbeat_interval_s: int = 30
    reconnect_attempts: int = 5
    reconnect_delay_s: int = 5


@dataclass
class DataConfig:
    """
    Main data configuration class.
    
    This class contains all configuration parameters for data management,
    including sources, feeds, storage, and processing settings.
    """
    
    # Basic settings
    name: str = "Default Data Config"
    description: str = ""
    
    # Data sources
    sources: List[DataSourceConfig] = field(default_factory=list)
    
    # Data feeds
    feeds: List[DataFeedConfig] = field(default_factory=list)
    
    # Configuration objects
    storage: StorageConfig = field(default_factory=StorageConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    real_time: RealTimeConfig = field(default_factory=RealTimeConfig)
    
    # Operational settings
    enable_logging: bool = True
    log_level: str = "INFO"
    enable_metrics: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            # Basic settings
            'name': self.name,
            'description': self.description,
            
            # Data sources
            'sources': [
                {
                    'name': source.name,
                    'source_type': source.source_type.value,
                    'api_key': source.api_key,
                    'api_secret': source.api_secret,
                    'base_url': source.base_url,
                    'rate_limit': source.rate_limit,
                    'timeout': source.timeout,
                    'retry_attempts': source.retry_attempts,
                    'enabled': source.enabled
                }
                for source in self.sources
            ],
            
            # Data feeds
            'feeds': [
                {
                    'symbol': feed.symbol,
                    'source': feed.source,
                    'frequency': feed.frequency.value,
                    'start_date': feed.start_date,
                    'end_date': feed.end_date,
                    'fields': feed.fields,
                    'enabled': feed.enabled
                }
                for feed in self.feeds
            ],
            
            # Storage configuration
            'storage': {
                'storage_type': self.storage.storage_type.value,
                'base_path': self.storage.base_path,
                'compression': self.storage.compression,
                'max_file_size_mb': self.storage.max_file_size_mb,
                'partition_by': self.storage.partition_by,
                'retention_days': self.storage.retention_days,
                'backup_enabled': self.storage.backup_enabled,
                'backup_path': self.storage.backup_path
            },
            
            # Processing configuration
            'processing': {
                'enable_validation': self.processing.enable_validation,
                'enable_cleaning': self.processing.enable_cleaning,
                'enable_normalization': self.processing.enable_normalization,
                'fill_missing_data': self.processing.fill_missing_data,
                'remove_outliers': self.processing.remove_outliers,
                'outlier_threshold': self.processing.outlier_threshold,
                'enable_caching': self.processing.enable_caching,
                'cache_size_mb': self.processing.cache_size_mb
            },
            
            # Real-time configuration
            'real_time': {
                'enable_real_time': self.real_time.enable_real_time,
                'buffer_size': self.real_time.buffer_size,
                'update_frequency_ms': self.real_time.update_frequency_ms,
                'enable_heartbeat': self.real_time.enable_heartbeat,
                'heartbeat_interval_s': self.real_time.heartbeat_interval_s,
                'reconnect_attempts': self.real_time.reconnect_attempts,
                'reconnect_delay_s': self.real_time.reconnect_delay_s
            },
            
            # Operational settings
            'enable_logging': self.enable_logging,
            'log_level': self.log_level,
            'enable_metrics': self.enable_metrics
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DataConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        # Basic settings
        config.name = data.get('name', config.name)
        config.description = data.get('description', config.description)
        
        # Data sources
        if 'sources' in data:
            config.sources = [
                DataSourceConfig(
                    name=source_data['name'],
                    source_type=DataSource(source_data['source_type']),
                    api_key=source_data.get('api_key'),
                    api_secret=source_data.get('api_secret'),
                    base_url=source_data.get('base_url'),
                    rate_limit=source_data.get('rate_limit', 10),
                    timeout=source_data.get('timeout', 30),
                    retry_attempts=source_data.get('retry_attempts', 3),
                    enabled=source_data.get('enabled', True)
                )
                for source_data in data['sources']
            ]
        
        # Data feeds
        if 'feeds' in data:
            config.feeds = [
                DataFeedConfig(
                    symbol=feed_data['symbol'],
                    source=feed_data['source'],
                    frequency=DataFrequency(feed_data['frequency']),
                    start_date=feed_data.get('start_date'),
                    end_date=feed_data.get('end_date'),
                    fields=feed_data.get('fields', ['open', 'high', 'low', 'close', 'volume']),
                    enabled=feed_data.get('enabled', True)
                )
                for feed_data in data['feeds']
            ]
        
        # Storage configuration
        if 'storage' in data:
            storage_data = data['storage']
            config.storage = StorageConfig(
                storage_type=StorageType(storage_data.get('storage_type', config.storage.storage_type.value)),
                base_path=storage_data.get('base_path', config.storage.base_path),
                compression=storage_data.get('compression', config.storage.compression),
                max_file_size_mb=storage_data.get('max_file_size_mb', config.storage.max_file_size_mb),
                partition_by=storage_data.get('partition_by', config.storage.partition_by),
                retention_days=storage_data.get('retention_days', config.storage.retention_days),
                backup_enabled=storage_data.get('backup_enabled', config.storage.backup_enabled),
                backup_path=storage_data.get('backup_path', config.storage.backup_path)
            )
        
        # Processing configuration
        if 'processing' in data:
            proc_data = data['processing']
            config.processing = ProcessingConfig(
                enable_validation=proc_data.get('enable_validation', config.processing.enable_validation),
                enable_cleaning=proc_data.get('enable_cleaning', config.processing.enable_cleaning),
                enable_normalization=proc_data.get('enable_normalization', config.processing.enable_normalization),
                fill_missing_data=proc_data.get('fill_missing_data', config.processing.fill_missing_data),
                remove_outliers=proc_data.get('remove_outliers', config.processing.remove_outliers),
                outlier_threshold=proc_data.get('outlier_threshold', config.processing.outlier_threshold),
                enable_caching=proc_data.get('enable_caching', config.processing.enable_caching),
                cache_size_mb=proc_data.get('cache_size_mb', config.processing.cache_size_mb)
            )
        
        # Real-time configuration
        if 'real_time' in data:
            rt_data = data['real_time']
            config.real_time = RealTimeConfig(
                enable_real_time=rt_data.get('enable_real_time', config.real_time.enable_real_time),
                buffer_size=rt_data.get('buffer_size', config.real_time.buffer_size),
                update_frequency_ms=rt_data.get('update_frequency_ms', config.real_time.update_frequency_ms),
                enable_heartbeat=rt_data.get('enable_heartbeat', config.real_time.enable_heartbeat),
                heartbeat_interval_s=rt_data.get('heartbeat_interval_s', config.real_time.heartbeat_interval_s),
                reconnect_attempts=rt_data.get('reconnect_attempts', config.real_time.reconnect_attempts),
                reconnect_delay_s=rt_data.get('reconnect_delay_s', config.real_time.reconnect_delay_s)
            )
        
        # Operational settings
        config.enable_logging = data.get('enable_logging', config.enable_logging)
        config.log_level = data.get('log_level', config.log_level)
        config.enable_metrics = data.get('enable_metrics', config.enable_metrics)
        
        return config
