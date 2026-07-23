---
phase: quick-260723-dc4
plan: 01
subsystem: venues + trading_system composition
tags: [refactor, hygiene, code-review-closure, WR-02, WR-07, WR-09]
status: complete
requires:
  - "itrader/venues/registry.py::COMPUTE_VENUE + DEFAULT_ACCOUNT_ID (the two constants, already homed)"
provides:
  - "single-home account-id routing key: venues.registry.DEFAULT_ACCOUNT_ID imported by all four venue modules"
  - "single-home compute-venue routing key across all three trading_system lookup sites"
  - "fail-loud non-streaming venue_exchange fallback in live_trading_system"
affects:
  - itrader/venues/
  - itrader/trading_system/
  - itrader/order_handler/
  - itrader/execution_handler/
  - itrader/portfolio_handler/
tech-stack:
  added: []
  patterns:
    - "routing-key constants live once in the import-inert venue substrate; consumers import, never re-declare"
    - "composition-root venue lookups are subscripts (fail-loud KeyError), not soft .get"
key-files:
  created: []
  modified:
    - itrader/venues/bundles.py
    - itrader/venues/assemble.py
    - itrader/venues/venue_uid_guard.py
    - itrader/venues/okx_plugin.py
    - itrader/trading_system/universe_wiring.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - itrader/execution_handler/execution_handler.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/account/conformance.py
decisions:
  - "The live non-streaming venue_exchange fallback is now a subscript — the batch's one deliberate behaviour change, required by WR-07."
metrics:
  duration: 5min
  completed: 2026-07-23
---

# Quick Task 260723-dc4: Phase 11.1 Review Hygiene (WR-02 / WR-07 / WR-09) Summary

Collapsed the duplicated `'default'` and `'paper'` routing-key literals onto the two
`itrader/venues/registry.py` constants, promoted the live non-streaming venue-exchange
fallback from a silent `.get` to a fail-loud subscript, and removed the dead code and
stale contract descriptions the phase's own deletions left behind.

## What Was Built

**Task 1 (WR-02) — `42f87e6e`.** Deleted the three private `_DEFAULT_ACCOUNT_ID = "default"`
copies in `bundles.py`, `assemble.py` and `venue_uid_guard.py`, and the two inline
`spec.account_id or "default"` literals in `okx_plugin.py`. All four modules now import
`DEFAULT_ACCOUNT_ID` from `itrader.venues.registry` (confirmed import-inert — its only
imports are `from __future__ import annotations` and `from typing import TYPE_CHECKING`,
so the new edge cannot redden the inertness gate).

The factually-false four-line "zero-dependency import-inertness posture" rationale above the
`bundles.py` and `assemble.py` assignments was deleted outright, not reworded — `bundles.py`
imports `itrader.logger` and `assemble.py` imports `itrader.venues.lifecycle`, so the claim
never held. No replacement comment was written (the `bundles.py::get` docstring already
states the normalization rule). The `venue_uid_guard.py` comment was *not* false — it explains
that a NULL PK half writes a row that never matches on a later connect — so its substance was
kept and moved down to annotate the use site at `assert_venue_uid`.

**Task 2 (WR-07) — `5d977669`.** Extended the existing
`from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID` line in all three
files to `COMPUTE_VENUE, DEFAULT_ACCOUNT_ID` (no new import statement, no new import edge —
that module already re-exports both in `__all__`).

- `universe_wiring.py:104-105` — `COMPUTE_VENUE` as the key half; the subscript (and its
  `KeyError`) retained. The `ConfigurationError` f-string now interpolates `COMPUTE_VENUE`;
  the rendered message is byte-identical because the constant's value is that same string.
- `backtest_trading_system.py:432-433` — `COMPUTE_VENUE` key half; left as `.get` per plan
  (hardening it is outside this finding). The `# D-27/D-05 pair key` comment retained.
- `live_trading_system.py:636-643` — **the one deliberate behaviour change.** The `else` arm
  changed from `.get((...))` to `exchanges[(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)]`, so a stale
  key raises rather than passing `None` into `SessionInitializer` and silently degrading
  `validate_symbol` / `resolve_precision`. The streaming arm is untouched. I independently
  re-verified the plan's safety claim before writing the comment that records it:
  `ExecutionHandler.init_exchanges` (`execution_handler.py:303`) unconditionally resolves
  `self._venue_bundles.get(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID, None)`, so the new subscript
  cannot raise on a normally-wired engine.

**Task 3 (WR-09) — `264c74bc`.** Three independent cleanups: deleted `VenueBundles.logger` and
its `get_itrader_logger` import (verified unread — the attribute had exactly two occurrences
tree-wide, both on those lines, and no external `.logger` read); corrected both stale
`account_factory(portfolio)` contract descriptions in `assemble.py` and `conformance.py` to
the real keyword-only call `lifecycle.bundle.account_factory(account_id=account_id)`; and
dropped the five unused imports, each re-verified as its file's only occurrence before deletion.

## Verification Results

All four plan gates green, run from the repo root after all three commits:

| Gate | Command | Result |
|------|---------|--------|
| 1. Byte-exact oracle | `pytest tests/integration/test_backtest_oracle.py -q` | **3 passed** (134 / `46189.87730727451`, `check_exact=True`) |
| 2. Inertness (WR-02's own proof) | `pytest tests/integration/test_okx_inertness.py -q` | **4 passed** |
| 3. Strict typing | `poetry run mypy itrader` | **Success: no issues found in 282 source files** |
| 4. Full suite | `poetry run pytest tests -q` | **2877 passed, 6 skipped in 40.66s** — exactly baseline |

The 6 skips are the pre-existing OKX-demo-credential-gated tests, unchanged by this batch.

Scope gates: `git diff --stat ebc2a40c HEAD` is **12 files, 37 insertions / 44 deletions**
(deletions-dominant, every file inside `files_modified`, zero files deleted).
`git log --oneline -3` shows exactly three commits in WR-02 / WR-07 / WR-09 order.

## Deviations from Plan

None — no task hit a STOP-and-report condition. Every plan claim about the code held on
inspection: the five named imports were each their file's only occurrence, `VenueBundles.logger`
was genuinely unread, `registry.py` has no runtime imports, and all three `('paper', ...)`
lookup sites were exactly as described.

One mechanical note, not a deviation: my first edit to `backtest_trading_system.py:433` was
rejected because I wrote five tabs where the file has four. Caught by the Edit tool's exact-match
requirement, corrected against `cat -et` output, and both tab files verified byte-level after
editing. No indentation regime changed anywhere — the per-file measurements (venues/ and
`conformance.py` 4-space; `universe_wiring.py` 93 tabs; `backtest_trading_system.py` 465 tabs;
`live_trading_system.py` 694 spaces / 0 tabs) were re-taken before the first edit and re-asserted
by each task's gate.

## Known Stubs

None. No stub, skipped test, or unrun `<verify>` was introduced by this batch.

## Threat Flags

None. No new network endpoint, auth path, file access pattern, or schema change. T-dc4-01 and
T-dc4-02 from the plan's register are both mitigated as designed (key literals collapsed onto the
two constants; the silent `.get` promoted to a fail-loud subscript). T-dc4-03 was accepted with
no action needed — zero dependency change, no `poetry` edit.

## Self-Check: PASSED

- All 12 modified files exist on disk.
- All three commits found in `git log`: `42f87e6e`, `5d977669`, `264c74bc`.
- No file deletions introduced (`git diff --diff-filter=D` empty across the range).
