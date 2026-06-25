# Phase 8 Plan 04 — D-03 Attribution Gate (per-win same-machine A/B)

**Date:** 2026-06-25
**Box:** main checkout, branch `v1.5/phase-8-hot-path-improvments`, in-project `.venv` (editable install).
**Method (per `08-MSGSPEC-SPIKE-FINDINGS.md` "Gate B" + memory `v15-perf-gateb-thermal-drift`):**
verified-cool box, **position-balanced 8-run** sequence `OPT BASE BASE OPT OPT BASE BASE OPT`
(each variant mean run-position 4.5 — cancels monotonic thermal drift), **fresh interpreter per run**,
**one discarded warmup**. Each win isolated by swapping its SINGLE production file between OPT (the win
commit's version, identical to HEAD) and BASE (the win commit's parent), holding every other file at HEAD.
**Only the same-session OPT-vs-BASE delta is trusted — NEVER the frozen-baseline compare.**
Δ sign convention: **+ = OPT faster** (good); **− = OPT slower** (regression).

> NOTE: absolute wall-clocks here (W1 ~23–29 s, W2@50 ~5 s) run warmer than the frozen v1.5-final
> reference (W1 28.3 s) — irrelevant by design. Only the within-session OPT/BASE separation is read.

## Thermal evidence (T-08-07 mitigation)

`pmset -g therm` — **no thermal/perf/CPU-power warning recorded** at all three checkpoints:

| Checkpoint | Result |
|---|---|
| BEFORE W1 A/B | clean (no thermal/perf warning) |
| AFTER W1 A/B / BEFORE W2 A/B | clean (no thermal/perf warning) |
| AFTER W2 A/B | clean (no thermal/perf warning) |

Box stayed cool for the entire attribution session.

## Win → commit map

| Req | Win | OPT commit | BASE (= OPT^) | Production file | W2-sensitive? |
|---|---|---|---|---|---|
| 1 | Hot-path valuation fusion | `48da911` | `277c2f6` | `itrader/portfolio_handler/position/position_manager.py` | yes (position axis) |
| 2 | Position net_qty/avg_price cache | `57a7fe3` | `cf0f56d` | `itrader/portfolio_handler/position/position.py` | no |
| 3 | itertuples Bar prebuild | `1419a8e` | `121a15a` | `itrader/price_handler/feed/bar_feed.py` | yes (symbol axis) |
| 4 | Per-instance to_dict cache | `d81f9a5` | `1419a8e` | `itrader/strategy_handler/base.py` | no |
| 5 | `_aligned` alignment audit | (test-only `84974e6`) | — | (no production code) | n/a |

> Req 4's BASE is Req 3's win commit (`1419a8e`); that isolates Req 4 ALONE (the only file that changes
> between BASE and OPT is `base.py`). Req 5 added NO production code (audit + equivalence test only,
> keep-only-measured already satisfied by construction) — nothing to A/B.

---

## W1 A/B (THE gate — `make perf-w1`, 4 sym / 6 pf / 2-month 5m)

Raw runs (wall_clock_s), warmup discarded:

| Req | RUN1 | RUN2 | RUN3 | RUN4 | RUN5 | RUN6 | RUN7 | RUN8 |
|---|---|---|---|---|---|---|---|---|
| | OPT | BASE | BASE | OPT | OPT | BASE | BASE | OPT |
| 1 fusion | 26.672 | 23.241 | 23.309 | 26.780 | 27.156 | 23.872 | 23.403 | 27.326 |
| 2 poscache | 26.410 | 31.140 | 30.973 | 26.927 | 27.055 | 32.672 | 31.153 | 26.659 |
| 3 itertuples | 28.524 | 28.874 | 28.654 | 28.621 | 28.592 | 28.623 | 28.738 | 28.406 |
| 4 to_dict | 29.120 | 29.198 | 29.488 | 28.617 | 28.641 | 29.244 | 29.486 | 28.596 |

W1 deltas:

| Req | OPT mean (s) | BASE mean (s) | Δ% (OPT faster if +) | Separation | Verdict |
|---|---|---|---|---|---|
| 1 fusion | 26.983 | 23.456 | **−15.04%** | **ALL OPT > ALL BASE** | **REGRESSION** |
| 2 poscache | 26.763 | 31.484 | **+15.00%** | ALL OPT < ALL BASE | **ATTRIBUTABLE** |
| 3 itertuples | 28.536 | 28.722 | +0.65% | all OPT < all BASE (tiny) | borderline → see W2 |
| 4 to_dict | 28.744 | 29.354 | **+2.08%** | ALL OPT < ALL BASE | **ATTRIBUTABLE (small)** |

## W2 @50 A/B (scaling-axis corroboration — `make perf-w2`, n_symbols=50, 3000 bars)

Only the two W2-sensitive wins (Req 1 fusion, Req 3 prebuild). Raw runs (wall_clock_s @50), warmup discarded:

| Req | RUN1 | RUN2 | RUN3 | RUN4 | RUN5 | RUN6 | RUN7 | RUN8 |
|---|---|---|---|---|---|---|---|---|
| | OPT | BASE | BASE | OPT | OPT | BASE | BASE | OPT |
| 1 fusion | 5.122 | 4.795 | 5.111 | 5.167 | 5.163 | 4.883 | 4.818 | 5.137 |
| 3 itertuples | 5.117 | 5.147 | 5.082 | 5.083 | 5.425 | 5.112 | 5.118 | 5.127 |

W2 @50 deltas:

| Req | OPT mean (s) | BASE mean (s) | Δ% (OPT faster if +) | Separation | Verdict |
|---|---|---|---|---|---|
| 1 fusion | 5.147 | 4.902 | **−5.01%** | ALL OPT > ALL BASE | **REGRESSION (both axes)** |
| 3 itertuples | 5.188 | 5.115 | −1.43% | **OVERLAP** | **NOISE** |

---

## Mechanism corroboration (the "why")

### Req 1 fusion — a real regression, not noise (mechanism-explained)
The "fusion" commit (`48da911`) did NOT remove a loop. Both `get_total_market_value` and
`get_total_unrealized_pnl` still call `_fused_valuation()`, so the loop runs **once per accessor
(twice per bar)** — exactly as before. Worse, the fused loop ALSO computes
`total_basis += position.aggregate_notional` for every position every bar, and **both callers discard
that third component** (`_total_basis` is unpacked-and-thrown-away). `aggregate_notional` is a computed
property (`net_quantity × avg_price`, Decimal math per position). Net effect: the same two passes PLUS a
new per-position per-bar Decimal computation that nothing consumes → strictly MORE work. This is precisely
the per-bar Decimal arithmetic the W1/W2 deltas measure: **−15% W1 / −5% W2@50, perfect OPT/BASE
separation on both axes.** The original 08-01 SUMMARY claimed a fusion "win" but never measured wall-clock
— this gate is why keep-only-measured exists.

### Req 3 itertuples — noise
`bar_feed.py` builds the `{ts: Bar}` prebuild **once at wiring** (not per tick), so it never touches the
timed hot loop on either workload. W1 +0.65% (inside run-to-run noise despite the small ordering) and
**W2@50 distributions OVERLAP (−1.43%)** → no attributable contribution. The construction change is
byte-exact but performance-inert on the measured workloads.

### Req 2 poscache & Req 4 to_dict — attributable
Req 2 caches `net_quantity`/`avg_price` (read every bar via `market_value`/`unrealised_pnl`) →
**clean +15% W1, every OPT run beats every BASE run.** Req 4 caches the per-instance `to_dict` static
snapshot → **+2.08% W1, clean separation** (smaller, but consistent and one-directional). Both are real.

> Scalene `perf-profile` was available but NOT needed for attribution here: the W1/W2 same-machine deltas
> already give clean directional separation for every kept/reverted decision, and the Req-1 regression has
> an exact code-level mechanism (the discarded `aggregate_notional` term) that does not require a profile to
> confirm. (Per the plan, Scalene is the corroboration mechanism "where individual per-win isolation is
> impractical" — here per-win isolation was fully practical via single-file swaps.)

---

## Keep / Revert decisions (D-02 keep-only-measured)

> **D-02 carve-out scope:** the do-NOT-revert-for-noise carve-out applies ONLY to the **msgspec extra DTOs
> in plan 08-05**. The five deterministic wins (Reqs 1–5) here ARE subject to keep-only-measured. This
> table does not contradict 08-05.

| Req | Win | Verdict | Action | Rationale |
|---|---|---|---|---|
| 1 | valuation fusion | **REGRESSION** | **REVERTED** | −15% W1 / −5% W2@50, clean separation both axes; mechanism = discarded per-bar `aggregate_notional` Decimal term + still-two-pass. A win that makes the engine slower must not ship. |
| 2 | Position cache | **ATTRIBUTABLE** | **KEPT** | +15% W1, every OPT < every BASE. Real, byte-exact. |
| 3 | itertuples prebuild | **NOISE** | **REVERTED** | W1 +0.65% (noise), W2@50 OVERLAP. Wiring-time build, never in the hot loop → no measurable contribution. |
| 4 | to_dict cache | **ATTRIBUTABLE** | **KEPT** | +2.08% W1, clean one-directional separation. Small but real. |
| 5 | `_aligned` audit | **n/a (no prod code)** | **KEPT (as-is)** | Test-only audit; keep-only-measured satisfied by construction (no new cache was added — the int64-ns grid lever was correctly NOT pre-added). Nothing to revert. |

### Reverts applied
- **Req 1 fusion** — `position_manager.py` restored to pre-fusion (`48da911^`): two separate single-purpose
  passes; `_fused_valuation` removed. Removed the win's 4 dedicated `test_fusion_*` tests + their
  `_build_mixed_positions` helper from `tests/unit/portfolio/test_position_manager.py` (they reference the
  removed `_fused_valuation`; no standalone value once the method is gone — the per-accessor sums are
  already covered by the existing position-manager tests, 32 passing).
- **Req 3 itertuples** — `bar_feed.py` restored to pre-prebuild (`1419a8e^`): `frame.iterrows()` +
  `Bar.from_row` build. Deleted `tests/unit/price/test_bar_prebuild_equivalence.py` (it pinned the
  itertuples build; with the build reverted to iterrows the equivalence test compares iterrows-to-iterrows
  — vacuous).

> No external code depends on `_fused_valuation` or the itertuples build (grep-confirmed: 0 hits outside
> the reverted files and their tests). The reverts are self-contained.

## Gate (a) byte-exact on the KEPT set (after reverts)

| Check | Result |
|---|---|
| `poetry run pytest tests/integration/test_backtest_oracle.py` | **3 passed** — **134 trades / 46189.87730727451** (byte-exact + behavioral identity + determinism double-run) |
| `poetry run mypy` (strict, configured) | **Success: no issues found in 188 source files** |
| Affected unit suites (position_manager, price feed, to_dict, position cache) | **80 passed** |
| Full test collection | **1337 collected, 0 errors** (the removed prebuild test no longer collected) |

The kept set (Req 2 + Req 4 + Req 5-audit) is gate-(a) byte-exact. The engine to be re-frozen is the
SHIPPED engine, not a reverted one.

---

## Owner sign-off — PENDING (blocking checkpoint)

Claude has automated all attribution + revert decisions. The owner-gated re-freeze + sign-off remains:

1. Confirm the box is still cool (`pmset -g therm` clean).
2. Re-freeze the cool W1 baseline: `make perf-baseline` → writes `perf/results/W1-BASELINE.json`
   (the NEW locked reference the msgspec A/B in 08-05 is measured against).
3. Re-freeze the cool W2 baseline: `make perf-w2-baseline` → writes `perf/results/W2-BASELINE.json`.
4. Confirm the regression guard passes against the new baseline: `make perf-w1 --check`.
5. Confirm gate (a) byte-exact: `poetry run pytest tests/integration/test_backtest_oracle.py`
   (134 / 46189.87730727451).
6. Record owner sign-off (attribution, as in quick `260625-0qj`).

> Per the executor mandate: `make perf-baseline` / `make perf-w2-baseline` are the OWNER-GATED re-freeze,
> NOT run by Claude. STATE.md / ROADMAP.md NOT modified; 08-04-SUMMARY.md NOT yet created — the plan is not
> complete until after sign-off + re-freeze.

**Owner sign-off:** _PENDING_
**Signed by:** _______________  **Date:** _______________
**New locked W1:** _______ s / _______ MB   **New locked W2@50:** _______ s / _______ MB
