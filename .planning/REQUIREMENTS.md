# Requirements: v1.1 — Backtest Trustworthiness: Breadth

> **Milestone goal:** Exhaustively harden the backtest engine — exercise the *entire*
> feature surface end-to-end (resting orders, brackets/OCO, fee/slippage, SLTP, sizing,
> scale in/out, multi-strategy/multi-ticker) — without re-baselining the v1.0 golden numbers.
>
> **Asset focus:** crypto-first. **Direction:** LONG-ONLY (shorts gated to v1.2 by the
> D-08/D-09 guard). **Proof model:** each E2E scenario uses a tiny purpose-built strategy on
> a known slice; expected fills/PnL are **hand-verified once, then regression-locked**.
> External cross-validation (backtesting.py/backtrader) only where those tools can express
> the scenario.

---

## v1.1 Requirements

### Data Ingestion (INGEST)
- [x] **INGEST-01**: A committed, re-runnable normalization script converts provider CSVs (split `date`+`time`, lowercase columns) into the golden Binance-kline schema (single tz-aware `Open time` + `Open/High/Low/Close/Volume`).
- [x] **INGEST-02**: ETHUSD, SOLUSD, AAVEUSD committed in the normalized golden schema alongside BTCUSD.
- [x] **INGEST-03**: `CsvPriceStore` loads all four datasets **unchanged** (no run-path schema-detection logic).

### Minimal Universe (UNIV)
- [x] **UNIV-01**: A real `membership` primitive derives the set of active tickers at time T from data availability (replaces the stub). Screening/ranking explicitly excluded.
- [x] **UNIV-02**: The engine correctly handles a ticker that lists mid-backtest and assets with differing end dates — no crash, no look-ahead, absent bars produce no fill.

### E2E Test Framework (E2E)
- [x] **E2E-01**: Dedicated `tests/e2e/` tree, subsystem-grouped, with a registered `e2e` marker (in `pyproject.toml`), folder-derived auto-marking, and a `make test-e2e` target.
- [x] **E2E-02**: A shared harness (`tests/e2e/conftest.py`) runs the full engine on a given `(strategy, data)` and diffs the result (trades/equity/summary) against that scenario's golden fixtures.
- [x] **E2E-03**: Each scenario is a self-contained leaf folder: its purpose-built strategy + frozen golden fixtures, runnable warning-clean under `filterwarnings=["error"]`.
- [x] **E2E-04**: Every scenario oracle is hand-verified for correctness once before it is frozen.

### Strategy Interface Hardening (HARD)
- [x] **HARD-01**: A pydantic `BaseStrategyConfig` validates engine-facing declarations (timeframe, tickers, order_type, direction, allow_increase, max_positions, sizing_policy, sltp_policy).
- [x] **HARD-02**: A per-strategy params model with validators (e.g. `short_window < long_window`, positivity) replaces unvalidated loose attributes.
- [x] **HARD-03**: `order_type` is the `OrderType` enum end-to-end (stringly-typed `"market"` removed).
- [x] **HARD-04**: The refactor is behavior-preserving — SMA_MACD golden master stays byte-exact (134 trades / `final_equity 46189.87730727451`); the golden test re-runs green proving zero drift. Pure-alpha D-12 contract intact (pydantic at construction only; `generate_signal` stays pure pandas).

### Signal Storage (SIG)
- [x] **SIG-01**: Strategy-generated signals are persisted with a typed record (strategy id, ticker, action, time, sizing/sltp declarations, config snapshot).
- [x] **SIG-02**: Stored signals are queryable for post-run inspection and feed E2E assertions.

### Order Types & Matching coverage (MATCH)
- [ ] **MATCH-01**: MARKET next-bar-open fills (regression of the v1.0 path).
- [ ] **MATCH-02**: LIMIT entry — in-bar touch fills at limit **vs** favorable gap-through fills at the better open.
- [ ] **MATCH-03**: STOP entry — pessimistic gap-down/gap-up fills.
- [ ] **MATCH-04**: Bracket order (entry + SL + TP) full OCO lifecycle: children dormant while parent rests, arm on parent fill, sibling OCO-cancel on fill.
- [ ] **MATCH-05**: Same-bar double trigger (SL and TP both reachable) resolves by STOP-beats-LIMIT priority.
- [ ] **MATCH-06**: Gap clean through a stop/limit, and a gap past *both* bracket legs.
- [ ] **MATCH-07**: MODIFY (re-price/re-size) and CANCEL of a resting order via the order round-trip.
- [ ] **MATCH-08**: A limit far from market never fills and is handled at run end.

### Fees & Slippage coverage (COST)
- [x] **COST-01**: percent fee model on a round-trip.
- [x] **COST-02**: maker_taker fee model — maker vs taker distinguished (limit vs market).
- [x] **COST-03**: fixed slippage model.
- [x] **COST-04**: linear slippage model.
- [x] **COST-05**: slippage is **not** applied to limit fills.
- [x] **COST-06**: combined fee+slippage round-trip cash math verified to the cent.

### Sizing coverage (SIZE)
- [x] **SIZE-01**: `FixedQuantity` sizing.
- [x] **SIZE-02**: `RiskPercent` sizing off stop distance.
- [x] **SIZE-03**: over-cash sizing produces the audited insufficient-funds rejection.

### SL/TP Policy coverage (SLTP)
- [x] **SLTP-01**: `PercentFromDecision` — SL/TP priced at signal assembly.
- [x] **SLTP-02**: `PercentFromFill` — SL/TP anchored to the actual fill price in `on_fill`.
- [x] **SLTP-03**: SL-hit, TP-hit, and held-to-end (neither) exit outcomes.

### Admission & Position Management (ADMIT)
- [x] **ADMIT-01**: `allow_increase=True` scale-in (pyramiding) **works** end-to-end (v1.0 only validated the reject direction).
- [x] **ADMIT-02**: partial scale-out via `exit_fraction < 1` across multiple sells.
- [x] **ADMIT-03**: reaching `max_positions` produces the audited new-entry rejection.
- [x] **ADMIT-04**: full exit followed by re-entry on the same ticker.

### Multi-Entity (MULTI)
- [ ] **MULTI-01**: one strategy trading two cryptos (multi-ticker) end-to-end.
- [ ] **MULTI-02**: multiple strategies running simultaneously.
- [ ] **MULTI-03**: a strategy fanned out to >1 portfolio, with per-portfolio cash isolation.
- [ ] **MULTI-04**: two strategies competing for the same portfolio's cash.

### Cash & Accounting edges (CASH)
- [x] **CASH-01**: insufficient funds → audited `cash_reservation` rejection.
- [x] **CASH-02**: reservation release on every terminal state (CANCELLED / REJECTED / REFUSED).

### Robustness & Metrics edges (ROBUST)
- [ ] **ROBUST-01**: sparse/absent bar for a ticker at T produces no fill and no crash.
- [ ] **ROBUST-02**: heterogeneous date spans (asset enters mid-run; differing end dates) handled over a union window.
- [ ] **ROBUST-03**: no-trade / flat / losing runs produce valid metrics (no NaN, no div-by-zero in Sharpe/drawdown/profit-factor).
- [ ] **ROBUST-04**: determinism — double-run byte-identical across all new scenarios.

### Codebase Clarity (CLAR)
- [ ] **CLAR-01**: one `gsd-map-codebase` pass produces an objective fix-list (naming, visibility, seams).
- [ ] **CLAR-02**: opportunistic naming/visibility cleanup applied along touched paths — NO big-bang refactor, no oracle re-baseline.

---

## Future Requirements (deferred)

- **v1.2 — Margin, Leverage, Shorts & Trailing Stops:** shorts (remove D-08/D-09 guard + fix CR-01 cover arm), margin/liquidation model, leverage, levered Kelly, perp funding-rate, engine-native trailing stop, **real long/short pair trading** (first flagship use of shorts).
- **v1.3 — Persistence & Performance:** PostgreSQL storage, profiler-guided performance, production-ready universe/screener.
- **v1.4 — Live Trading Readiness:** real-time data engine, live execution, `TradingInterface` modify/cancel.
- **Multi-asset (deferred indefinitely under crypto-first):** multi-currency accounting, trading calendars/sessions, corporate actions (forex/equities/ETF).
- **Sizing:** unlevered `KellyFraction` / vol-target — pulled into v1.1 ONLY if a validated strategy needs it (rolling/walk-forward edge estimate, never realized-stats).
- **Instrument/contract-spec model** — folded into v1.1 config typing only if cheap; otherwise a data-engine concern.

## Out of Scope (v1.1)

- **Shorts / short-side anything** — hard-gated by the `StrategiesHandler` LONG_ONLY guard (D-08/D-09); needs the margin/liquidation model first.
- **Live trading, PostgreSQL persistence, performance optimization** — explicit later milestones; v1.1 is correctness-breadth only.
- **Production screener/ranking** — only minimal `membership`-from-availability is in scope.
- **Re-baselining the golden numbers** — v1.1 is behavior-preserving; any result-changing finding is owner-gated, not silently folded in.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CLAR-01 | Phase 1 | Pending |
| CLAR-02 | Phase 1 | Pending |
| INGEST-01 | Phase 2 | Complete |
| INGEST-02 | Phase 2 | Complete |
| INGEST-03 | Phase 2 | Complete |
| UNIV-01 | Phase 3 | Complete |
| UNIV-02 | Phase 3 | Complete |
| E2E-01 | Phase 4 | Complete |
| E2E-02 | Phase 4 | Complete |
| E2E-03 | Phase 4 | Complete |
| E2E-04 | Phase 4 | Complete |
| HARD-01 | Phase 5 | Complete |
| HARD-02 | Phase 5 | Complete |
| HARD-03 | Phase 5 | Complete |
| HARD-04 | Phase 5 | Complete |
| SIG-01 | Phase 5 | Complete |
| SIG-02 | Phase 5 | Complete |
| MATCH-01 | Phase 6 | Pending |
| MATCH-02 | Phase 6 | Pending |
| MATCH-03 | Phase 6 | Pending |
| MATCH-04 | Phase 6 | Pending |
| MATCH-05 | Phase 6 | Pending |
| MATCH-06 | Phase 6 | Pending |
| MATCH-07 | Phase 6 | Pending |
| MATCH-08 | Phase 6 | Pending |
| COST-01 | Phase 7 | Complete |
| COST-02 | Phase 7 | Complete |
| COST-03 | Phase 7 | Complete |
| COST-04 | Phase 7 | Complete |
| COST-05 | Phase 7 | Complete |
| COST-06 | Phase 7 | Complete |
| SIZE-01 | Phase 7 | Complete |
| SIZE-02 | Phase 7 | Complete |
| SIZE-03 | Phase 7 | Complete |
| SLTP-01 | Phase 7 | Complete |
| SLTP-02 | Phase 7 | Complete |
| SLTP-03 | Phase 7 | Complete |
| ADMIT-01 | Phase 8 | Complete |
| ADMIT-02 | Phase 8 | Complete |
| ADMIT-03 | Phase 8 | Complete |
| ADMIT-04 | Phase 8 | Complete |
| CASH-01 | Phase 8 | Complete |
| CASH-02 | Phase 8 | Complete |
| MULTI-01 | Phase 9 | Pending |
| MULTI-02 | Phase 9 | Pending |
| MULTI-03 | Phase 9 | Pending |
| MULTI-04 | Phase 9 | Pending |
| ROBUST-01 | Phase 9 | Pending |
| ROBUST-02 | Phase 9 | Pending |
| ROBUST-03 | Phase 9 | Pending |
| ROBUST-04 | Phase 9 | Pending |

**Coverage:** 51/51 v1.1 requirements mapped — no orphans, no duplicates.
