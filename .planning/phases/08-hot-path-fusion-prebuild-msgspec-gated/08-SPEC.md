# Phase 8: Hot-Path Fusion, Bar Prebuild & msgspec-Gated Spike — Specification

**Created:** 2026-06-25
**Ambiguity score:** 0.12 (gate: ≤ 0.20)
**Requirements:** 6 locked (5 committed deterministic wins + 1 gated msgspec decision)

## Goal

Cut the post-Phase-7 profiler-confirmed per-bar CPU hotspots in the backtest hot path so the clean
W1 benchmark shows a measurable wall-clock improvement vs the current re-frozen baseline, with **zero
change to engine numbers** (the SMA_MACD oracle stays byte-exact: 134 trades / `46189.87730727451`).

## Background

Phase 7 closed v1.5's planned scope (Phases 1–7). A fresh Scalene CPU profile of W1 taken this session
(`make perf-profile`, logging disabled, 4 symbols / 6 portfolios / 2-month 5m window, 1,578 fills,
`perf/results/scalene-w1.json`) exposed the next tier of hotspots. All prior wins held — the D-10
window cursor and the dict-lookup fast-path are gone from the profile. The remaining costs, with the
code that owns them:

- **Frozen-dataclass `__init__` (~13% aggregate).** Scalene pins all `@dataclass(frozen=True, slots=True)`
  construction to the shared `<exec@dataclasses.py:498>` codegen frame. Frozen init calls
  `object.__setattr__` per field in pure Python. Dominated by the high-frequency objects: `Bar`
  (`itrader/core/bar.py`, ~69k built at warm-up) + per-tick `TimeEvent`/`BarEvent` + per-signal/order/
  fill events (`itrader/events_handler/events/`).
- **Portfolio per-bar mark-to-market (~12.5%).** `position_manager.get_total_market_value`
  (`position_manager.py:286`) and `get_total_unrealized_pnl` (`:297`) each loop the full
  `_storage.get_positions()` separately every bar; `portfolio_handler.py:638-645` loops positions
  again for locked margin. 2–3 full passes per bar. Scales on the W2 symbol-count axis.
- **`Position` Decimal property recompute (~7.3%).** `net_quantity` (`position.py:127`,
  `abs(buy_quantity - sell_quantity)`) and `avg_price` (`:110`) recompute on every access, though they
  only change on a fill; called repeatedly per bar via `market_value`/`aggregate_notional`.
- **Per-signal `to_dict` serialization (~3.3%).** `strategy_handler/base.py` `to_dict()` (L650-695)
  re-introspects `_declared_hints(type(self))` and `_json_safe`-walks every declared field on every
  `SignalRecord` (`strategies_handler.py:192`), though the snapshot is almost entirely static per
  strategy instance.
- **Per-tick timeframe alignment (~3%).** `outils/time_parser.py` `check_aligned` (L167-168) does
  `astimezone(pytz.utc).replace(...)` + `total_seconds()` per tick.

The queue is already pandas-free (`BarEvent.bars` carries `Bar` value objects, not Series, M5-02/D-15);
the only surviving Series-per-row is the `iterrows()` prebuild. `msgspec` is already present (0.21.1,
dev-only transitive via nautilus-trader); promoting it to a runtime dependency is the one open
cost-of-adoption question, flagged as a measure-first spike in the Phase 07 TODO
(`07-CONTEXT.md:36`, `07-SPEC.md:64`).

This phase is **byte-exact** (NOT a re-baseline like Phase 5) — every target has zero numeric surface.

## Requirements

1. **Mark-to-market single-pass fusion**: The per-bar portfolio valuation computes total market value,
   total unrealised PnL, and locked margin in ONE iteration over the positions.
   - Current: `get_total_market_value` and `get_total_unrealized_pnl` each iterate
     `_storage.get_positions()` independently, and `portfolio_handler` loops positions a third time for
     locked margin — 2–3 full passes per bar.
   - Target: a single fused pass produces the values the per-bar update needs; the public
     `get_total_market_value` / `get_total_unrealized_pnl` accessors keep returning identical Decimals.
   - Acceptance: oracle byte-exact (134 trades / `46189.87730727451`); same-machine A/B shows an
     attributable W1 (and/or W2) wall-clock contribution, else this change is reverted.

2. **Position property caching**: `Position.net_quantity` and `avg_price` are cached and invalidated on
   fill, not recomputed per access.
   - Current: both are `@property`s recomputing Decimal arithmetic on every read; hit repeatedly per
     bar through `market_value`/`aggregate_notional`.
   - Target: cached values, invalidated whenever a fill mutates `buy_quantity`/`sell_quantity`/
     commissions/avg prices; `market_value` still reflects the per-bar `current_price`.
   - Acceptance: oracle byte-exact; a unit test proves the cache invalidates on a fill (cached value
     after a buy/sell differs correctly); same-machine A/B shows an attributable contribution, else
     reverted.

3. **Bar prebuild without `iterrows`**: Prebuilt `Bar`s are constructed via `itertuples`/vectorized
   column reads, not `frame.iterrows()`.
   - Current: `bar_feed.py:255-258` builds `self._prebuilt` with `for ts, row in frame.iterrows()`,
     materializing ~69k throwaway pandas Series.
   - Target: the same `{ts: Bar}` mapping built from `itertuples(index=True)` or column-array zips — no
     per-row Series; the Decimal-via-string contract (D-14) preserved byte-for-byte.
   - Acceptance: oracle byte-exact; prebuilt `Bar` objects equal the `iterrows` build field-for-field
     (equivalence test); same-machine A/B shows an attributable contribution, else reverted.

4. **`to_dict` static-snapshot cache**: `Strategy.to_dict` does not re-introspect declared hints and
   re-walk static fields on every signal.
   - Current: `base.py` L650-695 calls `_declared_hints(type(self))` + `_json_safe` over every declared
     field per `SignalRecord` emission.
   - Target: the static portion of the snapshot is computed once per strategy instance (or per class)
     and cached; only the genuinely runtime fields are refreshed per call.
   - Acceptance: `to_dict()` output is byte-identical to the pre-change dict (snapshot-drift test, as in
     Phase 4's `_declared_hints` memo); oracle byte-exact; same-machine A/B shows an attributable
     contribution, else reverted.

5. **Per-tick alignment precompute**: `check_aligned` no longer recomputes the same
   `astimezone`/`replace`/`total_seconds` work every tick.
   - Current: `time_parser.py` L167-168 recomputes per call; called per tick × timeframe.
   - Target: alignment decided from a precomputed/cached int64-ns grid (same approach as the D-10
     cursor), behavior identical.
   - Acceptance: `check_aligned` returns identical booleans across a representative tick/timeframe set
     (equivalence test); oracle byte-exact; same-machine A/B shows an attributable contribution, else
     reverted.

6. **msgspec.Struct migration — DECISION-GATED**: The `Bar` + per-tick events migration to
   `msgspec.Struct` is folded into this phase IFF a measure-first spike clears the gate.
   - Current: events + `Bar` are `@dataclass(frozen=True, slots=True, kw_only=True)`; `msgspec` is a
     dev-only transitive dependency (0.21.1). Migration friction is known-low: one `dataclasses.replace`
     (`matching_engine.py:166`), one `asdict` (`reporting/frames.py:75`, off hot path), and the
     `field(default=EventType.X, init=False)` type-tag pattern.
   - Target: a spike converts `Bar` + per-tick events to `msgspec.Struct` (frozen, `gc=False` where
     reference-cycle-free) and measures W1/W2 same-machine A/B. The migration ships in Phase 8 IFF it
     clears **≥5% W1 wall-clock** (the gate-(b) threshold) AND msgspec is promoted to a runtime
     dependency of shipped `itrader/`. Otherwise the migration is DEFERRED to a follow-up phase and the
     spike's measured delta + recommendation are recorded.
   - Acceptance: a spike artifact records the measured W1 (and W2) A/B delta and the include/defer
     decision against the ≥5% W1 threshold; IF included → oracle byte-exact + `mypy --strict` clean +
     determinism double-run identical with msgspec in place; IF deferred → no msgspec on the shipped
     runtime path, `pyproject.toml` unchanged, follow-up recorded.

## Boundaries

**In scope:**
- Single-pass fusion of the per-bar portfolio mark-to-market (market value + unrealised PnL + locked
  margin) — `position_manager.py`, `portfolio_handler.py`.
- Fill-invalidated caching of `Position.net_quantity` / `avg_price` — `position/position.py`.
- `itertuples`/vectorized `Bar` prebuild — `price_handler/feed/bar_feed.py`.
- `Strategy.to_dict` static-snapshot cache — `strategy_handler/base.py`.
- Per-tick `check_aligned` precompute/cache — `outils/time_parser.py`.
- A measure-first `msgspec.Struct` spike for `Bar` + per-tick events, with an include/defer decision
  gated on ≥5% W1.
- Equivalence/invalidation/drift tests for each committed change; same-machine A/B attribution; cool
  re-freeze of the W1 baseline per the thermal-drift caveat.

**Out of scope:**
- The full event-model msgspec migration if the spike misses ≥5% W1 — deferred to a follow-up (the
  spike still runs and records its number).
- Coverage-strategy costs (`perf/strategies/*`, e.g. `d_short_zscore.std()` ~5.9%) — benchmark
  instruments, not engine code.
- `reporting/` pandas (`metrics.py`, `frames.py`, `plots.py`, `summary.py`, `cash_operations.py`) —
  runs once post-run, not a per-bar hot path.
- One-time CSV load (`csv_store.py` `pd.to_datetime`/`read_csv`, ~4.7%) — fixed cost; amortizes on
  longer runs.
- The `bar_feed.window()` `iloc` slice — already tamed by the D-10 cursor; not re-opened.
- Any change to engine numbers — this phase is byte-exact; re-baselining is Phase-5-only territory.
- `to_money` `Decimal(str(x))` / `uuid7` — inherent Decimal/ID discipline, not optimized here.

## Constraints

- **Byte-exact oracle (Gate a):** `tests/integration/test_backtest_oracle.py` stays green — 134 trades
  / `final_equity 46189.87730727451`; determinism double-run byte-identical; `mypy --strict` clean.
- **Perf Gate (b):** clean W1 benchmark shows a measurable wall-clock improvement vs the current
  re-frozen baseline; attribute via **same-machine A/B**, never the frozen-baseline compare alone, and
  re-freeze on a verified-cool box (lesson `v15-perf-gateb-thermal-drift`).
- **Keep-only-measured:** each committed change (Reqs 1–5) is kept only if A/B shows an attributable
  contribution; a change that lands in run-to-run noise is reverted (Phase 6 discipline).
- **Decimal end-to-end:** every change is *less repeated work*, never a float swap. Cached Decimals
  stay Decimal; the D-14 Bar string-path contract is preserved.
- **msgspec runtime dependency:** only promoted from dev-only to a shipped `itrader/` runtime
  dependency if Req 6's gate is met; otherwise `pyproject.toml` runtime deps are unchanged.
- **Determinism / look-ahead:** no change to RNG seeding, the injected clock, or the 7-rule bar-timing
  contract; the prebuild change touches construction only, not window slicing.

## Acceptance Criteria

- [ ] SMA_MACD oracle green: 134 trades / `final_equity 46189.87730727451`.
- [ ] Determinism double-run byte-identical; `mypy --strict` clean; e2e suite green.
- [ ] Per-bar portfolio valuation does a single pass over positions (not 2–3); public accessors return
      identical Decimals.
- [ ] `Position.net_quantity`/`avg_price` cached with a test proving fill-invalidation correctness.
- [ ] Prebuilt `Bar`s built without `iterrows`; equivalence test vs the prior build passes.
- [ ] `Strategy.to_dict()` output byte-identical to pre-change (snapshot-drift test).
- [ ] `check_aligned` returns identical booleans across the equivalence set.
- [ ] Each committed change (Reqs 1–5) has a same-machine A/B result; noise-only changes are reverted.
- [ ] msgspec spike artifact records the W1 (and W2) A/B delta + an include/defer decision against the
      ≥5% W1 threshold; if included, oracle stays byte-exact with msgspec in place.
- [ ] Clean W1 benchmark improves vs the re-frozen baseline (`make perf-w1 --check` passes); baseline
      re-frozen cool.

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                        |
|--------------------|-------|------|--------|--------------------------------------------------------------|
| Goal Clarity       | 0.90  | 0.75 | ✓      | Specific files/functions/%s; measurable (≥5% W1, byte-exact) |
| Boundary Clarity   | 0.92  | 0.70 | ✓      | Explicit in/out lists; msgspec gated; coverage+reporting out |
| Constraint Clarity | 0.85  | 0.65 | ✓      | Oracle, gate (b), thermal A/B, keep-only-measured, dep gate  |
| Acceptance Criteria| 0.85  | 0.70 | ✓      | Pass/fail oracle + per-win A/B + msgspec gate threshold      |
| **Ambiguity**      | 0.12  | ≤0.20| ✓      |                                                              |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

| Round | Perspective    | Question summary                          | Decision locked                                              |
|-------|----------------|-------------------------------------------|--------------------------------------------------------------|
| 0     | Researcher     | Where does this work live? (v1.5 close)   | Extend v1.5 as Phase 8 (Phase 7 add-on precedent)            |
| 1     | Boundary Keeper| msgspec include/exclude gate?             | Include iff spike clears ≥5% W1 (gate-b) + dep accepted      |
| 1     | Failure Analyst| 5 deterministic wins — keep rule?         | Keep-only-measured; revert noise (Phase 6 discipline)        |

> Pre-grounded by a live Scalene profile + direct reads of `bar_feed.py`, `position.py`,
> `position_manager.py`, `strategy_handler/base.py`, `time_parser.py`, and `events_handler/events/`
> this session — current state confirmed against code, not assumed.

---

*Phase: 08-hot-path-fusion-prebuild-msgspec-gated*
*Spec created: 2026-06-25*
*Next step: /gsd:discuss-phase 8 — implementation decisions (how to build what's specified above), then run the msgspec measure-first spike to resolve Req 6's gate*
