---
phase: quick-260718-di7
plan: 01
subsystem: strategy-registry
status: complete
tags: [CR-01, WR-01, WR-02, IN-02, IN-01, rehydrate, warmup, docstrings]
requires: [STRAT-01, STRAT-02, STRAT-03]
provides:
  - "rehydrate loads the full roster via read_all() honoring enabled as is_active"
  - "derive_warmup_depth floored at NEWEST_BAR_ONLY (never 0)"
affects:
  - itrader/strategy_handler/registry/rehydrate.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/price_handler/feed/cache_registration.py
  - itrader/events_handler/events/universe.py
tech-stack:
  added: []
  patterns: [duck-typed-store-protocol, derive-once-at-wiring, present-but-dark-rehydrate]
key-files:
  created: []
  modified:
    - itrader/strategy_handler/registry/rehydrate.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/price_handler/feed/cache_registration.py
    - itrader/events_handler/events/universe.py
    - tests/unit/strategy/test_rehydrate.py
    - tests/unit/price_handler/test_cache_registration.py
decisions:
  - "CR-01 Option 2 (LOCKED): honor enabled as is_active — disabled rows load present-but-dark, not dropped"
  - "read_all() gets its first production caller here — resolves IN-01 with no separate action"
metrics:
  duration: ~15min
  completed: 2026-07-18
  tasks: 3
  files: 6
---

# Quick Task 260718-di7: Fix Phase 10 Code-Review Findings (CR-01/WR-01/WR-02/IN-02) Summary

Remediated the Phase 10 durable-strategy-registry code-review findings: the rehydrate/persistence
contract mismatch (CR-01, blocker), the all-zero-warmup depth crash (WR-01), and two docstring gaps
(WR-02 live-pair warmup, IN-02 add-factory payload shape). All three tasks committed atomically; full
strategy unit suite + phase-10 integration tests + `mypy itrader` green.

## What Changed

### Task 1 — CR-01: rehydrate the full roster (honor `enabled` as `is_active`)
- `rehydrate.py`: `StrategyRegistryReader` Protocol replaced `list_active()` + `portfolio_subscriptions()`
  with a single `read_all()`; `rehydrate_strategies` now loads via `store.read_all()`, consumes each
  record's inline `portfolio_ids`, and calls `strategy.deactivate_strategy()` for `enabled=False` rows so
  a disabled/removing strategy is reconstructed present-but-dark (`is_active` False, re-enable-able, owning
  its positions) rather than silently dropped. The malformed-id resolution stays INSIDE the per-row `try`
  so a bad id still quarantines atomically. D-19 quarantine, `RehydrateInfrastructureError` loud arm, D-02
  duplicate reject, D-21 empty-valid, and deterministic order preserved. The catalog-None error string
  reworded "enabled row(s)" → "row(s)".
- `strategies_handler.py`: `on_strategy_command` `disable` bullet + `_remove_strategy_verb` docstring now
  state the real post-fix restart guarantee, PLUS the no-auto-resume caveat (`_pending_removals` is
  in-memory only) and the removing-vs-disabled indistinguishability footgun.
- `test_rehydrate.py`: old `test_rehydrate_skips_disabled_rows` rewritten to
  `test_rehydrate_reconstructs_disabled_rows_present_but_dark` (both rows load; disabled one `is_active`
  False and re-enable-able); `_BrokenStore.list_active` → `read_all`; ordering test renamed to `read_all`.
- **IN-01 resolved** as a side effect: `read_all()` now has a production caller.

### Task 2 — WR-01: floor `derive_warmup_depth` at `NEWEST_BAR_ONLY`
- `cache_registration.py`: both return paths wrapped in `max(NEWEST_BAR_ONLY, ...)`, so a non-empty
  all-zero-warmup roster (handle-free `EmptyStrategy` / `EthBtcPairStrategy`) returns 1, never 0 — which
  would register `StrategyWarmupConsumer(required_history_depth=0)` and crash the next `cache_capacity()`
  on the `< 1` WR-06 guard. `Returns` docstring updated with the floor.
- `test_cache_registration.py`: added `test_derive_warmup_depth_non_empty_all_zero_warmup_floors_at_newest_bar`
  covering both scaled and unscaled branches.

### Task 3 — WR-02 + IN-02: documentation-only
- `strategies_handler.py::on_bars_loaded`: documents a live `PairStrategy` is NOT warmed by the
  `BarsLoaded` bulk path (spread bookkeeping fills only via `update_pair`, not the inherited `update()`);
  `is_pair_ready` gate blocks wrong trades meanwhile (accepted P10 scope). Body byte-unchanged.
- `universe.py::StrategyCommandEvent.add`: documents `config` must be a version-stamped `config_json`
  blob (carrying `int config_version`), not bare authoring kwargs, else `decode_strategy_config` rejects
  it (a silent loud-no-op for a FastAPI client). Factory body byte-unchanged.

## Deviations from Plan

None — plan executed exactly as written. Indentation matched per file (TABS in `rehydrate.py` /
`strategies_handler.py`; 4 SPACES in `cache_registration.py` / `universe.py` / both test files); no
normalization diff.

## Verification

Actual command output (this session):

- `poetry run pytest tests/unit/strategy/ tests/unit/price_handler/test_cache_registration.py
  tests/integration/test_strategy_registry_restart.py tests/integration/test_strategy_remove_flat.py
  tests/integration/test_strategy_external_add_lifecycle.py tests/integration/test_strategy_add_warmup.py -q`
  → **322 passed, 9 skipped in 2.97s**. The 9 skips are all `PostgreSQL container unavailable` (environmental
  — no local Postgres/Docker), unrelated to this change.
- `poetry run mypy itrader` → **Success: no issues found in 266 source files**.
- Per-task gates were also run green: Task 1 (310 passed, 9 skipped), Task 2 (10 passed), Task 3 (329 passed).
- Gate note: used `poetry run pytest` (not `make test`) per project memory — `make test` disables logs /
  aborts on `.env`. Prepended `PYTHONPATH="$PWD"` per the worktree-venv-shadowing memory (harmless on the
  main checkout).

## Commits

- `bad7fc40` — fix(10): rehydrate disabled strategy rows present-but-dark (CR-01)
- `4c039357` — fix(10): floor derive_warmup_depth at NEWEST_BAR_ONLY (WR-01)
- `992b31a5` — docs(10): clarify live-pair warmup + add-factory payload (WR-02/IN-02)

## Known Stubs

None.

## Self-Check: PASSED

- All 6 modified files exist and are committed.
- Commits `bad7fc40`, `4c039357`, `992b31a5` present in `git log`.
