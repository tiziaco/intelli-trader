---
phase: 04-composition-config-interface
plan: 03
subsystem: composition-config-interface
tags: [update-config, canonical-contract, deep-merge, atomic-swap, configuration-error, byte-exact, oracle-dark]
requires:
  - "04-02: OrderConfig threaded into OrderManager/OrderHandler; construction-time ExchangeConfig threading; SimulatedExchange config seam"
provides:
  - "shared deep_merge helper (itrader/config/merge.py, WR-04 sibling-preserving) used by all config-model update_config bodies"
  - "canonical update_config(self, updates: dict[str, Any]) -> None on PortfolioHandler, Portfolio, SimulatedExchange, ExecutionHandler, OrderManager, OrderHandler (D-07/D-08/D-09)"
  - "single web-catchable error contract: pydantic ValidationError wrapped into core.ConfigurationError (extra='forbid' catches unknown keys)"
  - "SimulatedExchange.configure() Protocol method on the dict + ConfigurationError contract (Pitfall 2 fixed)"
affects:
  - "Future live runtime-config transport (N+4): the uniform update_config surface every config-model handler now exposes is the bridge target"
  - "Wave 4 (04-05): the e2e conftest D-14 fee/slippage re-init seam (which manually re-inits, never calls update_config) can collapse onto build_backtest_system construction-time config"
tech-stack:
  added: []
  patterns:
    - "canonical update_config body (config-model handlers): deep_merge(self.config.model_dump(), updates) -> Config.model_validate(merged) -> atomic-swap; wrap pydantic ValidationError in ConfigurationError; re-derive cached internals after the swap (Pitfall 1)"
    - "shared deep-merge helper promoted to one home (config/merge.py) — no per-handler re-derivation"
    - "thin-facade delegation: OrderHandler.update_config delegates to OrderManager.update_config (handler/manager split)"
    - "atomic reference assignment (self.config = new) IS the thread-safety primitive (D-11) — no new locking"
key-files:
  created:
    - itrader/config/merge.py
    - tests/unit/portfolio/test_update_config.py
    - tests/unit/execution/test_simulated_exchange_update_config.py
    - tests/unit/order/test_order_update_config.py
  modified:
    - itrader/config/__init__.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/execution_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_handler.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/unit/order/test_stop_limit_orders.py
    - tests/unit/core/test_commission_estimator.py
    - tests/integration/test_execution_handler_routing.py
    - tests/integration/test_symbol_seeding.py
decisions:
  - "D-07/D-08: standardized the 3 inconsistent update_config forms (PortfolioHandler Dict->bool; Portfolio/SimulatedExchange **kwargs->None) onto ONE: dict->None, raising ConfigurationError. The bool-return swallow and the bare ValueError are gone."
  - "D-09: promoted PortfolioHandler._deep_merge to itrader/config/merge.py::deep_merge (WR-04). PortfolioHandler._deep_merge kept as a thin delegate so any existing caller keeps working; all five canonical bodies import the shared helper."
  - "Pitfall 1: each handler reproduces its post-swap re-derivations AFTER the atomic swap — PortfolioHandler.max_portfolios; SimulatedExchange fee_model/slippage_model/simulate_failures/failure_rate/_supported_symbols(REPLACEMENT)/_min_order_size/_max_order_size(Decimal)/_exchange_name; OrderManager.market_execution. The SimulatedExchange re-derivations are now UNCONDITIONAL (the old form did them per-key-conditionally) — simpler and strictly safe since model_validate rebuilt the whole object."
  - "Pitfall 2: SimulatedExchange.configure() now calls update_config(config) (dict, not **config) and `except ConfigurationError` (not ValueError), still returning False on a rejected config."
  - "Trap 1 (symbol replacement): SimulatedExchange.update_config re-derives _supported_symbols by REPLACEMENT off config.limits; the deep_merge sibling-preservation keeps supported_symbols when an update omits it. Pinned by a direct test (omit-supported-symbols-preserves-the-set + validate_symbol still admits)."
  - "ExecutionHandler owns no Pydantic config model of its own; its update_config routes the partial update to the simulated exchange's canonical update_config (thin delegation), raising ConfigurationError when no exchange is wired."
  - "OrderHandler stays a thin facade: update_config delegates to OrderManager and re-syncs the handler's cached market_execution mirror — no business logic in the handler (CLAUDE.md split)."
  - "Indentation matched per-file: portfolio_handler.py is 4-SPACE (not tabs, despite the handler convention); portfolio.py/simulated.py/execution_handler.py/order_manager.py/order_handler.py are TABS; config/merge.py + all new tests are 4 spaces. No normalization."
metrics:
  duration: ~40 min
  completed: 2026-06-12
  tasks: 3
  files: 17
---

# Phase 4 Plan 03: Canonical update_config on the five config-model handlers Summary

Rolled the canonical `update_config(self, updates: dict[str, Any]) -> None` contract onto all five config-model handlers (PortfolioHandler, Portfolio, SimulatedExchange, ExecutionHandler, OrderManager/OrderHandler), standardizing the three inconsistent existing forms onto one `deep_merge -> model_validate -> atomic-swap` body that wraps pydantic `ValidationError` into `core.ConfigurationError`; promoted the shared WR-04 `deep_merge` helper to `itrader/config/merge.py`; reproduced every per-handler post-swap cache re-derivation (Pitfall 1); and fixed the `SimulatedExchange.configure()` Protocol coupling (Pitfall 2). Oracle-dark and byte-exact — validated by new direct unit tests with the BTCUSD oracle, e2e 58/58, and `mypy --strict` all holding.

## What Was Built

- **`itrader/config/merge.py`** (NEW, 4 SPACES) — `deep_merge(base, updates)`: the WR-04 sibling-preserving recursive merge, promoted verbatim from `PortfolioHandler._deep_merge`. Exported from `config/__init__`.
- **`portfolio_handler.py`** (Task 1, 4 SPACES) — `update_config` is now `dict -> None`, raises `ConfigurationError` (no more `bool` swallow), re-derives `max_portfolios` after the swap; `_deep_merge` kept as a thin delegate to the shared helper.
- **`portfolio.py`** (Task 1, TABS) — `update_config(**kwargs) -> None` migrated to the canonical `dict` body over `self.config`; the old `config_mapping` setattr-poke dict is gone.
- **`simulated.py`** (Task 2, TABS) — `update_config(**kwargs)` migrated to the canonical `dict` body over `ExchangeConfig`; reproduces all post-swap re-derivations (fee/slippage models, failure sim, `_supported_symbols` by REPLACEMENT, size caches as Decimal, exchange name). `configure()` now calls `update_config(config)` and `except ConfigurationError`.
- **`execution_handler.py`** (Task 2, TABS) — new `update_config` delegating to the simulated exchange's canonical `update_config` (the handler owns no config model of its own); raises `ConfigurationError` when no exchange is wired.
- **`order_manager.py`** (Task 3, TABS) — new `update_config` over `OrderConfig` (deep_merge -> model_validate -> atomic-swap -> ConfigurationError), re-derives the cached `market_execution`.
- **`order_handler.py`** (Task 3, TABS) — new thin `update_config` delegating to the manager, re-syncs the handler's `market_execution` mirror.
- **Tests** — three new direct contract test files (portfolio / execution / order) covering valid swap + cache re-derive, unknown-key raise, bad-value wrap, WR-04 sibling preservation, the `configure()` Pitfall-2 behavior, and the Trap-1 symbol-set replacement property.

## Commits

- `0965c7f` feat(04-03): shared deep_merge + canonical update_config on PortfolioHandler/Portfolio (D-07/D-08/D-09)
- `e167b15` feat(04-03): canonical update_config on SimulatedExchange/ExecutionHandler + configure() fix (Pitfall 1+2)
- `df5f83c` feat(04-03): canonical update_config over OrderConfig on OrderManager/OrderHandler (D-05/D-09)

## Verification

**BYTE-EXACT GATE — HELD:**
- BTCUSD oracle: `poetry run pytest tests/integration/test_backtest_oracle.py -q` → **3 passed** (134 trades / `final_equity 46189.87730727451`, byte-exact — update_config is oracle-dark, never fires in the golden run).
- e2e: `make test-e2e` → **58/58 passed**, 881 deselected.
- `poetry run mypy itrader` → **Success: no issues found in 182 source files** (181 → 182, +config/merge.py).
- Domain suites: `poetry run pytest tests/unit/portfolio tests/unit/execution tests/unit/order -q` → **504 passed**.
- Full unit + integration suite: **881 passed**.

**Acceptance gates:**
- `update_config` returns `None` (not `bool`) on every migrated handler; raises `ConfigurationError` on unknown key (extra='forbid') and bad value (pydantic ValidationError wrapped).
- Shared `deep_merge` lives in `itrader/config/merge.py`; all five canonical bodies use it.
- `configure()` calls `update_config(config)` (dict) and `except ConfigurationError` (Pitfall 2).
- Pitfall-1 cache re-derivations reproduced per handler (max_portfolios; fee/slippage/failure-sim/_supported_symbols/_min/_max_order_size Decimal/_exchange_name; market_execution).
- Trap-1 symbol replacement: an `update_config` that omits supported_symbols preserves the construction-seeded set (direct test).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated out-of-scope test callers broken by the contract change.**
- **Found during:** Task 2 + Task 3.
- **Issue:** Five test files outside this plan's `files_modified` called the old `**kwargs`/flat-key `update_config` form (`tests/unit/execution/exchanges/test_simulated_exchange.py` — many sites; `tests/unit/order/test_stop_limit_orders.py`; `tests/unit/core/test_commission_estimator.py`; `tests/integration/test_execution_handler_routing.py`; `tests/integration/test_symbol_seeding.py`). The contract change broke them, blocking the verification gate.
- **Fix:** Translated every call to the canonical nested-dict form (e.g. `update_config(simulate_failures=True, failure_rate=0.05)` → `update_config({"failure_simulation": {"simulate_failures": True, "failure_rate": "0.05"}})`). Also migrated two pre-existing in-scope tests in `tests/unit/portfolio/test_portfolio_handler.py` (the bool-return + `**kwargs` assertions). Updated stale docstrings/comments that described the old setattr-bypass / "Wave 3 lands the dict path" behavior.
- **Files modified:** the 5 test files above + `tests/unit/portfolio/test_portfolio_handler.py`.
- **Commits:** e167b15 (execution + 4 callers), 0965c7f (portfolio).

**2. [Design clarification — Pitfall 1] SimulatedExchange re-derivations are now UNCONDITIONAL.**
- **Found during:** Task 2.
- **Issue:** The old `**kwargs` form re-derived caches conditionally (`if 'fee_model_type' in kwargs: ...`). The canonical body always rebuilds the whole config via `model_validate`, so a conditional re-derive is both unnecessary and a latent staleness risk.
- **Fix:** Re-derive ALL config-derived caches unconditionally after the atomic swap. Strictly safe (the new object is fully validated) and simpler; byte-identical end-state to the conditional form for any given update.
- **Files:** simulated.py.

### Note (no change made)
- The e2e conftest D-14 fee/slippage re-init seam (`tests/e2e/conftest.py:316-333`) references `update_config` only in prose; it manually assigns `simulated.config` and re-inits models (deliberately avoiding the symbol-wipe trap) and does NOT call `update_config`. It is therefore unaffected by the contract change and was left for the Wave 4 collapse.

## Threat Surface

The three registered tampering threats (T-04-06/07/08) are mitigated and tested:
- **T-04-06** (mass-assignment via unknown keys) — every config model is `ConfigDict(extra="forbid")`; `model_validate` rejects unknown keys → `ConfigurationError`. Pinned per handler (unknown-key tests).
- **T-04-07** (silent type confusion in a partial nested update) — `deep_merge` preserves siblings (WR-04) + `model_validate` coerces/validates the full merged object. Pinned (sibling-preservation + bad-value tests).
- **T-04-08** (symbol-set wipe via replacement) — deep-merge sibling preservation keeps `supported_symbols` when omitted; Trap-1 replacement test pins it. No new security surface (internal refactor; developer-authored config dicts only).

## Known Stubs

None. The methods are oracle-dark by construction (D-11) — they never fire in the golden run — and are fully exercised by the new direct unit tests; they are complete, not stubs.

## Self-Check: PASSED
- itrader/config/merge.py — FOUND
- tests/unit/portfolio/test_update_config.py — FOUND
- tests/unit/execution/test_simulated_exchange_update_config.py — FOUND
- tests/unit/order/test_order_update_config.py — FOUND
- commit 0965c7f — FOUND
- commit e167b15 — FOUND
- commit df5f83c — FOUND
