---
phase: 01-sql-spine-security-hardening
fixed_at: 2026-06-27T19:22:01Z
review_path: .planning/phases/01-sql-spine-security-hardening/01-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-06-27T19:22:01Z
**Source review:** .planning/phases/01-sql-spine-security-hardening/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (6 Warning + 3 Info; `fix_scope: all`)
- Fixed: 9
- Skipped: 0

**Verification gate (per-fix + final):**
- Each fix re-read after edit (Tier 1) + `ast.parse` syntax check (Tier 2) + the relevant `pytest` file.
- Final consolidated gate: `pytest tests/unit/storage tests/unit/results tests/unit/price_handler/test_sql_handler.py tests/integration/storage` -> **33 passed** (Docker was available, so the testcontainers Postgres integration tests ran, not skipped).
- `mypy --strict` over `itrader/`: **Success, no issues found in 173 source files**.
- Tests were run with `PYTHONPATH=<worktree>` against the isolated worktree to defeat the editable-install shadowing (`make test` deliberately NOT used — it exports `ITRADER_DISABLE_LOGS=true`).

## Fixed Issues

### WR-01: `read_prices` hardcoded `"Europe/Paris"` instead of the authoritative `TIMEZONE` constant

**Files modified:** `itrader/price_handler/store/sql_store.py`
**Commit:** 3447b46
**Applied fix:** Added `from itrader.config import TIMEZONE` and replaced `tz_convert("Europe/Paris")` with `tz_convert(TIMEZONE)`, so the SQL store's index timezone tracks the same authoritative source (`Settings.timezone`) as its `CsvPriceStore` sibling instead of diverging on a bare literal.
**Note:** During the edit I discovered this file is actually **4-space indented**, not tab-indented as the CLAUDE.md / task convention note stated. I matched the real (space) indentation; a first attempt that introduced tabs was caught and corrected before commit (would have raised `TabError`). Worth flagging the convention note for `sql_store.py`.

### WR-02: `UtcIsoText.process_bind_param` silently coerces naive datetimes against system local time

**Files modified:** `itrader/storage/types.py`
**Commit:** 26deebd
**Applied fix:** Added a guard that raises `ValueError` when `value.tzinfo is None`, before the `astimezone(timezone.utc)` call — so a naive datetime can no longer be silently shifted against the host's system-local timezone. Confirmed no existing test passes a naive datetime (`tests/unit/storage/test_types.py` only uses aware datetimes + `None`), so the new raise does not break any current caller.

### WR-03: `SqlBackend` exposes no `dispose()` — shared-engine ownership hazard

**Files modified:** `itrader/storage/backend.py`, `itrader/price_handler/store/sql_store.py`, `tests/unit/storage/test_sql_backend.py`
**Commit:** 9365d51
**Applied fix:** Added `SqlBackend.dispose()` (the layer that OWNS the engine owns its teardown) and made `SqlHandler.stop_engine()` delegate to `self.backend.dispose()` instead of calling `dispose()` on the shared engine directly.
**Design note:** `tests/unit/storage/test_sql_backend.py` asserted the backend has **zero** public methods ("pure Engine+MetaData holder, no business logic", D-01). A lifecycle `dispose()` is resource lifecycle, not query/business logic, so it is consistent with D-01's intent; I updated that assertion from `== set()` to `== {"dispose"}` (with an explanatory comment) rather than skip the reviewer-endorsed fix. This is a deliberate, documented relaxation of a design-assertion test, not a workaround to make a broken fix pass.

### WR-04: `ResultsStore.top_runs(metric: str)` is an unconstrained column-name seam (pre-injection contract)

**Files modified:** `itrader/results/base.py`
**Commit:** ecf1a4c
**Applied fix:** Added a module-level `MetricName = Literal["sharpe", "total_return", "max_drawdown", "calmar"]` allow-list and narrowed the ABC signature to `top_runs(self, metric: MetricName, n: int)`, plus updated the docstring. This forces every Phase-2 concrete implementation onto a fixed allow-list so the `ORDER BY`-column-interpolation injection pattern can never be written. Used `Literal` (the review's first option) over a `(str, Enum)` to keep the change minimal; `tests/unit/results/test_results_store_abc.py` still passes (its concrete subclass leaves `metric` unannotated and is not mypy-checked).

### WR-05: `env.py` creates an undisposed engine at import; "never at import" docstring is inaccurate

**Files modified:** `itrader/storage/migrations/env.py`
**Commit:** 4c46f57
**Applied fix:** Replaced `target_metadata = SqlBackend(SqlSettings.default()).metadata` with a bare `target_metadata = MetaData()` (no operational tables are registered yet anyway), added `MetaData` to the `sqlalchemy` import, and removed the now-unused `from itrader.storage.backend import SqlBackend` import. This removes the import-time SQLite engine (and its leaked `SingletonThreadPool`) entirely, so the module is now fully import-inert and the docstring's "DB URL resolved lazily, never at import" claim is accurate. Verified end-to-end by the non-Docker `test_alembic_chain_creates_alembic_version_sqlite` (and the full migration test file, 3 passed).

### WR-06: FL-06 credential grep gate is too narrow to enforce its stated guarantee

**Files modified:** `tests/unit/price_handler/test_sql_handler.py`
**Commit:** 0ff1d62
**Applied fix:** Replaced the literal-substring matchers with structural regexes assembled from fragments:
- credential gate -> `://[^:\s/@]+:[^@\s/]+@` (matches any embedded `scheme://user:password@host`, e.g. `postgres:password@`, `itrader:itrader123@`, not just `user:pass@` / `:1234@`);
- `text()` gate -> `(?<![A-Za-z0-9_])text\(\s*f["']` (catches `text( f"..."` and a line-broken `text(` / `f"...")` that the old whitespace-free check missed).

The scan now runs over whole-file text (so `\s` can span a newline) and only over `itrader/` (this test file lives under `tests/` and is excluded by construction). Added a negative lookbehind so the gate does NOT false-trip on identifiers ending in `text` (e.g. `_operation_context(f"...")`, which exists in `portfolio_handler.py`). Sanity-checked the regexes against known-good and known-bad strings (all expectations met) and confirmed the 7 tests still pass with no false positives on the current clean tree.

### IN-01: `render_as_string(hide_password=False)` surfaces an unmasked credential URL in test code

**Files modified:** `tests/integration/storage/test_migrations.py`
**Commit:** 4492405
**Applied fix:** Added an inline `# SECURITY (IN-01): ...` comment documenting that the plaintext render is safe ONLY because `engine` is the throwaway testcontainers Postgres (a disposable container password), and warning against adapting the pattern to a real/shared/CI credential (prefer `hide_password=True` + passing the live `engine`/connection to Alembic).

### IN-02: `SqlSettings.engine_url` Postgres arm ignores the `driver` member with no scheme validation

**Files modified:** `itrader/config/sql.py`
**Commit:** 26b10e5
**Applied fix:** Documented (docstring + inline comment) that on the Postgres arm `driver` is a **branch selector only**: the returned URL is `Settings.database_url` verbatim, so its scheme/driver is whatever `ITRADER_DATABASE_URL` carries and is NOT reconciled against the enum member. Chose the review's "document" option over adding a scheme assertion, since a hard assertion could reject otherwise-valid operator-supplied URLs (a design decision beyond the review's stated minimal fix).

### IN-03: `from typing import List` deprecated alias in a Python-3.13 module

**Files modified:** `itrader/results/base.py`
**Commit:** dab9220
**Applied fix:** Dropped `List` from the `typing` import and changed the `top_runs` return annotation and its docstring from `List[Any]` to the builtin generic `list[Any]`, matching the project's "modern union/generic syntax preferred" convention. (Committed separately from WR-04, which also touched this file.)

## Skipped Issues

None — all 9 in-scope findings were fixed.

---

_Fixed: 2026-06-27T19:22:01Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
