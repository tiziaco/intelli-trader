---
phase: 02-data-ingestion
plan: 01
subsystem: data
tags: [csv, ohlcv, normalization, golden-data, pandas, decimal-edge, deterministic-serialization]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: CsvPriceStore loader contract (6-column golden schema, tz-aware index construction)
provides:
  - Committed re-runnable normalization script (scripts/normalize_data.py) producing byte-identical output
  - Three normalized golden-schema CSVs in data/ (ETHUSD 1834, SOLUSD 1416, AAVEUSD 1639 bars)
  - Preserved provider inputs under data/raw/ (re-runnable transform sources)
  - make normalize-data target
  - Proof that all four datasets (BTCUSD + 3 new) load through the UNCHANGED CsvPriceStore (INGEST-03)
affects: [multi-ticker scenarios, phase-3, phase-9, golden-fixture-freeze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dependency-light offline driver: hot CSV->CSV transform imports only pathlib + pandas; itrader-importing acceptance check isolated behind --verify flag"
    - "Deterministic serialization pin: fixed column order + rows sorted by Open time + float_format='%.10f' -> sha256-stable re-runs"
    - "Validate-and-RAISE before write (D-06): malformed bars abort rather than enter a frozen golden fixture"

key-files:
  created:
    - data/ETHUSD_1d_ohlcv.csv
    - data/SOLUSD_1d_ohlcv.csv
    - data/AAVEUSD_1d_ohlcv.csv
    - .planning/phases/02-data-ingestion/deferred-items.md
  modified:
    - scripts/normalize_data.py
    - data/raw/ETHUSD_1d.csv (relocated via git mv, Task 1)
    - data/raw/SOLUSD_1d.csv (relocated via git mv, Task 1)
    - data/raw/AAVEUSD_1d.csv (relocated via git mv, Task 1)
    - Makefile (Task 1)

key-decisions:
  - "D-06 volume check relaxed from strictly-positive (>0) to non-negative (>=0), still guarded against NaN/negative (user decision Option 1)"
  - "Zero-volume bars on SOLUSD(11)/AAVEUSD(35) are a provider missing-data sentinel, not true zeros; kept byte-exact because OHLC is real and volume is inert on the v1.1 run path"

patterns-established:
  - "Pattern: dependency-light normalization driver (pathlib+pandas hot path, itrader behind --verify)"
  - "Pattern: deterministic CSV serialization (column order + row sort + %.10f float_format) for sha256-stable golden data"

requirements-completed: [INGEST-01, INGEST-02, INGEST-03]

# Metrics
duration: ~2min (resume session); full plan spanned 2 sessions (Task 1 prior)
completed: 2026-06-09
---

# Phase 2 Plan 01: Data Ingestion Summary

**Committed, re-runnable normalization driver converts three provider crypto CSVs (ETHUSD/SOLUSD/AAVEUSD) into the byte-identical golden 6-column schema that loads through the UNCHANGED CsvPriceStore alongside BTCUSD.**

## Performance

- **Duration:** ~2 min (this resume session); full plan executed across two sessions (Task 1 in a prior session, Tasks 2-3 + decision here)
- **Started (resume):** 2026-06-09T09:45:32Z
- **Completed:** 2026-06-09T09:47:14Z
- **Tasks:** 3 (Task 1 prior; Tasks 2 & 3 this session)
- **Files modified:** 5 created/modified this session (3 CSVs, normalize_data.py, deferred-items.md)

## Accomplishments
- Three normalized golden-schema CSVs generated and committed (ETHUSD 1834 / SOLUSD 1416 / AAVEUSD 1639 bars), row counts preserved end-to-end.
- D-07 byte-identical re-runs proven: sha256 of all three outputs unchanged across two consecutive script runs.
- INGEST-03 proven: all four datasets (BTCUSD golden + the three new) load through CsvPriceStore with `git diff --quiet itrader/price_handler/store/csv_store.py` exit 0 — no run-path loader change, no schema-detection branch.
- D-06 volume validation relaxed to non-negative (still raising on NaN/negative) per the user's Option 1 decision, with accurate provider-sentinel justification documented.

## Task Commits

Each task was committed atomically:

1. **Task 1: Relocate raw inputs + write normalization script + Makefile target** - `460fa12` (feat, prior session)
2. **D-06 decision resolution: relax volume check to non-negative** - `267e59c` (fix, this session)
3. **Task 2: Generate + validate normalized CSVs, prove byte-identical re-runs** - `3eae837` (feat)
4. **Task 3: Prove INGEST-03 — four datasets load through unchanged CsvPriceStore** - verification-only, no tracked source changes (csv_store.py intentionally byte-unchanged)

**Plan metadata:** committed separately with this SUMMARY.

## Files Created/Modified
- `scripts/normalize_data.py` - Relaxed D-06 volume check to non-negative (NaN/negative still raise); accurate justification recorded in docstring (Task 1 created the script).
- `data/ETHUSD_1d_ohlcv.csv` - ETHUSD in golden 6-column schema, 1834 bars.
- `data/SOLUSD_1d_ohlcv.csv` - SOLUSD in golden 6-column schema, 1416 bars (11 zero-volume sentinel bars kept byte-exact).
- `data/AAVEUSD_1d_ohlcv.csv` - AAVEUSD in golden 6-column schema, 1639 bars (35 zero-volume sentinel bars kept byte-exact).
- `.planning/phases/02-data-ingestion/deferred-items.md` - Future-phase caveat on known-unreliable SOL/AAVE volume sentinel dates.

## Decisions Made
- **D-06 volume check → non-negative (Option 1).** The provider data contains zero-volume bars (SOLUSD 11, AAVEUSD 35; ETHUSD 0, BTCUSD golden 0). These are NOT genuine no-trade days: the OHLC on those dates shows real intraday movement (e.g. SOLUSD 2024-08-27 open 157.15 / high 159.69 / low 145.14 / close 146.85, ~9% range) — price cannot move that far with zero trades, so `volume == 0` is a **provider missing-data sentinel**, not a true zero. The OHLC prices are real, internally consistent, and the only field the v1.1 run path consumes (SMA_MACD reads no volume; execution/slippage/fee track only executed-fill `_total_volume`, never input bar volume; sizing/risk read no volume). Relaxing to `>= 0` preserves the real price data and the pinned row counts while keeping volume guarded so genuinely-corrupt bars still raise (NaN or negative volume aborts the run). Rows are NOT dropped and values are NOT imputed — the sentinel rows stay byte-exact (`0.0000000000`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Decision Checkpoint Resolution] Relax D-06 volume validation from strictly-positive to non-negative**
- **Found during:** Task 2 (generation) — the D-06 `volume > 0` check correctly RAISED because provider data contains zero-volume bars (SOLUSD 11, AAVEUSD 35).
- **Resolution path:** Surfaced as a decision checkpoint; user selected **Option 1** (relax to `>= 0`, keep all other D-06 checks strict, keep volume guarded against NaN/negative, do not drop or impute rows).
- **Fix:** Changed the volume assertion to `Volume >= 0` plus an explicit `Volume.isna()` guard; updated the docstring/comment with the accurate provider-missing-data-sentinel justification (the prior "no trades that day" framing was incorrect and was replaced).
- **Files modified:** scripts/normalize_data.py
- **Verification:** validate_frame still raises on OHLC inconsistency, non-monotonic/duplicate dates, NaN, and negative/NaN volume; accepts zero volume. Row counts preserved (1834/1416/1639). Byte-identical re-runs proven.
- **Committed in:** `267e59c`

---

**Total deviations:** 1 (decision-checkpoint resolution, user-approved Option 1)
**Impact on plan:** No scope reduction. All D-01..D-07 realized; the only adjustment is the documented, user-approved D-06 volume relaxation that preserves real price data and the pinned row counts while keeping protection against genuinely-corrupt bars. No placeholder/"v1" behavior.

## Issues Encountered
None beyond the decision checkpoint above (resolved by user as Option 1).

## Known Stubs
None.

## Threat Flags
None — no new security surface. The offline transform reads committed in-repo provider CSVs and writes committed data files; no network, secrets, or run-path involvement. The accepted zero-volume relaxation is tracked as a data-quality caveat in deferred-items.md, not a security threat.

## Future-Phase Caveat (volume on SOL/AAVE sentinel dates)
Volume on the specific SOLUSD (11) and AAVEUSD (35) zero-volume dates is **KNOWN-UNRELIABLE** (provider missing-data sentinel = 0). Any future phase that builds a volume-using scenario on SOL/AAVE must treat these dates as suspect and re-verify the volume against an independent source before freezing — consistent with the hand-verify-once-then-freeze discipline. The OHLC on those dates is trustworthy; only `Volume` is not. Recorded in `.planning/phases/02-data-ingestion/deferred-items.md`.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Multi-ticker golden data ready: ETHUSD, SOLUSD, AAVEUSD committed in the golden schema alongside BTCUSD, all loading through the unchanged CsvPriceStore — ready for Phase 3/9 multi-ticker E2E scenarios.
- Caveat: any volume-dependent scenario on SOL/AAVE must re-verify the flagged sentinel dates first (see deferred-items.md).

## Self-Check: PASSED

All claimed files exist on disk (scripts/normalize_data.py, data/{ETHUSD,SOLUSD,AAVEUSD}_1d_ohlcv.csv, deferred-items.md, 02-01-SUMMARY.md) and all task commits are present in git history (460fa12, 267e59c, 3eae837).

---
*Phase: 02-data-ingestion*
*Completed: 2026-06-09*
