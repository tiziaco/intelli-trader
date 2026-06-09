---
phase: 01-m1-ignition-lock-the-oracle
plan: 02
subsystem: price-handler (offline/csv feed)
tags: [price-handler, csv, offline-feed, backtest, frame-shape, tz, oracle]
requires:
  - "01-01: importable backtest path + package-level TIMEZONE re-export"
provides:
  - "PriceHandler csv/offline feed: __init__ skips SqlHandler + CCXT on the csv path (D-07)"
  - "load_data csv branch loads the golden CSV into self.prices[BTCUSD] in exact CCXT frame shape"
  - "tz-aware DatetimeIndex named 'date' (Europe/Paris) consistent with the ping clock (Pitfall 6)"
  - "Explicit D-02 date window slice (2018-01-01 -> 2026-06-03) on the feed side"
  - "Malformed/empty-CSV path raises loudly (V5 / T-02-01)"
affects:
  - itrader/price_handler/data_provider.py
tech-stack:
  added: []
  patterns:
    - "Reproduce the CCXT _format_data frame shape (lowercase OHLCV + tz-aware index) on an offline read path"
    - "Exchange-selector branch inside the handler that skips SQL/network construction (D-07)"
    - "Trusted-but-verify CSV load: validate header + raise on malformed/empty frame"
key-files:
  created: []
  modified:
    - itrader/price_handler/data_provider.py
decisions:
  - "D-01: dataset = data/BTCUSD_1d_ohlcv_2018_2026.csv (CSV_DEFAULT_PATH constant)"
  - "D-02: date window 2018-01-01 -> 2026-06-03 pinned explicitly on the feed side (slice in _load_csv_data)"
  - "D-07: minimal csv/offline branch INSIDE PriceHandler; skips SqlHandler/CCXT entirely"
  - "Sourced index tz from the package-level TIMEZONE re-export (Plan 01), not the dict config singleton (Rule 1 fix)"
metrics:
  duration: ~10 min
  completed: 2026-06-04
---

# Phase 1 Plan 02: PriceHandler CSV/Offline Feed Summary

Added the minimal `csv`/offline feed branch INSIDE `PriceHandler` (D-07) so the backtest
reads the golden BTCUSD CSV instead of SQL/CCXT — loading `self.prices[BTCUSD]` in the
EXACT lowercase-OHLCV + tz-aware DatetimeIndex shape the CCXT path produces (Pitfall 6),
windowed explicitly to 2018-01-01 -> 2026-06-03 (D-02), while touching zero of
PriceHandler's four consumers and reaching no PostgreSQL/network.

## What Was Built

### Task 1 — csv/offline `__init__` guard (D-07)
- `itrader/price_handler/data_provider.py` `__init__`: added an `is_csv` selector
  (`exchange.lower() == 'csv'`) plus an optional backward-compatible `csv_path` kwarg.
  On the csv path the constructor builds **neither** `SqlHandler()` **nor** a CCXT exchange
  (`self.sql_handler = None`, `self.exchange = None`) and stores `self.csv_path`
  (defaulting to the golden CSV). The non-csv path is unchanged (`_init_exchange` + `SqlHandler()`
  behind the `else`). Added class constants `CSV_DEFAULT_PATH`, `CSV_START_DATE`,
  `CSV_END_DATE`, `CSV_TICKER` (D-01/D-02/D-03). Public signature stays compatible — the four
  existing consumers (DynamicUniverse, StrategiesHandler, ScreenersHandler, StatisticsReporting)
  construct `PriceHandler` unchanged; only the run script/engine opts into `exchange="csv"`.

### Task 2 — `load_data` csv branch reproduces exact CCXT frame shape (M1-07, Pitfall 6)
- `load_data` now short-circuits to `_load_csv_data()` and returns when `is_csv`, never
  calling `sql_handler.get_symbols_SQL()` or `exchange.download_data`.
- `_load_csv_data` reads the golden CSV with pandas, validates the Binance-kline header,
  maps `Open time -> date` and `Open/High/Low/Close/Volume -> lowercase` (dropping the trailing
  Binance-kline columns), parses `'YYYY-MM-DD HH:MM:SS.ffffff UTC'` to a tz-aware index
  (`utc=True`), `tz_convert(TIMEZONE)` (Europe/Paris), names the index `date`, `astype(float)`,
  then slices the explicit D-02 window. Stores into `self.prices['BTCUSD']`.
- V5 / T-02-01: a missing-column header **or** an empty post-slice frame raises `ValueError`
  loudly instead of silently yielding empty bars.

## Verification Results

- `poetry run python -c "from itrader.price_handler.data_provider import PriceHandler"` — exits 0
- csv-mode init: `sql_handler is None` and `exchange is None` (no PostgreSQL/CCXT construction) — verified
- Loaded frame: `columns == ['open','high','low','close','volume']`, index name `date`,
  tz-aware (`Europe/Paris`), **3076 bars**, dtype `float64` — verified
- `get_bar('BTCUSD', <index ts>)` returns a non-null bar (tz lookup matches) — verified
- Malformed-header CSV raises `ValueError` (V5) — verified
- Plan automated checks: Task 1 import exits 0; Task 2 `len(df) >= 3000` -> `csv ok 3076` — PASS
- `poetry run pytest test/ --ignore=test/test_smoke -q` — **274 passed** (no legacy regression)
- `grep -Pc "^\t" data_provider.py` = 333 tab-indented lines; edited regions use tabs — verified

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `config.TIMEZONE` (dict singleton) raises AttributeError; sourced TIMEZONE from the package re-export instead**
- **Found during:** Task 2 (first frame-shape verification run)
- **Issue:** The plan's `<interfaces>` referenced `config.TIMEZONE` (as CCXT._format_data does via
  `from itrader import config`). In this codebase `from itrader import config` is a **dict** singleton
  with no `TIMEZONE` attribute — `config.TIMEZONE` raised `AttributeError`. (The existing CCXT path
  shares this latent defect; its real fix is the M2-06 config collapse, out of scope here.)
- **Fix:** Imported the package-level `TIMEZONE` constant that Plan 01 re-exported
  (`from itrader.config import TIMEZONE`, = `'Europe/Paris'`) and used it for both the index
  `tz_convert` and the D-02 slice bounds. This is the same value CCXT intends, and because the ping
  clock is derived from this same frame index, the index tz IS the ping tz by construction (Pitfall 6).
- **Files modified:** itrader/price_handler/data_provider.py
- **Commit:** 49c88a1

## Threat Model Compliance

- T-02-01 (Tampering — malformed/regenerated CSV): mitigated. Header validated; malformed header
  and empty post-slice frame both raise `ValueError`; D-02 window pinned explicitly in code.
- T-02-02 (Info Disclosure / DoS — Postgres/network reach on the offline path): mitigated.
  csv `__init__` sets `sql_handler=None`/`exchange=None`; `load_data` returns before any
  `sql_handler`/`exchange.download_data` call (source-asserted).
- T-02-03 (Spoofing — tz mismatch -> empty bars -> silent zero trades): mitigated. Single tz
  (`TIMEZONE`) sourced from the same frame as the ping clock; `get_bar` lookup verified against an
  index timestamp.
- T-02-SC: accept — no package installs (pandas already present).

## Known Stubs

None. The csv branch loads real bars (3076) from the committed golden CSV.

## Notes for Next Plan

- Plan 03 adds the fraction-of-cash sizing seam in `OrderManager._create_primary_order`, the
  `record_metrics` per-Portfolio fix in `backtest_trading_system.py`, and the SMA_MACD
  `.iloc[-1]`/`fillna=False` fix — together turning the RED smoke test (Plan 01) green.
- End-to-end bar load (>=1 trade implies bars loaded with matching tz) is verified by the smoke
  test once Plan 03 lands; this plan verified the feed in isolation (3076 bars, exact shape).
- The engine passes `exchange="csv"` into `PriceHandler` via `TradingSystem.__init__`; no consumer
  change was needed (csv_path defaults to the golden CSV).

## Self-Check: PASSED
- FOUND: itrader/price_handler/data_provider.py (modified)
- FOUND commit: 8b90586 (Task 1 — csv/offline __init__ guard)
- FOUND commit: 49c88a1 (Task 2 — load_data csv branch)
