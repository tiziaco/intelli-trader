---
phase: 04-composition-config-interface
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/merge.py
  - itrader/config/order.py
  - itrader/core/commission_estimator.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/execution_handler.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/reporting/summary.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/__init__.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/system_spec.py
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-12
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 4 adds the engine-level composition API (`build_backtest_system` / `compose_engine` / `BacktestRunner` / `SystemSpec`), the `OrderConfig` Pydantic model, the `CommissionEstimator` Protocol with its `FeeModelCommissionEstimator` late-binding adapter, and a uniform `update_config(dict) -> None` surface across 7 handlers via the shared `config/merge.py` deep-merge.

The structural design is sound. The `compose_engine` seam is correctly mode-agnostic (D-14a), containing no backtest/live backend strings. The `FeeModelCommissionEstimator` reads `exchange.fee_model` at call time, not at construction — late binding is implemented correctly. The `deep_merge` correctly preserves sibling keys. All `update_config` implementations follow the canonical deep_merge -> model_validate -> atomic-swap -> ConfigurationError-wrap contract. The `_seed_supported_symbols` factory path correctly seeds the complete symbol set at construction time, making `_supported_symbols` replacement-safe across subsequent `update_config` calls (PATTERNS-A2). The `OrderConfig` model_dump/model_validate Enum round-trip is confirmed correct.

No correctness bugs, security vulnerabilities, or data-loss risks were found. Four warnings and three info items are surfaced below.

---

## Warnings

### WR-01: `failure_rate` cached as `float` — inconsistent with Decimal-first policy

**File:** `itrader/execution_handler/exchanges/simulated.py:81` (also line 648)
**Issue:** `self.failure_rate = float(self.config.failure_simulation.failure_rate)` converts a `Decimal` field to `float` for local caching. While `failure_rate` is a probability (not money), the project's Decimal-first policy is applied to all numeric fields in the config domain. The float cache is re-derived in `update_config` (line 648), so it is not stale after a reconfigure. However, this is an inconsistency: every other `ExchangeLimits` / `FailureSimulation` field is compared or stored as `Decimal`, but this one is narrowed to float and compared against `self._rng.random()` (which itself is `float`). The comparison works correctly at runtime but introduces a policy exception that is not documented.
**Fix:** Store the comparison threshold as `Decimal` and compare via the Decimal path, or at minimum document this as an intentional edge at the `rng.random()` float boundary:
```python
# keep as Decimal — compare against Decimal("...") cast of rng output at call site
self.failure_rate: Decimal = self.config.failure_simulation.failure_rate
# ... at use site:
if self.simulate_failures and Decimal(str(self._rng.random())) < self.failure_rate:
```
Or, if the float cast is accepted as an intentional probability-boundary edge (not money), add an inline comment citing the exception, analogous to the `float()` serialization-edge comments elsewhere in the codebase.

---

### WR-02: `order_value < 1.0` compares `Decimal` to float literal

**File:** `itrader/execution_handler/exchanges/simulated.py:407`
**Issue:** `order_value = event.quantity * event.price` yields a `Decimal`. The comparison `order_value < 1.0` mixes `Decimal` with a float literal `1.0`. Python's `Decimal.__lt__(float)` works at runtime (returns a correct boolean without raising), but the comparison bypasses the project's Decimal-first convention for all numeric thresholds. All other thresholds in `validate_order` use integer literals (`event.quantity > 0`, `event.price > 1000000`) which compare cleanly against `Decimal`. This one outlier is inconsistent and would silently misbehave if the Python version or decimal context changed the comparison semantics.
**Fix:**
```python
if order_value < Decimal("1"):  # Minimum order value
    warnings.append(f"Order value ${order_value:.2f} is very small")
```

---

### WR-03: Documented `TradingSystem` backward-compat alias is not implemented

**File:** `itrader/trading_system/backtest_trading_system.py:4` (module docstring)
**Issue:** The module docstring states "A backward-compat `TradingSystem` alias is retained so existing import sites (oracle/integration/conftest/scripts) keep working until Wave 4 migrates them." No such alias (`TradingSystem = BacktestTradingSystem`) exists anywhere in the file. Any future caller that reads the docstring and adds `from itrader.trading_system.backtest_trading_system import TradingSystem` will receive an `ImportError`. The docstring has created a false contract.

Verification: current tests import only `BacktestTradingSystem`, so there is no active breakage today. But the claim is false and leaves a trap for Wave 4 migration.
**Fix:** Either add the alias:
```python
#: Backward-compat alias — remove when Wave 4 migration (04-05) completes.
TradingSystem = BacktestTradingSystem
```
Or correct the docstring to remove the claim.

---

### WR-04: `rollback_config(steps: int = 1)` — `steps` parameter is dead code

**File:** `itrader/portfolio_handler/portfolio_handler.py:484`
**Issue:** The `rollback_config` method declares a `steps: int = 1` parameter that is never read. The implementation always resets unconditionally to `get_portfolio_preset('default')` regardless of the `steps` value. A caller passing `steps=5` expecting a multi-step history rollback gets the same result as `steps=1`, with no indication that the parameter is ignored. This is a misleading API surface.
**Fix:** Remove the dead parameter and update the signature to make the intent clear:
```python
def rollback_config(self) -> bool:
    """Reset PortfolioHandler configuration to the default preset."""
```
If multi-step rollback is ever needed, it should be backed by an actual history buffer, not a `steps` counter that is silently ignored.

---

## Info

### IN-01: `print()` in `BacktestRunner` bypasses structlog

**File:** `itrader/trading_system/backtest_runner.py:111`
**Issue:** `print("Backtest duration:", duration)` writes directly to stdout instead of going through the bound structlog logger (`self.logger`). Every other diagnostic in the runner and handlers uses `self.logger.info(...)`. This single `print` is inconsistent and will not appear in JSON log output if a non-console renderer is configured.
**Fix:**
```python
self.logger.info('Backtest completed', duration_seconds=duration.total_seconds())
```

---

### IN-02: Stray `)` in `OrderHandler` initialization log message

**File:** `itrader/order_handler/order_handler.py:93`
**Issue:** The log message has an unbalanced closing parenthesis inside the f-string:
```python
self.logger.info(f'Order Handler initialized with market_execution={self.market_execution})')
```
The trailing `)` is part of the string, not the method call. The log output reads `"...market_execution=MarketExecution.IMMEDIATE)"` — the trailing paren is cosmetically wrong and confusing.
**Fix:**
```python
self.logger.info('Order Handler initialized with market_execution=%s', self.market_execution)
```
(Switching to %-format also matches the surrounding handler logging style.)

---

### IN-03: Redundant double-connect log for the `csv` exchange alias

**File:** `itrader/execution_handler/execution_handler.py:162-175`
**Issue:** The `init_exchanges` loop iterates `{'simulated': sim, 'csv': sim, 'ccxt': None}`. Both `'simulated'` and `'csv'` point to the same `SimulatedExchange` object. `connect()` is called twice on the same instance. The second call is idempotent (the `if self._connected: return` guard fires), but the `init_exchanges` loop logs `"Successfully connected to csv exchange"` even though no actual connection action occurred on the second call. This misleads anyone reading the logs about what happened at startup.
**Fix:** Apply the same `seen: set[int]` dedup used in `on_market_data` to the connect loop, or log at `debug` instead of `info` for the alias entries:
```python
seen_connect: set[int] = set()
for exchange_name, exchange in exchanges.items():
    if exchange is None or id(exchange) in seen_connect:
        continue
    seen_connect.add(id(exchange))
    try:
        connection_result = exchange.connect()
        ...
```

---

_Reviewed: 2026-06-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
