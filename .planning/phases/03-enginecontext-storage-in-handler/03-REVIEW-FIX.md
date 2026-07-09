---
phase: 03-enginecontext-storage-in-handler
fixed_at: 2026-07-09T00:00:00Z
review_path: .planning/phases/03-enginecontext-storage-in-handler/03-REVIEW.md
iteration: 1
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-07-09
**Source review:** .planning/phases/03-enginecontext-storage-in-handler/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 1 (fix_scope=all — includes INFO)
- Fixed: 1
- Skipped: 0

## Fixed Issues

### IN-01: SQL leaf-store constructors retained `backend` as the parameter name after the class rename

**Files modified:**
- `itrader/order_handler/storage/sql_storage.py`
- `itrader/portfolio_handler/storage/sql_storage.py`
- `itrader/strategy_handler/storage/sql_storage.py`
- `itrader/results/sql_storage.py`
- `itrader/price_handler/store/sql_store.py`
- `itrader/storage/halt_record_store.py`

**Commit:** cd7d200c

**Applied fix:** Completed the D-01 vocabulary sweep by renaming the constructor
parameter `backend: SqlEngine` → `sql_engine: SqlEngine` in all six SQL leaf-store
constructors, and updated every in-body reference to that parameter
(`self.backend = backend` → `self.backend = sql_engine`; `backend.engine`,
`backend.metadata`, `metadata = backend.metadata`, and the
`backend.metadata.create_all(...)` calls → `sql_engine.*`). The `Parameters` docstring
label for each constructor was also updated from `backend:` to `sql_engine:` (and the
`sql_engine.metadata` reference inside those parameter descriptions) for full identifier
consistency.

Scope notes / deliberate non-changes:
- The `self.backend` instance attribute name was retained (used by `dispose()` /
  `stop_engine()` across each store). IN-01 scopes only to the *parameter* identifier,
  not the attribute; the attribute is not a reference to the parameter.
- Top-of-module and class-level prose docstrings describing the pluggable
  "storage-backend" pattern (e.g. `on \`\`backend.metadata\`\`` design prose,
  "shared backend engine", "backend-written seq") were left as-is — these are prose,
  not the renamed parameter, and are explicitly permitted to remain.
- `PortfolioHandler.__init__`'s `sql_engine: Optional[Any]` typing was NOT touched
  (IN-01 flags it as pre-existing deliberate looseness, out of scope).

Verification (this is a behavior-preserving, oracle-gated milestone; a pure identifier
rename must not change behavior):
- Call-site scan: `grep -rn 'backend=' itrader/ tests/` → none. All six constructors are
  invoked positionally, so no keyword-argument call site needed updating.
- Residual-token grep over the six files: no `backend` identifier remains as the
  `SqlEngine` parameter (only the retained `self.backend` attribute and design prose).
- `ast.parse` clean on all six files.
- Backtest oracle byte-exact: `pytest tests/integration/test_backtest_oracle.py` →
  3 passed (134 / 46189.87730727451 preserved).
- OKX import-inertness: `pytest tests/integration/test_okx_inertness.py` → 2 passed
  (no eager sqlalchemy import introduced; the existing `SqlEngine` typing imports were
  left structurally intact).
- `mypy itrader` (strict) → Success: no issues found in 215 source files.
- Indentation: all six files are 4-space (measured per file before editing); exact-string
  edits preserved each file's existing whitespace — no tab/space normalization.

---

_Fixed: 2026-07-09_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
