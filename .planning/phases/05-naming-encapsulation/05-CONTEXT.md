# Phase 5: Naming & Encapsulation - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Make names consistent and close the encapsulation gaps surfaced in the cleanup review — all
**behavior-preserving**. Five mechanical-but-precise renames/seams:

- **NAME-01** [W3-03, W3-10]: `OrderHandler` queue param/attr `events_queue → global_queue`; the
  count-by-status operation gets a single canonical name across façade and storage.
- **NAME-02** [W3-01, W3-02]: strategy classes → PascalCase; strategy-config windows →
  `fast_window`/`slow_window`/`signal_window`; all run-path importers updated; golden byte-exact.
- **NAME-03** [W3-08, W3-04]: `EventHandler` routes reachable through a public name (not `_routes`);
  `SimulatedExchange` exposes `register_symbol()` + a complete `update_config` seam; production code
  no longer mutates `_supported_symbols`/`_min_order_size` directly.
- **NAME-04** [W3-05, W3-07, W3-06]: tests assert through public query APIs, not
  `_by_id`/`_storage`/`_routes`/`_generate_correlation_id` internals.

**Verification gate (inherited milestone gate, D-00):** the SMA_MACD golden master re-runs
**byte-exact** (134 trades / `final_equity 46189.87730727451`), `pytest tests/e2e -m e2e` stays
58/58, `mypy --strict` clean across all source. This phase re-baselines nothing.

Out of scope: the `order_manager.py` god-module SPLIT (Phase 6 — FRAGILE-zone, isolated); any
semantics/behavior change; new contract work; deferred/off-path subsystems (live `TradingInterface`,
screeners, `strategy_handler/my_strategies/`); renaming strategy **module files** (D-02 decision).

</domain>

<decisions>
## Implementation Decisions

### Cross-cutting — verification & behavior-preservation
- **D-00 (milestone gate, inherited):** Every change is behavior-preserving — SMA_MACD golden
  master byte-exact (134 trades / `final_equity 46189.87730727451`); `tests/e2e` 58/58;
  `mypy --strict` clean. No new float-for-money; single UUIDv7 scheme. This is a pure naming /
  encapsulation phase: every rename is a value-/behavior-equal carrier swap, never a logic change.

### NAME-01 — queue naming + count-by-status canonical name (W3-03, W3-10)
- **D-01 (owner choice — fresh canonical name):** The count-by-status operation is currently
  **divergently named** — façade `get_orders_summary()` (`order_handler.py:328`,
  `order_manager.py:1293`) delegates to storage `get_orders_count_by_status()`
  (`base.py:258`, `in_memory_storage.py:177`, `postgresql_storage.py:53`). Collapse to **one
  fresh verb-first canonical name: `count_orders_by_status`** across **all four sites** — façade
  (`OrderHandler`), `OrderManager`, the `base.py` storage Protocol, and both storage backends.
  - **Rationale (owner-confirmed):** `get_orders_summary` is a misnomer — the method returns
    `Dict[str, int]` (status → count), not a summary; `count_orders_by_status` is self-describing
    (the "by status" makes the dict return obvious, where bare `count_orders` would read as `int`),
    and drops the `get_` prefix the encapsulation cleanup is moving away from.
  - The `postgresql_storage.py` backend is the deferred `NotImplementedError`/stub path — rename it
    for Protocol conformance but it stays a stub.
- **D-02 (queue rename):** In `OrderHandler` (`order_handler.py`), rename the constructor parameter
  `events_queue → global_queue`, the attribute `self.events_queue → self.global_queue`, and the
  five `self.events_queue.put(...)` call-sites (`:107,120,155,187,219`) plus the docstring at `:46`.
  This aligns `OrderHandler` with the `global_queue` convention every other handler already uses
  (the queue-only-cross-domain convention names it `global_queue`). The four `events_queue`
  references in `strategy_handler/my_strategies/` are **off-path / deferred** (user-supplied
  strategies under mypy `ignore_errors`) — **not touched** this phase.

### NAME-02 — strategy PascalCase + `*_window` config (W3-01, W3-02)
- **D-03 (owner choice — "attrs too, keep filenames"):** Rename reaches **class names + config
  Field names + instance attributes**, but **NOT the module filenames**:
  - Classes: `SMA_MACD_strategy → SMAMACDStrategy` (`strategies/SMA_MACD_strategy.py:39`),
    `Empty_strategy → EmptyStrategy` (`strategies/empty_strategy.py:14`).
  - Config Fields: `FAST/SLOW/WIN → fast_window/slow_window/signal_window` on `SMA_MACDConfig`
    (`SMA_MACD_strategy.py:27-29`); update the `_short_lt_long`/HARD-02 cross-field rule and the
    class docstring that cites `FAST=6, SLOW=12, WIN=3`.
  - Instance attributes: `self.FAST/self.SLOW/self.WIN → self.fast_window/self.slow_window/
    self.signal_window` (`:58-60`) and their read at the MACD call (`:92`
    `window_fast=self.fast_window`, etc.).
  - **Module filenames stay** `SMA_MACD_strategy.py` / `empty_strategy.py` — renaming files would
    add import-path churn and break git history for no naming-consistency gain (the literal ROADMAP
    wording only asks for class + config-window names; this decision extends to the instance attrs
    for internal consistency but stops at filenames).
- **D-04 (pure rename, no back-compat aliases):** No deprecation aliases for the old class /
  Field / attr names — every run-path importer is updated in the same change (consistent with the
  owner's clean-rename stance in prior phases; back-compat shims would be dead weight in a
  single-strategy reference engine). Importers to update (run-path only): `config/strategy.py`,
  the two strategy files, `tests/unit/strategy/test_strategy.py`,
  `tests/unit/strategy/test_strategy_config.py`, `tests/integration/test_backtest_oracle.py`,
  `test_backtest_smoke.py`, `test_reservation_inertness.py`, `scripts/run_backtest.py`,
  `scripts/normalize_data.py`, `scripts/crossval/{indicators,backtrader_run,backtesting_py_run}.py`.
  **Off-path / deferred (do NOT touch):** `strategy_handler/my_strategies/**` (those carry their own
  unrelated `FAST=`/`SLOW=` strategy classes under mypy `ignore_errors`).
- **D-05 (⚠ INDENTATION HAZARD — flag to executor):** the strategy files
  (`strategies/SMA_MACD_strategy.py`, `strategies/empty_strategy.py`) are **TAB-indented** handler
  modules; the `config/strategy.py` re-export module is **4-space**. The window-Field renames touch
  pydantic config classes that (per Phase-4 D-14/D-15) now live inside the TAB strategy files —
  match each file's existing indentation, never normalize.

### NAME-03 — public routes + exchange seam (W3-08, W3-04)
- **D-06 (owner choice — plain field rename for routes):** Rename `EventHandler._routes → routes`
  (a plain public attribute, **no `@property` wrapper, no `get_routes()` method**) at
  `full_event_handler.py:68` (definition), `:118` (dispatch read `self._routes[event.type]`), and
  `:29` (docstring). The requirement asks only for "a public name/accessor"; a plain rename is the
  smallest diff and the exposure is theoretical — the routes dict is wired once at construction
  under the single-writer contract and nothing mutates it at runtime. Update the five test files
  that read `._routes` to read `.routes` (see NAME-04).
- **D-07 (`register_symbol()` — close the direct-mutation gap):** Add a public
  `SimulatedExchange.register_symbol(symbol: str)` method that adds a symbol to this instance's
  supported set (the encapsulated form of the manual mutation at `execution_handler.py:109`:
  `simulated._supported_symbols = set(simulated._supported_symbols) | {'BTCUSD'}`). Replace that
  line with `simulated.register_symbol('BTCUSD')`. After this, **no production code mutates
  `_supported_symbols`/`_min_order_size` directly** — those stay private, written only via
  `__init__`, `register_symbol()`, and the existing `update_config` re-derivation block
  (`simulated.py:644-649`). `register_symbol` must remain a per-instance mutation (not the shared
  preset) and be idempotent (set union), preserving the DEF-01-B/Plan-01-04 behavior exactly.
- **D-08 (`update_config` seam — verify "complete", fill only real gaps):** `update_config(**kwargs)`
  already exists and is broad (`simulated.py:603-653`: maps all config keys, re-inits fee/slippage
  models, re-derives limits as Decimal, raises `ValueError` on unknown keys). The requirement's
  "complete `update_config` seam" is **largely already satisfied** — the planner audits it for any
  config field reachable only by direct attribute mutation and routes that through `update_config`;
  it does NOT redesign the method. Decimal-end-to-end is preserved (the existing `# DEC-02 / D-06`
  Decimal re-derivation at `:647` is the pattern; no `float()` on the limits path).

### NAME-04 — tests through public APIs (W3-05, W3-07, W3-06)
- **D-09 (owner choice — add public APIs where genuinely missing):** Rewrite tests to assert
  through public query APIs instead of `_by_id`/`_storage`/`_routes`/`_generate_correlation_id`.
  **Prefer existing public APIs** (`get_orders_by_status`, `get_order_history`, `get_active_orders`,
  `get_orders_by_ticker`, the new `routes` attr from D-06, `count_orders_by_status` from D-01,
  etc.); **but where a test genuinely needs read-state that no public method exposes, add a minimal
  public query method to the production class** rather than contorting the test — a missing public
  read is itself an encapsulation gap worth closing.
  - **Guardrail:** any newly added API must be a legitimate **read/query** (no test-only backdoors,
    no internal-state **setters**, no exposure of mutable internals beyond a copy). If a public
    surface is added, it is justified by a real product-side read need, not test convenience alone.
  - Test files known to reach internals (audit + update): `tests/unit/events/test_dispatch_registry.py`,
    `test_error_flow.py`, `tests/integration/test_event_wiring.py`,
    `tests/unit/order/test_order_timestamps.py`, `tests/unit/portfolio/test_state_storage.py`
    (all read `._routes`); plus the `_by_id`/`_storage`/`_generate_correlation_id` consumers under
    `tests/unit/order/` and `tests/unit/portfolio/` surfaced by the scout grep. The planner produces
    the exhaustive per-file mapping (internal access → public replacement / new API).
- **D-10 (verification rigor — lean, carried from Phase 3/4):** Gate on the byte-exact oracle +
  58/58 e2e + `mypy --strict`. The renamed public surfaces (`count_orders_by_status`, `routes`,
  `register_symbol`) may get **lean targeted unit assertions** where useful, but **no broad new
  SMA_MACD strategy test** (Phase-3 D-02 owner constraint carries forward). The test-hygiene
  rewrites (D-09) are themselves the bulk of the NAME-04 test work.

### Claude's Discretion
- Plan/wave decomposition across NAME-01..04 (likely: queue + count rename → strategy rename →
  routes/exchange seam → test-hygiene sweep; or group the SAFE oracle-dark renames and gate the
  strategy rename's golden re-run separately).
- Exact signature/return of `register_symbol` (likely `(symbol: str) -> None`) and whether it
  validates the symbol string.
- Whether any newly-added NAME-04 public query method is warranted, its exact name/signature, and
  which test reaches justify it (apply the D-09 guardrail).
- Extent of touched-path opportunistic cleanup (Phase-1 D-05 / `CLEANUP-STANDARD.md`).
- Exact home/wording of the D-08 `update_config` completeness-audit note.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §Phase 5 (Naming & Encapsulation) — goal + 5 success criteria.
- `.planning/REQUIREMENTS.md` NAME-01..04 (lines ~91-102) — the four requirements with source
  cleanup-review finding tags (W3-01..W3-10).

### Source findings (cleanup-review rationale + payoff/risk ratings)
- `.planning/codebase/V1.2-CLEANUP-REVIEW.md` — the W3-* rows behind NAME-01..04:
  W3-01/W3-02 (strategy PascalCase + `*_window`), W3-03/W3-10 (queue + count-by-status naming),
  W3-04 (`register_symbol`/`update_config` seam), W3-08 (public `routes`),
  W3-05/W3-06/W3-07 (test-internals access).

### Locked decisions & conventions
- `CLAUDE.md` §Conventions / §"Indentation" — the queue is always named `global_queue` (D-02 basis);
  the tab/space indentation hazard (D-05).
- `.planning/codebase/CONVENTIONS.md` — the four documented conventions incl. the tab/space hazard
  and the config-enum-in-`config/` exception.
- `.planning/codebase/CLEANUP-STANDARD.md` — touched-path opportunistic-cleanup standard.
- `.planning/phases/04-type-modeling/04-CONTEXT.md` §D-14/D-15 — the strategy-config co-location +
  indentation hazard that D-05 inherits (the window-Field renames touch the moved config classes).
- `.planning/phases/03-hot-path-performance/03-CONTEXT.md` §D-01/D-02 — the verification-rigor
  precedent (oracle byte-exact + lean tests, no new SMA_MACD strategy test) that D-10 follows.

### Code targets (verified during scout)
- `itrader/order_handler/order_handler.py:40,46,63,107,120,155,187,219` — `events_queue` →
  `global_queue` (D-02); `:328` `get_orders_summary` → `count_orders_by_status` (D-01).
- `itrader/order_handler/order_manager.py:1293-1295` — `get_orders_summary` →
  `count_orders_by_status` façade delegating to storage (D-01).
- `itrader/order_handler/base.py:258` — storage Protocol `get_orders_count_by_status` →
  `count_orders_by_status` (D-01).
- `itrader/order_handler/storage/in_memory_storage.py:177`,
  `itrader/order_handler/storage/postgresql_storage.py:53` — both backends (D-01; postgres is stub).
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:16,20,27-29,39,58-60,92` — config
  Fields + class + instance attrs (D-03); `strategies/empty_strategy.py:10,14` — class rename (D-03).
- `itrader/config/strategy.py` — re-exports `SMA_MACDConfig`/strategy symbols (importer to update,
  D-04); 4-space module (D-05).
- `itrader/events_handler/full_event_handler.py:29,68,118` — `_routes` → `routes` (D-06).
- `itrader/execution_handler/exchanges/simulated.py:98,102,387-388,467-471,603-653` —
  `_supported_symbols`/`_min_order_size`, `register_symbol` home, `update_config` seam (D-07/D-08).
- `itrader/execution_handler/execution_handler.py:109` — the direct-mutation line to replace with
  `register_symbol('BTCUSD')` (D-07).
- Test-internals consumers (NAME-04 / D-09): `tests/unit/events/test_dispatch_registry.py`,
  `test_error_flow.py`, `tests/integration/test_event_wiring.py`,
  `tests/unit/order/test_order_timestamps.py`, `tests/unit/portfolio/test_state_storage.py` (read
  `._routes`); plus `_by_id`/`_storage`/`_generate_correlation_id` consumers across
  `tests/unit/order/` and `tests/unit/portfolio/` (scout grep — planner produces exhaustive map).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`global_queue` convention** — every other handler already names its queue `global_queue`;
  D-02 is alignment, not invention.
- **`update_config(**kwargs)` already exists and is broad** (`simulated.py:603-653`) — D-08 audits
  it for completeness, it does not build the seam from scratch. The `get_supported_symbols()` /
  `get_config_dict()` read accessors already exist as the public-read pattern `register_symbol`
  complements.
- **Existing public order query APIs** (`get_orders_by_status`, `get_order_history`,
  `get_active_orders`, `get_orders_by_ticker`, `search_orders`) — the first stop for D-09 test
  rewrites before adding any new API.

### Established Patterns
- **Indentation hazard:** `order_handler/`, `execution_handler/`, `strategy_handler/` (incl.
  `strategies/`) are **TAB** modules; `config/`, `core/`, and `events_handler/` are **4-space**.
  `full_event_handler.py` (routes rename) and the strategy files are TAB; `config/strategy.py` is
  4-space. Match each file (D-05).
- **`.name`-based serialization / value-equal swaps** — prior phases established that renames on the
  golden path must be byte-inert; here the renames are identifier-only (no serialized string carries
  a method/attr name), so the strategy-config-Field rename is the only one whose golden re-run is
  load-bearing (config keys are not serialized into the golden CSV, but the indicator windows drive
  the trades — value-equal defaults `6/12/3` must be preserved under the new Field names).
- **mypy `--strict` as the gate** — `count_orders_by_status` Protocol rename must stay consistent
  across `base.py` + both backends + façade or mypy fails (the structural conformance check).

### Integration Points
- **Queue rename (D-02)** touches `OrderHandler` construction (the `global_queue` is passed in at
  wiring in both `TradingSystem` and `LiveTradingSystem` — verify the call-site keyword if any uses
  `events_queue=`).
- **Count rename (D-01)** spans façade → manager → storage Protocol → 2 backends; the Protocol
  (`base.py`) is the conformance anchor.
- **Strategy rename (D-03/D-04)** touches the strategy-config import graph + 12 run-path importers
  (tests/scripts/crossval); `my_strategies/` is explicitly excluded.
- **`register_symbol` (D-07)** sits at the `ExecutionHandler.init_exchanges` wiring — the BTCUSD
  golden-ticker admission (DEF-01-B) must stay behavior-identical.

</code_context>

<specifics>
## Specific Ideas

- **Owner stance — names must be self-describing (D-01):** the count-by-status rename was driven by
  the owner rejecting `get_orders_summary` as a misnomer ("it's really not a summary, it just
  returns a count") and choosing a fresh verb-first `count_orders_by_status` over keeping either
  legacy name. The principle: a method name should make its return type obvious.
- **Clean rename, no back-compat shims (D-04/D-06):** every rename updates all importers in the same
  change; no deprecation aliases. Consistent with the owner's prior-phase stance — this is a
  single-strategy reference engine, not a public library, so shims are dead weight.
- **Encapsulation = no direct private mutation from production code (D-07):** the
  `simulated._supported_symbols = ...` line at `execution_handler.py:109` is the canonical gap;
  `register_symbol()` is its encapsulated replacement, after which `_supported_symbols`/
  `_min_order_size` are written only through `__init__`/`register_symbol`/`update_config`.
- **Verification philosophy carried from Phase 3/4 (D-10):** byte-exact oracle proves correctness;
  lean targeted assertions prove the rename landed; no broad strategy test.

</specifics>

<deferred>
## Deferred Ideas

- **`order_manager.py` god-module SPLIT** → Phase 6 (dedicated, isolated, FRAGILE-zone). This phase
  only renames identifiers inside it (count-by-status façade), never restructures it.
- **Off-path id/queue/strategy naming** — `strategy_handler/my_strategies/**` (`events_queue`,
  `FAST=`/`SLOW=` in user-supplied strategies) and live `TradingInterface`/screeners are under mypy
  `ignore_errors` and PROJECT.md-deferred; not renamed here (revisit when those subsystems are
  de-deferred next milestone).
- **Strategy-setting-system refactor** (owner-noted, next milestone) — the reason D-03 keeps the
  rename to class/config/attr names and does NOT rename module files or redesign config wiring.

</deferred>

---

*Phase: 5-Naming & Encapsulation*
*Context gathered: 2026-06-11*
