# Phase 4 — Logging Behavior-Preservation Audit (D-06)

**Produced:** 2026-06-24 (Task 4, Plan 04-01)
**Status:** LOCKED — establishes, in writing, that every Phase-4 (PERF-03) logging change
belongs to exactly one of three behavior-preserving classes, none of which alters the
content emitted at a given *enabled* level. This is the written half of the D-06 drift
lock; the executable half is `tests/unit/core/test_logging_gate.py`.

**No oracle re-baseline. No numeric surface. This phase changes log VOLUME, never emitted
log CONTENT at an enabled level.**

---

## Locked Claim (one sentence)

> Every Phase-4 logging change is a *central-gate* (D-02), a *demote* (D-01), or a
> *delete-debug* (D-04); the byte-exact SMA_MACD oracle observes only trade count + final
> equity and the e2e matrix observes only result leaves — **neither observes logs** — so a
> logging change cannot move an observed number, which is itself the proof these changes are
> behavior-only on every path the correctness gates watch (D-06).

---

## The Three Behavior-Preserving Change Classes

### Class 1 — Central level-gate (D-02)

**What changed:** `itrader/logger.py` — each `ITraderStructLogger` wrapper method
(`debug`/`info`/`warning`/`error`/`critical`, plus the `warn` alias) now short-circuits via
a cached `self._stdlib.isEnabledFor(<level>)` check *before* the 9-processor structlog
pipeline runs. `__init__` caches `self._stdlib = logging.getLogger(log_name)`; `bind()`
(which builds via `__new__`, skipping `__init__`) explicitly carries `_stdlib` onto the new
instance. `exception()` is left as an always-emit path.

**Why it is behavior-only:** previously a below-level call walked all 9 processors and was
dropped at the stdlib handler (`root_logger.setLevel`); now it returns earlier. The *drop
decision is identical* — same level threshold, same `isEnabledFor` semantics the stdlib
handler already applied — only the drop happens *before* the pipeline instead of *after* it.
An **enabled** call takes the unchanged path: it still calls `self.logger.<level>(...)` with
the same event + args, so the emitted content + fields are byte-identical. This is the whole
~6% W1 / ~22% W2 logging win (hotspot #4): the pipeline no longer runs on below-level calls.

**Companion — D-08 kill-switch:** a module-level cached `_DISABLE_LOGS` (resolved once from
`ITRADER_DISABLE_LOGS` via `os.environ`, mirroring the existing `_env_json_logs` idiom — it
must NOT instantiate `Settings()` at import, Pitfall 8) is checked FIRST in each guard. When
`False` (the default — backtest path is env-free) it is inert; when `True` it short-circuits
every level unconditionally for a fully-silent run. Default-off means it changes nothing on
the oracle path.

**Drift lock:** `test_logging_gate.py::test_above_level_emits_identical_content`,
`::test_below_level_emits_nothing`, `::test_error_emits_at_error_level`,
`::test_bind_carries_stdlib_for_gate`, `::test_disable_logs_silences_every_level`,
`::test_env_disable_logs_parses_truthy_values`.

### Class 2 — Demote (D-01)

**What changed:** `itrader/order_handler/admission/admission_manager.py` — the per-bar
admission-rejection log was demoted from `error` to `warning` and wrapped in a cached
`self.logger._stdlib.isEnabledFor(logging.WARNING)` guard around the eager f-string +
`[m.message for m in validation_result.errors]` list-comp (D-03: this is the ONE hot callsite
with an expensive eager arg, which the central gate cannot skip because Python evaluates args
before the call).

**Why it is behavior-only:**
- The emitted **content** is unchanged. The call keeps the established lazy `%s` shape
  (`self.logger.warning('%s - %s', error_msg, [...])`); demoting `error → warning` changes
  only the `level` field on the record, not the rendered message string or its positional
  args. `test_logging_gate.py::test_admission_line_warning_renders_same_content_as_error`
  asserts the rendered event string is byte-identical between the prior `error` call and the
  new `warning` call (only the `level` field differs).
- The **audit trail is untouched.** The forensic record is the `add_state_change(REJECTED,
  ...)` + `order_storage.add_order(...)` block immediately below the log — it runs regardless
  of log level and was not modified (verified: the diff does not touch `add_state_change` /
  `add_order`). The log is operator-visibility only.
- The **W1 win** comes from the level math against the benchmark environment: `.env` sets
  `ITRADER_LOG_LEVEL=ERROR` and the `Makefile` does `include .env` + `.EXPORT_ALL_VARIABLES`,
  so `make perf-w1` runs at ERROR. `warning` (30) < `ERROR` (40) ⇒ the line **gates out at
  the benchmark level** (the demotion itself realizes the win), while at the `INFO` real-run
  default it still emits so operators keep out-of-cash visibility. Both rejection reasons
  (dust `"Quantity below minimum"` and genuine `"Insufficient cash"`) flow through the same
  `validate_order_pipeline` → same site → uniform `warning` treatment.

**Drift lock:** `test_logging_gate.py::test_admission_line_warning_renders_same_content_as_error`
and `::test_admission_demoted_warning_gates_out_at_error_emits_at_info`.

### Class 3 — Delete-debug (D-04)

**What changed:** Exactly 8 owner-signed-off internal-mechanics `debug()` calls were deleted
(per-line sign-off at the blocking checkpoint, no amendments):

| File | Deleted debug line | Indent |
|------|--------------------|--------|
| `portfolio_handler/position/position_manager.py` | `'Position updated'` | 4-space |
| `portfolio_handler/position/position_manager.py` | `'Position market values updated'` | 4-space |
| `portfolio_handler/cash/cash_manager.py` | `'Fill cash flow applied'` | 4-space |
| `portfolio_handler/cash/cash_manager.py` | `'Cash reserved'` | 4-space |
| `portfolio_handler/cash/cash_manager.py` | `'Cash reservation released'` | 4-space |
| `portfolio_handler/cash/cash_manager.py` | `'Margin locked'` | 4-space |
| `portfolio_handler/cash/cash_manager.py` | `'Margin released'` | 4-space |
| `order_handler/admission/admission_manager.py` | `'Processed signal ... operations completed'` | tab |

**KEEP (live-trading visibility, gated-free at ERROR, available at DEBUG):**
`order_handler.py` `'Processing signal'` / `'OrderEvent sent'`, `strategies_handler.py`
`'Strategy signal'`, `simulated.py` `'Order executed'` — all confirmed still present.

**Why it is behavior-only:** a removed `debug()` line was never an oracle-observed or
e2e-observed leaf — the oracle reads trade count + final equity, the e2e matrix reads result
leaves, and neither inspects log output. The deleted lines are pure internal bookkeeping. No
`info()` line was touched and no level was changed (no `debug → info` promotion). The diff
contains only `.debug(` deletions (verified: 8 removed, 0 `.info(`/level edits) and introduces
no mixed-indent (4-space files stay 4-space, the tab file stays tab).

---

## Why the Correctness Gates Cannot Catch a Logging Regression (and why that is fine)

The byte-exact SMA_MACD oracle (`tests/integration/test_backtest_oracle.py`, 134 trades /
`final_equity 46189.87730727451`) and the e2e matrix assert only on *trade/result leaves* —
they have no log assertions. So a logging change is invisible to them by construction. This
cuts both ways:

1. It means a logging change **cannot move the numbers** — which is the positive proof that
   these changes are behavior-only on every observed path.
2. It means the oracle/e2e are **not** the drift lock for logging content. That is why D-06
   adds the dedicated unit-level lock in `tests/unit/core/test_logging_gate.py` (this audit's
   executable half), exactly mirroring the Phase 3 D-03 "audit the invariant + dedicated
   equivalence/regression test" rigor (`03-INVARIANT-AUDIT.md`).

No hot-path runtime guard is re-added by the tests — re-paying the gate cost is precisely
what this phase removes; the gate lives once, in the wrapper.

---

## Verification at Audit Time

- Gate (a): `tests/integration/test_backtest_oracle.py` byte-exact (134 / `46189.87730727451`).
- `tests/unit/core/test_logging_gate.py` green (8 tests: gate-transparency, below-level,
  bind carry-over, disable-logs, env parsing, admission content-equivalence, admission gating).
- `mypy --strict` clean on every touched source file.
- Touched-domain unit suites green (`tests/unit/{portfolio,order,core}/`, 666 passed).

## Commit Trail

| Class | Commit | Decision tags |
|-------|--------|---------------|
| RED (tests) | `cfe392e` | D-02, D-08, D-01, D-06 |
| Central gate + kill-switch | `25402ab` | D-02, D-08 |
| Demote + guard | `3adfb27` | D-01, D-03, D-06 |
| Delete-debug | `1b0a712` | D-04 |

---

*Phase: 04-hot-path-discipline · Plan: 04-01 · Audit produced 2026-06-24*
