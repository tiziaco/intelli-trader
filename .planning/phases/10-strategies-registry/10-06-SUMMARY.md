---
phase: 10-strategies-registry
plan: 06
subsystem: strategy-handler + events
tags: [D-07, D-08, D-09, D-16, D-17, WD-1, WD-2, CR-01, strat-02, oracle-gated]
status: complete
requires:
  - "itrader/storage/strategy_registry_store.py (Plan 02 — upsert / add_portfolio_subscription / remove_portfolio_subscription)"
  - "itrader/strategy_handler/registry/config_codec.py (Plan 04 — encode_strategy_config)"
  - "itrader/strategy_handler/strategies_handler.py::calculate_signals D-07 is_active guard (Plan 03)"
  - "itrader/trading_system/live_trading_system.py system_store gate (Plan 05)"
provides:
  - "StrategyCommandEvent — one control event carrying all nine D-09 verbs, one factory each"
  - "Strategy.mark_unwarm() / PairStrategy.mark_unwarm() — THE WD-1/WD-2 re-warm seam (Plan 07 add + Plan 08 reconfigure reuse it)"
  - "StrategiesHandler.registry_store — the injected durable registry (None on backtest)"
  - "StrategiesHandler._persist_strategy / _request_rewarm / _portfolio_id_from"
  - "_PAIR_REFUSED_VERBS — the D-16/D-17 verb-scoped pair guard set"
affects:
  - "Plan 07 (add) — MUST reuse mark_unwarm + _request_rewarm; ONE warm path (WD-1)"
  - "Plan 08 (reconfigure) — same seam; the pair arm stays refused (D-17)"
tech-stack:
  added: []
  patterns:
    - "deferred child-table write applied after the parent upsert (FK ordering)"
    - "parse-at-the-boundary for untrusted payload ids, returning None (loud no-op) rather than raising into the queue"
    - "reusing an existing per-symbol pipeline's retry trigger instead of minting a new event type"
key-files:
  created:
    - tests/unit/events/test_strategy_command_vocabulary.py
    - tests/unit/strategy/test_mark_unwarm.py
    - tests/unit/strategy/test_strategy_command_verbs.py
  modified:
    - itrader/events_handler/events/universe.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/pair_base.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/strategy/test_pair_dispatch.py
decisions:
  - "WD-1 implemented over the plan text: enable unwarms + re-warms; the plan's four 'indicators stay WARM / no re-warmup' claims are dead."
  - "WD-2 seam = Strategy.mark_unwarm(), a named wrapper over the existing reset(); PairStrategy overrides it to clear the spread buffers. No bool flag, no handler-side warmth."
  - "Deviation: universe_handler.py needed NO edit (audit F2 confirmed) — the real symbol read is strategies_handler.py:512."
  - "Deviation: subscribe/unsubscribe DO route through the parent upsert — the child FK forces it, and the plan's 'keep them out' instruction would raise IntegrityError into the queue."
  - "Deviation: payload portfolio_id must be PARSED to PortfolioId — mypy caught the exact bug 10-05 hit on the rehydrate arm."
  - "Deviation: enable emits a UniversePollEvent follow-on (the plan restricted the poll to ticker verbs) — WD-1's re-warm rides the CR-02 retry, which only runs on a poll."
metrics:
  duration: ~55m
  completed: 2026-07-17
  tasks: 3
  files: 9
  tests_added: 44
---

# Phase 10 Plan 06: D-09 Light-Verb Dispatch + the WD-1 Re-Warm Seam Summary

STRAT-02's dispatch surface lands: one control event carries all nine verbs, the four light
verbs apply live **and** persist, and the CR-01 pair guard narrows from "refuse everything"
to exactly what D-16/D-17 decided — with `enable` now re-warming per WD-1 rather than
trading the next bar off a holed window.

## What Was Built

**Task 1 — D-08 event vocabulary (`b46a3b0b`, RED `ef5bc4cb`).** `StrategyCommandEvent`
(a `msgspec.Struct`, not a dataclass) gains `symbol: str | None = None` and
`config: dict | None = None` plus seven factories. Both new fields are defaulted, so every
existing construction and every old-shaped payload still decodes — pinned by a round-trip
test. `__str__` renders symbol-less verbs and reports `config` **by key count only**: a
payload is operator-supplied and `__str__` feeds the logs, so a test asserts a planted
secret value never appears in the rendering.

**Task 2 — the WD-2 seam (`f7389b48`, RED `e5b6d573`).** `Strategy.mark_unwarm()` is a
named wrapper over the existing `reset()`. `PairStrategy.mark_unwarm()` overrides it to
clear `_buf_A`/`_buf_B`/`_pair_bar_count` **then** call `super()`.

**Task 3 — dispatch + guard + wiring (`56db7b04`, RED `06705d37`).** The four light verbs,
ticker-verb persistence, `_PAIR_REFUSED_VERBS = {reconfigure, add_ticker, remove_ticker}`,
and the store injected inside the `system_store is not None` gate before rehydrate.

## The Two Binding Decisions

**WD-1 — `enable` re-warms.** Implemented over the plan text (the plan's four
"indicators stay WARM / trades the next bar with NO re-warmup" claims are now dead;
`strategies_handler.py:164-167`'s stale comment is rewritten to document the freeze and
why `enable` must discard it).

`enable` → `activate_strategy()` → `mark_unwarm()` → `_request_rewarm()`. The correctness
guarantee rests on `mark_unwarm()` **alone**: `is_ready`/`is_pair_ready` gate emission, so
the strategy physically cannot signal until its recurrence has re-advanced over a
contiguous window. `_request_rewarm` only makes it *fast*.

**On WD-1's `warmup_pipeline.warm(strategy)` pseudocode:** no such API exists — 10-05
confirmed no warm seam, and the warmup pipeline is per-**symbol** and owned by
`UniverseHandler` behind the queue boundary, so `StrategiesHandler` cannot call it. Its
existing trigger is the **CR-02 FAILED-retry**: `on_poll` collects still-desired FAILED
members, flips them PENDING and folds them into `added` → `_begin_warmup` → `BarsLoaded` →
`on_bars_loaded` replays the window through `strategy.update`. So `_request_rewarm` marks
the strategy's symbols FAILED and the `enable` follow-on poll drives it. **This is
literally "reuse the P7 warmup path"** — no new event type, no cross-domain call, and Plan
07's `add` reuses the same two calls (WD-1's one-warm-path requirement).

Three details worth carrying forward:
- **`mark_failed`, not `mark_pending`.** Only FAILED members are collected by the retry;
  PENDING would leave the symbol dark **forever** — the silent-permanent-no-warm failure
  mode F-1 exists to eliminate. The re-warm streak counter increments at the *failure*
  sites, not at `mark_failed`, so this raises no false "stuck symbol" alarm.
- **`_selection_source` is unconditionally wired live** (`session_initializer.py:166`), so
  `on_poll`'s early return cannot strand the re-warm. Verified, not assumed.
- **Two accepted, bounded consequences** (documented at the call site): a symbol shared
  with a warm sibling goes dark for one poll interval (readiness is per-symbol and
  aggregate *by design*), and the replayed bars are re-delivered to that sibling — which
  the CR-01 monotonic guard rejects before any state mutation. That guard exists for
  exactly this case.

**WD-2 — the seam is a wrapper, and it covers the pair arm.** `is_ready` stays the single
computed truth; a test asserts **no bool attribute containing "warm"** exists on the
instance after `mark_unwarm()`, so a future `self._warm = False` regression fails loudly.
The pair arm is the load-bearing half: a handle-free pair has `warmup == 0`, so `is_ready`
is vacuously `True` **always** — a handles-only unwarm would leave it reporting warm
instantly while its spread stayed hot, re-entering on a β fit across a discontinuity.
`test_pair_enable_re_warms_the_spread_not_just_the_handles` drives the full
disable→enable→tick path and asserts zero signals.

**Oracle proven, not assumed** (WD-2 asked): re-run byte-exact after the `base.py` commit
and again at the end. The wrapper adds no per-bar read.

## Deviations from Plan

### 1. [Rule 3 — Blocking] `universe_handler.py` needed no edit; the real read is elsewhere

- **Issue:** The plan names `universe.py:498`'s `symbol = event.symbol` in four places and
  puts `universe_handler.py` in Task 1's `<files>`. Audit F2 is correct: line 498 is inside
  `_begin_warmup`'s **docstring**, and that file contains no `on_strategy_command` and no
  `StrategyCommandEvent.symbol` read at all. The real site is
  `strategies_handler.py:512`, which is **not** in Task 1's file list.
- **Fix:** Left `universe_handler.py` untouched; the `symbol` read moved inside the
  ticker-verb branches in Task 3 (where the plan does cover it correctly). **mypy proved
  the file choice**: after Task 1 it flagged exactly `strategies_handler.py:520` for the
  `str | None` narrowing — and nothing in `universe_handler.py`.
- **Also confirmed stale (harmless, fixed by reading content not coordinates):** `__str__`
  is at `:138` not `:419` (F3); `on_strategy_command` is at `:452` not `:438` (F4).

### 2. [Rule 1 — Bug] The plan's child-write instruction raises `IntegrityError` into the queue

- **Found during:** Task 3 — three subscribe tests failed with
  `sqlite3.IntegrityError: FOREIGN KEY constraint failed`.
- **Issue:** The plan directs that subscribe/unsubscribe "write the child table directly in
  their branch, so keep them out of the `_persist_strategy` upsert path or the config blob
  would be rewritten needlessly". But `strategy_portfolio_subscriptions` carries an **FK to
  `strategy_registry`**, so writing a child row for a strategy the registry has never seen
  (one hand-added rather than rehydrated) raises straight into the queue — violating this
  method's never-raise contract and turning an operator subscribe into an `ErrorEvent`.
- **Fix:** The parent upsert now runs first and the child write is deferred until after it.
  The FK is not an obstacle to work around; it is stating the invariant — a durable
  subscription edge whose instance is absent from the registry is an orphan **rehydrate
  would silently drop at restart**, so the subscription would survive the process but not
  the reboot. The plan asked me to decide and say so: subscribe/unsubscribe **do** route
  through `_persist_strategy`.

### 3. [Rule 1 — Bug] A bare-`str` portfolio id would have fanned signals into the void

- **Found during:** Task 3, surfaced by `mypy --strict`.
- **Issue:** `subscribed_portfolios` is `list[PortfolioId | int]` and `calculate_signals`
  casts each entry straight onto `SignalEvent.portfolio_id` (FL-02). The payload carries a
  `str`, which sails through that cast and reaches the portfolio lookup matching
  **nothing** — the subscription looks healthy and trades into the void. **This is
  precisely 10-05's Deviation 2, one arm over**, and precisely the trap it warned about:
  my own first-draft tests asserted `"p1" in subscribed_portfolios` — value equality that
  **passes while the type is wrong**.
- **Fix:** `_portfolio_id_from` parses (UUID first, then the legacy `int` arm), mirroring
  `rehydrate._resolve_portfolio_id` but returning `None` instead of raising — rehydrate
  quarantines a bad instance at boot, whereas a bad runtime command must be a loud no-op.
  Pinned by a **TYPE** assertion (`isinstance(..., UUID)` and `not isinstance(..., str)`)
  plus malformed-id and int-arm tests.

### 4. [Rule 2 — Missing critical functionality] `enable` must emit the poll follow-on

- **Issue:** The plan says "Emit the `UniversePollEvent` follow-on ONLY for the ticker
  verbs. The light verbs do not change universe membership." True for
  disable/subscribe/unsubscribe — but WD-1 post-dates that sentence, and the re-warm it
  mandates rides the CR-02 retry, which **only runs on a poll**. Without the follow-on the
  unwarmed strategy would wait for the next scheduled poll at best.
- **Fix:** `_POLL_FOLLOW_ON_VERBS = {add_ticker, remove_ticker, enable}`, named and
  commented so the reason survives.

### 5. [Reported per plan request] No existing pair-refusal assertions needed updating

The plan says `test_pair_dispatch.py` holds "the existing pair coverage to EXTEND. The
current tests assert the blanket refusal; some will need updating in lockstep." **It holds
none** — that file had zero `StrategyCommandEvent` tests (its three tests cover two-leg
dispatch). Grepping the whole tree, **no test anywhere asserted the blanket refusal**, so
the re-scoping changed no existing assertion. Worth noting for the record: the blanket
guard that D-16 says silently guts pair durability was entirely unpinned by tests, which
is why it survived to be found by planning rather than by a failure.

### 6. [Judgment call] One test of mine was wrong, not the code

`test_pair_enable_re_warms_the_spread_not_just_the_handles` initially drained the queue
expecting only signals and tripped on `enable`'s own poll follow-on. The two WD-2
assertions (`is_pair_ready() is False`) already passed. Narrowed the assertion to
`SignalEvent`s, which is what the test is actually about.

## Verification Results

| Gate | Result |
|------|--------|
| **Backtest oracle (MANDATORY, byte-exact 134 / `46189.87730727451`)** | **PASS** (3 passed) — re-run after `base.py`, and again at the end |
| **OKX inertness (MANDATORY)** | **PASS** (4 passed) |
| `test_cache_classification.py` (the `@cache` trap) | **PASS** (4 passed) — no memoization added |
| `test_strategy_command_verbs.py` | **PASS** (24 tests) |
| `test_mark_unwarm.py` | **PASS** (10 tests) |
| `test_strategy_command_vocabulary.py` | **PASS** (22 tests) |
| `test_pair_dispatch.py` | **PASS** (10 tests: 3 pre-existing + 7 new) |
| **FULL tree `pytest tests` (incl. `tests/e2e`)** | **PASS — 2475 passed, 6 skipped** (OKX creds absent) |
| `mypy --strict` (whole package) | **clean (244 files)** |

All runs used `PYTHONPATH="$PWD"` to defeat worktree `.venv` shadowing. The full tree —
not just unit+integration — was run per the 10-05 lesson.

**Source gates:** handler space-indent lines = **0** (stays TABS) · module-top `registry`
import = **0** (codec is function-local) · `_PAIR_REFUSED_VERBS` = 3 · `D-16` = 6 ·
`D-17` = 4 · `D-09` = 19 · `registry_store` in handler = 8, in `live_trading_system` = 5 ·
the four verb branches = 4 · `universe.py` tabs = 0 (stays 4-space) ·
`live_trading_system.py` tabs = 0 (stays 4-space) · `grep -c caplog` on the new verb suite
= **0**. No `__init__.py` added to any test dir. All three new test files confirmed
**tracked** (the `**cache**` gitignore trap that bit 10-03).

**`live_trading_system.py` blindspot sweep** (mypy `ignore_errors`): re-read the diff by
hand. One added name, used twice; no orphaned imports. It also collapses a duplicated
`StrategyRegistryStore(...)` construction into one shared instance.

## Threat Mitigations Applied

| Threat ID | Disposition | How |
|-----------|-------------|-----|
| T-10-33 | mitigated | `_PAIR_REFUSED_VERBS` refuses `reconfigure` for any pair; gated by `-k reconfigure`. The guard comment cites all three D-17 evidence sites by `file:line`. |
| T-10-34 | mitigated | Guard is verb-scoped; four tests assert a pair ACCEPTS enable/disable/subscribe/unsubscribe. |
| T-10-35 | mitigated | The light verbs read ONLY `config["portfolio_id"]`, validated AND parsed at the boundary; malformed → loud no-op (test). |
| T-10-36 | mitigated | Parameterized SQLAlchemy Core only (Plan 02 store); no SQL constructed on this path. |
| T-10-37 | mitigated | `_persist_strategy` always writes the FULL post-mutation set from `encode_strategy_config`, never the delta. |
| T-10-38 | mitigated | `encode_strategy_config` lazy-imported inside `_persist_strategy`; inertness gate green + module-top grep = 0. |
| T-10-39 | accepted | Per plan — FastAPI ingress owns rate limiting. |
| T-10-40 | mitigated | `at=event.time`; gated by a test asserting the persisted `updated_at` equals the event's business time. |

## Known Stubs

None. `add`/`remove`/`reconfigure` fall through to the existing loud unknown-verb no-op by
design (Plans 07/08), pinned by a test asserting they mutate/persist/emit nothing.

## Threat Flags

None. No new network endpoint, auth path, or schema change. The one new trust boundary
(payload `portfolio_id` → live state + SQL) is parsed and validated at the boundary, and
the durable write goes through the existing parameterized store.

## For Future Plans

- **⚠ Plan 07 (`add`) and Plan 08 (`reconfigure`) MUST reuse `strategy.mark_unwarm()` +
  `self._request_rewarm(strategy)`** — that pair IS the one warm path WD-1 requires. Add
  the verb to `_POLL_FOLLOW_ON_VERBS` if it unwarms; the poll is what drives the re-warm.
- **The child-table FK forces parent-before-child.** Any plan writing
  `strategy_portfolio_subscriptions` must ensure the registry row exists first.
- **The `config` vs `config_json` split (10-05 Deviation 1) did NOT bite here** — the write
  side (`upsert(config=...)`) and the read side (`get()["config"]`) agree. It remains a
  live trap only on the codec **read** path.
- **Anything crossing the store needs a TYPE assertion.** Three consecutive plans (10-04
  Decimal, 10-05 PortfolioId, this one PortfolioId again) shipped a value-equality
  assertion that would have passed over a wrong type. mypy caught two of the three.
- **`_request_rewarm` overloads `Readiness.FAILED` to mean "deliberately unwarmed".**
  Functionally correct today (the streak counter is untouched), but if a future plan needs
  to tell "backfill errored" from "operator re-enabled" in observability, that is where a
  distinct readiness state would go.

## Self-Check: PASSED

- `tests/unit/events/test_strategy_command_vocabulary.py` — FOUND, tracked
- `tests/unit/strategy/test_mark_unwarm.py` — FOUND, tracked
- `tests/unit/strategy/test_strategy_command_verbs.py` — FOUND, tracked
- Commits `ef5bc4cb`, `b46a3b0b`, `e5b6d573`, `f7389b48`, `06705d37`, `56db7b04` — all
  verified in `git log`
- Working tree clean; `git diff --diff-filter=D 97ff49b3..HEAD` empty (no deletions)
- No modifications to STATE.md / ROADMAP.md (orchestrator-owned)

## TDD Gate Compliance

All three tasks followed RED → GREEN, gates present and correctly ordered:
`test(10-06) ef5bc4cb` → `feat(10-06) b46a3b0b`; `test(10-06) e5b6d573` →
`feat(10-06) f7389b48`; `test(10-06) 06705d37` → `feat(10-06) 56db7b04`. Each RED was
verified failing for the intended reason (`AttributeError: no attribute 'mark_unwarm'`,
not a collection error). No REFACTOR commits — none needed.
