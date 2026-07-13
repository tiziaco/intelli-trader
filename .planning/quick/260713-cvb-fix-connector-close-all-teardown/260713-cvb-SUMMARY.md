---
phase: quick-260713-cvb
plan: 01
subsystem: connectors
tags: [live-trading, teardown, resilience, WR-02]
status: complete
requirements: [WR-02]
provides:
  - "ConnectorProvider.close_all robust to a single raising disconnect()"
  - "ConnectorProvider bound logger (self.logger)"
key-files:
  created: []
  modified:
    - itrader/connectors/provider.py
    - tests/unit/connectors/test_provider.py
decisions:
  - "Catch Exception (not BaseException) per-connector, mirroring per-symbol isolation in OkxExchange.catch_up_missed_fills"
  - "Bind self.logger (public), NOT self._logger from the review snippet — matches OkxConnector convention"
metrics:
  tasks: 2
  files-modified: 2
  completed: 2026-07-13
---

# Phase quick-260713-cvb Plan 01: Fix ConnectorProvider.close_all Teardown Summary

Hardened `ConnectorProvider.close_all` so a single connector's `disconnect()` raise
can no longer strand the remaining memoized connectors or leak the memo — WR-02 from
`05-REVIEW.md` is closed.

## What Changed

**Task 1 — `itrader/connectors/provider.py` (4-space, unchanged):**
- Added module-level runtime import `from itrader.logger import get_itrader_logger`
  (inertness-safe: already loaded at `itrader` import, not in the inertness `_FORBIDDEN` set).
- `__init__` now binds `self.logger = get_itrader_logger().bind(component="ConnectorProvider")`
  as its last statement (public `self.logger`, matching `OkxConnector` — NOT the review's `self._logger`).
- `close_all` rewritten to `try/finally`: `self._memo.clear()` runs in `finally` (memo always emptied);
  each `connector.disconnect()` is wrapped in its own `try/except Exception` that logs
  `self.logger.error("connector disconnect failed", exc_info=True)` and continues the fan-out.
- `get`, the `ConnectorPlugin` Protocol, the memo key shape, and `connectors/__init__.py` untouched.

**Task 2 — `tests/unit/connectors/test_provider.py`:**
- Added `_RaisingConnector` (counts then raises `RuntimeError` from `disconnect`) and
  `_RaisingConnectorPlugin` doubles near the existing fakes.
- Added `test_close_all_isolates_a_raising_disconnect_and_clears_the_memo`: memoizes the raising
  connector FIRST, then a survivor under "okx"; asserts `close_all()` does not propagate, both
  `disconnect_calls == 1`, and `provider._memo == {}`.
- Four existing tests unchanged; no `__init__.py` added (dir stays package-less).

## Deviations from Plan

None - plan executed exactly as written.

## Verification Gates (actual output)

**Gate 1 — inertness (`tests/integration/test_okx_inertness.py`):** PASS
```
collected 3 items
tests/integration/test_okx_inertness.py ...                              [100%]
============================== 3 passed in 1.75s ===============================
```

**Gate 2 — provider unit tests (`tests/unit/connectors/test_provider.py`):** PASS
```
collected 6 items
tests/unit/connectors/test_provider.py ......                            [100%]
============================== 6 passed in 0.78s ===============================
```
(5 pre-existing tests + 1 new regression test = 6.)

**Gate 3 — mypy --strict on `itrader/connectors/provider.py`:** PASS
```
Success: no issues found in 1 source file
```

## Commits

- `f9fd0c2b` fix(05): isolate each disconnect in ConnectorProvider.close_all (WR-02)
- `5045db99` test(05): assert close_all isolates a raising disconnect and clears memo (WR-02)

## Self-Check: PASSED

- FOUND: itrader/connectors/provider.py (modified)
- FOUND: tests/unit/connectors/test_provider.py (modified)
- FOUND commit: f9fd0c2b
- FOUND commit: 5045db99
- Confirmed: no `__init__.py` in tests/unit/connectors/
