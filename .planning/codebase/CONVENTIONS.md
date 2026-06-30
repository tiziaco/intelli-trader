<!-- last_mapped_commit: 6b15b25 -->
# Coding Conventions

**Analysis Date:** 2026-06-30

## Naming Patterns

**Files:**
- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `cash_manager.py`, `position_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `itrader/execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `sql_storage.py`, `cached_sql_storage.py`, `postgresql_storage.py`.
- Storage factories: `storage_factory.py` exposing `<Concern>StorageFactory` (`OrderStorageFactory`, `PortfolioStateStorageFactory`, `SignalStorageFactory`).
- Tests mirror source: `test_<module>.py` (e.g. `tests/unit/order/test_order_manager.py`).

**Functions:**
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` (`Order.new_order()`, `FillEvent.new_fill()`) and `create()` on storage factories.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_order()`, `get_artifact()`.
- Ranking/query reads on stores: verb-first plurals — `top_runs()`, `top_portfolios()`, `save_run()`, `save_artifact()`.
- Private helpers/attributes: single leading underscore — `_resolve_rng_seed()`, `self._rng`, `self._storage`, `store._encode_frame()`.
- Test-local builders: leading-underscore module functions — `_make_order()`, `_metrics()`, `_run()`, `_frame()`, `_run_id()`.

**Variables:**
- `snake_case` always.
- The shared event queue is always `global_queue` (constructor parameter) or `events_queue`.
- Bound logger is always `self.logger`.
- Config is always `self.config` (or a typed config object such as `SystemConfig`, `SqlSettings`).
- Module-private module-level constants: leading underscore — `_ONE`, `_DEFAULT_SCALES`, `_CASH_SCALES`, `_BT` (a pinned business time in tests).

**Types:**
- Classes: `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `SqlResultsStore`, `SqlBackend`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` / `<Domain>Settings` — `PortfolioConfig`, `SystemConfig`, `ExchangeConfig`, `SqlSettings`.
- Record/value dataclasses: `<Domain>Record` — `RunRecord`, `PortfolioRecord`, `RunMetrics` (`itrader/results/records.py`).
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `ResultsNotFound`.
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Code Style

**Formatting:**
- No autoformatter configured (no black/ruff/prettier config present). Match the surrounding file by hand.
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml` all absent).
- The only static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).

**Indentation (correctness hazard — never normalize):**
- **Tabs:** handler/manager modules under `itrader/` — `order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`. Confirmed: `itrader/order_handler/order_handler.py` is tab-indented.
- **4 spaces:** `itrader/config/`, `itrader/core/` (e.g. `money.py`, `bar.py`, `ids.py`), `itrader/price_handler/feed/`, the `events_handler/events/` package, the v1.6 `itrader/storage/` and `itrader/results/` packages, and ALL test files (`tests/conftest.py` and every `tests/**`).
- **Rule:** ALWAYS match the indentation of the file being edited. Do not normalize. A mixed-indentation diff in a tab file will break the file. New v1.6 storage/results modules and all tests are spaces.

**Linting/typing:**
- Required and enforced under `mypy --strict` for in-scope code (`itrader/`).
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`, `"Queue[Any]"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Public module surfaces pin `__all__` (e.g. `itrader/core/money.py::__all__ = ["ONE", "to_money", "quantize"]`).
- Deferred subsystems are exempted via `[[tool.mypy.overrides]]` (`live_trading_system`, `trading_interface`, ccxt/oanda providers, `binance_stream`, `screeners_handler.*`, `my_strategies.*`) and stubless third-party libs get `ignore_missing_imports`. New code should be strict-clean; do not rely on these exemptions.

## Import Organization

**Order (observed in spaces-modules / tests):**
1. Standard library (`import uuid`, `from datetime import datetime, timezone`, `from decimal import Decimal`).
2. Third-party (`import pandas as pd`, `import pytest`, `from sqlalchemy import select`, `import uuid_utils.compat as uc`).
3. First-party `itrader.*` (`from itrader import idgen`, `from itrader.results.records import RunRecord`).

- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear in source; relative is common inside a domain package, absolute for cross-domain. Match the file (`order_handler.py` uses relative `..core`, `.base`).
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`, `from itrader import config`.
- **Deferred-import idiom (v1.6, load-bearing):** heavy / optional imports (`testcontainers`, `docker`, SQLAlchemy `create_engine`, `BacktestTradingSystem`) live INSIDE fixture/factory function bodies so `pytest --collect-only` needs no Docker daemon and a Dockerless run stays green. See `tests/integration/storage/conftest.py::pg_engine` and `tests/integration/conftest.py::backtest_engine`.
- **Import-quarantine discipline:** the backtest storage path must pull NO SQLAlchemy. Storage factories import their `cached_sql_storage`/SQLAlchemy wrappers lazily inside the `'live'` arm only — enforced by `tests/unit/storage/test_import_quarantine.py` (GATE-01) running a clean-interpreter subprocess probe.

**Path Aliases:**
- None — Python package imports only. No `tsconfig`-style aliases.

## Error Handling

**Exception hierarchy:**
- Root: `ITraderError` (`itrader/core/exceptions/base.py`).
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`.
- Domain-specific: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `itrader/core/exceptions/order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `itrader/core/exceptions/data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`).
- v1.6 results store: `ResultsNotFound` (raised by `SqlResultsStore.get_artifact` on an unknown `run_id`; a KNOWN run with zero artifacts returns `{}`, never raises — see `test_get_artifact_known_run_without_artifacts_returns_empty`).

**Patterns:**
- Raise typed exceptions, not bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False`.
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).
- **Rejections flow as events, not exceptions:** `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` and emits a `FillEvent(REFUSED)` so the order mirror reconciles. Execution error codes live in `core/enums/execution.py::ExecutionErrorCode`.
- **Run-mode error policy (intentional, documented — not an inconsistency):** backtest is fail-fast (`EventHandler._on_handler_error` re-raises); live is publish-and-continue (overridden to emit `ErrorEvent` and keep draining). `ExecutionHandler.on_order`/`on_market_data` catch per-exchange exceptions and log without re-raising to prevent queue stalls.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- **Dockerless skip policy (v1.6):** any testcontainers Postgres startup failure converts to `pytest.skip` (D-11) — the PG arm must never hard-fail a Dockerless run (`tests/integration/storage/conftest.py::pg_engine`). `pytest.skip` raises `Skipped` (a `BaseException`) so a broad `except Exception` does not re-swallow it.

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision). `float()` appears only at the serialization/logging edge.
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`, D-04). NEVER call `Decimal(float)` directly (binary-float repr artifact). Test fixtures honour this: `_bar_struct` enters every field via `Decimal(str(x))` (`tests/conftest.py`).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP` (D-03).
- Per-instrument scales read off the `Instrument` value object; `_DEFAULT_SCALES`/`_CASH_SCALES` are the no-data fallback in `itrader/core/money.py`.
- **Persistence (v1.6):** money columns are Postgres-native `Numeric` and round-trip as exact `Decimal`. SQLite `Numeric` decays to float, so money/round-trip test arms are gated to the Postgres `pg_backend` fixture (Pitfall 2 — `tests/integration/storage/test_sql_order_storage.py`).

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do not introduce a second ID scheme. Tests mint ids via `idgen._uuid7()` or `uuid_utils.compat.uuid7()` (`tests/integration/storage/test_sql_order_storage.py`).
- Determinism: a single seeded `random.Random` is constructed at engine wiring and injected into stochastic components (`ExecutionHandler._rng`, seed from config key `performance.rng_seed`, default 42). Never seed per-call. An injected `BacktestClock` (`core/clock.py`) is staged on the determinism seam.
- Time is a business `time` carried on events/records, never wall clock — tests pin a constant business time (`_BT = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)`) so derived `created_at`/`updated_at` are deterministic.
- v1.6 result codecs are byte-deterministic: the gzip frame codec encodes the same frame to identical bytes (`SqlResultsStore._encode_frame`, D-10).

## Logging

- Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")` (structlog).
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True`; `debug` rarely used.
- `make test` exports `ITRADER_DISABLE_LOGS=true`, which disables log emission and can fail `caplog` warn-assertion tests — use `poetry run pytest tests` as the gate for those.

## Comments & Docstrings

**When to Comment:**
- Heavy, decision-anchored. Comments explain WHY, often citing a locked decision tag or pitfall (`# D-04 — string entry`, `# RESEARCH Pitfall 5`, `# GATE-01 VIOLATION: ...`). Avoid restating what the code does.
- These tags (`D-01`, `D-13`, `M5-04`, `OPS-01`, `RESULT-02`, `GATE-02`, `Pitfall N`, `WR-NN`) are load-bearing references to planning artifacts — preserve them.
- **Cross-module citation caveat (IN-04):** when a comment cites another module by `FILE:LINE`, the SYMBOL named alongside (e.g. `SimulatedExchange.update_config`) is the durable anchor; the trailing `:line` is an approximate hint that drifts. Lead new citations with the symbol.

**Docstrings:**
- Modules open with a triple-quoted docstring; in v1.6 storage/test files this docstring enumerates the threats/decisions the module covers (see `tests/unit/storage/test_import_quarantine.py`, `tests/integration/storage/test_sql_order_storage.py`).
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks (`OrderHandler.__init__`).
- Test functions carry a one-line docstring naming the assertion AND its decision tag (e.g. `"""``top_runs`` on a fresh store returns ``[]`` (empty-safe, D-16)."""`).

## Function & Module Design

- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage).
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event onto the queue instead. Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel` Protocol, `BacktestBarFeed`).
- Events and value objects are `@dataclass` (frozen for immutability — events are `@dataclass(frozen=True, slots=True, kw_only=True)`). v1.6 record types (`RunRecord`, `PortfolioRecord`, `RunMetrics`) are field-wise dataclasses whose `__eq__` drives round-trip equality assertions.
- **Storage layering (v1.6):** a concern store (`Sql<Concern>Storage`) is constructed over a shared `SqlBackend` (`itrader/storage/backend.py`), itself built from a `SqlSettings`. Backend selection happens at wiring via factories with `'backtest'`/`'live'` arms; the backtest arm imports no SQL (GATE-01).
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `from itrader.storage import SqlBackend`).

---

*Convention analysis: 2026-06-30*
