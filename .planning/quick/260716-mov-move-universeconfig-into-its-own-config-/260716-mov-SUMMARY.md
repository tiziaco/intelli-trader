---
phase: quick-260716-mov
plan: 01
subsystem: config
tags: [config, refactor, universe, one-domain-per-file]
status: complete
requires: []
provides:
  - "itrader/config/universe.py — UniverseConfig new home"
affects:
  - itrader/config/system.py
  - itrader/config/__init__.py
  - itrader/config/itrader_config.py
  - itrader/trading_system/config_router.py
  - itrader/trading_system/live_trading_system.py
tech-stack:
  added: []
  patterns: ["config/ one-domain-per-file convention"]
key-files:
  created:
    - itrader/config/universe.py
  modified:
    - itrader/config/system.py
    - itrader/config/__init__.py
    - itrader/config/itrader_config.py
    - itrader/trading_system/config_router.py
    - itrader/trading_system/live_trading_system.py
decisions:
  - "UniverseConfig moved VERBATIM (byte-identical body + docstring) — pure relocation, zero behavior change."
  - "Field import dropped from config/system.py: SystemSettings uses only ConfigDict + plain-default fields, so Field became unused after the move."
  - "Barrel __init__.py re-exports UniverseConfig from .universe; __all__ unchanged so `from itrader.config import UniverseConfig` still resolves."
metrics:
  duration: 6min
  completed: 2026-07-16
requirements: [QT-260716-mov]
---

# Quick Task 260716-mov: Move UniverseConfig into its own config/universe.py Summary

Relocated `UniverseConfig` from `itrader/config/system.py` into a dedicated
`itrader/config/universe.py`, matching the `config/` one-domain-per-file convention —
a pure mechanical move with byte-identical class body and docstring, zero behavior change.

## What Changed

- **NEW `itrader/config/universe.py`** (4-space indentation) — holds `UniverseConfig`
  verbatim (`model_config = ConfigDict(extra="forbid", validate_assignment=True)`,
  `poll_cadence_s: float = Field(default=60.0, gt=0.0)`,
  `remove_policy: str = "orphan-and-track"`) plus its original docstring. Module docstring
  documents the relocation, live/control-plane-only usage, off-hot-path, pydantic/stdlib-only
  inertness (GATE-01). Imports `from pydantic import BaseModel, ConfigDict, Field`.
- **`config/system.py`** — deleted the `UniverseConfig` class; kept `Environment`,
  `LogLevel`, `SystemSettings`. Dropped the now-unused `Field` from the pydantic import
  (SystemSettings uses only `ConfigDict` + plain-default fields). Module docstring updated
  to note the relocation and drop the UniverseConfig ownership sentence.
- **`config/__init__.py`** — `UniverseConfig` removed from the `from .system import (...)`
  block; added `from .universe import UniverseConfig`. `__all__` unchanged (still lists it).
- **Consumers repointed** (UniverseConfig split onto its own `from itrader.config.universe
  import UniverseConfig` line, rest kept from `.system`):
  - `config/itrader_config.py`
  - `trading_system/config_router.py`
  - `trading_system/live_trading_system.py` (two local imports at ~:1039 and ~:1178)

## Verification

Task 1 automated gate (move):
- `test -f itrader/config/universe.py` → FILE OK
- Zero `from itrader.config.system import ... UniverseConfig` lines remain → GREP OK
- `class UniverseConfig` gone from system.py → SYSTEM OK
- Runtime probe: `c.universe` is a `UniverseConfig`, `poll_cadence_s == 60.0`,
  `remove_policy == 'orphan-and-track'`, `sqlalchemy`/`ccxt` not imported → `MOVE OK`

Task 2 gate (all green — real output):
- `poetry run pytest tests -q` → **2307 passed, 6 skipped** (skips are OKX-credential-gated) in 38.12s
- `poetry run pytest tests/integration/test_okx_inertness.py -q` → **4 passed** — config/universe.py pydantic/stdlib-only, inertness intact
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → **3 passed** — byte-exact 134 / 46189.87730727451
- `poetry run mypy itrader` → **Success: no issues found in 261 source files**

## Deviations from Plan

None - plan executed exactly as written. `Field` was correctly anticipated as removable
from system.py (the plan flagged the conditional removal); confirmed unused by the kept
classes.

## Commits

- `d5a9deac`: refactor(config): move UniverseConfig to its own config/universe.py

## Self-Check: PASSED

- `itrader/config/universe.py` — FOUND
- Commit `d5a9deac` — FOUND in git log
