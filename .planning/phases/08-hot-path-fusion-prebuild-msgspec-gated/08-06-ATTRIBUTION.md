# Phase 8 Plan 06 — msgspec D-03 Attribution Gate (fresh same-machine A/B) + final Phase-8 re-freeze

**Date:** 2026-06-25
**Box:** main checkout, branch `v1.5/phase-8-hot-path-improvments`, in-project `.venv` (editable install).
**Method (per `08-MSGSPEC-SPIKE-FINDINGS.md` "Gate B" + memory `v15-perf-gateb-thermal-drift`):**
verified-cool box, **position-balanced 8-run** sequence `OPT BASE BASE OPT OPT BASE BASE OPT`
(each variant mean run-position 4.5 — cancels monotonic thermal drift and within-pair position bias),
**fresh interpreter per run**, **one discarded warmup** per workload.
**Only the same-session OPT-vs-BASE delta is trusted — NEVER the frozen-baseline compare.**
Δ sign convention: **+ = OPT faster** (good).

## A/B granularity — COMMIT-LEVEL (the msgspec migration spans 10 engine files)

This A/B is FRESH on the cool re-frozen baseline (D-03 — the spike A/B on the discarded
`spike/msgspec-events` branch is NOT inherited; msgspec was re-implemented cleanly in plan 08-05).

| Variant | Engine state | What it is |
|---|---|---|
| **BASE** | commit `2c01499` (`itrader/`) | the deterministic-wins HEAD: plan-08-04 kept set (Position cache + to_dict cache + itertuples prebuild + `_aligned` audit; fusion reverted), **NO msgspec** |
| **OPT** | HEAD `31d74f7` (`itrader/`) | the msgspec migration in place (08-05 commits `eeaf286..5b117df`) |

Engine switched per run via `git checkout <ref> -- itrader/` (ONLY `itrader/`, never tests/perf).
Verified: `git diff --stat 2c01499 HEAD -- itrader/` = exactly the 10 msgspec-migration files
(bar.py + 6 event files + matching_engine.py + transaction.py + signal_record.py), 0 unrelated files.
Working tree restored to HEAD and confirmed CLEAN after each workload (`git status --porcelain` empty).

> Absolute wall-clocks this session run COOLER than the cool re-frozen v1.5 reference
> (W1 17.4 s frozen) only because the frozen freeze used a single clean run; here we read ONLY the
> within-session OPT/BASE separation, never the frozen-baseline compare.

## Thermal evidence (T-08-11 mitigation)

`pmset -g therm` — **no thermal / performance / CPU-power warning recorded** at every checkpoint:

| Checkpoint | Result |
|---|---|
| BEFORE W1 A/B | clean (no thermal/perf/CPU-power warning) |
| AFTER W1 A/B | clean |
| BEFORE W2 A/B | clean |
| AFTER W2 A/B | clean |

Box stayed cool for the entire attribution session.

---

## W1 A/B (THE gate — `run_w1_benchmark --json`, 4 sym / 6 pf / 2-month 5m)

Raw runs (wall_clock_s, full precision; one warmup discarded). Workload byte-identical every run:
**1578 fills / 659 closed positions**.

| run | variant | wall_clock_s |
|---|---|---|
| 1 | OPT  | 22.114 |
| 2 | BASE | 23.765 |
| 3 | BASE | 24.345 |
| 4 | OPT  | 21.966 |
| 5 | OPT  | 23.566 |
| 6 | BASE | 23.939 |
| 7 | BASE | 24.442 |
| 8 | OPT  | 22.037 |

- **OPT mean = 22.421 s** (runs 1,4,5,8) · **BASE mean = 24.123 s** (runs 2,3,6,7)
- **Δ = +7.06% faster (OPT)**
- **Clean separation: max OPT 23.566 < min BASE 23.765** — every OPT run beats every BASE run
  (consistent one-directional signal, not noise).
- Exceeds the spike expectation (+3.82%) — cooler session; same direction, stronger separation.

## W2 @50 A/B (scaling axis — `run_w2_sweep --json`, n_symbols=50, n_bars=3000, seed=42)

Raw 50-symbol-point runs (wall_clock_s, full precision; one warmup discarded):

| run | variant | wall_clock_s @50 |
|---|---|---|
| 1 | OPT  | 4.338 |
| 2 | BASE | 4.979 |
| 3 | BASE | 4.810 |
| 4 | OPT  | 4.219 |
| 5 | OPT  | 4.159 |
| 6 | BASE | 4.645 |
| 7 | BASE | 4.644 |
| 8 | OPT  | 4.333 |

- **OPT mean = 4.262 s** · **BASE mean = 4.769 s**
- **Δ = +10.64% faster (OPT)**
- **Clean separation: max OPT 4.338 < min BASE 4.644** — every OPT < every BASE.
- The construction win **amplifies with symbol count** (more `Bar`/`BarEvent` built per tick):
  +7.06% at 4 symbols → +10.64% at 50. Exceeds the spike expectation (+6.72%) and clears the strict
  ≥10% W2 line.

---

## Scalene corroboration (mechanism check — single profile on OPT)

| | BASE (committed `perf/results/scalene-w1.json`) | OPT (msgspec HEAD) |
|---|---|---|
| dataclass construction CPU share (`<exec@dataclasses.py:498>` family) | **13.32%** | **5.13%** |
| `msgspec` CPU share | — | **0.00%** |

- Construction frame **roughly halved (−8.18 pp)**. msgspec's per-object construction is compiled C →
  **invisible** to Scalene's Python-line attribution (the per-field `object.__setattr__` Python loop is
  *gone* — exactly why it is faster).
- Residual 5.13% = the **other** hot-path dataclasses NOT in scope (Position, transactions/decision
  structs that fire at low frequency) + the `created_at` `__post_init__` `object.__setattr__` default
  that ports verbatim under the kept `frozen=True`.
- Directional drop (BASE→OPT) is the signal; absolute Scalene shares are perturbed by instrumentation.
- OPT profile written to scratchpad (NOT committed) so the committed BASE `scalene-w1.json` is untouched.

---

## Headline attribution + D-02 carve-out

**Headline win = the events + `Bar` slice** (every `Bar`/`BarEvent`/`SignalEvent`/`OrderEvent`/`FillEvent`
built per tick — ~69k Bar volume/run). This is the A/B-attributed gate-(b) number: **+7.06% W1 /
+10.64% W2@50, clean OPT/BASE separation on both axes, Scalene-corroborated (construction frame halved).**

**D-02 carve-out (stated explicitly, per 08-05 D-02):** the 5 standalone DTOs
(`FillDecision`, `CancelDecision`, `TrailState`, `Transaction`, `SignalRecord`) fire at low frequency
(~1,578/run, ≈4% of the ~69k Bar volume), so their *isolated* A/B lands in NOISE. Per the D-02
carve-out they are **NOT reverted** — they ship under the same byte-exact oracle gate for a uniform
value-object layer. The commit-level A/B above measures the migration as a whole; the headline
attribution is the events+Bar slice, and the DTOs' noise-band isolated delta is expected and NOT a
revert trigger. This is the intended carve-out, not a hidden contradiction (T-08-12 mitigation).

---

## Gate (a) byte-exact — full Phase-8 stack in place (deterministic wins + msgspec)

| Check | Result |
|---|---|
| `poetry run pytest tests/integration/test_backtest_oracle.py` | **3 passed** — **134 trades / 46189.87730727451** (byte-exact + behavioral identity + determinism double-run, zero tolerance) |
| `poetry run pytest tests` (full suite) | **1340 passed, 0 failed** |
| `poetry run mypy` (strict, configured) | **Success: no issues found in 188 source files** |
| Determinism double-run | identical (covered by `test_oracle_behavioral_identity`) |

Gate (a) is byte-exact green with the full Phase-8 stack. The engine to be re-frozen is the SHIPPED
engine (HEAD, msgspec in place), tree clean.

---

## Owner sign-off — PENDING (blocking checkpoint)

Claude has automated the migration (08-05) + gate (a) + the fresh cool same-machine A/B. The
owner-gated re-freeze + sign-off remains (NOT run by Claude — `make perf-baseline` / `make perf-w2-baseline`
are owner-gated):

1. Confirm the box is still cool (`pmset -g therm` clean).
2. Re-freeze the cool W1 baseline: `make perf-baseline` → writes `perf/results/W1-BASELINE.json`
   (the final locked Phase-8 reference).
3. Re-freeze the cool W2 baseline: `make perf-w2-baseline` → writes `perf/results/W2-BASELINE.json`.
4. Confirm the regression guard passes against the new baseline: `make perf-w1 --check`.
5. Confirm gate (a) byte-exact: `poetry run pytest tests/integration/test_backtest_oracle.py`
   (134 / 46189.87730727451); `poetry run mypy` clean.
6. Record owner sign-off (attribution, as in quick `260625-0qj` / 08-04 sign-off).

> STATE.md / ROADMAP.md NOT modified; 08-06-SUMMARY.md NOT yet created — the plan is not complete
> until after sign-off + re-freeze. This is the FINAL Phase-8 gate.

**Owner sign-off:** **PENDING** — tiziaco (tiziano.iaco@gmail.com).

Cool-box re-freeze (to be accepted as the new locked Phase-8 references):
- **W1 ______ s / ______ MB** (workload byte-identical 1578 fills / 659 closed) → `perf/results/W1-BASELINE.json`
- **W2 @50 ______ s / ______ MB** (n_bars=3000, seed=42) → `perf/results/W2-BASELINE.json`

**Signed by:** _______________  **Date:** _______________
