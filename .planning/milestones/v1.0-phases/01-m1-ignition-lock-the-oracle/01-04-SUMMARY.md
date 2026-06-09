---
phase: 01-m1-ignition-lock-the-oracle
plan: 04
subsystem: oracle-generator (run script / make target / smoke gate)
tags: [oracle, run-backtest, make-backtest, smoke, ignition, sizing-seam, decimal-money, def-resolution]
requires:
  - "01-01: importable backtest path + package-level config re-exports + RED smoke scaffold"
  - "01-02: PriceHandler csv/offline feed (3076 BTCUSD bars, exact CCXT frame shape, D-02 window)"
  - "01-03: SMA_MACD .iloc/fillna fix, record_metrics per-Portfolio, fraction-of-cash sizing seam"
provides:
  - "scripts/run_backtest.py: pinned reproducible oracle generator (D-01/02/04/06), serializes deterministic trades/equity/summary to output/ from closed_positions + metrics snapshots (NOT _prepare_data)"
  - "make backtest target invoking the run script; output/ gitignored (output/ form), test/golden committable"
  - "Green smoke test: full PING->BAR->SIGNAL->ORDER->FILL loop runs end-to-end under filterwarnings=error and produces real round-trip trades (M1-09)"
  - "DEF-01-B resolved: csv execution-venue alias + BTCUSD supported symbol + csv venue admitted + crypto price ceiling + sizing-before-validation narrow gate + long-only exit closes the open long"
  - "DEF-01-A resolved (minimal local fix, overlaps M4): Decimal fee commission coerced to float at the fill->transaction boundary + position avg_price"
affects:
  - scripts/run_backtest.py
  - Makefile
  - .gitignore
  - itrader/execution_handler/execution_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/position.py
  - test/test_smoke/test_backtest_smoke.py
tech-stack:
  added: []
  patterns:
    - "Pinned oracle generator: dataset/window/cash/params literals in a committed run script for bit-reproducibility (D-12)"
    - "Source equity from metrics_manager PortfolioSnapshot list, not StatisticsReporting._prepare_data (Pitfall 5)"
    - "Deterministic serialization: pandas to_csv with pinned float_format + stdlib json sorted/indented (T-04-01/02)"
    - "Resolve sizing BEFORE validation as a narrow gate so the validator's zero-quantity rejection unit-test stays intact"
    - "Coerce Decimal money to float at the single fill->transaction boundary rather than patching every downstream arithmetic site"
    - "Long-only exit sizing: a SELL with an open long is sized to the long's net quantity so round-trips close"
key-files:
  created:
    - scripts/run_backtest.py
  modified:
    - Makefile
    - .gitignore
    - itrader/execution_handler/execution_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_validator.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/position.py
    - test/test_smoke/test_backtest_smoke.py
decisions:
  - "D-01/02/04/06: dataset/window/cash/ticker pinned as literals in scripts/run_backtest.py"
  - "D-10/D-12: CSV trade log + CSV equity + JSON summary; deterministic fields only (exclude position_id/current_price/unrealised_pnl)"
  - "D-11: output/ gitignored (trailing-slash form); test/golden committable"
  - "DEF-01-B(3) implemented as sizing-before-validation (narrow gate), NOT by weakening the validator's zero-quantity rule (preserves test_zero_quantity_signal)"
  - "DEF-01-A fixed at the single fill->transaction commission boundary (minimal, overlaps M4 #22 — reconcile at M4)"
  - "Long-only SELL exit sizes to the open long's net quantity so positions close (minimal M1-06 extension; full sizing policy is M5)"
metrics:
  duration: ~22 min
  completed: 2026-06-04
---

# Phase 1 Plan 04: Oracle Generator + Smoke Green Summary

Built the committed, reproducible oracle generator (`scripts/run_backtest.py` + `make backtest`)
that runs the full PING→BAR→SIGNAL→ORDER→FILL loop on the golden BTCUSD CSV and serializes a
**deterministic** trade log + equity curve + summary to `output/`, and turned the run-path smoke
test GREEN (M1-07, M1-09). Getting the loop to run end-to-end required resolving the two
pre-identified blockers (DEF-01-B integration wirings and the DEF-01-A money-type defect) plus a
small set of same-class wirings that surfaced once fills started flowing. A `make backtest` run now
produces **134 round-trip trades** with a final equity of **$53,229.75** (start $10k, total realised
PnL +$43,229.70), all under `filterwarnings=["error"]`, with the 274 legacy tests still green.

## What Was Built

### Task 1 — scripts/run_backtest.py + ignition wirings (M1-07) — commit 00d7d40
- `scripts/run_backtest.py` (SPACES): constructs the csv-fed `TradingSystem` pinning the window
  2018-01-01→2026-06-03 (D-02), adds a $10k portfolio (D-04) and the `SMA_MACD` strategy on `1d`
  subscribed to `BTCUSD` (D-03/D-06), runs `system.run(print_summary=False)` (avoids the broken
  `_prepare_data`, Pitfall 5), then reads result state AFTER the run (queue-only rule) and writes:
  - `output/trades.csv` — deterministic columns only from `closed_positions`→`Position.to_dict()`
    (entry_date, exit_date, side, net_quantity, avg_price, avg_bought, avg_sold, total_bought,
    total_sold, realised_pnl, pair); EXCLUDES position_id/current_price/unrealised_pnl (D-12).
  - `output/equity.csv` — sourced from the `metrics_manager` `PortfolioSnapshot` list (NOT
    `_prepare_data`); Decimal fields cast to float, rows sorted by timestamp.
  - `output/summary.json` — final cash + minimal deterministic metrics (trade count, total realised
    PnL, final equity); derived ratios omitted (M5-owned/buggy). Pinned `float_format=%.10f` and
    `json.dump(sort_keys=True, indent=2)` for cross-platform repr stability (T-04-01/02).
- The integration/money wirings needed to make the run execute are committed alongside (see
  Deviations).

### Task 2 — make backtest target + gitignore (M1-07) — commit 3872013
- `Makefile`: added a TAB-indented `backtest` target (`poetry run python scripts/run_backtest.py`,
  emoji-echo style matching the test-* targets) and registered it in `.PHONY`.
- `.gitignore`: normalized bare `output` → `output/` (D-11). `test/golden` remains committable
  (verified via `git check-ignore`).

### Task 3 — smoke test green (M1-09) — commit 619b38f
- `test/test_smoke/test_backtest_smoke.py` (SPACES): the assertion was corrected to check a
  non-zero **traded** quantity (`buy_quantity`/`sell_quantity`) rather than `net_quantity` — a
  CLOSED position has `net_quantity ≈ 0` by construction (it closes when buy/sell net to within
  tolerance), so the original net-quantity assertion could never pass once positions actually
  close. The test now proves: (a) the loop runs to completion without raising (catches the
  FutureWarning hard-error, Pitfall 3, and the tz-mismatch zero-trade case, Pitfall 6), and (b)
  ≥1 closed position round-tripped a real non-zero quantity.

## Verification Results

- `make backtest` exits 0 and writes `output/{trades.csv,equity.csv,summary.json}` — **134 trade
  rows** (>1), `total_equity` column present in equity.csv, valid summary.json with final cash +
  trade count + total realised PnL.
- `grep -Pc "\t" scripts/run_backtest.py` = 0 (SPACES); script makes no real `_prepare_data` call
  (only mentioned in cautionary comments).
- `grep -qE "^backtest:" Makefile` PASS; `backtest` in `.PHONY`; `grep -qE "^output/?$" .gitignore`
  PASS; `git check-ignore test/golden/trades.csv` → not ignored (committable).
- `poetry run pytest test/test_smoke -m unit -q` — **1 passed** (smoke GREEN under filterwarnings=error).
- `poetry run pytest test/ -q` — **275 passed** (274 legacy + 1 smoke; no regression).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Smoke assertion checked the wrong quantity (net vs traded)**
- **Found during:** Task 3. The pre-existing scaffold asserted `abs(net_quantity) > 0` on CLOSED
  positions, but a closed position's net_quantity is ~0 by definition.
- **Fix:** assert a non-zero traded quantity (`buy_quantity`/`sell_quantity`) instead.
- **Files modified:** test/test_smoke/test_backtest_smoke.py — **Commit:** 619b38f

### Out-of-declared-scope wirings (pre-identified, owner-routed to this plan)

These touch files outside this plan's three declared `files_modified` but were explicitly
authorized by `deferred-items.md` (DEF-01-B routed to Plan 04, DEF-01-A authorized for a minimal
fix). All committed in 00d7d40.

**2. [DEF-01-B(1) - Wiring] `csv` execution-venue alias to SimulatedExchange**
- Backtest portfolios use `exchange="csv"`, so orders carry that venue. `ExecutionHandler.init_exchanges`
  now maps `'csv'` to the same `SimulatedExchange` instance as `'simulated'`. Added an id-dedup
  guard in `on_market_data` so the shared instance is driven once per bar (no double matching).
- **File:** itrader/execution_handler/execution_handler.py

**3. [DEF-01-B(2) - Wiring] `BTCUSD` added to the simulated exchange's supported symbols**
- The default preset lists only `*USDT`. Added `BTCUSD` to the instance's `_supported_symbols`
  (instance-level mutation, not the shared preset, so other exchanges/tests are unaffected).
- **File:** itrader/execution_handler/execution_handler.py

**4. [DEF-01-B(3) - Wiring, narrow gate] Resolve sizing BEFORE validation**
- Rather than weakening the validator (which would break `test_zero_quantity_signal`), the
  fraction-of-cash sizing is now resolved in `OrderManager._resolve_signal_quantity`, called at the
  TOP of `process_signal` (before the validator runs) and idempotently re-called in
  `_create_primary_order` for the direct-create path. The running engine therefore never presents
  `quantity=0` to the validator, while the validator's own zero-quantity rejection — exercised
  directly via `validate_signal_pipeline` by the unit test — is left fully intact.
- **File:** itrader/order_handler/order_manager.py

**5. [DEF-01-B class - Wiring] Validator admits `csv` venue + raises crypto price ceiling**
- Surfaced once orders started routing: the validator rejected `Unsupported exchange: csv` and
  `Price ... above maximum 100000.0` (BTC reaches ~$116k). Added `"csv"` to `supported_exchanges`
  and raised `max_price` (10_000_000) so the offline crypto run is admitted.
- **File:** itrader/order_handler/order_validator.py

**6. [Rule 2 - Missing functionality] Long-only SELL exit sizes to close the open long**
- The SMA_MACD reference strategy is long-only (BUY enters, SELL exits; short block commented out).
  Sizing every SELL as fresh fraction-of-cash meant exits never netted the open long to zero, so no
  position ever closed and the trade log stayed empty. `_resolve_signal_quantity` now sizes a SELL
  with an open long to that long's net quantity, so round-trips close. This is the minimal M1-06
  extension required for M1-07's "non-trivial trade log"; the full strategy-declared sizing policy
  remains M5.
- **File:** itrader/order_handler/order_manager.py

**7. [DEF-01-A - Money type, MINIMAL fix overlapping M4] Decimal commission coerced to float**
- The fee model returns `Decimal` commissions (even ZeroFeeModel → `Decimal('0')`) into a float
  transaction/position path → `TypeError` on the first fill, then again in the
  `TransactionManager` funds check. Fixed at the single `PortfolioHandler.on_fill`
  fill→transaction boundary (coerce `fill_event.commission` to `float`, matching
  `Transaction.commission: float`) plus a defensive `float(...)` in `Position.avg_price`. This is a
  behavior-preserving type-consistency fix, NOT the Decimal-money redesign M4 owns (#22 Critical) —
  **flagged for reconciliation at M4.**
- **Files:** itrader/portfolio_handler/portfolio_handler.py, itrader/portfolio_handler/position.py

## Threat Model Compliance

- T-04-01 (Tampering — non-deterministic fields leak): mitigated. Only deterministic columns
  serialized (position_id/current_price/unrealised_pnl excluded); pinned float_format; rows sorted
  by bar time.
- T-04-02 (Tampering — unsafe deserialization): mitigated. stdlib `json` + pandas `to_csv` only; no
  eval/pickle.
- T-04-03 (Info Disclosure — committing fresh run artifacts): mitigated. `output/` gitignored;
  blessed `test/golden` is committed only in Plan 05.
- T-04-SC: accept — no package installs.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: money-semantics | itrader/portfolio_handler/portfolio_handler.py, position.py | DEF-01-A float/Decimal boundary coercion is a temporary M1 fix that overlaps M4's Decimal-money trust-boundary work (#22 Critical); must be reconciled when money moves to Decimal end-to-end. |

## Known Stubs

None. `make backtest` produces a real 134-trade deterministic oracle from live closed positions and
metrics snapshots; the smoke test exercises the same loop and asserts real round-trip trades. The
oracle's economic realism (e.g. the first signal being a SELL that opens a transient short, precise
long-only entry/exit gating) is an M5 strategy-correctness concern, not a stub — the loop runs and
produces a non-trivial, deterministic, closing trade log as required by M1-07.

## Notes for Next Plan

- Plan 05 (lock the oracle) promotes a blessed `output/` run to the committed `test/golden/` and
  adds the integration test that diffs a fresh full run against it (D-13). The current
  `make backtest` output (134 trades, final equity $53,229.75) is the candidate to bless.
- M4 must reconcile the DEF-01-A float coercions (portfolio_handler.on_fill, position.avg_price)
  when money moves to Decimal end-to-end (#22 Critical).
- M5 owns the full strategy-declared sizing policy and the long-only entry/exit semantics; the
  minimal SELL-exit-closes-the-long sizing added here is the M1 seam M5 will extend, not replace.

## Self-Check: PASSED
- FOUND: scripts/run_backtest.py (created)
- FOUND: output/trades.csv (134 rows), output/equity.csv, output/summary.json (generated, gitignored)
- FOUND: Makefile backtest target + .PHONY entry
- FOUND: .gitignore output/ (trailing-slash form)
- FOUND commit: 00d7d40 (Task 1 — run script + ignition wirings)
- FOUND commit: 3872013 (Task 2 — make backtest + gitignore)
- FOUND commit: 619b38f (Task 3 — smoke green)
