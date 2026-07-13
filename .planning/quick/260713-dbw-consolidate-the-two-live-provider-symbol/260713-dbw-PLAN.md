---
phase: quick-260713-dbw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/price_handler/providers/live_provider.py
  - itrader/price_handler/providers/replay_provider.py
  - itrader/trading_system/live_trading_system.py
  - tests/unit/price_handler/test_live_provider.py
  - tests/unit/price/test_replay_provider.py
autonomous: true
requirements:
  - QUICK-260713-dbw-consolidate-live-provider-symbol
user_setup: []

must_haves:
  truths:
    - "live_provider.py exposes exactly ONE public symbol: the LiveDataProvider @runtime_checkable Protocol (the concrete no-op base class is gone)."
    - "ReplayDataProvider no longer inherits any base; it defines the 7 optional streaming/wiring seams inline as no-ops and still satisfies the LiveDataProvider Protocol structurally."
    - "The two touched test modules import only LiveDataProvider from live_provider, keep every positive Protocol isinstance check, and drop all base-class-specific assertions — the whole suite for both files stays green."
    - "mypy --strict is clean on both edited providers and the OKX import-inertness posture of live_provider.py is preserved (no ccxt/sqlalchemy/asyncio imports)."
  artifacts:
    - itrader/price_handler/providers/live_provider.py
    - itrader/price_handler/providers/replay_provider.py
    - tests/unit/price_handler/test_live_provider.py
    - tests/unit/price/test_replay_provider.py
  key_links:
    - "ReplayDataProvider -> LiveDataProvider: isinstance(ReplayDataProvider(), LiveDataProvider) must stay True after the base is removed (real set_bar_sink + inlined optional seams)."
    - "itrader/venues/{bundle,assemble,lifecycle,okx_plugin,paper_plugin}.py annotate against LiveDataProvider — they must still import cleanly and stay inert."
---

<objective>
Consolidate the two live-provider symbols in `itrader/price_handler/providers/live_provider.py`
into one. Delete the concrete `BaseLiveDataProvider` no-op base class and keep only the
`LiveDataProvider` `@runtime_checkable` Protocol. Its sole production consumer,
`ReplayDataProvider`, stops inheriting the base and instead defines the 7 optional
streaming/wiring seams directly as no-ops. Update the two test modules that reference the base
to drop base-specific assertions while preserving the Protocol `isinstance` conformance checks.

Purpose: One structural symbol instead of two removes a class whose only value was inheritable
no-op defaults for a single non-streaming consumer — a leaner surface with identical behavior.
Output: A single-symbol `live_provider.py`, a self-contained `ReplayDataProvider`, and two
updated test modules — all `mypy --strict` clean, inertness preserved, oracle untouched.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

@itrader/price_handler/providers/live_provider.py
@itrader/price_handler/providers/replay_provider.py
@tests/unit/price_handler/test_live_provider.py
@tests/unit/price/test_replay_provider.py
</context>

<!-- planner-discipline-allow: BaseLiveDataProvider -->

<tasks>

<task type="auto">
  <name>Task 1: Trim live_provider.py to the single LiveDataProvider Protocol</name>
  <files>itrader/price_handler/providers/live_provider.py</files>
  <action>
Delete the entire concrete `BaseLiveDataProvider` class (its class statement, its docstring,
and all 7 no-op method bodies — the whole trailing block). Keep the `LiveDataProvider`
`@runtime_checkable` `Protocol` intact including its `set_bar_sink` REQUIRED method and the 7
OPTIONAL streaming-seam method stubs (`...` bodies unchanged).

Rewrite the MODULE docstring so it describes ONE symbol: state that this module gives every
live data provider one structural shape (the Protocol) so `VenueLifecycle` can wire any
provider unconditionally, and that the Protocol declares the REQUIRED `set_bar_sink` plus the
OPTIONAL streaming/wiring seams. Remove every sentence that describes a concrete no-op base
class supplying inherited defaults, and reframe the "a provider that does not stream" note to
say such a provider (e.g. the offline replay provider) implements those optional seams directly
as no-ops rather than inheriting them. Keep the D-10 uniformity-rule paragraph, the
`OkxDataProvider`-conforms-structurally paragraph, the inertness paragraph, and the 4-space /
`mypy --strict` note.

Rewrite the `LiveDataProvider` CLASS docstring's "Surface split" so the "Optional streaming/wiring
seams" bullet no longer says a non-streaming provider inherits the removed base's defaults — say
instead it implements them directly as no-ops; and remove the parenthetical claiming
`set_bar_sink` "is NOT defaulted on" the removed base (reframe to: a no-op default would silently
drop every bar, so each concrete provider MUST implement it).

Do NOT change any import line: `TYPE_CHECKING, Any, Protocol, runtime_checkable` and the
`TYPE_CHECKING`-guarded `Callable` are all still consumed by the Protocol method signatures
(`set_bar_sink(sink: Callable[[Any], None])`, `set_global_queue(global_queue: Any)`, etc.), so
they must remain to stay both mypy-clean and inertness-clean. Match the existing 4-SPACE
indentation exactly (never tabs).
  </action>
  <verify>
    <automated>test -z "$(grep -n 'class BaseLiveDataProvider' itrader/price_handler/providers/live_provider.py)" && poetry run python -c "import itrader.price_handler.providers.live_provider as m; assert hasattr(m,'LiveDataProvider'); assert not hasattr(m,'BaseLiveDataProvider'); print('single-symbol OK')"</automated>
  </verify>
  <done>`live_provider.py` exports only `LiveDataProvider`; the concrete base class definition is gone; the module still imports (no ccxt/sqlalchemy/asyncio) and the module + Protocol docstrings describe a single symbol.</done>
</task>

<task type="auto">
  <name>Task 2: Make ReplayDataProvider standalone with inlined no-op seams</name>
  <files>itrader/price_handler/providers/replay_provider.py, itrader/trading_system/live_trading_system.py</files>
  <action>
In `replay_provider.py`: remove the `from itrader.price_handler.providers.live_provider import
BaseLiveDataProvider` import line, and change the class declaration so `ReplayDataProvider` no
longer inherits it (bare `class ReplayDataProvider:`).

Add the 7 optional streaming/wiring seams as inline no-op methods on `ReplayDataProvider`, each a
one-line body, with the SAME signatures the Protocol declares:
`set_global_queue(self, global_queue: Any) -> None` returns `None`;
`set_halt_signal(self, halt_signal: Callable[[str], None]) -> None` returns `None`;
`set_stream_state_listener(self, on_down: Callable[[str], None], on_up: Callable[[str], None]) -> None`
returns `None`; `subscribe(self, symbol: str) -> None` returns `None`;
`unsubscribe(self, symbol: str) -> None` returns `None`;
`spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None` returns `None`;
`is_streaming_healthy(self) -> bool` returns `True`. Give each a short docstring explaining it is
a deliberate no-op because offline replay does not stream (a non-streaming provider is trivially
healthy). Place them in a clearly-commented section (e.g. after the existing feed-seam methods)
so the real `set_bar_sink`, `replay_bar`, `iter_closed_bars`, and `fetch_ohlcv_backfill` stay
untouched.

Fix the imports for the new signatures: change `from typing import Callable` to
`from typing import Any, Callable` (Any is now needed for `set_global_queue`; Callable is already
used by the existing sink type and the new seam signatures). Do not remove the existing
`collections.abc.Iterator` / `decimal.Decimal` imports.

Rewrite the `ReplayDataProvider` CLASS docstring "Uniform provider surface" paragraph: it no
longer inherits a base — say it implements the optional streaming/wiring seams DIRECTLY as
no-ops so `VenueLifecycle` can call them unconditionally, and it keeps its real `set_bar_sink`,
so `isinstance(ReplayDataProvider(...), LiveDataProvider)` is True.

In `live_trading_system.py`: this file has NO code dependency on the removed base — only the
inline comment near the uniform provider->feed wiring (the block that calls
`provider.set_global_queue` / `set_halt_signal` / `set_stream_state_listener`) mentions the
removed base class supplying the no-op defaults. Reword that comment so it says the replay
provider no-ops the streaming seams via its own inline no-op methods (drop the reference to the
removed base). Comment text only — no logic change. Match this file's 4-SPACE indentation. Match
`replay_provider.py`'s 4-SPACE indentation (never tabs).
  </action>
  <verify>
    <automated>poetry run python -c "from itrader.price_handler.providers.replay_provider import ReplayDataProvider; from itrader.price_handler.providers.live_provider import LiveDataProvider; p=ReplayDataProvider(); assert isinstance(p, LiveDataProvider); assert p.set_global_queue(object()) is None; assert p.is_streaming_healthy() is True; assert p.subscribe('BTCUSD') is None; assert p.spawn_warmup('BTCUSD','1d',10) is None; print('standalone replay OK')"</automated>
  </verify>
  <done>`ReplayDataProvider` inherits nothing, defines all 7 optional seams inline as no-ops, still satisfies the `LiveDataProvider` Protocol, and `live_trading_system.py`'s wiring comment no longer references the removed base.</done>
</task>

<task type="auto">
  <name>Task 3: Update the two test modules to the single symbol</name>
  <files>tests/unit/price_handler/test_live_provider.py, tests/unit/price/test_replay_provider.py</files>
  <action>
In `tests/unit/price_handler/test_live_provider.py`: change the import so it pulls ONLY
`LiveDataProvider` from `live_provider` (drop the removed base from the import list). Delete the
`_BaseBackedProvider` helper class (it subclassed the removed base) and delete the six
base-specific tests: the one asserting the bare-base streaming seams return None, the one
asserting bare-base `is_streaming_healthy` is True, the one asserting the base does not define
`set_bar_sink`, the base-subclass-conforms test, the bare-base-is-not-yet-a-provider negative
test, and the set_bar_sink-override-is-honoured test. KEEP the `_FakeFullProvider` test double and
its `test_protocol_is_runtime_checkable_fake_conforms` Protocol `isinstance` check, KEEP
`test_okx_data_provider_conforms_structurally`, and KEEP
`test_live_provider_module_imports_nothing_heavy` (the inertness guard). Trim the MODULE docstring
so its numbered list no longer describes the removed base's no-op defaults; keep the Protocol
`@runtime_checkable` structural-conformance point and the inertness point.

In `tests/unit/price/test_replay_provider.py`: change the import so it pulls ONLY
`LiveDataProvider` from `live_provider` (drop the removed base). In
`test_replay_provider_is_a_uniform_live_data_provider`, remove the `isinstance(provider,
BaseLiveDataProvider)` assertion and KEEP the `isinstance(provider, LiveDataProvider)` assertion.
In `test_replay_provider_inherited_streaming_seams_are_noops`, keep every no-op assertion but
update the name/comment to say the seams are the provider's own inline no-ops (they are no longer
inherited) — the assertions themselves are unchanged.

Both test dirs are package-less (no `__init__.py`) and 4-SPACE indented — match exactly, do not
add markers.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/price_handler/test_live_provider.py tests/unit/price/test_replay_provider.py -v</automated>
  </verify>
  <done>Both test modules import only `LiveDataProvider`, contain no reference to the removed base class, keep every positive Protocol `isinstance` check, and the full run of both files is green.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none introduced) | Pure internal type/no-op refactor — deletes a concrete class, inlines its no-op methods into one consumer, updates tests. No new external input, no I/O, no package installs, no trust boundary crossed. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-dbw-01 | Tampering | live_provider.py inertness posture | low | mitigate | Preserve the no-ccxt/sqlalchemy/asyncio import posture; `test_live_provider_module_imports_nothing_heavy` is kept and re-run in Task 3. |
| T-dbw-02 | Denial of Service | ReplayDataProvider Protocol conformance | low | mitigate | Removing the base could silently drop `LiveDataProvider` conformance and break `VenueLifecycle` wiring; Task 2 verify asserts `isinstance(..., LiveDataProvider)` and the venues-import smoke in `<verification>` proves nothing broke. |
</threat_model>

<verification>
Run after all three tasks complete:

- `poetry run mypy --strict itrader/price_handler/providers/live_provider.py itrader/price_handler/providers/replay_provider.py` — strict-clean on both edited providers.
- `poetry run pytest tests/unit/price_handler/test_live_provider.py tests/unit/price/test_replay_provider.py -v` — both modules green.
- Symbol fully removed (comment lines filtered so a lingering doc reference cannot false-green):
  `! grep -rn 'BaseLiveDataProvider' itrader/ tests/ | grep -v '^\s*#'` — returns no matches (the base is gone from code and comments).
- Venues import smoke (the Protocol consumers) — proves the wiring surface still imports and stays inert:
  `poetry run python -c "import itrader.venues.bundle, itrader.venues.assemble, itrader.venues.lifecycle, itrader.venues.okx_plugin, itrader.venues.paper_plugin; import itrader.price_handler.providers.live_provider, itrader.price_handler.providers.replay_provider; print('venues + providers import OK')"`
- Optional broader safety net: `poetry run mypy itrader` stays clean (config-driven strict + per-module overrides).
</verification>

<success_criteria>
- `live_provider.py` exposes exactly one public symbol (`LiveDataProvider`); the concrete no-op base class is deleted; module + Protocol docstrings describe a single symbol.
- `ReplayDataProvider` inherits nothing, defines all 7 optional seams inline as no-ops, and still satisfies `LiveDataProvider` structurally.
- The `live_trading_system.py` wiring comment no longer references the removed base (comment-only edit).
- Both test modules import only `LiveDataProvider`, keep every positive Protocol `isinstance` check, drop all base-specific assertions, and run green.
- `mypy --strict` clean on both providers; inertness guard green; venues + providers import smoke passes.
</success_criteria>

<output>
Create `.planning/quick/260713-dbw-consolidate-the-two-live-provider-symbol/260713-dbw-SUMMARY.md` when done.
</output>
