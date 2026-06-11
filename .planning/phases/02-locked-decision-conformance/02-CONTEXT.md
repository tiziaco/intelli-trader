# Phase 2: Locked-Decision Conformance - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the three bounded **locked-decision violations** surfaced by the v1.2 cleanup
review, **without changing results**. Behavior-preserving / oracle byte-exact (134 trades /
`final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green; determinism
double-run byte-identical.

In scope (locked by ROADMAP §Phase 2 success criteria, REQUIREMENTS DEC-01/02/03):
- **DEC-01 (W4-01):** `modify_order`/`cancel_order` public-API price/quantity params retyped
  from `Optional[float]` to **`Optional[Decimal]`** — no float-for-money at a domain
  boundary. Both the `OrderHandler` façade and the `OrderManager` layer.
- **DEC-02 (W2-10):** `_min/_max_order_size` carried as **`Decimal` end-to-end** in
  `SimulatedExchange` (drop the `float(...)` wraps). **NOTE: the cited "latent TypeError" is
  a misdiagnosis — see D-07 below.** The real defect is float-for-money inconsistency.
- **DEC-03 (W4-08 ≡ W1-06):** retire `uuid.uuid4()` in `_generate_correlation_id` — replace
  the second ID scheme with the single UUIDv7 `idgen` scheme.

Out of scope: any change that moves the oracle; the result-changing 999.5 backlog items
(SIG/COMP/IND/LIFE); `Order`-entity `.modify_order`/`.cancel_order` signatures (different
method, not a W4-01 target); the `order_manager.py` split (Phase 6); other cleanup-review
batches (Phases 3-5).

</domain>

<decisions>
## Implementation Decisions

### DEC-03 — Correlation-ID scheme (W4-08/W1-06)
- **D-01:** Use the **single UUIDv7 `idgen` scheme**, not a deterministic counter. Rationale:
  it is the most faithful reading of the locked "single UUIDv7 scheme via `idgen` — do not
  introduce a second ID scheme" decision (`uuid4()` IS the second scheme; `idgen` UUIDv7 is
  the one scheme). It is also **consistent** with the run path today — all 10
  `idgen.generate_*` entity-ID call sites already mint per-run-varying UUIDv7s and the oracle
  is byte-exact regardless, because correlation IDs are **oracle-dark** (they ride only on
  error/log events — `PortfolioErrorEvent` — never on `trades.csv`/`equity.csv`/`summary.json`,
  and are not in any compared fixture). The "(or a deterministic counter)" criterion clause is
  an escape hatch we are NOT taking. `FINAL-ORACLE.md:111` pre-documents this `uuid4()` as the
  sole `grep -rn 'uuid4'` hit to retire — removing it makes that DoD check fully clean.
- **D-02:** Type the correlation ID as **`uuid.UUID`, not a formatted string**, via a new
  `CorrelationId` NewType — consistent with the D-12 nine-alias pattern in `core/ids.py`
  (`OrderId`, `PortfolioId`, … each `NewType("…", uuid.UUID)`). Concretely:
  - Add `CorrelationId = NewType("CorrelationId", uuid.UUID)` to `core/ids.py` (10th alias).
  - Add `IDGenerator.generate_correlation_id(self) -> uuid.UUID` (mirrors the other methods,
    which return raw `uuid.UUID`).
  - `_generate_correlation_id` returns `CorrelationId(idgen.generate_correlation_id())`
    (exactly like `order.py`'s `OrderId(idgen.generate_order_id())`).
  - `PortfolioErrorEvent.correlation_id` retyped `str | None` → `CorrelationId | None`
    (`events/error.py`, 4-space module; update the field docstring).
  - The `ph_` prefix is **dropped** (it was a string-format artifact).
  - `import uuid` in `portfolio_handler.py` becomes dead → **remove** (touched-path cleanup,
    Phase-1 D-05 / `CLEANUP-STANDARD.md`).
  - Update `tests/unit/portfolio/test_portfolio_handler.py::test_correlation_id_generation`:
    swap the `.startswith("ph_")` assertions for a `uuid.UUID` isinstance + uniqueness check.
    (`test_error_flow.py` injects its own literal `"abc-123"` and does not call the generator;
    tests aren't mypy-checked — `files=["itrader"]` — so the literal is runtime-fine but may be
    tidied to a real UUID at the planner's discretion.)

### DEC-01 — Money-API signature shape (W4-01)
- **D-03:** Type the params **strictly `Optional[Decimal]`** (NOT a permissive
  `Decimal|float|int|str|None` union). Rationale: it is the literal requirement and the
  strongest "no float-for-money at a domain boundary" statement — it forces callers into the
  Decimal domain. The internal `to_money()` coercion at `order_manager.py:1135-1137` stays
  (defensive), but the boundary annotation forbids float. Update the NumPy-style docstrings
  (`new_price : float` → `Decimal`, etc.) in both `order_handler.py` and `order_manager.py`.
- **D-04:** **Update in-repo boundary callers** that pass floats to the retyped handler/manager
  API, keeping the boundary float-free in practice (not just in annotation):
  - `tests/unit/order/test_order_manager.py` — `new_price=28.0`, `new_quantity=2.0` calls on
    `harness.handler.modify_order(...)` → `Decimal(...)`.
  - `tests/e2e/conftest.py:269` — `modify_order(new_price=action.new_price, …)`: if the
    scenario `ModifyAction` carries floats, convert at the seam (or make the field Decimal).
  - **Leave alone:** `tests/unit/order/test_order.py:130,135` etc. — those call the **`Order`
    entity** `.modify_order` (a different method, already Decimal-capable, out of W4-01 scope).
- **D-05:** W4-01's "999.5-(d) coordinate" note: the modify/cancel surface is the same one
  LIFE-01 (TIF / `create_order` gating, deferred) will revisit. Keep this change **minimal**
  (annotations + docstrings + boundary callers) — do NOT pre-build for the deferred work.

### DEC-02 — `_min/_max_order_size` Decimal + the misdiagnosis (W2-10)
- **D-06:** Carry `_min/_max_order_size` as **`Decimal`** — drop the `float(...)` wraps at
  `simulated.py:99-100` (init) and `:605-606` (`update_config`). The comparisons at
  `:388,390` then run Decimal-vs-Decimal. **Mirror the change** in the E2E harness seam
  `tests/e2e/conftest.py:331-332` (which deliberately re-derives both fields with `float()` to
  mirror production — see its `:323` comment) and update that comment. DEC-02 is **localized to
  `simulated.py`**: the dual-layer `order_validator.py` has **no** min/max handling (verified).
- **D-07 (gap-discovery delta — owner-flagged):** W2-10 / DEC-02 / ROADMAP §Phase-2 SC-2 claim
  a *"latent `Decimal < float` TypeError on the below-minimum validation path."* This is
  **false**. In Python 3, Decimal-vs-float **comparison** operators (`< > <= >=`) work and
  return a bool — only **arithmetic** (`+ - * /`) raises `TypeError`, and there is **no
  arithmetic** on these fields anywhere (verified: the only uses are the `float()` wraps, the
  two comparisons, two f-string messages, and a status dict). Empirical proof: the frozen E2E
  leaf `tests/e2e/cash/release_refused` **already** drives `event.quantity > self._max_order_size`
  (Decimal > float) → `REFUSED` and is green. Also corrected: the golden run **does** route
  through `validate_order` (via `_admit_order` on every NEW order) — it is NOT bypassed; in-limit
  golden quantities simply never trip a reject branch, so there is "nothing to prove never
  routed through." **Action:** the fix is still required (the `float(Decimal)` wraps are
  float-for-money, violating the Decimal-end-to-end locked decision), but the planner must
  **reframe** DEC-02's rationale (float-for-money consistency, NOT a TypeError) and **log this
  as a bounded gap-discovery delta** per PROJECT.md ("gap discovery is bounded — logged,
  owner-flagged, never silently folded"). Correct the ROADMAP/REQUIREMENTS success-criterion
  wording accordingly.
- **D-08:** Add a **below-minimum unit test** driving `event.quantity < _min_order_size` →
  `REFUSED` (Decimal-vs-Decimal). This is the "regression test" decision, reframed as **branch
  coverage**: `release_refused` covers `> _max`, but the symmetric `< _min` branch is exercised
  by **no** leaf today. Cheap, closes the gap.

### Claude's Discretion
- Plan/wave decomposition (how to group the three independent fixes into plans/waves).
- Exact placement/naming of the new below-minimum unit test and the `CorrelationId` test edit.
- Exact wording/home of the gap-discovery delta entry (D-07) and the corrected SC-2 wording.
- Extent of touched-path import cleanup beyond the dead `import uuid` (per Phase-1 D-05).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §Phase 2 (lines ~110-122) — goal + 4 success criteria. **Also an edit
  target:** SC-2's "latent `Decimal < float` TypeError" wording must be corrected per D-07.
- `.planning/REQUIREMENTS.md` DEC-01 / DEC-02 / DEC-03 (lines ~41-48) — the three requirements
  with source-finding tags `[W4-01]` / `[W2-10]` / `[W4-08 / W1-06]`. DEC-02's "latent
  TypeError" wording is also an edit target per D-07.

### Source findings (cleanup-review rationale + adjudications)
- `.planning/codebase/V1.2-CLEANUP-REVIEW.md` — rows: **1** (W2-10, `simulated.py:99-100,
  388-391,605-606` `_min/_max_order_size` float), **3** (W4-01, `order_handler.py:121-122,148`
  + `order_manager.py:1087-1088,1136-1137` `Optional[float]`), **4** (W4-08≡W1-06,
  `portfolio_handler.py:87-88` `uuid4()`). §6 "Batch 2 — Locked-decision conformance"
  (lines ~183-186) is the batch summary; note the W2-10 ⚠ BEHAVIOR-SENSITIVE flag that D-07
  re-adjudicates.

### Locked decisions & conventions
- `CLAUDE.md` §"Determinism & money" / §"IDs & Determinism" — Decimal end-to-end; single
  UUIDv7 `idgen` scheme. The two locked decisions DEC-01/03 conform to.
- `.planning/codebase/CONVENTIONS.md` — tab/space hazard (handler modules tab; `core/`,
  `config/`, events package 4-space) + the dual-layer validator overlap (W4-04, justified by
  decision — relevant to D-06's "localized to `simulated.py`" finding).
- `.planning/codebase/CLEANUP-STANDARD.md` — touched-path opportunistic-cleanup standard
  governing the dead-`import uuid` removal (Phase-1 D-05 precedent).
- `tests/golden/FINAL-ORACLE.md` line ~111 — pre-documents the `uuid4()` correlation-id as the
  sole `grep -rn 'uuid4'` hit, "non-result-bearing"; DEC-03 retires it.

### Code targets (verified during scout)
- `itrader/order_handler/order_handler.py:121-122,148` — `modify_order`/`cancel_order` façade
  signatures + docstrings (DEC-01).
- `itrader/order_handler/order_manager.py:1087-1088,1135-1137` — manager signatures + the
  `to_money(...)` boundary coercion (DEC-01).
- `itrader/execution_handler/exchanges/simulated.py:99-100,388-391,460-461,605-606` — the
  `_min/_max_order_size` float wraps, comparisons, status dict, update_config (DEC-02).
- `itrader/portfolio_handler/portfolio_handler.py:9 (import uuid),86-88` — `_generate_correlation_id`
  (DEC-03); `idgen` already imported at `:29`.
- `itrader/core/ids.py:15-25` — the nine-NewType D-12 block (add `CorrelationId`).
- `itrader/outils/id_generator.py:6-50` — `IDGenerator` (add `generate_correlation_id`).
- `itrader/events_handler/events/error.py:38,51` — `PortfolioErrorEvent.correlation_id` field
  + docstring (DEC-03 retype).

### Test targets
- `tests/unit/portfolio/test_portfolio_handler.py:427-434` — `test_correlation_id_generation`
  (DEC-03: drop `ph_` assertions).
- `tests/unit/order/test_order_manager.py:144,156,184` — float `modify_order` callers (DEC-01).
- `tests/e2e/conftest.py:267-272,323,331-332` — modify caller + the `_min/_max_order_size`
  float mirror seam (DEC-01 + DEC-02).
- `tests/e2e/cash/release_refused/` — the existing `> _max` REFUSED leaf (DEC-02 evidence; keep
  green; the `< _min` symmetric test (D-08) is new).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`idgen` singleton** (`from itrader import idgen`) — already imported in
  `portfolio_handler.py:29`; DEC-03 reuses it (just add `generate_correlation_id`).
- **`to_money()`** (`core/money.py`) — already coerces at the modify/cancel manager boundary;
  DEC-01 is annotation-only at the call site (the runtime coercion stays).
- **`tests/e2e/cash/release_refused`** — a ready-made, golden-locked over-maximum-rejection
  scenario; proves the Decimal-vs-float comparison doesn't crash today and is the model for the
  new below-minimum test (D-08).

### Established Patterns
- **D-12 NewType IDs** (`core/ids.py`): every ID is `NewType("…", uuid.UUID)`, constructed at
  the mint site as `XId(idgen.generate_x_id())`. `CorrelationId` follows this exactly.
- **Indentation hazard:** `order_handler/`, `portfolio_handler/`, `execution_handler/` are
  **tab** modules; `core/ids.py`, `outils/`, and `events_handler/events/` are **4-space**.
  Match each file — a mixed-indent diff breaks a tab file.
- **Dual-layer validator (W4-04):** `order_validator.py` (domain) and `simulated.py` (exchange)
  validate independently by design. DEC-02 touches only the exchange layer; the domain layer
  has no min/max handling.

### Integration Points
- DEC-03 touches the error/log seam only (`PortfolioErrorEvent` → `full_event_handler.py:163`
  log dict → structlog renders `str(UUID)`); no golden output, no serialization concern.
- DEC-02's exchange `validate_order` runs on the golden path via `_admit_order` (on_order);
  the change must keep every in-limit golden order admitting identically (byte-exact).

</code_context>

<specifics>
## Specific Ideas

- DEC-03's "single scheme" framing won the day over the counter precisely because the codebase
  already accepts `idgen` UUIDv7 nondeterminism for every entity ID on the run path — a counter
  would impose a stricter determinism standard than the project applies anywhere else, for a
  non-result-bearing ID.
- The DEC-02 misdiagnosis (D-07) is the most important finding of this discussion: the planner
  should treat "fix the float-for-money" as the real objective and explicitly NOT write a test
  that "proves the TypeError is gone" (there was none) — the test asserts correct REFUSED
  behavior on the `< _min` branch.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (The deterministic-counter alternative for DEC-03,
the permissive money-input union for DEC-01, and any pre-building for the deferred LIFE-01
modify/cancel surface were each considered and explicitly rejected as out-of-intent, not
deferred work.)

</deferred>

---

*Phase: 2-Locked-Decision Conformance*
*Context gathered: 2026-06-11*
