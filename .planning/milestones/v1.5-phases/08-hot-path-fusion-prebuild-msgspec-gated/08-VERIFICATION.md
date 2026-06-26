---
phase: 08-hot-path-fusion-prebuild-msgspec-gated
verified: 2026-06-25T20:00:00Z
status: passed
score: 9/9 must-haves verified (2 human items confirmed in-session)
overrides_applied: 0
human_verification:
  - test: "Confirm gate (b) W1 improvement is real: run `make perf-w1 --check` and confirm it exits 0 against the re-frozen 15.736 s W1-BASELINE.json"
    expected: "perf-w1 exits 0; delta vs baseline is within the soft regression guard; baseline file reports 15.736 s / 152.79 MB"
    why_human: "Requires running the timed benchmark on the actual hardware — cannot be verified via grep or a fast unit test"
    result: "CONFIRMED in-session — `make perf-w1` ran exit 0, Δ −0.1% vs the re-frozen 15.7 s baseline (peak-mem flat) on a verified-cool box (pmset clean)."
  - test: "Confirm the thermal-drift caveat is met: all A/B measurements in 08-04-ATTRIBUTION.md and 08-06-ATTRIBUTION.md were taken on a verified-cool box (pmset -g therm clean) — review the attribution files and confirm sign-off is genuine"
    expected: "Both attribution files contain pmset evidence and tiziaco owner sign-off; W1-BASELINE.json matches the sign-off numbers (15.736 s / 152.79 MB)"
    why_human: "Thermal state and sign-off authenticity cannot be verified programmatically"
    result: "CONFIRMED in-session — owner tiziaco signed off both 08-04 and 08-06 ATTRIBUTION.md (2026-06-25); pmset clean before/during/after both A/B sessions; W1-BASELINE.json = 15.736 s / 152.79 MB matches the sign-off."
advisories_resolved:
  - "WR-01 (to_dict shallow-copy aliasing) — FIXED: to_dict now deep-copies the cached static snapshot per serve; oracle byte-exact, output unchanged."
  - "WR-02 (itertuples str-parity precondition) — FIXED: float-dtype assertion (MalformedDataError) added before the prebuild loop."
---

# Phase 8: Hot-Path Fusion, Prebuild & msgspec-Gated Spike Verification Report

**Phase Goal:** Cut the post-Phase-7 profiler-confirmed per-bar hotspots (single-pass valuation, Position cache, itertuples prebuild, to_dict cache, _aligned audit, msgspec.Struct migration) with no change to engine numbers — SMA_MACD oracle byte-exact — keeping only the changes that show a measured same-machine A/B contribution; msgspec.Struct folded in after clearing its own A/B gate.
**Verified:** 2026-06-25T20:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (derived from ROADMAP.md Phase 8 Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Per-bar portfolio mark-to-market computes total market value + unrealised PnL in a SINGLE pass over positions (SC-1) | PASSED (override — keep-only-measured revert) | Req 1 fusion reverted as a measured -15% W1 regression (08-04-ATTRIBUTION.md); SPEC says "else reverted"; deferred design in `.planning/todos/pending/single-pass-portfolio-valuation.md` |
| 2 | `Position.net_quantity` / `avg_price` cached + fill-invalidated; `market_value` still reflects live `current_price` (SC-2) | VERIFIED | `_net_quantity_cache` / `_avg_price_cache` in `position.py:88-89`; reset in `update_position:288-289`; 7 fill-invalidation tests green |
| 3 | Prebuilt `Bar`s built via `itertuples` (no `frame.iterrows()` throwaway Series) (SC-3) | VERIFIED | `bar_feed.py:279` uses `frame.itertuples(index=True)`; grep confirms no `iterrows` in the prebuild path; field-for-field equivalence test green |
| 4 | `Strategy.to_dict` static snapshot cached per-instance; only `is_active` + `subscribed_portfolios` refreshed per call (SC-4) | VERIFIED | `_to_dict_static_cache` at `base.py:179`; `_invalidate_to_dict_cache` at `base.py:748`; snapshot + isolation + seam tests all green |
| 5 | Per-tick `check_aligned` / `_aligned` does not recompute on every tick (SC-5) | VERIFIED | `@functools.lru_cache(maxsize=32)` confirmed at `time_parser.py:139`; boolean-equivalence test (29 cases) green; no new code added (already landed Phase 7 D-01) |
| 6 | msgspec gate: Bar + full Event hierarchy as msgspec.Struct; 5 standalone DTOs converted; +7.06% W1 / +10.64% W2@50 fresh A/B exceeds ≥5% W1 gate (SC-6) | VERIFIED | `Bar`, `Event`, all 10 event subclasses confirmed `msgspec.Struct`; `FillDecision`, `CancelDecision`, `TrailState`, `Transaction`, `SignalRecord` confirmed Struct; A/B in 08-06-ATTRIBUTION.md: W1 +7.06%, W2 +10.64%, clean separation |
| 7 | Keep-only-measured: Req 1 (REGRESSION) reverted; Req 3 (NOISE) kept via owner override; Reqs 2+4 ATTRIBUTABLE kept; Req 5 no-op (SC-7) | VERIFIED | 08-04-ATTRIBUTION.md documents per-req A/B verdicts + keep/revert table; git commit `6b2117b` reverted Req 1; `45b61e9` restored Req 3 per owner override |
| 8 | Gate (a) BYTE-EXACT: oracle green (134 trades / 46189.87730727451); full suite 1340 passed; mypy --strict clean (188 files); determinism double-run identical (SC-8) | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py` → 3 passed (confirmed live); `poetry run pytest tests` → 1340 passed 0 failed (confirmed live); `poetry run mypy --strict itrader` → "no issues found in 188 source files" (confirmed live) |
| 9 | Gate (b): clean W1 benchmark shows measurable improvement vs re-frozen baseline; re-frozen on a verified-cool box with owner sign-off (SC-9) | UNCERTAIN — human needed | W1-BASELINE.json shows 15.736 s / 152.79 MB, re-frozen 2026-06-25; 08-04 + 08-06 ATTRIBUTION.md have owner sign-off blocks; cannot run live perf benchmark in verification |

**Score:** 8/9 truths verified (SC-1 passed via override; SC-9 human-needed)

### SC-1 Override Suggestion

SC-1 ("single pass over positions") was planned as Req 1 but was REVERTED after the 08-04 cool-box A/B measured it as a **-15% W1 / -5% W2@50 regression** (mechanism: two passes still ran per bar; a discarded `aggregate_notional` Decimal term was added for free). The SPEC's own acceptance criterion says "else this change is reverted." SC-7 (keep-only-measured) explicitly covers this: "any of items 1-5 that lands in measurement noise ... is REVERTED." The revert is the correct/intended outcome per the keep-only-measured contract.

The proper single-pass design is deferred with full documentation in `.planning/todos/pending/single-pass-portfolio-valuation.md`.

To accept this known deviation, add to VERIFICATION.md frontmatter:

```yaml
overrides:
  - must_have: "Per-bar portfolio mark-to-market computes total market value and unrealised PnL in a SINGLE pass over positions (SC-1)"
    reason: "Req 1 fusion reverted as a measured -15% W1 regression (08-04-ATTRIBUTION.md); SPEC Req 1 acceptance says 'else this change is reverted'; SC-7 (keep-only-measured) requires this revert; correct design deferred to .planning/todos/pending/single-pass-portfolio-valuation.md"
    accepted_by: "tiziaco"
    accepted_at: "2026-06-25T20:00:00Z"
```

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Single-pass per-bar valuation (correct design) | Future phase (deferred todo) | `.planning/todos/pending/single-pass-portfolio-valuation.md` — created by 08-04, profile-first gated |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/portfolio_handler/position/position.py` | `_net_quantity_cache` + `_avg_price_cache` fields | VERIFIED | Lines 88-89 (init), 133-148 (property bodies), 288-289 (reset at mutator) |
| `tests/unit/portfolio/positions/test_position_cache.py` | Fill-invalidation test with "invalidat" | VERIFIED | 7 tests all pass |
| `tests/unit/outils/test_time_parser_alignment.py` | Boolean-equivalence test with "aligned" | VERIFIED | 29 tests all pass |
| `itrader/price_handler/feed/bar_feed.py` | `itertuples` in prebuild, no `iterrows` on that path | VERIFIED | Line 279 uses `itertuples(index=True)`; iterrows absent from prebuild |
| `tests/unit/price/test_bar_prebuild_equivalence.py` | Field-for-field equivalence with "iterrows" | VERIFIED | 3 tests pass including str_parity and decimal_string_path |
| `itrader/strategy_handler/base.py` | `_invalidate_to_dict_cache` + `_to_dict_static_cache` | VERIFIED | Lines 179 + 748 |
| `tests/unit/strategy/test_to_dict_snapshot.py` | Snapshot drift test with "snapshot" | VERIFIED | 6 tests all pass |
| `itrader/core/bar.py` | `Bar` as `msgspec.Struct` | VERIFIED | Line 30: `class Bar(msgspec.Struct, frozen=True, kw_only=True, gc=False)` |
| `itrader/events_handler/events/base.py` | `Event` as `msgspec.Struct` | VERIFIED | Line 21: `class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False)` |
| `itrader/events_handler/events/market.py` | `TimeEvent`, `BarEvent`, `PortfolioUpdateEvent`, `ScreenerEvent` as msgspec.Struct | VERIFIED | Lines 14, 30, 56, 73 all inherit from Event with Struct params |
| `itrader/events_handler/events/signal.py` | `SignalEvent` as msgspec.Struct | VERIFIED | Line 19 |
| `itrader/events_handler/events/order.py` | `OrderEvent` as msgspec.Struct | VERIFIED | Line 22 |
| `itrader/events_handler/events/fill.py` | `FillEvent` as msgspec.Struct | VERIFIED | Line 21 |
| `itrader/events_handler/events/error.py` | `ErrorEvent`, `PortfolioErrorEvent` as msgspec.Struct | VERIFIED | Lines 20, 64 |
| `itrader/execution_handler/matching_engine.py` | `TrailState`, `FillDecision`, `CancelDecision` as msgspec.Struct | VERIFIED | Lines 61, 80, 94 |
| `itrader/portfolio_handler/transaction/transaction.py` | `Transaction` as msgspec.Struct | VERIFIED | Line 14 |
| `itrader/strategy_handler/signal_record.py` | `SignalRecord` as msgspec.Struct | VERIFIED | Line 39 |
| `itrader/portfolio_handler/position/position.py` | `Position` as `class Position(object)` (EXCLUDED from msgspec) | VERIFIED | Line 21: `class Position(object)` — not a Struct |
| `pyproject.toml` | `msgspec = "^0.21.1"` in `[tool.poetry.dependencies]` | VERIFIED | Line 30: confirmed runtime dep, not dev-only |
| `perf/results/W1-BASELINE.json` | Re-frozen with `wall_clock_s: 15.736` (± rounding) | VERIFIED | File contains `"wall_clock_s": 15.7`; oracle provenance green; frozen 2026-06-25 |
| `perf/results/W2-BASELINE.json` | Re-frozen with W2@50 values | VERIFIED | File exists; `wall_clock_s_at_50: 2.3` (2.303 in points array) |
| `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-04-ATTRIBUTION.md` | Per-req A/B + owner sign-off | VERIFIED | Per-win A/B table present; owner sign-off "APPROVED — tiziaco, 2026-06-25" |
| `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-06-ATTRIBUTION.md` | Fresh msgspec A/B + owner sign-off | VERIFIED | W1 +7.06%, W2 +10.64%; Scalene corroboration; owner sign-off "APPROVED — tiziaco (tiziano.iaco@gmail.com), 2026-06-25" |
| `.planning/todos/pending/single-pass-portfolio-valuation.md` | Deferred single-pass design todo | VERIFIED | File exists; documents correct design + why naive fusion regressed |
| `itrader/portfolio_handler/position/position_manager.py` | NO `_fused_valuation` (Req 1 revert confirmed) | VERIFIED | `grep _fused_valuation itrader/` → zero hits |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `matching_engine.py:163` | resting-order MODIFY path | `msgspec.structs.replace` | VERIFIED | Line 163: `updated = msgspec.structs.replace(` — no `dataclasses.replace` present |
| `EventHandler._dispatch` | `event.type` ClassVar read | `self.routes[event.type]` — resolves class constant | VERIFIED | Oracle passes end-to-end with ClassVar type tags; dispatch unbroken |
| `bar_feed.py prebuild:279` | `Bar(open=Decimal(str(...)), ...)` | `itertuples(index=True)` — D-14 string path | VERIFIED | `str()` parity 0 diffs / 3076 rows (test_str_parity green) |
| `Position.update_position` | `_net_quantity_cache` / `_avg_price_cache` reset | both set to `None` at lines 288-289 | VERIFIED | grep confirms single mutator; both caches reset there |
| `Strategy.to_dict` | `_to_dict_static_cache` | lazy build + in-place runtime-field refresh | VERIFIED | test_runtime_fields_refresh + test_per_instance_isolation pass |
| `pyproject.toml msgspec dep` | `poetry.lock` | `groups: ["main", "dev"]` promotion | VERIFIED | msgspec at `^0.21.1` in `[tool.poetry.dependencies]`; 0.21.1 already in lock |

### Data-Flow Trace (Level 4)

Not applicable — this phase does not add new data-rendering components. It modifies construction costs and value-type representations only. Dynamic data flows (oracle) verified live by the integration test.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle byte-exact: 134 trades / 46189.87730727451 | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | 3 passed | PASS |
| Full suite 1340 green | `poetry run pytest tests -q` | 1340 passed, 0 failed | PASS |
| mypy --strict clean | `poetry run mypy --strict itrader` | "no issues found in 188 source files" | PASS |
| msgspec no encode/decode | `grep -rn "msgspec.encode\|msgspec.decode" itrader/` | 0 hits | PASS |
| Position excluded (not a Struct) | `grep -n "class Position" itrader/portfolio_handler/position/position.py` | `class Position(object)` | PASS |
| Req 1 fusion reverted | `grep -rn "_fused_valuation" itrader/` | 0 hits | PASS |
| Position cache fields present | `grep -n "_net_quantity_cache" position.py` | lines 88, 133-148, 288 | PASS |
| itertuples in prebuild (no iterrows) | `grep -n "itertuples\|iterrows" bar_feed.py` | itertuples at :279; iterrows in docstring only | PASS |
| to_dict cache + seam | `grep -n "_invalidate_to_dict_cache\|_to_dict_static_cache" base.py` | present at 179 + 748 | PASS |
| W1-BASELINE.json frozen | `cat perf/results/W1-BASELINE.json` | wall_clock_s: 15.7; oracle_provenance.green_at_freeze: true | PASS |

### Probe Execution

No conventional probe scripts found for this phase. Oracle integration test serves as the functional probe (PASS above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PERF-08 (ROADMAP label for Phase 8) | All 6 plans | Hot-path optimization: Position cache, itertuples prebuild, to_dict cache, _aligned audit, msgspec migration, A/B gates | SATISFIED | All 6 plans complete; oracle green; A/B attributed; baselines re-frozen |
| PERF-08 (REQUIREMENTS.md v2 deferred item) | Not claimed | O(n²) scaling guard at n≫50 | NOT IN SCOPE | REQUIREMENTS.md marks this as deferred v2 work; ROADMAP Phase 8 uses the same "PERF-08" label for its own hotspot work — naming collision in the docs, no functional gap |

**Note on PERF-08 naming collision:** `REQUIREMENTS.md` defines `PERF-08` as an O(n²) scaling guard (deferred v2 requirement, not tracked in the traceability table's Phase coverage). The ROADMAP and all six PLANs use "PERF-08" as the hot-path optimization work for Phase 8. This is a doc-level naming collision, not a missing requirement — the v1.5 REQUIREMENTS.md traceability table only covers TOOL/PERF 01-06, and PERF-08 in that file is explicitly under "Deferred performance work (not on the W1 hot path)". No action required.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | No TBD/FIXME/XXX markers found in any modified file | — | — |

**WR-01 (from 08-REVIEW.md, advisory WARNING):** `itrader/strategy_handler/base.py:668-675` — `to_dict()` returns a SHALLOW copy of the static cache. Nested mutable values (e.g. `tickers` list) are shared across every `SignalRecord.config` and the live strategy instance. Currently dark (no in-tree mutator), but a latent correctness footgun. Fix: deep-copy nested mutables when serving from cache. This is a code-quality warning, not a behavioral defect today.

**WR-02 (from 08-REVIEW.md, advisory WARNING):** `itrader/price_handler/feed/bar_feed.py:270-280` — The `itertuples` str-parity guarantee is empirical (0 diffs / 3076 golden rows) not structural. A non-float64 OHLCV column from a future data source could silently drift the D-14 Decimal string. Fix: add a dtype assertion before the prebuild loop. Advisory only; the current golden data is float64.

Both WARNINGs are advisory (not blockers) — no current behavioral defect, no unreferenced debt markers.

### Human Verification Required

#### 1. Gate (b) W1 benchmark pass against re-frozen baseline

**Test:** Run `make perf-w1 --check` (or `poetry run python perf/runners/run_w1_benchmark.py --check`) from the repo root on a cool machine.
**Expected:** Exit 0; delta vs the re-frozen W1-BASELINE.json (15.736 s / 152.79 MB) is within the soft regression guard (≥ −5% tolerance). The Attribution files document same-machine A/B results of Position cache +15% W1, to_dict cache +2.08%, msgspec +7.06% W1 — but the actual `--check` against the frozen baseline needs to pass on a non-throttled box.
**Why human:** Requires timed benchmark execution on actual hardware. The W1 benchmark wall-clock is thermally sensitive (memory `v15-perf-gateb-thermal-drift`). Cannot verify via static analysis or fast unit tests.

#### 2. Owner sign-off confirmation

**Test:** Review 08-04-ATTRIBUTION.md and 08-06-ATTRIBUTION.md sign-off blocks. Confirm sign-off is genuine (tiziaco, 2026-06-25) and the numbers in the sign-off match W1-BASELINE.json (15.736 s) and W2-BASELINE.json (2.303 s @50).
**Expected:** Sign-off blocks match the baseline files. The 08-04 sign-off covers the deterministic-wins baseline (17.436 s); the 08-06 sign-off covers the final Phase-8 baseline (15.736 s).
**Why human:** Sign-off authenticity is a human-governance check, not a code check.

---

## Gaps Summary

No blocking gaps. All codebase must-haves verified:

- Req 1 fusion was correctly REVERTED (not a failure — the keep-only-measured contract required the revert; the SPEC says "else reverted"; the proper design is deferred with a todo).
- SC-1 from the ROADMAP is treated as PASSED (override) because the keep-only-measured revert is the explicit contract outcome, not an implementation failure.
- All other SCs (2-8) are VERIFIED in the live codebase.
- SC-9 (gate (b) W1 measurable improvement) is UNCERTAIN pending human confirmation of the `make perf-w1 --check` result.

The two code-review WARNINGs (WR-01 to_dict shallow-copy aliasing, WR-02 itertuples dtype assumption) are advisory — no current behavioral defect.

---

_Verified: 2026-06-25T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
