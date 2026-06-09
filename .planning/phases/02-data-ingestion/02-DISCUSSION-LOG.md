# Phase 2: Data Ingestion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 2-Data Ingestion
**Areas discussed:** Output schema scope, Timestamp format fidelity, File layout & naming, Script ergonomics & validation

---

## Output Schema Scope

| Option | Description | Selected |
|--------|-------------|----------|
| 6 real columns | Emit only Open time + OHLCV — what the loader consumes; honest (no fabricated columns). | ✓ |
| Full 12-column header | Reproduce literal golden header; would require fabricating Close time / quote-volume / taker columns. | |
| 12 cols, blanks for missing | Header-identical to golden but blank unavailable columns. | |

**User's choice:** 6 real columns
**Notes:** User initially selected this, then asked "what's more correct?" Affirmed: the provider has no Close time / quote-asset-volume / taker volumes; fabricating them would inject invented numbers into files that become frozen E2E golden fixtures. Loader requires exactly the 6 and drops the rest.

---

## Timestamp Format Fidelity

| Option | Description | Selected |
|--------|-------------|----------|
| Byte-exact golden format | `YYYY-MM-DD HH:MM:SS.ffffff UTC` matching BTC; deterministic re-runs. | ✓ |
| ISO-8601 tz-aware | Any pandas-parseable tz-aware string; diverges from golden look. | |

**User's choice:** Byte-exact golden format
**Notes:** Functionally identical to the loader (`pd.to_datetime(..., utc=True)`), so correctness is about the committed artifact — all four datasets read as one homogeneous golden schema and re-run byte-identically.

---

## File Layout & Naming

| Option | Description | Selected |
|--------|-------------|----------|
| `data/raw/` inputs + golden-named outputs | Move provider CSVs to data/raw/, write `data/{TICKER}_1d_ohlcv.csv`. | ✓ |
| Flat in data/, distinct output names | Keep raw files in place; outputs alongside under distinct names. | |
| Overwrite in place | Normalize provider files into themselves; loses raw inputs. | |

**User's choice:** `data/raw/` inputs + `data/{TICKER}_1d_ohlcv.csv` outputs
**Notes:** Real correctness argument — INGEST-01 demands byte-identical re-runs, so raw provider CSVs are pipeline inputs that must persist (overwrite disqualified). BTCUSD keeps its existing name (pinned in CsvPriceStore.CSV_DEFAULT_PATH + run_backtest.py); minor naming asymmetry accepted over disturbing the oracle path.

---

## Script Ergonomics & Validation

| Option | Description | Selected |
|--------|-------------|----------|
| Validate + fail loud | Monotonic/unique dates, OHLC consistency, positive volume, no NaN — raise on violation. | ✓ |
| Validate + warn | Log anomalies but still write output. | |
| Transform only | Trust provider data, no validation. | |

**User's choice:** Validate + fail loud (script at `scripts/normalize_data.py`, all three tickers by default, `make` target — accepted as framed)
**Notes:** Most clearly correct — mirrors `csv_store._load_csv` trusted-but-verify philosophy (raise rather than silently yield bad bars). These datasets feed hand-verify-once-then-freeze E2E fixtures; a malformed bar must never slip silently into a frozen fixture.

## Claude's Discretion

- Exact `make` target name, CLI surface beyond all-tickers-by-default, and the precise float-formatting mechanism (as long as byte-identical re-runs hold).

## Deferred Ideas

None — discussion stayed within phase scope. (Membership-from-availability and heterogeneous-span handling → Phase 3; E2E consumption of these datasets → Phases 4/9.)
