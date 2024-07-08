# intelliTrader

iTrader is a powerful algorithmic trading framework designed for both backtesting and live execution of trading strategies. Built on an event-driven architecture, it provides a flexible and modular environment for developing and deploying automated trading strategies.

### Key Features

- **Event-Driven Architecture:** iTrader's robust event-driven design ensures efficient and responsive strategy execution.
- **Data pipeline:** download, parse and store price data from any exchange.
- **Dynamic Market Screener:** Define and apply custom market screeners to identify and trade on the most opportune asset.
- **Multi-Strategy Support:** Run multiple trading strategies concurrently, each associated to a portfolio. Generate a signal when all conditions are met.
- **Integrated Risk Management:** Utilize an integrated risk management tool to control and optimize trading exposure.
- **Order and Portfolio Management:** Seamlessly manage stop and limit orders for a streamlined trading experience.
- **Execution management:** Virtually execute the orders validated by the order handler
- **Portfolio tracking:** handle the transactions validated by the execution handler. Track open and closed positions and store the equity data. Multiple portfolios can be set up.
- **SQL Database Integration:** Store and access historical and real-time data efficiently in a SQL database.

<img width="1070" alt="itrader_architecture_1" src="https://github.com/tiziaco/intelli-trader/assets/112805643/28dd5057-a8a1-48ed-8acd-885e2cb16af1">

At the heart of iTrader lies an event-driven architecture. This means components communicate by publishing and subscribing to events. More specifically, publishers place events in a message queue (FIFO), then the event broker pull messages from the queue and send it to the designated event consumer when they are ready to process them.

### Installation

```bash
pip install git+https://github.com/tiziaco/intelli-trader.git
```
---
