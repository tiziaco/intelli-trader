---
phase: 02-data-ingestion
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - scripts/normalize_data.py
  - Makefile
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-09
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed the offline ingestion driver `scripts/normalize_data.py` and the `normalize-data` Makefile target against the project's INGEST decisions (D-01..D-07) and the run-path consumer `itrader/price_handler/store/csv_store.py`. The transform/validation logic is sound on the *current* committed raw data: timestamp join, sort, format pinning, and the D-06 raise-before-write checks all behave correctly and produce byte-stable output for the existing files (verified empirically — pandas 2.3.3, all OHLCV columns read float64, no source value exceeds 10 decimals, no parse warnings).

No BLOCKER-level correctness, security, or data-loss defects were found. The decision-pinned choices flagged as intentional in the review brief (offline-only, hardcoded registry, raise-on-violation, non-negative volume sentinel, determinism pins, Makefile tabs) were excluded from findings.

However, several genuine robustness/data-integrity gaps remain that weaken the script's guarantee against *future* raw inputs and against partial-write corruption of frozen golden fixtures. These are WARNING-level because they do not misbehave on today's data but defeat the script's own "never silently-wrong" (D-06) and "byte-identical re-runs" (D-07) contracts under realistic input drift.

## Warnings

### WR-01: OHLCV column dtype is not pinned — `%.10f` silently bypassed for integer-typed columns, breaking the D-07 byte-exact format

**File:** `scripts/normalize_data.py:83-92, 190`
**Issue:** `normalize_frame` passes the raw OHLCV columns straight through (`df["open"]`, `df["volume"]`, ...) with whatever dtype `pd.read_csv` inferred. `to_csv(..., float_format="%.10f")` only applies to *float* columns. If a future raw file has an all-integer column (e.g. a `volume` column whose every value is a whole number, or an integer `open` for a high-priced instrument), `read_csv` infers `int64`, `float_format` does not apply, and the cell renders as `12345` instead of the golden `12345.0000000000`. Validation (`>= 0`, `isna`, OHLC comparisons) all still pass on integers, so this produces a non-golden-format output that the loader will still ingest — a silently-wrong format drift that defeats D-07's byte-exact pin and the "drops straight into the frozen golden fixtures" promise. The current three files happen to all be float64, so the defect is latent, not active.
**Fix:** Coerce the OHLCV columns to float before building the output frame, so the float format pin always applies:
```python
out = pd.DataFrame(
    {
        "Open time": timestamp.dt.strftime(OPEN_TIME_FORMAT),
        "Open": df["open"].astype(float),
        "High": df["high"].astype(float),
        "Low": df["low"].astype(float),
        "Close": df["close"].astype(float),
        "Volume": df["volume"].astype(float),
    }
)
```

### WR-02: Non-atomic write can leave a truncated/corrupt golden CSV on interrupted run

**File:** `scripts/normalize_data.py:190`
**Issue:** `out.to_csv(out_path, ...)` writes in place over `OUT_DIR / out_filename`. If the process is interrupted mid-write (Ctrl-C, OOM, disk-full), the destination golden file is left half-written. Because these outputs are intended to "drop straight into the frozen E2E golden fixtures," a truncated file would still parse as a valid CSV with fewer rows and could be committed/frozen without the validation ever running again (validation runs on the in-memory frame *before* the write, line 187, so it cannot catch a write-time truncation). This is a data-integrity hazard for the very artifacts the script exists to produce.
**Fix:** Write to a temporary sibling and atomically replace:
```python
tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
out.to_csv(tmp_path, index=False, float_format=FLOAT_FORMAT)
tmp_path.replace(out_path)  # atomic on same filesystem
return out_path
```

### WR-03: `validate_frame` re-parses the rendered string instead of validating the actual sort key — and NaN/OHLC check ordering produces a misleading error

**File:** `scripts/normalize_data.py:140, 146-162`
**Issue:** Two related gaps in the D-06 validator:
1. Monotonic/unique checks re-parse `out["Open time"]` strings (line 140) rather than checking the timestamp the rows were actually sorted by in `normalize_frame`. This works today, but it means the validator does not independently confirm the sort succeeded against the *source* instants — it only confirms the rendered strings are ordered. If the D-02 format string and the parse ever diverge (e.g. a microsecond field dropped on render), the check would silently agree with the corrupted output. The validator should ideally receive/recompute the canonical timestamp, not round-trip the lossy display string.
2. The OHLC consistency checks (lines 146-151) run *before* the NaN check (line 161). A NaN in `Open`/`High`/`Low`/`Close` makes the comparison `out["Low"] <= open_close_min` evaluate to `False`, so the function raises `"OHLC inconsistency"` for what is actually a NaN/missing-data row. The run still aborts (good — not silently-wrong), but the error message misdirects the operator away from the real cause (missing data) toward a non-existent OHLC ordering problem.
**Fix:** Move the NaN guard to the top of `validate_frame` so missing data is reported as missing data before any comparison:
```python
if out[GOLDEN_COLUMNS].isna().any().any():
    raise ValueError(f"{ticker}: NaN present in one of {GOLDEN_COLUMNS}")
# ... then monotonic/unique, then OHLC, then volume sign checks
```
For (1), consider asserting `len(out) == len(raw)` in `normalize_ticker` (no rows silently dropped by the join/sort) and validating the OHLC `High >= Low` invariant explicitly (see WR-04).

### WR-04: No explicit `High >= Low` (bar-range) check, and no row-count conservation check

**File:** `scripts/normalize_data.py:146-151, 185-187`
**Issue:** The OHLC validation only checks `Low <= min(Open, Close)` and `max(Open, Close) <= High`. It never directly checks `High >= Low`. A corrupt bar with `High < Low` but `Open`/`Close` both equal to a value between them is theoretically possible to construct and would pass both existing checks while being an impossible bar. Additionally, nothing asserts that the output row count equals the input row count — `pd.to_datetime(...)` with a malformed `date`/`time` cell could (under different parse settings) coerce or the join could mis-align, dropping rows without any check catching it. For a frozen golden fixture, silent row loss is exactly the "silently-wrong" outcome D-06 exists to prevent.
**Fix:** Add a bar-range invariant and a conservation check:
```python
# in validate_frame, with the OHLC checks:
if not (out["Low"] <= out["High"]).all():
    raise ValueError(f"{ticker}: OHLC inconsistency — Low > High")

# in normalize_ticker, after normalize_frame:
if len(out) != len(raw):
    raise ValueError(f"{ticker}: row count changed in transform "
                     f"({len(raw)} raw -> {len(out)} normalized)")
```

## Info

### IN-01: `--verify` acceptance check is too weak to catch content/row-count drift

**File:** `scripts/normalize_data.py:208-217`
**Issue:** `verify_loads` only asserts `not frame.empty`. This proves the file *parses* through `CsvPriceStore` but would pass even if rows were dropped, prices corrupted, or the date window mostly empty (one surviving row passes `not empty`). Given the script's purpose is to produce trustworthy frozen fixtures, the verify step provides weak assurance. It also uses span ends of `2026-12-31` while the actual data ends `2026-01-08`, so the window is far wider than the data — harmless but imprecise.
**Fix:** Assert an expected row count (or a minimum) and that the loaded index covers the expected span, e.g. `assert len(frame) >= EXPECTED_MIN_ROWS[ticker]` and check `frame.index.min()/max()` against the known data bounds. Consider printing a sha256 of the output so re-runs can be compared for the D-07 byte-stability claim.

### IN-02: `verify_loads` span registry duplicates ticker keys already in `REGISTRY` and can silently drift

**File:** `scripts/normalize_data.py:203-209`
**Issue:** `spans` is a second per-ticker dict keyed by the same tickers as `REGISTRY`. If a ticker is added to `REGISTRY` but not to `spans`, `verify_loads` raises `KeyError(ticker)` at line 209 only when `--verify` is passed — a latent inconsistency between two hand-maintained literals. Minor, but it is a duplicated source of truth.
**Fix:** Fold the span into the `REGISTRY` value tuple (`ticker -> (raw, out, start, end)`) so there is a single per-ticker record, or derive the span from the loaded frame instead of pinning it separately.

### IN-03: `pd.read_csv(raw_path)` does not pin dtype for the `date`/`time` string columns

**File:** `scripts/normalize_data.py:185`
**Issue:** The timestamp join `df["date"] + " " + df["time"]` (line 81) relies on both columns being inferred as `object`/string. This holds for the current files, but if a future raw `date` column happened to be fully numeric in a way pandas infers as non-string, the `+` would perform numeric addition rather than string concatenation and produce garbage timestamps (or a TypeError). Low likelihood given the `+00:00` offset in `time` forces object dtype, but pinning makes the contract explicit.
**Fix:** Read the join columns as string explicitly: `pd.read_csv(raw_path, dtype={"date": str, "time": str})`.

---

_Reviewed: 2026-06-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
