---
phase: 01-sql-spine-security-hardening
plan: 03
subsystem: database
tags: [sqlalchemy, sqlite, postgres, testcontainers, uuidv7, business-time, abc, spine, roundtrip]

# Dependency graph
requires:
  - phase: 01-01
    provides: "indirect-parametrized sqlite/postgres engine fixture (testcontainers pg_engine) — the cross-backend round-trip substrate consumed here"
  - phase: 01-02
    provides: "itrader/storage spine — SqlBackend + Uuid(as_uuid=True) + UtcIsoText, the encoding layer this plan exercises cross-dialect"
provides:
  - "SPINE-03 proof: a UUIDv7 id + business-time round-trip lossless and value-EQUAL on BOTH in-process SQLite and testcontainers Postgres, with byte-identical encoded TEXT across runs"
  - "itrader/results/ package — ResultsStore(ABC) seam: the spine's fourth composable concern (composes SqlBackend, no god base); concrete impl deferred to Phase 2"
affects: [phase-02-results-store, phase-03-operational-sql-backends, GATE-02]

# Tech tracking
tech-stack:
  added: []  # assembly of already-present SQLAlchemy 2.0.50 + uuid_utils + the 01-02 spine — no new dependency
  patterns: [cross-backend round-trip via the indirect engine fixture, narrow composition-seam ABC (ResultsStore mirrors SignalStore, no god base)]

key-files:
  created:
    - tests/integration/storage/test_spine_roundtrip.py
    - itrader/results/__init__.py
    - itrader/results/base.py
    - tests/unit/results/test_results_store_abc.py
  modified: []

key-decisions:
  - "SPINE-03 round-trip helper builds a fresh MetaData Table (Uuid(as_uuid=True) PK + UtcIsoText) and reads back filtered by run_id — robust on the session-scoped Postgres engine; same value-equality + instant-equality assertions run on both dialects (D-03/D-04/D-05, D-10), PG skips Dockerless (D-11)"
  - "Determinism asserted directly via UtcIsoText().process_bind_param twice (byte-identical UTC isoformat TEXT) — no engine needed, business time only, never datetime.now (T-01-08)"
  - "ResultsStore is a NARROW ABC with exactly four @abstractmethods mapped 1:1 to RESULT-01/02/03 (save_run / save_artifact / get_artifact / top_runs); it composes the SqlBackend, no SqlStorageBase god base (SPINE-02, D-01); concrete columns/encoding finalized Phase 2"
  - "tests/unit/results/__init__.py deliberately NOT created (plan files_modified listed it) — tests/unit/ is package-less under prepend import mode; the colliding storage __init__.py was removed in 30c0f61, so a results one would re-break full-suite collection"

patterns-established:
  - "Cross-backend parity test: parametrize over the indirect engine fixture ['sqlite','postgres'], one _roundtrip helper, identical assertions on both arms — the SPINE-03 template Phase 3 reuses for operational-store round-trips"
  - "Composition-seam ABC: a new storage concern is a narrow class X(ABC) + @abstractmethod sourced 1:1 from its requirements, mirroring SignalStore — never a widened or inherited god base"

requirements-completed: [SPINE-03]  # SPINE-02 ABC-seam half shipped; concrete Sql<Concern>Storage composers land Phases 2-3 — see ## Requirements

# Metrics
duration: 4min
completed: 2026-06-27
---

# Phase 01 Plan 03: SPINE-03 Round-trip + ResultsStore ABC Summary

**Proved SPINE-03 — the milestone's load-bearing correctness check: a UUIDv7 `run_id` and a business-time timestamp written through the SQL-spine layer (`Uuid(as_uuid=True)` + `UtcIsoText`) read back lossless and value-EQUAL on BOTH in-process SQLite and testcontainers Postgres, with byte-identical encoded TEXT across runs — and added the `itrader/results/ResultsStore` ABC as the spine's fourth composable concern (impl deferred to Phase 2), all `mypy --strict` clean and oracle-inert.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-27T17:30:59Z
- **Completed:** 2026-06-27T17:34:42Z
- **Tasks:** 2 (Task 1 test, Task 2 feat)
- **Files modified:** 4 (all created)

## Accomplishments
- Shipped `tests/integration/storage/test_spine_roundtrip.py`: a `_roundtrip` helper writes a `uuid_utils.compat.uuid7()` `run_id` + `datetime(2018,1,1,tzinfo=utc)` business time through a fresh `MetaData` Table (`Uuid(as_uuid=True)` PK — no Integer autoincrement — plus a `UtcIsoText` column) and reads it back filtered by `run_id`. Parametrized over the 01-01 `engine` fixture (`indirect`, `["sqlite","postgres"]`), the SAME `got_id == run_id` / `isinstance(uuid.UUID)` / `got_bt == bt` assertions ran green on in-process SQLite AND on the testcontainers Postgres-16 container (Docker present — the PG arm executed, not skipped).
- Added a determinism test asserting two `UtcIsoText().process_bind_param(...)` binds of the same business datetime produce byte-identical `"2018-01-01T00:00:00+00:00"` TEXT (T-01-08; business time only, never wall-clock).
- Shipped `itrader/results/` (`__init__.py` barrel + `base.py`): `ResultsStore(ABC)` with exactly four `@abstractmethod`s mapped 1:1 to RESULT-01/02/03 (`save_run`, `save_artifact`, `get_artifact`, `top_runs`). It mirrors `SignalStore`'s narrow shape, composes the spine (no `Sql`-god-base, no spine inheritance — grep-verified), and documents that the concrete `runs`/`run_artifacts` columns + encoding are finalized in Phase 2.
- 5 new tests green under `filterwarnings=["error"]` (3 round-trip/determinism + 2 ABC); `mypy --strict` clean over `itrader/results`; full-suite collection clean (1363 tests, no package collision); GATE-01 oracle byte-exact (3 oracle tests, `46189.87730727451`).

## Task Commits

Each task was committed atomically:

1. **Task 1: SPINE-03 cross-backend round-trip + determinism** — `ede2f81` (test)
2. **Task 2: ResultsStore ABC seam (4th composable concern)** — `464ff21` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified
- `tests/integration/storage/test_spine_roundtrip.py` - SPINE-03 cross-backend (sqlite + postgres) round-trip via the indirect `engine` fixture + business-time determinism test; threat coverage T-01-06/07/08
- `itrader/results/base.py` - `ResultsStore(ABC)`: four `@abstractmethod`s (RESULT-01/02/03), composes `SqlBackend`, no god base; concrete contract deferred to Phase 2
- `itrader/results/__init__.py` - barrel re-exporting `ResultsStore`
- `tests/unit/results/test_results_store_abc.py` - asserts `ResultsStore` is abstract (`TypeError`) + a minimal concrete subclass instantiates

## Decisions Made
- **Round-trip helper reads back filtered by `run_id`.** The Postgres `engine` arm delegates to the session-scoped `pg_engine`; selecting `WHERE run_id == run_id` keeps the assertion robust even though the round-trip table persists for the container's lifetime — value equality is asserted on the exact written row, identically on both dialects (D-03/D-04/D-05, D-10). The PG arm skips (not errors) Dockerless (D-11), inherited from the fixture.
- **Determinism asserted at the encoder, not via a second DB write.** Two `process_bind_param` binds of the same aware business datetime yield byte-identical UTC isoformat TEXT — the cheapest, engine-free proof of the no-non-deterministic-persistence guarantee (T-01-08); business `time` only, never `datetime.now`.
- **`ResultsStore` stays narrow — four methods, sourced 1:1 from the written requirements.** `save_run` (RESULT-01 summary row), `save_artifact`/`get_artifact` (RESULT-02 frame blob round-trip), `top_runs` (RESULT-03 cross-run query). No invented Phase-2 surface; parameters are `Any`-typed forward references and the docstrings pin the column/encoding contract to Phase 2. The ABC composes the spine and has no `Sql`-god-base (SPINE-02 / D-01).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Did NOT create `tests/unit/results/__init__.py` despite the plan's `files_modified` listing it**
- **Found during:** Task 2 (results unit-test directory)
- **Issue:** `tests/unit/` directories are package-LESS under pytest's prepend import mode (like `tests/unit/order`, `tests/unit/execution`). Adding an empty `tests/unit/results/__init__.py` would create a top-level `results` test package that breaks full-suite collection — this exact bug with the `storage` test dir was fixed in wave 1 by removing `tests/unit/storage/__init__.py` (commit `30c0f61`). Test basenames are already unique, so no `__init__.py` is needed.
- **Fix:** Skipped the file. `tests/unit/results/test_results_store_abc.py` is collected by basename without an `__init__.py`.
- **Files modified:** none (deliberate omission of the listed file)
- **Verification:** `pytest --collect-only tests` reports 1363 tests with no collection error; the results test runs and passes.
- **Committed in:** `464ff21` (Task 2 commit — the directory ships without an `__init__.py`)

---

**Total deviations:** 1 (1 Rule 3 blocking — a deliberate omission to honor the package-less `tests/unit` convention)
**Impact on plan:** No scope change. The omission is required to keep full-suite collection green; the production package marker `itrader/results/__init__.py` (a real, required package) WAS created. No other change to the four planned files.

## Issues Encountered
None. Docker was available, so the Postgres round-trip arm executed (not skipped); all assertions passed on both dialects on the first run.

## Requirements

**SPINE-03 — COMPLETE.** UUIDv7 ids and business-time timestamps persist and round-trip losslessly through the SQL layer on BOTH SQLite and Postgres — single UUIDv7 scheme, business time (no wall-clock), no second ID scheme / autoincrement, deterministic encoded bytes. The cross-backend parity test asserts value-equality on the testcontainers Postgres substrate (the half 01-02 left Pending), closing the requirement. Marked complete in REQUIREMENTS.md.

**SPINE-02 — Pending (ABC-seam half shipped).** This plan adds the fourth ABC (`ResultsStore`) so the "all four concerns compose the spine" shape is concrete and proves "no cross-concern god base" (grep-verified). But SPINE-02's full body — *each of the four ABCs implemented by exactly one `Sql<Concern>Storage` that composes the `SqlBackend`* — requires the four concrete storage classes that land in Phases 2-3. Left Pending; marking it complete after the seam alone would falsely close a requirement the verifier tracks across phases.

**GATE-02 — Pending (recurring, bound to Phase 1).** This plan's persistence-adjacent code is `mypy --strict` clean and `filterwarnings=["error"]` green, and it delivers the first real DB round-trip on the right substrate (in-process SQLite + testcontainers Postgres). GATE-02 is a recurring milestone-wide gate (restart-rehydration coverage spans Phases 3-4); consistent with 01-01/01-02, it stays Pending until the milestone-wide criteria are met.

## Known Stubs
None that block the plan goal. `ResultsStore`'s four `@abstractmethod` bodies (`...`) are an intentional, documented ABC seam — the concrete `Sql`-backed implementation and its `runs`/`run_artifacts` schema are scoped to Phase 2 (RESULT-01/02/03/04). This is the plan's explicit deliverable (SPINE-02 composition seam, impl deferred), not an unwired stub.

## User Setup Required
None - no external service configuration required. The round-trip defaults to in-process SQLite; the Postgres arm uses an ephemeral testcontainers container when Docker is present and skips cleanly when it is not (D-11).

## Self-Check: PASSED
- FOUND: tests/integration/storage/test_spine_roundtrip.py, itrader/results/__init__.py, itrader/results/base.py, tests/unit/results/test_results_store_abc.py
- ABSENT (by design): tests/unit/results/__init__.py (package-less tests/unit convention, ref 30c0f61)
- FOUND commits: ede2f81 (Task 1 test), 464ff21 (Task 2 feat)
- 5 new tests pass under filterwarnings=["error"] (3 roundtrip/determinism incl. live Postgres arm + 2 ABC); mypy --strict clean over itrader/results
- Full-suite collect-only clean (1363 tests, no package collision); GATE-01 oracle byte-exact (3 oracle tests)
- No tracked-file deletions; working tree clean

## Next Phase Readiness
- SPINE-03 is closed: the spine's encoding is cross-backend value-equal on the real testcontainers Postgres substrate — Phase 2's results store and Phase 3's operational stores can persist `run_id`/business-time with confidence.
- `itrader/results/ResultsStore` is the composition target Phase 2 implements (one `Sql`-backed `ResultsStore` holding a `SqlBackend`, `runs` Float columns + JSON settings, `run_artifacts` JSON/gzip'd-text frame round-trip).
- No blockers. GATE-01 oracle byte-exact; the spine remains structurally inert on the backtest hot path.

---
*Phase: 01-sql-spine-security-hardening*
*Completed: 2026-06-27*
