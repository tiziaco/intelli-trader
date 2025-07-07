# intelliTrader

iTrader is a powerful algorithmic trading framework designed for both backtesting and live execution of trading strategies. Built on an event-driven architecture, it provides a flexible and modular environment for developing and deploying automated trading strategies.

### Key Features

- **Event-Driven Architecture:** iTrader's robust event-driven design ensures efficient and responsive strategy execution with clean separation between components.
- **Advanced Data Pipeline:** Download, parse, and store price data from any exchange with support for multiple timeframes and real-time streaming.
- **Dynamic Market Screener:** Define and apply custom market screeners to identify and trade on the most opportune assets with configurable filtering criteria.
- **Multi-Strategy Support:** Run multiple trading strategies concurrently, each associated with a dedicated portfolio. Generate signals when all conditions are met with sophisticated signal aggregation.
- **Integrated Risk Management:** Multi-layered risk controls including position sizing, exposure limits, and real-time portfolio monitoring.
- **SQL Database Integration:** Efficient storage and retrieval of historical and real-time data with optimized queries for backtesting and analysis.

### Core Trading Modules

- **Order Handler:** 
  - Centralized order orchestration with OrderManager for streamlined processing
  - Support for Market, Stop-Loss, and Take-Profit orders with configurable execution modes
  - True One-Cancels-Other (OCO) functionality for professional risk management
  - Complete audit trail with SQL-like order storage for regulatory compliance
  - Real-time order validation and risk management controls

- **Portfolio Handler:**
  - Modern four-manager architecture: CashManager, PositionManager, TransactionManager, and MetricsManager
  - Robust cash management with strict validation and decimal precision calculations
  - Comprehensive position management supporting both long and short positions
  - Real-time performance tracking with advanced metrics and risk analytics
  - Thread-safe operations with concurrent portfolio management capabilities

- **Execution Handler:**
  - Multi-exchange execution support with health monitoring and error handling
  - Configurable execution modes for both live trading and backtesting scenarios
  - Comprehensive slippage modeling and transaction cost analysis
  - Detailed execution result tracking with metadata for performance analysis
  - Robust error recovery and retry mechanisms for production environments

<img width="1070" alt="itrader_architecture_1" src="https://github.com/tiziaco/intelli-trader/assets/112805643/28dd5057-a8a1-48ed-8acd-885e2cb16af1">

At the heart of iTrader lies an event-driven architecture. This means components communicate by publishing and subscribing to events. More specifically, publishers place events in a message queue (FIFO), then the event broker pull messages from the queue and send it to the designated event consumer when they are ready to process them.

### Installation

```bash
pip install git+https://github.com/tiziaco/intelli-trader.git
```
