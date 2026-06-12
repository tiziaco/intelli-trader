# Phase 05: Naming & Encapsulation - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** ~16 source + ~10 test sites (behavior-preserving rename phase, not greenfield)
**Analogs found:** 3 / 3 new public surfaces mapped to existing in-codebase analogs

> **Phase shape (read first):** This is a **behavior-preserving naming & encapsulation refactor**.
> The bulk of the work is **in-place identifier renames** of EXISTING code (params, attrs, methods,
> class names, config Fields). Only **2-3 genuinely-new public surfaces** are added
> (`register_symbol`, the `count_orders_by_status` canonical name, and possibly one NAME-04 read API).
> The planner needs (a) concrete shapes for those 2-3 surfaces and (b) a per-file
> indentation + exact-site table so executors never normalize indentation. Both are below.

---

## Indentation Regime per Touched File (D-05 — VERIFIED against live code)

> **Load-bearing convention.** No autoformatter guards this. A space-indented edit in a TAB file is
> a defect. Match each file exactly; never normalize. (Correction to a common assumption:
> `full_event_handler.py` is **TAB**, not 4-space — verified below.)

| File | Indent | Touched by |
|------|--------|-----------|
| `itrader/order_handler/order_handler.py` | **TAB** | D-01 (count), D-02 (queue) |
| `itrader/order_handler/order_manager.py` | **TAB** | D-01 (count façade) |
| `itrader/order_handler/base.py` | **4-space** | D-01 (storage Protocol) |
| `itrader/order_handler/storage/in_memory_storage.py` | **4-space** | D-01 (backend) |
| `itrader/order_handler/storage/postgresql_storage.py` | **4-space** | D-01 (stub backend) |
| `itrader/execution_handler/exchanges/simulated.py` | **TAB** | D-07 (`register_symbol`), D-08 (`update_config` audit) |
| `itrader/execution_handler/execution_handler.py` | **TAB** | D-07 (replace direct-mutation line :109) |
| `itrader/events_handler/full_event_handler.py` | **TAB** ⚠ | D-06 (`_routes` → `routes`) |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | **TAB** ⚠ | D-03 (class + config Fields + attrs) |
| `itrader/strategy_handler/strategies/empty_strategy.py` | **TAB** | D-03 (class rename) |
| `itrader/config/strategy.py` | **4-space** | D-04 (re-export importer) |
| All `tests/**` | **4-space** | D-04, D-09 |

---

## File Classification

| Surface | Role | Data Flow | Status | Closest Analog | Match |
|---------|------|-----------|--------|----------------|-------|
| `SimulatedExchange.register_symbol(symbol)` | exchange-method | transform (set-union mutation) | **NEW** | `update_config` limits re-derivation (`simulated.py:644-649`) + `get_supported_symbols` read accessor (`:469-471`) | exact-role |
| `count_orders_by_status` (canonical name) | query method (façade→mgr→storage→2 backends) | CRUD-read | **RENAME** of `get_orders_summary`/`get_orders_count_by_status` | the chain itself + sibling `get_orders_by_status` | self |
| NAME-04 new read API (only if a test reaches read-state no public method exposes) | query method | CRUD-read | **CONDITIONAL** | `get_orders_by_status` / `get_active_orders` / `get_order_history` / `get_orders_by_ticker` / `search_orders` (`order_manager.py:1273-1291`) | exact-role |
| `routes` (was `_routes`) | public attribute | n/a (dict literal, wired once) | **RENAME** (plain field, no property) | n/a — plain rename | self |

---

## Pattern Assignments — New Public Surfaces

### `SimulatedExchange.register_symbol(symbol: str) -> None` (D-07, NEW)

**File:** `itrader/execution_handler/exchanges/simulated.py` — **TAB indent**

**How `_supported_symbols` is currently built / mutated (the shapes the new method must match):**

Init (`:98`):
```python
		# Exchange limits and settings
		self._supported_symbols = self.config.limits.supported_symbols
```

`update_config` re-derivation block (`:644-649`) — the only other writer today:
```python
		# Update internal state for limits
		if any(k in ['supported_symbols', 'min_order_size', 'max_order_size'] for k in kwargs):
			self._supported_symbols = self.config.limits.supported_symbols
			# DEC-02 / D-06: re-derived as Decimal (no float() — mirror init, Decimal end-to-end).
			self._min_order_size = self.config.limits.min_order_size
			self._max_order_size = self.config.limits.max_order_size
```

Existing public read accessor to mirror in style (`:465-471`):
```python
	def validate_symbol(self, symbol: str) -> bool:
		"""Check if symbol is supported for trading."""
		return symbol in self._supported_symbols

	def get_supported_symbols(self) -> set[str]:
		"""Get set of supported trading symbols."""
		return self._supported_symbols.copy()
```

**Shape to copy** — per-instance, idempotent set-union, no `float()`, TAB-indented, docstring with
decision tag. Must reproduce EXACTLY the behavior at `execution_handler.py:109`
(`set(...) | {symbol}`), so the golden BTCUSD admission (DEF-01-B) stays byte-identical:
```python
	def register_symbol(self, symbol: str) -> None:
		"""Add `symbol` to this instance's supported set (D-07).

		Encapsulates the direct `_supported_symbols` mutation. Per-instance
		(not the shared preset) and idempotent (set union), so re-registering
		is a no-op. Keeps `_supported_symbols` written only via __init__,
		this method, and the update_config re-derivation block.
		"""
		self._supported_symbols = set(self._supported_symbols) | {symbol}
```

**Then replace the direct-mutation gap** at `execution_handler.py:109` (**TAB indent**):
```python
		# was:  simulated._supported_symbols = set(simulated._supported_symbols) | {'BTCUSD'}
		simulated.register_symbol('BTCUSD')
```
Keep the surrounding DEF-01-B / Plan-01-04 comment block (`:105-108`) intact.

> **D-09 guardrail check:** `register_symbol` is a legitimate product-side admission seam (it replaces
> a real production-code mutation), NOT a test-only backdoor. It mutates a private set via a narrow,
> idempotent method — allowed. `_supported_symbols` / `_min_order_size` stay private after this.

---

### `count_orders_by_status` canonical rename (D-01) — the full 4+1 site chain

The operation is **divergently named today**: façade `get_orders_summary` → storage
`get_orders_count_by_status`. Collapse to ONE fresh verb-first name `count_orders_by_status` across
**every** site. The storage **Protocol (`base.py`) is the mypy conformance anchor** — Protocol +
both backends + both façade methods must all change together or `mypy --strict` fails.

| # | Site | File | Line | Current name | Indent |
|---|------|------|------|--------------|--------|
| 1 | façade (OrderHandler) | `order_handler/order_handler.py` | `:328` | `get_orders_summary` | TAB |
| 2 | façade (OrderManager) | `order_handler/order_manager.py` | `:1293` | `get_orders_summary` → delegates to storage | TAB |
| 3 | storage Protocol | `order_handler/base.py` | `:257-258` | `get_orders_count_by_status` (`@abstractmethod`) | 4-space |
| 4 | in-memory backend | `order_handler/storage/in_memory_storage.py` | `:177` | `get_orders_count_by_status` | 4-space |
| 5 | postgres stub backend | `order_handler/storage/postgresql_storage.py` | `:53` | `get_orders_count_by_status` (stays `NotImplementedError`) | 4-space |

**Delegation chain to preserve** (only the method NAME changes; body/return `Dict[str, int]` identical):

Façade → manager (`order_manager.py:1293-1295`, TAB):
```python
	def get_orders_summary(self, portfolio_id: Optional[PortfolioId] = None) -> Dict[str, int]:
		"""Get a summary of orders by status."""
		return self.order_storage.get_orders_count_by_status(portfolio_id)
```
becomes:
```python
	def count_orders_by_status(self, portfolio_id: Optional[PortfolioId] = None) -> Dict[str, int]:
		"""Count orders by status (status name -> count)."""
		return self.order_storage.count_orders_by_status(portfolio_id)
```

Backend body (`in_memory_storage.py:177-183`, 4-space) — rename signature only, keep logic:
```python
    def count_orders_by_status(self, portfolio_id: Optional[IdLike] = None) -> Dict[str, int]:
        """Count orders by status (status name -> count)."""
        status_counts: Dict[str, int] = {}
        for order in self._orders(portfolio_id):
            status_name = order.status.name
            status_counts[status_name] = status_counts.get(status_name, 0) + 1
        return status_counts
```

Postgres stub (`postgresql_storage.py:53`, 4-space) — rename for Protocol conformance, stays a stub:
```python
    def count_orders_by_status(self, portfolio_id=None):
        raise NotImplementedError("To be implemented in Phase 2")
```

> Also update the OrderHandler façade docstring at `order_handler.py:328-340` to drop the "summary"
> wording (owner: it returns a count, not a summary). No serialized string carries this method name,
> so this rename is **oracle-dark** (no golden re-run risk).

---

### `routes` (was `_routes`) — plain field rename (D-06)

**File:** `itrader/events_handler/full_event_handler.py` — **TAB indent** ⚠ (verified — this file is
TAB even though much of `events_handler/events/` is 4-space). Plain attribute rename; **no
`@property`, no `get_routes()`**. Three sites:

| Line | Site | Current |
|------|------|---------|
| `:29` | class/module docstring | "Routing is data: ``self._routes`` maps each ``EventType``…" |
| `:68` | definition | `self._routes: dict[EventType, list[Callable[[Any], Any]]] = {` |
| `:118` | dispatch read | `handlers = self._routes[event.type]` |

No back-compat alias (D-04/D-06). Then update the test reader (see NAME-04 below).

---

### NAME-04 conditional new read API (D-09) — analogs if one is needed

**Prefer existing public query APIs first.** If, and only if, a test genuinely needs read-state no
public method exposes, add a minimal **read/query** method (guardrail: no setters, no test-only
backdoor, no mutable-internal exposure beyond a copy). Match the shape of the existing order-query
family in `order_manager.py:1273-1291` (all `-> List[Order]`, optional `portfolio_id`, one-line
docstring, pure delegation to storage):

```python
	def get_orders_by_status(self, status: OrderStatus, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""Get all orders with a specific status."""
		return self.order_storage.get_orders_by_status(status, portfolio_id)

	def get_active_orders(self, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		...

	def get_order_history(self, order_id: OrderId) -> List[Dict[str, Any]]:
		...
```
A new read API should be a verb-first/`get_`-prefixed pure delegator returning a value or a copy,
mirroring these. The `get_supported_symbols` copy-return pattern (above) is the analog for any
exchange-side read.

---

## NAME-04 Test-Hygiene Rewrites — EXHAUSTIVE Internal-Access Map (verified by grep)

> CONTEXT.md D-09 listed several test files (`test_error_flow.py`, `test_event_wiring.py`,
> `test_order_timestamps.py`, `test_state_storage.py`) that **do not exist / have moved** in the live
> tree. The TRUE current consumers are below. Planner: produce the per-assertion mapping from these.

### `._routes` consumers → rewrite to `.routes` (D-06)
| File | Sites |
|------|-------|
| `tests/unit/events/test_dispatch_registry.py` | 9 reads — lines `:81,90,99,103,104,109,110,115` (+ docstring `:4`). Pattern `wiring.handler._routes[EventType.X]` → `wiring.handler.routes[EventType.X]`. |

This is the **only** `._routes` consumer in the live tree. (No `_routes` reads in
`test_error_flow`/`test_event_wiring`/`test_order_timestamps`/`test_state_storage` — those files are
absent.)

### `._by_id` consumers → rewrite through public order query API
| File | Sites |
|------|-------|
| `tests/unit/order/test_order_storage.py` | 6 reads — `:155,156,170,174,227` use `store.storage._by_id[...]`. Replace with `get_order(oid)` / `get_orders_by_status` / membership via a public getter. (`:227` reads `.price` — needs `get_order(oid).price`.) |

### `_generate_correlation_id` consumers → assert observable effect, not the private helper
| File | Sites |
|------|-------|
| `tests/unit/portfolio/test_portfolio_handler.py` | 2 reads. Replace direct `_generate_correlation_id` access with an assertion on the emitted event / public state that carries the correlation id. |

### `_supported_symbols` direct-mutation in tests → use `register_symbol` (D-07 follow-through)
| File | Sites | Action |
|------|-------|--------|
| `tests/unit/execution/exchanges/test_simulated_exchange.py` | `:148` reads `self.exchange._supported_symbols == new_symbols` | After D-07, assert via `get_supported_symbols()`; if a test sets symbols, use `register_symbol`. |
| `tests/integration/test_universe_spans.py` | `:141` mutates `simulated._supported_symbols = set(...) | {...}`, `:149` reads it | Replace mutation with `register_symbol(...)`; read via `get_supported_symbols()`. |
| `tests/e2e/conftest.py` | `:348` mutates `_supported_symbols` (note `:311` already documents NOT touching it on one path) | Replace the `:348` mutation with `register_symbol(...)`. |

### Softer `._storage` reads (NOT in NAME-04 scope unless they hide a missing public read)
`_storage` in the portfolio managers is accessed almost entirely **through public getters**
(`pm._storage.get_positions()`, `cm._storage.get_cash_operations()`, `mm._storage.get_snapshots()`)
across `test_position_manager.py`, `test_cash_manager.py`, `test_transaction_manager.py`,
`test_metrics_manager.py`. These read the private `_storage` HANDLE but call its **public** methods —
a milder gap than `._by_id`. The two writes that DO reach raw internals
(`test_cash_manager.py:266,271` — `cm._storage.add_reservation(...)` / `pop_reservation(...)`) are
the candidates to route through a public API or leave as documented white-box manager tests per the
D-09 guardrail. Planner adjudicates; not a blocker.

---

## Strategy Rename (D-03/D-04) — Site + Importer Confirmation

**Classes / Fields / attrs (TAB files — never normalize):**

`strategies/SMA_MACD_strategy.py` (TAB):
| Line | Current | New |
|------|---------|-----|
| `:16` | `class SMA_MACDConfig(BaseStrategyConfig):` | keep `SMA_MACDConfig` (config class name unchanged — only Field names) |
| `:27-29` | `FAST/SLOW/WIN: int = Field(default=6/12/3, gt=0)` | `fast_window/slow_window/signal_window` |
| `:19-20` | docstring cites `FAST=6, SLOW=12, WIN=3` | update wording |
| `:32` `_short_lt_long` (HARD-02 rule) | references `FAST`/`SLOW` | update field refs |
| `:39` | `class SMA_MACD_strategy(Strategy):` | `SMAMACDStrategy` |
| `:51` | `super().__init__("SMA_MACD", config)` | **string `"SMA_MACD"` unchanged** (name literal, not class) |
| `:58-60` | `self.FAST/SLOW/WIN = config.FAST/...` | `self.fast_window/slow_window/signal_window = config.fast_window/...` |
| `:92` | `window_fast=self.FAST, window_slow=self.SLOW, window_sign=self.WIN` | `=self.fast_window, =self.slow_window, =self.signal_window` |

`strategies/empty_strategy.py` (TAB): `:14` `class Empty_strategy(Strategy):` → `EmptyStrategy`
(`EmptyStrategyConfig` at `:10` already PascalCase — leave).

> **Golden re-run is load-bearing here only.** Config keys are not serialized into the golden CSV,
> but the window values DRIVE the indicator (`:92`) and thus the trades — the new Field defaults must
> stay value-equal `6/12/3`. This is the one rename whose byte-exact re-run (134 trades /
> `46189.87730727451`) actually exercises the change.

**Run-path importers to update (D-04, verified — `my_strategies/**` EXCLUDED):**
- `itrader/config/strategy.py` (4-space) — re-export module (docstring + any symbol re-export)
- `tests/unit/strategy/test_strategy.py` (`:41,43,55,57,101,127,138,147`)
- `tests/unit/strategy/test_strategy_config.py` (`:20,30,50,62,82,93`)
- `tests/integration/test_backtest_smoke.py` (`:21,45`)
- `tests/integration/test_backtest_oracle.py` (`:255-257,276,283`)
- `tests/integration/test_reservation_inertness.py` (`:70,79`)
- `scripts/run_backtest.py` (`:48,77,84`)
- `scripts/crossval/{indicators,backtrader_run,backtesting_py_run}.py` — **comments/docstrings only**
  reference `SMA_MACD_strategy` (filename, unchanged) and `FAST=`; these are verbatim-quote comments,
  not imports — update only if the quoted Field name is now stale (low priority, oracle-dark).
- `scripts/normalize_data.py:116` — comment reference to the module file (unchanged) — no code change.

> Importing `SMA_MACDConfig` keeps working (config class name unchanged); `SMA_MACD_strategy` →
> `SMAMACDStrategy` is the importable symbol that breaks — every `import ... SMA_MACD_strategy` and
> `SMA_MACD_strategy(...)` call-site above must update in the same change (no back-compat alias).

---

## D-02 Queue Rename — Site Confirmation

`itrader/order_handler/order_handler.py` (**TAB**) — verified sites:
| Line | Current |
|------|---------|
| `:40` | `def __init__(self, events_queue: "Queue[Any]", ...)` → `global_queue` |
| `:46` | docstring `events_queue: `Queue object`` |
| `:63` | `self.events_queue = events_queue` → `self.global_queue = global_queue` |
| `:107,120,155,187,219` | `self.events_queue.put(order_event)` → `self.global_queue.put(...)` |

> **Wiring check (integration point):** verify `OrderHandler(...)` construction in
> `backtest_trading_system.py` and `live_trading_system.py` — if either passes the queue by keyword
> (`events_queue=...`) that call-site must update too. The 4 `events_queue` refs under
> `strategy_handler/my_strategies/` are **off-path / deferred — NOT touched** (D-02).

---

## D-08 `update_config` Completeness Audit (not a redesign)

`update_config(**kwargs)` (`simulated.py:603-653`, TAB) already maps all 16 config keys, re-inits
fee/slippage models, re-derives Decimal limits (`:644-649`), and raises `ValueError` on unknown keys.
The audit task: confirm no config field is reachable ONLY by direct attribute mutation (route any
such field through `update_config`); do NOT redesign the method. The Decimal re-derivation at
`:647-649` (`# DEC-02 / D-06`) is the no-`float()` pattern to preserve. `get_config_dict()`
(`:655-672`) is the read mirror.

---

## No Analog Found

None. Every new surface has a direct in-codebase analog (set-union mutation + copy-return read for
`register_symbol`; the existing query family for `count_orders_by_status` and any NAME-04 read).
No RESEARCH.md-only patterns are needed.

---

## Metadata

**Analog search scope:** `itrader/order_handler/`, `itrader/execution_handler/`,
`itrader/events_handler/`, `itrader/strategy_handler/strategies/`, `itrader/config/`, `tests/`, `scripts/`
**Line numbers:** verified against live code 2026-06-11 (HEAD `f6b998a`, branch `v1.2/phase-5-naming`)
**Indentation:** verified per-file with `grep -P '^\t'`
**Pattern extraction date:** 2026-06-11
