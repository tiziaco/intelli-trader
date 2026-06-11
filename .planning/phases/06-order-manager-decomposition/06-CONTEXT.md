# Phase 6: Order-Manager Decomposition - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Decompose the 1279-line `order_manager.py` god-module into focused collaborators under
`order_handler/`, mirroring the `portfolio_handler/` manager layout — as **pure code-motion,
no semantics change**. This is the dedicated, isolated, **LAST** v1.2 phase: the FRAGILE
fill-reconciliation / reservation-release path is split out on its own so it is never bundled
with behavior fixes (MOD-01, SYN-06).

**Target structure** (the ROADMAP 3-bucket set, extended by one — see D-01):
```
order_handler/
  order_manager.py        # thin coordinator: storage + BracketBook + 4 collaborators + read API; NO queue
  admission/   admission_manager.py   → AdmissionManager   (signal→order pipeline, gates, sizing)
  brackets/    bracket_manager.py     → BracketManager     (bracket assembly + SLTP children)
               bracket_book.py        → BracketBook        (shared pending-bracket state owner)
               levels.py              → stateless _bracket_levels helper
  reconcile/   reconcile_manager.py   → ReconcileManager   (on_fill, FRAGILE — moved intact)
  lifecycle/   lifecycle_manager.py   → LifecycleManager   (modify_order / cancel_order)
  storage/                            (existing)
```

**Verification gate (inherited milestone gate, D-00):** SMA_MACD golden master re-runs
**byte-exact** (134 trades / `final_equity 46189.87730727451`), `pytest tests/integration`
oracle held, `pytest tests/e2e -m e2e` 58/58, `mypy --strict` clean across all source,
determinism double-run byte-identical. This phase re-baselines nothing.

**Out of scope (FRAGILE isolation, criterion 3):** ANY semantics/behavior change; the `on_fill`
reconciliation refactor; the `process_signal` rename; any enum/naming/perf/doc change riding
along; opportunistic cleanup (strictly zero — D-09). All deferred to milestone 999.5.

</domain>

<decisions>
## Implementation Decisions

### Cross-cutting — verification & behavior-preservation
- **D-00 (milestone gate, inherited):** Every change is pure code-motion / behavior-preserving —
  golden master byte-exact (134 trades / `46189.87730727451`); `tests/integration` oracle held;
  `tests/e2e` 58/58; `mypy --strict` clean; determinism double-run byte-identical. No new
  float-for-money; single UUIDv7 scheme. This is the FRAGILE-zone isolation phase: NOTHING else
  ships in it.

### Method placement (Area 1)
- **D-01 (owner choice — 4th `lifecycle/` bucket):** `modify_order` / `cancel_order` move to a NEW
  `lifecycle/` collaborator (`LifecycleManager`), beyond the ROADMAP-literal 3-bucket set
  (`admission/`/`brackets/`/`reconcile/`). This is an **intentional, recorded extension** of
  criterion 1 — the order domain is pipeline/verb-shaped, so `lifecycle/` (modify/cancel verbs) sits
  naturally beside the other verb buckets. The mirror-`portfolio_handler` directive is about the
  *folder-of-collaborators layout*, not about copying which methods `Portfolio` happened to retain.
  Downstream verifier MUST treat `lifecycle/` as intended structure, not scope creep.
- **D-02 (read delegators stay on the facade):** The 7 read/query pass-throughs
  (`get_order_by_id`, `get_orders_by_status`, `get_active_orders`, `get_order_history`,
  `get_orders_by_ticker`, `search_orders`, `count_orders_by_status`) **stay on `OrderManager`** (the
  D-18 read interface; `OrderManager` owns storage). `OrderHandler.get_X` keeps delegating to
  `OrderManager.get_X` exactly as today. No `queries/` folder — reads are not a pipeline verb.
- **D-03 (helper placement):** `_estimate_commission` → `admission/` (its only caller is
  `process_signal` at `:408`). `_PendingBracket` (the bracket value type) → `brackets/`, with the
  `BracketBook`. Both signal entries — `process_signal` (`:289`) AND `create_orders_from_signal`
  (`:468`) — move to `admission/` together (both are signal→order pipelines; `OrderHandler` calls
  both, at `:101` and `:210`).

### Shared bracket state (Area 2)
- **D-04 (owner choice — coordinator-owned star):** `OrderManager` (the coordinator) constructs ONE
  `BracketBook` and **injects it** into the three collaborators that touch the shared state
  (`brackets`, `reconcile`, `lifecycle`). No collaborator owns state another reaches into — clean
  star topology, all depend on the shared `BracketBook`. Mirrors how `Portfolio` owns shared state
  and hands it to its managers. Lowest coupling through the FRAGILE zone.
- **D-05 (owner choice — thin `BracketBook` class):** `brackets/bracket_book.py` wraps the
  `Dict[OrderId, _PendingBracket]` in a small class with named methods
  (`arm`/`get`/`consume`/`refresh_quantity`) that are **1:1 wrappers over the current dict ops** —
  the `pop(.., None)` default and the `replace(...)` preserved exactly. Byte-exact, but gives the
  shared FRAGILE state a real single owner instead of a raw dict reached three ways. Current sites:
  `__init__:126` (own), `on_fill:240/249` (consume), `_assemble...:640/729` (arm/disarm),
  `modify_order:1164-66` (refresh), `cancel_order:1231` (disarm).

### Residual coordinator role + collaborator shape (Area 3)
- **D-06 (layering unchanged — handler vs manager):** `OrderHandler` stays the **queue boundary**
  (the only queue-aware order-domain layer: `on_signal`/`on_fill` callbacks, emits `OrderEvent`s).
  `OrderManager` stays the **no-queue business-logic coordinator** — owns storage + `BracketBook` +
  the four collaborators + the read API, never touches `global_queue` (D-18). Decomposition splits
  `OrderManager`'s *internals*; it does NOT collapse the handler/manager layers.
- **D-07 (owner choice — full Option B, entry-points relocate INTACT):** `process_signal`/
  `create_orders_from_signal` → `admission/`, `on_fill` → `reconcile/`, each relocated as a **whole
  intact unit**. `OrderManager.process_signal`/`on_fill` become one-line delegations. **Critical for
  FRAGILE:** `on_fill`'s `try`/`finally`/`should_release` interplay travels as ONE indivisible unit
  and is NEVER bisected across a coordinator boundary (`should_release` is set in the body at the
  method's line ~70 and consumed in the `finally` at ~132 — they cannot be cleanly separated, and
  splitting them is exactly what criterion 2 forbids). The pure-orchestrator alternative was rejected
  for this reason.
- **D-08 (cross-stage coupling is stateless, not sibling-class):** Where `admission`/`reconcile`
  reach into bracket logic, they use (a) the injected `BracketBook` and (b) **pure shared helpers** —
  `_bracket_levels` (used by both bracket assembly and the fill-anchored path) extracted to a
  stateless `brackets/levels.py` imported by both. So `admission`/`reconcile` hold **no ref to the
  `brackets` collaborator** — there is no stateful sibling edge, only shared injected state + pure
  function imports. This keeps Option B's coupling near-nil while preserving the intact moves.
- **D-09 (constructor injection):** `OrderManager` builds each collaborator once at `__init__`,
  passing the subset of shared deps it needs (`order_storage`, `logger`, `order_validator`,
  `sizing_resolver`, `portfolio_handler` read-model, `commission_estimator`, `market_execution`,
  `BracketBook`); collaborators hold them as instance attrs. Mirrors `portfolio_handler` managers
  (`CashManager`/`PositionManager` hold their refs).

### Sequencing & verification (Area 4)
- **D-10 (owner choice — incremental, golden-gated, reconcile last):** Extract incrementally with the
  golden master re-run gating EACH step, in dependency order: **(1)** introduce `BracketBook` in place
  (wrap `_pending_brackets`, all 7 sites use it; no code moved) → **(2)** extract `brackets/` →
  **(3)** extract `admission/` → **(4)** extract `lifecycle/` → **(5)** extract `reconcile/`
  (`on_fill` intact — FRAGILE, **LAST**). A break points at exactly one extraction; the fragile move
  is isolated to the final, most-scrutinized step. Likely one plan per extraction.
- **D-11 (owner choice — full milestone gate per step):** Run the whole gate after EACH extraction
  (`pytest tests/integration` byte-exact 134/`46189.87730727451`, `tests/e2e` 58/58, `mypy --strict`);
  determinism double-run at the `reconcile/` step. Cheap relative to the FRAGILE risk; catches any
  semantics drift the moment it is introduced.

### Naming & layout (Area 5)
- **D-12 (owner choice — mirror `portfolio_handler` exactly):** Subfolder-per-collaborator, each with
  an `__init__.py` re-exporting its manager (like `cash/__init__.py` re-exports `CashManager`).
  **Unprefixed** `<Domain>Manager` class names — `AdmissionManager`, `BracketManager`,
  `ReconcileManager`, `LifecycleManager` (like `CashManager`, not `OrderAdmissionManager`); plus
  `BracketBook` and a stateless `levels.py`. Collaborators stay **INTERNAL** — `order_handler/__init__.py`
  is UNCHANGED (they are `OrderManager` implementation details, exactly as the portfolio managers are
  not top-barrel-exported; the top barrel keeps exporting only `OrderHandler`/`Order`/storage).

### Cleanup policy (Area 6)
- **D-13 (owner choice — strictly zero + spot-and-log):** Pure code-motion only; no renames, no perf
  tweaks, no doc rewrites ride along (criterion 3 isolation). Only the mechanical adjustments
  *inherent* to the move (import paths, the `BracketBook` wrapper, new module docstrings citing the
  decision tags). **Evidence-based:** the SAFE `order_manager.py` cleanup is already DONE (Phases 2-5:
  float→Decimal W4-01, str→enum W2-05/W2-06, `_PendingBracket` slots W2-12, `count_orders_by_status`
  W3-10); the remainder is FRAGILE/contract work already deferred to 999.5 (W2-02 `action`→`Side`,
  W1-11 double `get_position`, W4-09 `create_order` path, SYN-05 `OrderConfig`). The 9 broad `except`s
  are deliberate run-mode policy (documented convention — NOT removed). **Spot-and-log:** any genuine
  NEW opportunity the executor notices mid-move is appended to the 999.5 backlog as a finding —
  captured, not fixed inline.

### Test organization (Area 7)
- **D-14 (owner choice — keep facade-level tests as-is):** Existing tests (`test_on_signal`,
  `test_order_manager`, `test_admission_rules`, `test_sltp_policy`, `test_stop_limit_orders`, etc.)
  keep passing through `OrderHandler`/`OrderManager` **public methods** unchanged — they are the
  byte-exact behavior proof and survive the decomposition untouched. **No per-collaborator test files**
  — those would import the internal collaborator classes directly, binding tests to the internal
  decomposition boundaries (re-introducing the internals-coupling Phase 5/NAME-04 just removed, and
  breaking under the deferred 999.5 `reconcile` refactor despite unchanged behavior).
- **D-15 (owner choice — lean `BracketBook` unit test):** Add ONE focused unit test for the
  genuinely-new `BracketBook` primitive (`arm`/`get`/`consume`/`refresh_quantity` + idempotent
  `consume` returning `None` on a missing key). Aligns with the D-10/Phase-3/4 lean-targeted precedent
  (lean assertions where useful, no broad new strategy test).

### Claude's Discretion
- Exact wave/plan decomposition within D-10's ordering (likely one plan per extraction step).
- Exact signatures of the `BracketBook` methods and the stateless `levels.py` helper (must be 1:1
  behavior-equal to current ops).
- Precise per-method subset of deps injected into each collaborator (D-09).
- Whether `_build_primary_order` lands in `admission/` (order creation) or `brackets/` (precedes
  assembly) — minor; planner traces the call graph.
- Module-docstring wording (must cite the load-bearing decision tags: D-13 PercentFromFill,
  WR-03/WR-04, T-05-17, T-07-15, RESEARCH Pattern 5).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §Phase 6 (Order-Manager Decomposition) — goal + 4 success criteria
  (incl. criterion 2: `should_release`/`finally`-release interplay byte-for-byte unchanged;
  criterion 3: FRAGILE-zone isolation, sole change in the phase).
- `.planning/REQUIREMENTS.md` MOD-01 (lines ~106-110) — the single requirement, citing SYN-06 +
  CONCERNS god-module / Fragile Areas.

### Source findings (decomposition directive + risk rating)
- `.planning/codebase/V1.2-CLEANUP-REVIEW.md` — row 53 (SYN-06): the owner directive for the split
  (subfolders within `order_handler/` mirroring `portfolio_handler/`; FRAGILE; byte-exact mandatory;
  pure code-motion; never bundled with behavior fixes). §6 Batch 8 (lines 217-230). Also rows
  documenting the order_manager.py items already done (W4-01, W2-05/06, W2-12, W3-10) and the
  999.5-deferred remainder (W2-02 `action`→`Side` row 39 — FRAGILE, in the bracket/reconcile path;
  W1-11 row 41; W4-09 row 42; SYN-05 row 244).

### FRAGILE-zone invariants (MUST read before touching reconcile/)
- `.planning/codebase/CONCERNS.md` §Tech Debt ("`order_manager.py` is a 1279-line god-module",
  lines 19-23) + §Fragile Areas ("Fill reconciliation + reservation release in `OrderManager`",
  lines 53-57): the `should_release` flag + idempotent release-in-`finally` (WR-04), the
  "stuck reservation corrupts buying power" failure (T-05-17), and the safe-modification rule
  (never change the terminal-status / `should_release` / `finally`-release interplay without the
  golden-master oracle).

### Conventions & precedents
- `CLAUDE.md` §Architecture (handler/manager split; D-18 layering; queue-only; read-model seams) +
  §Conventions (tab/space indentation hazard — `order_handler/` is TAB-indented; the four documented
  conventions incl. broad-`except` run-mode policy — NOT removed).
- `.planning/codebase/CONVENTIONS.md` — the four pinned conventions (config-enum exception,
  broad-`except` run-mode policy, tab/space hazard, dual-layer validator overlap).
- `.planning/codebase/CLEANUP-STANDARD.md` — touched-path standard (D-13 OVERRIDES it to strictly
  zero for this FRAGILE-isolation phase).
- `.planning/phases/05-naming-encapsulation/05-CONTEXT.md` §D-09/D-10 — the NAME-04 internals→public
  test-hygiene direction (D-14 rests on it) + the lean-tests / byte-exact verification precedent.

### Code targets (verified during scout)
- `itrader/order_handler/order_manager.py` (1295 lines) — the module to decompose. Method map:
  `_PendingBracket:35`; `OrderManager:54`; `__init__:69` (shared deps + `_pending_brackets:126`);
  `_estimate_commission:128`; `on_fill:139` (FRAGILE → reconcile/); `process_signal:289`,
  `create_orders_from_signal:468`, `_get_signal_exchange:513`, `_build_primary_order:521`,
  `_enforce_direction_admission:808`, `_enforce_position_admission:872`, `_resolve_signal_quantity:964`,
  `_reject_unsized_signal:1062` (→ admission/); `_assemble_bracket_and_emit:568`, `_bracket_levels:739`
  (→ stateless levels.py), `_create_fill_anchored_children:755` (→ brackets/); `modify_order:1103`,
  `cancel_order:1191` (→ lifecycle/); read delegators `:1269-1295` (stay on OrderManager).
- `itrader/order_handler/order_handler.py:101,210` — the two signal entries the handler delegates to;
  read methods delegate to manager (D-18).
- `itrader/order_handler/{base.py, operation_result.py, order_validator.py, sizing_resolver.py, order.py}`
  — existing standalone modules the new collaborators join; `storage/` subdir is the layout precedent.
- `itrader/portfolio_handler/` — the mirror: `cash/cash_manager.py::CashManager`,
  `position/position_manager.py::PositionManager`, `cash/__init__.py` re-export pattern,
  `__init__.py` exporting only `PortfolioHandler`/`Portfolio` (managers internal).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`portfolio_handler/` IS the template** — `cash/`, `position/`, `transaction/`, `metrics/`
  subdirs each with a `<domain>_manager.py` stateful class + `__init__.py` re-export, owned and
  orchestrated by `Portfolio`. The order split mirrors this 1:1 (D-12).
- **`order_handler/` already has partial separation** — `sizing_resolver.py`, `order_validator.py`,
  `operation_result.py`, `base.py`, `order.py`, `storage/` are already standalone. The new
  collaborator subfolders join an established multi-module package, not a flat file.
- **`PortfolioReadModel` Protocol (`core/portfolio_read_model.py`)** — the narrow read boundary
  `OrderManager` already uses for `release()`/position/cash; injected into the collaborators that need
  it (reconcile/lifecycle for `release`, admission for position-aware gates). SYN-04 confirms it stays
  in `core/` (moving it would force order-domain modules to import the portfolio package).

### Established Patterns
- **Handler/manager split (D-18):** facade → manager → storage, one-directional; manager has NO queue
  access and NO back-ref to the handler. The decomposition preserves this — collaborators sit BELOW
  `OrderManager`, still no queue access.
- **Indentation hazard:** `order_handler/` is **TAB-indented**. Every new collaborator file must be
  TAB-indented; never normalize (a mixed-indent diff breaks a tab file). `core/` (where any enum
  would live) is 4-space — but no enum/core change is in scope here (D-13).
- **Decision-tag docstrings:** modules open with docstrings citing locked decision tags (D-13,
  WR-03/04, T-05-17, RESEARCH Pattern N). The moved code carries its tags; new module docstrings cite
  the same.
- **Byte-exact golden discipline:** prior phases prove pure-structure changes must leave the golden
  master byte-identical; here the entire phase is structure-only, so the gate is the whole proof.

### Integration Points
- **`OrderManager.__init__`** is the wiring point — it constructs the `BracketBook` and the four
  collaborators (D-04/D-09). The `TradingSystem`/`LiveTradingSystem` construction of `OrderManager`
  itself is UNCHANGED (same ctor signature externally; internals rewired).
- **`OrderHandler` entry points** (`on_signal`/`on_fill` + read delegators) are UNCHANGED — they call
  the same `OrderManager` methods, which now one-line-delegate into collaborators (D-07).
- **Cross-stage seams** (D-08): `admission` → `BracketManager`/`levels.py` for assembly; `reconcile` →
  `BracketBook.consume` + `_create_fill_anchored_children` + `portfolio_handler.release`; `lifecycle`
  → `BracketBook` get/refresh/disarm + `release`. All via injected state + pure helpers, no sibling
  collaborator refs.

</code_context>

<specifics>
## Specific Ideas

- **Owner stance — "fragile" ≠ "broken" (D-07/D-13):** the `on_fill` `should_release`/`finally` flow
  is a working fix (T-05-17), not a defect. The phase relocates it INTACT; it does NOT refactor it.
  The decomposition is the *enabler* of the eventual refactor (move it cleanly first, refactor it
  safely later with re-validation), not a competitor to it.
- **Owner stance — clean, consistent, low-confusion structure (D-01/D-07):** the owner chose the 4th
  `lifecycle/` bucket and full Option B specifically for the most self-documenting, symmetric layout
  (every order-lifecycle verb is a named collaborator; one obvious place to find "how does a cancel
  work?"), accepting the recorded deviation from the literal 3-bucket criterion.
- **Owner stance — evidence over dogma on cleanup (D-13):** the strictly-zero cleanup decision was
  made AFTER confirming the safe cleanup is already done and the remainder is FRAGILE/999.5-booked —
  not as blanket conservatism. Hence "spot-and-log" to still capture any genuine new finding.
- **`OrderHandler` is essential, not redundant (D-06):** clarified during discussion — keeping reads
  on `OrderManager` does not eliminate `OrderHandler`; the handler is the queue seam that keeps queue
  I/O out of business logic.

</specifics>

<deferred>
## Deferred Ideas

- **Refactor / streamline `on_fill` reconciliation + `should_release` flow → milestone 999.5.**
  A behavior change (or behavior-risk), forbidden under v1.2's behavior-preserving mandate; needs its
  own oracle re-baseline + external cross-validation (`backtesting.py`/`backtrader`). This phase's
  intact-move into `reconcile/` is the clean, bounded surface that makes that future refactor safe.
- **Rename manager-layer `process_signal` (for symmetry with `on_fill`) → future naming touch.**
  The isolation rule (criterion 3) forbids a ride-along naming change. The consistent target is itself
  an open design question (the manager isn't an event handler, so `on_signal` may be the wrong target;
  `process_signal` + a renamed `process_fill`/`reconcile_fill` is equally valid) — deserves its own
  decision, not a bundle.
- **999.5-booked `order_manager.py` items spotted during scout (do NOT fix here):** W2-02
  `action: str` → `Side` (FRAGILE, in `_PendingBracket.action`/`Order.action`); W1-11 double
  `get_position()` in admission→sizing; W4-09 `create_order` second unvalidated path
  (needs-owner-decision); SYN-05 `OrderConfig` + `market_execution` enum. The spot-and-log policy
  (D-13) routes any further finding to the 999.5 backlog.

### Reviewed Todos (not folded)
None — `gsd-sdk todo.match-phase 6` returned zero matches.

</deferred>

---

*Phase: 6-Order-Manager Decomposition*
*Context gathered: 2026-06-11*
