---
type: execution-finding
phase: 06-bar-feed-window-copies-optional-slip-able
created: 2026-06-24
status: open
blocks: gate-b
feeds: next-plan (incremental-cursor window())
---

# Phase 06 — Gate (b) measurement + profile finding

**TL;DR:** 06-01 (read-only window view + memoized `_offset_alias` + read-only master
frames) is **correct and safe** but delivers **no measurable W2 wall-clock win** (~0%, within
noise). Gate (b)'s ≥10% W2 requirement is **not met and not reachable by 06-01's levers**. The
profile pinpoints the real PERF-06 hotspot: the **per-tick `searchsorted` + `iloc` window slice
(~26% of W2 CPU)**, which 06-01 never touched. Recommended next step: a planned
**monotonic incremental-cursor `window()`** that replaces the per-tick `searchsorted`.

## Gate (a) — held (unchanged by this finding)
- `tests/integration/test_backtest_oracle.py`: **134 trades / final_equity 46189.87730727451**, determinism double-run identical.
- Full suite **1258 passed** under `poetry run pytest tests/`; `mypy --strict` clean.
- NOTE: `make test` shows ONE failure (`test_warn_on_mid_life_gap`) — a **pre-existing** local
  `.env` artifact (`ITRADER_DISABLE_LOGS=true` / `ITRADER_LOG_LEVEL=ERROR` exported by `make`
  suppress the asserted WARNING). Reproduces identically at clean base 2fe879b. Not a regression.

## Gate (b) — A/B measurement (same-session, thermal-controlled)
Runner: `perf/runners/run_w2_sweep.py` (50-symbol point, n_bars=3000, seed=42). Single variable:
`itrader/price_handler/feed/bar_feed.py` (OPT=06-01 `9168cae` vs BASE=`2fe879b`). Runner held constant.

| Round (order) | OPT 50-sym | BASE 50-sym | Δ |
|---|---|---|---|
| R1 (BASE→OPT) | 49.79s | 50.69s | +1.8% |
| R2 (OPT→BASE) | 50.39s | 49.91s | −0.96% |
| **Position-averaged** | **50.09s** | **50.30s** | **+0.41%** |

- Reversed round R2 cancels position/thermal bias → **not** the `v15-perf-gateb` throttling artifact (box held 97–98% CPU).
- Run-to-run variance (~1–1.5%) swamps the signal. Peak memory essentially unchanged (214.6 vs 215.0 MB) — the per-tick copies were short-lived.
- `--check` against the BASE-frozen baseline printed `improvement +1.8% < required 10.0% — gate (b) FAILED`.

## Scalene CPU profile (W2 sweep, `--cpu-only --program-path`)
bar_feed.py CPU **share is flat**: **BASE 28.58% → OPT 29.71%** (06-01 did not reduce it).

OPT line-level (share of total program CPU):
- L473 `pos = frame.index.searchsorted(cutoff, side="right")` — **13.2%**  ← the hotspot
- L486 `return frame.iloc[start:pos]` (slice) — **7.9%**
- L474 `start = max(0, pos - max_window)` — **5.3%**
- L470 `_offset_alias(timeframe)` — **0.04%**  ← 06-01 memoization worked; was never expensive
- `.copy()` removal — marginal (the slice cost is the `iloc`, not the copy)

Other big W2 frames (context for future phases, OUT of PERF-06 scope):
- `logger.py` per-bar logging — **~22%** (untouched)
- `run_w2_sweep.py` harness (tracemalloc + synthetic-gen) — **~19%** measurement overhead diluting the sweep denominator
- `strategy_handler/base.py` — ~9%

## Why 06-01 missed
The "~22% bar-feed hotspot" that motivated PERF-06 was a profiler **CPU-share** of the bar-feed
frames. 06-01 attacked the *reducible-looking* sub-parts (alias string compute, slice copy) which
turned out to be **negligible** (<0.1% + marginal). The dominant, inherent cost — a fresh
`searchsorted` over the full frame index **every tick × every symbol** (50 × 3000 = 150k calls) —
was left in place.

## Recommended next plan — monotonic incremental cursor
In a backtest the `asof` cutoff advances **monotonically** per (ticker, timeframe). Replace the
per-tick `searchsorted(cutoff)` with a cached cursor that only steps forward from the last
position. Expected to remove most of the ~13% searchsorted + reduce the slice path → plausibly
≥10% W2.

Must be planned (not bolted on) because it touches look-ahead safety:
- Preserve the **7-rule bar-timing contract** (`bar_feed.py`) and the D-08 drift lock byte-for-byte.
- Cursor must be per-(ticker, timeframe), reset/seek-safe (screener membership changes, sparse/gap
  frames per D-04), and must NOT leak a future bar (cutoff is exclusive-right today).
- Keep the 06-01 read-only-view guarantee on the returned slice.
- Re-validate Gate (a) byte-exact + the `--check` ≥10% gate on a cool machine.

## State of committed work (kept)
- `9168cae` 06-01 feat (read-only view + alias memo) — **complete, SUMMARY written**. Keep: it is a real safety improvement (look-ahead enforcement), just not a perf win.
- `f51d7c6` 06-02 Task 1 — `run_w2_sweep.py --baseline-out/--check` + Makefile `perf-w2`/`perf-w2-baseline`. **Reusable** — the gate harness is correct; it simply has no ≥10% win to certify yet.
- **No W2-BASELINE.json frozen** (correct — nothing to freeze until the cursor fix lands).
- 06-02 Task 2/3 (cool-machine freeze + SUMMARY) **deferred** behind the cursor fix.
