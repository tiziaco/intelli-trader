---
phase: 10-strategies-registry
plan: 04
subsystem: strategy_handler
tags: [codec, catalog, serialization, allowlist, d-01, d-04, d-16, d-20, security]
status: complete
requires:
  - itrader/core/policy_codec.py (Plan 01 — encode_policy / decode_policy / PolicyRegistry)
  - itrader/strategy_handler/base.py (_declared_hints, _COERCE, _apply_params, _run_init)
  - itrader/storage/strategy_registry_store.py (Plan 02 — the row shape decode consumes)
provides:
  - StrategyCatalog / resolve_strategy_class / UnknownStrategyTypeError — the D-01 injected allowlist
  - encode_strategy_config / decode_strategy_config / CONFIG_VERSION / StrategyConfigError — the D-04/D-20 codec
  - tests/support/strategy_catalog.py — test_catalog / build_shipped_strategies / seeded_registry_rows
affects:
  - Plan 05 rehydrate — build_strategy is catalog x row x codec; consumes decode_strategy_config
  - Plan 07 runtime add — decodes a STRATEGY_COMMAND payload through the same seam
  - Plan 09 restart lifecycle — reuses seeded_registry_rows
tech-stack:
  added: []
  patterns:
    - injected-dict-as-allowlist (the catalog IS the access control for an untrusted type string)
    - annotation-driven codec over the declared authoring surface (MRO-merged get_type_hints)
    - derived-field exclusion as a correctness requirement (re-derive beats store)
    - decode returns (cls, params) so the constructor's validator owns rejection
key-files:
  created:
    - itrader/strategy_handler/registry/__init__.py
    - itrader/strategy_handler/registry/catalog.py
    - itrader/strategy_handler/registry/config_codec.py
    - tests/support/strategy_catalog.py
    - tests/unit/strategy/test_config_roundtrip.py
  modified: []
decisions:
  - "D-01/D-04/D-05/D-16/D-20 implemented as specified, except the two corrections below"
  - "Deviation: the plan's Test 7 premise was factually wrong — the pair's entry_z/exit_z/leverage ARE declared (annotated on PairStrategy, merged across the MRO). Implementing the plan literally would have silently dropped author intent."
  - "Deviation: the plan's codec spec omitted the Decimal arm entirely. Without it Test 8 (json.dumps, no default= hook) fails and Decimal params round-trip to str SILENTLY."
  - "decode reads config_json (the real Plan 02 column name), not the plan's sketch key 'config'"
metrics:
  duration: ~35m
  completed: 2026-07-17
  tasks: 3
  files: 5
  tests_added: 36
---

# Phase 10 Plan 04: D-01 Catalog + D-04/D-20 Config Codec Summary

The `catalog × codec` half of D-01's type-vs-instance split: an injected-allowlist type
resolver plus a symmetric authoring-param codec, so a strategy instance is DATA that
round-trips through `config_json` losslessly on its declared surface.

## What Was Built

`itrader/strategy_handler/registry/` (TABS, 3 files) — a collaborator package mirroring
`order_handler/admission/`, deliberately **not** added to the `strategy_handler` top barrel
(D-05/GATE-01: barrel-exporting it would pull SQL onto the backtest import graph).

- **`catalog.py`** — `StrategyCatalog` (`dict[str, type[Strategy]]`), `resolve_strategy_class`,
  `UnknownStrategyTypeError`. The resolver's entire body is a dict lookup and a raise: no
  by-name import, no source-text evaluation. `Strategy` is imported under `TYPE_CHECKING`
  only, so the module pulls in no concrete strategy class.
- **`config_codec.py`** — `encode_strategy_config` / `decode_strategy_config` /
  `CONFIG_VERSION = 1` / `_DERIVED_FIELDS` / `StrategyConfigError`.
- **`tests/support/strategy_catalog.py`** (4-space, matching `replay_harness.py`) —
  `test_catalog`, `build_shipped_strategies`, `seeded_registry_rows` (both D-06 tables).
- **`tests/unit/strategy/test_config_roundtrip.py`** — 36 cases.

A blob is the declared surface minus the exclusions, plus a two-key envelope:

```json
{"allow_increase": false, "direction": "long_only", "max_positions": 1,
 "sizing_policy": {"kind": "FractionOfCash", "fraction": "0.95", "step_size": null},
 "sltp_policy": null, "tickers": ["BTCUSD"], "timeframe": "1d",
 "strategy_type": "SMAMACDStrategy", "config_version": 1}
```

**Key mechanisms:**

- **The catalog is the access control (T-10-18).** `strategy_type` is untrusted — it arrives
  from a `STRATEGY_COMMAND` payload or a stored row. Resolution is closed over an injected
  dict, which makes an off-list type *unreachable* rather than merely unlikely.
- **The authoring surface is `_declared_hints(cls)`** — reused from `base.py`, not
  re-derived. Runtime state (`is_active`/`subscribed_portfolios`/`strategy_id`) carries
  function-local annotations, so it is structurally invisible and needs no exclusion list.
- **Derived-field exclusion (F-2).** `_run_init` is the only post-`_apply_params` mutator of
  declared fields and touches exactly `warmup`/`max_window`, so the set is exhaustive by
  construction. Verified against all three shipped strategies (100 / 1 / 280), with three
  successive round-trips asserting no ratchet.
- **Decode routes through the constructor.** Returning `(cls, params)` means
  `_apply_params` owns unknown/missing rejection and `_COERCE` owns `timeframe`/`direction`
  coercion — so the codec and the validator *cannot* drift. An unrecognised blob key is
  passed through untouched precisely so `UnknownParamError` fires (T-10-20).
- **Stable key order** — `sorted(hints)` rather than MRO order, so an unchanged instance
  never produces a spurious row update.

## Key Decisions

- **`config_version` lives inside the blob, stamped now** (D-20). It describes the blob's
  shape; D-06 reserves columns for queryable runtime state. Stamped now because it cannot be
  added retroactively — a blob written without one is indistinguishable from v1 forever after.
- **Row/blob `strategy_type` cross-check.** The blob is self-describing *and* the row has a
  `strategy_type` column. The column is authoritative; a disagreement now raises rather than
  silently resolving one way (T-10-22/T-10-24) — the disagreement is itself the signal that
  something wrote the row inconsistently.
- **`rec["config_json"]`, not the plan's `rec["config"]`.** `config_json` is the real column
  name in Plan 02's `build_strategy_registry_tables`. The plan's Test 1 sketch used `config`;
  adopting it would have handed Plan 05 a key that does not exist on the row it reads.

## Deviations from Plan

### 1. [Rule 1 — Bug] The plan's Test 7 premise is factually wrong; implementing it literally would have shipped a silent data-loss bug

- **Found during:** Task 1 test design (pre-write verification of the plan's `read_first` claims).
- **Issue:** The plan asserts — in `read_first`, in Test 7, in the `must_haves`, and in the
  Task 3 `<action>` — that `EthBtcPairStrategy`'s `entry_z`/`exit_z`/`leverage` are
  *"UNANNOTATED class attrs at :68-72, which `_declared_hints` never sees"*, and directs that
  they *"appear nowhere in the blob"*. This is false. Those attrs are **annotated on the
  parent `PairStrategy`** (`pair_base.py:85-93`), and `get_type_hints` merges annotations
  **across the MRO** — so `_declared_hints(EthBtcPairStrategy)` returns all of
  `entry_z`, `exit_z`, `leverage`, `use_log_prices`, `entry_units`, `z_lookback`,
  `beta_warmup`. Verified empirically before writing a line:
  ```
  'entry_z'  declared? True   type=<class 'decimal.Decimal'>
  EthBtcPairStrategy(timeframe='1d', entry_z=Decimal('3')).entry_z -> Decimal('3')
  ```
  They are settable authoring kwargs. A codec that excluded them would round-trip
  `entry_z=Decimal("3")` back to the class default `Decimal("2")` — **silently changing the
  alpha's entry threshold on every rehydrate.**
- **The plan is self-contradictory here**, which is what makes this unambiguous rather than a
  judgement call: Test 1 requires *"every name in `_declared_hints(type(s))` compares equal on
  `s` and `s2`"* and the D-05 `must_have` requires reconstruction *"equal on the declared
  surface"*. Test 7 requires those same declared names to be absent from the blob. Both cannot
  hold. Test 1 is load-bearing (it is the D-05 symmetry contract); Test 7's *stated intent* —
  D-16, "a pair encodes and decodes exactly like any other instance, no special case" — is
  fully satisfiable and is what I implemented.
- **Fix:** Test 7 now asserts the pair's declared extras ARE in the blob and round-trip, using
  **non-default values** (`entry_z=3`, `exit_z=0.25`, `entry_units=2`) — deliberately, because
  a defaults-only test would pass even against a codec that dropped them. The codec has no
  `PairStrategy` branch (D-16 holds); the three `PairStrategy` occurrences in the file are
  docstring prose documenting this correction.
- **Files modified:** `tests/unit/strategy/test_config_roundtrip.py`, `itrader/strategy_handler/registry/config_codec.py`
- **Commits:** `520b79d1` (test), `c7279749` (feat)

### 2. [Rule 2 — Missing critical functionality] The codec spec omitted the `Decimal` arm; two independent gates fail without it

- **Found during:** Task 1 test design, as a direct consequence of Deviation 1.
- **Issue:** The plan's `encode` spec enumerates Enum → `.value`, policy → `encode_policy`,
  list → copy, and the `timeframe`/`name` skips. **No `Decimal` arm.** Once the pair's
  Decimal-typed knobs are correctly recognised as declared params (Deviation 1), the omission
  breaks two things — both verified:
  1. `json.dumps({'entry_z': Decimal('2')})` → `TypeError: Object of type Decimal is not JSON
     serializable`, failing the plan's own Test 8 (json-dumpable with no `default=` hook).
  2. On decode, the plan directs *"pass the strings straight through and let `_COERCE` do it"* —
     but `_COERCE` covers **only** `timeframe` and `direction` (`base.py:138-141`, and its
     comment is explicit: *"ONLY these three engine fields coerce a str… every other knob is
     left as supplied"*). So `entry_z` would land on the instance as the **str `'2'`**.
- **This one fails silently, which is why it rates Rule 2 rather than cosmetic.** The natural
  guard does not catch it: `validate()` computes `self.exit_z < self.entry_z`, and on strings
  that is a *lexicographic* comparison — `'0.5' < '2'` → `True`. Construction succeeds. The
  corruption surfaces much later, in the alpha, as `abs(curr_z) > self.entry_z` comparing
  `Decimal` to `str`.
- **Fix:** `Decimal` is a first-class arm on both sides, **driven by the resolved class
  annotation** — which the plan's own `must_have` sanctions: *"coercion on load is driven by
  the class annotation resolved via the catalog"*. Encode emits `str(value)` with a
  finite-guard; decode re-enters via `to_money` (the `Decimal(str(x))` path), refusing a JSON
  float outright rather than silently rounding it. This mirrors the Plan 01 policy codec's
  money boundary exactly, so the two agree. `_COERCE` fields are still passed through
  untouched, honouring the plan's no-duplication directive.
- **Files modified:** `itrader/strategy_handler/registry/config_codec.py`
- **Commit:** `c7279749`

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/unit/strategy/test_config_roundtrip.py -x -q` | **36 passed** |
| `pytest tests/integration/test_okx_inertness.py -x -q` (**MANDATORY**) | **4 passed** |
| `pytest tests/integration/test_backtest_oracle.py -x -q` (byte-exact 134 / `46189.87730727451`) | **3 passed** |
| `pytest tests/integration/test_cache_classification.py -q` (**upstream finding 1**) | **4 passed** |
| `mypy itrader/strategy_handler/registry/` (strict, no new ignores) | **clean (3 files)** |
| `mypy` (whole project) | **clean (243 files)** |
| `pytest tests/unit tests/integration -q` | **2313 passed, 2 skipped** |

**Source gates (`config_codec.py`):** `_DERIVED_FIELDS` = 3 · `timeframe_alias` = 4 ·
`CONFIG_VERSION` = 7 · `eval(` = 0 · `import importlib` = 0 · `Decimal(float` = 0 ·
`D-04` = 8 · `D-20` = 4 · no `sqlalchemy`/`itrader.storage` import · space-indent lines = 0
(258 tab lines — TABS, matching the package).

**Source gates (`catalog.py`):** `eval(` = 0 · `import importlib` = 0 · `D-01` = 5 · no
`sqlalchemy`/`itrader.storage`/concrete-strategy import · space-indent = 0 / tabs = 30.

**Barrel:** `grep -c 'registry' itrader/strategy_handler/__init__.py` == **0** (untouched).

**Marker:** `-m unit` selects all 36; `-m "not unit"` deselects all 36 (folder-derived). No
`__init__.py` in `tests/unit/strategy/` (verified absent).

**Upstream finding 1 (`@cache` trap) — avoided by design, not luck:** the codec reuses
`base.py`'s existing `_declared_hints` rather than adding a memo, so the memoization surface
stays at exactly the 3 documented sites. The gate was run explicitly and is green.

## Threat Mitigations Applied

| Threat ID | Disposition | How |
|-----------|-------------|-----|
| T-10-18 | mitigated | `resolve_strategy_class` is a dict lookup in the injected catalog and nothing else. Gated by `eval(`/`importlib`/no-concrete-import greps on `catalog.py`. |
| T-10-19 | mitigated | Policy fields delegate to the Plan 01 tagged-union codec; `to_dict()`'s repr form is never a decode source. Same greps on `config_codec.py`. |
| T-10-20 | mitigated | Decode returns `(cls, params)`; the codec never `setattr`s and passes unknown keys THROUGH so `_apply_params` raises `UnknownParamError`. Test 11. |
| T-10-21 | mitigated | `_DERIVED_FIELDS` excludes `warmup`/`max_window`; Test 6 round-trips three times per strategy asserting no growth. |
| T-10-22 | mitigated | `name` is never in the blob; decode sources it from `rec["strategy_name"]` (Test 4). Extended: a row/blob `strategy_type` disagreement now raises. |
| T-10-23 | accepted | Per plan — the blob is declared params only; no credential field exists on the authoring surface. |
| T-10-24 | mitigated | `config_version` stamped in every blob; absent/newer raises naming both versions rather than best-effort decoding. |

## Known Stubs

None. The catalog and codec are complete and fully tested. They are not yet *consumed* by a
production caller — by design: Plan 05's `build_strategy` (rehydrate) and Plan 07's `add`
verb are their first consumers.

## Threat Flags

None — this plan adds no network endpoint, auth path, file access, or schema change. Both new
trust boundaries (`strategy_type` → resolver, blob → decode) were already registered in the
plan's threat model and are mitigated above.

## For Future Plans

- **⚠ Plan 05 / Plan 07: `decode_strategy_config` takes `rec["config_json"]`**, not `"config"`
  (the plan sketch's key). It reads three row keys: `strategy_name`, `strategy_type`,
  `config_json`.
- **Decode does NOT construct** — it returns `(cls, params)` so Plan 05's `build_strategy`
  owns the D-19 per-instance quarantine. A construction failure propagates deliberately.
- **The pair's alpha knobs are part of the authoring surface** (Deviation 1). Any future work
  reasoning about "the base's ten declared params" should note a `PairStrategy` has seventeen.
- **`enabled` / subscriptions are NOT in the blob** (D-06): they are the `enabled` column and
  the child table. `seeded_registry_rows` already emits both correctly — reuse it.
- **If a future strategy declares a non-`_COERCE` Enum knob**, the codec coerces it via the
  annotation (the arm exists and is documented). If one declares a type outside
  {Decimal, Enum, bool, int, str, list, policy}, the codec fails loud by design — extend
  `_encode_value`/`_decode_value` in tandem rather than adding a pass-through.

## Self-Check: PASSED

- `itrader/strategy_handler/registry/__init__.py` — FOUND
- `itrader/strategy_handler/registry/catalog.py` — FOUND
- `itrader/strategy_handler/registry/config_codec.py` — FOUND
- `tests/support/strategy_catalog.py` — FOUND
- `tests/unit/strategy/test_config_roundtrip.py` — FOUND
- Commit `520b79d1` (test/RED) — FOUND
- All 7 exported symbols import cleanly; all 36 tests green; full suite green.

## TDD Gate Compliance

Both gates present and correctly ordered: `test(10-04)` RED commit `520b79d1` (verified
failing with `ModuleNotFoundError` against the absent `itrader.strategy_handler.registry`)
precedes the two `feat(10-04)` GREEN commits (`ba3a9874` catalog, then `c7279749` codec). No REFACTOR commit — none
needed.
