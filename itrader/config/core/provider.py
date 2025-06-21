"""
Configuration provider base classes and implementations.

This module provides the foundational provider classes for configuration management.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, TypeVar, Generic
from pathlib import Path
import yaml
import threading

from itrader.logger import get_itrader_logger

T = TypeVar('T')


class ConfigProvider(ABC, Generic[T]):
    """
    Abstract base class for configuration providers.
    
    Defines the interface that all configuration providers must implement.
    """
    
    def __init__(self, domain: str):
        self.domain = domain
        self.logger = get_itrader_logger().bind(component=f"ConfigProvider_{domain}")
        self._lock = threading.RLock()
    
    @abstractmethod
    def get_config(self) -> T:
        """Get current configuration."""
        pass
    
    @abstractmethod
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """Update configuration with new values."""
        pass
    
    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate configuration data."""
        pass
    
    @abstractmethod
    def reset_to_defaults(self) -> bool:
        """Reset configuration to defaults."""
        pass


class FileConfigProvider(ConfigProvider[Dict[str, Any]]):
    """
    File-based configuration provider that reads from YAML files.
    """
    
    def __init__(self, domain: str, config_dir: str = "settings"):
        super().__init__(domain)
        self.config_dir = Path(config_dir)
        self._config_cache: Optional[Dict[str, Any]] = None
        self._last_modified: Optional[float] = None
    
    @property
    def config_file(self) -> Path:
        """Get the configuration file path for this domain."""
        return self.config_dir / f"{self.domain}.yaml"
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration from file."""
        with self._lock:
            self._refresh_cache()
            return self._config_cache.copy() if self._config_cache else {}
    
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """Update configuration and save to file."""
        try:
            with self._lock:
                current_config = self.get_config()
                current_config.update(updates)
                
                if self.validate_config(current_config):
                    self._save_config(current_config)
                    self._config_cache = current_config
                    return True
                return False
                
        except Exception as e:
            self.logger.error("Failed to update config", error=str(e))
            return False
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Basic validation - can be overridden by subclasses."""
        return isinstance(config, dict)
    
    def reset_to_defaults(self) -> bool:
        """Reset to defaults by removing the config file."""
        try:
            if self.config_file.exists():
                self.config_file.unlink()
            
            with self._lock:
                self._config_cache = None
                self._last_modified = None
            
            return True
            
        except Exception as e:
            self.logger.error("Failed to reset config", error=str(e))
            return False
    
    def _refresh_cache(self):
        """Refresh configuration cache if file has changed."""
        if not self.config_file.exists():
            return
        
        try:
            current_mtime = self.config_file.stat().st_mtime
            
            if self._last_modified is None or current_mtime > self._last_modified:
                with open(self.config_file, 'r') as f:
                    self._config_cache = yaml.safe_load(f) or {}
                self._last_modified = current_mtime
                
        except Exception as e:
            self.logger.error("Failed to refresh config cache", error=str(e))
    
    def _save_config(self, config: Dict[str, Any]):
        """Save configuration to file."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, indent=2)


class RuntimeConfigProvider(ConfigProvider[Dict[str, Any]]):
    """
    Runtime configuration provider that keeps config in memory.
    """
    
    def __init__(self, domain: str, initial_config: Optional[Dict[str, Any]] = None):
        super().__init__(domain)
        self._config = initial_config or {}
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration from memory."""
        with self._lock:
            return self._config.copy()
    
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """Update configuration in memory."""
        try:
            with self._lock:
                new_config = self._config.copy()
                new_config.update(updates)
                
                if self.validate_config(new_config):
                    self._config = new_config
                    return True
                return False
                
        except Exception as e:
            self.logger.error("Failed to update runtime config", error=str(e))
            return False
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Basic validation."""
        return isinstance(config, dict)
    
    def reset_to_defaults(self) -> bool:
        """Reset to empty configuration."""
        with self._lock:
            self._config = {}
            return True
