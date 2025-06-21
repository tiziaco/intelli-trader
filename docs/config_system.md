# iTrader Configuration System

## Overview

The iTrader configuration system has been refactored to use a clean, domain-based architecture that provides better separation of concerns, maintainability, and flexibility.

## Directory Structure

```
itrader/config/
├── core/
│   ├── __init__.py          # Core infrastructure exports
│   ├── registry.py          # Central configuration registry
│   ├── provider.py          # Configuration providers (File, Runtime)
│   └── validator.py         # Configuration validation framework
├── portfolio/
│   ├── __init__.py          # Portfolio domain exports
│   ├── config.py            # Portfolio configuration classes
│   ├── schema.py            # Portfolio validation schemas
│   └── defaults.py          # Portfolio presets and defaults
├── trading/
│   ├── __init__.py          # Trading domain exports
│   ├── config.py            # Trading configuration classes
│   └── schema.py            # Trading validation schemas
├── data/
│   ├── __init__.py          # Data domain exports
│   └── config.py            # Data source and feed configurations
├── system/
│   ├── __init__.py          # System domain exports
│   ├── config.py            # System-level configurations
│   └── logging_config.py    # Specialized logging configuration
└── __init__.py              # Main configuration module exports
```

## Core Components

### 1. Configuration Registry

The `ConfigRegistry` class provides centralized management of domain-specific configurations:

```python
from itrader.config import get_config_registry

# Get the global registry
registry = get_config_registry("settings")

# Access domain-specific providers
portfolio_provider = registry.get_provider("portfolio")
trading_provider = registry.get_provider("trading")
```

### 2. Configuration Providers

Providers handle configuration storage and retrieval:

- **FileConfigProvider**: Reads/writes YAML files
- **RuntimeConfigProvider**: In-memory configuration management

```python
from itrader.config import FileConfigProvider

provider = FileConfigProvider("portfolio", "settings")
config = provider.get_config()
provider.update_config({"name": "Updated Portfolio"})
```

### 3. Domain Configurations

Each domain has its own configuration classes and presets:

#### Portfolio Configuration

```python
from itrader.config import PortfolioConfig, get_portfolio_preset

# Create from preset
conservative_config = get_portfolio_preset('conservative')

# Create custom configuration
config = PortfolioConfig(
    name="My Portfolio",
    initial_capital=Decimal('100000'),
    base_currency="USD"
)

# Convert to/from dictionary
config_dict = config.to_dict()
config_from_dict = PortfolioConfig.from_dict(config_dict)
```

#### Trading Configuration

```python
from itrader.config import TradingConfig, ExecutionMode

config = TradingConfig(
    enable_trading=True,
    execution=ExecutionSettings(
        mode=ExecutionMode.SIMULATION,
        max_orders_per_second=10
    )
)
```

#### Data Configuration

```python
from itrader.config import DataConfig, DataSource

config = DataConfig(
    sources=[
        DataSourceConfig(
            name="binance",
            source_type=DataSource.BINANCE,
            api_key="your_key"
        )
    ]
)
```

#### System Configuration

```python
from itrader.config import SystemConfig, Environment

config = SystemConfig(
    environment=Environment.PRODUCTION,
    performance=PerformanceSettings(
        max_threads=20,
        enable_caching=True
    )
)
```

## Usage Examples

### Basic Configuration Access

```python
from itrader.config import get_config_registry

# Initialize registry
registry = get_config_registry()

# Get configuration for any domain
portfolio_config = registry.get_config("portfolio")
trading_config = registry.get_config("trading")

# Update configuration
registry.update_config("portfolio", {"name": "New Portfolio"})
```

### Using Convenience Functions

```python
from itrader.config import (
    get_portfolio_config_provider,
    get_trading_config_provider,
    get_data_config_provider,
    get_system_config_provider
)

# Get domain-specific providers directly
portfolio_provider = get_portfolio_config_provider()
config = portfolio_provider.get_config()
```

### Portfolio Presets

```python
from itrader.config import get_portfolio_preset, list_available_presets

# List available presets
presets = list_available_presets()
# ['default', 'conservative', 'moderate', 'aggressive', 'crypto']

# Get specific preset
aggressive_config = get_portfolio_preset('aggressive')
crypto_config = get_portfolio_preset('crypto')
```

### Configuration Validation

```python
from itrader.config import validate_portfolio_config, validate_trading_config

# Validate configurations
portfolio_data = {"name": "Test", "base_currency": "USD"}
is_valid = validate_portfolio_config(portfolio_data)

trading_data = {"enable_trading": True, "execution": {"mode": "simulation"}}
is_valid = validate_trading_config(trading_data)
```

## Configuration Files

The system automatically creates YAML configuration files in the specified settings directory:

- `portfolio.yaml` - Portfolio domain configuration
- `trading.yaml` - Trading domain configuration  
- `data.yaml` - Data domain configuration
- `system.yaml` - System domain configuration

Example `portfolio.yaml`:
```yaml
name: "My Portfolio"
portfolio_type: "equity"
base_currency: "USD"
initial_capital: "100000.0"
limits:
  max_positions: 50
  max_position_value: "1000000.0"
  max_portfolio_concentration: 0.25
risk_management:
  enable_stop_loss: true
  default_stop_loss_pct: 0.05
  risk_level: "moderate"
```

## Migration from Old System

The new system is **not backward compatible** by design. Key changes:

1. **Domain-based structure**: Configurations are organized by domain instead of modules
2. **Simplified API**: Cleaner, more intuitive configuration access
3. **Type safety**: Strong typing with dataclasses and enums
4. **Validation**: Built-in validation for configuration data
5. **Presets**: Pre-defined configuration presets for common use cases

### Updating Existing Code

**Before:**
```python
from itrader.config import get_portfolio_handler_config, PortfolioHandlerConfig
config = get_portfolio_handler_config()
```

**After:**
```python
from itrader.config import get_portfolio_config_provider
provider = get_portfolio_config_provider()
config = provider.get_config()
```

## Best Practices

1. **Use presets**: Start with built-in presets and customize as needed
2. **Validate configurations**: Always validate configuration data before use
3. **Use type-safe classes**: Prefer configuration objects over raw dictionaries
4. **Centralized access**: Use the registry for consistent configuration management
5. **Environment-specific configs**: Use different settings directories for different environments

## Testing

The configuration system includes comprehensive tests:

```bash
# Run configuration system tests
python test_new_config.py
```

This tests:
- Core infrastructure functionality
- Domain configuration loading
- Configuration updates and validation
- PortfolioHandler integration
- Configuration presets and defaults

## Performance

The new system is designed for performance:
- **Lazy loading**: Configurations are loaded only when needed
- **Caching**: File-based providers cache loaded configurations
- **Thread safety**: All operations are thread-safe
- **Minimal overhead**: Lightweight provider pattern

## Extension

To add new configuration domains:

1. Create a new domain directory under `itrader/config/`
2. Implement configuration classes with `to_dict()` and `from_dict()` methods
3. Add validation schemas and default values
4. Export classes in the domain's `__init__.py`
5. Add imports to the main `config/__init__.py`

The system will automatically create providers and handle file operations for new domains.
