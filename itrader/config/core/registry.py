"""
Configuration registry for managing domain-specific configurations.

This module provides a centralized registry for configuration management
across different domains (portfolio, trading, data, system).
"""

import threading
from typing import Dict, Any, Optional
from pathlib import Path

from .provider import ConfigProvider, FileConfigProvider
from .validator import ConfigValidator
from itrader.logger import get_itrader_logger


class ConfigRegistry:
    """
    Central registry for domain-specific configuration management.
    
    This registry manages configuration providers for different domains
    and provides a unified interface for configuration operations.
    """
    
    def __init__(self, config_dir: str = "settings"):
        self.config_dir = Path(config_dir)
        self.logger = get_itrader_logger().bind(component="ConfigRegistry")
        self._lock = threading.RLock()
        
        # Domain providers
        self._providers: Dict[str, ConfigProvider] = {}
        self._validators: Dict[str, ConfigValidator] = {}
        
        # Ensure config directory exists
        self.config_dir.mkdir(exist_ok=True)
        
        self.logger.info("ConfigRegistry initialized", config_dir=str(self.config_dir))
    
    def register_domain(self, domain: str, provider: Optional[ConfigProvider] = None) -> ConfigProvider:
        """
        Register a domain with its configuration provider.
        
        Args:
            domain: Domain name (e.g., 'portfolio', 'trading', 'data', 'system')
            provider: Optional custom provider, defaults to FileConfigProvider
            
        Returns:
            The registered configuration provider
        """
        with self._lock:
            if provider is None:
                provider = FileConfigProvider(domain, str(self.config_dir))
            
            self._providers[domain] = provider
            self.logger.info("Domain registered", domain=domain, provider_type=type(provider).__name__)
            
            return provider
    
    def get_provider(self, domain: str) -> ConfigProvider:
        """
        Get configuration provider for a domain.
        
        Args:
            domain: Domain name
            
        Returns:
            Configuration provider for the domain
            
        Raises:
            ValueError: If domain is not registered
        """
        with self._lock:
            if domain not in self._providers:
                # Auto-register with default provider
                return self.register_domain(domain)
            
            return self._providers[domain]
    
    def register_validator(self, domain: str, validator: ConfigValidator):
        """Register a validator for a domain."""
        with self._lock:
            self._validators[domain] = validator
            self.logger.info("Validator registered", domain=domain)
    
    def get_validator(self, domain: str) -> Optional[ConfigValidator]:
        """Get validator for a domain."""
        return self._validators.get(domain)
    
    def get_config(self, domain: str) -> Dict[str, Any]:
        """Get configuration for a domain."""
        provider = self.get_provider(domain)
        return provider.get_config()
    
    def update_config(self, domain: str, updates: Dict[str, Any]) -> bool:
        """Update configuration for a domain."""
        provider = self.get_provider(domain)
        
        # Validate if validator exists
        validator = self.get_validator(domain)
        if validator:
            current_config = provider.get_config()
            current_config.update(updates)
            
            validation_result = validator.validate(current_config)
            if not validation_result.is_valid:
                self.logger.error("Config validation failed", 
                                domain=domain, 
                                errors=[e.message for e in validation_result.errors])
                return False
        
        return provider.update_config(updates)
    
    def reset_domain(self, domain: str) -> bool:
        """Reset a domain to its defaults."""
        provider = self.get_provider(domain)
        return provider.reset_to_defaults()
    
    def list_domains(self) -> list[str]:
        """List all registered domains."""
        with self._lock:
            return list(self._providers.keys())
    
    def reset_all(self):
        """Reset all domains and clear registry."""
        with self._lock:
            for domain in list(self._providers.keys()):
                self.reset_domain(domain)
            
            self._providers.clear()
            self._validators.clear()
            
            self.logger.info("Registry reset completed")
