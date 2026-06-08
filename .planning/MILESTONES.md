# Milestones

## v1.0 — Backtest-Correctness Refactor (Shipped: 2026-06-08)

**Scope:** 8 phases (M1 → M5c), 62 plans. The 999.x backlog phases (N+1…N+4) are future milestones, not part of v1.0.

**Delivered:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` now produces correct, deterministic, externally cross-validated numbers — the engine's results are trustworthy and regression-locked.

**Definition of done — green on all 8 checks (08-09 owner-signed final-oracle freeze):**
`SMA_MACD` runs end-to-end (134 trades / final_equity 46189.87730727451 / 3076 equity points) · `mypy --strict` clean · no float money (Decimal end-to-end) · single UUIDv7 scheme · deterministic (seeded RNG + injected clock) · 724 tests pass · run-path integration gate byte-exact · cross-validated vs `backtesting.py` + `backtrader` (+ `nautilus-trader`).

**Key accomplishments:**

- **M1 — Ignition + lock the oracle:** Made the backtest path import and run end-to-end (resolved the config-shadow import cascade, `to_timedelta`, `SMA_MACD` `.iloc`/`fillna`, `record_metrics` target, minimal sizing seam); froze the human-blessed behavioral + numerical reference oracle into `tests/golden/`, regression-locked by an exact tolerance-free integration test.
- **M2 — Identity, money, determinism & foundations:** Single UUIDv7 ID scheme via `uuid-utils`; money Decimal end-to-end with centralized quantization; `mypy --strict` clean with frozen/slots DTOs and real ABCs (11 dead Py2 `__metaclass__` bases → Protocols/ABCs); deterministic runs (seeded RNG + injected clock); config collapsed 3,380 → ~1,130 lines of Pydantic v2 + `pydantic-settings`; enums centralized; portfolio storage seam; numerical oracle re-frozen byte-exact after the float→Decimal shift.
- **M3 — Event & dispatch core:** Immutable frozen events with `event_id` + required linkage IDs + enum-typed fields; race-free `dict[EventType, list[Callable]]` dispatch registry (`get_nowait`, `NotImplementedError` on unknown types); unified `ITraderError` hierarchy + structlog — behavior-preserving, oracle byte-exact.
- **M4 — Money & transaction correctness:** Every trade's cash routes through `CashManager` (reservation lifecycle, no setter bypass); atomic validate-first settlement; one-directional facade→manager→storage layering with O(1) `{order_id: order}` lookup + narrow `PortfolioReadModel` Protocol; frozen Decimal execution DTOs — value-preserving, oracle byte-exact.
- **M5a/M5b — Backtest validity, fills, data pipeline, sizing & metrics:** Removed resampling look-ahead, immutable `Bar` struct payload, precomputed frames, correct fee/slippage, Provider/Store/Feed price-handler split with a read-only run path; next-bar-open fills through the unified `MatchingEngine`; full strategy-declared sizing resolved engine-side (`SizingResolver`); correct reporting/metrics; universe stub. Two owner-approved RESULT-CHANGING re-freezes (LONG_ONLY direction guard + `allow_increase=False`) — oracle settled at 134 trades, 0 shorts.
- **M5c — Cross-validation & final oracle:** Cross-validated against `backtesting.py`, `backtrader`, and `nautilus-trader` — all reconcile to 134 trades and final_equity ≈ 46189.877; verdict 0 BUG / 4 LEGITIMATE-DIFFERENCE (owner-approved); final numerical oracle frozen as the new authoritative reference.

**Audit:** `tech_debt` status — all 45/45 requirements satisfied, 8/8 phases verified, 18/18 integration seams wired, 1/1 E2E flow complete, 0 blockers. See `milestones/v1.0-MILESTONE-AUDIT.md`.

**Known deferred items at close: 12** (3 done-but-flagged quick tasks, 5 partial human-UAT gaps, 4 unsigned per-phase verification reports — all advisory, owner-deferred, or out-of-scope live-mode; see STATE.md → Deferred Items). Substantive behavior deferrals (margin/liquidation model, shorts, SHORT_ONLY cover-arm hole) are tracked in the ROADMAP backlog as N+2.

**Archived:** `milestones/v1.0-ROADMAP.md`, `milestones/v1.0-REQUIREMENTS.md`, `milestones/v1.0-MILESTONE-AUDIT.md`.

---
