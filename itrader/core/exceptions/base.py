"""
Base exception classes for the iTrader system.
"""

import uuid
from typing import Optional


class ITraderError(Exception):
    """Base exception for all iTrader system errors."""
    pass


class ValidationError(ITraderError):
    """Base exception for validation errors."""
    
    def __init__(self, field: str, value: Optional[str] = None, message: Optional[str] = None):
        self.field = field
        self.value = value
        error_msg = f"Validation error for field '{field}'"
        if value:
            error_msg += f" with value '{value}'"
        if message:
            error_msg += f": {message}"
        super().__init__(error_msg)


class ConfigurationError(ITraderError):
    """Base exception for configuration errors."""

    def __init__(self, config_key: Optional[str] = None, config_value: Optional[object] = None, reason: Optional[str] = None):
        self.config_key = config_key
        self.config_value = config_value
        self.reason = reason
        message = "Configuration error"
        if config_key:
            message += f" for '{config_key}'"
        if config_value:
            message += f" with value '{config_value}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class StateError(ITraderError):
    """Base exception for invalid state transitions or operations."""
    
    def __init__(self, entity_id: uuid.UUID | int | str, current_state: str, required_state: Optional[str] = None, operation: Optional[str] = None):
        self.entity_id = entity_id
        self.current_state = current_state
        self.required_state = required_state
        self.operation = operation
        
        message = f"Entity {entity_id} is in state '{current_state}'"
        if operation:
            message += f" but operation '{operation}' is not allowed"
        if required_state:
            message += f" (requires state '{required_state}')"
        super().__init__(message)


class NotFoundError(ITraderError):
    """Base exception for entity not found errors."""
    
    def __init__(self, entity_type: str, entity_id: Optional[uuid.UUID | int | str] = None, identifier: Optional[str] = None):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.identifier = identifier
        message = f"{entity_type} not found"
        if entity_id:
            message += f" with ID {entity_id}"
        elif identifier:
            message += f" with identifier '{identifier}'"
        super().__init__(message)
