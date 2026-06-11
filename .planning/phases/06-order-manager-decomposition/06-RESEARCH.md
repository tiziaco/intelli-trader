# Phase 6: Order-Manager Decomposition - Research

**Researched:** 2026-06-11
**Domain:** Brownfield pure code-motion refactor (Python 3.13) — splitting a 1295-line god-module into collaborator subpackages under `order_handler/`, mirroring `portfolio_handler/`, with a byte-exact golden-master gate.
**Confidence:** HIGH (all claims verified against current source in this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-00 through D-15 — verbatim summary)

- **D-00 (milestone gate, inherited):** Every change is pure code-motion / behavior-preserving — golden master byte-exact (134 trades / `46189.87730727451`); `tests/integration` oracle held; `tests/e2e` 58/58; `mypy --strict` clean; determinism double-run byte-identical. No new float-for-money; single UUIDv7 scheme. This is the FRAGILE-zone isolation phase: NOTHING else ships in it.
- **D-01 (4th `lifecycle/` bucket):** `modify_order` / `cancel_order` move to a NEW `lifecycle/` collaborator (`LifecycleManager`), an intentional recorded extension of the ROADMAP 3-bucket set. Downstream verifier MUST treat `lifecycle/` as intended structure, not scope creep.
- **D-02 (read delegators stay on the facade):** The 7 read/query pass-throughs stay on `OrderManager`. `OrderHandler.get_X` keeps delegating to `OrderManager.get_X`. No `queries/` folder.
- **D-03 (helper placement):** `_estimate_commission` → `admission/`; `_PendingBracket` → `brackets/` with `BracketBook`. BOTH signal entries (`process_signal`, `create_orders_from_signal`) → `admission/`.
- **D-04 (coordinator-owned star):** `OrderManager` constructs ONE `BracketBook` and injects it into the three collaborators that touch shared state (`brackets`, `reconcile`, `lifecycle`). Clean star topology.
- **D-05 (thin `BracketBook` class):** `brackets/bracket_book.py` wraps `Dict[OrderId, _PendingBracket]` with named methods (`arm`/`get`/`consume`/`refresh_quantity`) that are 1:1 wrappers over current dict ops — `pop(.., None)` and `replace(...)` preserved exactly.
- **D-06 (layering unchanged):** `OrderHandler` stays the queue boundary; `OrderManager` stays the no-queue coordinator. Decomposition splits internals, not the handler/manager layers.
- **D-07 (full Option B, entry-points relocate INTACT):** `process_signal`/`create_orders_from_signal` → `admission/`, `on_fill` → `reconcile/`, each as a whole intact unit. `on_fill`'s `try`/`finally`/`should_release` travels as ONE indivisible unit, NEVER bisected.
- **D-08 (cross-stage coupling is stateless):** `_bracket_levels` → stateless `brackets/levels.py` imported by both bracket assembly and the fill-anchored path. `admission`/`reconcile` hold NO ref to the `brackets` collaborator — only shared injected `BracketBook` + pure function imports.
- **D-09 (constructor injection):** `OrderManager` builds each collaborator once at `__init__`, passing the subset of shared deps it needs.
- **D-10 (incremental, golden-gated, reconcile last):** Extraction order: **(1)** introduce `BracketBook` in place → **(2)** `brackets/` → **(3)** `admission/` → **(4)** `lifecycle/` → **(5)** `reconcile/` (LAST). Likely one plan per extraction.
- **D-11 (full milestone gate per step):** Run the whole gate after EACH extraction; determinism double-run at the `reconcile/` step.
- **D-12 (mirror `portfolio_handler` exactly):** Subfolder-per-collaborator each with `__init__.py` re-exporting its manager. Unprefixed `<Domain>Manager` names. Collaborators stay INTERNAL — `order_handler/__init__.py` UNCHANGED.
- **D-13 (strictly zero cleanup + spot-and-log):** Pure code-motion only. Only mechanical move-inherent adjustments (import paths, `BracketBook` wrapper, new module docstrings). Any new finding → 999.5 backlog, not fixed inline.
- **D-14 (keep facade-level tests as-is):** Existing tests keep passing through `OrderHandler`/`OrderManager` public methods. No per-collaborator test files.
- **D-15 (lean `BracketBook` unit test):** ONE focused unit test for the new `BracketBook` primitive (`arm`/`get`/`consume`/`refresh_quantity` + idempotent `consume` returning `None` on missing key).

### Claude's Discretion
- Exact wave/plan decomposition within D-10's ordering (likely one plan per extraction step).
- Exact signatures of `BracketBook` methods and `levels.py` helper (must be 1:1 behavior-equal).
- Precise per-method subset of deps injected into each collaborator (D-09).
- Whether `_build_primary_order` lands in `admission/` or `brackets/` — minor; planner traces the call graph. **(See §Architecture: this research confirms `admission/`.)**
- Module-docstring wording (must cite load-bearing tags: D-13 PercentFromFill, WR-03/WR-04, T-05-17, T-07-15, RESEARCH Pattern 5).

### Deferred Ideas (OUT OF SCOPE)
- Refactor / streamline `on_fill` reconciliation + `should_release` flow → milestone 999.5.
- Rename manager-layer `process_signal` (for symmetry with `on_fill`) → future naming touch.
- 999.5-booked `order_manager.py` items spotted during scout: W2-02 `action: str`→`Side`; W1-11 double `get_position()`; W4-09 `create_order` second unvalidated path; SYN-05 `OrderConfig` + `market_execution` enum.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MOD-01 | `order_manager.py` (1295-line god-module) decomposed into `admission/`, `brackets/`, `reconcile/` (+ `lifecycle/` per D-01) collaborators under `order_handler/`, mirroring `portfolio_handler/`, as pure code-motion with no semantics change; terminal-status / `should_release` / `finally`-release interplay unchanged; golden master byte-exact. | §Architecture Patterns (verified method→bucket map), §Common Pitfalls (the 3 landmines), §Validation Architecture (the full gate). The decomposition target structure is verified buildable against the current module; the FRAGILE `on_fill` span is mapped line-for-line. |
</phase_requirements>

## Summary

This is a **pure code-motion refactor of a single 1295-line file** with an exhaustively-locked design (D-00 through D-15). There is no library research to do and no alternatives to weigh — the planner needs verified codebase facts and landmines, which this research supplies.

**Three findings materially affect how the planner must sequence the work:**

1. **The "`order_handler/` is TAB-indented" claim in CONTEXT.md is only HALF true, and the mirror template is the WRONG indentation model.** `order_manager.py` (and the code being moved out of it) is **TAB-indented**, but the `portfolio_handler/` template (`cash_manager.py`) is **4-SPACE-indented**, and four existing `order_handler/` siblings (`base.py`, `order_validator.py`, `sizing_resolver.py`, the whole `storage/` subdir) are **4-SPACE**. The moved code is byte-identical only if the new collaborator files are **TAB-indented** (matching the source it came from), NOT space-indented like the portfolio template. Mirroring the *layout* of `portfolio_handler/` must not be confused with mirroring its *indentation*.

2. **One existing test reaches into `OrderManager._pending_brackets` as a raw dict** (`test_sltp_policy.py`, 4 sites: `== {}` ×3 and `order_id in ...` ×1). D-10 step (1) replaces `_pending_brackets` with a `BracketBook` class. This test will break unless `BracketBook` supports `__eq__`/`__contains__`/`len`, OR the attribute keeps dict semantics, OR the test is updated. D-14 ("keep facade tests as-is") does not cover this test because it is NOT facade-level — it asserts on an internal attribute. **The planner must explicitly resolve this in step (1).**

3. **`on_fill` is the FRAGILE unit and its `should_release` flag spans the full method body→`finally`** (lines 139–287, flag set at 173/208, consumed at 270). It must move as one indivisible block. This is criterion 2 (byte-for-byte unchanged) and the LAST extraction (D-10 step 5).

**Primary recommendation:** Plan one extraction per D-10 step. In step (1), make `BracketBook` a dict-compatible wrapper (support `__eq__`, `__contains__`, `__len__`, or expose the raw dict) so `test_sltp_policy.py` survives without edits — OR explicitly schedule a minimal test update as a move-inherent change (D-13 allows mechanical adjustments). All new collaborator files must be TAB-indented. The `on_fill` move (step 5) is byte-exact-or-nothing.

## Architectural Responsibility Map

This is a single-tier (in-process library) refactor — there is no browser/API/CDN/DB tier split. The relevant "tiers" are the **layering bands** within the order domain, which the decomposition must preserve (D-06):

| Capability | Primary Layer | Secondary Layer | Rationale |
|------------|--------------|-----------------|-----------|
| Queue I/O (enqueue OrderEvents, `on_signal`/`on_fill` callbacks) | `OrderHandler` (facade) | — | Queue boundary — the ONLY queue-aware order layer (D-06/D-18). UNCHANGED by this phase. |
| Order business-logic orchestration + storage ownership + read API | `OrderManager` (coordinator) | — | No-queue coordinator; owns `OrderStorage` + `BracketBook` + 4 collaborators. Internals split, layer preserved. |
| Signal→order pipeline, admission gates, sizing | `AdmissionManager` (`admission/`) | injected `BracketBook`, `levels.py`, read-model | Pipeline verb; below the coordinator. |
| Bracket assembly + SLTP children + pending-bracket state | `BracketManager` + `BracketBook` (`brackets/`) | `levels.py` (stateless) | Owns the shared state primitive; assembly logic. |
| Fill reconciliation (FRAGILE) + reservation release | `ReconcileManager` (`reconcile/`) | injected `BracketBook`, `levels.py`, read-model | The FRAGILE intact unit; moved LAST. |
| Modify / cancel verbs | `LifecycleManager` (`lifecycle/`) | injected `BracketBook`, read-model | Lifecycle verbs (D-01 4th bucket). |
| Order persistence | `OrderStorage` (`storage/`, existing) | — | Already separated; manager-owned (D-18). UNCHANGED. |

**Invariant the planner must enforce:** collaborators sit BELOW `OrderManager`, have NO queue access, and (per D-08) hold NO reference to sibling collaborators — only the injected `BracketBook` (shared state) and `levels.py` (pure function imports).

## Standard Stack

No external packages are added or changed by this phase. It is pure intra-repo code motion. The "stack" is the existing stdlib + project primitives the moved code already depends on:

| Symbol | Source | Used by (post-split bucket) | Notes |
|--------|--------|------------------------------|-------|
| `to_money` | `..core.money` | admission, brackets, reconcile, lifecycle | Money entry point. Each new module needs this import. `[VERIFIED: grep order_manager.py lines 185,186,633,772,1005,1152,1153,1167]` |
| `replace` | `dataclasses` | lifecycle (modify_order only) | Used ONLY at line 1166 — travels to `lifecycle/`. `[VERIFIED: grep — single site]` |
| `assert_never` | `typing` | brackets (`_assemble_bracket_and_emit`) | Used ONLY at line 650 — travels to `brackets/`. `[VERIFIED: grep — single site]` |
| `_ONE = Decimal("1")` | module-level constant (line 31) | brackets (`levels.py`) | Module-private constant used ONLY by `_bracket_levels` (lines 752–753) — must travel to `brackets/levels.py`. `[VERIFIED: grep — only 2 sites, both in _bracket_levels]` |
| `PortfolioReadModel` | `..core.portfolio_read_model` | admission (gates), reconcile (release), lifecycle (release) | The narrow read boundary, already injected into `OrderManager`. `[VERIFIED: order_manager.py:24]` |
| `OrderStorage` | `.base` | all (manager-owned, injected) | `[VERIFIED: order_manager.py:26]` |
| `EnhancedOrderValidator` | `.order_validator` | admission, lifecycle | `[VERIFIED: order_manager.py:28]` |
| `SizingResolver` | `.sizing_resolver` | admission | `[VERIFIED: order_manager.py:29]` |
| `Order`, `OperationResult` | `.order`, `.operation_result` | all | `[VERIFIED: order_manager.py:18-19]` |
| `OrderEvent`/`SignalEvent`/`FillEvent` | `..events_handler.events` | admission (Signal/Order), reconcile (Fill/Order), brackets/lifecycle (Order) | `[VERIFIED: order_manager.py:27]` |

**No `npm`/`pip`/`cargo` install step. No Package Legitimacy Audit needed (zero external packages).**

## Package Legitimacy Audit

**Not applicable** — this phase installs zero external packages. It is pure intra-repo code motion. No registry verification, slopcheck, or postinstall audit is required.

## Architecture Patterns

### Verified method → target-bucket map (corrected line numbers)

The CONTEXT.md §Code targets line map is **stale by 1–88 lines** in several places (the file is 1295 lines, CONTEXT cited 1295 correctly but individual method lines drifted). Below is the **verified current map** (`grep -n` confirmed this session). The planner must use THESE numbers.

| Method / symbol | CONTEXT.md line | **Actual line** | Target bucket | Callers (internal) | Notes |
|-----------------|-----------------|-----------------|---------------|--------------------|-------|
| `_PendingBracket` (dataclass) | :35 | **:34–52** | `brackets/` (with `BracketBook`) | constructed in `_assemble`:640, `_create_fill_anchored_children`:755 (type hint), `modify_order` `replace`:1166 | D-03. Carries `action: str` (W2-02 deferred — do NOT retype). |
| `OrderManager` (class) | :54 | **:54** | stays (coordinator) | — | — |
| `__init__` | :69 | **:69–126** | stays (coordinator wiring) | — | Constructs `BracketBook` + 4 collaborators (D-04/D-09). `_pending_brackets` init at **:126**. |
| `_estimate_commission` | :128 | **:128–137** | `admission/` | `process_signal`:408 ONLY | D-03 confirmed — single admission caller. |
| `on_fill` (FRAGILE) | :139 | **:139–287** | `reconcile/` (LAST, intact) | — | Criterion 2. See FRAGILE map below. Calls `self.cancel_order`:227 (cross-bucket → lifecycle) and `self._create_fill_anchored_children`:247 (→ brackets) and `self._pending_brackets.pop`:240/249 (→ BracketBook). |
| `process_signal` | :289 | **:289–466** | `admission/` | — (entry point) | D-07 intact. Becomes a 1-line delegation on `OrderManager`. |
| `create_orders_from_signal` | :468 | **:468–511** | `admission/` | — (entry point) | D-03/D-07 intact. 1-line delegation. |
| `_get_signal_exchange` | :513 | **:513–519** | `admission/` | `process_signal`:365, `create_orders_from_signal`:497, `_reject_unsized_signal`:1084 | All callers in admission → `admission/`. |
| `_build_primary_order` | :521 | **:521–566** | **`admission/`** ✅ | `process_signal`:368, `create_orders_from_signal`:499, `_reject_unsized_signal`:1085 | **Resolves the D-15 discretion open question:** ALL 3 callers are admission-bucket methods → place in `admission/`, NOT `brackets/`. |
| `_assemble_bracket_and_emit` | :568 | **:568–737** | `brackets/` | `process_signal`:431, `create_orders_from_signal`:503 | Arms `_pending_brackets`:640, disarms:729. Calls `self._bracket_levels`:632. Uses `assert_never`:650. |
| `_bracket_levels` | :739 | **:739–753** | `brackets/levels.py` (stateless) | `_assemble_bracket_and_emit`:632, `_create_fill_anchored_children`:773 | D-08 — pure function, used by BOTH bracket assembly AND reconcile's fill-anchored path → stateless shared module. Uses `_ONE`. |
| `_create_fill_anchored_children` | :755 | **:755–806** | `brackets/` | `on_fill`:247 ONLY | Called from reconcile. Per D-08, reconcile imports this rather than holding a brackets ref — confirm placement: it builds children (bracket concern) so `brackets/`, imported by reconcile. |
| `_enforce_direction_admission` | :808 | **:808–870** | `admission/` | `process_signal`:340 | — |
| `_enforce_position_admission` | :872 | **:872–962** | `admission/` | `process_signal`:349 | — |
| `_resolve_signal_quantity` | :964 | **:964–1060** | `admission/` | `process_signal`:361, `create_orders_from_signal`:493 | — |
| `_reject_unsized_signal` | :1062 | **:1062–1101** | `admission/` | 6 sites (851,862,931,952,1011,1060) — all admission | — |
| `modify_order` | :1103 | **:1103–1189** | `lifecycle/` | — (public API) | Uses `_pending_brackets.get`:1164 + `[]=`+`replace`:1166–67 → BracketBook.refresh. Uses `replace` import. |
| `cancel_order` | :1191 | **:1191–1263** | `lifecycle/` | `on_fill`:227 (cross-bucket call from reconcile!) | **Cross-bucket call:** `on_fill` (reconcile) calls `self.cancel_order` (lifecycle). See Pitfall 3. Uses `_pending_brackets.pop`:1231 → BracketBook.consume. |
| read delegators (7) | :1269–1295 | **:1269–1295** | stay on `OrderManager` | called by `OrderHandler` | D-02. UNCHANGED. |

### The `_pending_brackets` → `BracketBook` site map (D-05, byte-equal wrappers)

All 8 sites verified this session. Each must become a 1:1 `BracketBook` method call:

| Line | Current dict op | Bucket after split | Proposed `BracketBook` method | Semantics to preserve |
|------|-----------------|--------------------|--------------------------------|------------------------|
| **:126** | `self._pending_brackets: Dict[OrderId, _PendingBracket] = {}` | coordinator `__init__` | `self._brackets = BracketBook()` (owns the dict) | Empty book at construction. |
| **:240** | `pending = self._pending_brackets.pop(order_id, None)` | reconcile (`on_fill`) | `pending = book.consume(order_id)` | `pop(.., None)` → returns entry or `None`, removes it. **Idempotent on missing key (D-15).** |
| **:249** | `self._pending_brackets.pop(order_id, None)` | reconcile (`on_fill`) | `book.consume(order_id)` (discard return) | Same `pop(.., None)`; non-EXECUTED terminal discards the entry. |
| **:640** | `self._pending_brackets[primary.id] = _PendingBracket(...)` | brackets (`_assemble`) | `book.arm(primary.id, _PendingBracket(...))` | `[]=` assignment. |
| **:729** | `self._pending_brackets.pop(primary.id, None)` | brackets (`_assemble` except) | `book.consume(primary.id)` (discard) | Disarm on assembly failure. |
| **:1164** | `pending = self._pending_brackets.get(order.id)` | lifecycle (`modify_order`) | `pending = book.get(order.id)` | `.get` → returns entry or `None`, does NOT remove. |
| **:1166–67** | `self._pending_brackets[order.id] = replace(pending, quantity=to_money(new_quantity))` | lifecycle (`modify_order`) | `book.refresh_quantity(order.id, to_money(new_quantity))` (wraps `replace`) | `replace(...)` preserved exactly inside the wrapper. |
| **:1231** | `self._pending_brackets.pop(order.id, None)` | lifecycle (`cancel_order`) | `book.consume(order.id)` (discard) | Disarm on local cancel. |

**Three distinct semantics the wrappers must keep:** `consume` = `pop(.., None)` (read-and-remove, None on miss), `get` = `.get` (read, no remove, None on miss), `arm` = `[]=` (write), `refresh_quantity` = `get`-then-`replace`-then-`[]=` (the modify path).

### The FRAGILE `on_fill` reconciliation map (criterion 2 — byte-for-byte unchanged)

`on_fill` spans **lines 139–287** (149 lines). The `should_release`/`try`/`finally` interplay is the criterion-2 invariant. Verified line-for-line:

| Concern | Line(s) | Detail |
|---------|---------|--------|
| `should_release = False` (init) | **:173** | Set to `False` BEFORE the `try`. Guards the non-terminal early-return. |
| `body_raised = False` (init) | **:174** | Distinguishes "body raised" vs "release raised" in the `finally`. |
| `try:` opens | **:175** | — |
| Unknown-status early `return` (holds reservation) | **:205** | `should_release` still `False` here → `finally` does NOT release. INTENTIONAL. |
| `should_release = True` (arm) | **:208** | Set AFTER a terminal status (EXECUTED/CANCELLED/REFUSED) is confirmed, BEFORE any further work, so a raise below still releases. |
| `self.order_storage.update_order(order)` | **:214** | — |
| WR-05 orphaned-child cancel loop → `self.cancel_order(...)` | **:223–231** | **Cross-bucket call into `lifecycle/`** (see Pitfall 3). |
| `pending = self._pending_brackets.pop(order_id, None)` (consume) | **:240** | EXECUTED path. |
| `self._create_fill_anchored_children(...)` | **:247** | Cross-bucket call into `brackets/`. |
| `self._pending_brackets.pop(order_id, None)` (discard) | **:249** | non-EXECUTED terminal path. |
| `except Exception as e:` → log + `body_raised = True` + `raise` | **:250–261** | Backtest fail-fast (WR-04). |
| `finally:` | **:262** | — |
| `if should_release and self.portfolio_handler is not None:` → `self.portfolio_handler.release(order.portfolio_id, order.id)` | **:270–273** | The idempotent terminal release (T-05-17). |
| Inner `except` (release failure): log; re-raise ONLY if `not body_raised` | **:274–286** | WR-03 — never mask the original body exception. |
| `return out_events` | **:287** | — |

**Mandate for the planner:** the entire 139–287 block moves to `ReconcileManager.on_fill` as ONE unit with ZERO line edits except (a) `self._pending_brackets.pop` → `self._brackets.consume`, (b) `self.cancel_order` → the injected lifecycle/coordinator delegation, (c) `self._create_fill_anchored_children` → the injected brackets helper/import. Indentation stays TAB. No reordering of the `should_release` set/consume.

### Recommended project structure (verified mirror of `portfolio_handler/`)

```
order_handler/
  __init__.py              # UNCHANGED (D-12) — exports OrderHandler/Order/OrderType/OrderStatus/OrderStorage/storage only
  order_handler.py         # UNCHANGED queue facade (TAB)
  order_manager.py         # SHRINKS to: __init__ wiring + read delegators + 1-line delegations (TAB)
  base.py                  # existing (4-SPACE)
  operation_result.py      # existing (TAB)
  order.py                 # existing (TAB)
  order_validator.py       # existing (4-SPACE)
  sizing_resolver.py       # existing (4-SPACE)
  storage/                 # existing (4-SPACE)
  admission/
    __init__.py            # re-export AdmissionManager (4-SPACE __init__ ok — see indentation note)
    admission_manager.py   # AdmissionManager (TAB — moved from order_manager.py)
  brackets/
    __init__.py            # re-export BracketManager, BracketBook
    bracket_manager.py     # BracketManager (TAB)
    bracket_book.py        # BracketBook + _PendingBracket (TAB)
    levels.py              # stateless _bracket_levels + _ONE (TAB)
  reconcile/
    __init__.py            # re-export ReconcileManager
    reconcile_manager.py   # ReconcileManager — on_fill intact (TAB)
  lifecycle/
    __init__.py            # re-export LifecycleManager
    lifecycle_manager.py   # LifecycleManager — modify/cancel (TAB)
```

The `__init__.py` re-export pattern is verified against `cash/__init__.py` and `position/__init__.py` (both: short docstring + `from .X import Y` + `__all__ = [...]`).

### Pattern 1: Coordinator-owned star with constructor injection (D-04/D-09)

**What:** `OrderManager.__init__` constructs ONE `BracketBook` and passes it (plus the dep subset each needs) to the 4 collaborators. Collaborators hold refs as instance attrs. Mirrors `Portfolio._init_managers` (verified: `portfolio.py:83-97`).

**Verified constructor deps `OrderManager.__init__` currently receives/constructs (lines 69–126):**
```
Received params:  order_storage, logger, market_execution="immediate",
                  portfolio_handler=None, commission_estimator=None
Constructs:       self.market_execution = MarketExecution(market_execution)   # :108
                  self.order_validator = EnhancedOrderValidator(portfolio_handler) if portfolio_handler else None   # :113
                  self.sizing_resolver = SizingResolver(portfolio_handler) if portfolio_handler else None   # :119
                  self._pending_brackets = {}   # :126  → becomes BracketBook()
```

**Per-collaborator injected dep subset (derived from verified call graph):**
| Collaborator | Needs |
|--------------|-------|
| `AdmissionManager` | `order_storage`, `logger`, `order_validator`, `sizing_resolver`, `portfolio_handler` (read-model), `commission_estimator`, `BracketManager`-or-`levels`-for-assembly, `BracketBook` |
| `BracketManager` | `order_storage`, `logger`, `BracketBook`, `levels` (import) |
| `ReconcileManager` | `order_storage`, `logger`, `portfolio_handler` (release), `BracketBook`, `_create_fill_anchored_children` (brackets import), `cancel_order` (lifecycle delegation — see Pitfall 3) |
| `LifecycleManager` | `order_storage`, `logger`, `order_validator`, `portfolio_handler` (release), `BracketBook` |

**External ctor signature of `OrderManager` is UNCHANGED** — `OrderHandler` constructs it with the same 5-arg call (`order_handler.py:73-79`, verified). Only internals rewire. `TradingSystem`/`LiveTradingSystem` are untouched.

### Anti-Patterns to Avoid

- **Normalizing indentation when moving code.** The single worst failure mode. Moved code is TAB; the portfolio template is SPACE. Do NOT "tidy" to match the template's spaces — that re-indents every moved line and the golden gate is the only proof you broke nothing, but a mixed-indent Python file may not even import. Match the SOURCE (tabs).
- **Bisecting `on_fill`'s `should_release`/`finally`.** Forbidden by criterion 2 and D-07.
- **Adding a `queries/` folder for reads.** D-02 — reads stay on the coordinator.
- **Retyping `_PendingBracket.action: str` → `Side`.** That is W2-02, deferred to 999.5 (D-13). The dataclass moves verbatim.
- **Giving `admission`/`reconcile` a reference to the `brackets` collaborator object.** D-08 — they use the injected `BracketBook` (state) + import `levels`/`_create_fill_anchored_children` (pure-ish helpers), never a sibling-class edge.
- **Per-collaborator test files importing internal classes.** D-14 — re-introduces the internals-coupling NAME-04 just removed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Verifying behavior is unchanged | A bespoke diff script | The existing `tests/integration/test_backtest_oracle.py` (`pdt.assert_frame_equal(check_exact=True)`) | Already frozen, column-level failure messages, no float tolerance. `[VERIFIED: read test file]` |
| Determinism proof | A new double-run harness | `tests/e2e/robust/test_determinism.py` (imports `tests.e2e.conftest._build_and_run`) | Existing in-process double-run. `[VERIFIED: read test file]` |
| Pending-bracket idempotency | New conditional logic | Keep `pop(.., None)` semantics inside `BracketBook.consume` | The idempotency IS the current `pop` default; the wrapper preserves it byte-equal (D-05/D-15). |

**Key insight:** the entire verification apparatus already exists and is frozen. This phase writes essentially zero new test *logic* — only the one lean `BracketBook` unit test (D-15). The gate is the existing oracle + e2e + mypy + determinism suite.

## Runtime State Inventory

This phase touches NO runtime state — it is pure in-process code motion within one Python package. Verified explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None.** `_pending_brackets` is in-memory instance state reconstructed each run; no DB/datastore key encodes a module path or class name. Order storage is `in_memory` for backtest. | none |
| Live service config | **None.** No external service references `OrderManager` internals. | none |
| OS-registered state | **None.** No Task Scheduler / systemd / pm2 entry references these modules. | none |
| Secrets/env vars | **None.** No env var or secret key names `order_manager` internals. | none |
| Build artifacts / installed packages | **None requiring action.** Editable Poetry install resolves `itrader` from source; new subpackages are importable without reinstall. `__pycache__` is stale-safe (Python recompiles). **Note:** the MEMORY.md "worktree .venv shadowing" hazard applies — if running in a worktree, prepend `PYTHONPATH="$PWD"` so pytest/mypy see the new modules, not a shadowing editable install. | none (but heed PYTHONPATH in worktrees) |

**Verified by:** grep across `itrader/` and `tests/` for external importers of `order_manager` internals — only `order_handler.py` (imports `OrderManager` the class) and `test_order_manager.py` (imports `OrderManager` the class). No external code imports `_PendingBracket`, `_pending_brackets`, or any private helper. `[VERIFIED: grep this session]`

## Common Pitfalls

### Pitfall 1: Indentation mismatch between moved code (TAB) and the mirror template (SPACE) — CRITICAL

**What goes wrong:** CONTEXT.md says "`order_handler/` is TAB-indented" and "mirror `portfolio_handler` exactly." These two directives conflict on indentation: the mirror template `cash_manager.py` is **4-SPACE** (479 space-indented lines, 0 tab lines — verified), while the code being moved out of `order_manager.py` is **TAB** (1159 tab lines, 0 space lines — verified). If the executor creates new collaborator files in spaces (copying the template's style) and pastes TAB-sourced code, the file is mixed-indentation and may not import; if they re-indent the moved code to spaces, every moved line changes and the diff is no longer a clean move.

**Why it happens:** "mirror `portfolio_handler`" is ambiguous — it means *layout* (subfolder + `__init__.py` re-export), NOT *whitespace*. Four `order_handler/` siblings are already 4-SPACE (`base.py`, `order_validator.py`, `sizing_resolver.py`, `storage/*`), so the package is genuinely mixed and there is no single "house style" to default to.

**How to avoid:** New collaborator files holding code moved FROM `order_manager.py` must be **TAB-indented** (match the source). The `__init__.py` re-export files are new tiny files — either indentation works since they have no nested blocks beyond the module docstring + imports; for consistency with the moved code, prefer TAB, but a 4-space `__init__.py` (like `cash/__init__.py`) is harmless as it has no mixed blocks. **Never re-indent moved code.**

**Warning signs:** `TabError`/`IndentationError` on import; a `git diff` showing whole-line changes on moved code instead of pure additions/deletions; `mypy --strict` failing to parse.

### Pitfall 2: `test_sltp_policy.py` reaches into `_pending_brackets` as a raw dict — D-14 does NOT cover it

**What goes wrong:** `test_sltp_policy.py` asserts on `harness.order_handler.order_manager._pending_brackets` at 4 sites:
- `== {}` (lines 208, 249, 272) — relies on the attribute being a dict-equal-to-empty
- `parent_event.order_id in ..._pending_brackets` (line 265) — relies on `__contains__`

When D-10 step (1) replaces the raw dict with a `BracketBook` instance, `book == {}` and `order_id in book` either raise or silently return wrong results unless `BracketBook` implements `__eq__`, `__contains__`, and ideally `__len__`. D-14 ("keep facade-level tests as-is") explicitly assumes tests go through public methods — but this test reaches an internal attribute, so D-14's protection does not apply.

**Why it happens:** This test predates the decomposition and was written against the raw-dict internal. The NAME-04 hygiene pass (Phase 5) removed most internals-coupling but left these 4 SLTP-policy assertions.

**How to avoid — planner must pick ONE explicitly in step (1):**
- **(a) Recommended:** make `BracketBook` dict-compatible — implement `__eq__` (compares the wrapped dict, so `book == {}` works), `__contains__`, and `__len__`. This keeps the test untouched (honors D-14's spirit) and the change is move-inherent (D-13-permitted: the wrapper is the new primitive). The D-15 unit test then also covers these dunders.
- **(b) Acceptable:** update the 4 assertions to `book.get(id) is None` / `id in book`-via-method as a mechanical move-inherent edit (D-13 "mechanical adjustments inherent to the move"). Lower-risk to the wrapper API but edits a test the golden discipline relies on.
- **(c) Avoid:** leaving `OrderManager._pending_brackets` as a public raw dict alongside the BracketBook — defeats D-05's "single owner."

**Warning signs:** `test_sltp_policy.py` failing with `TypeError`/`AssertionError` immediately after step (1), before any code is even moved out.

### Pitfall 3: Two cross-bucket calls inside the FRAGILE `on_fill` — reconcile→lifecycle and reconcile→brackets

**What goes wrong:** `on_fill` (reconcile bucket) calls `self.cancel_order` (line 227, lifecycle bucket) and `self._create_fill_anchored_children` (line 247, brackets bucket). After the split these are no longer same-class `self.` calls. If the planner naively gives `ReconcileManager` a direct reference to `LifecycleManager` and `BracketManager`, it creates the stateful sibling edges D-08 forbids.

**Why it happens:** `on_fill`'s orphaned-child WR-05 logic cancels bracket children (a lifecycle verb), and its EXECUTED path creates fill-anchored children (a bracket concern). These were free method calls inside one class; the split exposes them as cross-bucket edges.

**How to avoid:**
- `_create_fill_anchored_children` → per D-08, place in `brackets/` and have reconcile **import the function/helper** (it is near-pure: takes `parent`, `pending`, `fill_event`, uses `order_storage` + `levels` + `logger`). Avoid a sibling-class ref by either making it a module function in `brackets/` taking its deps as args, or accepting the documented exception. **Planner must decide and record.**
- `self.cancel_order` → the cleaner option is to route the orphaned-child cancel back through the **coordinator** (`OrderManager`), which owns all collaborators — i.e., reconcile calls an injected coordinator callback rather than holding a `LifecycleManager` ref. This preserves the star topology (D-04: all depend on the coordinator-owned shared state, not on each other). **Planner must specify the exact wiring; this is the single trickiest seam in the phase and lands in the LAST, most-scrutinized extraction.**

**Warning signs:** circular import between `reconcile_manager.py` and `lifecycle_manager.py`/`bracket_manager.py`; a `ReconcileManager.__init__` that takes sibling-manager instances (the D-08 red flag).

### Pitfall 4: `test_order_manager.py` imports `OrderManager` directly

**What goes wrong:** `test_order_manager.py:21` does `from itrader.order_handler.order_manager import OrderManager`. This is fine (it imports the coordinator class, which stays), but if the extraction accidentally moves the class or changes its public surface, this test breaks. The 7 read delegators and the public `process_signal`/`on_fill`/`modify_order`/`cancel_order`/`create_orders_from_signal` MUST remain on `OrderManager` as delegations (D-02/D-07).

**How to avoid:** keep `OrderManager` importable from the same path with the same public method names. The delegations are 1-line forwards. `[VERIFIED: only this test + order_handler.py import OrderManager]`

## Code Examples

### `BracketBook` 1:1 wrapper shape (D-05) — illustrative, TAB-indented

```python
# Source: derived from order_manager.py dict ops (lines 126,240,249,640,729,1164,1166,1231)
# brackets/bracket_book.py — TAB-indented to match moved code
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Dict, Optional
from ..core.ids import OrderId
# _PendingBracket moves here too (D-03)

class BracketBook:
	"""Single owner of the PercentFromFill pending-bracket map (D-04/D-05).

	1:1 wrappers over the prior raw-dict ops — pop(.., None) and replace(...)
	preserved exactly (RESEARCH Pattern 5 Option B, D-13, T-07-15).
	"""
	def __init__(self) -> None:
		self._pending: Dict[OrderId, "_PendingBracket"] = {}

	def arm(self, order_id: OrderId, bracket: "_PendingBracket") -> None:
		self._pending[order_id] = bracket          # was [order_id] = ...

	def get(self, order_id: OrderId) -> "Optional[_PendingBracket]":
		return self._pending.get(order_id)         # was .get(id)

	def consume(self, order_id: OrderId) -> "Optional[_PendingBracket]":
		return self._pending.pop(order_id, None)   # was .pop(id, None) — idempotent

	def refresh_quantity(self, order_id: OrderId, quantity: Decimal) -> None:
		pending = self._pending.get(order_id)
		if pending is not None:
			self._pending[order_id] = replace(pending, quantity=quantity)

	# Pitfall 2: dict-compat dunders so test_sltp_policy.py survives untouched (D-14)
	def __eq__(self, other: object) -> bool:
		if isinstance(other, dict):
			return self._pending == other
		if isinstance(other, BracketBook):
			return self._pending == other._pending
		return NotImplemented

	def __contains__(self, order_id: object) -> bool:
		return order_id in self._pending

	def __len__(self) -> int:
		return len(self._pending)
```

*(Signatures are Claude's-discretion per D-15; the load-bearing requirement is byte-equal behavior to the dict ops. `__hash__` should be set to `None` implicitly via `__eq__`, which is fine for a mutable container.)*

## State of the Art

Not applicable — no external technology, library, or API is involved. This is an internal refactor governed entirely by locked project decisions. There is no "old vs current approach" to track.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `__init__.py` re-export files may be 4-space (like `cash/__init__.py`) without breaking anything, since they have no mixed nested blocks. | Pitfall 1 | LOW — if wrong, a trivial re-indent fixes it; caught by import at step gate. |
| A2 | The cleanest wiring for the reconcile→lifecycle `cancel_order` call is a coordinator callback (star topology), not a sibling ref. | Pitfall 3 | MEDIUM — if the planner picks a sibling ref instead, it violates D-08; either way the golden gate catches behavior breakage, but the topology decision is a design call the planner must make explicitly. |
| A3 | `BracketBook.__eq__` against `dict` + `__contains__` is sufficient to keep `test_sltp_policy.py` green without editing it. | Pitfall 2 | LOW — verified the 4 access patterns (`== {}`, `in`); if a 5th pattern exists elsewhere it would surface at step (1)'s gate. Grep confirmed only these 4 live sites. |

**Note:** All factual codebase claims (line numbers, indentation counts, call graph, test access sites, dep imports) are `[VERIFIED]` via grep/read this session — they are NOT assumptions. Only the three design-judgment items above are assumed and flagged for the planner.

## Open Questions

1. **reconcile→lifecycle `cancel_order` wiring (the WR-05 orphaned-child cancel at line 227).**
   - What we know: `on_fill` (reconcile) calls `self.cancel_order` (lifecycle). After the split this is a cross-bucket edge in the FRAGILE unit.
   - What's unclear: coordinator-callback vs injected-lifecycle-ref vs keep-`cancel_order`-reachable-on-coordinator.
   - Recommendation: route through the coordinator (`OrderManager`) to preserve the D-04 star and avoid a circular import. Decide in the planning of step (5).

2. **`_create_fill_anchored_children` placement (brackets, called from reconcile).**
   - What we know: D-08 says reconcile imports pure helpers from `brackets/` rather than holding a brackets ref; this method builds children (a bracket concern) but is invoked from `on_fill`.
   - What's unclear: module function vs `BracketManager` method.
   - Recommendation: a module-level function in `brackets/` (or on `BracketBook`/a stateless helper) taking `order_storage`/`logger`/`levels` as args, imported by reconcile — avoids the sibling-class edge.

3. **`BracketBook` test-compat: dunders vs test edit (Pitfall 2).** Recommendation: dunders (option a) — keeps the test untouched and gives the D-15 unit test more surface to assert. Planner confirms in step (1).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Poetry + in-project `.venv` | running any test/gate | ✓ (project standard) | per `pyproject.toml` (Python 3.13) | — |
| `pytest` ^8.4.2 | unit/integration/e2e gates | ✓ | 8.4.2 | — |
| `mypy` ^2.1.0 | `mypy --strict` gate | ✓ | 2.1.0 | — |
| `pandas`/`pandas.testing` | oracle frame-equal diff | ✓ | 2.3.3 | — |
| `tests/golden/` frozen artifacts | oracle byte-exact gate | ✓ | present (`summary.json`, `trades.csv`, `equity.csv` verified) | — |
| `scripts/run_backtest.py` | oracle generator (in-process) | ✓ | present | — |

**No missing dependencies.** All gate infrastructure is present and frozen. Worktree caveat (MEMORY.md): prepend `PYTHONPATH="$PWD"` to pytest/mypy invocations if running in a worktree, so the new subpackages are seen rather than a shadowing editable install.

## Validation Architecture

`workflow.nyquist_validation` is `true` (`.planning/config.json`) — this section is REQUIRED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (`--strict-markers`, `--strict-config`, `filterwarnings=["error", ...]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| Quick run command | `poetry run pytest tests/unit/order/ -q` (the directly-affected unit suite) |
| Full suite command | `poetry run pytest tests/ -q` (or per-tier: `make test-unit`, `make test-integration`, `make test-e2e`) |
| Markers | only `unit`, `integration`, `slow`, `e2e` declared; type auto-applied by folder via `tests/conftest.py` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MOD-01 | Golden master byte-exact (134 trades / `final_equity 46189.87730727451`) after EACH extraction | integration (slow) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ |
| MOD-01 | Behavioral identity (trade count + entry/exit/side/pair grid) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py::test_oracle_behavioral_identity -q` | ✅ |
| MOD-01 | Numeric magnitudes EXACT (final_cash/final_equity/realised_pnl + metrics dict) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py::test_oracle_numeric_values -q` | ✅ |
| MOD-01 | e2e scenarios 58/58 (cash release, sltp from_fill/from_decision, admission, matching) | e2e | `poetry run pytest tests/e2e -m e2e -q` (collected: **58** ✅) | ✅ |
| MOD-01 | SLTP pending-bracket lifecycle (the `_pending_brackets`/BracketBook assertions) | unit | `poetry run pytest tests/unit/order/test_sltp_policy.py -q` | ✅ (see Pitfall 2 — may need BracketBook dunders) |
| MOD-01 | Order manager public surface intact | unit | `poetry run pytest tests/unit/order/test_order_manager.py -q` | ✅ |
| MOD-01 | `mypy --strict` clean across all source | static | `poetry run mypy itrader` (config `files=["itrader"]`, `strict=true`) | ✅ |
| MOD-01 | Determinism double-run byte-identical (at the `reconcile/` step, D-11) | e2e | `poetry run pytest tests/e2e/robust/test_determinism.py -q` | ✅ |
| MOD-01 (new) | `BracketBook` primitive unit test — `arm`/`get`/`consume`/`refresh_quantity` + idempotent `consume`→`None` on missing key + dict-compat dunders (D-15) | unit | `poetry run pytest tests/unit/order/test_bracket_book.py -q` | ❌ **Wave 0 — new file** |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/order/ -q && poetry run mypy itrader` (fast, < 30s for the unit slice; mypy a few s).
- **Per wave / per extraction step (D-11 full gate):** `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q && poetry run mypy itrader` — the byte-exact 134/`46189.87730727451` + 58/58 + strict.
- **At the `reconcile/` step additionally:** `poetry run pytest tests/e2e/robust/test_determinism.py -q` (double-run).
- **Phase gate:** full `poetry run pytest tests/ -q` green + `mypy itrader` clean before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/order/test_bracket_book.py` — the ONE new lean unit test for `BracketBook` (D-15). Asserts: `arm`+`get` round-trip; `consume` returns the entry and removes it; `consume` on a missing key returns `None` (idempotent); `refresh_quantity` replaces only the quantity (preserves the other `_PendingBracket` fields); and the dict-compat dunders (`== {}`, `in`, `len`) if option (a) of Pitfall 2 is chosen. TAB-indented (it exercises code moved from a TAB file) — but note `tests/` house style is 4-space; **match the test-package style (4-space) for the test file itself**, since the test is NEW code, not moved code. The MOVED production code stays TAB.
- [ ] No framework install needed — pytest/mypy present.

*(Everything else: existing test infrastructure covers all phase requirements — the oracle, e2e suite, determinism harness, and facade unit tests are all frozen and present.)*

## Security Domain

`security_enforcement` is not present in `.planning/config.json`. Per the standard (absent = enabled), a brief assessment:

This phase is **pure internal code motion with zero new external surface, zero new input parsing, zero new I/O, and zero dependency changes.** No ASVS category is newly engaged:

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | no auth code touched |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | no (unchanged) | `EnhancedOrderValidator` moves verbatim into `admission/`/`lifecycle/` — validation logic byte-unchanged |
| V6 Cryptography | no | no crypto; UUIDv7 via `uuid-utils` untouched |

**Threat patterns:** The only project-specific "tampering" risk class adjacent to this code is the `EventHandler._dispatch` "silent drop" concern — out of scope here (the event router is untouched). The FRAGILE `on_fill` reservation-release (a financial-integrity invariant, not a security boundary) is the real risk surface; it is covered by criterion 2 (byte-exact) and the golden gate, documented in Pitfall 3 and the FRAGILE map above. No new STRIDE exposure is introduced by the move.

## Sources

### Primary (HIGH confidence — verified this session)
- `itrader/order_handler/order_manager.py` (full read + `grep -n` for defs, `_pending_brackets`, helper callers, `replace`/`assert_never`/`to_money`/`_ONE` sites) — the method→bucket map, the 8 `_pending_brackets` sites, the FRAGILE `on_fill` 139–287 span.
- `itrader/order_handler/order_handler.py` (full read) — queue facade unchanged; delegations at :101 (`process_signal`), :119 (`on_fill`), :150 (`modify_order`), :182 (`cancel_order`), :210 (`create_orders_from_signal`), read delegators :240–342.
- `itrader/portfolio_handler/cash/cash_manager.py`, `cash/__init__.py`, `position/__init__.py`, `portfolio.py` — the mirror template; `Portfolio._init_managers` injection pattern (:83–97); `__init__.py` re-export shape.
- Indentation counts via `grep -cP "^\t"` / `^    ` per file — order_manager.py 1159 TAB/0 SPACE; cash_manager.py 0 TAB/479 SPACE; base.py/order_validator.py/sizing_resolver.py/storage/* all SPACE.
- `tests/unit/order/test_sltp_policy.py` (lines 195–279) — the 4 `_pending_brackets` raw-dict access sites.
- `tests/integration/test_backtest_oracle.py` (full read) — the byte-exact oracle gate mechanic.
- `tests/e2e/robust/test_determinism.py` — the double-run determinism harness.
- e2e collection: `pytest tests/e2e -m e2e --collect-only` → **58 collected**.
- `.planning/codebase/CONCERNS.md` (§Tech Debt :19–23, §Fragile Areas :53–68), `.planning/REQUIREMENTS.md` (MOD-01 :104–110), `.planning/codebase/CONVENTIONS.md`, `.planning/config.json`, `Makefile` (test targets).

### Secondary / Tertiary
- None — no external sources needed for an internal code-motion refactor.

## Metadata

**Confidence breakdown:**
- Method→bucket map & line numbers: HIGH — `grep -n` verified every def and call site this session.
- `_pending_brackets`/BracketBook site map: HIGH — all 8 sites read and classified.
- FRAGILE `on_fill` span: HIGH — read line-for-line (139–287).
- Indentation landmine: HIGH — exact tab/space line counts per file.
- Test-coupling landmine: HIGH — the 4 `test_sltp_policy.py` sites read directly.
- Cross-bucket wiring (Pitfall 3) resolution: MEDIUM — the facts (the two cross-bucket calls) are verified; the *recommended* wiring is a design judgment (A2) the planner must lock.

**Research date:** 2026-06-11
**Valid until:** until `order_manager.py` is next edited (line numbers drift on any change). For planning THIS phase off the current tree, valid now. Re-grep line numbers if any commit lands on the file before planning.
