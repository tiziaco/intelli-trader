---
phase: quick-260716-mov
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/config/universe.py          # NEW — UniverseConfig home
  - itrader/config/system.py            # remove UniverseConfig, keep Environment/LogLevel/SystemSettings
  - itrader/config/__init__.py          # barrel — import UniverseConfig from .universe
  - itrader/config/itrader_config.py    # repoint import
  - itrader/trading_system/config_router.py       # repoint import
  - itrader/trading_system/live_trading_system.py # repoint 2 local imports
autonomous: true
requirements: [QT-260716-mov]

must_haves:
  truths:
    - "UniverseConfig lives in itrader/config/universe.py (its own module, matching the config/ one-domain-per-file convention); it no longer exists in config/system.py."
    - "config/system.py still exports Environment, LogLevel, SystemSettings (unchanged); only UniverseConfig moved out."
    - "config.universe is still a UniverseConfig with poll_cadence_s=60.0 (gt=0.0) and remove_policy='orphan-and-track', validate_assignment=True, extra='forbid' — behavior byte-identical to before the move."
    - "No `from itrader.config.system import` line anywhere still names UniverseConfig; every consumer imports it from itrader.config.universe."
    - "import itrader stays inert (config/universe.py imports only pydantic/stdlib); OKX inertness gate green."
    - "Backtest oracle unchanged (134 / 46189.87730727451) — UniverseConfig is live-only, off the hot path."
  artifacts:
    - itrader/config/universe.py
    - itrader/config/system.py
    - itrader/config/__init__.py
  key_links:
    - "itrader/config/__init__.py re-exports UniverseConfig (from .universe) so `from itrader.config import UniverseConfig` still works — __all__ unchanged."
    - "ITraderConfig.universe field (itrader_config.py) is typed UniverseConfig, now imported from itrader.config.universe."
---

<objective>
Relocate `UniverseConfig` from `itrader/config/system.py` into its own `itrader/config/universe.py`,
matching the `config/` one-domain-per-file convention (exchange/order/portfolio/safety/stream/sql/log
each own a file). Pure mechanical move — zero behavior change. `UniverseConfig` is live dynamic-universe
config (poll cadence + remove policy), only ever landed in `system.py` as the Phase 9 ex-`MonitoringSettings`
demotion. After the move, `system.py` cleanly holds only system-domain symbols: `Environment`, `LogLevel`,
`SystemSettings`.

CONVENTIONS: config/ = 4-SPACE indentation (new universe.py + edited config files). The trading_system
files use tabs for code, but every edit here is a column-0 `import` line, so no indentation hazard —
just don't reflow surrounding code.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@itrader/config/system.py
@itrader/config/__init__.py
@itrader/config/itrader_config.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Move UniverseConfig into config/universe.py and repoint every import</name>
  <files>itrader/config/universe.py, itrader/config/system.py, itrader/config/__init__.py, itrader/config/itrader_config.py, itrader/trading_system/config_router.py, itrader/trading_system/live_trading_system.py</files>
  <action>
1. CREATE itrader/config/universe.py (4-space indentation). Move the `UniverseConfig(BaseModel)` class
   VERBATIM from config/system.py (its full body: `model_config = ConfigDict(extra="forbid",
   validate_assignment=True)`, `poll_cadence_s: float = Field(default=60.0, gt=0.0)`,
   `remove_policy: str = "orphan-and-track"`) AND its existing docstring. Add
   `from pydantic import BaseModel, ConfigDict, Field` at the top. Module docstring: live
   dynamic-universe config (poll cadence + remove policy), ex-MonitoringSettings, live/control-plane
   only, OFF the backtest hot path, pydantic/stdlib-only so it stays inert (GATE-01).

2. EDIT config/system.py: DELETE the `UniverseConfig` class. KEEP `Environment`, `LogLevel`,
   `SystemSettings`. Update the module docstring to drop the UniverseConfig sentence. Before removing
   any import, CONFIRM it is still used by the kept classes: `SystemSettings` uses
   `ConfigDict` (model_config) and plain-default fields — it does NOT use `Field`. If `Field` is now
   unused in system.py, remove it from the `from pydantic import ...` line; keep `BaseModel`, `ConfigDict`.
   Keep `from enum import Enum`.

3. EDIT config/__init__.py: remove `UniverseConfig` from the `from .system import (...)` block; add
   `from .universe import UniverseConfig`. Keep Environment/LogLevel/SystemSettings from .system.
   `__all__` unchanged (still lists "UniverseConfig").

4. Repoint the consumer imports (split UniverseConfig onto its own `from itrader.config.universe import
   UniverseConfig` line, keep the rest from .system):
   - itrader/config/itrader_config.py: `from itrader.config.system import Environment, SystemSettings, UniverseConfig`
     → `from itrader.config.system import Environment, SystemSettings` + `from itrader.config.universe import UniverseConfig`.
   - itrader/trading_system/config_router.py: `from itrader.config.system import SystemSettings, UniverseConfig`
     → `from itrader.config.system import SystemSettings` + `from itrader.config.universe import UniverseConfig`.
   - itrader/trading_system/live_trading_system.py (TWO local imports, ~:1039 and ~:1178, both
     `from itrader.config.system import SystemSettings, UniverseConfig`) → same split at each site.

5. GREP: confirm zero `from itrader.config.system import` lines still contain `UniverseConfig`
   (test_config_restart_layering.py only mentions it in a comment — leave it).
  </action>
  <verify>
    <automated>test -f itrader/config/universe.py && ! grep -rnE "from itrader\.config\.system import.*UniverseConfig" itrader tests --include="*.py" && ! grep -nq "class UniverseConfig" itrader/config/system.py; poetry run python -c "from itrader.config import ITraderConfig, UniverseConfig; from itrader.config.universe import UniverseConfig as U; c=ITraderConfig(); assert isinstance(c.universe, UniverseConfig); assert float(c.universe.poll_cadence_s)==60.0; assert c.universe.remove_policy=='orphan-and-track'; import sys; assert 'sqlalchemy' not in sys.modules and 'ccxt' not in sys.modules; print('MOVE OK')"</automated>
  </verify>
  <done>config/universe.py holds UniverseConfig; system.py no longer defines it (keeps Environment/LogLevel/SystemSettings); every consumer imports UniverseConfig from itrader.config.universe; the barrel re-exports it; import stays inert.</done>
</task>

<task type="auto">
  <name>Task 2: Verification gate</name>
  <files>(no source changes — verification only)</files>
  <action>
Run each and confirm success (do NOT use `make test`):
  1. `poetry run pytest tests -q` — full suite green.
  2. `poetry run pytest tests/integration/test_okx_inertness.py -q` — inertness intact.
  3. `poetry run pytest tests/integration/test_backtest_oracle.py -q` — byte-exact 134 / 46189.87730727451.
  4. `poetry run mypy itrader` — strict-clean.
If any fails, fix the offending edit and re-run.
  </action>
  <verify>
    <automated>poetry run pytest tests -q && poetry run pytest tests/integration/test_okx_inertness.py -q && poetry run pytest tests/integration/test_backtest_oracle.py -q && poetry run mypy itrader</automated>
  </verify>
  <done>Full suite, inertness gate, byte-exact oracle, and mypy all green.</done>
</task>

</tasks>

<success_criteria>
- UniverseConfig lives in config/universe.py; system.py keeps only Environment/LogLevel/SystemSettings.
- Every consumer imports UniverseConfig from itrader.config.universe; the barrel re-exports it (__all__ unchanged).
- Full suite + OKX inertness + byte-exact oracle + mypy all green; behavior byte-identical.
</success_criteria>

<output>
Create `.planning/quick/260716-mov-move-universeconfig-into-its-own-config-/260716-mov-SUMMARY.md` when done.
</output>
