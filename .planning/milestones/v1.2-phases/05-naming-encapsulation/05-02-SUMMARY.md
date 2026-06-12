---
phase: 05-naming-encapsulation
plan: 02
subsystem: api
tags: [encapsulation, naming, event-dispatch, execution-handler, simulated-exchange, decimal]

# Dependency graph
requires:
  - phase: 05-naming-encapsulation
    provides: "05-PATTERNS.md indentation regime + exact-site map; D-06/D-07/D-08 decisions"
provides:
  - "Public EventHandler.routes attribute (plain field, no property) — D-06"
  - "Public SimulatedExchange.register_symbol(symbol) admission seam — D-07"
  - "Direct-mutation gap at execution_handler.py:109 closed (register_symbol('BTCUSD'))"
  - "D-08 update_config completeness audit confirmed — no config field reachable solely by direct mutation"
affects: [05-04, NAME-04, test-hygiene, order-manager-decomposition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Encapsulated private-set mutation behind a narrow, idempotent public method (set-union, no float, per-instance) — mirrors get_supported_symbols copy-return style"
    - "Public plain-field rename for once-wired, never-runtime-mutated dispatch registry (no @property ceremony)"

key-files:
  created: []
  modified:
    - itrader/events_handler/full_event_handler.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/execution_handler.py

key-decisions:
  - "D-06: _routes -> routes as a plain public attribute (no @property, no get_routes()) — smallest diff; dict wired once at construction under single-writer contract, nothing mutates it at runtime"
  - "D-07: register_symbol(symbol) reproduces the exact set-union at execution_handler.py:109 — per-instance, idempotent, no float() — so DEF-01-B BTCUSD admission stays byte-identical"
  - "D-08: update_config confirmed complete — _supported_symbols/_min_order_size/_max_order_size are written only via __init__, register_symbol, and the update_config re-derivation block; no production field is reachable solely by direct attribute mutation"

patterns-established:
  - "Admission seam: replace raw `_x = set(_x) | {v}` production mutation with a documented public method tagged to its decision"

requirements-completed: [NAME-03]

# Metrics
duration: ~8min
completed: 2026-06-11
---

# Phase 05 Plan 02: Naming & Encapsulation (NAME-03) Summary

**Public `EventHandler.routes` attribute + `SimulatedExchange.register_symbol()` admission seam that closes the direct `_supported_symbols` mutation gap — golden master byte-exact (134 trades / 46189.87730727451), 58/58 e2e, mypy --strict clean.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-11
- **Completed:** 2026-06-11
- **Tasks:** 3 (2 implementation, 1 verification gate)
- **Files modified:** 3

## Accomplishments
- Renamed `EventHandler._routes` → `routes` as a plain public attribute (D-06) across all three sites (docstring, definition, dispatch read) — no property wrapper, no `get_routes()`, no back-compat alias.
- Added public `SimulatedExchange.register_symbol(symbol: str) -> None` (D-07) — an idempotent, per-instance set-union seam mirroring the `get_supported_symbols` read-accessor style.
- Closed the direct-mutation gap at `execution_handler.py:109`: the raw `simulated._supported_symbols = set(...) | {'BTCUSD'}` line now calls `simulated.register_symbol('BTCUSD')`, with the DEF-01-B/Plan-01-04 comment block intact and a D-07 routing note added.
- Completed the D-08 `update_config` completeness audit: `_supported_symbols`/`_min_order_size`/`_max_order_size` are written only via `__init__`, `register_symbol`, and the `update_config` re-derivation block — no production code reaches any config field solely by direct attribute mutation.
- Proved NAME-03 behavior-preserving: integration oracle byte-exact, e2e 58/58, `mypy --strict` clean, zero golden/oracle baseline files edited.

## Task Commits

Each implementation task was committed atomically:

1. **Task 1: Rename EventHandler _routes → routes (D-06)** - `010ef56` (refactor)
2. **Task 2: Add register_symbol() seam + close direct-mutation gap + D-08 audit (D-07/D-08)** - `9f8cfb9` (feat)
3. **Task 3: Behavior-preserving gate (golden + e2e + mypy)** - verification-only, no files, no commit

## Files Created/Modified
- `itrader/events_handler/full_event_handler.py` - `_routes` → `routes` plain public rename (3 sites); TAB preserved.
- `itrader/execution_handler/exchanges/simulated.py` - Added `register_symbol(symbol)` public method after `get_supported_symbols`; TAB preserved.
- `itrader/execution_handler/execution_handler.py` - Replaced direct `_supported_symbols` mutation with `register_symbol('BTCUSD')`; comment block kept + D-07 note added; TAB preserved.

## Decisions Made
- **D-06 (plain field, not property):** the routes dict is wired once at construction under the single-writer contract and nothing mutates it at runtime, so a plain public attribute is the smallest correct diff — no `@property`/`get_routes()` ceremony.
- **D-07 (byte-identical seam):** `register_symbol` body is the exact set-union the old line performed, so the golden BTCUSD admission (DEF-01-B) is unchanged. The rename is oracle-dark (no serialized string carries the attr/method name).
- **D-08 (audit, not redesign):** confirmed `update_config` already routes every config key, re-inits fee/slippage models, re-derives Decimal limits (no `float()`), and raises on unknown keys — no field is reachable solely by direct mutation. No redesign performed.

## Deviations from Plan

None - plan executed exactly as written.

## D-08 Audit Record

Grep of production code (`itrader/`) for direct writers of the three encapsulated fields:

- `_supported_symbols =` → exactly 3 writers, all in `simulated.py`: `__init__` (:98), `register_symbol` (:481), `update_config` re-derivation (:656). No production writer outside `simulated.py` (the prior `execution_handler.py:109` writer is now removed).
- `_min_order_size =` / `_max_order_size =` → 2 writers each, both in `simulated.py`: `__init__` (:102/:103) and `update_config` (:658/:659). Reachable only via `__init__` and the complete `update_config` seam — never by direct attribute mutation from outside.

Conclusion: `update_config` is the complete config-update seam; no config field is reachable only by direct attribute mutation. No new field needed routing.

## Known Stubs

None introduced. (`postgresql_storage.py` and other pre-existing stubs are outside this plan's touched files.)

## Issues Encountered
None. (One transient: the initial `execution_handler.py` Edit failed because the file had not been Read in-session — resolved by reading the target section first, then editing.)

## Next Phase Readiness
- `routes` and `register_symbol`/`get_supported_symbols` public surfaces are in place for plan 05-04 (NAME-04 test hygiene), which rewrites the `._routes` / `_supported_symbols` test consumers to use these public accessors.
- Milestone gate held byte-exact — no oracle re-baseline; no blockers.

## Self-Check: PASSED

- Files: all 3 modified source files + SUMMARY.md present on disk.
- Commits: `010ef56` (Task 1), `9f8cfb9` (Task 2) both present in git log.
- Gate: oracle 3/3 byte-exact, e2e 58/58, mypy --strict clean (162 files), no baseline edited.

---
*Phase: 05-naming-encapsulation*
*Completed: 2026-06-11*
