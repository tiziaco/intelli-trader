# Milestones

## v1.1 — Backtest Trustworthiness: Breadth (Shipped: 2026-06-10)

**Scope:** 9 phases (Phases 1–9, numbering reset from v1.0), 28 plans, 53 tasks. The 999.x backlog phases (N+2…N+4, plus the v1.2 Engine Surface Completion seed) are future milestones, not part of v1.1.

**Delivered:** Trustworthy, regression-locked backtest behavior extended across the engine's *entire* feature surface — resting-order book, brackets/OCO, fee/slippage variants, SLTP policies, sizing, scale in/out, and multi-strategy/multi-ticker/multi-portfolio runs — **without re-baselining the v1.0 golden numbers**. The hardening gate before any margin/live work.

**Definition of done — achieved:** full feature surface exercised by a 58-leaf frozen E2E matrix (`tests/e2e/`, `e2e` marker, `make test-e2e`, per-scenario golden fixtures, shared harness) + the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`, byte-exact) · `pytest tests/e2e -m e2e` 58 passed · `pytest tests/integration` 12 passed · `mypy --strict` clean across 161 source files · behavior-preserving guarantee held (no oracle re-baseline). LONG-ONLY throughout; shorts gated to v1.2.

**Key accomplishments:**

- **E2E harness + full coverage matrix (Phases 4, 6–9):** stood up the dedicated `tests/e2e/` apparatus (registered `e2e` marker, folder-derived auto-marking, `make test-e2e`, shared golden-compare harness with hand-verify-once-then-freeze discipline), then filled it to a 58-leaf frozen matrix spanning matching, cost, sizing, SLTP, admission, cash, multi-entity, and robustness — every leaf hand-verified once against the real `TradingSystem` (no mocks) before freezing.
- **Order-matching + cost/sizing/SLTP surface proven (Phases 6–7):** golden-locked the resting-order book end-to-end — MARKET/LIMIT/STOP fill shapes, bracket OCO lifecycle, same-bar STOP-beats-LIMIT priority, gap clean-through/past-both-legs, MODIFY/CANCEL round-trips, far-from-market no-fill (MATCH-01..08); plus percent & maker/taker fees, fixed & linear slippage (not-on-limit), combined cash math to the cent, `FixedQuantity`/`RiskPercent`/over-cash sizing, and `PercentFromDecision`/`PercentFromFill` SL/TP exit outcomes (COST/SIZE/SLTP).
- **Admission, position management & cash edges (Phase 8):** first end-to-end coverage of the LONG-ONLY directions v1.0 never exercised — scale-in (pyramiding via `allow_increase=True`), partial scale-out, `max_positions` rejection, exit-then-re-entry — plus the full cash reservation/release lifecycle across CANCELLED/REJECTED/REFUSED, fronted by a new opt-in oracle-dark cash-ledger snapshot serializer.
- **Strategy interface hardening + signal storage (Phase 5):** collapsed the strategy constructor to a single frozen pydantic `BaseStrategyConfig` + per-strategy params validators (`short_window < long_window`, positivity), made `order_type` the `OrderType` enum end-to-end, and added a typed, queryable `SignalRecord` store (own UUIDv7 `SignalId` + config snapshot, pluggable seam) — all byte-exact vs the SMA_MACD oracle, pure-alpha D-12 contract intact.
- **Data ingestion + minimal real universe (Phases 2–3):** a committed, re-runnable normalization script brings ETH/SOL/AAVE into the byte-identical golden Binance-kline schema (loaded through the UNCHANGED `CsvPriceStore`); a real `membership`-from-availability primitive (`is_active`/`active_membership`) replaces the stub and is proven over mid-run listings and differing end dates with no crash and no look-ahead.
- **Multi-entity breadth + robustness + determinism (Phase 9):** multi-ticker, multi-strategy, multi-portfolio cash isolation, contended-cash contention, sparse-bar and union-window real-data spans, degenerate-run metric finiteness (no NaN/inf), and cross-scenario double-run byte-identity (MULTI-01..04, ROBUST-01..04).
- **Codebase clarity, scoped (Phase 1, cross-cutting):** one `gsd-map-codebase` pass → objective `FIX-LIST.md`; the opportunistic-cleanup standard (4-gate checklist) established and applied along touched paths only — no big-bang refactor, no oracle re-baseline — verified at milestone close (CLAR-01/02).

**Audit:** `passed` status — 51/51 requirements satisfied, 9/9 phases verified, 58/58 e2e + 12/12 integration seams, 58/58 flows, 0 blockers. Phase 9 WR-01 (determinism frame scope) fixed in code; WR-02 (`profit_factor: inf` on genuinely all-win goldens) owner-ratified carve-out. See `milestones/v1.1-MILESTONE-AUDIT.md`.

**Known deferred items at close: 4** (the 4 completed v1.1 quick tasks — canonically complete, flagged only by a `gsd-sdk` v1.42.3 SDK-port filename bug; see STATE.md → Deferred Items). Tracked optional hygiene: formal Nyquist Wave-0 incomplete on 6 phases / absent on 2 (strong behavioral coverage via the 58-leaf matrix + oracle), and empty `requirements_completed` SUMMARY frontmatter on phases 1/4/5/7/9 (cosmetic — traceability + VERIFICATION carry the truth). Substantive behavior deferrals (margin/liquidation, shorts, trailing stops, real pair trading) → v1.2 (ROADMAP backlog).

**Archived:** `milestones/v1.1-ROADMAP.md`, `milestones/v1.1-REQUIREMENTS.md`, `milestones/v1.1-MILESTONE-AUDIT.md`.

---

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
