---
phase: 09-multi-entity-robustness-metrics-edges
fixed_at: 2026-06-10T00:00:00Z
review_path: .planning/phases/09-multi-entity-robustness-metrics-edges/09-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 10
skipped: 0
status: all_fixed
---

# Phase 09: Code Review Fix Report

**Fixed at:** 2026-06-10T00:00:00Z
**Source review:** .planning/phases/09-multi-entity-robustness-metrics-edges/09-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 10 (6 warning + 4 info; `fix_scope = all`)
- Fixed: 10
- Skipped: 0

All fixes respected the golden-master discipline: no frozen golden CSV/JSON fixture
was edited. Every fix landed in Python test/harness logic or in VERIFY-note / docstring
documentation only. The full `tests/e2e` suite (58 tests) is green after every code
(non-doc) change, run under the project's strict `filterwarnings=["error"]` /
`--strict-markers` config.

## Fixed Issues

### WR-01: Determinism test omits the three new Phase-9 frames

**Files modified:** `tests/e2e/robust/test_determinism.py`
**Commit:** 9c56162
**Applied fix:** Extended `test_double_run_identical` to assert frame-equality on all
six `_assemble` artifacts — added `orders` (a[3]), `cash_ops` (a[4]), and
`portfolios_frame` (a[5]) to the existing trades/equity/summary asserts. These three
frames are the MULTI-03/MULTI-04 vehicles most exposed to non-determinism
(registration-order winner/loser split, dict iteration over portfolios).
**Verification (per guardrail 3):** Ran `poetry run pytest tests/e2e/robust/test_determinism.py -v`
— all nine leaves PASS, confirming all six frames are byte-identical across the two
in-process runs. No frame was non-deterministic, so the strengthened assertion is safe
and was retained (no revert needed).

### WR-02: No-tolerance summary diff silently locks `profit_factor: Infinity`

**Files modified:** `tests/e2e/multi/two_tickers/scenario.py`,
`tests/e2e/multi/two_strategies/scenario.py`,
`tests/e2e/multi/fanout_portfolios/scenario.py`,
`tests/e2e/multi/contended_cash/scenario.py`, `tests/e2e/conftest.py`
**Commit:** d0293a9
**Applied fix:** Implemented option (b) per guardrail 2 (NOT option a, which would
break the four frozen, passing `summary.json` goldens). Added an explicit
"`profit_factor: Infinity` is INTENDED" carve-out paragraph to the VERIFY note of each
of the four all-win multi-entity leaves, explaining the gross-losses-zero all-WIN
branch, that the ROBUST-03 finite guard is opt-in and deliberately not applied to these
leaves, and that a re-verifier should keep `Infinity` frozen. Also documented the
carve-out at the harness `_diff_summary` docstring. The frozen goldens and the opt-in
`test_metrics_finite.py` guard were left untouched.
**Verification:** Docstring/comment-only changes; `python -m ast.parse` clean on all
five files; full `tests/e2e` suite green.

### WR-03: `union_window` slippage attribution frozen but undocumented

**Files modified:** `tests/e2e/robust/union_window/scenario.py`
**Commit:** 8d12b9c
**Applied fix:** Added a slippage-attribution paragraph to the union_window VERIFY note
(mirroring two_tickers). Hand-derived both rows against the single `spec.ticker`
(AAVEUSD) close series: BTC fills precede AAVE's first bar so `decision_close` returns
0.0 via the `position <= 0` guard and slippage equals the raw BTC fill prices
(33502.87 / 32729.12); AAVE entry 271.03 − 270.75 = 0.28, exit 254.06 − 256.32 = −2.26.
Cross-checked each digit against the frozen `golden/trades.csv` — all match.
**Verification:** Docstring-only change; `ast.parse` clean; e2e suite green.

### WR-04: `_make_on_tick` resolves operator actions against `portfolio_ids[0]` only

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 6a649ce
**Applied fix:** Chose the lower-risk arm (per guardrail 5): added an explicit guard at
the `_build_and_run` call site —
`assert not spec.actions or len(spec.portfolios) == 1` — that converts the latent
single-portfolio assumption into an enforced precondition with a clear message, plus a
comment documenting that a future multi-portfolio operator leaf must thread a per-action
target portfolio before the guard can be relaxed. No rearchitecting of the shared
harness; none of the nine Phase-9 leaves carry `actions`, so the assert is inert today.
**Verification:** `ast.parse` clean; full `tests/e2e` suite (58 tests) green — the new
assert does not fire for any existing leaf.

### WR-05: `attach_slippage` membership guard can raise mid-`apply`

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 6a649ce
**Applied fix:** Chose the documentation arm (per guardrail 5): documented the
single-close-series invariant at the `_assemble` slippage call site — "every traded
ticker's fill dates MUST be a subset of `spec.ticker`'s date grid, or fall entirely
before its first bar" — and spelled out that a future differing-end-date leaf would
raise `ValueError` and must attribute slippage per-ticker before being authored.
**Verification:** Comment-only change; `ast.parse` clean; e2e suite green.

### WR-06: Commission merge key not provably unique

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 6a649ce
**Applied fix:** Chose the documentation arm (per guardrail 5): documented the
merge-key uniqueness precondition at the commission merge site — the
`(pair, entry_date, exit_date, side)` key must be unique per leaf; two same-ticker
same-bar round-trips (e.g. scale-in/scale-out) are unsupported and would trip the
intended `validate="one_to_one"` hard failure, and such a leaf must add a per-position
discriminator before being authored.
**Verification:** Comment-only change; `ast.parse` clean; e2e suite green.

### IN-01: summary.json and portfolios.csv disagree on float precision

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 8b4b6b8
**Applied fix:** Added a note to the `_freeze` docstring (no code change, as the
reviewer specified): `summary.json` is raw `json.dump` (full float repr) while CSV
goldens use 10-dp `FLOAT_FORMAT`, so cross-artifact equality is by-value-not-by-string.
**Verification:** Docstring-only; `ast.parse` clean; e2e suite green.

### IN-02: `_assemble` builds per-portfolio snapshot every run, then discards it

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 8b4b6b8
**Applied fix:** Per the reviewer's "Optional — low priority" framing and the guardrail
to avoid rearchitecting the shared harness with two drift-prone code paths, added a
tracking note documenting that the always-on per-portfolio rebuild is deliberate and
that the single-portfolio short-circuit is intentionally deferred. No logic change.
**Verification:** Comment-only; `ast.parse` clean; e2e suite green.

### IN-03: `_assert_finite.py` type hint claims `dict[str, float]` but is not enforced

**Files modified:** `tests/e2e/robust/_assert_finite.py`
**Commit:** 53de207
**Applied fix:** Added a defensive `isinstance(v, (int, float))` guard that fails with a
readable message if a metric drifts to a non-numeric type (e.g. `None`/`Decimal`),
instead of a raw `TypeError` from `math.isfinite`. Added a docstring SCOPE line noting
the helper is only valid on the ROBUST-03 degenerate-metrics leaves and that an all-WIN
leaf's legitimate `profit_factor=inf` must not be passed here.
**Verification:** `ast.parse` clean; the three opt-in finite leaves
(`test_metrics_finite.py`) still PASS in the full `tests/e2e` run — the new guard does
not reject the existing finite float metrics.

### IN-04: Heavy reliance on decision-tag prose comments citing other modules by line

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 8b4b6b8
**Applied fix:** Per the reviewer's "Optional" framing and the project convention that
the existing `D-NN`/`WR-NN` decision-tag comments are load-bearing, added a single
"Cross-module citation caveat" section to the module docstring rather than sweeping
every `file:line` citation (which would risk corrupting load-bearing comments). The note
states the named SYMBOL is the durable anchor and the trailing `:line` is an approximate
hint, and that new cross-module citations should lead with the symbol.
**Verification:** Docstring-only; `ast.parse` clean; e2e suite green.

## Skipped Issues

None — all ten in-scope findings were fixed.

---

_Fixed: 2026-06-10T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
