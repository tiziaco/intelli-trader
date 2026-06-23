---
phase: quick-260623-bmg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - perf/strategies/b_limit_maker.py
  - perf/strategies/c_pyramiding_trend.py
  - perf/strategies/d_short_zscore.py
autonomous: true
requirements: [PERF-COVERAGE-DENSITY]

must_haves:
  truths:
    - "Strategy B (P2_B) closes >0 positions over the verification slice (limit-maker longs recycle)"
    - "Strategy C (P3_C) closes >0 positions over the verification slice (pyramided long takes profit and frees cash)"
    - "Strategy D (P4_D/P5_D/P6_D) each close >0 positions over the verification slice (short covers and re-shorts)"
    - "Total W1 fills over the slice are materially higher than the 3/3/1/1/1 baseline"
    - "Each instrument's coverage SEMANTICS/docstring intent are unchanged — only an exit leg is added"
  artifacts:
    - path: "perf/strategies/b_limit_maker.py"
      provides: "buy_limit now carries both sl (below) and tp (above) so the long recycles"
      contains: "_SL_BELOW"
    - path: "perf/strategies/c_pyramiding_trend.py"
      provides: "buy now carries both sl (below) and tp (above) so the pyramided long takes profit"
      contains: "_TP_PCT"
    - path: "perf/strategies/d_short_zscore.py"
      provides: "sell now carries a tp (below entry) + sl (above entry) bracket so the short covers and re-shorts"
      contains: "_TP_BELOW"
  key_links:
    - from: "perf/strategies/d_short_zscore.py"
      to: "Strategy.sell"
      via: "self.sell(ticker, sl=..., tp=...)"
      pattern: "self\\.sell\\(ticker, .*tp="
    - from: "perf/strategies/b_limit_maker.py"
      to: "Strategy.buy_limit"
      via: "self.buy_limit(ticker, price=..., sl=..., tp=...)"
      pattern: "sl=sl"
    - from: "perf/strategies/c_pyramiding_trend.py"
      to: "Strategy.buy"
      via: "self.buy(ticker, sl=..., tp=...)"
      pattern: "tp=tp"
---

<objective>
The three W1 coverage instruments B, C, and D each open positions but have NO working
EXIT leg, so positions never close, `max_positions` is hit almost immediately, and
trade density collapses (empirically: P2_B 3 fills / 0 closed, P3_C 3 fills / 0 closed,
P4/P5/P6_D 1 fill / 0 closed each). These are coverage instruments whose whole purpose
is trade DENSITY to saturate engine paths — tight exits are CORRECT here. Add the missing
exit leg to each so positions recycle (close → free a slot → re-enter), boosting density.

Purpose: restore the trade-density these coverage instruments are supposed to generate so
the W1 benchmark exercises the engine paths it claims to own (resting-limit recycling,
pyramiding + re-accumulation, short-side admission + fan-out fired repeatedly).
Output: three edited strategy files (exit leg added, semantics unchanged) + a slice
verification proving closed_positions > 0 for B, C, and all three D portfolios.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@./CLAUDE.md
@perf/README.md
@perf/strategies/b_limit_maker.py
@perf/strategies/c_pyramiding_trend.py
@perf/strategies/d_short_zscore.py
@perf/runners/run_w1_benchmark.py
@perf/workloads/w1_topology.py

<interfaces>
<!-- Confirmed from itrader/strategy_handler/base.py — executor needs no exploration. -->

`buy`/`sell`/`buy_limit` all accept sl/tp as absolute prices, `float | Decimal | None`,
entering the Decimal domain via `to_money` (passing Decimal is correct; NEVER Decimal(float)):

```python
def buy(self, ticker, sl=None, tp=None, exit_fraction=Decimal("1")) -> SignalIntent: ...
def sell(self, ticker, sl=None, tp=None, exit_fraction=Decimal("1")) -> SignalIntent: ...
def buy_limit(self, ticker, *, price, sl=None, tp=None, exit_fraction=Decimal("1")) -> SignalIntent: ...
```

Long semantics (B, C): tp ABOVE entry (sell to take profit), sl BELOW entry (sell to stop loss).
Short semantics (D): tp BELOW entry (buy-to-cover in profit when price falls), sl ABOVE entry
(buy-to-cover the loss when price rises).

Current state of each call (the gap):
- B `b_limit_maker.py`: `buy_limit(ticker, price=limit_price, tp=tp)` — tp 1% above limit, NO sl.
- C `c_pyramiding_trend.py`: `buy(ticker, sl=sl)` — sl 3% below close, NO tp.
- D `d_short_zscore.py`: `sell(ticker)` — NO sl/tp at all.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add the recycling exit leg to coverage instruments B, C, D</name>
  <files>perf/strategies/b_limit_maker.py, perf/strategies/c_pyramiding_trend.py, perf/strategies/d_short_zscore.py</files>
  <action>
Add the missing exit leg to each of the three coverage instruments so positions recycle
(close → free a `max_positions` slot → re-enter), boosting trade density. 4-SPACE
indentation throughout (perf/ convention); build all sl/tp as Decimal off the existing
`close`/`limit_price` Decimals (NEVER Decimal(float) — the files already use
`Decimal(str(...))` / Decimal literals). Keep every numeric exit value as a tunable
module-level constant with an explanatory comment, in the existing decision-anchored
comment style. Do NOT change the coverage SEMANTICS or docstring INTENT of any instrument
(B = resting-limit book + cancel/modify via runner on_tick; C = pyramiding/averaging +
insufficient-funds rejections; D = short-side admission + 3-portfolio fan-out + rejections)
— only ADD the exit. Update each module's docstring/comments to note the added exit leg and
WHY (tight exits → recycling → density).

B — `perf/strategies/b_limit_maker.py`:
- Tighten `_TP_ABOVE` from `Decimal("0.01")` to `Decimal("0.005")` (take profit ~0.5% above
  the limit) and add a new module-level `_SL_BELOW = Decimal("0.01")` constant in the SAME
  style next to `_TP_ABOVE` (stop ~1% below the limit).
- In `generate_signal`, after computing `limit_price` and `tp`, compute
  `sl = limit_price * (Decimal("1") - _SL_BELOW)` and pass it:
  `return self.buy_limit(ticker, price=limit_price, sl=sl, tp=tp)`.
- Note in the comment/docstring that the long now recycles (tight tp/sl) instead of resting
  forever, which keeps the resting-limit book churning — more density, same coverage.

C — `perf/strategies/c_pyramiding_trend.py`:
- Add a new module-level `_TP_PCT = Decimal("0.02")` constant next to `_SL_PCT` (take profit
  ~2% above the latest add).
- In `generate_signal`, after computing `sl`, compute
  `tp = Decimal(str(close)) * (Decimal("1") + _TP_PCT)` and pass it:
  `return self.buy(ticker, sl=sl, tp=tp)`.
- Note in the comment/docstring that the pyramided long now takes profit, closes, and frees
  cash to re-accumulate — keeping the repeated-admission / averaging / CASH-rejection paths
  firing across multiple cycles instead of one stuck position.

D — `perf/strategies/d_short_zscore.py`:
- Add two module-level constants next to `_Z_ENTRY`, same style:
  `_TP_BELOW = Decimal("0.01")` (cover ~1% BELOW entry — short profit when price falls) and
  `_SL_ABOVE = Decimal("0.015")` (cover ~1.5% ABOVE entry — stop when price rises).
- In `generate_signal`, the z-score reads `closes` as floats; build the exit prices as
  Decimal off the current close: `close_d = Decimal(str(close))`,
  `tp = close_d * (Decimal("1") - _TP_BELOW)`, `sl = close_d * (Decimal("1") + _SL_ABOVE)`,
  then `return self.sell(ticker, sl=sl, tp=tp)`.
- Note in the comment/docstring that the short now COVERS (tp below / sl above for a SHORT)
  and re-shorts repeatedly — exercising short-side admission + fan-out + rejections many
  times per portfolio instead of opening one short and capping at `max_positions`.
  </action>
  <verify>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader && grep -n 'sl=sl' perf/strategies/b_limit_maker.py && grep -n 'tp=tp' perf/strategies/c_pyramiding_trend.py && grep -nE 'self\.sell\(ticker, .*tp=' perf/strategies/d_short_zscore.py && grep -nq '_SL_BELOW' perf/strategies/b_limit_maker.py && grep -nq '_TP_PCT' perf/strategies/c_pyramiding_trend.py && grep -nq '_TP_BELOW' perf/strategies/d_short_zscore.py && PYTHONPATH="$PWD" poetry run python -c "import perf.strategies.b_limit_maker, perf.strategies.c_pyramiding_trend, perf.strategies.d_short_zscore; print('import OK')"</automated>
  </verify>
  <done>
All three calls carry both an entry AND an exit leg (B: buy_limit with sl+tp; C: buy with
sl+tp; D: sell with sl+tp), the new tunable constants (_SL_BELOW / _TP_PCT / _TP_BELOW+_SL_ABOVE)
exist with explanatory comments, the three modules import cleanly, indentation is 4-space, and
no Decimal(float) was introduced. Each docstring/comment notes the added exit and the
recycling-for-density rationale; coverage semantics/intent are unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 2: Verify density jumped on the 30-day slice</name>
  <files>(throwaway verification script — not committed)</files>
  <action>
Re-run the W1 topology on the SAME ~30-day slice used in the diagnosis (start_date
2025-12-24, end_date 2026-01-24) and confirm density jumped. Do NOT permanently change the
runner's full-window `_START_DATE`/`_END_DATE` (the 180-day window is the durable artifact).

Write a small THROWAWAY script under the scratchpad directory
(`/private/tmp/claude-501/-Users-tizianoiacovelli-Desktop-projects-intelli-trader/66004239-46a9-4a1d-b489-2fb451838f38/scratchpad/verify_slice.py`)
that mirrors `perf/runners/run_w1_benchmark.py::run_w1` but pins the slice dates:
- construct `BacktestTradingSystem(exchange="csv", csv_paths=CSV_PATHS, start_date="2025-12-24",
  end_date="2026-01-24", timeframe=TIMEFRAME)` (import from `perf.workloads.w1_topology`),
- `topo = wire_w1(system)`, build the on_tick via the runner's `_make_on_tick(system, topo)`
  (import it) so Strategy B's cancel/modify lifecycle still drives,
- `system.run(print_summary=False, on_tick=on_tick)`,
- print the per-portfolio (fills / open / closed) table for the six labels
  ["P1_A","P2_B","P3_C","P4_D","P5_D","P6_D"] — read fills via `len(portfolio.transactions)`,
  closed via `len(portfolio.closed_positions)`, and open via `portfolio.open_positions`
  (use the same accessor shape the runner uses; if `open` is not directly available, derive
  open count from the portfolio's open-positions collection — confirm the attr name against
  the Portfolio object at run time, do NOT guess silently).

Run it from the MAIN checkout (project memory: `make test` aborts on missing .env inside
worktrees — prefer `PYTHONPATH="$PWD" poetry run python ...` directly):
`PYTHONPATH="$PWD" poetry run python <scratchpad>/verify_slice.py`

Confirm the density gate: closed_positions > 0 for P2_B, P3_C, AND each of P4_D / P5_D / P6_D,
and total fills materially higher than the 3/3/1/1/1 baseline (i.e. well above ~11 total).
Report the full per-portfolio table in the task result. The full unchanged 180-day
`run_w1_benchmark.py` run is NOT required (it is slow) — the slice is the gate.
  </action>
  <verify>
    <human-check>Throwaway slice script ran via PYTHONPATH="$PWD" poetry run python; per-portfolio table reported; closed_positions > 0 for P2_B, P3_C, P4_D, P5_D, P6_D; total fills materially above the 3/3/1/1/1 baseline.</human-check>
  </verify>
  <done>
The slice re-run printed a per-portfolio (fills / open / closed) table; B, C, and all three D
portfolios each show closed_positions > 0; total fills are materially higher than baseline.
The runner's `_START_DATE`/`_END_DATE` remain the full 180-day window (untouched). The
throwaway script is NOT committed.
  </done>
</task>

</tasks>

<verification>
- `grep` confirms each of the three calls now passes both an entry and an exit leg, and the
  new tunable constants exist.
- The three modules import cleanly under `PYTHONPATH="$PWD" poetry run python`.
- The slice re-run shows closed_positions > 0 for P2_B, P3_C, P4_D, P5_D, P6_D and total fills
  materially above the 3/3/1/1/1 baseline.
- No Decimal(float) introduced; 4-space indentation preserved; coverage docstrings/intent
  unchanged (only the exit leg added).
</verification>

<success_criteria>
Positions recycle for all three coverage instruments: each opens, hits its tight exit, closes,
frees a `max_positions` slot, and re-enters — driving W1 trade density well above the dead
3/3/1/1/1 baseline, with B/C/D all reporting closed_positions > 0 on the verification slice.
The runner's durable full-window dates are unchanged.
</success_criteria>

<output>
Create `.planning/quick/260623-bmg-fix-perf-coverage-instruments-b-c-d-so-p/260623-bmg-SUMMARY.md` when done
</output>
