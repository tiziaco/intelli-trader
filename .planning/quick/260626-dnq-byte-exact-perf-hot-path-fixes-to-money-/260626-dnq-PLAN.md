---
phase: quick-260626-dnq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/core/money.py
  - itrader/strategy_handler/base.py
autonomous: true
requirements: [PERF-HOTPATH-MONEY, PERF-HOTPATH-TODICT]
must_haves:
  truths:
    - "to_money(d) returns the same Decimal object for an already-Decimal input (no stringify/reparse)"
    - "to_money produces byte-identical results to the prior Decimal(str(x)) path for all input types"
    - "Strategy.to_dict() returns a per-call-isolated snapshot — mutating a returned nested container does not poison the shared cache"
    - "Strategy.to_dict() output is byte-identical to the pre-change deepcopy path (same keys, order, types, values)"
    - "SMA_MACD backtest oracle remains byte-exact after both fixes"
  artifacts:
    - path: "itrader/core/money.py"
      provides: "to_money Decimal fast-path (D-04 round-trip identity preserved)"
      contains: "type(x) is Decimal"
    - path: "itrader/strategy_handler/base.py"
      provides: "to_dict targeted-isolation copy replacing copy.deepcopy"
  key_links:
    - from: "itrader/core/money.py::to_money"
      to: "hot-path callers (bar.close, intent prices, SL/TP)"
      via: "fast-path early return for Decimal inputs"
    - from: "itrader/strategy_handler/base.py::to_dict"
      to: "self._to_dict_static_cache"
      via: "targeted isolating copy (per-call nested-container isolation)"
---

<objective>
Two surgical, byte-exact performance hot-path fixes ranked by the latest Scalene profile
(`perf/results/scalene-w1.json`, 28.16s run):

1. `to_money()` Decimal fast-path (~2.7% CPU) — skip stringify/reparse when the input is already a Decimal.
2. Replace `copy.deepcopy` in `Strategy.to_dict()` (~5% CPU) with a targeted isolating copy.

Purpose: Reduce W1 backtest CPU on the two profiler-ranked hot paths WITHOUT changing any output. The project is under golden-master / oracle discipline — byte-exact preservation is the non-negotiable verification bar.

Output: Two atomic commits, each independently oracle-verified, mypy-clean, with existing decision-anchor comments (D-04 / WR-01 / WR-02 / D-06) preserved and updated to reflect the change.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<critical_constraints>
- **Indentation (NEVER normalize):** `itrader/core/money.py` uses **4 spaces** (core/ module). `itrader/strategy_handler/base.py` uses **TABS** (handler module). A mixed-indentation diff breaks the file. Match each file exactly.
- **Money policy:** Decimal end-to-end. The fast-path is provably byte-exact ONLY because `Decimal(str(d)) == d` round-trips exactly for any Decimal `d`. Use `type(x) is Decimal` (identity), NOT `isinstance(x, Decimal)`, to stay conservative against Decimal subclasses whose `str()` round-trip could differ.
- **Test gate (project memory):** Do NOT use `make test` as the gate — it exports `ITRADER_DISABLE_LOGS=true` (breaks caplog tests) and aborts in worktrees on missing `.env`. Use `poetry run pytest tests ...` directly.
- **Worktree .venv shadowing (project memory):** the editable install can hide worktree edits from pytest/mypy. Prepend `PYTHONPATH="$PWD"` to every pytest/mypy invocation so the worktree source is imported, not the installed copy.
- **Byte-exact gate (project memory):** the SMA_MACD oracle is `tests/integration/test_backtest_oracle.py` (NOT `tests/golden`, which is artifacts / 0 tests).
</critical_constraints>

<interfaces>
<!-- Verified from the codebase — executor should use these directly, no exploration needed. -->

itrader/core/money.py (4-space indent), current line 59-66:
  def to_money(x: float | int | str | Decimal) -> Decimal:
      """...D-04 docstring..."""
      return Decimal(str(x))   # <- add fast-path guard ABOVE this line

itrader/strategy_handler/base.py (TAB indent):
  - line 1: `import copy`  (KEEP — copy.deepcopy is ALSO used at line 245 for default-value copying; only the line-679 usage changes)
  - line 668-682: to_dict() — `snapshot = copy.deepcopy(self._to_dict_static_cache)` is line 679
  - line 670-678: the WR-01 comment block explaining WHY per-call isolation is needed (caller mutating result["tickers"] must not poison the shared cache)
  - _json_safe (line 74-91) NORMALIZES the value domain: every snapshot value is None/str/int/float (immutable scalar) OR a list/dict whose contents are recursively json-safe. There are NO custom mutable leaf objects in the cached snapshot — everything non-scalar is a plain list/dict.

Byte-exact pin test (fix #2): tests/unit/strategy/test_to_dict_snapshot.py
  - test_snapshot_byte_identical asserts: two calls equal; AND mutating a returned TOP-LEVEL key (second["short_window"]=-999) does NOT poison the next call.
  - WR-01's stricter concern is a NESTED mutable (e.g. result["tickers"] list) — isolation must hold one+ level down too.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: to_money Decimal fast-path (money.py)</name>
  <files>itrader/core/money.py</files>
  <action>
In `to_money` (line ~59-66, 4-space indentation), add a fast-path guard as the FIRST statement of the function body, before the existing `return Decimal(str(x))`:

  if type(x) is Decimal:
      return x

Use `type(x) is Decimal` (identity check), NOT `isinstance` — this is deliberate and conservative: it returns the value unchanged ONLY for exact-Decimal inputs, avoiding any Decimal subclass whose `str()` round-trip might differ. Add a single one-line comment directly above the guard tying the fast-path to the round-trip identity, e.g.: `# Fast-path: Decimal(str(d)) == d round-trips exactly, so an already-Decimal input can be returned unchanged (D-04 preserved, ~2.7% W1 hot-path win).`

PRESERVE the existing D-04 docstring verbatim. Do NOT touch `quantize`, `ONE`, the scale tables, or `__all__`. Keep 4-space indentation.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit -k money -q && PYTHONPATH="$PWD" poetry run python -c "from decimal import Decimal; from itrader.core.money import to_money; d=Decimal('10.10'); assert to_money(d) is d; assert to_money('10.1')==Decimal('10.1'); assert to_money(10.1)==Decimal('10.1'); assert to_money(3)==Decimal('3'); print('OK')"</automated>
  </verify>
  <done>Fast-path guard present using `type(x) is Decimal`; an already-Decimal input is returned by identity (`is`); str/int/float inputs still produce the exact prior `Decimal(str(x))` value; D-04 docstring intact; money unit tests pass; mypy clean (verified in Task 3 shared gate).</done>
</task>

<task type="auto">
  <name>Task 2: replace copy.deepcopy in to_dict with targeted isolating copy (base.py)</name>
  <files>itrader/strategy_handler/base.py</files>
  <action>
STEP 1 — VERIFY the snapshot value domain BEFORE changing code (do not assume). Run:
  PYTHONPATH="$PWD" poetry run python -c "from decimal import Decimal; from itrader.core.sizing import FractionOfCash, TradingDirection; from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy; s=SMAMACDStrategy(timeframe='1d', tickers=['BTCUSDT'], sizing_policy=FractionOfCash(Decimal('0.95')), direction=TradingDirection.LONG_ONLY, allow_increase=False, short_window=50, long_window=100); snap=s._build_to_dict_snapshot(); [print(k, type(v).__name__, repr(v)) for k,v in snap.items()]"
Confirm from the output: every value is an immutable scalar (str/int/float/bool/None) OR a flat list/dict of scalars. This is GUARANTEED by `_json_safe` (line 74-91), which coerces all non-native leaves to repr-strings and only ever produces list/dict containers — there are no custom mutable leaf objects.

STEP 2 — Because the value domain is scalars + (possibly nested) plain list/dict, a recursive structural copy over ONLY list/dict (returning scalars unchanged) is provably (a) byte-exact — deepcopy of an immutable scalar returns an equal value anyway, and (b) fully isolated to ANY nesting depth, exactly matching deepcopy's per-call isolation for this value domain, without the memo dict / introspection / immutable-copying overhead deepcopy pays.

Implement: replace `snapshot = copy.deepcopy(self._to_dict_static_cache)` (line 679) with a call to a small module-level helper. Add the helper near `_json_safe` (TAB indentation), structurally: a function `_isolating_copy(val)` that returns `[_isolating_copy(x) for x in val]` when `type(val) is list`, `{k: _isolating_copy(v) for k, v in val.items()}` when `type(val) is dict`, and `val` unchanged otherwise (scalars are immutable — no copy needed). Then `snapshot = _isolating_copy(self._to_dict_static_cache)` (the top-level cache is a dict, so the dict branch copies the top level). Use `type(...) is list/dict` for speed and to match the conservative-identity style of Task 1.

  - NOTE: if STEP 1's output had shown all mutable containers at exactly ONE level deep, the inline one-level comprehension `{k: (list(v) if type(v) is list else dict(v) if type(v) is dict else v) for k, v in self._to_dict_static_cache.items()}` would also be sufficient and marginally faster. The recursive helper is preferred because it is robust to any nesting `_json_safe` could emit (e.g. a declared `dict[str, list[...]]`) with no correctness cliff. Choose the recursive helper unless STEP 1 proves the data flat AND you document the flatness guarantee in the comment.

STEP 3 — KEEP `import copy` at line 1 (still used by line 245 for default-value copying). Do NOT remove it. UPDATE the WR-01 comment block (line 670-678) to describe the deepcopy→targeted-isolating-copy change: state that the snapshot value domain is scalars + plain list/dict (normalized by `_json_safe`), so the recursive list/dict copy provides the same per-call nested-container isolation deepcopy gave (a caller mutating result["tickers"] cannot poison the cache) while staying byte-identical (same types/values), and that test_to_dict_snapshot still pins it. PRESERVE the surrounding D-06 / WR-02 comments unchanged. Keep TAB indentation throughout.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy/test_to_dict_snapshot.py -v && PYTHONPATH="$PWD" poetry run python -c "from decimal import Decimal; from itrader.core.sizing import FractionOfCash, TradingDirection; from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy; s=SMAMACDStrategy(timeframe='1d', tickers=['BTCUSDT'], sizing_policy=FractionOfCash(Decimal('0.95')), direction=TradingDirection.LONG_ONLY, allow_increase=False, short_window=50, long_window=100); d1=s.to_dict(); d1['tickers'].append('POISON'); d2=s.to_dict(); assert 'POISON' not in d2['tickers'], 'nested-container isolation broken'; assert list(d1.keys())==list(d2.keys()); print('isolation OK')"</automated>
  </verify>
  <done>`copy.deepcopy` at the to_dict serve site replaced by the targeted isolating copy; `import copy` retained (line 245 still uses it); nested-container mutation of a returned dict does NOT poison the cache; all 7 tests in test_to_dict_snapshot.py pass; output byte-identical (keys/order/types/values); WR-01 comment updated, WR-02/D-06 preserved; TAB indentation intact; mypy clean (Task 3 gate).</done>
</task>

<task type="auto">
  <name>Task 3: shared byte-exact oracle + mypy gate (both fixes)</name>
  <files>itrader/core/money.py, itrader/strategy_handler/base.py</files>
  <action>
This task runs NO new edits — it is the combined proof gate that BOTH fixes preserved byte-exact output and types. Run the SMA_MACD oracle (the project's authoritative byte-exact gate) and mypy --strict over the two changed modules. If either fails, return to Task 1/Task 2 and fix before committing. Both fixes are committed as separate atomic commits (Task 1 = money.py, Task 2 = base.py) only AFTER this gate is green.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py tests/unit/strategy/test_to_dict_snapshot.py -v && PYTHONPATH="$PWD" poetry run mypy itrader/core/money.py itrader/strategy_handler/base.py</automated>
  </verify>
  <done>`tests/integration/test_backtest_oracle.py` passes (SMA_MACD backtest byte-exact / oracle unchanged); `test_to_dict_snapshot.py` passes; `mypy` reports no errors on both modules; two atomic commits made (one per fix).</done>
</task>

</tasks>

<verification>
- Byte-exact gate: `tests/integration/test_backtest_oracle.py` green (SMA_MACD numbers unchanged).
- Fix #2 pin: `tests/unit/strategy/test_to_dict_snapshot.py` all 7 tests green, including the nested-container isolation probe.
- Fix #1 round-trip: `to_money` returns equal values for str/int/float and the identical object for Decimal.
- Type safety: `mypy --strict` clean on both modules.
- Indentation: `git diff` shows 4-space-only changes in money.py and TAB-only changes in base.py (no whitespace normalization).
</verification>

<success_criteria>
- Both hot-path fixes applied, each byte-exact and oracle-verified.
- `to_money` short-circuits already-Decimal inputs via `type(x) is Decimal` identity return.
- `Strategy.to_dict()` uses a targeted isolating copy (no `copy.deepcopy` at the serve site) with per-call nested-container isolation preserved.
- All decision-anchor comments (D-04, WR-01, WR-02, D-06) preserved/updated; `import copy` retained.
- mypy --strict clean; indentation hazard respected; two atomic commits.
</success_criteria>

<output>
Create `.planning/quick/260626-dnq-byte-exact-perf-hot-path-fixes-to-money-/260626-dnq-SUMMARY.md` when done.
</output>
