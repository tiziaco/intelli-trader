# Phase 2: Data Ingestion - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring three additional cryptos (ETHUSD, SOLUSD, AAVEUSD) into the repo in the
golden Binance-kline schema via a committed, re-runnable normalization script —
so multi-ticker scenarios (Phases 3, 9) have real data — **without touching the
run-path loader**. The provider CSVs (split `date`+`time`, lowercase columns)
already exist in `data/` (`ETHUSD_1d.csv`, `SOLUSD_1d.csv`, `AAVEUSD_1d.csv`);
this phase normalizes them into the canonical schema that `CsvPriceStore` reads
unchanged.

**In scope:** the offline normalization script + its inputs/outputs, and the
three committed normalized datasets.
**Out of scope (own phases):** the membership-from-availability primitive
(Phase 3), the E2E harness (Phase 4), any change to `CsvPriceStore` /
`BacktestBarFeed` run-path logic, and any re-baseline of the BTCUSD golden
oracle (v1.1 is behavior-preserving).

</domain>

<decisions>
## Implementation Decisions

### Output Schema Scope
- **D-01:** Normalized CSVs contain **only the 6 real columns the loader reads** —
  `Open time, Open, High, Low, Close, Volume`. Do NOT reproduce the golden BTC
  file's full 12-column Binance-kline header. The provider data has no Close
  time / Quote asset volume / Number of trades / taker volumes / Ignore; the
  loader (`CsvPriceStore._load_csv`) requires exactly those 6 and drops the
  rest, and the Phase-2 success criterion defines "golden schema" as
  `Open time + OHLCV`. Fabricating the trailing columns would inject invented
  numbers into files that become frozen E2E golden fixtures — disallowed.
  Provider `trade_count` is dropped (not mapped to a synthetic "Number of
  trades" column, since the rest of the 12-col schema would still be missing).

### Timestamp Format
- **D-02:** Emit `Open time` in the **byte-exact golden format**
  `YYYY-MM-DD HH:MM:SS.ffffff UTC` (space-separated, 6-digit microseconds,
  literal ` UTC` suffix), matching `data/BTCUSD_1d_ohlcv_2018_2026.csv`. The
  provider's split `date` (`2021-01-01`) + `time` (`00:00:00+00:00`) is joined
  into a single tz-aware UTC instant, then serialized with `strftime`. Rationale:
  functionally any tz-aware string parses identically via the loader's
  `pd.to_datetime(..., utc=True)`, so correctness here is about the *committed
  artifact* — all four datasets should read as one homogeneous golden schema and
  re-run byte-identically.

### File Layout & Naming
- **D-03:** Separate raw inputs from normalized outputs. Move the provider CSVs
  to **`data/raw/`** (preserved as re-runnable script inputs — INGEST-01 demands
  byte-identical re-runs, so inputs must persist; overwrite-in-place is
  disqualified because it destroys the inputs). Write normalized outputs to
  **`data/{TICKER}_1d_ohlcv.csv`** (e.g. `data/ETHUSD_1d_ohlcv.csv`).
- **D-04:** **BTCUSD keeps its existing name** `BTCUSD_1d_ohlcv_2018_2026.csv` —
  it is pinned in `CsvPriceStore.CSV_DEFAULT_PATH` and `scripts/run_backtest.py`
  (D-01 of the oracle). Renaming it would disturb the golden run path. The
  resulting minor naming asymmetry (new files drop the date-range suffix because
  each asset spans a different window) is the correct trade-off vs. touching the
  oracle path. New files omit the date range deliberately.

### Script Ergonomics
- **D-05:** One committed script at **`scripts/normalize_data.py`**, mirroring
  `scripts/run_backtest.py` conventions (module docstring pinning decisions,
  importable, `make` target). It normalizes **all three tickers by default**
  (re-runnable, deterministic), driven by an internal ticker→raw-path registry.
  A `make` target (e.g. `make normalize-data`) invokes it.

### Output Validation
- **D-06:** **Validate and fail loud.** The script verifies each normalized
  frame before writing: monotonic + unique dates, OHLC consistency
  (`low <= open/close <= high`), positive volume, no NaN — and **raises** on any
  violation. This mirrors the codebase's trusted-but-verify philosophy
  (`csv_store._load_csv` raises rather than "silently yielding empty bars, which
  would produce a silently-wrong oracle"). These datasets feed the
  hand-verify-once-then-freeze E2E fixtures, so a malformed bar must never slip
  silently into a frozen fixture. (Validate-and-warn rejected — warnings get
  ignored on re-runs; transform-only rejected — contradicts the stated
  philosophy.)

### Determinism / Byte-Identical Re-Runs (INGEST-01)
- **D-07:** Output must be byte-identical across re-runs. Implication for the
  planner: pin column order, deterministic row order (sorted by `Open time`),
  and a fixed float serialization so volume/price values render identically
  every run. No wall-clock or environment-dependent values in the output.

### Claude's Discretion
- The exact `make` target name, the script's CLI surface beyond the
  all-tickers-by-default behavior, and the precise float-formatting mechanism
  (as long as D-07 byte-identical re-runs hold) are left to planning.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Run-path loader contract (the schema the output MUST match)
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore._load_csv`
  defines the EXACT consumed schema: requires `['Open time','Open','High','Low','Close','Volume']`,
  maps to lowercase `date/open/high/low/close/volume`, builds a tz-aware index
  (`pd.to_datetime(..., utc=True).tz_convert(TIMEZONE)`), then date-window
  slices. **This file is NOT modified in this phase** (INGEST-03). It is the
  acceptance contract: all four CSVs must load through it with no code change.

### Golden schema exemplar
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — the reference for header + `Open time`
  string format (`Open time` = `YYYY-MM-DD HH:MM:SS.ffffff UTC`). Note: BTC
  carries the full 12-column header; per D-01 the new files reproduce only the
  6 the loader reads.

### Provider input format
- `data/ETHUSD_1d.csv`, `data/SOLUSD_1d.csv`, `data/AAVEUSD_1d.csv` — current
  raw provider files (header `time,date,open,high,low,close,volume,trade_count`;
  `time`=`00:00:00+00:00`, `date`=`2021-01-01`). To be moved to `data/raw/`.

### Script conventions
- `scripts/run_backtest.py` — the committed-driver convention to mirror
  (decision-pinning docstring, importable, `make` target).

### Phase / requirements / decisions
- `.planning/ROADMAP.md` §"Phase 2: Data Ingestion" — goal + 3 success criteria.
- `.planning/REQUIREMENTS.md` — INGEST-01, INGEST-02, INGEST-03.
- `.planning/PROJECT.md` Key Decisions — v1.1 locked decision: "normalize new
  data via committed script, not loader logic … `CsvPriceStore` unchanged";
  behavior-preserving (BTCUSD golden oracle not re-baselined).
- `.planning/codebase/FIX-LIST.md` — no Phase-2-eligible cleanup items on this
  path; all price_handler entries (FL-06/07/10/11) are deferred (SQL / live /
  providers), so opportunistic cleanup (CLAR-02) has nothing to touch here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CsvPriceStore._load_csv` (`itrader/price_handler/store/csv_store.py`) — the
  column-validation + tz-index logic. The normalization script targets its
  required header exactly; can be used as the post-normalization acceptance
  check (load each output through `CsvPriceStore` to prove INGEST-03).
- `scripts/run_backtest.py` — committed-driver template (docstring style,
  structure, `make` integration via `Makefile`).
- `itrader/config.TIMEZONE` — the configured tz the loader converts to; the
  script should produce UTC and let the loader convert (don't pre-convert to a
  non-UTC tz in the file).

### Established Patterns
- **Offline-vs-runtime lifecycle** (M5-05): the run path is read-only; ingestion
  is an offline concern. The script lives in `scripts/`, not in `price_handler`.
- **Trusted-but-verify** (`_load_csv` docstring): raise loudly on malformed data
  rather than producing silently-wrong output — D-06 applies this to the script.

### Integration Points
- Output files land in `data/` and are picked up by `CsvPriceStore(csv_paths={...})`
  in later phases (Phase 3 membership, Phase 9 multi-ticker scenarios). This
  phase only produces the files; wiring tickers into a store/universe is Phase 3+.

</code_context>

<specifics>
## Specific Ideas

- All four datasets should be visually homogeneous as committed golden artifacts
  (same header shape, same `Open time` string format) — the driver behind D-02.
- The provider files already exist in `data/`; the conflict resolution (move to
  `data/raw/`, D-03) is the explicit user-confirmed layout.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Membership-from-availability,
mid-run listing / heterogeneous-span handling → Phase 3; E2E consumption of
these datasets → Phases 4/9.)

</deferred>

---

*Phase: 2-Data Ingestion*
*Context gathered: 2026-06-09*
