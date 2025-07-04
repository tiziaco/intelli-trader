"""
Exchange configuration validation schemas.

This module provides validation schemas and functions for exchange configurations,
ensuring data integrity and proper parameter validation.
"""

from typing import Dict, Any, List
from ..core import ValidationResult, SchemaValidator, BusinessValidator


# Base schema for exchange configuration
EXCHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "exchange_type": {
            "type": "string",
            "enum": ["simulated", "binance", "coinbase", "kraken"]
        },
        "exchange_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100
        },
        "fee_model": {
            "type": "object",
            "properties": {
                "model_type": {
                    "type": "string",
                    "enum": ["zero", "no_fee", "percent", "maker_taker", "tiered"]
                },
                "fee_rate": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "maker_rate": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "taker_rate": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "tiers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "min_volume": {"type": "number", "minimum": 0},
                            "max_volume": {"type": "number", "minimum": 0},
                            "fee_rate": {"type": "number", "minimum": 0, "maximum": 1}
                        },
                        "required": ["min_volume", "max_volume", "fee_rate"]
                    }
                }
            },
            "required": ["model_type"]
        },
        "slippage_model": {
            "type": "object",
            "properties": {
                "model_type": {
                    "type": "string",
                    "enum": ["none", "zero", "linear", "fixed"]
                },
                "slippage_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "base_slippage_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "size_impact_factor": {
                    "type": "number",
                    "minimum": 0
                },
                "max_slippage_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "random_variation": {
                    "type": "boolean"
                }
            },
            "required": ["model_type"]
        },
        "limits": {
            "type": "object",
            "properties": {
                "min_order_size": {
                    "type": "number",
                    "minimum": 0
                },
                "max_order_size": {
                    "type": "number",
                    "minimum": 0
                },
                "max_price": {
                    "type": "number",
                    "minimum": 0
                },
                "supported_symbols": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "pattern": "^[A-Z0-9]+$"
                    },
                    "minItems": 1
                }
            }
        },
        "failure_simulation": {
            "type": "object",
            "properties": {
                "simulate_failures": {
                    "type": "boolean"
                },
                "failure_rate": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                },
                "enabled_scenarios": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["network_timeout", "exchange_maintenance", "rate_limit", "execution_timeout"]
                    }
                }
            }
        },
        "connection": {
            "type": "object",
            "properties": {
                "auto_connect": {
                    "type": "boolean"
                },
                "connection_timeout": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 300
                },
                "retry_attempts": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10
                },
                "retry_delay": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 60
                }
            }
        },
        "metadata": {
            "type": "object"
        }
    },
    "required": ["exchange_type", "exchange_name", "fee_model", "slippage_model"]
}


class ExchangeBusinessValidator(BusinessValidator):
    """Business logic validator for exchange configurations."""
    
    def validate(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate exchange configuration business rules."""
        errors = []
        warnings = []
        
        # Validate fee model consistency
        fee_model = data.get("fee_model", {})
        fee_type = fee_model.get("model_type")
        
        if fee_type == "percent" and not fee_model.get("fee_rate"):
            errors.append("Percent fee model requires fee_rate parameter")
        
        if fee_type == "maker_taker":
            if not fee_model.get("maker_rate") or not fee_model.get("taker_rate"):
                errors.append("Maker-taker fee model requires both maker_rate and taker_rate")
        
        if fee_type == "tiered" and not fee_model.get("tiers"):
            errors.append("Tiered fee model requires tiers configuration")
        
        # Validate slippage model consistency
        slippage_model = data.get("slippage_model", {})
        slippage_type = slippage_model.get("model_type")
        
        if slippage_type == "linear":
            if not slippage_model.get("base_slippage_pct"):
                warnings.append("Linear slippage model should specify base_slippage_pct")
        
        if slippage_type == "fixed" and not slippage_model.get("slippage_pct"):
            errors.append("Fixed slippage model requires slippage_pct parameter")
        
        # Validate order size limits
        limits = data.get("limits", {})
        min_size = limits.get("min_order_size")
        max_size = limits.get("max_order_size")
        
        if min_size is not None and max_size is not None and min_size >= max_size:
            errors.append("min_order_size must be less than max_order_size")
        
        # Validate failure simulation
        failure_sim = data.get("failure_simulation", {})
        if failure_sim.get("simulate_failures", False):
            failure_rate = failure_sim.get("failure_rate", 0)
            if failure_rate > 0.1:  # 10%
                warnings.append("High failure rate may significantly impact trading performance")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )


def validate_exchange_config(config_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate exchange configuration data.
    
    Parameters
    ----------
    config_data : Dict[str, Any]
        Exchange configuration data to validate
        
    Returns
    -------
    ValidationResult
        Validation result with errors and warnings
    """
    # Schema validation
    schema_validator = SchemaValidator(EXCHANGE_SCHEMA)
    schema_result = schema_validator.validate(config_data)
    
    if not schema_result.is_valid:
        return schema_result
    
    # Business logic validation
    business_validator = ExchangeBusinessValidator()
    business_result = business_validator.validate(config_data)
    
    # Combine results
    all_errors = (schema_result.errors or []) + (business_result.errors or [])
    all_warnings = (schema_result.warnings or []) + (business_result.warnings or [])
    
    return ValidationResult(
        is_valid=len(all_errors) == 0,
        errors=all_errors if all_errors else None,
        warnings=all_warnings if all_warnings else None
    )


def get_exchange_schema() -> Dict[str, Any]:
    """Get the exchange configuration schema."""
    return EXCHANGE_SCHEMA.copy()
