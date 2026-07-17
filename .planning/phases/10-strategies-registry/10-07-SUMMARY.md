---
phase: 10-strategies-registry
plan: 07
subsystem: strategy-handler + universe + live-wiring
tags: [D-10, D-11, D-16, D-01, D-02, F-1, WD-1, STRAT-02, oracle-gated]
status: complete
requires:
  - "itrader/strategy_handler/registry/rehydrate.py (Plan 05 — build_strategy: the one reconstruction path add reuses)"
  - "itrader/strategy_handler/registry/catalog.py (Plan 04 — resolve_strategy_class / UnknownStrategyTypeError allowlist)"
  - "itrader/strategy_handler/strategies_handler.py::on_strategy_command (Plan 06 — the dispatch skeleton + warm seam)"
  - "itrader/price_handler/feed/cache_registration.py::required_base_depth (Plan 03 — the F-1 warmability boundary)"
  - "itrader/universe/universe_handler.py (P7 — spawn_warmup / _on_symbol_removed / on_bars_loaded, reached queue-only)"
  - "itrader/core/portfolio_read_model.py (PortfolioReadModel — the remove flat-detect seam)"
provides:
  - "StrategiesHandler._add_strategy_verb — D-10 add (catalog-gate, dark register, F-1 gate, persist, warm via the P7 poll)"
  - "StrategiesHandler._remove_strategy_verb + _pending_removals + on_fill — D-11 remove (force-flat first, pending, drop child-then-parent on flat)"
  - "StrategiesHandler.strategy_catalog / .portfolio_read_model — the two injected seams the heavy verbs need"
  - "LiveRouteRegistrar FILL now appends strategies_handler.on_fill (live-only; backtest _routes untouched)"
affects:
  - "Plan 08 (reconfigure) — reuses the same strategy_catalog + build_strategy seam; add/remove are now the concrete precedents"
  - "10-08 audit F1 confirmed: F-1 gate uses the EXISTING self.feed, no second handle injected"
tech-stack:
  added: []
  patterns:
    - "dispatch a new-name verb (add) BEFORE the by-name lookup guard"
    - "pending state across event cycles (mirrors pending-bracket / reconnect-resume) for a multi-cycle force-flat"
    - "exclude-from-membership-derivation (not from the roster) to drive the symbol-scoped P7 force-close while keeping the row"
    - "read-model degrade arm keyed on an attribute (getattr base_timeframe) rather than a redundant injected handle"
key-files:
  created:
    - tests/integration/test_strategy_add_warmup.py
    - tests/integration/test_strategy_remove_flat.py
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/trading_system/route_registrar.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/strategy/test_strategy_command_verbs.py
decisions:
  - "remove's force-close trigger = shape (a) REINTERPRETED: exclude the pending strategy from get_strategies_universe (the membership-DERIVING method), NOT from self.strategies — the instance stays registered (Test 1) and the row is kept until flat (crash-safety)."
  - "add is dispatched BEFORE the by-name lookup guard — it targets a NEW name the guard would reject."
  - "add does NOT call mark_unwarm/_request_rewarm: a freshly built instance is already dark; the cold-symbol warm path is the poll -> membership -> spawn_warmup (the plan's Task 1 action). ONE warm path (the P7 pipeline), no second path."
  - "F-1 gate uses the EXISTING self.feed (audit 10-07 F1), keyed on getattr(self.feed, base_timeframe) so the backtest feed skips cleanly — no second feed handle injected."
  - "strategies_handler.on_fill wired ONLY on the LIVE route_registrar FILL list (after portfolio/order/universe) — never on the backtest _routes, so the oracle path is untouched by construction."
metrics:
  duration: ~75m
  completed: 2026-07-17
  tasks: 3
  files: 6
  tests_added: 26
---

# Phase 10 Plan 07: D-10 `add` + D-11 `remove` — the heavy lifecycle verbs Summary

The two verbs that make the roster genuinely runtime-mutable land on the Plan 06 skeleton, and
they invent NO machinery: `add` reuses `build_strategy` (Plan 05) and the P7 warmup pipeline;
`remove` reuses the P7 universe force-close → detach-on-flat machinery — both reached through a
queue-emitted `UniversePollEvent`, never by import. `remove` adds the one genuinely new mechanism:
a pending-removal state, because the flat is observed on a LATER event cycle.

## What Was Built

**Task 1 — D-10 `add` (`f6c92b6d`, RED `1aff1c7a`).** `_add_strategy_verb` is dispatched BEFORE the
by-name lookup guard (add targets a new name). It gates on the injected `strategy_catalog` allowlist
(loud reject when None), rejects a duplicate name (D-02) and a malformed payload before construction,
builds through the IDENTICAL `build_strategy` path rehydrate uses (D-01), runs the F-1 warmability gate
(`required_base_depth` vs `self.feed.cache_capacity()`), registers via `add_strategy`, subscribes any
payload `portfolio_id`, persists, and emits the poll that IS the warmup wiring. Every rejection is a
loud no-op naming the error KIND, never the payload values, caught by SPECIFIC exception types.

**Task 2 — D-11 `remove` (`5081efff`, RED `24a966f1`).** `_remove_strategy_verb` deactivates (D-07
gate stops new entries), enters `_pending_removals`, persists `enabled=False`, and emits the poll —
then attempts immediate completion. `get_strategies_universe` excludes pending strategies, so the poll
re-derives membership without them and the P7 `_on_symbol_removed` force-close plays out. `on_fill`
(wired live-only, after `PortfolioHandler.on_fill`) re-scans pending removals and, once a strategy's
positions are observed flat via the injected `PortfolioReadModel`, drops the object + deletes
child-then-parent rows + recomputes `min_timeframe`. The registry row survives while pending
(crash-safety).

**Task 3 — integration coverage + live wiring (`aaa6f668`).** `build_live_system` now injects
`strategy_catalog` (the add allowlist) and `portfolio_handler` (the remove flat-detect read-model) into
the live handler, next to `registry_store`. Two offline CI-safe integration tests drive the verbs
end-to-end through a fully-wired paper system: a cold-symbol `add` registers dark → BarsLoaded warms it
→ it signals; a `remove` force-flats, survives while pending, and deletes both rows after the flat fill.

## The Load-Bearing Design Call (recorded per plan request)

`remove`'s force-close is SYMBOL-scoped (`_on_symbol_removed`), so it fires only when a symbol LEAVES
the derived membership. The plan offered shape (a) "drop the instance from the membership-visible
roster" vs (b) "keep it registered, drive force-close another way", but Test 1 requires the instance to
STAY in `self.strategies`. These reconcile: I excluded the pending strategy from
`get_strategies_universe` — the membership-DERIVING method — NOT from `self.strategies`. The instance
stays registered (Test 1 ✓) and its row is kept until flat (crash-safety ✓), while its tickers leave
membership so the poll's REMOVE branch force-closes them (D-11's "reuse the P7 machinery" ✓).

**Accepted limitation (P10 scope):** a symbol traded by BOTH a removed and a still-live strategy stays
a member via the live one, so the force-close (symbol-scoped) does not fire for the removed strategy's
position. The tests use non-shared symbols; the limitation is documented at the `get_strategies_universe`
exclusion site.

## Deviations from Plan

### 1. [Rule 3 — Blocking] `add` dispatched before the by-name lookup guard
- **Issue:** the plan slots `add` into `on_strategy_command`, but the shared `strategy is None` guard
  would reject every add (the name is not registered yet).
- **Fix:** `add` is handled at the top of `on_strategy_command`, before `by_name.get`. Documented in a
  comment; a pair `add` is likewise handled here (the verb-scoped pair guard governs only EXISTING pair
  instances).

### 2. [Acceptance criterion unsatisfiable — pre-existing code] `grep -c 'except Exception' == 0`
- **Issue:** the file already carries ONE `except Exception` in `update_config` (line 1151, a Plan-08-era
  D-08 reconfigure-wrapping that converts any `reconfigure` failure to the single web-catchable
  `ConfigurationError`). The grep returns 1, not 0.
- **Fix:** left untouched (out of scope; removing it breaks the D-08 single-catch contract). My new
  `_add_strategy_verb` / `_remove_strategy_verb` catch only SPECIFIC types — the criterion's INTENT (no
  NEW bare except) is met.

### 3. [Deviation from plan text] `add` does not call `mark_unwarm`/`_request_rewarm`
- **Issue:** the orchestrator prompt's warm-seam note says to reuse `mark_unwarm` + `_request_rewarm`,
  but that pair is the WARM re-warm path (enable, 10-06). A freshly-constructed instance is ALREADY dark.
- **Fix:** followed the plan's Task 1 action: the cold-symbol warm path is the poll → membership
  re-derive → new symbol → `spawn_warmup` → BarsLoaded. ONE warm path (the P7 pipeline reached via the
  queue), no second path built (`live_bar_feed` refuses one; LX-09).

### 4. [Deviation / audit 10-07 F1] no second feed handle injected for F-1
- **Issue:** the plan said "`StrategiesHandler` has no feed reference today; inject one". Audit F1 (FALSE)
  showed `self.feed` already exists and `cache_capacity()` is on the `BarFeed` ABC.
- **Fix:** the F-1 gate uses `self.feed.cache_capacity()` and keys on `getattr(self.feed, "base_timeframe",
  None)` — the LIVE feed carries `base_timeframe` (property), the backtest feed does not, so the gate
  skips cleanly on the backtest path. No redundant handle, no `live_trading_system` bloat.

### 5. [Rule 1 — Bug] `portfolio_id` stripped from the config blob before `build_strategy`
- **Issue:** the config_json blob is passed to `build_strategy`, whose `_apply_params` raises
  `UnknownParamError` on any non-declared key. A payload `portfolio_id` (a child-table concern) would
  therefore reject the whole add.
- **Fix:** the add branch builds the blob as the payload MINUS `portfolio_id`, then parses `portfolio_id`
  separately via `_portfolio_id_from` (the same boundary-parse the light verbs use, T-10-35) and
  subscribes it after registration.

### 6. [Route placement — strictly safer than planned] `on_fill` live-only
- **Issue:** the plan's threat model (T-10-45) assumed `strategies_handler.on_fill` would be added to the
  SHARED backtest `_routes` FILL list, relying on `_pending_removals` being empty in backtest.
- **Fix:** appended it ONLY to the LIVE `route_registrar` FILL list (after portfolio/order/universe). The
  backtest `EventHandler._routes` FILL stays `[portfolio, order]`, so `on_fill` never runs on the oracle
  path at all — a stronger guarantee than "empty set". The mandatory oracle gate still verified byte-exact.

### 7. [Existing test updated in lockstep] deferred-verbs test narrowed
- `test_verbs_deferred_to_later_plans_are_no_ops_here` → `test_reconfigure_is_still_a_no_op_here`: `remove`
  is now implemented, so only `reconfigure` (Plan 08) remains deferred.

## Verification Results

| Gate | Result |
|------|--------|
| **Backtest oracle (MANDATORY, byte-exact 134 / `46189.87730727451`)** | **PASS** (re-run after each task) |
| **OKX inertness (MANDATORY)** | **PASS** (4 passed) |
| `test_cache_classification.py` (the `@cache` trap) | **PASS** (4 passed) — no memoization added |
| `test_strategy_command_verbs.py` | **PASS** (49 tests: 27 pre-existing + 12 add + 10 remove) |
| `test_strategy_add_warmup.py` | **PASS** (2 — cold add → dark → ready → signal; BarsLoadFailed dark+registered) |
| `test_strategy_remove_flat.py` | **PASS** (2 — force-flat/pending/drop; no-position same-cycle) |
| `test_paper_restart_restore.py` + `test_live_portfolio_durable_wiring.py` | **PASS** (untouched) |
| **FULL tree `pytest tests` (incl. `tests/e2e`)** | **PASS — 2501 passed, 6 skipped** (OKX creds absent) |
| `mypy --strict` (whole package) | **clean (244 files)** |

All runs used `PYTHONPATH="$PWD"` to defeat worktree `.venv` shadowing; the FULL tree (incl. `tests/e2e`)
was gated per the 10-05 lesson.

**Source gates:** `build_strategy` present · `required_base_depth` present · `eval(` = 0 · `import
importlib` = 0 · cross-domain import (universe_handler/UniverseHandler/live_bar_feed) = 0 ·
`portfolio_handler` import = 0 · `D-10` = 8 · `D-11` = 15 · `_pending_removals` = 11 · handler space-indent
lines = 0 (stays TABS) · `strategy_catalog` in `live_trading_system` = 5 · network refs in the add test = 0.
The one `except Exception` is the pre-existing `update_config` wrapper (deviation 2).

## Threat Mitigations Applied

| Threat ID | Disposition | How |
|-----------|-------------|-----|
| T-10-41 | mitigated | `add` rejects loudly with no catalog and resolves ONLY through `resolve_strategy_class`; `eval(`/`import importlib` greps = 0; Tests `unknown_type` + `no_catalog`. |
| T-10-42 | mitigated | D-02 duplicate loud reject BEFORE construction; the existing row is re-read and asserted unchanged (`add_of_a_duplicate_name`). |
| T-10-43 | mitigated | F-1 gate compares `required_base_depth` vs `cache_capacity()` and rejects loudly; finer-than-base raises `UnwarmableTimeframeError` (Tests 6/6b/7). |
| T-10-44 | mitigated | `remove` force-flats first and drops only on the observed flat; the row survives while pending (Tests 1/2/4 + integration). |
| T-10-45 | mitigated | `on_fill` is on the LIVE route only, never the backtest `_routes`; the byte-exact oracle re-verified on every task. |
| T-10-46 | mitigated | Both verbs reach P7 through a queue-emitted `UniversePollEvent`; no cross-domain import (grep = 0). |
| T-10-47 | mitigated | `build_strategy` constructs via the real constructor, so `MissingParamError`/`UnknownParamError` fire before registration (Tests 5/5b). |
| T-10-49 | mitigated | Reject warnings name the strategy name, the verb, and the error KIND — never the config values. |

## Known Stubs

None. Both verbs are fully wired end-to-end and proven on offline integration drivers.

## Threat Flags

None. The one new operator-facing surface (the `add` payload → `build_strategy` → live instantiation) is
gated by the injected catalog allowlist and covered by T-10-41; no new network endpoint or schema change.

## For Future Plans

- **Plan 08 (`reconfigure`) reuses the SAME seams:** `strategy_catalog` + `build_strategy` for
  reconstruction, `_persist_strategy` for durability, the poll follow-on for re-warm. `add`/`remove` are
  now the concrete precedents.
- **Shared-symbol force-close limitation** (documented at `get_strategies_universe`): a symbol traded by
  both a removed and a live strategy is not force-closed by removing one. If per-strategy position
  ownership is ever needed, that is where a strategy-scoped force-close would go.
- **`add` requires a decode-ready blob** (config_json carrying `strategy_type` + `config_version`).
  `encode_strategy_config` stamps both; the future FastAPI ingress must encode the operator's raw params
  into that shape (or the decode fires a loud no-op) — the deferred FastAPI layer owns that + rate
  limiting (T-10-48, accepted).

## Self-Check: PASSED

- `itrader/strategy_handler/strategies_handler.py` — FOUND (modified)
- `itrader/trading_system/route_registrar.py` — FOUND (modified)
- `itrader/trading_system/live_trading_system.py` — FOUND (modified)
- `tests/integration/test_strategy_add_warmup.py` — FOUND, tracked
- `tests/integration/test_strategy_remove_flat.py` — FOUND, tracked
- Commits `1aff1c7a`, `f6c92b6d`, `24a966f1`, `5081efff`, `aaa6f668` — all verified in `git log`
- Working tree clean; no deletions across the branch; no STATE.md / ROADMAP.md changes (orchestrator-owned)

## TDD Gate Compliance

Tasks 1 & 2 followed RED → GREEN: `test(10-07) 1aff1c7a` → `feat(10-07) f6c92b6d`; `test(10-07) 24a966f1`
→ `feat(10-07) 5081efff`. Each RED was verified failing for the intended reason (add/remove not yet
dispatched). Task 3 is a `type="auto"` integration task (no RED gate required). No REFACTOR commits —
none needed.
