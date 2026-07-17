---
phase: 10-strategies-registry
plan: 05
subsystem: strategy_handler
tags: [rehydrate, restart, d-01, d-02, d-16, d-19, d-21, strat-01, wiring]
status: complete
requires:
  - itrader/storage/strategy_registry_store.py (Plan 02 — list_active / portfolio_subscriptions)
  - itrader/strategy_handler/registry/config_codec.py (Plan 04 — decode_strategy_config)
  - itrader/strategy_handler/registry/catalog.py (Plan 04 — the injected allowlist)
  - itrader/trading_system/live_trading_system.py (the system_store gate)
provides:
  - build_strategy / rehydrate_strategies / RehydrateInfrastructureError — the D-01 boot seam
  - build_live_system(strategy_catalog=...) — the injected type allowlist
  - state.quarantined_strategies — the D-19 read-model surface
  - StrategiesHandler.add_strategy duplicate-name reject (D-02)
affects:
  - Plan 06 enable verb — WD-1 re-warm must converge with Plan 07's add on ONE warm path
  - Plan 07 runtime add — same catalog x codec seam; add_strategy now rejects duplicates
  - Plan 08 reconfigure — the store-record vs table-row key mismatch below applies
tech-stack:
  added: []
  patterns:
    - two-arm failure split (per-instance quarantine vs loud infrastructure) held apart by a narrow exception tuple
    - atomic per-instance registration (resolve everything before touching the handler)
    - explicit schema probe over exception-swallowing, so a real fault stays distinguishable
key-files:
  created:
    - itrader/strategy_handler/registry/rehydrate.py
    - tests/unit/strategy/test_rehydrate.py
    - tests/integration/test_strategy_registry_restart.py
  modified:
    - itrader/strategy_handler/registry/__init__.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/strategy/test_is_active_gate.py
    - tests/unit/strategy/test_signal_store.py
decisions:
  - "D-01/D-02/D-16/D-19/D-21 implemented as specified, plus the four corrections below"
  - "Deviation: the store record spells the blob `config`, the codec reads `config_json` — a real Plan-02/Plan-04 integration gap the plan assumed away. Adapted in ONE documented seam."
  - "Deviation: stored portfolio ids rehydrated as bare `str`, which would fan signals at a portfolio matching nothing. mypy surfaced it; now parsed back to PortfolioId."
  - "Deviation: an unprovisioned registry TABLE is D-21 (zero rows), not D-19 infrastructure — probed with has_table rather than swallowing the query error."
  - "Deviation: two pre-existing tests relied on a duplicate strategy name that D-02 now forbids; instances renamed."
metrics:
  duration: ~65m
  completed: 2026-07-17
  tasks: 3
  files: 9
  tests_added: 24
---

# Phase 10 Plan 05: D-01 Rehydrate — the Roster Survives Restart Summary

STRAT-01 lands: `build_live_system` now reconstructs the configured strategy **instances**
from `store × catalog × codec` at boot, so the store — not composition code — is the source
of truth for what trades.

## What Was Built

**`itrader/strategy_handler/registry/rehydrate.py`** (TABS, 3 exports)

- `build_strategy(rec, *, catalog, policy_registry=None)` — decode then `cls(**params)`. The
  constructor runs `_apply_params` → `validate()` → `_run_init()`, so validation, coercion
  and warmup re-derivation all happen on the real path. Errors propagate: the caller owns
  the quarantine decision.
- `rehydrate_strategies(...) -> list[str]` — returns the quarantined names.
- `RehydrateInfrastructureError(RuntimeError)` — the D-19 loud arm.

**The D-19 two arms are held apart by a narrow exception tuple**, not a broad catch. This is
the module's most load-bearing detail: `except Exception` around the per-row body would also
swallow a genuine store/driver fault raised mid-loop and quarantine every strategy in turn —
reporting a data problem while hiding an outage. `_QUARANTINABLE` names exactly four types
(`UnknownStrategyTypeError`, `StrategyConfigError`, `UnknownParamError`, `MissingParamError`).

**Wiring** — `build_live_system` gained `strategy_catalog: Optional[Dict[str, type]] = None`
(mirroring `data_plugins`), and rehydrate runs at **construction time, inside the
`system_store is not None` gate, immediately after `_layer_persisted_overrides`** — the
placement that satisfies all four constraints at once (portfolios layered above; session
init reads the roster below; the three `_initialize_live_session` monkeypatch tests stay
reachable; lazy imports keep GATE-01 inertness). `state.quarantined_strategies` is a
dedicated read-model field, not folded into the single-valued `last_error`.

## Deviations from Plan

### 1. [Rule 3 — Blocking] The store record and the codec disagree on the blob's key — Plans 02 and 04 never actually met

- **Found during:** Task 2 pre-write verification.
- **Issue:** The plan directs `build_strategy(rec, ...)` to take `store.list_active()` rows
  straight to `decode_strategy_config`. That **cannot work**. Plan 02's store renames the
  column on the way out (`"config": row["config_json"]`, mirroring the repo-wide
  `VenueStore`/`ConfigRouter` store-record convention), while Plan 04's codec reads
  `rec.get("config_json")` — because it was built and tested against `seeded_registry_rows`,
  which emits raw **table rows**. Passing a store record to the codec raises
  `StrategyConfigError: config_json must be a mapping, got NoneType`. Two shapes for one
  row; neither plan noticed because neither ever called the other.
- **Fix:** One documented adapter, `_codec_rec`, is the single place the two are reconciled.
  Deliberately **not** a tolerant `rec.get("config") or rec.get("config_json")`: a row
  carrying neither key still reaches the codec and fails loudly there, naming the strategy.
  I did **not** reshape Plan 02's just-landed API — `"config"` is shared with `VenueStore`
  and pinned by three store tests, and Plans 06–08 may already assume it.
- **⚠ Downstream:** Plan 07/08 authors must pick a shape deliberately. This is a latent trap.
- **Commit:** `22677065`

### 2. [Rule 1 — Bug] Portfolio subscriptions rehydrated as bare `str` and would have traded into the void

- **Found during:** Task 2, surfaced by `mypy --strict` (`subscribe_portfolio` expects
  `PortfolioId | int`, got `str`).
- **Issue:** Not a typing nit. The column is `String` (Plan 02's deliberate choice — a `Uuid`
  column would reject the legal `int` arm), and `to_dict` writes `str(pid)`. But the inverse
  was missing: `calculate_signals` fans an intent over `subscribed_portfolios` and **casts**
  each id onto `SignalEvent.portfolio_id` (`strategies_handler.py`, FL-02: *"the runtime
  value is always a UUIDv7-backed PortfolioId"*). A bare `str` sails through that cast and
  reaches the portfolio lookup matching **nothing** — the strategy rehydrates looking
  perfectly healthy and then trades into the void.
- **Why it would have shipped:** the plan's own assertion sketch (`subscribed_portfolios`
  equals its child rows) passes trivially against strings. Only a **type** assertion catches
  it — the same trap 10-04 hit with Decimals.
- **Fix:** `_resolve_portfolio_id` parses back to `PortfolioId(UUID(...))`, falling back to
  the legacy `int` arm; a malformed id raises `StrategyConfigError` so D-19 quarantines it.
  Pinned by `test_uuid_portfolio_subscription_rehydrates_as_a_portfolio_id_not_a_str`
  (asserts `isinstance(..., UUID)` and `not isinstance(..., str)`).
- **Commit:** `22677065`

### 3. [Rule 2 — Missing critical functionality] Per-instance registration was not atomic

- **Found during:** Task 2, as a consequence of #2.
- **Issue:** The plan's order is `build → add_strategy → subscribe each id`. With id parsing
  added, a bad subscription would raise **after** `add_strategy`, leaving a half-wired
  strategy registered — trading with a silently truncated portfolio set, which is worse than
  the quarantine that was supposed to catch it.
- **Fix:** the instance **and** its resolved fan-out are built inside the `try`, before the
  handler is touched. Quarantine is now all-or-nothing. Pinned by
  `test_malformed_portfolio_subscription_quarantines_the_instance`.
- **Commit:** `22677065`

### 4. [Rule 3 — Blocking] An unprovisioned registry table is D-21, not D-19

- **Found during:** Task 3 — `test_durable_store_constructs_live_portfolio_handler` (a test
  the plan requires to stay **unmodified and green**) points at a bare Postgres with no
  schema. `list_active()` raised `UndefinedTable`, which propagated and failed the boot.
- **The judgement:** the plan forbids degrade-clean because it would invert D-19's loud arm.
  That reasoning holds for *rows we cannot load* — but an absent **table** means the registry
  was never provisioned, so there are provably **zero rows**. That is D-21's first-start
  state expressed at the schema level, and skipping it **cannot** produce the outcome D-19
  forbids (a silent boot with zero strategies *while rows exist*). Every sibling store on
  this path already degrades on "schema unavailable".
- **Fix:** an explicit `inspect(engine).has_table("strategy_registry")` probe — **not** an
  exception swallow, which could not distinguish an absent table from a lost connection or a
  permissions fault. Those still propagate loud out of `rehydrate_strategies`. Logged at
  **WARNING**, never silently: on a live deployment an absent table means the Alembic chain
  was never applied, and the operator needs to see that.
- **Commit:** `e8eec78f`

### 5. [Rule 1 — Bug] Two pre-existing tests relied on a duplicate strategy name

- **Found during:** Task 2 full-suite run. `test_is_active_gate` and `test_signal_store` each
  register two instances of one class whose `name` is class-pinned — a genuine D-02
  collision (two instances named `always_buy` cannot be told apart in the registry and would
  overwrite each other's persisted state). The guard is correct; the tests relied on
  behaviour the durable model now forbids.
- **Fix:** named the sibling instances distinctly, which is what a real operator must also
  do. The tests' actual subjects (the is_active gate, the two-instance fan-out) are unchanged.
- **Commit:** `22677065`

### Note: pairs and the SHORT-01 gate (D-16 interaction, not a deviation)

A `PairStrategy` is `LONG_SHORT`, so rehydrating one onto a handler without **both**
`allow_short_selling` and `enable_margin` raises the SHORT-01/D-07 registration gate. This is
**not** quarantined and that is deliberate: an unadmissible direction means the engine is
misconfigured for the roster it was asked to run — a system-level problem the operator must
see, not a bad row to skip past. Pinned by
`test_pair_row_needs_the_short_flags_like_any_other_instance`.

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/unit/strategy/test_rehydrate.py -q` | **18 passed** |
| `pytest tests/integration/test_strategy_registry_restart.py -q` | **6 passed** (real Postgres) |
| `pytest tests/integration/test_okx_inertness.py -x -q` (**MANDATORY**) | **4 passed** |
| `pytest tests/integration/test_backtest_oracle.py -x -q` (byte-exact 134 / `46189.87730727451`) | **3 passed** |
| `pytest tests/integration/test_cache_classification.py -q` (**upstream finding 3**) | **4 passed** |
| `test_paper_restart_restore.py` + `test_live_portfolio_durable_wiring.py` | **5 passed, `git diff --stat` empty (UNMODIFIED)** |
| `mypy` (strict, whole project) | **clean (244 files)** |
| `pytest tests/unit tests/integration -q` | **2337 passed, 2 skipped** |

**Source gates (`rehydrate.py`):** `_degrade_clean` = 0 · `except Exception` = 0 ·
`enabled=False` = 0 · `upsert` = 0 · `eval(` = 0 · `import importlib` = 0 · `isinstance` = 0
(D-16 — no pair special case) · `D-01` = 4 · `D-19` = 16 · space-indent lines = 0 (187 tab
lines — TABS).

**Source gates (`live_trading_system.py`):** `strategy_catalog` = 3 · `rehydrate_strategies`
= 4 · `quarantined_strategies` = 3 · `D-01` = 3 · tabs = 0 (stays 4-space) · no module-top
`strategy_registry_store` / `registry.rehydrate` import (both lazy, inside the gate) ·
`_layer_persisted_overrides(` at line 1571 **precedes** `rehydrate_strategies(` at 1622 ·
`grep -c 'rehydrate' session_initializer.py` = **0**.

**`grep -c 'D-02' strategies_handler.py`** = 8. **`grep -c caplog test_rehydrate.py`** = 0
(assertions go through the alert-sink double). No `__init__.py` added to either test dir.

**Blindspot sweep (per the plan's `live_trading_system.py` mypy `ignore_errors` warning):**
re-read the diff by hand. It caught one real issue — `StrategyRegistryStore` was constructed
unconditionally but used only in the `else` branch (a pointless metadata side effect when the
table is absent); construction moved inside the branch. Every other added name is used; no
imports orphaned.

## Threat Mitigations Applied

| Threat ID | Disposition | How |
|-----------|-------------|-----|
| T-10-25 | mitigated | Class resolution goes only through `resolve_strategy_class`'s injected-catalog lookup. `eval(` = 0, `import importlib` = 0 on `rehydrate.py`. |
| T-10-26 | mitigated | D-19 per-instance quarantine: skip + CRITICAL alert + continue. Gated by the quarantine tests (healthy sibling still loads). |
| T-10-27 | mitigated | `RehydrateInfrastructureError` when rows exist with no catalog; `_degrade_clean` = 0. Gated at both the unit and the real-Postgres factory level. |
| T-10-28 | mitigated | The row is never mutated — `upsert` = 0, `enabled=False` = 0; both unit and integration tests re-read the row and assert `enabled is True`. |
| T-10-29 | mitigated | D-02 loud reject in `add_strategy`; two tests (rehydrate twice; collide with a hand-added name). |
| T-10-30 | mitigated | The alert binds `strategy_name` + the error KIND only — deliberately not the exception message, which quotes the offending stored value. Gated by a test asserting a distinctive stored value (`0.987654321`) appears nowhere in the payload. |
| T-10-31 | mitigated | Store + collaborator imports lazy inside the gate, never barrel-exported. `test_okx_inertness.py` green + the module-top import grep. |
| T-10-32 | accepted | Per plan — `strategy_id` is ephemeral/telemetry-only; pinned by the fresh-UUIDv7 test. |

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path, or schema change. The one new surface (a stored
`portfolio_id` string parsed back into a `PortfolioId`) is a parse of data the engine itself
wrote, validated by the same round-trip; a malformed value quarantines rather than
propagating.

## For Future Plans

- **⚠ The `config` vs `config_json` key split is live** (Deviation 1). `rehydrate._codec_rec`
  is the only reconciliation today. Plan 07 (`add` from a `STRATEGY_COMMAND` payload) and
  Plan 08 (reconfigure) each touch this seam — pick a shape deliberately rather than
  assuming. Unifying the store on `config_json` is a defensible follow-up (it would touch
  `VenueStore`'s parallel and 3 store tests).
- **Assert on TYPE, not just value, for anything crossing the store.** Two independent
  silent-corruption bugs (10-04's Decimal-as-str, this plan's PortfolioId-as-str) both had
  value-equality assertions that passed while the type was wrong.
- **`add_strategy` now rejects duplicate names** (D-02). Any plan registering two instances
  of one class must name them distinctly — the class-pinned default name collides.
- **WD-1 convergence:** this plan establishes no warm/unwarm seam — rehydrate registers
  instances and the existing warmup path runs at session init as before. Plan 06 (`enable`)
  and Plan 07 (`add`) are therefore still free to converge on ONE warm path, as WD-1
  requires; nothing here forces two.
- **`rehydrate_strategies` is catalog-agnostic about warmth.** A rehydrated instance is
  registered before `wire_universe` / `register_strategy_warmup`, so it warms through the
  normal session-init path with no special casing.

## Self-Check: PASSED

- `itrader/strategy_handler/registry/rehydrate.py` — FOUND
- `tests/unit/strategy/test_rehydrate.py` — FOUND
- `tests/integration/test_strategy_registry_restart.py` — FOUND
- Commit `87690257` (test/RED) — FOUND
- Commit `22677065` (feat, Task 2) — FOUND
- Commit `e8eec78f` (feat, Task 3) — FOUND
- All 3 exports import cleanly; 24 new tests green; full suite green.

## TDD Gate Compliance

Both gates present and correctly ordered: `test(10-05)` RED commit `87690257` (verified
failing with `ModuleNotFoundError` against the absent
`itrader.strategy_handler.registry.rehydrate`) precedes the two `feat(10-05)` GREEN commits
(`22677065` collaborator + handler guard, `e8eec78f` wiring). No REFACTOR commit — none needed.
