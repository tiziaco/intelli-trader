# Phase 4: Hot-Path Discipline - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 removes structural waste from the per-bar path on **two behavior-only sinks**, neither of
which has a numeric surface (PERF-03 + PERF-04):

1. **Hot-loop logging** (hotspot #4, ~6% W1 / ~22% W2). Today the structlog pipeline runs on
   *every* log call — even below-level ones — because `setup_logging` configures the default
   `BoundLogger` with filtering only at the stdlib handler (`root_logger.setLevel`, logger.py:177).
   So a below-level `debug()`/`warning()` still walks all 9 processors before being dropped at the
   end. The fix is a **central level-gate** in the `ITraderStructLogger` wrapper that short-circuits
   *before* the pipeline, plus demoting the per-bar admission-rejection log and a curated removal of
   redundant per-bar `debug()` calls.
2. **Re-resolved type hints** (hotspot #6, ~2% W1 / ~14% W2). `Strategy.to_dict` calls
   `get_type_hints(type(self))` on **every signal snapshot** (base.py:356), re-walking the MRO and
   re-resolving annotations though they are constant per class. The fix is a per-class
   **memoization**.

This is the perf analog of v1.2 Consolidation: **behavior-preserving — it re-baselines NOTHING.**
The byte-exact SMA_MACD oracle stays the lock; Decimal/money untouched; no emitted-log *content* or
signal-snapshot *content* changes on any path the oracle or e2e leaves observe (demotion/deletion
affect log **volume**, not correctness).

**In scope:**
- Central level-gate in `ITraderStructLogger` (D-02); demote the admission-rejection log
  `error`→`warning` + cached `isEnabledFor` guard (D-01); curated per-bar `debug()` removal with
  per-line sign-off (D-04); a new `ITRADER_DISABLE_LOGS` kill-switch (D-08).
- Memoize `get_type_hints` per class via a module-level `@functools.cache` helper, routing both
  `to_dict` (hot) and `_apply_params` (cold) through it (D-05).
- Behavior-preservation drift locks for both changes (D-06 logging, D-07 type hints).

**Out of scope (behavior-preserving milestone — changes NO numbers):**
- Whole-codebase logging-policy review and any `debug`→`info` **promotions** for live observability
  (deferred → N+4 Live Trading Readiness; see Deferred). The per-line review this phase is
  **hot-path only**.
- Removing `get_type_hints` resolution entirely / replacing with a names-only MRO walk (deferred;
  byte-identity/ordering risk — not in a byte-exact phase; see Deferred).
- Any change to `min_order_size` or the coverage-strategy sizing to silence the admission spam
  (decided in Phase 1 — wrong lever, would re-bake the W1 baseline; **do NOT revisit**).
- Any money / float / Decimal-precision change; any oracle re-baseline.

**Gate (inherited from Phase 1 D-04, every wave):**
- **Gate (a):** byte-exact SMA_MACD oracle green (134 trades / `final_equity 46189.87730727451`);
  `mypy --strict` clean; determinism double-run byte-identical.
- **Gate (b):** clean W1 benchmark shows a measurable wall-clock improvement (**≥5%, single timed
  run** per Phase 1 D-04) vs the Phase 3 re-frozen baseline; re-freeze as the new locked reference.
  Peak memory tracked alongside.

</domain>

<decisions>
## Implementation Decisions

### Admission-rejection log treatment (PERF-03, the Phase-1-flagged spam)
- **D-01 (demote `error`→`warning` + cached `isEnabledFor(WARNING)` guard):** The per-bar admission
  rejection at `admission_manager.py:235-237` logs at `error` level every bar in W1 (coverage
  strategies C/D deplete cash → `FractionOfCash` sizing yields sub-`0.001 BTC` dust orders → the
  validator correctly refuses them with `"Quantity ... below minimum 0.001"`, order_validator.py:391).
  An out-of-cash condition is real and noteworthy, but it is **not a system error** — demote to
  `warning`. **Key measurement insight:** `.env` sets `ITRADER_LOG_LEVEL=ERROR` and the `Makefile`
  does `include .env` + `.EXPORT_ALL_VARIABLES`, so `make perf-w1` runs at **ERROR**. The frozen
  baseline was measured at ERROR with the `error`-level log **firing** (error ≥ ERROR → emits → costs
  CPU). Demoting to `warning` (30 < ERROR 40) means it **gates out at the benchmark level** — *the
  demotion itself realizes the W1 win* — while at the `INFO` real-run default it still emits, so the
  operator keeps out-of-cash visibility. The cached `isEnabledFor(WARNING)` guard additionally skips
  the eager f-string at this one site. **No sampling/rate-limiting needed.** The audit trail is
  unaffected — the PENDING→REJECTED state change + summary persists to `order_storage`
  (admission_manager.py:240-245) regardless of log level; the log is operator-visibility only.
  Both rejection reasons (dust `"Quantity below minimum"` AND genuine
  `"Insufficient cash: $X < $Y required"`, order_validator.py:509/523) flow through the same
  `validate_order_pipeline` → same log site → uniform treatment. **Rejected:** keep at `error`
  (over-states severity for an expected admission outcome); demote to `debug` (loses out-of-cash
  visibility the owner explicitly wants in real runs).

### Level-gate mechanism (PERF-03)
- **D-02 (central level-gate in `ITraderStructLogger`, logger.py — NOT per-callsite):** Add an
  `isEnabledFor` short-circuit inside each wrapper method (`debug/info/warning/error/critical`) so
  below-level calls return *before* the structlog processor chain runs. All 21 components route
  through this single wrapper, so one gate covers every callsite with no per-site guards. Shape:
  cache the stdlib logger (`self._stdlib = logging.getLogger(log_name)`) in `__init__`; the `bind()`
  path (which builds via `__new__`) must carry `_stdlib` onto the new instance. This is the
  documented "cached `isEnabledFor`/bool" of criterion #1 and *is* the ~6% W1 sink (the pipeline runs
  on below-level calls today). **Rejected:** per-callsite guards everywhere (the owner explicitly does
  not want a guard at every log); structlog's native `make_filtering_bound_logger` as `wrapper_class`
  (equivalent, but the existing `ITraderStructLogger` wrapper keeps the control in our own code and
  matches the established design).

### Eager-argument residual (PERF-03)
- **D-03 (leave the admission list-comp arg as-is):** The central gate skips the *pipeline* but
  **cannot** skip eager argument construction — Python evaluates args before the call reaches any
  central method, so this is not centralizable in principle. The only hot-path callsite with an
  expensive eager arg is the admission line's `[msg.message for msg in validation_result.errors]`
  (a 1–2 element comprehension); every other hot log call passes already-in-hand values with lazy
  `%s`/kwargs formatting. After the central gate, that residual is microseconds over a 240 s run —
  far under the ≥5% gate-(b) bar — so a one-off guard *or* a lazy-callable API would be special-casing
  for ~zero gain. Leaving it is the choice most consistent with "don't single out one line."
  **Rejected:** naive lazy-pass (`pass validation_result.errors`) — changes the *emitted content*
  (`%s` renders error-object reprs, not `.message`), violating criterion #3; content-safe lazy
  `__str__` wrapper — complexity for negligible payoff; targeted guard — the one-off the owner wanted
  to avoid.

### `debug()` removal scope (PERF-03, criterion #1)
- **D-04 (hot-path-only curated removal, per-line sign-off — NOT blanket delete):** The central gate
  (D-02) makes all `debug()` near-free, so "removed from the per-bar path" is satisfied for cost. On
  top of that, planning **reviews the per-bar/hot-path `debug()` callsites one-by-one** and proposes
  delete-vs-keep **per line for owner sign-off** (mirrors Phase 3 D-04). **Curated, not blanket** —
  because the operationally-meaningful lines the owner needs for live trading are *currently at
  `debug`*, not `info`: `'Strategy signal'` (strategies_handler.py:255), `'Order executed'`
  (simulated.py:298), `'Processing signal'`/`'OrderEvent sent'` (order_handler.py:135/147). These are
  **kept** (gated — free at the ERROR backtest level, available when running live at DEBUG). **Deleted**
  are the redundant internal-mechanics debug lines never needed even when debugging live:
  `'Position updated'`/`'Position market values updated'` (position_manager.py:198/273), the
  cash-bookkeeping lines (`'Cash reserved'`, `'Margin locked/released'`, `'Fill cash flow applied'`,
  cash_manager.py), `'Processed signal ... operations completed'` (admission_manager.py:383), etc.
  **`info()` is never touched** (all `info` operational logging is safe); **levels are unchanged** (no
  `debug`→`info` promotion this phase). Scope is **hot-path log calls only** — no whole-codebase
  logging audit. **Rejected:** blanket-delete the hottest debug (would delete the live-trading lines);
  keep-all-rely-on-gate-only (keeps the internal-mechanics noise and only satisfies "removed" by the
  gate's documented reading).

### `get_type_hints` memoization (PERF-04)
- **D-05 (module-level `@functools.cache` helper keyed by exact class; route both sites; memoize the
  raw dict):** Add `@cache def _declared_hints(cls): return get_type_hints(cls)`. `type(self)` gives
  the concrete subclass, so each resolves once; thread-safe in live mode (`functools.cache` locks
  internally); no manual invalidation (annotations are fixed at import; strategy-class count is
  small/bounded); `mypy --strict`-clean (`def _declared_hints(cls: type[Strategy]) -> dict[str, Any]`).
  Route **both** `to_dict` (base.py:356, hot — per signal) **and** `_apply_params` (base.py:147, cold
  — construct/reconfigure) through the helper for one consistent path; per-instance `getattr` stays
  per-instance. The cached dict is **shared → read-only**; both sites already only iterate keys (never
  mutate, never `.pop` from it). Byte-identical output by construction (same function, cached → same
  keys + order → identical snapshot). **Investigation finding (informs why memoize, not remove):**
  *neither* site uses the resolved annotation *types* — `to_dict` reads only the keys, and
  `_apply_params` gets its enum-coercion targets from the hand-maintained `_COERCE` dict
  (base.py:63/177), not from `hints[nm]`. So the expensive resolution is technically discarded — but
  after memoization the per-signal cost is a dict lookup regardless, so removing resolution would save
  only a one-time-per-class cost while adding key-ordering/byte-identity risk in a byte-exact phase.
  **Rejected:** replace with a names-only `__mro__`/`__annotations__` walk (~zero hot-path gain after
  caching + ordering risk); class-attribute cache (inheritance/keying hazards, more moving parts);
  `to_dict`-only memoization (two divergent paths for the same resolution).

### Full-disable kill-switch (PERF-03 companion)
- **D-08 (new `ITRADER_DISABLE_LOGS` boolean, checked first in the central guard):** Add an
  `ITRADER_`-prefixed boolean env var (via pydantic `Settings`, matching the `ITRADER_LOG_LEVEL`
  idiom), resolved **once and cached**, checked at the top of each `ITraderStructLogger` guard method
  to short-circuit *all* logging unconditionally (a cached bool, marginally cheaper than
  `isEnabledFor`). For a fully-silent backtest set `ITRADER_DISABLE_LOGS=true`. Connected to the
  central guard from D-02. **Not strictly required for gate (b)** (the ERROR benchmark level already
  gates the hot logs) — it is a convenience + marginal extra win that also silences the rare remaining
  `error`/`critical` logs. **Planner discretion:** whether the switch *also* drops the root logger
  level (logger.py:177) so third-party/stdlib logs are silenced too, for a true full-off (the wrapper
  guard alone only covers calls routed through `ITraderStructLogger`). **Rejected (owner chose the
  boolean):** extend `ITRADER_LOG_LEVEL` with an `OFF`/`NONE` sentinel (one connected mechanism, no new
  surface) — viable but the owner preferred an explicit dedicated kill-switch.

### Behavior-preservation proof (criterion #3 — gate (a) does NOT observe logs/snapshots)
- **D-06 (logging — audit + gate-transparency test):** The oracle observes only trade count + final
  equity, and e2e observes result leaves — *neither observes logs*. So criterion #3 needs its own
  drift lock (mirrors Phase 3 D-03 audit+test rigor). Lock via: (1) a written **audit** that every
  logging change is a *demote / central-gate / delete-debug* — none of which alters the content
  emitted at a given *enabled* level; (2) **one gate-transparency unit test** — above level the wrapper
  emits identical content+fields as a direct structlog call, below level nothing emits; plus assert the
  demoted admission line renders the **same content at `WARNING`** as the prior `error` content;
  (3) lean on the oracle/e2e/determinism for the numbers (logging changes cannot move them — which is
  itself the proof they are behavior-only on observed paths). **Rejected:** per-line before/after
  content tests for every touched log (more code, much asserting deleted lines no longer emit);
  emitted-log golden snapshot (heavy + brittle on timestamps/ordering/env — overkill since logs aren't
  an oracle-observed leaf).
- **D-07 (type hints — equivalence test + `to_dict` snapshot):** A dedicated equivalence test asserting
  `_declared_hints(cls) == get_type_hints(cls)` (same keys **and** order) plus a `to_dict` snapshot
  regression for a reference strategy. Direct mirror of Phase 3 D-03; byte-identical by construction.
  **Rejected:** equivalence-test-only (doesn't lock the full snapshot content/order end-to-end).

### Claude's Discretion
- Exact attribute name/shape of the cached stdlib-logger reference and the `bind()` carry-over (D-02),
  and the helper name/placement for `_declared_hints` (D-05).
- The precise per-line delete-vs-keep list for hot-path `debug()` (D-04) — planning proposes, owner
  signs off per line.
- Whether `ITRADER_DISABLE_LOGS` also lowers the root logger level for a true full-off (D-08).
- Exact placement/shape of the gate-transparency, admission-content, equivalence, and `to_dict`
  snapshot tests (D-06/D-07), within the stated contracts.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source of truth (the spike IS the research)
- `perf/results/PERF-BASELINE-RESULTS.md` — §2 ranked hotspot map (**hotspot #4** = hot-path logging,
  **hotspot #6** = `Strategy.to_dict` `get_type_hints`), §6 phase breakdown ("P3 — Hot-path logging
  discipline", "P4 — Cache `get_type_hints`"), §7 exit criteria. **Authoritative.**

### Milestone scope + requirements + gate
- `.planning/REQUIREMENTS.md` — **PERF-03** + **PERF-04** (this phase) + the milestone gate (a)/(b)
  definition.
- `.planning/milestones/v1.5-ROADMAP.md` — Phase 4 goal + success criteria (5 criteria).
- `.planning/ROADMAP.md` — Phase 4 entry + the captured **Phase-1 note** on the admission-rejection
  spam (the "discuss the HOW at Phase 4" instruction this discussion resolves; and the "do NOT touch
  `min_order_size`/sizing" lock) + the v1.5 behavior-preserving framing.
- `.planning/phases/01-perf-tooling-baseline/01-CONTEXT.md` — **D-04** (≥5% wall-clock, single timed
  run; gate (b) inherited milestone-wide) + the baseline/regression-guard tooling gate (b) uses.
- `.planning/phases/03-running-pnl-accumulator/03-CONTEXT.md` — precedent for the
  audit-the-invariant + dedicated equivalence/regression test pattern (D-03 there), reused here as
  D-06/D-07, and the propose-for-sign-off CONCERNS-cleanup convention (D-04 there), reused as D-04.

### Target code — logging (PERF-03)
- `itrader/logger.py` — `ITraderStructLogger` (the central gate site: `debug`/`info`/`warning`/
  `error`/`critical` at lines 222-240, `bind` at 199, `__init__` at 196); `setup_logging`
  (processor chain + `root_logger.setLevel`, lines 117-177); `_env_log_level` (ITRADER_LOG_LEVEL,
  line 26 — the D-08 sibling knob). **4-space indent.**
- `itrader/order_handler/admission/admission_manager.py` — line **235-237** (the per-bar admission
  rejection log to demote+guard, D-01); line 383 ('Processed signal' debug, delete candidate, D-04).
  **Tab indent.**
- `itrader/order_handler/order_validator.py` — line 391 (`"Quantity below minimum"` dust rejection,
  the W1 spam source) + 509/523 (`"Insufficient cash"`, the genuine out-of-cash reason) — both flow
  through `validate_order_pipeline`. **Read-only — explains the two rejection reasons.**
- Per-bar `debug()` delete/keep candidates (D-04, hot-path only): `order_handler/order_handler.py`
  :135/:147 (keep), `strategy_handler/strategies_handler.py`:255 (keep),
  `execution_handler/exchanges/simulated.py`:298 (keep); `portfolio_handler/position/position_manager.py`
  :198/:273 (delete), `portfolio_handler/cash/cash_manager.py` debug lines (delete). **Mixed indent —
  match each file (tabs in handlers; 4 spaces in `position_manager.py`).**
- `itrader/config/settings.py` — `Settings(BaseSettings)` `ITRADER_` env layer (where
  `ITRADER_DISABLE_LOGS` is declared, D-08).

### Target code — type hints (PERF-04)
- `itrader/strategy_handler/base.py` — `to_dict` (line 345, `get_type_hints` at **:356**, hot — per
  signal); `_apply_params` (line 127, `get_type_hints` at **:146/147**, cold); `_COERCE` (line 63,
  the hand-maintained enum-coercion map used at :177 — confirms resolved types are unused). **Tab
  indent.**

### Gate (a) — correctness lock (held, not changed) + test homes
- `tests/integration/test_backtest_oracle.py` — byte-exact SMA_MACD oracle
  (134 / `46189.87730727451`). (Per memory `oracle-test-location`: this is the oracle; `tests/golden`
  is artifacts.)
- `tests/unit/strategy/` — home for the PERF-04 equivalence + `to_dict` snapshot tests (D-07).
- `tests/unit/` (logging) — home for the gate-transparency + admission-content tests (D-06).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The central wrapper already exists** — `ITraderStructLogger` (logger.py:180) is the single
  chokepoint all 21 components route through (`get_itrader_logger().bind(component=...)`), so the
  level-gate (D-02) lands in one place and covers everything. No new abstraction.
- **The env-level knob already exists** — `_env_log_level` / `ITRADER_LOG_LEVEL` (logger.py:26) and
  pydantic `Settings.log_level`; `ITRADER_DISABLE_LOGS` (D-08) is a sibling boolean in the same layer.
- **`get_type_hints` is already centralized in `base.Strategy`** — only two call sites (`:356`,
  `:146`), both read-only key iteration, so one `@cache` helper cleanly serves both (D-05).
- **The audit trail is independent of the log** — `add_state_change(REJECTED, ...)` +
  `add_order` (admission_manager.py:240-245) persist the rejection regardless of log level, so
  demoting/gating the log loses no forensic record (D-01).

### Established Patterns
- **structlog filters at the handler, not the wrapper (today)** — `setup_logging` uses the default
  `BoundLogger` + `root_logger.setLevel`, so below-level calls pay the full 9-processor pipeline
  before being dropped. That *is* hotspot #4; a wrapper-level `isEnabledFor` gate fixes it at the
  source (D-02).
- **`.env` + Makefile env-export** — `include .env` + `.EXPORT_ALL_VARIABLES` (Makefile:2-3) means
  `ITRADER_LOG_LEVEL=ERROR` is live for `make perf-w1`. This is *why* demoting `error`→`warning` gates
  the admission log out of the benchmark (D-01) — and why D-08's `ITRADER_DISABLE_LOGS` would be set
  the same way.
- **Indentation hazard (CLAUDE.md):** `logger.py` and `base.py`... `logger.py` is **4-space**;
  `base.py` is **tab**; `admission_manager.py` is **tab**; `position_manager.py` is **4-space**.
  Match each file exactly — never normalize.
- **Phase 3's "audit the invariant + dedicated equivalence test, no hot-path runtime guard"** (03-CONTEXT
  D-03/D-04) is the precedent reused for D-06/D-07 (proof without re-paying cost) and D-04
  (propose-for-sign-off cleanups).

### Integration Points
- The level-gate is internal to `ITraderStructLogger` — no event-queue, handler, or ABC change; all
  callers keep their `self.logger.debug(...)` calls unchanged (D-02).
- `_declared_hints` is a module-level helper in `base.py`; `to_dict`/`_apply_params` swap their inline
  `get_type_hints(type(self))` for `_declared_hints(type(self))` — local, no public API change (D-05).
- `ITRADER_DISABLE_LOGS` resolves through the existing `Settings`/env layer and is read once at logger
  construction (D-08).

</code_context>

<specifics>
## Specific Ideas

- The W1 win on logging comes from the **demotion gating against the ERROR benchmark level**, not from
  sampling — confirmed by `.env`'s `ITRADER_LOG_LEVEL=ERROR` (D-01). Keep `warning` so real runs at
  `INFO` still surface out-of-cash conditions.
- The central gate (D-02) is the *whole* logging win; the eager-arg residual is left alone (D-03) and
  the `debug()` removal is a *curated, signed-off* refinement (D-04) — not a blanket sweep.
- `get_type_hints` is memoized, **not removed** — the resolution is technically unused, but memoizing
  already collapses the per-signal cost to a lookup, so removal is deferred to avoid byte-identity risk
  (D-05).
- `ITRADER_DISABLE_LOGS=true` is the intended "silent backtest" lever (D-08).

</specifics>

<deferred>
## Deferred Ideas

- **Whole-codebase logging-policy review + `debug`→`info` promotions for live observability** — the
  signal/order events the owner needs in live are currently at `debug`, so they won't show in a live
  `INFO` run; promoting them (and a broader per-level audit across non-hot code) is a logging-policy
  change with no perf payoff (gates out at the ERROR benchmark) and changes the INFO emitted surface.
  Belongs in **N+4 Live Trading Readiness**, not this behavior-preserving perf phase (D-04, scope:
  hot-path only).
- **Remove `get_type_hints` resolution entirely** — neither call site uses the resolved types (only
  the merged name set); a names-only `__mro__`/`__annotations__` walk would avoid resolution, but saves
  only a one-time-per-class cost after memoization and risks changing snapshot key-ordering. Revisit in
  a future *non-byte-exact* cleanup phase (D-05).
- **Extend `ITRADER_LOG_LEVEL` with an `OFF`/`NONE` sentinel** — an alternative to the D-08 boolean
  (one connected mechanism, no new config surface); not chosen now but noted if the boolean ever proves
  redundant with the level system.

</deferred>

---

*Phase: 4-hot-path-discipline*
*Context gathered: 2026-06-24*
