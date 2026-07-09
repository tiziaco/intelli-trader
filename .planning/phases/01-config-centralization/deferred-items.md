# Phase 01 — Deferred / Out-of-Scope Items

Items discovered during execution that are OUTSIDE the current plan's scope
(pre-existing, in files not owned by the running plan). Logged per the executor
SCOPE BOUNDARY rule — NOT fixed by the discovering plan.

## GATE-01 import-quarantine failure — pre-existing, introduced by plan 01-01

- **Discovered during:** plan 01-04, Task 2 (`poetry run pytest tests/unit`).
- **Failing test:** `tests/unit/storage/test_import_quarantine.py::test_backtest_storage_path_imports_no_sql`
- **Symptom:** `GATE-01 VIOLATION: sqlalchemy imported on the backtest storage path`.
- **Root cause:** `itrader/config/system.py:16` performs a MODULE-LEVEL
  `from itrader.config.sql import SqlSettings`. Because `itrader/__init__.py`
  constructs `SystemConfig.default()` at import, importing anything under
  `itrader` eagerly pulls `config/sql.py` → `from sqlalchemy import URL`
  (`config/sql.py:35`) onto the backtest import graph. This defeats plan 01-01's
  own stated goal ("`SystemConfig.sql` is a `functools.cached_property` … keeping
  `SqlSettings`/Postgres off the import graph").
- **Introduced by:** commit `476df49a` — `feat(01-01): add eager runtime + lazy
  sql + flip extra=forbid on SystemConfig` (Wave 1, already complete). The
  module-level import is an ancestor of plan 01-04; the failure predates this plan.
- **Why NOT fixed here:** `config/system.py` is not in plan 01-04's
  `files_modified` and the defect is unrelated to the CFG-03 constant fold. Per
  the SCOPE BOUNDARY rule the discovering plan does not fix sibling plans' files.
- **Suggested fix (for a follow-up / 01-01 remediation):** move the `SqlSettings`
  import under `if TYPE_CHECKING:` (it is only needed as the `sql` cached_property
  return annotation) and import it lazily inside the property body — restoring the
  01-01 inertness intent. Verify with
  `poetry run pytest tests/unit/storage/test_import_quarantine.py`.
- **Note:** plan 01-04's OWN inertness gate,
  `tests/integration/test_okx_inertness.py`, stays GREEN — the fold introduced no
  new leak. This is a distinct, pre-existing GATE-01 regression.
