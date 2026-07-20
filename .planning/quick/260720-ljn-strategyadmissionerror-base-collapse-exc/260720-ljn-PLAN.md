---
phase: quick-260720-ljn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/core/exceptions/strategy.py
  - itrader/core/exceptions/__init__.py
  - itrader/strategy_handler/registry/catalog.py
  - itrader/strategy_handler/registry/config_codec.py
  - itrader/strategy_handler/registry/rehydrate.py
  - itrader/strategy_handler/lifecycle/manager.py
  - tests/unit/core/test_exceptions.py
  - tests/unit/strategy/test_rehydrate.py
  - .planning/quick/260720-ljn-strategyadmissionerror-base-collapse-exc/SUMMARY.md
autonomous: true
requirements: [CR-01-followup]
must_haves:
  truths:
    - "Every strategy-payload rejection type is catchable through one ancestor, StrategyAdmissionError"
    - "All four hand-listed catch sites name two types, not four-to-six, and cannot drift apart again"
    - "A rehydrate infrastructure fault still propagates out of rehydrate_strategies instead of quarantining a row (D-19 separability preserved)"
    - "UnknownParamError and MissingParamError keep their structured ValidationError fields; StrategyConfigError and UnknownStrategyTypeError keep plain-message construction"
    - "The backtest oracle stays byte-exact at 134 / 46189.87730727451"
  artifacts:
    - "itrader/core/exceptions/strategy.py — StrategyAdmissionError defined and exported"
    - "tests/unit/core/test_exceptions.py — MRO/isinstance pinning for all four reparented types"
    - "tests/unit/strategy/test_rehydrate.py — D-19 separability regression test"
  key_links:
    - "manager.py zone-1 tier-1 tuple -> StrategyAdmissionError (the CR-01 drift surface)"
    - "rehydrate.py _QUARANTINABLE -> StrategyAdmissionError + UnwarmableTimeframeError"
    - "core/exceptions/__init__.py barrel -> StrategyAdmissionError (the import path both tab-files use)"
---

<objective>
Introduce a single `StrategyAdmissionError` ancestor for the strategy-domain rejection
exceptions and collapse the four divergent, hand-listed catch tuples onto it.

Purpose: those four tuples share no ancestor today, so "catch a bad strategy payload"
means hand-listing unrelated names — and the sets have ALREADY diverged. That drift is the
root cause of CR-01 (fixed in quick task 260720-km2), where a bare `ValueError` escaped a
never-raise boundary into a live HALT vector. This removes the drift surface itself.

Output: one new base class, four reparented exceptions, four collapsed catch sites, an
updated D-19 doctrine comment, and tests pinning both the new hierarchy and the D-19
separability property the collapse now makes load-bearing.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

@itrader/core/exceptions/base.py
@itrader/core/exceptions/strategy.py
@itrader/strategy_handler/registry/rehydrate.py
@itrader/strategy_handler/lifecycle/manager.py
@.planning/quick/260720-km2-fix-cr-01-add-verb-never-raise-zone-guar/260720-km2-SUMMARY.md
</context>

<ground_truth>
Verified against the live tree during planning. Where this section and any prose disagree,
CODE WINS — re-measure before acting.

**Indentation (measured, bytes — never normalize):**
- 4-SPACE: `core/exceptions/strategy.py`, `core/exceptions/__init__.py`,
  `tests/unit/core/test_exceptions.py`, `tests/unit/strategy/test_rehydrate.py`,
  `tests/unit/strategy/test_strategy_command_verbs.py`
- TAB: `registry/catalog.py`, `registry/config_codec.py`, `registry/rehydrate.py`,
  `lifecycle/manager.py`

**MRO probe re-run at plan time against the real class shapes — confirmed:**
`UnknownParamError -> ValidationError -> StrategyAdmissionError -> ITraderError -> ValueError -> Exception`.
Both construction forms work; `.names` / `.name` / `.field` survive; plain-message
construction works for the two `ValueError`-rooted types; and
`issubclass(RehydrateInfrastructureError, StrategyAdmissionError)` is False.

**Import-usage census (drives the prune in Task 2 — do NOT blind-delete):**
- `manager.py:57` (`MissingParamError`, `UnknownParamError`) — used ONLY in the catch
  tuples. Becomes unused; remove the whole line.
- `manager.py:74` (`UnknownStrategyTypeError`) — used ONLY in the catch tuples. Remove.
- `manager.py:76` (`StrategyConfigError`, inside the `config_codec` import block) — used
  ONLY in the catch tuples. Remove that ONE name; `decode_strategy_config` and
  `encode_strategy_config` are used 9 times and MUST stay.
- `manager.py:384` mentions `UnknownParamError` in a PROSE COMMENT that stays. A
  file-wide count of that identifier will therefore NOT reach zero — do not write a gate
  that expects it to.
- `rehydrate.py:73` + `:84` (`MissingParamError`, `UnknownParamError`,
  `UnknownStrategyTypeError`) — used ONLY in `_QUARANTINABLE`. Remove.
- `rehydrate.py:87` (`StrategyConfigError`) — **STAYS**. It is not only caught, it is
  RAISED at `rehydrate.py:195` (`_resolve_portfolio_id` on a malformed portfolio id).
  Deleting this import breaks the module.
- `registry/__init__.py` re-exports both registry exceptions — unchanged, no edit needed.
- `strategy_handler/base.py` raises the two param errors — unchanged, no edit needed.

**Equivalence argument for the `_QUARANTINABLE` collapse (why it is not a widening):**
the try block at `rehydrate.py:322-366` wraps `build_strategy`, `_resolve_portfolio_id`,
and `required_base_depth`. `StrategyAdmissionError` gains exactly the four named types and
nothing else, so the caught set is unchanged. `add_strategy`'s duplicate-name **bare**
`ValueError` (D-02, documented at `rehydrate.py:291-293` as deliberately NOT quarantined)
is raised OUTSIDE this try block AND is not a `StrategyAdmissionError` — it stays
un-quarantined on both counts.
</ground_truth>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Define StrategyAdmissionError and reparent the two param errors</name>
  <files>itrader/core/exceptions/strategy.py, itrader/core/exceptions/__init__.py</files>
  <behavior>
    - `StrategyAdmissionError("plain message")` constructs and `str()`s to that message
    - `isinstance(UnknownParamError(["a"]), StrategyAdmissionError)` is True
    - `isinstance(UnknownParamError(["a"]), ITraderError)` is True
    - `isinstance(UnknownParamError(["a"]), ValueError)` is True
    - `UnknownParamError(["a","b"]).names == ["a","b"]` and `.field == "strategy_params"`
    - `MissingParamError("x").name == "x"` and `.field == "x"`
    - same four isinstance results hold for `MissingParamError`
  </behavior>
  <action>
    Both files are 4-SPACE indented — match them exactly.

    In `itrader/core/exceptions/strategy.py`:

    1. Widen the import to bring in `ITraderError` alongside `ValidationError` from `.base`.

    2. Add `StrategyAdmissionError(ITraderError, ValueError)` ABOVE the two existing
       classes, with a body of only a docstring. The docstring states: a strategy payload
       — an external `STRATEGY_COMMAND` or a stored registry row — was REFUSED at
       admission. Then explain, in the decision-anchored style of the surrounding modules,
       WHY the two bases are what they are, because both are load-bearing and a future
       reader will otherwise "simplify" one away:
         - `ITraderError` joins the house hierarchy, consistent with `PortfolioError` /
           `OrderError` / `DataError`.
         - `ValueError` preserves every pre-existing catch site AND keeps plain-message
           construction working (`ITraderError` is a bare `Exception` subclass). This is
           precisely why the alternative — rooting everything at the house
           `ValidationError` — is impossible: `StrategyConfigError` is raised roughly 25
           times with a plain message string, and `ValidationError.__init__` takes
           `(field, value=None, message=None)`.
       Cite CR-01 as the motivating defect: before this base existed, catching "a bad
       strategy payload" meant hand-listing unrelated names across four sites, those sets
       drifted, and one drifted tuple let a bare `ValueError` escape a never-raise
       boundary into a live HALT vector.

    3. Reparent both existing classes to `(ValidationError, StrategyAdmissionError)`.
       Change NOTHING else about them — the `__init__` bodies, the `super().__init__`
       calls, the stored `.names` / `.name` attributes, and their docstrings stay as they
       are apart from any base-class mention.

    4. Rewrite the module docstring. It currently describes only the two param errors and
       closes with a sentence about both subclassing the house `ValidationError`. It must
       now lead with `StrategyAdmissionError` as the shared admission-refusal ancestor,
       keep the existing D-06 / D-07 bullets verbatim in substance, and replace the
       closing sentence so it states that the two param errors carry BOTH the structured
       ValidationError fields and the shared admission ancestor. Keep the existing
       "RESEARCH §Don't Hand-Roll — never a bare raise ValueError" reference.

    In `itrader/core/exceptions/__init__.py`: add `StrategyAdmissionError` to BOTH the
    `from .strategy import (...)` block and the `__all__` list, in the "Strategy
    exceptions" group, listed FIRST (base before subclasses, matching how the portfolio
    and order groups already lead with their base).
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run python -c "
from itrader.core.exceptions import StrategyAdmissionError, UnknownParamError, MissingParamError, ITraderError, ValidationError
u = UnknownParamError(['a','b']); m = MissingParamError('x')
for e in (u, m):
    assert isinstance(e, StrategyAdmissionError) and isinstance(e, ITraderError) and isinstance(e, ValueError) and isinstance(e, ValidationError), e
assert u.names == ['a','b'] and u.field == 'strategy_params'
assert m.name == 'x' and m.field == 'x'
assert str(StrategyAdmissionError('plain msg')) == 'plain msg'
print('OK')
"</automated>
  </verify>
  <done>The probe prints OK; `strategy.py` and `__init__.py` remain 4-space indented; the module docstring documents the new base and its two-base rationale.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Reparent the registry exceptions and collapse all four catch sites</name>
  <files>itrader/strategy_handler/registry/catalog.py, itrader/strategy_handler/registry/config_codec.py, itrader/strategy_handler/registry/rehydrate.py, itrader/strategy_handler/lifecycle/manager.py</files>
  <behavior>
    - `isinstance(StrategyConfigError('msg'), StrategyAdmissionError)` and still a `ValueError`
    - `isinstance(UnknownStrategyTypeError('msg'), StrategyAdmissionError)` and still a `ValueError`
    - both still construct from a plain message string with an unchanged `str()`
    - `len(rehydrate._QUARANTINABLE) == 2`
    - `issubclass(RehydrateInfrastructureError, StrategyAdmissionError)` is False
  </behavior>
  <action>
    All four files are TAB indented — match them exactly; a space-indented line breaks the
    file.

    Import path for the new base in all four files: `from itrader.core.exceptions import
    StrategyAdmissionError` (the barrel — the same path `manager.py:57` and
    `rehydrate.py:73` already use).

    1. `registry/catalog.py` — change `UnknownStrategyTypeError`'s base from `ValueError`
       to `StrategyAdmissionError` and add the import. Its docstring and its single raise
       site at line 73 are UNCHANGED. Append one sentence to the class docstring noting it
       is still a `ValueError` through the base, so pre-existing catches are unaffected.

    2. `registry/config_codec.py` — same reparent for `StrategyConfigError`, same added
       import, same appended sentence. All ~25 plain-message raise sites are UNCHANGED —
       do not touch a single one.

    3. `registry/rehydrate.py`:
       - Collapse `_QUARANTINABLE` (currently lines 105-112) to exactly two members:
         `StrategyAdmissionError` and `UnwarmableTimeframeError`. Keep per-member trailing
         comments in the existing style: the base covers unknown type, undeserializable
         blob, and both directions of param drift; `UnwarmableTimeframeError` stays a
         SEPARATE explicit member because it is a FEED exception and a
         payload-x-environment interaction (the same config is valid on the backtest feed,
         which has no `base_timeframe`) — a bad ROW, quarantined not raised (F-1 / WR-01).
       - REWRITE the doctrine comment above it (lines 100-104). It currently reads as a
         prohibition on catching a base class, which is exactly what this change now does,
         so leaving it would read as a contradiction and invite a revert. The rewrite must
         PRESERVE the original's actual point and state it as a live constraint on the new
         base: the property that matters is that the catch stays NARROW, so a genuine
         infrastructure fault (a store or driver error raised mid-loop) is NOT swallowed
         and does not silently quarantine every strategy in turn — reporting a data problem
         while hiding an outage. Say explicitly that `StrategyAdmissionError` preserves
         this because `RehydrateInfrastructureError` roots at `RuntimeError` and is NOT a
         subclass of it, that this is now LOAD-BEARING rather than incidental, and that it
         is pinned by a regression test. Do not widen this tuple toward a bare `except`;
         the two D-19 arms must stay separable.
       - Prune imports per the census in `<ground_truth>`: drop line 73 entirely, drop
         `UnknownStrategyTypeError` from the catalog import at line 84 — and KEEP
         `StrategyConfigError` at line 87, which is RAISED at line 195. Verify each name's
         remaining usage before deleting rather than trusting this list.

    4. `lifecycle/manager.py` — collapse all three catch tuples to
       `except (StrategyAdmissionError, ValueError) as exc:`:
       - `~396-400` — the CR-01 zone-1 TIER-1 arm from quick task 260720-km2.
         ONLY THE TUPLE MEMBERS CHANGE. The tier-1 comment, the `logger.warning` call and
         its message string, the `return`, the entire tier-2 `except Exception` arm with
         its four-point comment, and all zone-2 code stay BYTE-IDENTICAL. Do not
         restructure the two-tier guard.
       - `~802-806` — reconfigure TRIAL.
       - `~862-866` — reconfigure APPLY. Note this site previously omitted
         `UnknownStrategyTypeError` (defensibly — apply resolves no class); folding it in
         via the base is harmless because apply cannot raise it.
       `ValueError` MUST REMAIN a member at all three sites: a third-party strategy's
       `validate()` override can still raise a bare `ValueError` and can never be brought
       into our hierarchy. Preserve each site's existing log body and message form exactly.
       Where a site's comment enumerates the caught types by name, update it to describe
       the base plus the bare-`ValueError` residue — keep the P8 declared-fields-only
       rationale and the CR-01 / D-19 anchors intact.
       - Then prune imports per the census: remove line 57 entirely, remove line 74, and
         remove ONLY `StrategyConfigError` from the `config_codec` import block at line 76.
         Add the `StrategyAdmissionError` import in correct alphabetical position within
         the `itrader.core.exceptions` import group. Leave the prose comment at line 384
         alone. Re-check each name's usage before deleting.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run python -c "
from itrader.core.exceptions import StrategyAdmissionError
from itrader.strategy_handler.registry.catalog import UnknownStrategyTypeError
from itrader.strategy_handler.registry.config_codec import StrategyConfigError
from itrader.strategy_handler.registry import rehydrate
for cls in (UnknownStrategyTypeError, StrategyConfigError):
    e = cls('plain msg')
    assert isinstance(e, StrategyAdmissionError) and isinstance(e, ValueError), cls
    assert str(e) == 'plain msg', cls
assert len(rehydrate._QUARANTINABLE) == 2, rehydrate._QUARANTINABLE
assert StrategyAdmissionError in rehydrate._QUARANTINABLE
assert not issubclass(rehydrate.RehydrateInfrastructureError, StrategyAdmissionError)
import itrader.strategy_handler.lifecycle.manager as mgr
print('OK')
" &amp;&amp; PYTHONPATH="$PWD" poetry run python -c "
import pathlib
for p in ['itrader/strategy_handler/registry/catalog.py','itrader/strategy_handler/registry/config_codec.py','itrader/strategy_handler/registry/rehydrate.py','itrader/strategy_handler/lifecycle/manager.py']:
    body = [l for l in pathlib.Path(p).read_text().splitlines() if l.startswith(' ') and l.strip()]
    assert not body, (p, body[:3])
print('TABS OK')
"</automated>
  </verify>
  <done>Both probes pass; the km2 zone-1/zone-2 two-tier structure is untouched apart from tier-1's tuple members; no tab file contains a space-indented line; no unused exception import remains.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Pin the hierarchy and D-19 separability with tests, then run all gates</name>
  <files>tests/unit/core/test_exceptions.py, tests/unit/strategy/test_rehydrate.py, .planning/quick/260720-ljn-strategyadmissionerror-base-collapse-exc/SUMMARY.md</files>
  <behavior>
    - all four reparented types are a StrategyAdmissionError, an ITraderError and a ValueError
    - UnknownParamError / MissingParamError additionally remain a ValidationError and keep
      `.names` / `.name` / `.field`
    - StrategyConfigError and UnknownStrategyTypeError construct from a plain message
    - the exact MRO chain of UnknownParamError is pinned
    - a RehydrateInfrastructureError raised MID-LOOP propagates out of rehydrate_strategies
      and is NOT quarantined, while a sibling admission-refusal row IS quarantined in the
      same run
  </behavior>
  <action>
    Both test files are 4-SPACE indented. Project gotcha (CLAUDE.md): `filterwarnings =
    ["error"]` and `--strict-markers` — any unexpected warning fails the suite.

    In `tests/unit/core/test_exceptions.py`, add a test group for the new hierarchy:
    - a parametrized isinstance test over all four reparented types asserting each is a
      `StrategyAdmissionError`, an `ITraderError` and a `ValueError`;
    - structured-field retention for `UnknownParamError` (`.names`, `.field`) and
      `MissingParamError` (`.name`, `.field`), each also still a `ValidationError`;
    - plain-message construction for `StrategyConfigError` and `UnknownStrategyTypeError`,
      asserting `str(exc)` is the message passed in — this is the property that makes the
      ~25 existing raise sites safe;
    - an explicit MRO-order assertion for `UnknownParamError` pinning
      `[UnknownParamError, ValidationError, StrategyAdmissionError, ITraderError, ValueError, ...]`.
      Comment WHY the order is pinned: `ValidationError.__init__` must win the lookup or
      the structured-field constructor breaks.

    In `tests/unit/strategy/test_rehydrate.py`, add the D-19 separability regression — the
    load-bearing one. Follow the fixtures and fake-store conventions already in that file
    (it already imports `RehydrateInfrastructureError` and drives rehydrate with fakes at
    ~line 53 / ~613; reuse them rather than inventing a parallel harness). Two assertions:
    - STRUCTURAL: `issubclass(RehydrateInfrastructureError, StrategyAdmissionError)` is
      False, with a comment stating the narrow base is what keeps the two D-19 arms
      separable.
    - BEHAVIORAL: seed two rows — one whose construction raises a
      `RehydrateInfrastructureError` from inside the per-row try block (a catalog class
      whose `init` raises it is the simplest injection point, mirroring the `_BoomStrategy`
      pattern in `tests/unit/strategy/test_strategy_command_verbs.py`), and one that fails
      with an admission refusal. Assert with `pytest.raises(RehydrateInfrastructureError)`
      that the infrastructure fault PROPAGATES out of `rehydrate_strategies` rather than
      being quarantined, and — in a second run containing only the admission-refusal row —
      that the row IS quarantined (returned in the quarantine list, alert emitted). Do not
      collapse these into one run: the point is that the two arms behave differently.

    Then create the milestone-close audit marker at
    `.planning/quick/260720-ljn-strategyadmissionerror-base-collapse-exc/SUMMARY.md`
    (the plain filename — the pre-audit scanner looks for `SUMMARY.md`, not the
    slug-prefixed one, and flags the task `[missing]` without it). Content: a two-line
    pointer to `260720-ljn-SUMMARY.md` plus the one-line task description.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/core/test_exceptions.py tests/unit/strategy -q &amp;&amp; PYTHONPATH="$PWD" poetry run pytest tests/unit/price_handler -q &amp;&amp; PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_strategy_registry_restart.py -q &amp;&amp; poetry run mypy &amp;&amp; test -f .planning/quick/260720-ljn-strategyadmissionerror-base-collapse-exc/SUMMARY.md</automated>
  </verify>
  <done>
    `tests/unit/strategy` is green at 337 + the new tests; price_handler green; the oracle
    is byte-exact (`trade_count 134`, `final_equity 46189.87730727451`); `poetry run mypy`
    reports no issues across 273 source files; the three CR-01 regression tests from
    260720-km2 pass UNCHANGED; the marker file exists.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| external -> `LiveTradingSystem.add_event` (D-10) | Untrusted `STRATEGY_COMMAND` payloads reach `_add_strategy_verb`'s zone-1 guard |
| stored registry row -> `rehydrate_strategies` | Persisted blobs are replayed into live objects at boot |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-ljn-01 | Denial of Service | `manager.py` zone-1 tier-1 tuple | high | mitigate | Collapsing to the base removes the drift surface that let a bare `ValueError` escape into the HALT-latch chain (CR-01); `ValueError` is retained so third-party `validate()` raises stay caught, and km2's tier-2 `except Exception` backstop is left byte-identical |
| T-ljn-02 | Denial of Service | `rehydrate.py` `_QUARANTINABLE` | high | mitigate | Base is NARROW — `RehydrateInfrastructureError` roots at `RuntimeError`, so a store/driver outage still propagates instead of silently quarantining the whole roster; pinned by an explicit regression test (Task 3) |
| T-ljn-03 | Information Disclosure | reject/quarantine log + alert bodies | medium | mitigate | Every log and alert body is preserved byte-identically, so the P8 declared-fields-only rule (error KIND only, never payload values) is not weakened by the refactor |
| T-ljn-04 | Tampering | dependency surface | low | accept | No package installs — pure in-repo refactor, no new dependency |
</threat_model>

<verification>
- `PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy -q` — was 337 passed, must be 337 + new
- `PYTHONPATH="$PWD" poetry run pytest tests/unit/core/test_exceptions.py -q`
- `PYTHONPATH="$PWD" poetry run pytest tests/unit/price_handler -q`
- `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -q` — MUST stay byte-exact: `trade_count 134`, `final_equity 46189.87730727451`
- `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_strategy_registry_restart.py -q` — the other `RehydrateInfrastructureError` consumer
- `poetry run mypy` — clean (was: no issues in 273 source files). If mypy objects to the
  two-hierarchy multiple inheritance, resolve it properly; do NOT add a blanket ignore.
- NEVER use `make test` (it exports `ITRADER_DISABLE_LOGS=true`, which false-greens log assertions).
</verification>

<success_criteria>
- `StrategyAdmissionError(ITraderError, ValueError)` exists in `core/exceptions/strategy.py` and is exported from the barrel
- All four rejection types are catchable through it; both construction forms still work
- All four catch sites name two types; `_QUARANTINABLE` has exactly two members
- The `rehydrate.py` doctrine comment explains the narrow-base reasoning instead of prohibiting it
- D-19 separability is pinned by an explicit test
- km2's zone-1/zone-2 structure, tier-2 arm, and all zone-2 code are byte-identical
- Nothing in `<out_of_scope>` was touched
- Oracle byte-exact; mypy clean; no unused imports left behind
</success_criteria>

<out_of_scope>
Decided deliberately — do NOT do any of this:
- `UnwarmableTimeframeError` does NOT join the base. It is a FEED exception, a
  payload-x-environment interaction, its three catch sites each emit a bespoke more-informative
  operator message, and `required_base_depth` is called AFTER `build_strategy` (outside zone 1)
  so it would unify nothing. It stays a separate explicit `_QUARANTINABLE` member.
- Do NOT convert the bare raises at `strategy_handler/base.py:292` or
  `strategies/SMA_MACD_strategy.py:42`. No tuple simplification results (third-party
  `validate()` keeps `ValueError` alive regardless) and it widens the diff into the oracle's
  reference strategy.
- Do NOT touch the zone-1/zone-2 two-tier guard STRUCTURE from 260720-km2 — only tier-1's
  tuple members change.
- No other 10.1-REVIEW.md finding (WR-01..WR-06, IN-01..IN-06).
</out_of_scope>

<output>
Create `.planning/quick/260720-ljn-strategyadmissionerror-base-collapse-exc/260720-ljn-SUMMARY.md` when done
</output>
</content>
</invoke>
