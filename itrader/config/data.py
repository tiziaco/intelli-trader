"""Data domain configuration (Pydantic v2, M2-06 / D-01..D-03).

Replaces the deleted hand-rolled ``config/data/`` package. Not exercised on the golden
backtest path (CSV feed reads directly); kept as a typed model for the public surface.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DataSource(str, Enum):
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


class DataFrequency(str, Enum):
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


class StorageType(str, Enum):
    """Data storage types."""

    MEMORY = "memory"
    CSV = "csv"
    PARQUET = "parquet"
    HDF5 = "hdf5"
    DATABASE = "database"
    REDIS = "redis"


class DataSourceConfig(BaseModel):
    """Configuration for a data source."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source_type: DataSource
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit: int = 10
    timeout: int = 30
    retry_attempts: int = 3
    enabled: bool = True


class DataFeedConfig(BaseModel):
    """Configuration for a data feed."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    source: str
    frequency: DataFrequency
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    fields: List[str] = Field(
        default_factory=lambda: ["open", "high", "low", "close", "volume"]
    )
    enabled: bool = True


class StorageConfig(BaseModel):
    """Data storage configuration."""

    model_config = ConfigDict(extra="forbid")

    storage_type: StorageType = StorageType.PARQUET
    base_path: str = "data"
    compression: str = "snappy"
    max_file_size_mb: int = 100
    partition_by: Optional[str] = "date"
    retention_days: Optional[int] = None
    backup_enabled: bool = False
    backup_path: Optional[str] = None


class ProcessingConfig(BaseModel):
    """Data processing configuration."""

    model_config = ConfigDict(extra="forbid")

    enable_validation: bool = True
    enable_cleaning: bool = True
    enable_normalization: bool = False
    fill_missing_data: bool = True
    remove_outliers: bool = False
    outlier_threshold: float = 3.0
    enable_caching: bool = True
    cache_size_mb: int = 500


class RealTimeConfig(BaseModel):
    """Real-time data configuration."""

    model_config = ConfigDict(extra="forbid")

    enable_real_time: bool = False
    buffer_size: int = 1000
    update_frequency_ms: int = 1000
    enable_heartbeat: bool = True
    heartbeat_interval_s: int = 30
    reconnect_attempts: int = 5
    reconnect_delay_s: int = 5


class DataConfig(BaseModel):
    """Main data configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Default Data Config"
    description: str = ""
    sources: List[DataSourceConfig] = Field(default_factory=list)
    feeds: List[DataFeedConfig] = Field(default_factory=list)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    real_time: RealTimeConfig = Field(default_factory=RealTimeConfig)
    enable_logging: bool = True
    log_level: str = "INFO"
    enable_metrics: bool = True

    @classmethod
    def default(cls) -> "DataConfig":
        """Default data config."""
        return cls()
