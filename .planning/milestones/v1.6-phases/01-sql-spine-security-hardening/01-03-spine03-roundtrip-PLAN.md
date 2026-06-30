---
phase: 01-sql-spine-security-hardening
plan: 03
type: execute
wave: 2
depends_on: [01-01, 01-02]
files_modified:
  - tests/integration/storage/test_spine_roundtrip.py
  - itrader/results/__init__.py
  - itrader/results/base.py
  - tests/unit/results/__init__.py
  - tests/unit/results/test_results_store_abc.py
autonomous: true
requirements: [SPINE-02, SPINE-03]

must_haves:
  truths:
    - "A UUIDv7 id round-trips value-equal (uuid.UUID == uuid.UUID) on SQLite AND testcontainers Postgres through the SqlBackend layer (SPINE-03, D-03)"
    - "A business-time timestamp round-trips instant-equal on both dialects, and encodes to identical TEXT bytes across two runs (SPINE-03 lossless + determinism, D-04, D-05)"
    - "The cross-backend round-trip uses a single canonical UUIDv7 scheme (uuid_utils.compat.uuid7), business time only (no wall-clock), and no DB autoincrement (D-03)"
    - "A ResultsStore ABC seam exists, making the four-concern composition shape concrete (the 4th ABC alongside OrderStorage/PortfolioStateStorage/SignalStore) — impl deferred to Phase 2 (SPINE-02)"
  artifacts:
    - path: "tests/integration/storage/test_spine_roundtrip.py"
      provides: "SPINE-03 cross-backend round-trip (sqlite + postgres) + determinism bytes"
      contains: "uuid7"
    - path: "itrader/results/base.py"
      provides: "ResultsStore(ABC) seam — narrow, Phase-2-owned contract"
      contains: "class ResultsStore"
  key_links:
    - from: "tests/integration/storage/test_spine_roundtrip.py"
      to: "itrader.storage.SqlBackend.metadata"
      via: "a _roundtrip Table with Uuid + UtcIsoText columns, written/read on both engines"
      pattern: "UtcIsoText"
    - from: "tests/integration/storage/test_spine_roundtrip.py"
      to: "tests/integration/storage/conftest.py::engine fixture"
      via: "indirect parametrize over ['sqlite','postgres']"
      pattern: "indirect"
---

<objective>
Prove SPINE-03 — the load-bearing verification of the milestone: a UUIDv7 id and a business-time
timestamp written through the SqlBackend layer read back losslessly and EQUAL on both SQLite and
testcontainers Postgres, with identical encoded bytes across runs. Add the `ResultsStore` ABC seam so
the "all four concerns compose the spine" shape (SPINE-02) is concrete (the implementation lands Phase 2).

Purpose: SPINE-03 cross-backend value equality is the single most important correctness proof of Phase 1
(a `run_id` written under SQLite must read equal under Postgres). The ResultsStore ABC makes SPINE-02's
fourth concern real without pre-building Phase 2's `runs`/`run_artifacts` implementation.
Output: `tests/integration/storage/test_spine_roundtrip.py` (sqlite + postgres + determinism) and
`itrader/results/base.py::ResultsStore`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md
@.planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md
@.planning/REQUIREMENTS.md
@itrader/strategy_handler/storage/base.py

<interfaces>
<!-- SPINE-03 round-trip assertion shape (RESEARCH.md Code Examples, lines 565-582) -->
```python
run_id = uc.uuid7()                              # native uuid.UUID, single scheme
bt = datetime(2018, 1, 1, tzinfo=timezone.utc)   # business time, never wall clock
got_id, got_bt = roundtrip(engine, run_id, bt)
assert got_id == run_id    # SPINE-03 value equality (D-03)
assert got_bt == bt        # instant equality (D-04/D-05)
# SAME assertions on SQLite AND testcontainers Postgres (D-10); PG skips when Docker absent (D-11).
```

<!-- Narrow-ABC analog: strategy_handler/storage/base.py::SignalStore (ABC + @abstractmethod, NumPy docstrings, 4-space) -->
<!-- The `engine` fixture (from 01-01 conftest) parametrizes ['sqlite','postgres'] via indirect -->
<!-- UUIDv7 source: from itrader import idgen  OR  import uuid_utils.compat as uc; uc.uuid7() -> native uuid.UUID -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: SPINE-03 cross-backend round-trip test (sqlite + postgres + determinism)</name>
  <files>tests/integration/storage/test_spine_roundtrip.py</files>
  <read_first>
    - tests/integration/storage/conftest.py (from 01-01 — the `engine` fixture parametrizing 'sqlite'/'postgres'; pg_engine skips Docker-absent)
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Code Examples → SPINE-03 cross-backend round-trip test shape" + the determinism nuance note (instant-preserving, UTC-normalized)
    - itrader/storage/types.py + itrader/storage/backend.py (from 01-02 — UtcIsoText, Uuid usage, SqlBackend.metadata)
    - INDENTATION: tests/integration/* = 4 SPACES.
  </read_first>
  <action>
    Create `tests/integration/storage/test_spine_roundtrip.py` (4-space). Define a `_roundtrip` Table on a fresh `MetaData` (or via a SqlBackend) with `Column("run_id", Uuid(as_uuid=True), primary_key=True)` and `Column("business_time", UtcIsoText)`. Parametrize the test over the `engine` fixture (`indirect=True`, params `["sqlite", "postgres"]`) so the SAME assertions run on in-process SQLite AND testcontainers Postgres. In the test: create the table via `metadata.create_all(engine)`, insert a `uuid_utils.compat.uuid7()` `run_id` and `datetime(2018,1,1,tzinfo=timezone.utc)` business time, read back, and assert `got_id == run_id`, `isinstance(got_id, uuid.UUID)`, and `got_bt == bt`. Add a separate `-k determinism` test that calls `UtcIsoText().process_bind_param(...)` (or inserts/reads) twice and asserts the encoded TEXT is byte-identical across the two runs. Use business `time` only (never datetime.now). The postgres parametrization must skip (not fail) when Docker is absent (inherited from the pg_engine fixture, D-11).
  </action>
  <verify>
    <automated>poetry run pytest tests/integration/storage/test_spine_roundtrip.py -k "sqlite or determinism" -x</automated>
  </verify>
  <acceptance_criteria>
    - `pytest tests/integration/storage/test_spine_roundtrip.py -k sqlite -x` passes (id value-equal + business-time instant-equal on SQLite).
    - `pytest tests/integration/storage/test_spine_roundtrip.py -k determinism -x` passes (identical TEXT bytes across two runs).
    - `pytest tests/integration/storage/test_spine_roundtrip.py -k postgres -x` passes when Docker is present, and SKIPS (not errors) when absent (D-11).
    - The test uses `uuid_utils.compat.uuid7()` (single scheme) and a fixed business datetime (no wall-clock); no `Integer primary_key`/autoincrement.
  </acceptance_criteria>
  <done>SPINE-03 round-trip is green on SQLite + determinism, and on Postgres when Docker is available.</done>
</task>

<task type="auto">
  <name>Task 2: ResultsStore ABC seam (SPINE-02 — fourth concern, impl deferred to Phase 2)</name>
  <files>itrader/results/__init__.py, itrader/results/base.py, tests/unit/results/__init__.py, tests/unit/results/test_results_store_abc.py</files>
  <read_first>
    - itrader/strategy_handler/storage/base.py:1-80 (the narrow-ABC analog — class X(ABC) + @abstractmethod + NumPy docstrings; do NOT widen)
    - .planning/REQUIREMENTS.md → RESULT-01/02/03 (the Phase-2 surface the abstract methods are SOURCED from — runs row, run_artifacts frame, top-N cross-run query)
    - .planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md → "itrader/results/base.py — ResultsStore ABC (OPTIONAL)" (mirror SignalStore's narrow shape)
    - INDENTATION: itrader/results/ (NEW) and tests/unit/* = 4 SPACES.
  </read_first>
  <action>
    Create `itrader/results/__init__.py` (re-export `ResultsStore`) and `itrader/results/base.py` (4-space) with `class ResultsStore(ABC)`. Declare four `@abstractmethod`s SOURCED from the already-written RESULT-01/02/03 requirements (do NOT invent a wider surface): `save_run(self, run)` (RESULT-01 summary row), `save_artifact(self, run_id, frame)` (RESULT-02 frame blob), `get_artifact(self, run_id)` (RESULT-02 round-trip read), and `top_runs(self, metric, n)` (RESULT-03 cross-run query). Use forward-referenced / `Any`-typed parameters and a module docstring stating the concrete column/encoding contract (`runs` Float + JSON settings, `run_artifacts` JSON/gzip text) is FINALIZED in Phase 2 — this is only the composition seam (the 4th ABC the spine serves; NO god base). Write `tests/unit/results/test_results_store_abc.py` asserting `ResultsStore` is abstract (cannot instantiate) and that a trivial concrete subclass implementing the four methods can be constructed (proves the seam is a usable composition target).
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/results/test_results_store_abc.py -x && poetry run mypy itrader/results</automated>
  </verify>
  <acceptance_criteria>
    - `ResultsStore` raises `TypeError` on direct instantiation (it is an ABC) and a minimal concrete subclass instantiates.
    - `! grep -rn 'class SqlStorageBase\|ResultsStore(SqlBackend)' itrader/results/` (the ABC composes the spine, it does not inherit it — SPINE-02).
    - The four abstract method names map 1:1 to RESULT-01/02/03 (no invented Phase-2 contract beyond those requirements).
    - `poetry run mypy itrader/results` clean.
  </acceptance_criteria>
  <done>ResultsStore ABC seam exists as the 4th composable concern; abstract-ness + subclassability proven; mypy green.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| persisted value ← business data | UUIDv7 id + business-time written/read across two SQL dialects |
| cross-dialect read | a value written under SQLite must read equal under Postgres |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-07 | Tampering | cross-backend id/timestamp encoding | mitigate | Round-trip asserts value-equality on BOTH SQLite and testcontainers Postgres (D-10); single Uuid type + UtcIsoText, no per-dialect hand-rolled encoding |
| T-01-08 | Repudiation | non-deterministic persistence edge | mitigate | Determinism test asserts identical TEXT bytes across two runs; business `time` only (never datetime.now), explicit UTC isoformat |
| T-01-06 | Tampering | second ID scheme / autoincrement | mitigate | uuid_utils.compat.uuid7() is the sole PK source; no Integer autoincrement in the round-trip table |
</threat_model>

<verification>
- `poetry run pytest tests/integration/storage/test_spine_roundtrip.py -k "sqlite or determinism" -x` green.
- `poetry run pytest tests/integration/storage/test_spine_roundtrip.py -k postgres -x` green when Docker present, skipped when absent.
- `poetry run pytest tests/unit/results -x` green; `poetry run mypy itrader/results` clean.
- GATE-01 (recurring, inert): no per-tick code added — oracle byte-exact 134 / `46189.87730727451`.
</verification>

<success_criteria>
- SPINE-03: UUIDv7 id + business-time round-trip lossless and EQUAL on SQLite and Postgres, deterministic bytes.
- SPINE-02: a ResultsStore ABC seam exists as the fourth composable concern (impl deferred to Phase 2), no god base.
</success_criteria>

<output>
Create `.planning/phases/01-sql-spine-security-hardening/01-03-SUMMARY.md` when done.
</output>
