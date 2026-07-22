---
phase: 11-multi-portfolio-live
plan: 02
subsystem: execution-handler
tags: [venue-correlation, client-order-id, okx, D-16, D-17, D-18, LR-19, MPORT-04]
requires:
  - itrader/execution_handler/exchanges/venue_correlation.py
  - itrader/execution_handler/exchanges/okx.py
provides:
  - "_orders_by_client_order_id / _client_order_id_by_venue_id — engine-vocabulary correlation maps"
  - "_extract_client_order_id — the documented single venue-vocabulary boundary on the fill read path"
  - "ValidationError guard on the venue-bound client order id that survives python -O"
affects:
  - tests/unit/execution/test_venue_correlation.py
  - tests/unit/execution/test_okx_exchange.py
  - tests/unit/execution/test_okx_fill_idempotency.py
tech-stack:
  added: []
  patterns:
    - "Venue-vocabulary boundary: exactly one function knows how a venue spells a wire field"
    - "Loud rejection over strippable assert (reconciliation_coordinator.py precedent, D-18)"
key-files:
  created: []
  modified:
    - itrader/execution_handler/exchanges/venue_correlation.py
    - itrader/execution_handler/exchanges/okx.py
    - tests/unit/execution/test_venue_correlation.py
    - tests/unit/execution/test_okx_exchange.py
    - tests/unit/execution/test_okx_fill_idempotency.py
decisions:
  - "Local variables and parameters still named `clordid` were left unrenamed — out of the plan's defined scope (the completion grep names only the two attributes) and renaming public parameters risks breaking keyword callers"
  - "Charset branch of the D-18 guard deliberately left untested — unreachable by construction; an always-passing assertion would be false coverage"
metrics:
  duration: ~20min
  completed: 2026-07-21
status: complete
---

# Phase 11 Plan 02: Attribution Boundary (Rename + Venue Seam + D-18 Guard) Summary

Renamed the two engine-side correlation maps off OKX's `clOrdId` field spelling, documented
`_extract_client_order_id` as the single venue-vocabulary boundary, and converted the strippable
`assert` guarding the venue-bound client order id into a typed `ValidationError` that survives
`python -O`.

## What Was Built

**Task 1 — engine identifiers renamed, venue seam documented (D-16 / LR-19 / MPORT-04)**

- `_orders_by_clOrdId` → `_orders_by_client_order_id` (8 sites)
- `_clordid_by_venue_id` → `_client_order_id_by_venue_id` (4 sites)
- 6 test-side accesses updated across `test_okx_exchange.py` (1) and `test_okx_fill_idempotency.py` (5)
- `_extract_client_order_id` docstring expanded to state explicitly that it is THE venue-vocabulary
  boundary, that a second venue with a different field name is a one-site change, and that the
  degenerate-shape `None` returns are the T-11-07 mitigation
- Docstring vocabulary split throughout both source files: engine prose says *client order id*;
  venue prose keeps `clOrdId` and names it as the venue's own field

**Task 2 — D-18 typed guard (T-11-06)**

- `assert clordid.isalnum() and len(clordid) <= 32, ...` → explicit `if not (...): raise ValidationError(...)`
- Message names the offending identifier, both constraints (ASCII alphanumeric, ≤32 — the venue's own
  limit), the actual observed length, and why refusal beats truncation
- `ValidationError` imported from `itrader.core.exceptions`
- Rendering untouched — byte-identical output for every valid input (WR-04 bijection intact)

## Wire Contract Preserved

`params["clOrdId"]` (submission) and the response readers `trade.get("clientOrderId")` /
`info.get("clOrdId")` / `info.get("clientOrderId")` are byte-untouched. `grep -c 'clOrdId'` on
`venue_correlation.py` returns 4 — deliberately non-zero.

## Plan drift found

**1. `register()` does not populate the client-order-id map.** The plan's `<behavior>` block says
"`release` still drops the client-order-id map entry (the R2 bound), proven by asserting the map is
empty after release." My first draft of that test called `register("OID-12", order, "it12")` alone and
failed with `KeyError: 'it12'`. Reading the code: `register()` writes `_orders_by_venue_id`,
`_venue_id_by_order_id` and `_client_order_id_by_venue_id`, but **only `register_pending` and `adopt`
write `_orders_by_client_order_id`**. The real submit sequence in `OkxExchange._submit_order` calls
`register_pending` *before* the RPC and `register` *after*. Fixed the test to mirror that real
sequence and documented the asymmetry in its docstring. No source defect — the code is correct; the
plan's one-line behavior description was incomplete.

**2. `mypy` reports 251 source files, not the 273 the executor brief claimed.** The brief's
"Baseline: Success, 273 source files" is wrong. Actual baseline and post-change are both
`Success: no issues found in 251 source files`. My changes added no files, so the discrepancy is
pre-existing brief drift, not caused by this plan.

**3. The `assert` the plan pins at `okx.py:540` is now at `:560`.** The plan said "re-locate by
symbol" and it was right to — my Task 1 and Task 2 edits shifted it. It is the same statement
(`assert result.order is not None` in `_handle_trade`) and was correctly left in place. Post-change
`grep -n 'assert ' itrader/execution_handler/exchanges/okx.py` returns only `:560`.

**4. The worktree `.venv` shadowing hazard bit this plan.** Bare `poetry run pytest` imported
`itrader` from the **main checkout**, not the worktree, so the rename appeared to have no effect
(`AttributeError` on the renamed attribute even though the worktree source was correct —
`poetry run python -c` confirmed the rename was live). Switching to `poetry run python -m pytest`
(which puts cwd on `sys.path`) resolved it. All test results in this summary are from
`python -m pytest`. Anyone re-verifying with bare `poetry run pytest` in a worktree will see
spurious failures.

## Criteria that were already green before any change (prove nothing about this work)

Per the plan's correction notice, recorded honestly rather than claimed as new coverage:

1. **Repo-wide `clOrdId` allowlist grep** — passed on unmodified code. `clOrdId` already appeared in
   exactly the three allowlisted files.
2. **Adjacency / lossless-bijection criterion** — already covered by the pre-existing
   `test_client_order_id_lossless_no_tail_bit_collision` (`test_okx_exchange.py:575`). I did **not**
   add a duplicate. It passes, but it passed before this plan too.
3. **The three `_extract_client_order_id` extraction tests I added pass pre-change.** They are
   characterization tests — they lock in existing behavior so the rename cannot silently alter what
   the seam reads off the wire. Only the two rename-dependent tests were genuine RED
   (`AttributeError` before the rename).
4. **The "consolidation" work was already done.** `_extract_client_order_id` already had exactly one
   caller and `grep -rn 'clientOrderId' itrader/` confirms there are no other trade-dict client-order
   reads anywhere in the repo. The real deliverable here was the docstring naming the seam — no
   refactor was invented to justify the task.

## Coverage deliberately not written

The **charset half** of the D-18 guard is unreachable by construction: `_CLORDID_ALPHABET`
(`okx.py:58`) is entirely alphanumeric and the `"it"` prefix is alphanumeric, so `clordid.isalnum()`
is always `True`. No charset-violation test was written — it could never fail and must never be
recorded as proof of coverage. The **length** branch is genuinely drivable and is tested:
`_make_order(order_id=(1 << 190) - 1)` goes through the `int` fallback and renders a 34-character
token (verified empirically before writing the test).

## Deviations from Plan

**1. [Rule 3 — blocking] `ValidationError` was not imported in `okx.py`**
- **Found during:** Task 2
- **Issue:** The raise referenced `ValidationError` with no import; would be a `NameError` at runtime.
- **Fix:** Added `from itrader.core.exceptions import ValidationError` to the import block.
- **Files modified:** `itrader/execution_handler/exchanges/okx.py`
- **Commit:** `2e6b4158`

**2. [Scope decision] `clordid` local variables and parameters left unrenamed**
- `register_pending(clordid, ...)`, `release_pending(clordid)` and local `clordid` bindings still use
  the case-folded venue spelling. The plan's completion grep defines scope as the two attributes
  only, and the artifacts table lists exactly two renames. Renaming public parameters would risk
  breaking keyword callers for no gain against the stated criteria. Flagged here rather than done
  silently — if the phase wants full `clordid` eradication, it is a follow-up.

## Verification Evidence

| Gate | Command | Result |
|---|---|---|
| Execution units | `poetry run python -m pytest tests/unit/execution -q` | 271 passed |
| Full suite | `poetry run python -m pytest tests -q` | **2606 passed, 6 skipped** |
| Type check | `poetry run mypy` | Success, 251 source files |
| Engine identifiers gone | `grep -rn '_orders_by_clOrdId\|_clordid_by_venue_id' itrader/ tests/ scripts/` | zero matches |
| Wire spelling preserved | `grep -c 'clOrdId' .../venue_correlation.py` | 4 |
| Wire submission untouched | `grep -c 'params\["clOrdId"\]' .../okx.py` | 1 |
| Allowlist scope | `grep -rln 'clOrdId' itrader/ \| grep -v <3 allowlisted>` | zero matches |
| Only narrowing assert left | `grep -n 'assert ' .../okx.py` | only `:560` |
| Guard under `python -O` | `poetry run python -O -m pytest tests/unit/execution/test_okx_exchange.py -q` | 26 passed |
| Import under `python -O` | `poetry run python -O -c "import ...okx"` | exit 0 |
| Tab discipline (source) | `git diff -U0 -- <each source> \| grep -cP '^\+    [^ ]'` | 0 for both |
| Oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed |
| OKX inertness | `pytest tests/integration/test_okx_inertness.py -q` | 4 passed |
| No dependency change | `git diff --stat <base> HEAD` | `pyproject.toml` / `poetry.lock` absent |

## Threat Mitigations Applied

- **T-11-06 (Tampering, high)** — mitigated. The `assert` is now a real `raise`; proven to hold under
  `python -O` by running the guard test on an optimized interpreter.
- **T-11-07 (Spoofing, medium)** — mitigated. Every degenerate trade shape returns `None`; covered by
  `test_extract_client_order_id_returns_none_for_every_degenerate_shape` (10 assertions across
  non-dict, missing-field, non-dict-`info`, and present-but-falsy inputs).
- **T-11-08 (Info disclosure, medium)** — held. No account or portfolio tag was encoded into the
  identifier; the rendering is byte-identical to before.
- **T-11-SC** — no packages installed; `pyproject.toml` and `poetry.lock` untouched.

## Known Stubs

None.

## Commits

| Commit | Type | Description |
|---|---|---|
| `375adf05` | test | RED — renamed-map + venue-seam tests |
| `687a7be6` | refactor | GREEN — rename + seam documentation (D-16/LR-19) |
| `c3ea8b92` | test | RED — D-18 typed-guard test |
| `2e6b4158` | fix | GREEN — assert → `ValidationError` raise (D-18) |

## Self-Check: PASSED

All 5 modified files verified present on disk; all 4 task commits verified in `git log`; working
tree clean after the SUMMARY commit. No shared orchestrator artifacts (STATE.md, ROADMAP.md) were
modified — confirmed by `git diff --stat` against the base, which lists only the 5 code/test files
plus this summary.
</content>
</invoke>
