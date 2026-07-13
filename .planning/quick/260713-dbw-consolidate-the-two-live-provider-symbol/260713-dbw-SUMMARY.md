---
task: quick-260713-dbw
title: Consolidate the two live-provider symbols into one
status: complete
subsystem: price_handler/providers
tags: [refactor, protocol, live-provider, venue-registry, inertness]
requires:
  - LiveDataProvider @runtime_checkable Protocol (existing)
provides:
  - Single-symbol live_provider.py (LiveDataProvider Protocol only)
  - Standalone ReplayDataProvider with inline no-op streaming seams
affects:
  - itrader/price_handler/providers/live_provider.py
  - itrader/price_handler/providers/replay_provider.py
  - itrader/trading_system/live_trading_system.py
  - tests/unit/price_handler/test_live_provider.py
  - tests/unit/price/test_replay_provider.py
key-files:
  created: []
  modified:
    - itrader/price_handler/providers/live_provider.py
    - itrader/price_handler/providers/replay_provider.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/price_handler/test_live_provider.py
    - tests/unit/price/test_replay_provider.py
decisions:
  - "Removed the concrete BaseLiveDataProvider no-op base class — its only value was inheritable no-op defaults for a single non-streaming consumer (ReplayDataProvider)."
  - "ReplayDataProvider now implements the 7 optional streaming/wiring seams DIRECTLY as inline no-ops; it inherits nothing and still satisfies the LiveDataProvider @runtime_checkable Protocol structurally."
  - "STATE.md decision entries (05-03) that reference BaseLiveDataProvider are historical records and were left untouched; no runtime code or comment references the base after this task."
metrics:
  duration: ~6min
  tasks: 3
  files_modified: 5
  completed: 2026-07-13
---

# Quick Task 260713-dbw: Consolidate the two live-provider symbols Summary

Collapsed `live_provider.py` from two symbols to one: deleted the concrete
`BaseLiveDataProvider` no-op base class and kept only the `LiveDataProvider`
`@runtime_checkable` Protocol. Its sole production consumer, `ReplayDataProvider`,
stopped inheriting the base and now defines the 7 optional streaming/wiring seams
inline as no-ops while still conforming to the Protocol structurally. Identical
runtime behavior, a leaner surface, inertness preserved.

## What Changed

### Task 1 — Trim `live_provider.py` to the single Protocol (commit `666a3597`)
- Deleted the entire `BaseLiveDataProvider` class (class statement, docstring, all 7
  no-op method bodies).
- Kept the `LiveDataProvider` `@runtime_checkable` Protocol intact (REQUIRED
  `set_bar_sink` + 7 OPTIONAL streaming-seam stubs with `...` bodies unchanged).
- Rewrote the module docstring and the Protocol class docstring to describe a single
  symbol; reframed the non-streaming-provider note to "implements the optional seams
  directly as no-ops" and the `set_bar_sink` note to "a no-op default would silently
  drop every bar, so each concrete provider MUST implement it."
- No import line changed (`TYPE_CHECKING, Any, Protocol, runtime_checkable` +
  `TYPE_CHECKING`-guarded `Callable` all still consumed by the Protocol signatures).

### Task 2 — Make `ReplayDataProvider` standalone (commit `2ee51e45`)
- Removed the `BaseLiveDataProvider` import and the inheritance (`class
  ReplayDataProvider:`).
- Added the 7 optional streaming/wiring seams inline as one-line no-ops with the exact
  Protocol signatures, in a clearly-commented section after `fetch_ohlcv_backfill`;
  the real `set_bar_sink` / `replay_bar` / `iter_closed_bars` / `fetch_ohlcv_backfill`
  are untouched.
- Changed `from typing import Callable` → `from typing import Any, Callable` (`Any`
  now needed for `set_global_queue`).
- Rewrote the class docstring "Uniform provider surface" paragraph (implements
  directly, no inherit; `isinstance(..., LiveDataProvider)` stays True).
- Reworded the `live_trading_system.py` provider→feed wiring comment (comment-only,
  no logic change) to say the replay provider no-ops the streaming seams via its own
  inline no-op methods.

### Task 3 — Update the two test modules (commit `d3dec871`)
- `tests/unit/price_handler/test_live_provider.py`: import only `LiveDataProvider`;
  deleted the `_BaseBackedProvider` helper and the six base-specific tests (bare-base
  streaming-seam no-ops, bare-base `is_streaming_healthy`, base-does-not-default
  `set_bar_sink`, base-subclass-conforms, bare-base-not-yet-a-provider,
  set_bar_sink-override-honoured). Kept `_FakeFullProvider` +
  `test_protocol_is_runtime_checkable_fake_conforms`,
  `test_okx_data_provider_conforms_structurally`, and
  `test_live_provider_module_imports_nothing_heavy` (inertness guard). Trimmed the
  module docstring's numbered list to the two surviving points.
- `tests/unit/price/test_replay_provider.py`: import only `LiveDataProvider`; dropped
  the `isinstance(provider, BaseLiveDataProvider)` assertion (kept the
  `LiveDataProvider` one); renamed
  `test_replay_provider_inherited_streaming_seams_are_noops` →
  `..._inline_streaming_seams_are_noops` and reworded its comment (assertions
  unchanged).

## Verification (actual output)

- `poetry run mypy --strict itrader/price_handler/providers/live_provider.py itrader/price_handler/providers/replay_provider.py`
  → `Success: no issues found in 2 source files`
- `poetry run pytest tests/unit/price_handler/test_live_provider.py tests/unit/price/test_replay_provider.py -v`
  → `10 passed in 0.13s` (3 in test_live_provider, 7 in test_replay_provider)
- `grep -rn 'BaseLiveDataProvider' itrader/ tests/` (raw, incl. comments/docstrings)
  → NO MATCHES ANYWHERE — the base is gone from code, comments, and docstrings.
- Venues + providers import smoke
  (`import itrader.venues.bundle, .assemble, .lifecycle, .okx_plugin, .paper_plugin;
  import ...live_provider, ...replay_provider`)
  → `venues + providers import OK`
- Optional broader safety net `poetry run mypy itrader`
  → `Success: no issues found in 244 source files`

## Deviations from Plan

None — plan executed exactly as written.

## Threat Model Outcome

- **T-dbw-01 (inertness posture):** preserved — `test_live_provider_module_imports_nothing_heavy`
  kept and green; no `ccxt`/`sqlalchemy`/`asyncio` import added. The two providers'
  import lines are unchanged apart from adding `Any` to `replay_provider`'s stdlib
  `typing` import.
- **T-dbw-02 (Protocol conformance / VenueLifecycle wiring):** verified —
  `isinstance(ReplayDataProvider(), LiveDataProvider)` stays True (Task 2 verify) and
  the venues import smoke proves the `VenueLifecycle`/plugin surface still imports and
  stays inert.

## Notes

- Ran NON-ISOLATED directly on branch `v1.8/phase-5-venue-registry` (confirmed before
  every commit). No branch created/switched; `main` untouched.
- STATE.md's historical 05-03 decision bullets still mention `BaseLiveDataProvider` as
  a record of the prior state; those are archival and were intentionally not edited.

## Self-Check: PASSED

- Modified files exist on disk: live_provider.py, replay_provider.py,
  live_trading_system.py, test_live_provider.py, test_replay_provider.py — all present.
- Commits exist: `666a3597` (Task 1), `2ee51e45` (Task 2), `d3dec871` (Task 3) — all in
  `git log`.
