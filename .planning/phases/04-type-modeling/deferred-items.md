# Phase 04 — Deferred / Out-of-Scope Items

Items discovered during execution that are NOT caused by the current plan's changes and
are therefore out of scope (per the executor scope boundary).

## Plan 04-02

- **`tests/unit/portfolio/test_position_manager.py` collection error (pre-existing).**
  The test imports `PositionEvent` from `itrader.portfolio_handler.position.position_manager`,
  but that enum lives in `itrader/core/enums/portfolio.py` (re-exported via `core/enums`).
  The stale import raises `ImportError` at collection time. This file was last touched in an
  earlier phase (commits `bac1fab`/`54396db`), NOT by Plan 04-02, and reproduces on the
  04-02 base commit (`a18cc75`). Left untouched — fix is a one-line import correction in a
  later naming/encapsulation or hygiene pass.
