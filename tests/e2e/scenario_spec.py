"""Shared E2E scenario value objects — UNIFIED onto the promoted ``SystemSpec`` (D-01).

Wave 4 (04-05) collapse: the per-leaf scenario value objects are no longer defined
here. They are RE-EXPORTED from the promoted, run-path ``itrader.trading_system.
system_spec`` (the Wave-1 promotion of this module's former ``ScenarioSpec`` shape).
``ScenarioSpec`` is now a thin ALIAS of ``SystemSpec`` so every existing leaf
``scenario.py`` keeps importing ``ScenarioSpec`` / ``PortfolioSpec`` / ``Action`` by
the same name, while the harness (``conftest.py``) and the engine factory
(``build_backtest_system``) consume ONE unified spec type.

Why an alias re-export (not a deletion)
---------------------------------------
The field names match EXACTLY (the promotion was field-for-field by design — D-01),
so ``ScenarioSpec = SystemSpec`` is byte-identical for the leaves: they construct the
spec by keyword, the harness reads attributes BY NAME, and the factory consumes the
same shape. No leaf needs editing; the spec is defined ONCE in the run path.

Indentation: 4 spaces (matches ``tests/conftest.py``).
"""

from itrader.trading_system.system_spec import (
    Action,
    PortfolioSpec,
    SystemSpec,
)

# ``ScenarioSpec`` is the historical leaf-facing name; it now aliases the promoted
# run-path ``SystemSpec`` (D-01). Field-for-field identical — the harness consumes
# the unified shape and every leaf keeps importing ``ScenarioSpec`` unchanged.
ScenarioSpec = SystemSpec

__all__ = ["Action", "PortfolioSpec", "ScenarioSpec", "SystemSpec"]
