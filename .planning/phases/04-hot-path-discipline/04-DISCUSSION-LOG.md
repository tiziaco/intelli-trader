# Phase 4: Hot-Path Discipline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 4-hot-path-discipline
**Areas discussed:** Admission-log treatment, Level-gate mechanism + scope, get_type_hints memoization, Behavior-preservation proof, Full-disable kill-switch

---

## Admission-log treatment (PERF-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Level-gate, keep at error | Cached level check, keep error severity | |
| Demote error→warning, then gate | Warning + level-gate; visible in real runs, gated in benchmark | ✓ |
| Demote to debug, then gate | Debug-level, effectively silent | |

**User's choice:** Demote `error`→`warning` + cached `isEnabledFor(WARNING)` guard.
**Notes:** Owner's rationale — an out-of-cash portfolio is a real, noteworthy condition they want to
see logged in a real-life run, so it must not be silenced (rules out debug), but it's not a system
error. Discovery during discussion: `.env` sets `ITRADER_LOG_LEVEL=ERROR` and the Makefile exports it
to `make perf-w1`, so the benchmark runs at ERROR — demoting to `warning` (30 < ERROR 40) gates it out
of the timed run (the W1 win) while still emitting at the `INFO` real-run default. Confirmed the audit
trail (PENDING→REJECTED persisted to storage) is independent of the log, and the spam is the dust
"Quantity below minimum" rejection driven by cash depletion (distinct from the "Insufficient cash"
reason; both flow through the same log site).

## Level-gate mechanism + scope (PERF-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Central gate in ITraderStructLogger | Single chokepoint, no per-callsite guards | ✓ |
| Per-callsite guards | isEnabledFor at each hot site | |

**User's choice:** Central level-gate in `ITraderStructLogger` (logger.py wrapper).
**Notes:** Owner's instinct — "do it properly, centralize it, I don't want a guard at every log."
Confirmed correct: `setup_logging` uses the default `BoundLogger` with filtering only at the stdlib
handler, so every below-level call pays the full 9-processor pipeline today (that *is* hotspot #4). The
wrapper is the single chokepoint for all 21 components. Clarified the distinction between the two costs:
the pipeline cost (centralizable, centralized via D-02) vs eager-arg construction (not centralizable —
Python evaluates args before the call).

### Eager-argument residual

| Option | Description | Selected |
|--------|-------------|----------|
| Leave args as-is | Negligible residual; no special-casing | ✓ |
| One targeted guard at the line | Skips f-string + list-comp at the single hot line | |
| Content-safe lazy wrapper | Defer list-comp via lazy `__str__` | |

**User's choice:** Leave the admission list-comp arg as-is.
**Notes:** Owner pushed to "do it properly / centralize the eager-arg logic too." Clarified this isn't
achievable — argument evaluation can't be centralized (Python semantics), and the admission list-comp
is the *only* hot callsite with an expensive eager arg, so there's no fleet of lines to centralize and
leaving it is the choice most consistent with "don't single out one line." Naive lazy-pass was rejected
as it would change emitted content (criterion #3).

### debug() removal scope

| Option | Description | Selected |
|--------|-------------|----------|
| Keep + rely on gate | No deletion; gate makes debug near-free | |
| Curated delete + keep signal/order | Delete redundant internal-mechanics debug, keep+gate live-relevant | ✓ (hot-path only) |
| Blanket delete hottest | Delete all hot per-bar debug | |

**User's choice:** Curated, hot-path-only review with per-line sign-off (combined two follow-up answers:
keep signal/order events; scope the review to hot-path only).
**Notes:** Owner wanted to keep signal-generated / order-executed messages for live trading. Caught that
those exact events are currently at `debug` level (not `info`), so a blanket delete would remove them —
hence curated: keep+gate the live-relevant lines, delete only redundant internal-mechanics debug. Owner
then proposed a whole-codebase per-line review incl. debug→info promotions; redirected to hot-path-only
scope for this perf phase (promotions deferred to N+4 Live Trading Readiness). `info()` never touched.

## get_type_hints memoization (PERF-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Module-level @functools.cache helper | Keyed by exact class, thread-safe | ✓ |
| Class-attribute cache | Store on the class | |

**User's choice:** Module-level `@functools.cache` helper keyed by exact class.

| Option | Description | Selected |
|--------|-------------|----------|
| Memoize raw dict, route both sites | One helper serves to_dict + _apply_params | ✓ |
| Replace with names-only MRO walk | Drop get_type_hints entirely | |
| Note removal as deferred cleanup | Memoize now, capture removal as deferred | (folded into Deferred) |

**User's choice:** Memoize the raw `get_type_hints` dict; route both `to_dict` and `_apply_params`
through the helper.
**Notes:** Owner asked "do I actually need this / why only here?". Investigation found neither site uses
the resolved annotation *types* (to_dict reads only keys; _apply_params coerces via the hand-maintained
`_COERCE` map, not `hints[nm]`), so resolution is technically discarded. But after memoization the
per-signal cost is a lookup regardless, so removal saves only a one-time-per-class cost while risking
snapshot key-ordering — hence memoize, not remove. The removal-investigation captured as a deferred
cleanup idea.

## Behavior-preservation proof (criterion #3)

| Option | Description | Selected |
|--------|-------------|----------|
| Audit + gate-transparency test | Audit + one transparency test + admission-content assertion | ✓ |
| Targeted content test per change | Before/after assertion per touched line | |
| Emitted-log golden snapshot | Capture + diff all emitted logs | |

**User's choice (logging):** Audit + gate-transparency unit test + admission-content assertion;
lean on oracle/e2e/determinism for numbers.

| Option | Description | Selected |
|--------|-------------|----------|
| Equivalence test + to_dict snapshot | memoized==fresh + reference-strategy snapshot | ✓ |
| Equivalence test only | Just memoized==fresh | |

**User's choice (type hints):** Dedicated equivalence test (memoized == fresh, keys+order) +
`to_dict` snapshot regression.
**Notes:** Established that gate (a)'s oracle observes only numbers, not logs/snapshots, so criterion #3
needs its own drift locks — mirroring the Phase 3 D-03 audit+test pattern.

## Full-disable kill-switch (PERF-03 companion)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend ITRADER_LOG_LEVEL with OFF/NONE | One connected mechanism, no new surface | |
| New ITRADER_DISABLE_LOGS boolean | Dedicated cached-bool kill-switch in the guard | ✓ |
| Defer — keep Phase 4 minimal | Skip a full-off switch this phase | |

**User's choice:** New `ITRADER_DISABLE_LOGS` boolean, checked first in the central guard.
**Notes:** Owner asked whether they'd get an env var to fully disable logs for backtest connected to the
central guard. Flagged it isn't required for gate (b) (ERROR already gates the hot logs) but is a
reasonable in-scope extension. Owner chose the explicit dedicated boolean over reusing the level knob.

---

## Claude's Discretion

- Exact attribute name/shape of the cached stdlib-logger reference and `bind()` carry-over (D-02);
  helper name/placement for `_declared_hints` (D-05).
- The precise per-line delete-vs-keep list for hot-path `debug()` (D-04) — planning proposes, owner
  signs off per line.
- Whether `ITRADER_DISABLE_LOGS` also lowers the root logger level for a true full-off (D-08).
- Exact placement/shape of the gate-transparency, admission-content, equivalence, and `to_dict`
  snapshot tests (D-06/D-07).

## Deferred Ideas

- Whole-codebase logging-policy review + `debug`→`info` promotions for live observability → N+4 Live
  Trading Readiness.
- Remove `get_type_hints` resolution entirely (names-only walk) → future non-byte-exact cleanup phase.
- Extend `ITRADER_LOG_LEVEL` with an `OFF`/`NONE` sentinel → alternative to the D-08 boolean if it ever
  proves redundant.
