# Phase 2: Data Ingestion - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 5 created/modified (1 script, 3 generated CSVs, 1 Makefile) + 3 file moves
**Analogs found:** 5 / 5 (every file has a concrete in-repo analog)

This phase is **not** a handler/component phase. There is exactly one code file
(`scripts/normalize_data.py`); the rest are generated data artifacts, file moves,
and a Makefile edit. The pattern work is therefore concentrated on: (a) mirroring
the committed-driver convention from `scripts/run_backtest.py`, (b) matching the
**exact** output schema the loader contract demands, and (c) the Makefile target
style. There is no "auth / CRUD / error-middleware" surface here.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/normalize_data.py` | script (offline driver) | transform / file-I/O (CSV→CSV) | `scripts/run_backtest.py` | role-match (committed driver) + contract-match (`csv_store._load_csv`) |
| `data/ETHUSD_1d_ohlcv.csv` | generated data artifact | file-I/O (output) | `data/BTCUSD_1d_ohlcv_2018_2026.csv` (header/format exemplar) | schema-match (6-col subset, D-01) |
| `data/SOLUSD_1d_ohlcv.csv` | generated data artifact | file-I/O (output) | `data/BTCUSD_1d_ohlcv_2018_2026.csv` | schema-match (6-col subset, D-01) |
| `data/AAVEUSD_1d_ohlcv.csv` | generated data artifact | file-I/O (output) | `data/BTCUSD_1d_ohlcv_2018_2026.csv` | schema-match (6-col subset, D-01) |
| `Makefile` (add target) | config (task runner) | n/a | `Makefile` `backtest:` target | exact (same file, same idiom) |
| MOVE `data/{ETH,SOL,AAVE}USD_1d.csv` → `data/raw/` | input relocation | file-I/O (move) | n/a (`data/raw/` does not exist yet — create it) | n/a |

**No analog needed for the file moves** — they are `git mv` operations into a new
`data/raw/` directory (D-03). Flag: `data/raw/` does **not** currently exist; the
plan must create it.

## Pattern Assignments

### `scripts/normalize_data.py` (script, transform / file-I/O)

Two analogs apply jointly: `scripts/run_backtest.py` supplies the **driver shape**,
and `csv_store.py::CsvPriceStore._load_csv` supplies the **output contract** (the
exact target this script must produce, and ideally the acceptance check it runs).

#### Analog A — committed-driver shape: `scripts/run_backtest.py`

**Decision-pinning module docstring** (`scripts/run_backtest.py` lines 1-26):
```python
#!/usr/bin/env python
"""Reproducible oracle generator for the SMA_MACD backtest (M1-07).

This committed driver pins every oracle-defining decision so a run is bit-reproducible:

  * D-01  dataset  : data/BTCUSD_1d_ohlcv_2018_2026.csv (the golden CSV feed)
  * D-02  window   : 2018-01-01 -> 2026-06-03 (pinned explicitly below)
  ...

Run via ``make backtest`` or ``poetry run python scripts/run_backtest.py``.
"""
```
Copy this docstring style verbatim: shebang, one-line summary, a `* D-NN  topic :`
decision-pin block (here: D-01..D-07 from `02-CONTEXT.md`), and a closing
`Run via ``make normalize-data`` ...` line.

**Pinned-configuration constants block** (`scripts/run_backtest.py` lines 53-67):
```python
# --- Pinned oracle configuration -------------------------------------------

DATASET = "data/BTCUSD_1d_ohlcv_2018_2026.csv"  # D-01
START_DATE = "2018-01-01"                        # D-02
...
FLOAT_FORMAT = "%.10f"                            # pinned repr for cross-platform stability (T-04-01)
```
Mirror this with a module-level **ticker→raw-path registry** (D-05: "internal
ticker→raw-path registry", all-tickers-by-default). Example shape:
```python
# --- Pinned normalization configuration ------------------------------------
RAW_DIR = pathlib.Path("data/raw")        # D-03 (inputs preserved here)
OUT_DIR = pathlib.Path("data")            # D-03 (normalized outputs)
REGISTRY = {                              # D-05 (all-tickers-by-default driver)
    "ETHUSD":  ("ETHUSD_1d.csv",  "ETHUSD_1d_ohlcv.csv"),
    "SOLUSD":  ("SOLUSD_1d.csv",  "SOLUSD_1d_ohlcv.csv"),
    "AAVEUSD": ("AAVEUSD_1d.csv", "AAVEUSD_1d_ohlcv.csv"),
}
```

**Imports — dependency-light vs `itrader` side effects.** `run_backtest.py` imports
heavy `itrader` modules (lines 33-50) because it boots the engine. **This script
should NOT.** `itrader/__init__.py` runs process-wide singleton init on import
(`config = SystemConfig.default()`, structlog `logger`, `idgen`). A pure CSV→CSV
transform needs none of that. Recommended imports: only `pathlib` + `pandas`.
- **D-02 does not require `config.TIMEZONE`:** the output `Open time` is emitted in
  **UTC** (literal ` UTC` suffix), and the loader itself does
  `pd.to_datetime(..., utc=True).tz_convert(TIMEZONE)` (see contract below). So the
  script produces UTC and lets the loader convert — it must NOT import
  `config.TIMEZONE` or pre-convert to a non-UTC zone (CONTEXT "Reusable Assets":
  *"produce UTC and let the loader convert"*). Staying dependency-light also keeps
  the script importable without firing the `itrader` import side effects.

**`main()` + `if __name__ == "__main__"` structure** (`scripts/run_backtest.py`
lines 154, 213-214): keep the same `def main(): ... if __name__ == "__main__": main()`
shape so the script is importable (D-05 "importable").

**Serialization with a pinned float format** (`scripts/run_backtest.py` lines 197-202):
```python
trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS].to_csv(
    OUTPUT_DIR / "trades.csv", index=False, float_format=FLOAT_FORMAT)
```
This is the in-repo precedent for D-07 byte-identical output: `df.to_csv(...,
index=False, float_format=<pinned>)`. The pinned `FLOAT_FORMAT = "%.10f"` already
exists in this repo (line 63, "pinned repr for cross-platform stability") — reuse
the **same `%.10f`** so all committed CSVs share one float convention.
- **Caveat (precision drift):** the BTC golden CSV and the provider CSVs carry
  *raw variable-precision* floats (e.g. BTC volume `8609.915844`, ETH volume
  `4354.69346`). `%.10f` will re-render these as fixed 10-decimal strings
  (`8609.9158440000`), which is fine for new files (they are fresh artifacts, never
  byte-compared to BTC), and is the determinism-safe choice for D-07. The plan owns
  the final mechanism (CONTEXT "Claude's Discretion") but `%.10f` is the established
  precedent and satisfies byte-identical re-runs. Do **not** rely on pandas' default
  float repr — it is the non-deterministic path D-07 forbids.

#### Analog B — output contract (the acceptance target): `csv_store.py::_load_csv`

The script's output MUST load through this unchanged (INGEST-03). Treat these as
hard assertions on the produced frame.

**Exact required header** (`csv_store.py` lines 154-166):
```python
expected_cols = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']
raw = pd.read_csv(csv_path)
missing = [col for col in expected_cols if col not in raw.columns]
if missing:
    raise MalformedDataError(str(csv_path), f"missing columns {missing}")

data = raw[expected_cols].copy()
data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
```
→ **Output header is exactly** `Open time,Open,High,Low,Close,Volume` (capitalized,
this order). D-01: emit ONLY these 6 — do **not** reproduce BTC's trailing
`Close time, Quote asset volume, Number of trades, Taker buy ..., Ignore`. The
loader drops them anyway, and fabricating them would inject invented numbers into a
frozen fixture (CONTEXT D-01). Provider `trade_count` is dropped.

**tz-index construction the output must be parseable by** (`csv_store.py` lines
170-172):
```python
data = data.set_index('date')
data.index = pd.to_datetime(data.index, utc=True)
data.index = data.index.tz_convert(TIMEZONE)
```
→ The `Open time` strings must parse under `pd.to_datetime(..., utc=True)`. The
golden format `YYYY-MM-DD HH:MM:SS.ffffff UTC` (D-02) does. Produce it from the
provider's split `date` + `time`:
```python
# join provider 'date' (2021-01-01) + 'time' (00:00:00+00:00) -> tz-aware UTC instant
ts = pd.to_datetime(df["date"] + " " + df["time"], utc=True)
open_time = ts.dt.strftime("%Y-%m-%d %H:%M:%S.%f UTC")   # D-02 byte-exact
```
Golden exemplar value (from `data/BTCUSD_1d_ohlcv_2018_2026.csv` row 2):
`2018-01-01 00:00:00.000000 UTC` — space-separated, 6-digit microseconds, literal
` UTC` suffix. `%f` yields the 6 digits; do not zero-pad differently.

**Loud-raise validation philosophy** (`csv_store.py` lines 1-12, 157-160, 183-187):
the loader raises `MalformedDataError` on a bad header and `MissingPriceDataError`
on an empty slice rather than yielding silently-wrong bars. **Mirror this in the
script's D-06 validation** — raise, never warn. Concrete checks to implement
(from CONTEXT D-06):
```python
# monotonic + unique dates; OHLC consistency; positive volume; no NaN — raise on any.
assert ts.is_monotonic_increasing and ts.is_unique, "..."
assert (df["low"] <= df[["open","close"]].min(axis=1)).all(), "..."
assert (df[["open","close"]].max(axis=1) <= df["high"]).all(), "..."
assert (df["volume"] > 0).all() and not df[cols].isna().any().any(), "..."
```
The codebase raises **typed** domain exceptions, not bare `assert`/`Exception`
(CONLUSION from `core/exceptions/`); however this offline script is dependency-light
(no `itrader` import), so a plain `raise ValueError(...)`/`AssertionError` at the
script edge is acceptable here. The plan should pick one and be consistent.

**Optional but recommended acceptance check** (CONTEXT "Reusable Assets"): after
writing each output, load it back through `CsvPriceStore(csv_paths={ticker: path},
start_date=..., end_date=...)` to prove INGEST-03 end-to-end. NOTE: doing this
*does* import `itrader` and fires the singleton side effects — keep it out of the
hot transform path, e.g. behind a `--verify` flag or a separate function, so the
core normalization stays dependency-light.

**Determinism (D-07) — concrete pins:**
1. Column order fixed: `['Open time','Open','High','Low','Close','Volume']`.
2. Row order: sort by the parsed `Open time` ascending before write (`df.sort_values`).
3. `to_csv(..., index=False, float_format="%.10f")` — fixed float repr.
4. No wall-clock / env-dependent values written (the script reads only the raw CSVs).

---

### `data/{ETHUSD,SOLUSD,AAVEUSD}_1d_ohlcv.csv` (generated artifacts, file-I/O output)

**Analog:** `data/BTCUSD_1d_ohlcv_2018_2026.csv` (header/format exemplar only).

These are **outputs of the script above**, not hand-authored. Their shape is fully
determined by the contract in Analog B:
- Header (D-01, 6-col subset): `Open time,Open,High,Low,Close,Volume`
- `Open time` cell format (D-02): `2021-01-01 00:00:00.000000 UTC`
- Float cells: pinned `%.10f` (D-07)
- Naming (D-03/D-04): `data/{TICKER}_1d_ohlcv.csv` (no date-range suffix — that
  suffix is unique to the pinned BTC golden name and is intentionally dropped here).

No separate pattern extraction — the producing script is the single source.

---

### `Makefile` (add `normalize-data` target)

**Analog:** the `backtest:` target in the existing `Makefile`.

**Existing target style to copy:**
```makefile
# Generate the deterministic backtest oracle (output/{trades,equity}.csv + summary.json)
backtest:
	@echo "🚀 Running backtest oracle generator..."
	poetry run python scripts/run_backtest.py
```
**New target (mirror exactly):** a comment line, `@echo "..."`, then
`poetry run python scripts/normalize_data.py`. Also add `normalize-data` to the
`.PHONY:` line (line 6 lists the phony targets — append it there). Use a **tab** for
the recipe body (Makefile requirement). The exact target name is Claude's discretion
(CONTEXT) — `normalize-data` is the suggested name from D-05.

---

## Shared Patterns

### Committed-driver convention
**Source:** `scripts/run_backtest.py` (lines 1-26, 53-67, 154, 213-214) + `Makefile` `backtest:`
**Apply to:** `scripts/normalize_data.py` + the new Makefile target
Decision-pinning module docstring → pinned-config constants block → `main()` →
`if __name__ == "__main__"` → `make` target. This is the one repeated convention in
the phase.

### Trusted-but-verify (raise loud, never silently-wrong)
**Source:** `itrader/price_handler/store/csv_store.py` (docstring lines 1-12; raises lines 157-160, 183-187)
**Apply to:** the D-06 validation block in `normalize_data.py`
Validate the frame (monotonic+unique dates, OHLC consistency, positive volume, no
NaN) and **raise** on any violation, mirroring `_load_csv`. Warn-and-continue is
explicitly rejected (CONTEXT D-06) because these feed frozen E2E fixtures.

### Deterministic serialization
**Source:** `scripts/run_backtest.py` line 63 (`FLOAT_FORMAT = "%.10f"`) + lines 197-202 (`to_csv(..., index=False, float_format=...)`)
**Apply to:** every `to_csv` write in `normalize_data.py`
Pinned float format + fixed column order + sorted rows + `index=False` → D-07
byte-identical re-runs. `%.10f` is the established repo pin.

### Dependency-light offline script (avoid `itrader` import side effects)
**Source:** `itrader/__init__.py` (singleton init on import) — by avoidance
**Apply to:** `scripts/normalize_data.py` core path
Importing `itrader` fires `config`/`logger`/`idgen` singleton construction. A pure
CSV→CSV transform must stay on `pathlib` + `pandas` only. Emit UTC and let the
loader's `tz_convert(TIMEZONE)` handle the zone — do NOT import `config.TIMEZONE`.
Any `CsvPriceStore`-based acceptance check (which does import `itrader`) goes behind
a flag / separate function, off the hot path.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `data/raw/` (new directory) | input store | n/a | No `data/raw/` exists today; the plan must create it and `git mv` the three provider CSVs into it (D-03). No code analog — it is a directory + move. |

Everything else has a concrete in-repo analog. There is **no** controller, service,
model, middleware, hook, store-class, or test file created this phase, so the
role-specific pattern categories (auth, CRUD, request-response) do not apply.

## Metadata

**Analog search scope:** `scripts/`, `itrader/price_handler/store/`, `itrader/config/`, `Makefile`, `data/`
**Files scanned:** `scripts/run_backtest.py`, `itrader/price_handler/store/csv_store.py`, `Makefile`, `itrader/config/__init__.py`, `data/BTCUSD_1d_ohlcv_2018_2026.csv` (header), `data/{ETH,SOL,AAVE}USD_1d.csv` (headers)
**Pattern extraction date:** 2026-06-09
