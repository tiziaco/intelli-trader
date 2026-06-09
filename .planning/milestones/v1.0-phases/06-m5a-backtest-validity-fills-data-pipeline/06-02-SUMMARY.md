---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 02
subsystem: price_handler
tags: [price-store, providers, quarantine, csv, mypy-overrides, m5-05]
requires: []
provides:
  - "PriceStore ABC (read_bars/write_bars/has/symbols/index) at itrader/price_handler/store/base.py"
  - "CsvPriceStore — golden-CSV read path with loud typed errors (FR7), multi-symbol capable"
  - "PriceProvider ABC (fetch_ohlcv/get_symbols, offline-only FR6) at itrader/price_handler/providers/base.py"
  - "ingestion.py stub — provider->store contract, NotImplementedError until D-sql"
  - "providers/ + store/ package layout with quarantined CCXT/OANDA/Binance/SQL modules"
affects: [06-03, 06-05]
tech-stack:
  added: []
  patterns:
    - "Seam = ABC + concrete impl + __init__ re-export (PortfolioStateStorage shape)"
    - "Typed loud errors: MalformedDataError/MissingPriceDataError, never silent None"
key-files:
  created:
    - itrader/price_handler/providers/__init__.py
    - itrader/price_handler/providers/base.py
    - itrader/price_handler/store/__init__.py
    - itrader/price_handler/store/base.py
    - itrader/price_handler/store/csv_store.py
    - itrader/price_handler/ingestion.py
    - tests/unit/price/test_csv_store.py
  modified:
    - itrader/price_handler/data_provider.py
    - pyproject.toml
  relocated:
    - "itrader/price_handler/exchange/CCXT.py -> itrader/price_handler/providers/ccxt_provider.py"
    - "itrader/price_handler/exchange/OANDA.py -> itrader/price_handler/providers/oanda_provider.py"
    - "itrader/price_handler/exchange/base.py -> itrader/price_handler/providers/exchange_base.py"
    - "itrader/price_handler/live_streaming/BINANCE_Live.py -> itrader/price_handler/providers/binance_stream.py"
    - "itrader/price_handler/sql_handler.py -> itrader/price_handler/store/sql_store.py"
decisions:
  - "store/base.py (PriceStore ABC) pulled forward into Task 1 so ingestion.py's typed signature keeps make typecheck green at the Task 1 commit boundary (Rule 3)"
  - "CsvPriceStore window bounds are instance attrs defaulting to the pinned class constants — enables the empty-window unit test without touching the oracle defaults"
metrics:
  duration: "~12 min"
  completed: "2026-06-06"
  tasks: 2
  commits: 2
---

# Phase 6 Plan 02: Provider/Store Seams + CsvPriceStore Summary

**One-liner:** M5-05 price-handler split stood up — providers/ and store/ package seams with quarantined CCXT/OANDA/Binance/SQL relocations (pure git mv, R098-R100), a tested CsvPriceStore inheriting the proven `_load_csv_data` logic with FR7 loud typed errors, and the FR6 offline-ingestion stub.

## What Was Built

### Task 1 — Package skeleton + relocations + mypy hygiene (commit `3ee78ed`)
- `git mv` quarantine (D-16/D-21, internals untouched): CCXT/OANDA adapters + legacy `AbstractExchange` into `providers/`, Binance streamer into `providers/binance_stream.py`, `SqlHandler` into `store/sql_store.py`; emptied `exchange/` and `live_streaming/` dirs deleted (intentional deletions: their two empty `__init__.py` files).
- Import-line fixes only: adapters' `from .base import AbstractExchange` -> `.exchange_base`; `data_provider.py` repointed to `.store.sql_store` / `.providers.ccxt_provider` (zero logic change — data_provider stays alive until 06-05).
- `pyproject.toml` mypy overrides repointed in the same commit (Pitfall 7); `providers.exchange_base` added to the D-oanda override set. New store/providers packages carry NO override — strict-clean.
- New seams: `PriceProvider` ABC (offline only, never on run path — FR6), `PriceStore` ABC (read accessors raise `MissingPriceDataError`, never None — FR7), `ingestion.py` stub raising `NotImplementedError` (D-sql).
- `providers/__init__.py` re-exports `PriceProvider` ONLY — quarantined adapters never imported at package level (T-06-06).

### Task 2 — CsvPriceStore + first price unit tests (commit `1408e91`)
- `CsvPriceStore(PriceStore)`: eager multi-symbol load at construction from a `csv_paths` mapping (default `{BTCUSD: golden CSV}`); per-CSV logic inherited from `data_provider._load_csv_data` — Binance-kline header validation (`MalformedDataError`, T-06-04), utc->TIMEZONE tz-aware `'date'` index, float64 columns, D-02 window pinning (`2018-01-01` -> `2026-06-03`), empty-slice raise (`MissingPriceDataError`, T-06-05). Upper-cased symbol keying (legacy parity). No bare `except:` anywhere.
- `write_bars` raises `NotImplementedError` — read-only run path (FR6).
- `store/__init__.py` re-exports `PriceStore` + `CsvPriceStore` with `__all__`; `sql_store` stays out of package-level imports (pulls sqlalchemy).
- `tests/unit/price/test_csv_store.py` (first-ever price_handler unit tests, 6 tests): golden-CSV canonical load, malformed header, empty window slice, unknown ticker raises (read_bars + index), write_bars read-only, two-symbol mapping (06-03 megaframe seed).

## Verification Evidence

| Check | Result |
|-------|--------|
| `make typecheck` | green at both commits (138 -> 139 source files, 0 issues) |
| `tests/unit/price/test_csv_store.py` | 6 passed |
| `tests/integration/test_backtest_smoke.py` | 1 passed |
| `tests/integration/test_backtest_oracle.py` | 2 passed (run path untouched — byte-exact) |
| Full suite `poetry run pytest tests/ -q` | 510 passed |
| `ls exchange/ live_streaming/` | No such file or directory (both) |
| `git log --diff-filter=R -1` | R100/R098 for all five relocated modules |
| pyproject grep | 0 hits for `sql_handler` / `exchange.` override strings; `store.sql_store` present |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] PriceStore ABC created in Task 1 instead of Task 2**
- **Found during:** Task 1
- **Issue:** `ingestion.py`'s typed signature (`store: PriceStore`) references `store/base.py`, which the plan scheduled for Task 2 — Task 1's `make typecheck` gate would fail on the unresolvable name.
- **Fix:** Created `store/base.py` (the exact interfaces-block ABC) in Task 1's commit; Task 2 added the concrete `CsvPriceStore`, the `__init__` re-export, and the tests.
- **Files modified:** itrader/price_handler/store/base.py
- **Commit:** 3ee78ed

**2. [Rule 1 - Bug] Task 1 commit initially missed the adapter import fixes**
- **Found during:** Task 2 pre-commit `git status` check
- **Issue:** The perl import-line edits to `ccxt_provider.py`/`oanda_provider.py` were applied after `git mv` staged the renames, leaving the fixes unstaged — the first Task 1 commit (045259a) contained the renamed files with the broken `from .base import AbstractExchange` line (masked by the D-oanda `ignore_errors` override).
- **Fix:** Amended the Task 1 commit (local branch, unpushed) to include both files; renames preserved as R098.
- **Files modified:** itrader/price_handler/providers/ccxt_provider.py, itrader/price_handler/providers/oanda_provider.py
- **Commit:** 3ee78ed (amended)

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `ingest()` raises NotImplementedError | itrader/price_handler/ingestion.py | Intentional per plan — offline ingestion pipeline deferred to the persistence milestone (D-sql); resolved when D-sql revives ingestion |
| `write_bars()` raises NotImplementedError | itrader/price_handler/store/csv_store.py | Intentional per the interfaces contract — CSV store is read-only on the run path (FR6) |

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface beyond the plan's threat model. Quarantined network/SQL code is package-isolated and never imported at package level (T-06-06 mitigated as planned).

## Next Phase Readiness

- 06-03 (Feed) can build against `PriceStore`/`CsvPriceStore` exactly as specified in the interfaces block; the two-symbol mapping test seeds the megaframe fixture.
- 06-05 (rewiring) has the package layout and `store.index(ticker)` surface ready for the `TimeGenerator.set_dates` repoint; `data_provider.py` remains alive and unchanged in behavior until its deletion there.

## Self-Check: PASSED

All created files exist on disk; commits 3ee78ed and 1408e91 present in git history.
