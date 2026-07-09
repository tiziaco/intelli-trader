---
phase: 01-config-centralization
plan: 04
subsystem: infra
tags: [pydantic, config, live-trading, okx, inertness, constant-fold]

# Dependency graph
requires:
  - phase: 01-02
    provides: HaltReason enum + live_trading_system.py baseline-residual retirement (current state built on)
provides:
  - "StreamSettings + FeedProviderSettings pure-pydantic config home (config/stream.py)"
  - "Reconnect-supervisor family folded into StreamSettings at its 3 live readers"
  - "Warmup margin + REST backfill page folded into FeedProviderSettings"
  - "Composition-root _OKX_*/_PAPER_* constants retired; PAPER_PARITY_* anchor preserved"
affects: [phase-05-venue-registry, phase-07-safety-reconciliation-stream-recovery, StreamSupervisor, config-centralization]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config-at-owner's-cardinality (LR-21): live-only supervisor/feed knobs live in domain config models (StreamSettings/FeedProviderSettings), not SystemConfig"
    - "P1 config seam: a default-constructed StreamSettings()/FeedProviderSettings() read at the reader is the interim seam; composition-root injection + shared StreamSupervisor deferred to P5 (D-08)"
    - "Guard-clause default resolution: function default arg becomes `int | None = None`, resolved from config inside the body (no module-level constant reintroduced)"

key-files:
  created:
    - itrader/config/stream.py
    - tests/unit/config/test_stream_settings.py
  modified:
    - itrader/config/__init__.py
    - itrader/config/models.py
    - itrader/price_handler/providers/okx_provider.py
    - itrader/portfolio_handler/account/venue.py
    - itrader/execution_handler/exchanges/okx.py
    - itrader/execution_handler/exchanges/venue_correlation.py
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/universe/universe_handler.py
    - itrader/price_handler/providers/replay_provider.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/universe/test_universe_warmup_consumers.py
    - tests/e2e/test_okx_sandbox_recon.py

key-decisions:
  - "StreamSettings reconnect fields are float/int (not Decimal) — non-money supervisor tunables, matching current live read-site usage; the naming-collision config/exchange.py::ConnectionSettings (Decimal time fields) is deliberately NOT overloaded"
  - "live_trading_system.py uses 4-space indentation (verified by od), NOT tabs as the project_gate stated — matched the actual file"
  - "Paper stream timeframe read site sourced from _STREAM_SETTINGS.okx_stream_timeframe (byte-identical '1d') per plan's 'same anchor/config with identical value'"
  - "Pre-existing GATE-01 quarantine failure (from plan 01-01) logged to deferred-items.md, NOT fixed — out of scope (config/system.py not owned by this plan)"

patterns-established:
  - "Grep-clean gate: directory-wide grep over itrader/ for a retired constant must return empty — comments/docstrings must not name the deleted constant either"
  - "_OKX_INTERVALS lookup table + PAPER_PARITY_* parity anchor are functional data / single-source anchors, explicitly preserved (not folded)"

requirements-completed: [CFG-03]

coverage:
  - id: D1
    description: "StreamSettings + FeedProviderSettings config home (pure pydantic), defaults == retired constants, extra=forbid, barrel re-exports"
    requirement: CFG-03
    verification:
      - kind: unit
        ref: "tests/unit/config/test_stream_settings.py (6 tests)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (config/stream pulls nothing live)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reconnect-supervisor family folded into StreamSettings at okx_provider/venue/okx exchange; venue_correlation comment updated; _STREAM_RECONNECT grep-clean"
    requirement: CFG-03
    verification:
      - kind: unit
        ref: "poetry run pytest tests/unit (1768 passed)"
        status: pass
      - kind: other
        ref: "grep -rn _STREAM_RECONNECT itrader/ (empty)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Warmup/backfill folded into FeedProviderSettings; _OKX_*/_PAPER_* composition-root constants retired to StreamSettings + PAPER_PARITY_* anchor; all 4 grep-clean gates empty; _OKX_INTERVALS + PAPER_PARITY_* preserved"
    requirement: CFG-03
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (134 / 46189.87730727451, check_exact)"
        status: pass
      - kind: integration
        ref: "tests/integration/test_paper_parity.py (Pitfall 4 — no parity drift)"
        status: pass
      - kind: other
        ref: "grep -rn _WARMUP_MARGIN|_BACKFILL_PAGE|_OKX_STREAM|_PAPER_STREAM|_PAPER_EXPECTED itrader/ (empty)"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-09
status: complete
---

# Phase 01 Plan 04: Live-Stream/Feed Constant Fold Summary

**Scattered live-only supervisor/feed magic numbers (`_STREAM_RECONNECT_*` ×3, `_WARMUP_MARGIN`, `_BACKFILL_PAGE`, `_OKX_STREAM_*`, `_PAPER_*`) folded into two pure-pydantic domain config models — `StreamSettings` + `FeedProviderSettings` — with every live reader rewired and the directory grep-clean, oracle byte-exact, and inertness gate all green.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-09T12:14:00Z
- **Completed:** 2026-07-09T12:40:00Z
- **Tasks:** 3
- **Files modified:** 15 (2 created, 10 source modified, 2 test modified, 1 planning doc)

## Accomplishments
- New `itrader/config/stream.py` — pure pydantic + stdlib `StreamSettings` (reconnect debounce/backoff-base/backoff-cap/retry-ceiling + OKX stream symbol/timeframe) and `FeedProviderSettings` (warmup margin + backfill page); both `extra="forbid"` with a `.default()` classmethod; re-exported from both `config/` barrels.
- Reconnect-supervisor family (triplicated verbatim across `okx_provider.py`, `account/venue.py`, `okx.py`) collapsed to a single `StreamSettings` read at each `__init__`.
- Warmup margin (`live_bar_feed.py`, `universe_handler.py`) and REST backfill page (`okx_provider.py` sync+async, `replay_provider.py`) fold into `FeedProviderSettings`; the backfill readers switched to `limit: int | None = None` with guard-clause resolution.
- Composition-root `_OKX_STREAM_*` retired to a module-level `_STREAM_SETTINGS = StreamSettings()`, and the `_PAPER_STREAM_*`/`_PAPER_EXPECTED_*` aliases dereferenced to the retained `PAPER_PARITY_*` anchor directly (Pitfall 4 — parity window/symbol byte-identical).
- All four grep-clean gates empty; `_OKX_INTERVALS` lookup table and `PAPER_PARITY_*` anchor preserved.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create StreamSettings + FeedProviderSettings config home, barrels, failing test** - `55ce3084` (feat)
2. **Task 2: Fold reconnect-supervisor family into StreamSettings at its three readers** - `68b4d70a` (feat)
3. **Task 3: Fold warmup/backfill + retire _OKX_*/_PAPER_* composition-root constants** - `ad3a190f` (feat)

## Files Created/Modified
- `itrader/config/stream.py` - NEW; `StreamSettings` + `FeedProviderSettings` (pure pydantic + stdlib)
- `tests/unit/config/test_stream_settings.py` - NEW; pins defaults == retired constants, extra=forbid, barrel import
- `itrader/config/__init__.py`, `itrader/config/models.py` - barrel re-exports for both new models
- `itrader/price_handler/providers/okx_provider.py` - reconnect + backfill fold; `_OKX_INTERVALS` preserved
- `itrader/portfolio_handler/account/venue.py` - reconnect fold
- `itrader/execution_handler/exchanges/okx.py` (tabs) - reconnect fold
- `itrader/execution_handler/exchanges/venue_correlation.py` (tabs) - stale comment updated
- `itrader/price_handler/feed/live_bar_feed.py` - warmup fold
- `itrader/universe/universe_handler.py` - warmup fold (+ docstring)
- `itrader/price_handler/providers/replay_provider.py` - backfill fold
- `itrader/trading_system/live_trading_system.py` - `_OKX_*`/`_PAPER_*` retirement; `PAPER_PARITY_*` kept
- `tests/unit/universe/test_universe_warmup_consumers.py` - updated to read `FeedProviderSettings().warmup_margin`
- `tests/e2e/test_okx_sandbox_recon.py` - stale comment updated

## Decisions Made
- **Reconnect fields float/int, not Decimal:** they are non-money supervisor tunables; the existing `config/exchange.py::ConnectionSettings` (a different concept using Decimal time fields) is deliberately not overloaded (PATTERNS naming-collision note).
- **`live_trading_system.py` is 4-space, not tabs:** verified via `od -c` on the actual read-site lines; the project_gate's tabs claim was wrong for this file. Matched the real indentation (never normalized).
- **Paper stream timeframe** sourced from `_STREAM_SETTINGS.okx_stream_timeframe` (byte-identical `"1d"`) — the plan explicitly allowed "the same anchor/config with the identical value".

## Deviations from Plan

None to the fold work — plan executed as written. One out-of-scope discovery was logged (below), not fixed.

## Issues Encountered

### Pre-existing GATE-01 import-quarantine failure (out of scope — logged, not fixed)
- **Discovered during:** Task 2, running `poetry run pytest tests/unit`.
- **Symptom:** `tests/unit/storage/test_import_quarantine.py::test_backtest_storage_path_imports_no_sql` fails with `GATE-01 VIOLATION: sqlalchemy imported on the backtest storage path`.
- **Root cause:** `itrader/config/system.py:16` does a MODULE-LEVEL `from itrader.config.sql import SqlSettings`; because `itrader/__init__.py` constructs `SystemConfig.default()` at import, importing anything under `itrader` eagerly pulls `config/sql.py` → `from sqlalchemy import URL`. This defeats plan **01-01**'s own stated goal (keep `SqlSettings`/Postgres off the import graph).
- **Introduced by:** commit `476df49a` — `feat(01-01): add eager runtime + lazy sql …` (Wave 1, already complete) — an ancestor of this plan; the failure predates 01-04.
- **Why not fixed here:** `config/system.py` is not in this plan's `files_modified` and the defect is unrelated to the CFG-03 fold (SCOPE BOUNDARY rule). Logged to `.planning/phases/01-config-centralization/deferred-items.md` with a suggested one-line fix (move the `SqlSettings` import under `TYPE_CHECKING`, import lazily in the `sql` cached_property body).
- **This plan's own gates unaffected:** `test_okx_inertness.py` (the plan's inertness gate) stays green — the fold introduced no new leak; `config/stream.py` imports only pydantic.

## Verification Evidence (real command output)
- Grep-clean (all empty over `itrader/`): `_STREAM_RECONNECT`, `_WARMUP_MARGIN`, `_BACKFILL_PAGE`, `_OKX_STREAM|_PAPER_STREAM|_PAPER_EXPECTED`.
- Preserved: `_OKX_INTERVALS` present; `PAPER_PARITY_` present (14 refs) in `live_trading_system.py`.
- `poetry run pytest tests/unit`: **1768 passed** (1 deselected = the pre-existing 01-01 quarantine test).
- Frozen gates: `test_backtest_oracle.py` (134 / `46189.87730727451`, `check_exact=True`) + `test_okx_inertness.py` — **5 passed**.
- Paper-parity / live lifecycle / warmup: `test_paper_parity.py` + live integration set — **passed** (Pitfall 4 confirmed).
- `mypy --strict` on all 6 changed source files — **Success: no issues found**.

## Next Phase Readiness
- P5's shared `StreamSupervisor` now has one typed source (`StreamSettings`) to read; composition-root injection is the remaining seam (D-08).
- **Carry-forward for the phase verifier / a 01-01 remediation:** the pre-existing GATE-01 quarantine regression in `config/system.py` (see `deferred-items.md`). It is a real inertness defect in a sibling completed plan and should be adjudicated before the phase closes.

## Self-Check: PASSED

- Created files verified on disk: `itrader/config/stream.py`, `tests/unit/config/test_stream_settings.py`, `01-04-SUMMARY.md`.
- Task commits verified in git log: `55ce3084`, `68b4d70a`, `ad3a190f`.

---
*Phase: 01-config-centralization*
*Completed: 2026-07-09*
