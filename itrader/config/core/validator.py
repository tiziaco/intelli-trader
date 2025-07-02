"""
Configuration validation framework.

This module provides validation capabilities for configuration data.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import threading

from itrader.logger import get_itrader_logger


class ValidationError(Exception):
    """Exception raised when configuration validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(message)


class ValidationResult:
    """Result of configuration validation."""
    
    def __init__(self, is_valid: bool = True, errors: Optional[List[ValidationError]] = None):
        self.is_valid = is_valid
        self.errors = errors or []
    
    def add_error(self, error: ValidationError):
        """Add a validation error."""
        self.errors.append(error)
        self.is_valid = False
    
    def __bool__(self):
        return self.is_valid


class ConfigValidator(ABC):
    """Abstract base class for configuration validators."""
    
    def __init__(self, domain: str):
        self.domain = domain
        self.logger = get_itrader_logger().bind(component=f"ConfigValidator_{domain}")
    
    @abstractmethod
    def validate(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate configuration data."""
        pass


class SchemaValidator(ConfigValidator):
    """Schema-based configuration validator."""
    
    def __init__(self, domain: str, schema: Dict[str, Any]):
        super().__init__(domain)
        self.schema = schema
    
    def validate(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate configuration against schema."""
        result = ValidationResult()
        
        try:
            self._validate_dict(config, self.schema, result)
        except Exception as e:
            result.add_error(ValidationError(f"Schema validation failed: {str(e)}"))
        
        return result
    
    def _validate_dict(self, config: Dict[str, Any], schema: Dict[str, Any], result: ValidationResult, path: str = ""):
        """Recursively validate dictionary against schema."""
        for key, expected_type in schema.items():
            full_path = f"{path}.{key}" if path else key
            
            if key not in config:
                result.add_error(ValidationError(f"Missing required field: {full_path}", field=key))
                continue
            
            value = config[key]
            
            if isinstance(expected_type, type):
                if not isinstance(value, expected_type):
                    result.add_error(ValidationError(
                        f"Field {full_path} must be of type {expected_type.__name__}, got {type(value).__name__}",
                        field=key, value=value
                    ))
            elif isinstance(expected_type, dict):
                if isinstance(value, dict):
                    self._validate_dict(value, expected_type, result, full_path)
                else:
                    result.add_error(ValidationError(
                        f"Field {full_path} must be a dictionary, got {type(value).__name__}",
                        field=key, value=value
                    ))


class BusinessValidator(ConfigValidator):
    """Business logic validator for configuration data."""
    
    def __init__(self, domain: str, validation_rules: List[callable]):
        super().__init__(domain)
        self.validation_rules = validation_rules
    
    def validate(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate configuration using business rules."""
        result = ValidationResult()
        
        for rule in self.validation_rules:
            try:
                rule_result = rule(config)
                if isinstance(rule_result, ValidationResult):
                    if not rule_result.is_valid:
                        result.errors.extend(rule_result.errors)
                        result.is_valid = False
                elif rule_result is False:
                    result.add_error(ValidationError(f"Business rule {rule.__name__} failed"))
            except Exception as e:
                result.add_error(ValidationError(f"Business rule {rule.__name__} raised exception: {str(e)}"))
        
        return result
