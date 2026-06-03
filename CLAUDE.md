# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

iTrader is an event-driven algorithmic trading framework for backtesting and live execution. All components communicate through a shared FIFO event queue rather than direct calls. Python 3.13, managed with Poetry.

## Commands

Environment setup (uses pyenv + Poetry, installs `.venv` in-project):
```bash
make init-env
```

Tests (all run through Poetry):
```bash
make test              # full suite
make test-unit         # only -m "unit"
make test-integration  # only -m "integration"
make test-portfolio    # test/test_portfolio_handler/
make test-orders       # test/test_order_handler/
make test-execution    # test/test_execution_handler/
make test-events       # test/test_events/
make test-strategy     # test/test_strategy/
make test-cov          # coverage -> opens htmlcov/index.html
make test-watch        # pytest-watch
```

Run a single test file / case:
```bash
poetry run pytest test/test_order_handler/test_order.py -v
poetry run pytest test/test_order_handler/test_order.py -k "test_name" -v
```

`run_tests.py` is an alternative runner (`python run_tests.py unit -x`, etc.).

**Test gotcha:** `pyproject.toml` sets `filterwarnings = ["error", ...]` and `--strict-markers`/`--strict-config`. Any unexpected warning fails the test, and every marker used must be declared in the `markers` list (unit, integration, slow, portfolio, events, orders, execution, strategy).

## Architecture

### Event-driven core

Everything flows through a single `global_queue` (`queue.Queue`). `events_handler/full_event_handler.py::EventHandler.process_events()` drains the queue and dispatches each event by `EventType`. Events are dataclasses in `events_handler/event.py`, each carrying a class-level `type` attribute. The canonical flow:

```
PING   -> screeners_handler.screen_markets + universe.generate_bar_event
BAR    -> portfolio_handler.update_portfolios_market_value
        + order_handler.process_orders_on_market_data   (stop/limit triggers)
        + strategies_handler.calculate_signals
SIGNAL -> order_handler.on_signal                       (validate + size -> OrderEvent)
ORDER  -> execution_handler.on_order                    (-> FillEvent)
FILL   -> portfolio_handler.on_fill                     (update positions/cash)
```

Adding a new event type means: define the dataclass in `event.py`, add it to the `EventType` enum, and add a branch in `process_events()`.

### Two run modes, same components

Both wire up the identical component graph around one shared queue in their `__init__`:
- `trading_system/backtest_trading_system.py::TradingSystem` — synchronous `for` loop over a `PingGenerator`, uses in-memory order storage.
- `trading_system/live_trading_system.py::LiveTradingSystem` — processes the queue on a background thread with start/stop/status lifecycle. `trading_system/trading_interface.py::TradingInterface` is the bridge between an external/web API and the live system (order creation, validation, status).

### Handlers (each owns a domain, talks via the queue)

- **order_handler/** — `OrderHandler` is a thin interface layer; all business logic (signal-to-order, lifecycle, modify/cancel, OCO) lives in `OrderManager`. Validation via `EnhancedOrderValidator`. Persistence is pluggable through `OrderStorageFactory` (`in_memory` for backtest, `postgresql` for live) under `order_handler/storage/`.
- **portfolio_handler/** — `PortfolioHandler` manages portfolio lifecycle; each `Portfolio` delegates to four managers: `CashManager`, `PositionManager`, `TransactionManager`, `MetricsManager`. Thread-safe via `readerwriterlock`.
- **execution_handler/** — `ExecutionHandler` with pluggable `fee_model/`, `slippage_model/`, and `exchanges/` (e.g. `simulated`). Turns `OrderEvent` into `FillEvent`.
- **strategy_handler/** — `StrategiesHandler` runs strategies; each combines a `position_sizer/`, `risk_manager/`, and `sltp_models/`. Concrete strategies live in `strategy_handler/my_strategies/` (gitignored at the top level but present in-tree).
- **screeners_handler/** & **universe/** — dynamic market screening and the tradable symbol universe.
- **price_handler/** — data download/storage (CCXT, OANDA exchanges; Binance live streaming; SQL via SQLAlchemy).

### Configuration system

`itrader/config/` is a domain-based config system: `core/` provides `ConfigRegistry` / `ConfigProvider` / validators; domains are `portfolio`, `trading`, `data`, `system`, `exchange`. Access via the convenience getters in `config/__init__.py` (`get_config_registry`, `get_portfolio_config_provider`, etc.). YAML config is loaded from the `settings/` directory (gitignored).

**Import side effects:** `itrader/__init__.py` initializes process-wide singletons on import — `config`, `logger` (structlog, via `init_logger`), and `idgen` (`IDGenerator`). Modules import these directly (`from itrader import config, idgen`). Get a bound logger with `get_itrader_logger().bind(component="...")`.

### Shared core

`core/enums/` (OrderType, OrderStatus + `VALID_ORDER_TRANSITIONS`, portfolio/execution enums) and `core/exceptions/` hold the cross-cutting types used by all handlers. Use the enum maps (e.g. `order_type_map`) to convert string inputs to enums.

## Conventions

- Source uses **tab indentation** in most handler modules (config/ and some newer modules use spaces — match the file you edit).
- Components are constructed with the `global_queue` as a constructor argument and never call each other directly across domains — emit an event instead.
