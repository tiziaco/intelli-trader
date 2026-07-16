---
phase: quick-260716-law
plan: 01
type: execute
wave: 1
depends_on: []
autonomous: true
requirements: [QT-260716-law]
files_modified:
  # --- Refactor A: move deep_merge -> outils/recursive_merge (Task 1) ---
  - itrader/config/merge.py                              # DELETED (git mv -> outils/dict_merge.py)
  - itrader/outils/dict_merge.py                         # NEW (tabs; deep_merge -> recursive_merge)
  - itrader/config/__init__.py                           # A: drop deep_merge re-export + __all__ | B: drop preset helpers | D: RuntimeSettings->LogConfig  (3 tasks edit this file, sequential)
  - itrader/trading_system/config_router.py             # A: direct import + calls
  - itrader/order_handler/order_manager.py               # A: barrel import + calls
  - itrader/portfolio_handler/portfolio.py               # A: barrel import + calls
  - itrader/portfolio_handler/portfolio_handler.py       # A: barrel import + calls + _deep_merge delegate body/docstring (KEEP method name)
  - itrader/execution_handler/execution_handler.py       # A: prose-only pipeline mention | B: import + :218 preset call
  - itrader/execution_handler/exchanges/simulated.py     # A: drop deep_merge from combined import | B: drop get_exchange_preset + :87  (A & B edit line 25, sequential)
  # A test sweep (grep-driven — GREP to confirm complete, these are confirmed):
  - tests/unit/trading_system/test_config_router.py      # A: direct import + calls
  - tests/unit/portfolio/test_update_config.py           # A: import + 3 call sites + 3 test_deep_merge_* FUNCTION NAMES + prose (densest)
  - tests/unit/order/test_liquidation_reconcile.py
  - tests/unit/order/test_order_update_config.py          # prose only
  - tests/unit/execution/test_simulated_exchange_update_config.py  # prose only
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/unit/portfolio/test_realised_pnl_accumulator.py
  - tests/unit/portfolio/test_validate_transaction_sell_exit.py
  - tests/unit/portfolio/test_portfolio.py
  - tests/unit/portfolio/test_carry.py
  - tests/unit/portfolio/test_wr04_lock_fits_buying_power.py
  - tests/unit/portfolio/test_liquidation.py
  - tests/unit/portfolio/test_portfolio_margin.py
  - tests/unit/portfolio/test_account_conformance.py
  - tests/integration/test_pair_exit_safety.py
  - tests/integration/test_pair_flagship_snapshot.py
  - tests/e2e/**/test_*_scenario.py                       # every e2e scenario importing deep_merge (10 files: partial_cover, levered_long, short_scale_in, short_roundtrip, trailing_short, levered_long_into_liquidation, short_carry, short_scale_in_partial_cover, forced_liq_long, forced_liq_short)
  # --- Refactor C: delete config/models.py (Task 2 — BEFORE B) ---
  - itrader/config/models.py                             # DELETED
  - tests/unit/config/test_config_models.py              # repoint import -> itrader.config barrel
  # --- Refactor B: exchange presets -> classmethods (Task 3 — ORACLE-CRITICAL) ---
  - itrader/config/exchange.py                           # .default() body=verbatim _default_preset; +high_fee(); delete 4 presets + _EXCHANGE_PRESETS + get_/list_ helpers
  - itrader/trading_system/backtest_trading_system.py    # B: import 33 + :62/:132/:461
  - tests/unit/execution/exchanges/test_simulated_exchange.py  # B: import 17 + :66 -> ExchangeConfig.high_fee()
  - tests/integration/test_symbol_seeding.py             # B: import 17 + :24 -> ExchangeConfig.default()
  # --- Refactor D: rename RuntimeSettings -> LogConfig, runtime.py -> log.py (Task 4) ---
  - itrader/config/runtime.py                            # DELETED (git mv -> config/log.py)
  - itrader/config/log.py                                # NEW (4 spaces; class LogConfig)
  - itrader/config/itrader_config.py                     # D: import + field type (field NAME stays `logging`) + docstring
  - itrader/logger.py                                    # D: docstrings ~29/33/48/51/300
  - tests/unit/config/test_itrader_config.py             # D: import 28 + assertions ~156/160/163/174/176
  - tests/unit/core/test_logger_config.py                # D: prose :6
  - tests/integration/test_okx_inertness.py              # D: prose comment :358

must_haves:
  truths:
    - "ORACLE BYTE-EXACT: a SMA_MACD backtest stays 134 trades / final equity 46189.87730727451 (check_exact). Refactor B is oracle-critical — ExchangeConfig.default() must construct the byte-identical config the deleted _default_preset() produced."
    - "OKX IMPORT-INERTNESS: tests/integration/test_okx_inertness.py stays green; zero new dependency; the moved outils/dict_merge.py and config/log.py import only stdlib/pydantic, so `import itrader` stays sqlalchemy/ccxt/async-free."
    - "ZERO-GREP A: the standalone `deep_merge` helper token is retired across itrader/ and tests/ (code AND prose) — the ONLY surviving *deep_merge* identifier is the intentionally-kept `PortfolioHandler._deep_merge` static delegate, whose body now calls `recursive_merge`."
    - "ZERO-GREP B1: `get_exchange_preset` appears nowhere in itrader/ or tests/."
    - "ZERO-GREP B2: `list_available_exchange_presets` appears nowhere in itrader/ or tests/."
    - "ZERO-GREP B3: `_EXCHANGE_PRESETS` appears nowhere in itrader/ or tests/."
    - "ZERO-GREP D: `RuntimeSettings` appears nowhere (renamed LogConfig); `config.runtime` / `config/runtime.py` module references are zero."
    - "ZERO-GREP C: `itrader.config.models` is referenced nowhere (module deleted; the one importer repointed to the config barrel); storage `.models` modules are left untouched."
    - "ZERO-GREP A-mod: `config.merge` / `config/merge.py` references are zero (module moved to itrader/outils/dict_merge.py)."
    - "GATE GREEN: `poetry run pytest tests -q` and `poetry run mypy itrader` are both clean."
  artifacts:
    - itrader/outils/dict_merge.py       # NEW — recursive_merge (tabs)
    - itrader/config/log.py              # NEW — LogConfig (4 spaces)
    - itrader/config/exchange.py         # presets folded into classmethods
    - itrader/config/__init__.py         # barrel: deep_merge + preset helpers + RuntimeSettings all removed/renamed
    - itrader/config/merge.py            # DELETED
    - itrader/config/models.py           # DELETED
    - itrader/config/runtime.py          # DELETED
  key_links:
    - "SimulatedExchange default path: simulated.py:87 `config or ExchangeConfig.default()` must yield the byte-identical oracle config (the reason B is oracle-gated)."
    - "config/__init__.py barrel is edited by THREE tasks in sequence (A drops deep_merge; B drops get_exchange_preset/list_available_exchange_presets; D swaps RuntimeSettings->LogConfig) — re-read before each edit."
    - "simulated.py line-25 combined import is edited by A (drop deep_merge) then B (drop get_exchange_preset) — re-read before the B edit."
    - "itrader_config.py `logging: LogConfig` — the FIELD NAME stays `logging`; only the type renames, so config.logging consumers are unaffected."
    - "outils/dict_merge.py is imported directly (`from itrader.outils.dict_merge import recursive_merge`), never re-exported from any barrel — matching the outils/ id_generator.py / time_parser.py convention (empty __init__.py)."
---

<objective>
Config-package cleanup: four cohesive, mechanical, user-locked refactors of `itrader/config` plus a verification gate. ALL naming/scope decisions are LOCKED (see `<locked_spec>` in the task brief) — do NOT re-open them.

- A) Move the `deep_merge` helper out of `config/` into `outils/` and rename it `recursive_merge`.
- C) Delete `config/models.py` (a redundant aggregation module; only one test imports it).
- B) Fold the exchange preset registry into `ExchangeConfig` classmethods (`.default()` / `.high_fee()`). **ORACLE-CRITICAL.**
- D) Rename `RuntimeSettings` -> `LogConfig` and `config/runtime.py` -> `config/log.py`.
- E) Verification gate (no source edits).

Purpose: retire four accreted config seams so the package matches the post-v1.8 model-direct convention, without disturbing the byte-exact backtest oracle or the OKX import-inertness gate.

Output: `recursive_merge` in `outils/`, exchange presets as classmethods, `models.py` gone, `LogConfig`, and 7 zero-grep goals met.

## Execution order (IMPORTANT — not the letter order)
Run tasks in this sequence to keep every intermediate commit green and importable:
**Task 1 = A → Task 2 = C → Task 3 = B → Task 4 = D → Task 5 = E.**
Rationale for C-before-B: `config/models.py` re-imports `get_exchange_preset` / `list_available_exchange_presets` from `config/exchange.py`. Refactor B DELETES those functions; if B ran while `models.py` still existed, `models.py`'s import would dangle and `pytest tests/unit/config` would break at collection. Deleting `models.py` first (C) removes that dependency so B's commit stays green.

## Shared-file sequencing (single executor, sequential edits)
- `itrader/config/__init__.py` is edited by A, B, and D. Re-read it before each of those edits.
- `itrader/execution_handler/exchanges/simulated.py` line-25 combined import is edited by A then B. Re-read before the B edit.
Because ONE executor runs the tasks in order, there is no parallel conflict — just re-read these two files before re-touching them.

## Indentation (CLAUDE.md — LOAD-BEARING, never normalize)
- `itrader/config/` = **4 spaces** (log.py, exchange.py, __init__.py, itrader_config.py).
- `itrader/outils/` = **TABS** (id_generator.py / time_parser.py convention) — the moved `dict_merge.py` MUST be tabs (convert merge.py's 4-space body).
- Handler/execution/trading_system modules = **TABS** (order_manager.py, portfolio*.py, simulated.py, execution_handler.py, config_router.py, backtest_trading_system.py). Match the file you edit.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

# Refactor A — source of truth + consumers
@itrader/config/merge.py
@itrader/config/__init__.py
@itrader/portfolio_handler/portfolio_handler.py
@itrader/outils/id_generator.py

# Refactor B — ORACLE-CRITICAL preset constructions
@itrader/config/exchange.py

# Refactor C / D
@itrader/config/models.py
@itrader/config/runtime.py
@itrader/config/itrader_config.py
@tests/unit/config/test_config_models.py
@tests/unit/config/test_itrader_config.py
</context>

<tasks>

<task type="auto">
  <name>Task 1 (Refactor A): move deep_merge -> itrader/outils/dict_merge.py::recursive_merge</name>
  <files>itrader/config/merge.py (DELETED), itrader/outils/dict_merge.py (NEW), itrader/config/__init__.py, itrader/trading_system/config_router.py, itrader/order_handler/order_manager.py, itrader/portfolio_handler/portfolio.py, itrader/portfolio_handler/portfolio_handler.py, itrader/execution_handler/execution_handler.py, itrader/execution_handler/exchanges/simulated.py, + the grep-driven test sweep (test_config_router.py, test_update_config.py, test_liquidation_reconcile.py, test_order_update_config.py, test_simulated_exchange_update_config.py, tests/unit/portfolio/*.py, tests/integration/test_pair_*.py, tests/e2e/**/test_*_scenario.py)</files>
  <action>
Move the helper with history: `git mv itrader/config/merge.py itrader/outils/dict_merge.py`. In the moved file, rename the function `deep_merge` -> `recursive_merge` (both the def and the internal recursive call), convert the ENTIRE body from 4-space to TAB indentation (outils/ convention), keep the WR-04 sibling-preservation docstring intact, and update any module-path self-reference in the docstring to `itrader/outils/dict_merge.py`. Do NOT add it to any `__init__.py` — outils/ modules are imported directly (id_generator.py / time_parser.py precedent; empty __init__.py).

config barrel: in `itrader/config/__init__.py` remove the `from .merge import deep_merge` import (~line 56) and the `"deep_merge"` entry in `__all__` (~line 105). config/ no longer re-exports the helper.

DIRECT-import consumers -> `from itrader.outils.dict_merge import recursive_merge`: `itrader/trading_system/config_router.py` (import line 70) and `tests/unit/trading_system/test_config_router.py` (import ~line 36).

BARREL-import consumers: drop `deep_merge` from the existing `from itrader.config import ...` (or `from ..config import ...`) list AND add a separate `from itrader.outils.dict_merge import recursive_merge` line: `itrader/order_handler/order_manager.py:27`, `itrader/portfolio_handler/portfolio.py:8`, `itrader/portfolio_handler/portfolio_handler.py:37`, `itrader/execution_handler/exchanges/simulated.py:25` (this line-25 import is COMBINED with get_exchange_preset — B edits it next; here only drop deep_merge, keep get_exchange_preset for now), and every test file GREP surfaces (confirmed set: tests/unit/portfolio/{test_update_config,test_realised_pnl_accumulator,test_portfolio_handler,test_portfolio,test_wr04_lock_fits_buying_power,test_validate_transaction_sell_exit,test_carry,test_account_conformance,test_liquidation,test_portfolio_margin}.py, tests/unit/order/test_liquidation_reconcile.py, tests/integration/{test_pair_exit_safety,test_pair_flagship_snapshot}.py, and every tests/e2e/*/test_*_scenario.py importing the helper).

Rename every CALL `deep_merge(` -> `recursive_merge(`.

`portfolio_handler.py` `_deep_merge` static delegate (~line 1304): KEEP the method name `_deep_merge`, but repoint its body (`return deep_merge(...)` ~line 1311 -> `return recursive_merge(...)`) and update its docstring path to `itrader/outils/dict_merge.py`. Also fix the standalone `deep_merge(...)` call in `update_config` (~line 1325) -> `recursive_merge(...)`.

Densest file — `tests/unit/portfolio/test_update_config.py`: it imports the helper (line 17), calls it (lines 27/34/40), AND names three test functions `test_deep_merge_preserves_sibling_submodel_fields` / `test_deep_merge_does_not_mutate_inputs` / `test_deep_merge_replaces_non_dict_values` (lines 25/31/39). Rename the import, the calls, AND the three function names to `test_recursive_merge_*` so the token fully retires.

Prose sweep (token retired in comments/docstrings too): rename every remaining pipeline mention `deep_merge -> model_validate` to `recursive_merge -> model_validate`, including prose-only files that do NOT import the symbol: `itrader/execution_handler/execution_handler.py` (docstrings ~lines 92/107), `tests/unit/order/test_order_update_config.py` (~line 3), `tests/unit/execution/test_simulated_exchange_update_config.py` (~lines 3/90). The grep gate below is the completeness check.
  </action>
  <verify>
    <automated>test -f itrader/outils/dict_merge.py && ! test -f itrader/config/merge.py && grep -q "def recursive_merge" itrader/outils/dict_merge.py</automated>
    <automated>test $(grep -rnE '(^|[^_])deep_merge' itrader tests --include='*.py' | wc -l) -eq 0   # only the kept _deep_merge method may remain</automated>
    <automated>test $(grep -rnE 'config\.merge|config/merge' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/portfolio/test_update_config.py tests/unit/order/test_order_update_config.py tests/unit/execution/test_simulated_exchange_update_config.py tests/unit/trading_system/test_config_router.py -q</automated>
  </verify>
  <done>merge.py moved to outils/dict_merge.py as `recursive_merge` (tabs); config barrel no longer re-exports it; all direct/barrel imports + calls repointed; `_deep_merge` method name kept but body calls recursive_merge; test_update_config.py function names renamed; standalone `deep_merge` grep (excluding `_deep_merge`) and `config.merge`/`config/merge` grep both return 0; the four update-config/router tests pass. Atomic commit.</done>
</task>

<task type="auto">
  <name>Task 2 (Refactor C): delete config/models.py; repoint its one test importer</name>
  <files>itrader/config/models.py (DELETED), tests/unit/config/test_config_models.py</files>
  <action>
Delete the redundant aggregation module: `git rm itrader/config/models.py`. It is imported by exactly ONE file. In `tests/unit/config/test_config_models.py`, change line 21 `from itrader.config.models import PortfolioConfig` -> `from itrader.config import PortfolioConfig`. READ the whole test file and confirm the two test bodies (`test_portfolio_config_model_dump_json_round_trips`, `test_portfolio_config_default_factory`) only exercise `PortfolioConfig` behaviors (model_validate / model_dump(mode="json") round-trip; `.default()` == `PortfolioConfig()`) — those hold identically through the barrel import, so keep the assertions as-is (coverage stays meaningful; no models.py-module-specific assertion exists to adapt).

DO NOT touch the unrelated `from .models import build_order_tables` / `build_portfolio_tables` in `order_handler/storage/sql_storage.py` and `portfolio_handler/storage/sql_storage.py` — those are `storage/models.py`, a DIFFERENT module, not `config.models`.
  </action>
  <verify>
    <automated>! test -f itrader/config/models.py</automated>
    <automated>test $(grep -rn 'itrader\.config\.models' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/config/test_config_models.py -q</automated>
  </verify>
  <done>config/models.py deleted; test_config_models.py imports PortfolioConfig from the barrel and passes; `itrader.config.models` grep returns 0; storage `.models` imports untouched. Atomic commit.</done>
</task>

<task type="auto">
  <name>Task 3 (Refactor B): fold exchange presets into ExchangeConfig classmethods (ORACLE-CRITICAL)</name>
  <files>itrader/config/exchange.py, itrader/config/__init__.py, itrader/trading_system/backtest_trading_system.py, itrader/execution_handler/execution_handler.py, itrader/execution_handler/exchanges/simulated.py, tests/unit/execution/exchanges/test_simulated_exchange.py, tests/integration/test_symbol_seeding.py</files>
  <action>
In `itrader/config/exchange.py`: replace the body of the existing `ExchangeConfig.default()` classmethod (currently `return get_exchange_preset("default")`, ~lines 176-178) with the `ExchangeConfig(...)` construction copied BYTE-FOR-BYTE from `_default_preset()` (~lines 181-210): exchange_name="SimulatedExchange", exchange_type=ExchangeVenue.SIMULATED, fee_model FeeModelType.ZERO with fee_rate Decimal("0.0"), slippage_model SlippageModelType.NONE with base_slippage_pct/size_impact_factor/max_slippage_pct all Decimal("0.0"), limits with supported_symbols {BTCUSDT,ETHUSDT,ADAUSDT,DOTUSDT,SOLUSDT} + min_order_size Decimal("0.001") + max_order_size Decimal("1000000.0") + max_price Decimal("1000000.0"), failure_simulation simulate_failures=False failure_rate Decimal("0.0") enabled_scenarios=["network_timeout","exchange_maintenance"], connection auto_connect=True connection_timeout Decimal("30.0") retry_attempts=3 retry_delay Decimal("1.0"). This byte-identity is what the oracle depends on — copy values exactly, do not "clean up".

Add a new `@classmethod def high_fee(cls) -> "ExchangeConfig"` returning the construction copied byte-for-byte from `_high_fee_preset()` (~lines 247-279).

DELETE: `_default_preset`, `_realistic_preset`, `_high_fee_preset`, `_low_latency_preset`, the `_EXCHANGE_PRESETS` dict, `get_exchange_preset`, and `list_available_exchange_presets`. Drop `realistic` and `low_latency` entirely (confirmed unreferenced). Update the module docstring to describe the classmethod pattern instead of the deleted preset registry.

config barrel: in `itrader/config/__init__.py` remove `get_exchange_preset` and `list_available_exchange_presets` from the `from .exchange import (...)` block (~lines 67-68) and from `__all__` (~lines 122-123). Keep `ExchangeConfig` and the other exchange re-exports.

Call sites -> `ExchangeConfig.default()` / `.high_fee()`:
- `itrader/trading_system/backtest_trading_system.py`: import line 33 (drop `get_exchange_preset`, keep `ExchangeConfig`); `:62` `get_exchange_preset('default').limits.supported_symbols` -> `ExchangeConfig.default().limits.supported_symbols`; `:132` `get_exchange_preset('default')` -> `ExchangeConfig.default()`; `:461` `get_exchange_preset('default')` -> `ExchangeConfig.default()`.
- `itrader/execution_handler/execution_handler.py`: import line 10 (drop `get_exchange_preset`); `:218` `config = get_exchange_preset('default')` -> `ExchangeConfig.default()`.
- `itrader/execution_handler/exchanges/simulated.py`: line-25 combined import (Task 1 already dropped deep_merge here — RE-READ first) drop `get_exchange_preset`, keep `ExchangeConfig` + the rest; `:87` `config or get_exchange_preset('default')` -> `config or ExchangeConfig.default()`.
- `tests/unit/execution/exchanges/test_simulated_exchange.py`: import line 17 (drop `get_exchange_preset`, keep `ExchangeConfig`); `:66` `get_exchange_preset('high_fee')` -> `ExchangeConfig.high_fee()`.
- `tests/integration/test_symbol_seeding.py`: import line 17 `from itrader.config import get_exchange_preset` -> `from itrader.config import ExchangeConfig`; `:24` `get_exchange_preset("default").limits.supported_symbols` -> `ExchangeConfig.default().limits.supported_symbols`.
  </action>
  <verify>
    <automated>test $(grep -rn 'get_exchange_preset' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn 'list_available_exchange_presets' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn '_EXCHANGE_PRESETS' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -v   # BYTE-EXACT 134 trades / final equity 46189.87730727451</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/execution/exchanges/test_simulated_exchange.py tests/integration/test_symbol_seeding.py -q</automated>
  </verify>
  <done>ExchangeConfig.default()/.high_fee() construct byte-identical configs; the 4 preset functions + _EXCHANGE_PRESETS + get_/list_ helpers are gone (grep 0); realistic/low_latency dropped; barrel + all 5 call-site files repointed; the backtest oracle stays byte-exact at 134 / 46189.87730727451; exchange + symbol-seeding tests pass. Atomic commit.</done>
</task>

<task type="auto">
  <name>Task 4 (Refactor D): rename RuntimeSettings -> LogConfig, config/runtime.py -> config/log.py</name>
  <files>itrader/config/runtime.py (DELETED), itrader/config/log.py (NEW), itrader/config/__init__.py, itrader/config/itrader_config.py, itrader/logger.py, tests/unit/config/test_itrader_config.py, tests/unit/core/test_logger_config.py, tests/integration/test_okx_inertness.py</files>
  <action>
Move with history: `git mv itrader/config/runtime.py itrader/config/log.py`. In the moved file rename the class `RuntimeSettings` -> `LogConfig` (still `BaseSettings`, `SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")`, fields `log_level`/`disable_logs` UNCHANGED); update the class docstring/comment references from RuntimeSettings to LogConfig. Keep 4-space indentation (config/ convention). Keep Pitfall-8 note that logger.py must NOT construct it.

`itrader/config/__init__.py`: change import (~line 22) `from .runtime import RuntimeSettings` -> `from .log import LogConfig`; change the `__all__` entry (~line 79) `"RuntimeSettings"` -> `"LogConfig"`; update the header module docstring mention (~lines 6-7) of `RuntimeSettings` -> `LogConfig`.

`itrader/config/itrader_config.py`: change import (~line 40) `from itrader.config.runtime import RuntimeSettings` -> `from itrader.config.log import LogConfig`; change the field annotation (~line 95) `logging: RuntimeSettings = Field(default_factory=RuntimeSettings)` -> `logging: LogConfig = Field(default_factory=LogConfig)` — the FIELD NAME stays `logging`; update the field's docstring/comment mention (~lines 91-94) RuntimeSettings -> LogConfig.

`itrader/logger.py`: rename the docstring mentions of `RuntimeSettings` -> `LogConfig` (~lines 29/33/48/51/300). Docstrings only — no code change.

Tests:
- `tests/unit/config/test_itrader_config.py`: import line 28 `from itrader.config import TIMEZONE, RuntimeSettings` -> `... TIMEZONE, LogConfig`; update the assertions/usages (~lines 156-176) — `isinstance(logging, RuntimeSettings)` -> `LogConfig`, `RuntimeSettings().log_level` -> `LogConfig().log_level`, and the docstrings. Function names using snake_case `runtime_settings` do not match the `RuntimeSettings` identifier grep, but rename them to `log_config` for consistency if trivial.
- `tests/unit/core/test_logger_config.py`: prose mention (~line 6) `RuntimeSettings()` -> `LogConfig()`.
- `tests/integration/test_okx_inertness.py`: prose comment (~line 358) `no RuntimeSettings()` -> `no LogConfig()`.
  </action>
  <verify>
    <automated>test -f itrader/config/log.py && ! test -f itrader/config/runtime.py && grep -q "class LogConfig" itrader/config/log.py</automated>
    <automated>test $(grep -rn 'RuntimeSettings' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rnE 'config\.runtime|config/runtime' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/config/test_itrader_config.py tests/unit/core/test_logger_config.py -q</automated>
  </verify>
  <done>runtime.py moved to config/log.py with class LogConfig (env-parsing preserved); the `logging` field keeps its name, type is LogConfig; barrel/itrader_config/logger/test docstrings updated; `RuntimeSettings` and `config.runtime`/`config/runtime` greps return 0; config + logger-config tests pass. Atomic commit.</done>
</task>

<task type="auto">
  <name>Task 5 (Refactor E): verification gate (no source edits)</name>
  <files>(none — verification only)</files>
  <action>
Run the full gate. Use `poetry run pytest` (NOT `make test` — it exports ITRADER_DISABLE_LOGS and aborts on a missing .env). If running from a worktree, prepend `PYTHONPATH="$PWD"` (editable-install shadowing). Fix any failure by returning to the owning task's edits — do NOT weaken a test or a grep gate. This task makes NO source changes; it is the phase acceptance gate and produces the commit only if everything is green.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests -q</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -v   # 134 trades / 46189.87730727451 byte-exact</automated>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/integration/test_okx_inertness.py -q</automated>
    <automated>PYTHONPATH="$PWD" poetry run mypy itrader   # strict-clean</automated>
    <automated>test $(grep -rnE '(^|[^_])deep_merge' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn 'get_exchange_preset' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn 'list_available_exchange_presets' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn '_EXCHANGE_PRESETS' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn 'RuntimeSettings' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rn 'itrader\.config\.models' itrader tests --include='*.py' | wc -l) -eq 0</automated>
    <automated>test $(grep -rnE 'config\.merge|config/merge|config\.runtime|config/runtime' itrader tests --include='*.py' | wc -l) -eq 0</automated>
  </verify>
  <done>Full suite green; oracle byte-exact at 134 / 46189.87730727451; OKX inertness green; mypy --strict clean; all 7 zero-grep goals (deep_merge standalone, get_exchange_preset, list_available_exchange_presets, _EXCHANGE_PRESETS, RuntimeSettings, itrader.config.models, config.merge + config.runtime) return 0. Atomic commit.</done>
</task>

</tasks>

<verification>
- Oracle: `tests/integration/test_backtest_oracle.py` byte-exact 134 trades / final equity 46189.87730727451 (Refactor B is the only oracle risk — B rewrites the default exchange config that seeds fees/slippage/limits).
- Inertness: `tests/integration/test_okx_inertness.py` green; zero new dependency; moved modules import only stdlib/pydantic.
- Full suite `poetry run pytest tests -q` and `poetry run mypy itrader` clean.
- 7 zero-grep goals all return 0 (deep_merge grep excludes the intentionally-kept `_deep_merge` method via `(^|[^_])deep_merge`).
</verification>

<success_criteria>
- `recursive_merge` lives in `itrader/outils/dict_merge.py` (tabs); `config/merge.py` gone; every consumer repointed; `_deep_merge` delegate kept-by-name, body calls recursive_merge.
- `config/models.py` gone; its one test repointed to the barrel and passing.
- Exchange presets are `ExchangeConfig.default()` / `.high_fee()` classmethods; the 4 preset funcs + `_EXCHANGE_PRESETS` + get_/list_ helpers deleted; realistic/low_latency dropped; oracle byte-exact.
- `LogConfig` in `config/log.py`; `config/runtime.py` gone; `logging` field name unchanged; env-parsing preserved.
- Full suite + mypy --strict green; all 7 zero-grep goals met; each of Tasks 1-4 is an independent, green, atomic commit; Task 5 is the gate commit.
</success_criteria>

<output>
Create `.planning/quick/260716-law-config-package-cleanup-move-deep-merge-t/260716-law-SUMMARY.md` when done.
</output>
