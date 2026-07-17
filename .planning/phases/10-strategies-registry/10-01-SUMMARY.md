---
phase: 10-strategies-registry
plan: 01
subsystem: core
tags: [codec, serialization, policies, money-boundary, security]
status: complete
requires:
  - itrader/core/sizing.py (SizingPolicy + SLTPPolicy union aliases, the six frozen policies)
  - itrader/core/money.py (to_money — the Decimal string-path entry point)
  - itrader/config (TrailType — function-local import only)
provides:
  - encode_policy / decode_policy — the D-03 reconstruction-safe policy wire format
  - default_policy_registry — kind->class map derived from both unions, overlay-injectable
  - PolicyCodecError / UnknownPolicyKindError — the loud-reject surface
  - PolicyRegistry — dict[str, type] type alias
affects:
  - D-01 rehydrate (10-0x) — needs decode_policy to rebuild instance policies
  - D-04 config_json (10-0x) — the tagged policy blob is a config_json member
  - D-09 runtime add/reconfigure (10-0x) — decodes policies from STRATEGY_COMMAND payloads
tech-stack:
  added: []
  patterns:
    - tagged-union codec with a derived, injectable kind->class registry
    - get_type_hints + explicit localns for quoted forward-ref resolution
    - Decimal-as-string money boundary across JSON
key-files:
  created:
    - itrader/core/policy_codec.py
    - tests/unit/core/test_policy_codec.py
  modified: []
decisions:
  - "D-03 implemented: tagged-union codec, generic dataclass introspection, injectable registry, Decimals as strings"
  - "D-05 implemented: codec placed in core/, imports nothing from itrader outside core at module level"
  - "Deviation: dropped the plan's functools.cache memo — it broke the locked Phase-5 cache-classification gate and its hot-path justification does not transfer to this cold path"
metrics:
  duration: ~18m
  completed: 2026-07-17
  tasks: 2
  files: 2
  tests_added: 16
---

# Phase 10 Plan 01: D-03 Policy Codec Summary

Reconstruction-safe tagged-union serializer/deserializer for the six frozen sizing/SLTP policy
value objects, placed in `core/` — the money boundary and the allowlist-gated decode seam that
every downstream P10 capability (rehydrate, `config_json`, runtime `add`) builds on.

## What Was Built

`itrader/core/policy_codec.py` (4-space, 305 lines) exporting `encode_policy`, `decode_policy`,
`default_policy_registry`, `PolicyRegistry`, `PolicyCodecError`, `UnknownPolicyKindError`.

A policy self-describes on the wire:

```json
{"kind": "FractionOfCash", "fraction": "0.95", "step_size": null}
```

**Why it exists (D-03):** `Strategy.to_dict()` renders policies through `repr()`
(`"FractionOfCash(Decimal('0.95'))"`). Rebuilding from that form would require interpreting
stored text as Python source — and a `kind` tag arrives from an external `STRATEGY_COMMAND`
payload or a `config_json` row, so that would turn operator-supplied config into arbitrary code
execution. The codec makes it unnecessary.

**Key mechanisms:**

- **Derived registry** — `default_policy_registry()` builds kind->class from
  `get_args(SizingPolicy)` + `get_args(SLTPPolicy)`. Hand-listing is exactly how
  `PercentFromDecision` got omitted once (by the CONTEXT's own D-03 list). An optional
  `overlay` merges over the derived default so the owner's private-repo IP policies register
  without `itrader` importing them. A fresh dict is returned per call — callers cannot mutate
  the shared default.
- **Class resolution is a dict lookup and nothing else** — the injected registry IS the
  allowlist (T-10-01/T-10-02). No dynamic module import; no blob field is ever interpreted as
  source text.
- **Money boundary** — Decimals encode via `str(value)` and re-enter via `to_money`
  (`Decimal(str(x))`). A JSON float is refused outright rather than silently rounded; non-finite
  Decimals (NaN/Infinity) are refused on encode (T-10-04).
- **The `trail_type` trap** — `PercentFromFill.trail_type` is the quoted forward ref
  `"TrailType | None"`, so `dataclasses.fields()[i].type` returns an unusable raw string.
  Resolution uses `get_type_hints` with an explicit `localns` sourced from a **function-local**
  `itrader.config` import — mirroring `sizing.py::__post_init__` and preserving the core->config
  direction (a module-level import would invert it and break inertness).
- **Fail-loud coercion** — an unhandled declared type raises rather than passing an uncoerced
  value into a frozen policy (T-10-03). Unknown blob fields and missing required fields also
  reject.
- **Free re-validation** — `decode_policy` constructs the class normally, so each
  `__post_init__` re-validates on the way back; the codec deliberately does not duplicate those
  validators (they would drift).

`tests/unit/core/test_policy_codec.py` — 9 test functions / **16 cases** covering round-trip for
all six policies (+ the step_size and trailing variants), the money boundary, JSON cycle,
enum-in-optional-union, registry derivation, unknown-kind reject, `__post_init__` re-validation,
overlay registration, and the non-finite encode backstop.

## Key Decisions

- **D-03 / D-05 implemented as specified** — codec in `core/`, generic dataclass introspection,
  injectable registry, Decimals as strings, loud unknown-kind reject.
- **Registry derived, not hand-listed** — makes omitting a future union member structurally
  impossible.
- **`_resolved_hints` is deliberately NOT memoized** — see Deviations.

## Deviations from Plan

### 1. [Rule 1 — Bug] Dropped the planned `functools.cache` memo on the hint resolver

- **Found during:** Task 2 full-sweep verification (`pytest tests/unit tests/integration`).
- **Issue:** The plan directed *"memoize the per-class resolved hints with `functools.cache`,
  copying the `base.py:130-133` `_declared_hints` idiom."* Implementing that literally added a
  **4th** memoization-decorator site under `itrader/`, breaking the locked Phase-5 governance
  gate `tests/integration/test_cache_classification.py`, which asserts the applied-decorator
  surface is **exactly the 3 documented sites** (`bar_feed` / `time_parser` / `base.py`) listed
  in `docs/CACHE-CLASSIFICATION.md`. This failure was NOT visible from the plan's own
  acceptance criteria (which scope test runs to `tests/unit/core tests/unit/storage`); it only
  surfaced in the plan's broader `<verification>` sweep.
- **Fix:** Removed the decorator; `_resolved_hints` resolves per call.
- **Why this and not the alternatives:**
  - *Register the 4th site* (edit `docs/CACHE-CLASSIFICATION.md` + the gate test) would touch
    two files outside this plan's declared `files_modified`, one a locked cross-phase governance
    gate whose test name literally encodes "three" — risky to mutate from a parallel worktree
    where sibling wave agents may also touch shared files.
  - *Hand-rolled module-level dict memo* would slip past the gate's `self._cache` field scan —
    an undocumented cache is strictly worse than no cache, so this was rejected outright.
  - *No memo* satisfies every stated `must_have` truth and acceptance criterion (none mention
    memoization) and stays entirely within declared scope.
- **The plan's premise did not transfer:** `base.py`'s own comment justifies its cache by
  HOT-path pressure — *"`to_dict` (hot — per signal snapshot) re-walked the MRO on every call."*
  This codec is a COLD path: it runs at rehydrate, runtime `add`, and `reconfigure` — never per
  bar. The memo would buy nothing measurable and would additionally retain a strong reference to
  every app-supplied overlay class. The reasoning is recorded in the `_resolved_hints` docstring
  so a future reader does not "helpfully" re-add it.
- **Files modified:** `itrader/core/policy_codec.py`
- **Commit:** `8c93d2c9`

### 2. [Rule 2 — Missing critical coverage] Non-finite backstop needed a validation-free carrier

- **Found during:** Task 1 test design.
- **Issue:** The plan's Test 8 specified *"encoding a policy whose Decimal field is
  `Decimal("NaN")` raises `PolicyCodecError`"*. Probing proved this **unreachable via any
  shipped policy**: every policy's `__post_init__` runs an ordering comparison against the
  value, and `Decimal("NaN") <= Decimal("1")` raises `InvalidOperation` at **construction** —
  before `encode_policy` is ever called.
- **Fix:** The backstop test uses a validation-free frozen dataclass (`_NonFiniteCarrier`)
  registered the same way an overlay policy would be. This is not a contrivance: it is exactly
  the real exposure — app-supplied **overlay** policies (the D-03 injectable-registry seam) are
  under no obligation to validate finiteness, so the codec's own encode-side guard is their only
  protection. Tested against NaN, Infinity, and -Infinity.
- **Files modified:** `tests/unit/core/test_policy_codec.py`
- **Commit:** `c2d5cb20`

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/unit/core/test_policy_codec.py -x -q` | **16 passed** |
| `pytest tests/unit/core/test_policy_codec.py -k decimal` | **3 passed** |
| `pytest tests/integration/test_okx_inertness.py` (**MANDATORY**) | **4 passed** |
| `mypy itrader/core/policy_codec.py` (strict, no new ignores) | **clean** |
| `mypy` (whole project, 240 files) | **clean** |
| `pytest tests/unit tests/integration -q` | **2251 passed, 2 skipped** (incl. the byte-exact backtest oracle) |
| `pytest tests/unit/core tests/unit/storage -q` | **224 passed** |
| `tests/integration/test_cache_classification.py` | **4 passed** (was RED — see Deviation 1) |

**Source gates:** `eval(` = 0 · `import importlib` = 0 · `Decimal(float` = 0 · `get_args` = 6
(incl. both literal `get_args(SizingPolicy)` / `get_args(SLTPPolicy)` key-link occurrences) ·
`D-03` = 12 · `D-05` = 2 · tabs = 0 (4-space, matching `core/`) · no module-level import of
`sqlalchemy` / `ccxt` / `itrader.config`.

**Marker:** `-m unit` selects all 16; `-m "not unit"` deselects all 16 — auto-applied by folder.
No `__init__.py` in `tests/unit/core/` (verified absent).

## Threat Mitigations Applied

| Threat ID | Disposition | How |
|-----------|-------------|-----|
| T-10-01 | mitigated | Kind resolution is a dict lookup in the injected registry only; no dynamic import, no source-text interpretation. Gated by `eval(`/`importlib` greps. |
| T-10-02 | mitigated | The codec IS the mitigation — `to_dict()`'s repr form stays a one-way snapshot and is never a decode source. |
| T-10-03 | mitigated | Coercion is driven by the resolved declared type; unhandled types, unknown blob fields, and missing required fields all raise. `__post_init__` re-validates. |
| T-10-04 | mitigated | Decimals cross as strings via `to_money`; JSON floats refused; non-finite refused on encode. |
| T-10-05 / T-10-06 | accepted | Per plan (bounded by the SQL column / operator surface; policies carry no credentials). |

## Known Stubs

None — the codec is complete and fully wired to its tests. It is not yet *consumed* by any
production caller; that is by design (downstream P10 plans wire it into rehydrate / `config_json`
/ the verb surface).

## Threat Flags

None — this plan adds no network endpoint, auth path, file access, or schema change. The new
trust boundary (external blob -> `decode_policy`) was already registered in the plan's threat
model and is mitigated above.

## For Future Plans

- **`decode_policy(blob, registry)` takes the registry explicitly** — it has no global default.
  Callers wiring rehydrate/`add` should build the registry once (with the app's overlay) and
  inject it, mirroring the D-01 catalog injection.
- **`default_policy_registry(overlay=...)` returns a fresh dict each call** — safe to hand out,
  but do not rely on identity between calls.
- **The `config_version` stamp (D-20) is NOT in the policy blob** — the codec serializes a single
  policy. Versioning belongs one level up, in the `config_json` envelope (D-04).
- **If the codec ever becomes hot,** register the memo site in `docs/CACHE-CLASSIFICATION.md` and
  update `tests/integration/test_cache_classification.py` rather than adding an ad-hoc dict —
  that gate is deliberate. Note for the phase: **any plan adding a `@cache`/`@lru_cache` under
  `itrader/` must update that gate**, and the plan's own acceptance criteria will not catch it.

## Self-Check: PASSED

- `itrader/core/policy_codec.py` — FOUND
- `tests/unit/core/test_policy_codec.py` — FOUND
- Commit `c2d5cb20` (test/RED) — FOUND
- Commit `8c93d2c9` (feat/GREEN) — FOUND
- All 6 exported symbols import cleanly; registry resolves the 6 expected kinds.

## TDD Gate Compliance

Both gates present and correctly ordered: `test(10-01)` RED commit `c2d5cb20` (verified failing
with `ModuleNotFoundError` against the absent module) precedes `feat(10-01)` GREEN commit
`8c93d2c9`. No REFACTOR commit — none needed.
