---
status: deferred
created: "2026-07-01"
source: Phase 01 (v1.7) code review finding WR-01 — owner-deferred (tiziaco, 2026-07-01)
tags: [margin, equity, accounting, liquidation, frozen-golden, D-17, owner-gated, cross-validation, live-margin]
resolves_phase: ""
---

# Margin-mode `total_equity` / `margin_ratio` double-count the borrowed notional (WR-01)

**Origin:** Phase 01 (v1.7 Account Abstraction) code review,
`.planning/phases/01-account-abstraction-portfolio-handler-refactor/01-REVIEW.md` finding **WR-01**.
Owner decision 2026-07-01 (tiziaco): **defer to a tracked follow-up**, adjudicate before the live
margin/leverage path relies on margin equity. NOT fixed in Phase 1 (behavior-preserving,
backtest-correctness-scoped; margin spot-dark; spot oracle byte-exact 134 / 46189.87730727451 unaffected).

## The defect

`total_equity = account.balance + position_manager.get_total_market_value()`
(`portfolio.py:245-252`, `portfolio_handler.py:311-326`). Opening a leveraged long debits only
commission and *locks* margin — the full notional is never removed from `balance` — while
`Position.market_value` returns the **full** notional (`position.py:104-107`). So for a freshly opened
leveraged long, `total_equity ≈ cash + full_notional`, overstating true equity (`cash + unrealised_pnl`)
by the borrowed amount. `SimulatedMarginAccount.margin_ratio` (`simulated.py:836-854`) reads this
inflated equity, so it would never read a sub-1 margin-call value.

The futures-correct formula is `equity = wallet balance + unrealised PnL`. Shielded today only because
margin is spot-dark: the SMA_MACD oracle runs all-spot (where the formula degenerates to the correct
`cash + market_value`) and the actual liquidation engine uses `_isolated_liq_price` against bar close,
not `margin_ratio`.

## Why it cannot be auto-fixed (the real cost)

The reviewer's recommended fix (gate on `enable_margin`: spot arm stays byte-exact `cash + market_value`,
margin arm switches to `cash + Σ unrealised PnL`) was applied, verified (oracle + mypy green, margin unit
test passing), then **rolled back** because it **breaks 6 owner-approved FROZEN accounting-core goldens**
(D-17, "Approved-by: tiziaco, 2026-06-16") that hand-assert open-position margin equity as
`balance + market_value`:

- `tests/e2e/levered_long/test_levered_long_scenario.py`
- `tests/e2e/partial_cover/test_partial_cover_scenario.py`
- `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py`
- `tests/e2e/short_scale_in/test_short_scale_in_scenario.py`
- `tests/e2e/short_scale_in_partial_cover/test_short_scale_in_partial_cover_scenario.py`
- `tests/integration/test_pair_flagship_snapshot.py`

E.g. `levered_long` asserts `equity == 30000` at fill (`10000 + 200*100`) and `28000` on the adverse mark;
the corrected formula yields `10000` / `8000` (cash + unrealised), the delta being exactly the borrowed
notional — confirming the reviewer's arithmetic.

## The cross-validation gap (decision-critical)

The disputed open-position values were **never externally cross-validated**.
`tests/golden/CROSS-VALIDATION-ACCOUNTING.md` only corroborates **final / flat** equity (14000, agreed by
backtesting.py + backtrader). The open-position 30000 / 28000 figures are **iTrader-internal hand-computation
only** — so "frozen" here does not mean "oracle-backed."

## What to do when promoted (before live margin relies on equity)

1. Decide the canonical open-position margin-equity formula (recommend futures-correct `cash + Σ unrealised PnL`).
2. Apply the code fix gated on `enable_margin` so the spot arm stays byte-exact.
3. Add a margin-mode unit test asserting equity ≈ cash immediately after a leveraged open.
4. **Correct + re-freeze the 6 goldens above with owner (tiziaco) sign-off.**
5. Ideally refresh `CROSS-VALIDATION-ACCOUNTING.md` so open-position equity is oracle-backed, not hand-computed.

Full design context: `.planning/notes/margin-leverage-shorts-999.4.md` §9 item 6.
