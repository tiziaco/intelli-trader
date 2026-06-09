# Fix-List (CLAR-01)

**Harvested:** 2026-06-09 · **Derived from:** `.planning/codebase/` map
(`CONCERNS.md` + `CONVENTIONS.md` + `STRUCTURE.md`) plus the two verified v1.0 residual
carry-forwards (#7/#37, #10). · **Satisfies:** CLAR-01.

This is the objective, deduplicated CLAR-01 fix-list for the v1.1 milestone (Backtest
Trustworthiness: Breadth). It was **NOT** produced by a fresh `gsd-map-codebase` run — the
codebase map is current (Analysis Date 2026-06-08, after engine commit `017bf72`); this artifact
**harvests** from that existing map rather than re-deriving it. The two named residual items
(#7/#37 `portfolio.py` bare `ValueError`s, #10 `portfolio_id: int` annotation carry-over) are
pulled forward from the archived `milestones/v1.0-COVERAGE-INDEX.md` per the ROADMAP; the
archived `milestones/v1.0-ARCHITECTURE-REVIEW.md` is a pre-v1.0 snapshot and was **NOT** used as
a source.

This list is **honest about a small post-refactor violation surface — no padding.** The
naming-fix surface is genuinely small (chiefly #10's annotation and the `order_type` string), the
visibility/exception surface is the bare-`ValueError` sites and the dead test skip, and the seam
surface is the deferred-path stubs (live / SQL / providers / `my_strategies`). `CONVENTIONS.md`
records the intended naming/visibility/seam conventions with **no violations** in the current tree
beyond the carry-forwards. Items were not invented to fill categories.

All line references below were **re-verified against the current tree** (grep, 2026-06-09) — the
exact line numbers are preserved as load-bearing citations.

## Scope discipline (read before consuming)

- **No `itrader/` or `tests/` source file is touched by this artifact.** It *records* line
  references; it never fixes them. Each fix happens later, in the phase that already touches the
  path (the `Eligible-in-phase` column), under the byte-exact golden-master gate.
- **Category C (deferred) items are RECORDED, not actioned in v1.1.** They live on paths v1.1
  does not touch (live / SQL / providers / `my_strategies`); each carries an owning milestone. The
  cleanup standard's eligibility gate keeps them untouched. Do NOT plan v1.1 fixes for them.
- **Golden master is NOT re-baselined in v1.1** (134 trades / `final_equity 46189.87730727451`).
  Any later cleanup on a `Golden-path? yes` item must re-run byte-exact.

## Column schema

| Column | Meaning |
|--------|---------|
| `ID` | Stable `FL-NN` identifier (survives reorder; later phases cite "fixes FL-03"). |
| `Category` | One of: naming / visibility / seam / exception / annotation / test-hygiene. |
| `Description` | One-line objective statement of the issue. |
| `File(s):line` | Exact, verified path(s) and line(s). |
| `Golden-path?` | `yes` / `no` — drives the byte-exact re-run requirement when fixed. |
| `Eligible-in-phase` | Pre-tagged v1.1 phase whose touched paths make the item eligible, or `deferred → vX.Y`. |
| `Status` | `open` / `done (phase N)` / `deferred`. |
| `Origin` | Provenance: `#7/#37` / `#10` / `CONCERNS.md` / `CONVENTIONS.md`. |

## Fix-List

| ID | Category | Description | File(s):line | Golden-path? | Eligible-in-phase | Status | Origin |
|----|----------|-------------|--------------|--------------|-------------------|--------|--------|
| FL-01 | exception | Bare `raise ValueError(...)` should become a typed domain exception (`PortfolioError` / `InsufficientFundsError` / `PortfolioNotFoundError` already exist in `core/exceptions/portfolio.py`); 7 sites. | `itrader/portfolio_handler/portfolio.py:101,103,124,183,410,431,436` | no | Phase 8 (Admission/Position/Cash — touches portfolio.py admission gates) | open | #7/#37 (CONCERNS.md Tech Debt — partial M3-03 exception migration) |
| FL-02 | annotation | `portfolio_id: int` annotation carry-over on Signal/Order/Fill event facts — annotation-only; runtime carries a UUID, so it is runtime-correct. 3 sites. | `itrader/events_handler/events/signal.py:84`, `itrader/events_handler/events/order.py:52`, `itrader/events_handler/events/fill.py:64` | yes (annotation-only; runtime carries UUID) | Phase 5 (HARD-03 retype) | open | #10 (CONCERNS.md — UUIDv7 annotation residual) |
| FL-03 | test-hygiene | Stale `pytest.skip("pending M2-07: FillStatus enum not added yet")` masks a now-passing FillStatus case-insensitive parse test (`FillStatus` was added in Phase 3 at `core/enums/execution.py:59`); the guarded assertions never run. | `tests/unit/core/test_enums.py:25-40` (skip at `:32`) | no | Phase 4 (E2E harness work touches the test tree) | open | CONCERNS.md (Known Bugs) |
| FL-04 | naming/seam | Stringly-typed `order_type: str = "market"` on the strategy base — should be an enum end-to-end. NOTE: this is HARD-03's core target in Phase 5, not a standalone Phase-1 fix. | `itrader/strategy_handler/base.py:27` (also `:38,:64`) | yes | Phase 5 (HARD-03 removes stringly-typed `order_type`) | open | CONVENTIONS.md / CONCERNS.md |
| FL-05 | seam | `PostgreSQLOrderStorage` is a `NotImplementedError` stub (live order persistence absent); off the backtest path. | `itrader/order_handler/storage/postgresql_storage.py` (all 57 lines stubs) | no | deferred → v1.3 (D-sql) | deferred | CONCERNS.md (Tech Debt) |
| FL-06 | seam | SQL table-name injection: `delete_all_tables` string-formats the symbol into DDL; `read_prices` passes raw `symbol` as the table name. RECORDED, not fixed in v1.1 (security item lives off the backtest path). | `itrader/price_handler/store/sql_store.py:35` (delete), `:~60` (`read_prices`) | no | deferred → v1.3 (D-sql) | deferred | CONCERNS.md (Known Bugs / Security) |
| FL-07 | seam | OANDA provider unfinished, carries untranslated Italian TODOs; ingestion not trustworthy at boundary conditions. | `itrader/price_handler/providers/oanda_provider.py:36,74` | no | deferred → with D-multiasset | deferred | CONCERNS.md (Tech Debt) |
| FL-08 | seam | `my_strategies/*` carry a repeated stranded `long_only` compliance TODO ("move to order_handler.compliance"); duplicated per strategy, off the reference path. | `itrader/strategy_handler/my_strategies/**` (5 files) | no | deferred → OUT (user-relocated) / v1.2 compliance | deferred | CONCERNS.md (Tech Debt) |
| FL-09 | seam | Stale screener/indicator TODOs (`volume_spyke` window-arg bug, `screeners/base.py` `to_timedelta` untested, `ehlers_indicators` "to be tested"). | `itrader/screeners_handler/screeners/volume_spyke.py:40`, `itrader/screeners_handler/screeners/base.py:29`, `itrader/strategy_handler/my_strategies/custom_indicators/ehlers_indicators.py:228` | no | deferred → v1.4 (D-screener) | deferred | CONCERNS.md (Tech Debt) |
| FL-10 | seam | Data-download providers have no retry / timeout / rate-limit backoff; transient failures bail rather than retry. | `itrader/price_handler/providers/ccxt_provider.py`, `itrader/price_handler/providers/oanda_provider.py` | no | deferred → v1.4 (D-live) | deferred | CONCERNS.md (Performance Bottlenecks) |
| FL-11 | seam | Binance live streamer `completed_bars` buffer accumulates without a bound (unbounded growth risk in long-running live sessions). | `itrader/price_handler/providers/binance_stream.py:176` | no | deferred → v1.4 (D-live) | deferred | CONCERNS.md (Fragile Areas) |
| FL-12 | visibility | Broad `except Exception` in domain logic — intentional/by-design (event loop must not stall; all sites log with context). Awareness-only: narrow to specific domain exceptions when a handler is edited. | `itrader/order_handler/order_manager.py` (8 sites), `itrader/portfolio_handler/portfolio_handler.py` (7 sites), `itrader/execution_handler/exchanges/simulated.py:155,316` | no | deferred → awareness-only (by-design per CLAUDE.md) | deferred | CONCERNS.md (Fragile Areas) |
| FL-13 | test-hygiene | Live system / `TradingInterface` have zero test coverage (largest untested critical surface); off the backtest path. | `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py` | no | deferred → v1.4 (D-live) | deferred | CONCERNS.md (Test Coverage Gaps / Fragile Areas) |
| FL-14 | seam | `pandas-ta 0.4.71b0` is a **beta** pin underpinning strategy filters / SLTP models; mild supply-chain/stability risk, isolated to non-reference strategy code. | `pyproject.toml` | no | deferred → isolated (non-reference strategy code) | deferred | CONCERNS.md (Dependencies at Risk) |

## Notes on honesty / non-padding

- **FL-01 / FL-02** are the only true carry-forward residuals (#7/#37, #10). They are MUST-include
  rows; their exact line numbers are re-verified against the current tree.
- **FL-03 / FL-04** are the only map-recorded concerns that fall on an *eligible* v1.1 path
  (the test tree in Phase 4; the strategy base `order_type` in Phase 5 / HARD-03).
- **FL-05 … FL-14** are RECORD-but-DEFER (Category C): real `CONCERNS.md` items, but on
  live / SQL / provider / `my_strategies` paths that no v1.1 phase touches. Each carries an owning
  milestone and Status `deferred`; none is planned for a v1.1 fix.
- The list is deliberately short. `CONVENTIONS.md` records the intended conventions with no
  violations in the current tree beyond the carry-forwards — the post-refactor naming surface is
  genuinely small. No invented items were added to inflate any category.
