---
phase: 260718-fxm
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/events_handler/events/portfolio.py
  - itrader/events_handler/events/screener.py
  - itrader/events_handler/events/strategy.py
  - itrader/events_handler/events/feed.py
  - itrader/events_handler/events/market.py
  - itrader/events_handler/events/universe.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/events/ack.py
  - itrader/events_handler/events/__init__.py
  - itrader/universe/universe_handler.py
  - tests/unit/events/test_universe_update_event.py
  - tests/unit/universe/test_universe_poll.py
  - tests/unit/universe/test_retry_policy_cr01.py
  - tests/unit/universe/test_universe_warmup_consumers.py
  - tests/integration/conftest.py
  - itrader/core/enums/event.py
  - CLAUDE.md
autonomous: true
requirements:
  - QUICK-260718-fxm

must_haves:
  truths:
    - "Every moved class is importable from the barrel `from itrader.events_handler.events import X` (PortfolioUpdateEvent, ScreenerEvent, UniverseUpdateEvent, StrategyCommandEvent, BarsLoaded, BarsLoadFailed, OrderAckEvent) plus all unchanged names."
    - "Each event class lives in its correct domain file per the target layout; ack.py no longer exists."
    - "The 6 direct-submodule importers of UniverseUpdateEvent resolve against events.universe (not events.market)."
    - "SMA_MACD oracle stays byte-exact (134 / 46189.87730727451) — pure relocation, zero behavior change."
    - "mypy --strict clean and the full pytest suite green."
  artifacts:
    - itrader/events_handler/events/portfolio.py
    - itrader/events_handler/events/screener.py
    - itrader/events_handler/events/strategy.py
    - itrader/events_handler/events/feed.py
    - itrader/events_handler/events/__init__.py
  key_links:
    - "Barrel __init__.py re-exports every moved class from its new module (primary blast-radius shield for barrel importers)."
    - "6 direct-submodule importers repointed market -> universe for UniverseUpdateEvent."
---

<objective>
Pure-relocation refactor of the `itrader/events_handler/events/` package: move each event class into its
correct trading-domain file so the package layout matches the domain map. NO behavior change — only file
locations, imports, and the barrel change. The `EventType` enum members do NOT move.

Purpose: Cohesive one-class-per-domain layout; remove the misfiled `ack.py`; keep the barrel as the stable
public surface so downstream importers are unaffected.
Output: 4 new domain files, a trimmed `market.py`/`universe.py`, `OrderAckEvent` merged into `order.py`,
`ack.py` deleted, an updated barrel, 6 repointed importers, a corrected enum comment, and a synced CLAUDE.md line.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@itrader/events_handler/events/__init__.py
@itrader/events_handler/events/market.py
@itrader/events_handler/events/universe.py
@itrader/events_handler/events/ack.py
@itrader/events_handler/events/order.py
@itrader/core/enums/event.py

Target end-state layout (per file, after this plan):
- base.py     -> Event (UNCHANGED)
- market.py   -> TimeEvent, BarEvent  (ONLY these two remain)
- portfolio.py (NEW) -> PortfolioUpdateEvent
- screener.py  (NEW) -> ScreenerEvent
- universe.py -> UniverseUpdateEvent, UniversePollEvent  (StrategyCommandEvent/BarsLoaded/BarsLoadFailed LEAVE; UniverseUpdateEvent ARRIVES)
- signal.py   -> SignalEvent (UNCHANGED)
- strategy.py  (NEW) -> StrategyCommandEvent (+ its 9 factory classmethods)
- order.py    -> OrderEvent, OrderAckEvent  (OrderAckEvent merged in)
- fill.py     -> FillEvent (UNCHANGED; keeps its `from .order import OrderEvent`)
- feed.py      (NEW) -> BarsLoaded, BarsLoadFailed
- error.py    -> ErrorEvent, PortfolioErrorEvent (UNCHANGED)
- control.py  -> StreamStateEvent, ConnectorFatalEvent, ConfigUpdateEvent (UNCHANGED)

CRITICAL invariants for the whole plan:
- The events package is 4-SPACE indented. Every new file and every edit uses 4 spaces. Do NOT introduce tabs (CLAUDE.md indentation hazard).
- Preserve each moved class VERBATIM — class docstring (carries load-bearing D-NN decision tags), all factory classmethods, `__str__`/`__repr__`, field defaults, and the `type: ClassVar[EventType] = EventType.X` pin. Only the file location changes; do not reword, reformat, or reorder class bodies.
- Each new/edited module carries EXACTLY the imports its remaining classes need (add what arrives, trim what leaves).
- MODULE-level docstrings (the file header triple-quote) MAY be updated to accurately describe each file's new contents. CLASS docstrings stay verbatim.
- Security note: this is a pure code-relocation refactor — no new dependencies, no external input, no I/O, no trust-boundary change — so no STRIDE register applies.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Relocate event classes, merge OrderAckEvent, delete ack.py, update barrel + repoint the 6 importers (one atomic green commit)</name>
  <files>itrader/events_handler/events/portfolio.py, itrader/events_handler/events/screener.py, itrader/events_handler/events/strategy.py, itrader/events_handler/events/feed.py, itrader/events_handler/events/market.py, itrader/events_handler/events/universe.py, itrader/events_handler/events/order.py, itrader/events_handler/events/ack.py, itrader/events_handler/events/__init__.py, itrader/universe/universe_handler.py, tests/unit/events/test_universe_update_event.py, tests/unit/universe/test_universe_poll.py, tests/unit/universe/test_retry_policy_cr01.py, tests/unit/universe/test_universe_warmup_consumers.py, tests/integration/conftest.py</files>
  <action>
This is one indivisible relocation: moving a class out of market.py breaks the 6 importers and the barrel until repointed/updated, so all of the sub-steps below land in the SAME commit to keep the tree green. Work in 4-space indentation throughout.

CREATE portfolio.py: move `PortfolioUpdateEvent` here VERBATIM from market.py. Imports it needs: `Any`, `ClassVar` from typing; `EventType` from `itrader.core.enums`; `Event` from `.base`. Write a short 4-space module docstring describing it (portfolio snapshot event, D-07).

CREATE screener.py: move `ScreenerEvent` here VERBATIM from market.py. Imports it needs: `ClassVar` from typing; `EventType` from `itrader.core.enums`; `Event` from `.base` (it has no `Any` field). Short module docstring (D-screener).

CREATE strategy.py: move `StrategyCommandEvent` AND all 9 of its factory classmethods (add/remove/enable/disable/reconfigure/subscribe_portfolio/unsubscribe_portfolio/add_ticker/remove_ticker) VERBATIM from universe.py — the full class docstring (D-08/D-09 verb-set text, the IN-02 and WR-04 warnings) stays byte-for-byte. Imports it needs: `datetime` from datetime; `Any`, `ClassVar` from typing; `EventType` from `itrader.core.enums`; `Event` from `.base`. Short module docstring (single control-plane command, D-08/D-09).

CREATE feed.py: move `BarsLoaded` and `BarsLoadFailed` here VERBATIM from universe.py (keep both class docstrings, incl. the T-05-27 secret-scrub note on BarsLoadFailed.reason). Imports it needs: `ClassVar` from typing; `Bar` from `itrader.core.bar` (BarsLoaded carries `tuple[Bar, ...]`); `EventType` from `itrader.core.enums`; `Event` from `.base`. Short module docstring (warmup bulk-transport events, D-03/D-04).

EDIT market.py: remove the moved `PortfolioUpdateEvent`, `ScreenerEvent`, and `UniverseUpdateEvent` class definitions. Only `TimeEvent` and `BarEvent` remain. Trim the now-unused `Any` from the typing import — change `from typing import Any, ClassVar` to `from typing import ClassVar` (the two remaining classes use no `Any`). Keep `from itrader.core.bar import Bar` (BarEvent uses it). Update the module docstring to describe only clock ticks + bars.

EDIT universe.py: remove the moved `StrategyCommandEvent`, `BarsLoaded`, and `BarsLoadFailed` class definitions; MOVE `UniverseUpdateEvent` in from market.py VERBATIM. After the change universe.py contains exactly `UniverseUpdateEvent` and `UniversePollEvent`. Trim imports to only what those two need: `ClassVar` from typing, `EventType` from `itrader.core.enums`, `Event` from `.base` — remove the now-unused `from datetime import datetime`, drop `Any` from the typing import, and remove `from itrader.core.bar import Bar`. Rewrite the module docstring to describe its new two-class contents (UniverseUpdateEvent + UniversePollEvent).

EDIT order.py: MERGE `OrderAckEvent` in from ack.py VERBATIM (the whole class incl. its docstring and the `new_order_ack` classmethod). order.py already imports every symbol OrderAckEvent needs — `OrderId`, `PortfolioId` (from `itrader.core.ids`), `Any`, `ClassVar` (from typing), `EventType`, and `Event` — so add NO new imports; confirm they are present rather than adding duplicates. Append `OrderAckEvent` after `OrderEvent` in the file. You may add one line to order.py's module docstring noting the venue-ack event (D-06/V17-02) is co-located here; keep OrderAckEvent's CLASS docstring verbatim.

DELETE ack.py entirely (its sole class moved into order.py).

UPDATE the barrel itrader/events_handler/events/__init__.py: keep re-exporting the exact same set of public names (do not add or drop any name), but source each from its new module and refresh the grouping comments. The new import grouping is: `.base` -> Event; `.market` -> TimeEvent, BarEvent; `.portfolio` -> PortfolioUpdateEvent; `.screener` -> ScreenerEvent; `.universe` -> UniverseUpdateEvent, UniversePollEvent; `.signal` -> SignalEvent; `.strategy` -> StrategyCommandEvent; `.order` -> OrderEvent, OrderAckEvent; `.fill` -> FillEvent; `.feed` -> BarsLoaded, BarsLoadFailed; `.error` -> ErrorEvent, PortfolioErrorEvent; `.control` -> StreamStateEvent, ConnectorFatalEvent, ConfigUpdateEvent; and `EventType` from `itrader.core.enums`. Ensure `__all__` still lists every one of these names (same names as before — this is the blast-radius shield for barrel importers).

REPOINT the 6 known direct-submodule importers of UniverseUpdateEvent from `itrader.events_handler.events.market` to `itrader.events_handler.events.universe`: itrader/universe/universe_handler.py:53, tests/unit/events/test_universe_update_event.py:30, tests/unit/universe/test_universe_poll.py:37, tests/unit/universe/test_retry_policy_cr01.py:28, tests/unit/universe/test_universe_warmup_consumers.py:31, tests/integration/conftest.py:301.

THEN grep the whole tree to prove no OTHER direct-submodule importer of any moved class was missed — run `grep -rn "events\.market import\|events\.ack import\|events\.universe import" itrader tests --include='*.py'` and inspect each hit: any reference to a MOVED class (UniverseUpdateEvent/PortfolioUpdateEvent/ScreenerEvent from .market; OrderAckEvent from .ack; StrategyCommandEvent/BarsLoaded/BarsLoadFailed from .universe) must be repointed to its new module. Note: `from .order import OrderEvent` in fill.py and `events.order import OrderEvent` in tests/unit/order/test_trailing_plumbing.py are CORRECT and must NOT change (OrderEvent stays in order.py). Do not assume the 6 known sites are exhaustive.
  </action>
  <verify>
    <automated>poetry run python -c "from itrader.events_handler.events import PortfolioUpdateEvent, ScreenerEvent, UniverseUpdateEvent, StrategyCommandEvent, BarsLoaded, BarsLoadFailed, OrderAckEvent, OrderEvent, TimeEvent, BarEvent, UniversePollEvent; print('ok')"</automated>
    <automated>test ! -f itrader/events_handler/events/ack.py && echo "ack.py removed"</automated>
    <automated>test -f itrader/events_handler/events/portfolio.py && test -f itrader/events_handler/events/screener.py && test -f itrader/events_handler/events/strategy.py && test -f itrader/events_handler/events/feed.py && echo "4 new files exist"</automated>
    <automated>[ "$(grep -rn 'events\.market import' itrader tests --include='*.py' | grep -c 'UniverseUpdateEvent\|PortfolioUpdateEvent\|ScreenerEvent')" -eq 0 ] && echo "no stale market-submodule imports of moved classes"</automated>
    <automated>poetry run mypy --strict itrader</automated>
    <automated>poetry run pytest tests/integration/test_backtest_oracle.py -v</automated>
    <automated>poetry run pytest tests</automated>
  </verify>
  <done>All 4 new files exist; ack.py is gone; every moved class imports cleanly from the barrel; no stale submodule imports of moved classes remain; mypy --strict is clean; the full pytest suite is green; and the SMA_MACD oracle is byte-exact (134 / 46189.87730727451).</done>
</task>

<task type="auto">
  <name>Task 2: Fix the stale STRATEGY_COMMAND inline comment in core/enums/event.py</name>
  <files>itrader/core/enums/event.py</files>
  <action>
This file is 4-SPACE indented. Do NOT move or rename any enum member — only fix ONE inline comment. On the `STRATEGY_COMMAND = "STRATEGY_COMMAND"` line, replace the trailing comment `# D-09: add/remove-ticker command` (now stale — it now carries the full verb set) with a comment describing the complete D-09 verb set: add/remove/enable/disable/reconfigure/subscribe_portfolio/unsubscribe_portfolio/add_ticker/remove_ticker. Keep the `# D-09:` prefix and the comment on the same line as the member. Change nothing else in the file.
  </action>
  <verify>
    <automated>[ "$(grep -c 'add/remove-ticker command' itrader/core/enums/event.py)" -eq 0 ] && echo "stale comment gone"</automated>
    <automated>grep -q 'reconfigure' itrader/core/enums/event.py && grep -q 'subscribe_portfolio' itrader/core/enums/event.py && echo "full verb set present"</automated>
    <automated>poetry run python -c "from itrader.core.enums import EventType; assert EventType.STRATEGY_COMMAND.value == 'STRATEGY_COMMAND'; print('ok')"</automated>
  </verify>
  <done>The STRATEGY_COMMAND comment lists the full D-09 verb set; the stale "add/remove-ticker command" text is gone; the enum member value is unchanged and imports cleanly.</done>
</task>

<task type="auto">
  <name>Task 3: Sync the CLAUDE.md events-split architecture line to the new file set</name>
  <files>CLAUDE.md</files>
  <action>
In CLAUDE.md there is exactly one architecture line (in the "Event-driven core" section) that enumerates the events split; it currently reads the parenthetical `(split by domain: base.py, market.py, signal.py, order.py, ack.py, fill.py, error.py, universe.py)`. Update ONLY that parenthetical file list to reflect the new file set and the removal of ack.py — the new set is: base.py, market.py, portfolio.py, screener.py, universe.py, signal.py, strategy.py, order.py, fill.py, feed.py, error.py, control.py. Do NOT alter the rest of that sentence or any other CLAUDE.md content. (Grep confirmed only one such reference exists; if the grep in verify surfaces more, update each.)
  </action>
  <verify>
    <automated>grep -q 'portfolio.py' CLAUDE.md && grep -q 'screener.py' CLAUDE.md && grep -q 'strategy.py' CLAUDE.md && grep -q 'feed.py' CLAUDE.md && echo "new files listed"</automated>
    <automated>[ "$(grep -c 'ack.py' CLAUDE.md)" -eq 0 ] && echo "ack.py reference removed"</automated>
  </verify>
  <done>The events-split line in CLAUDE.md lists the new file set (incl. portfolio.py, screener.py, strategy.py, feed.py, control.py) and no longer references ack.py.</done>
</task>

</tasks>

<verification>
Full plan-level gate (must all pass after Task 1; Tasks 2-3 are non-functional and independently green):
- Barrel import smoke: `poetry run python -c "from itrader.events_handler.events import PortfolioUpdateEvent, ScreenerEvent, UniverseUpdateEvent, StrategyCommandEvent, BarsLoaded, BarsLoadFailed, OrderAckEvent, OrderEvent; print('ok')"`
- `poetry run mypy --strict itrader` clean.
- `poetry run pytest tests` green (use this, NOT `make test` — `make test` can abort on missing .env and its ITRADER_DISABLE_LOGS breaks caplog tests).
- SMA_MACD oracle byte-exact: `poetry run pytest tests/integration/test_backtest_oracle.py -v` (134 / 46189.87730727451 — pure relocation, must not change).
- `itrader/events_handler/events/ack.py` no longer exists.
</verification>

<success_criteria>
- Every event class lives in its correct domain file per the target layout; ack.py deleted.
- Each moved class is preserved verbatim (docstrings, factories, `__str__`/`__repr__`, field defaults, ClassVar type pin) with only its file location changed.
- The barrel re-exports the exact same public name set from the new modules; barrel importers are unaffected.
- The 6 (and any grep-surfaced) direct-submodule importers of UniverseUpdateEvent are repointed market -> universe.
- The STRATEGY_COMMAND enum comment and the CLAUDE.md events-split line reflect the new reality.
- mypy --strict clean, full suite green, oracle byte-exact.
</success_criteria>

<output>
Create `.planning/quick/260718-fxm-reorganize-events-package-by-domain-file/260718-fxm-SUMMARY.md` when done.
</output>
