# Phase 1: M1 — Ignition + Lock the Oracle - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-04
**Phase:** 1-m1-ignition-lock-the-oracle
**Areas discussed:** Golden run config, CSV data feed, Minimal sizing rule, Oracle capture & test, Test-skeleton scope

---

## Golden Run Configuration

### Strategy parameters
| Option | Description | Selected |
|--------|-------------|----------|
| Use code defaults | short=50, long=100, FAST=6, SLOW=12, WIN=3 (already in `__init__`) | ✓ |
| I'll specify values | User pins exact param set | |

**User's choice:** Use code defaults.

### Starting cash & fees
| Option | Description | Selected |
|--------|-------------|----------|
| Zero fees, $10k cash | Cleanest oracle; fee/slippage correctness is M5 | ✓ |
| Config defaults | Bakes the M5-flagged-buggy fee model into the M1 oracle | |
| I'll specify | User gives exact values | |

**User's choice:** Zero fees, $10k cash.

### Run entrypoint & date span
| Option | Description | Selected |
|--------|-------------|----------|
| Committed script, full CSV | `make backtest` over the entire file | |
| Script, fixed date window | `make backtest` + explicit pinned start/end | ✓ |
| Reuse the notebook | Not CI-reproducible | |

**User's choice:** Committed script + `make backtest`, fixed date window.

### Date window / dataset
| Option | Description | Selected |
|--------|-------------|----------|
| Full available range (orig CSV) | 2025-05-01 → 2026-06-03 (398 rows) | |
| I'll specify the window | — | |
| Flag as a data problem first | filename/content mismatch as blocker | |
| **(User-provided)** new dataset | `data/BTCUSD_1d_ohlcv_2018_2026.csv` | ✓ |

**User's choice:** Provided a better dataset — `data/BTCUSD_1d_ohlcv_2018_2026.csv` (Binance-klines, 3076 daily bars, 2018-01-01 → 2026-06-03). Then chose **full range** on it.
**Notes:** Discovered the original `…01_01_2021-04_06_2026.csv` only contained 398 rows / 13 months despite its filename; the new file is comma-delimited ascending Binance-klines and supersedes the filename used across the planning docs.

---

## CSV Data Feed

| Option | Description | Selected |
|--------|-------------|----------|
| Option 1 — CSV branch in PriceHandler | Minimal offline branch reads file → `self.prices`, skips SqlHandler/CCXT; zero consumer rewiring | ✓ |
| Option 2 — separate CSVDataProvider | Standalone provider; rewire 4 consumers; pre-judges M5 design | |
| Option 3 — load directly in run script | Bypass `load_data()`; throwaway hack | |

**User's choice:** Option 1 (CSV branch in PriceHandler).
**Notes:** User asked whether starting with Option 2 and improving later was "too risky." Clarified it's not risky for the oracle (golden-master discipline protects reworking the data layer; M5 owns the real Provider/Store/Feed split), but Option 2 costs more M1 work because `PriceHandler` feeds 4 components and a standalone provider would pre-judge the M5 abstraction. User accepted Option 1 as minimal + least throwaway.

---

## Minimal Sizing Rule

### Rule
| Option | Description | Selected |
|--------|-------------|----------|
| Fraction of available cash | qty = fraction × cash / price; ~95% per entry | ✓ |
| Fixed notional per trade | qty = fixed $ / price | |
| 100% all-in | risks overshooting cash check | |
| I'll specify | — | |

**User's choice:** Fraction of available cash (95%).

### Seam point
| Option | Description | Selected |
|--------|-------------|----------|
| OrderManager (on_signal path) | Compute qty where it reads signal_event.quantity | ✓ |
| A risk_manager component | More wiring; M5 finishes RiskManager.check_cash anyway | |
| You decide | — | |

**User's choice:** OrderManager (on_signal path).

---

## Oracle Capture & Test

### Format & location
| Option | Description | Selected |
|--------|-------------|----------|
| CSV trade log + equity curve, JSON summary, in test/golden/ | diffable curves + structured metrics | ✓ (format) |
| All-JSON in test/golden/ | large arrays diff poorly | |
| All-CSV in test/golden/ | nested metrics awkward | |

**User's choice:** Format = CSV trade log + equity curve + JSON summary. **Location adjusted by user:** fresh output to `output/` (gitignored); committed oracle to `test/golden/`.
**Notes:** User initially wanted "everything in `output/` + gitignore it"; clarified the M1-08/M1-10 requirement that the oracle be *committed* and the integration test diff a *committed* golden file. Resolved into a two-artifact split (transient `output/` vs frozen `test/golden/`).

### Determinism
| Option | Description | Selected |
|--------|-------------|----------|
| Capture only deterministic fields | Exclude wall-clock timestamps + ID values; no code change | ✓ |
| Pull M2 determinism forward | Inject clock/seed now; rework risk | |

**User's choice:** Capture only deterministic fields.
**Notes:** User asked "do I really need these fields to be deterministic?" Clarified: no — a "deterministic oracle" means the *captured* fields are reproducible, not every field. The trade-defining fields are already deterministic (fixed CSV + params + sizing; SMA_MACD has no RNG); volatile metadata (wall-clock timestamps, integer ID values) is simply not recorded, so the oracle survives the M2 clock/UUIDv7 switch.

### Assertion strictness
| Option | Description | Selected |
|--------|-------------|----------|
| Behavioral exact, numerical exact (re-baseline at M2/M5) | Strictest drift guard; re-freeze only at sanctioned boundaries | ✓ |
| Behavioral exact, numerical with tolerance | Masks real regressions (M1 is bit-reproducible) | |

**User's choice:** Behavioral exact, numerical exact (re-baseline at M2/M5).

---

## Test-Skeleton Scope

### Marker application
| Option | Description | Selected |
|--------|-------------|----------|
| Auto-apply by path in root conftest | `pytest_collection_modifyitems` maps dir→marker; zero edits to 30 legacy files | ✓ |
| Manual marks on every file | touches all 30 files | |
| Mark only new M1 tests | narrower than M1-09 reads | |

**User's choice:** Auto-apply by path in root conftest.
**Notes:** Found all 30 existing test files are `unittest.TestCase` with no markers and no conftest; bulk unittest→pytest conversion is M2b.

### Conftest layout
| Option | Description | Selected |
|--------|-------------|----------|
| Single root test/conftest.py | shared fixtures + auto-marking hook | ✓ |
| Root + per-package conftests | premature structure | |
| You decide | — | |

**User's choice:** Single root test/conftest.py.

### Smoke vs integration split
| Option | Description | Selected |
|--------|-------------|----------|
| Smoke = tiny slice; integration = full golden diff | fast smoke + full regression | ✓ |
| Both run the full CSV | slow smoke loses fast-feedback value | |
| You decide | — | |

**User's choice:** Smoke = tiny slice; integration = full golden diff.

---

## Claude's Discretion

- Exact ticker string if universe/price-handler wiring needs a specific symbol.
- Exact filenames / column schemas within `output/` and `test/golden/`.
- Directory→marker mapping details and conftest fixture signatures.
- Run-script location/name and how `make backtest` invokes it.

## Deferred Ideas

- Standalone CSV provider / real Provider–Store–Feed split → M5a (M5-04).
- Full strategy-declared sizing policy + `RiskManager.check_cash` + `VariableSizer` → M5b (M5-06).
- Injected clock + seeded RNG + UUIDv7 + Decimal money → M2.
- Fee/slippage correctness → M5a (M5-03).
- Bulk unittest→pytest-native conversion → M2b (M2-09).
- Update doc references to the new dataset filename → COVERAGE-INDEX §E gap-discovery delta.
