# Phase 10: Strategies Registry ★ - Research

**Researched:** 2026-07-17
**Domain:** Durable strategy roster (persistence + rehydrate + runtime mutation) — brownfield wiring of existing P4/P7/P9 surface
**Confidence:** HIGH (all three CONTEXT research items resolved with in-repo code evidence; zero external dependencies involved)

## Summary

P10 is a **wiring + extension** phase, not a build phase. The CONTEXT's assessment is confirmed by
code: `StrategyRegistryStore` is complete and unwired, the P7 warmup pipeline is complete, the
`STRATEGY_COMMAND` ingress allowlist already admits the verb, and the P9 `ConfigRouter`/`VenueStore`
block is a directly-copyable template. Zero new dependencies are needed.

All three CONTEXT research items resolve cleanly and, in two cases, **more favourably than the CONTEXT
feared**. The flagged `build_live_system` D-12 tension (research item 2) **dissolves on inspection** —
rehydrate belongs at construction time in `build_live_system`, and that placement is *compatible with*
rather than in conflict with the existing test contracts, because D-12's deferral governs *session
wiring*, not *strategy registration*. The `config_json` round-trip (item 3) is lossless with a
`_DERIVED_FIELDS = {"warmup", "max_window"}` exclusion set that I verified is exhaustive.

This research also surfaces **three defects the CONTEXT did not anticipate**, all reachable only via
P10's new capabilities. The most serious (F-1: the ring-depth unit mismatch) makes D-15's
timeframe-mutability produce a strategy that **can never warm**. These are flagged in
`## Common Pitfalls` and are the highest-value content here after the three resolved items.

**Primary recommendation:** Run rehydrate at construction time in `build_live_system`, inside the
existing `system_store is not None` gate, immediately AFTER the `_layer_persisted_overrides(...)` call
at `live_trading_system.py:1546-1555`. That single placement satisfies the D-01 store-is-source-of-truth
contract, the CONTEXT's portfolios-before-strategies ordering constraint, the
`register_strategy_warmup` / `wire_universe` read-ordering constraint, and every existing live test
contract — with no change to `_initialize_live_session`. Then gate D-15's timeframe mutability behind
the F-1 ring-depth fix, or narrow D-15's allowlist.

## Research Items Resolved

### Item 1 — The live feed's multi-timeframe model: **RESOLVED. It resamples; it does not multi-subscribe.**

**Answer:** `LiveBarFeed` holds **one ring per (symbol, timeframe) but only ever populates the BASE
timeframe ring**, and serves a coarser strategy timeframe by **resampling that base ring on read**. No
per-timeframe stream subscription exists or is needed for a coarser timeframe.

**Evidence:**
- `live_bar_feed.py:749-764` (`window()`) — `if timeframe == self._base_timeframe: resampled = base`
  else `base.resample(alias, label="left", closed="left").agg(_AGG).dropna(how="all")`. The coarser
  timeframe is a **pull-resample from the base ring** (the docstring names this "D-11 pull-resample from
  the ring"). [VERIFIED: source read]
- `live_bar_feed.py:786-806` (`_find_ring`) — explicitly returns **only** the ring whose timeframe
  normalizes to `self._base_alias`; the docstring states a "coarser/other-timeframe ring for the same
  symbol is NOT returned." So `window()` always reads base bars regardless of the requested timeframe.
  [VERIFIED: source read]
- `live_bar_feed.py:262-269` (WR-01 off-grid rejection) — a bar that is not on the base `L+tf` grid is
  WARN+dropped. This is the mechanism that makes a **finer**-than-base timeframe unserviceable: the feed
  physically has no sub-base bars, and nothing would deliver them without re-subscribing the stream.
  [VERIFIED: source read]
- `outils/time_parser.py:173` (`check_timeframe`) + `strategies_handler.py:159` — the dispatch gate is
  `if not check_timeframe(event.time, strategy.timeframe): continue`. A coarser strategy simply
  **skips** base bars that are not on its grid; it needs no separate stream. [VERIFIED: source read]

**What this pins for D-15:**
1. D-15's core mechanism is **confirmed correct**: coarser-or-multiple → plain re-warm, **no feed
   re-subscribe, no `min_timeframe` ripple**. The stream is already streaming finer-than-needed and
   `window()`'s resample absorbs the change transparently. The CONTEXT's reasoning holds exactly.
2. D-15's rejection of finer-than-base is **confirmed necessary**, and for a stronger reason than the
   CONTEXT states: it is not merely that re-subscribing is expensive — the off-grid guard at `:263`
   means finer bars would be **actively dropped** even if they arrived. The deferred todo's framing
   (re-subscribe + re-warm all + base recompute) is the right shape. [VERIFIED: source read]
3. The "non-multiple" rejection is **also confirmed necessary**: `resample()` on a non-multiple alias
   would produce buckets straddling base-bar boundaries with partial data. Reject as D-15 says.

> [!WARNING]
> **BUT — D-15's mechanism is broken today by a ring-depth unit mismatch (F-1).** The "plain re-warm on
> the new grid" is necessary but **not sufficient**: the base ring is not deep enough to yield the
> coarser strategy's required bar count. See **Pitfall F-1**. This is the single most important
> finding in this document and it directly gates D-15.

### Item 2 — Where rehydrate runs: **RESOLVED. Construction time, in `build_live_system`. The D-12 tension dissolves.**

**Recommendation:** Place rehydrate in `build_live_system`, **inside the existing
`if system_store is not None:` gate**, **immediately after** the `_layer_persisted_overrides(...)` call
that ends at `live_trading_system.py:1555`. Do **not** put it in `_initialize_live_session`.

**Why the flagged tension dissolves.** The CONTEXT records D-12 as deferring live session wiring to
`start()` "because of the pervasive add-strategy-after-construction + monkeypatch-
`_initialize_live_session`-before-`start()` contracts," and asks how rehydrate — which *creates*
strategies — coexists. The resolution: **D-12's deferral governs session wiring, not strategy
registration.** Those are different concerns, and the test contracts constrain only the former.

Evidence, in the order that settles it:

1. **The existing test contract is literally "register strategies at construction time, before
   `start()`."** Every live test does `system = build_live_system(...)` then
   `system.strategies_handler.add_strategy(...)` then `start()` (or a monkeypatched no-op session init).
   Rehydrate registering strategies during `build_live_system` **is the same lifecycle position** those
   tests already occupy. It composes with them rather than conflicting: a test-added strategy and a
   rehydrated strategy simply both land in `strategies_handler.strategies` before session init reads it.
   [VERIFIED: `grep add_strategy tests/` — 30 files; pattern confirmed in
   `tests/integration/test_paper_restart_restore.py`, `test_live_portfolio_durable_wiring.py`]
2. **The monkeypatch contract is *satisfied*, not broken, by construction-time rehydrate.** Three
   integration tests neutralize session init with `monkeypatch.setattr(system,
   "_initialize_live_session", lambda: None)` — `test_paper_restart_restore.py:139,196`,
   `test_live_portfolio_durable_wiring.py:140`. If rehydrate lived *inside* `_initialize_live_session`,
   those tests would silently lose it — and `test_paper_restart_restore.py` is a **restart** test, so
   that would be actively wrong. Construction-time placement keeps rehydrate reachable in exactly the
   tests that most need it. [VERIFIED: source read]
3. **Session init MUST read a fully-populated strategy list, so rehydrate must precede it.** This is a
   hard ordering constraint, not a preference:
   - `session_initializer.py:118` — `universe = wire_universe(engine)`, which uses
     `StrategyDerivedSelectionModel` (`session_initializer.py:110`): **membership is derived FROM the
     registered strategies.** A strategy rehydrated after this point would never enter the universe and
     its symbols would never be subscribed.
   - `session_initializer.py:124-125` — `register_strategy_warmup(engine.feed,
     engine.strategies_handler.strategies)`: **the feed ring is sized from the registered strategies.**
     A strategy rehydrated after this point would not size the ring.
   [VERIFIED: source read]
4. **The CONTEXT's portfolios-before-strategies ordering constraint is satisfied at that exact line.**
   `_layer_persisted_overrides` iterates `portfolio_handler._portfolios` at `:1250` — so portfolios
   exist (built by `compose_engine`, `:1414`) and their persisted config has been layered by the time
   control reaches `:1555`. Rehydrating strategies immediately after means `subscribe_portfolio` binds
   to portfolio_ids that are already present and restart-stable. [VERIFIED: source read]
5. **It is the P9 template verbatim.** The `system_store is not None` gate at `:1510-1555` already does
   exactly this shape: lazy imports inside the gate, construct the store, apply persisted state,
   degrade cleanly to a no-op on the in-memory fallback. Rehydrate is one more block in that pattern —
   which also keeps `strategy_registry_store` imports lazy inside the live gate, satisfying GATE-01.
   [VERIFIED: source read]

**Concrete recommended shape** (indentation: **4 SPACES** — `live_trading_system.py` is 4-space, see
`## Indentation Map`):

```python
# Inside `if system_store is not None:` in build_live_system, AFTER _layer_persisted_overrides(...)
# (live_trading_system.py:~1555). Lazy import inside the gate — GATE-01 inertness.
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.rehydrate import rehydrate_strategies  # D-05 collaborator

strategy_registry_store = StrategyRegistryStore(system_db_backend)
# D-19: infrastructure failure (no catalog injected / store unreadable) -> fail LOUD.
# Per-instance failure (unknown type / undeserializable config) -> skip + alert_sink CRITICAL.
rehydrate_strategies(
    store=strategy_registry_store,
    catalog=strategy_catalog,          # D-01 injected; see open question OQ-1
    strategies_handler=engine.strategies_handler,
    alert_sink=alert_sink,             # D-19 CRITICAL egress (already built at :1495)
)
```

**Two consequences the planner must handle:**
- **The D-21 empty-registry case is the default for every existing test.** No current test has
  `strategy_registry` rows (the store is constructed only in
  `tests/unit/storage/test_strategy_registry_store.py`), so rehydrate is a zero-row no-op everywhere
  today → **no existing live test changes behaviour.** This is why the placement is safe. Blast radius
  is genuinely near-zero. [VERIFIED: `grep -rl StrategyRegistryStore tests/`]
- **D-02's duplicate-name loud-reject can only fire if a test both seeds rows and adds a same-named
  strategy.** No such test exists today. But P10's own D-22 restart test will do both — so the planner
  should ensure that test seeds rows and does *not* also hand-add the same instance.

### Item 3 — The `config_json` round-trip contract: **RESOLVED, with three aliasing traps.**

**Answer:** `cls(**authoring_params)` **is** lossless for every shipped strategy, and
**`_DERIVED_FIELDS = {"warmup", "max_window"}` is exhaustive as an exclusion set** — but only if the
codec ALSO handles three **aliased** fields whose on-instance runtime value is *not* a valid kwarg. The
CONTEXT's D-04 named the exclusions correctly; the aliasing is the part that will silently break a naive
implementation.

**The authoring surface is exactly the class-body annotations, and runtime fields are auto-excluded.**
`_declared_hints(cls)` is `get_type_hints(cls)` (`base.py:131-133`), which returns only **class-body**
annotations across the MRO. The base declares exactly ten (`base.py:170-186`): `timeframe`, `tickers`,
`sizing_policy`, `direction`, `allow_increase`, `max_positions`, `sltp_policy`, `max_window`, `warmup`,
`name`. `is_active`, `subscribed_portfolios`, and `strategy_id` are assigned in `__init__` with
*function-local* annotations (`base.py:190-194`), which never enter `cls.__annotations__` — so they are
**structurally invisible** to `_declared_hints` and need no explicit exclusion. D-04's runtime-exclusion
requirement is satisfied for free. [VERIFIED: source read]

**Trap 1 — `timeframe` is destructively resolved on the instance. Serialize `timeframe_alias`.**
`_apply_params` sets `self.timeframe` to the coerced `Timeframe` **enum** in its loop, then at
`base.py:318-320` **overwrites it with a `timedelta`** (`self.timeframe = to_timedelta(...)`), stashing
the enum on `self._timeframe` and the string on `self.timeframe_alias`. So
`getattr(strategy, "timeframe")` returns a `timedelta` — **not** a valid `timeframe=` kwarg. The codec
MUST serialize `self.timeframe_alias` (a str, e.g. `"1d"`), which `_COERCE` (`base.py:138-141`)
re-coerces back to `Timeframe` on load. `to_dict` already does exactly this and documents why
(`base.py:766-769` — "resolves to a timedelta at runtime — skip it here and serialize via the stable
`timeframe_alias`"). This confirms D-04's parenthetical "`timeframe` alias" and is the #1 trap.
[VERIFIED: source read]

**Trap 2 — `name` is the authoring kwarg; `strategy_name` is the store PK.** `to_dict` surfaces `name`
as `strategy_name` (`base.py:769`). The codec's `cls(**params)` needs `name=`, and the store row key is
`strategy_name`. Per D-02 these are the same value under two spellings — the reconstruction collaborator
must map `rec["strategy_name"] -> name=`. Do **not** store `name` redundantly inside `config_json`
(it would permit a row whose PK and blob disagree). [VERIFIED: source read]

**Trap 3 — `direction` serializes as `.value`.** `TradingDirection` is an `Enum`; `_COERCE` re-coerces a
str on load via the enum's case-insensitive `_missing_`. D-04 already names this. [VERIFIED: source read]

**`_DERIVED_FIELDS` — why `{warmup, max_window}` is exhaustive AND why excluding beats storing:**
`_run_init` (`base.py:382-406`, docstring) is the only post-`_apply_params` mutator of declared fields,
and it touches exactly two:
- `warmup` — **unconditionally overwritten** to `max(min_period, default=0)` (the WR-03 footgun fix,
  D-08). Storing it is pointless; excluding it is correct. Round-trip re-derives it identically.
- `max_window` — `max(handle-derived, hand-set class value)`. **Excluding it is correct and
  reproduces author intent exactly**, verified against all three shipped strategies:
  | Strategy | class `max_window` | handle-derived | excluded → `max(derived, class_default)` | correct? |
  |---|---|---|---|---|
  | `SMAMACDStrategy` | (base default `0`) | 100 | `max(100, 0) = 100` | ✅ |
  | `EmptyStrategy` (`empty_strategy.py:16`) | `1` | 0 | `max(0, 1) = 1` | ✅ |
  | `EthBtcPairStrategy` (`eth_btc_pair_strategy.py:75`) | `280` | (pair) | `max(derived, 280) = 280` | ✅ |
  [VERIFIED: source read]

> [!WARNING]
> **Do NOT store `max_window` in `config_json` "to be safe" — it ratchets and never shrinks (F-2).**
> `_apply_params`' reconfigure fallback (`base.py:252-255`) reads the **prior instance value**, which
> after `_run_init` is the **post-`max()` derived value**. Storing and replaying it means `max_window`
> monotonically ratchets upward across reconfigures and can never shrink — silently defeating D-14's
> "window shrank → still warm" case. Excluding it is not just tidier; it is the **correctness**
> requirement. See Pitfall F-2.

**The D-03 generic dataclass codec against `core/sizing.py` — one field resists generic coercion:**

| Policy | `file:line` | Fields | Generic-codec safe? |
|---|---|---|---|
| `FractionOfCash` | `sizing.py:94` | `fraction: Decimal`, `step_size: Decimal \| None` | ✅ str↔Decimal |
| `FixedQuantity` | `sizing.py:118` | `qty: Decimal`, `step_size: Decimal \| None` | ✅ |
| `RiskPercent` | `sizing.py:138` | `risk_pct: Decimal`, `step_size: Decimal \| None` | ✅ |
| `LeveredFraction` | `sizing.py:162` | `fraction: Decimal`, `step_size: Decimal \| None` | ✅ |
| `PercentFromFill` | `sizing.py:209` | `sl_pct`, `tp_pct: Decimal`; **`trail_type: "TrailType \| None"`**; `trail_value: Decimal \| None` | ⚠️ **see below** |
| `PercentFromDecision` | `sizing.py:278` | `sl_pct: Decimal`, `tp_pct: Decimal` | ✅ |

**Two flags on this table:**

1. **`PercentFromFill.trail_type` is the one field that resists generic introspective coercion**, on
   three counts (`sizing.py:242`):
   - It is a **string-quoted forward reference** (`"TrailType | None"`). `dataclasses.fields()[i].type`
     returns the **raw string** `'TrailType | None'`, not a type — a naive `fields()`-driven codec gets
     an unusable string. The codec must use `typing.get_type_hints(cls)` (as `_declared_hints` already
     does for strategies), **not** `field.type`.
   - `TrailType` is **deliberately not importable at `core/sizing.py` module level** — it lives in
     `config/` (the config-enum exception, CONVENTIONS.md) and is lazily imported inside `__post_init__`
     at `sizing.py:264` precisely to avoid inverting the core→config dependency. `get_type_hints()` on
     this class will therefore **raise `NameError`** unless given an explicit `localns`/`globalns`
     containing `TrailType`. **This will bite the implementer.** The codec must either resolve hints with
     an explicit namespace or special-case enum members of a union.
   - It is an **`Enum` inside an `Optional` union** — the codec's "coerce by declared type" needs to
     unwrap `X | None` and dispatch to `Enum(value)` for the non-None arm.
   [VERIFIED: source read]
2. **`PercentFromDecision` is missing from the CONTEXT's D-03 list.** The CONTEXT enumerates
   `FractionOfCash / FixedQuantity / RiskPercent / LeveredFraction / PercentFromFill`. The `SLTPPolicy`
   union at `sizing.py:301` is `PercentFromFill | PercentFromDecision` — so **`PercentFromDecision`
   (`sizing.py:278`) is a first-class member the codec's `kind → class` registry must include.** Omitting
   it would make any strategy declaring it un-rehydratable (a D-19 quarantine on a healthy strategy).
   This is a genuine gap in the CONTEXT, not a re-litigation. [VERIFIED: source read]

**The two canonical unions to drive the registry from** (`sizing.py:205`, `:301`):
```python
SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent | LeveredFraction
SLTPPolicy   = PercentFromFill | PercentFromDecision
```
Deriving the default `kind → class` registry from `typing.get_args()` of these two unions keeps it
**structurally impossible to omit a member** (the D-02 growth rule + `assert_never` discipline already
guards the resolver the same way). Recommended over a hand-listed dict; the injectable overlay for
custom IP policies (D-03) layers on top.

**Round-trip verdict per shipped strategy:**
| Strategy | `file` | Authoring params | Lossless? |
|---|---|---|---|
| `SMAMACDStrategy` | `strategies/SMA_MACD_strategy.py:13` | `name`, `tickers`, `timeframe`→alias, `sizing_policy`(`FractionOfCash`), `direction`→`.value`, `short/long/fast/slow/signal_window: int`, `allow_increase`, `max_positions`, `sltp_policy` | ✅ |
| `EmptyStrategy` | `strategies/empty_strategy.py:5` | base ten only | ✅ |
| `EthBtcPairStrategy` | `strategies/eth_btc_pair_strategy.py:46` | base ten + `z_lookback: int`, `beta_warmup: int`, `entry_units: Decimal` | ✅ **with a caveat →** |

> [!NOTE]
> **`EthBtcPairStrategy` has UNANNOTATED class attrs that are invisible to the engine — this is
> pre-existing, and it independently reinforces D-17.** `entry_z = Decimal("2")` (`:68`),
> `exit_z = Decimal("0.5")` (`:69`), and `leverage = Decimal("1")` (`:72`) carry **no annotation**, so
> `_declared_hints` never sees them: they are **not kwarg-settable, not reconfigurable, and not part of
> the authoring surface** — by the base's own documented design (`base.py:167-172`: "an unannotated
> class attr would be invisible to the engine"). They round-trip **correctly** (as class constants) —
> the codec simply never touches them. But it means a pair's most interesting knobs (`entry_z`/`exit_z`)
> are already un-reconfigurable at the base-class level, entirely independently of D-17's guard. **No
> action for P10** (D-17 refuses pair reconfiguration wholesale). Recorded because it is a fact the
> next-milestone pair-reconfiguration work will need: annotating those three attrs is a prerequisite
> there. `my_strategies/` contains only subpackages of indicators/filters, no `Strategy` subclasses at
> the top level — nothing further to audit. [VERIFIED: source read]

## Indentation Map (measured, per file — do not generalize)

Measured by counting leading-tab vs leading-4-space lines. **The CONTEXT contains one error here.**

| File P10 touches | Measured | Verdict |
|---|---|---|
| `itrader/strategy_handler/base.py` | 838 tab / 0 space | **TABS** |
| `itrader/strategy_handler/strategies_handler.py` | 603 tab / 0 space | **TABS** |
| `itrader/strategy_handler/pair_base.py` | 192 tab / 0 space | **TABS** |
| `itrader/storage/strategy_registry_store.py` | 0 tab / 248 space | **4-SPACE** |
| `itrader/core/sizing.py` | 0 tab / 220 space | **4-SPACE** |
| `itrader/events_handler/events/universe.py` | 0 tab / 79 space | **4-SPACE** |
| `itrader/trading_system/live_trading_system.py` | 0 tab / 1434 space | **4-SPACE** |
| `itrader/trading_system/session_initializer.py` | 0 tab / 126 space | **4-SPACE** |
| `itrader/trading_system/route_registrar.py` | 0 tab / 121 space | **4-SPACE** |
| `itrader/universe/universe_handler.py` | 0 tab / 559 space | **4-SPACE** ⚠️ |
| `migrations/versions/strategy_registry.py` | 0 tab / 37 space | **4-SPACE** |

> [!WARNING]
> **CONTEXT CORRECTION.** `10-CONTEXT.md` (Established Patterns, line ~359) states "`strategy_handler/`
> and `universe/` are **tabs**." **`itrader/universe/universe_handler.py` is 4-SPACE** (0 tab-indented
> lines out of 559). The `strategy_handler/` half of that claim is correct. A planner or executor
> trusting the CONTEXT verbatim would write tabs into a 4-space file — exactly the mixed-indentation
> break the project constraint warns about. **New codec module in `core/` → 4-space. New reconstruction
> collaborator in `strategy_handler/` → tabs.** [VERIFIED: measured]

## Standard Stack

**Zero new dependencies.** Everything P10 needs is already in `pyproject.toml`; v1.8's no-poetry-change
constraint holds trivially.

| Library | Version | Purpose in P10 | Why standard here |
|---|---|---|---|
| `sqlalchemy` | ^2.0.50 | `strategy_registry` + new child table; Core-only parameterized (SEC-01) | The existing spine — `StrategyRegistryStore` is already built on it [VERIFIED: source read] |
| `alembic` | (via sqlalchemy spine) | D-06 migration chaining after `system_stats` | The existing chain owner [VERIFIED: `migrations/versions/`] |
| `msgspec` | (in-tree) | D-08 optional `config` field on `StrategyCommandEvent` | Events are `msgspec.Struct` [VERIFIED: source read] |
| stdlib `dataclasses` + `typing.get_type_hints` | 3.13 | D-03 generic codec introspection | `fields()[i].type` returns raw strings — `get_type_hints` is required (see Trap in Item 3) [VERIFIED: source read] |
| stdlib `decimal` | 3.13 | Money boundary — `Decimal(str)` only | Locked project policy |

**Installation:** none required.

## Package Legitimacy Audit

**Not applicable — P10 installs no external packages.** No `npm`/`pip`/`cargo` install occurs; the
milestone-wide constraint is zero new dependencies and P10 requires none. No `[SLOP]`/`[SUS]` verdicts to
report; no `checkpoint:human-verify` install gate needed.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Persist instance rows + portfolio subs | Database / Storage (`itrader/storage/`) | — | D-06; the store is persistence-only and must not import strategy classes (D-05, inertness) |
| Serialize/deserialize policy value objects | Core (`itrader/core/`) | — | D-05; codec serializes core value objects, depends on nothing in `itrader`, is a money boundary |
| `catalog × row × codec → Strategy` | Domain (`strategy_handler/` collaborator) | Core (codec) | D-05; NOT in `Strategy` base (pure-alpha #24 boundary), NOT in the store |
| Rehydrate call + catalog injection | Composition root (`build_live_system`) | Storage, Domain | Item 2; must precede session init, must follow portfolio layering |
| Verb dispatch + persist-on-mutate | Domain (`StrategiesHandler.on_strategy_command`) | Storage | D-09; the handler owns the roster |
| `is_active` gate | Domain (`calculate_signals`) | — | D-07; the one shared hot-path edit (oracle-gated) |
| External ingress | Composition/facade (`add_event`) | — | D-22; already admits `STRATEGY_COMMAND`, no change |
| Warmup after add/reconfigure | Domain (`universe_handler` P7 pipeline) | Feed | D-10/D-14; reuse, don't reinvent |

## Architecture Patterns

### System Architecture Diagram

```
                        ┌──────────────────────────────────────────────┐
   RESTART / BOOT       │           build_live_system()                │
   ──────────────►      │  (composition root, live_trading_system.py)  │
                        │                                              │
                        │  compose_engine ──► portfolio_handler        │
                        │        │            strategies_handler       │
                        │        ▼                                     │
                        │  if system_store is not None:   :1510        │
                        │    ├─ ConfigRouter / VenueStore              │
                        │    ├─ _layer_persisted_overrides()  :1546    │
                        │    │     └─► portfolios rehydrated ✔         │
                        │    │                                         │
                        │    └─ ★ REHYDRATE STRATEGIES ★    (P10 NEW)  │
                        │         store.list_active()                  │
                        │              │                               │
                        │              ▼                               │
                        │   ┌──────────────────────────────┐           │
                        │   │ for each row:                │           │
                        │   │  cls = catalog[type] ────────┼──► KeyError ──► D-19
                        │   │  params = codec.decode(cfg) ─┼──► ParamError ─► QUARANTINE
                        │   │  cls(name=…, **params)       │           │      (skip + CRITICAL
                        │   │  handler.add_strategy(…)     │           │       via alert_sink)
                        │   │  strategy.subscribe_portfolio│           │
                        │   └──────────────────────────────┘           │
                        └────────────────┬─────────────────────────────┘
                                         │  strategies list POPULATED
                                         ▼
                        ┌──────────────────────────────────────────────┐
   start()  ──────────► │      _initialize_live_session()  :541        │
                        │        └─► SessionInitializer                │
                        │              ├─ wire_universe(engine)        │  reads strategies
                        │              │    └─ StrategyDerivedSelection│  ◄── ORDERING
                        │              ├─ register_strategy_warmup(    │      CONSTRAINT
                        │              │      feed, strategies)        │  ◄── (see F-1)
                        │              └─ LiveRouteRegistrar.install   │
                        └────────────────┬─────────────────────────────┘
                                         ▼
   RUNTIME MUTATION                 global_queue
   ────────────────►  add_event(StrategyCommandEvent)   [allowlist :57 ✔]
                            │
                            ▼
                      route_registrar :106 ──► StrategiesHandler.on_strategy_command :438
                            │
              ┌─────────────┼──────────────┬───────────────┬──────────────┐
              ▼             ▼              ▼               ▼              ▼
            add          remove        enable/disable  reconfigure   (un)subscribe_portfolio
              │             │              │               │              │
     catalog-gate    force-flat      is_active flag   D-13 ordering:  mutate list
     + dup-name      (P7 detach-      (stays WARM)    validate→persist  + child row
     reject (D-02)    on-flat)              │          →apply→re-warm      │
              │             │               │               │              │
              └─────────────┴───────────────┴───────────────┴──────────────┘
                                         │
                                    EVERY VERB PERSISTS
                                         ▼
                              StrategyRegistryStore (SQL)
                                         │
                    ┌────────────────────┴────────────────────┐
                    ▼                                         ▼
            strategy_registry                  strategy_portfolio_subscriptions
        (strategy_name PK, strategy_type,          (strategy_name FK, portfolio_id)
         config_json, enabled, updated_at)                composite PK
                                                    [strategy_subscriptions: DROPPED]

   WARMUP (reused, P7):  add/reconfigure-grow ──► spawn_warmup :508 ──► REST backfill
                                                        │
                              instance DARK (WR-02 gate, is_ready False)
                                                        │
                          BarsLoaded ──► on_bars_loaded :516 ──► READY ──► trades
                          BarsLoadFailed ──► FAILED ──► CR-02 retry next poll (:383-394)
```

### Recommended Project Structure

```
itrader/
├── core/
│   ├── sizing.py                    # existing frozen policies (unchanged)
│   └── policy_codec.py              # NEW — D-03/D-05 codec. 4-SPACE. No itrader deps.
├── strategy_handler/
│   ├── base.py                      # TABS — D-07 is_active is in strategies_handler, not here
│   ├── strategies_handler.py        # TABS — D-07 guard, D-09 verbs
│   └── registry/                    # NEW collaborator subdir (mirrors order_handler/admission/)
│       ├── __init__.py
│       ├── catalog.py               # TABS — StrategyCatalog type alias / validation
│       └── rehydrate.py             # TABS — build_strategy(catalog, row, codec) + D-19 quarantine
├── storage/
│   └── strategy_registry_store.py   # 4-SPACE — D-06 schema change + portfolio-sub methods
└── trading_system/
    └── live_trading_system.py       # 4-SPACE — rehydrate call site (Item 2)
migrations/versions/
└── p10_strategy_portfolio_subs.py   # NEW — down_revision = "system_stats" (current head)
```

### Pattern 1: The P9 gated-store block (the D-01 template)

**What:** Construct a store + apply its persisted state inside a `system_store is not None` gate in
`build_live_system`, with lazy imports, degrading cleanly to a no-op on the in-memory fallback.
**When to use:** Every durable-store wiring in this codebase. P10's rehydrate is the next instance.
**Example** (`live_trading_system.py:1510-1555`, verbatim shape):

```python
# Source: itrader/trading_system/live_trading_system.py:1510-1555
order_handler = engine.order_handler
if system_store is not None:
    from itrader.core.clock import WallClock
    from itrader.storage.venue_store import VenueStore      # LAZY inside the gate — GATE-01
    from itrader.trading_system.config_router import ConfigRouter

    venue_store: Optional[Any] = VenueStore(system_db_backend)
    facade._config_router = ConfigRouter(...)

    # RESTART LAYERING (D-10/D-22): apply persisted overrides on boot from each OWNING store.
    _layer_persisted_overrides(
        _system_config, system_store=system_store, venue_store=venue_store,
        order_handler=order_handler, portfolio_handler=portfolio_handler,
        execution_handler=execution_handler,
    )
    # ★ P10 rehydrate goes HERE — portfolios are layered above; session init reads strategies below.
```

### Pattern 2: Degrade-clean restart layering (`_degrade_clean`)

**What:** Wrap persisted-state application in `try/except _degrade_clean` → WARN + continue boot.
**When to use:** Infrastructure-shaped failures where boot should continue.
**Caution for D-19:** P10's semantics are **finer-grained** than this pattern. D-19 mandates
**per-instance** skip + **CRITICAL alert** (not a WARN), while **infrastructure** failure (no catalog,
unreadable store) must **fail loud** — the *opposite* of degrade-clean. Do not blanket-wrap rehydrate in
`_degrade_clean`; that would convert D-19's loud-infrastructure arm into a silent boot-with-zero-
strategies, which D-19 explicitly calls "worse."
**Example** (`live_trading_system.py:1243-1257`):

```python
# Source: itrader/trading_system/live_trading_system.py:1248-1257
try:
    for _pid, portfolio in portfolio_handler._portfolios.items():
        portfolio_cfg = portfolio.state_storage.load_config()
        if portfolio_cfg:
            portfolio.update_config(portfolio_cfg)
except _degrade_clean as exc:
    logger.warning("Skipping persisted PORTFOLIO-config restart layering — ... boot degrades clean", exc)
```

### Pattern 3: Trial-resolve-then-commit (the D-13 atomicity precedent already exists)

**What:** Resolve + validate the FULL input set into a local dict; mutate `self` only after every check
passes.
**When to use:** D-13's "trial-validate the FULL new config FIRST."
**Key insight for the planner:** `_apply_params` **already implements exactly this** (the WR-02 fix,
`base.py:235-300`) — `remaining`/`resolved` locals, commit phase at `:297-299`. So `_apply_params`
alone is already atomic. **The remaining tear is `validate()` and `_run_init()`**, which
`reconfigure` (`base.py:695-718`) calls *after* the commit — a cross-field `validate()` failure leaves
the strategy mutated. D-13's tightening is therefore **narrower than the CONTEXT implies**: the
setattr-tear is already fixed; what P10 must add is a **trial construction/validation** that exercises
`validate()` + `_run_init()` before committing. Recommended: build a **throwaway instance**
(`cls(**merged_params)`) as the trial — it runs `_apply_params` + `validate()` + `_run_init()` in the
real constructor path (`base.py:210-212`), proving the config good, then apply to the live instance.
**Example:**

```python
# Source: itrader/strategy_handler/base.py:295-299 (the existing WR-02 commit phase)
        # WR-02 commit phase: every check above passed — now mutate self. A
        # rejected reconfigure raised before reaching this line, leaving prior
        # instance state intact.
        for nm, val in resolved.items():
            setattr(self, nm, val)
```

### Anti-Patterns to Avoid

- **Serializing `getattr(strategy, "timeframe")`** — yields a `timedelta`, not a kwarg. Use
  `timeframe_alias` (Item 3, Trap 1).
- **Storing `max_window` in `config_json`** — ratchets, never shrinks (F-2).
- **Driving the D-03 codec off `dataclasses.fields()[i].type`** — returns raw strings for quoted
  forward refs (`PercentFromFill.trail_type`). Use `get_type_hints` with an explicit namespace.
- **Hand-listing the `kind → class` registry** — derive from `get_args(SizingPolicy)` /
  `get_args(SLTPPolicy)` so a new union member cannot be silently omitted (`PercentFromDecision` was
  already missed once, in the CONTEXT itself).
- **Putting rehydrate in `_initialize_live_session`** — three restart/wiring tests monkeypatch it to a
  no-op (Item 2).
- **Barrel-exporting `StrategyRegistryStore` or the catalog** — breaks GATE-01 inertness.
- **Blanket `except _degrade_clean` around rehydrate** — inverts D-19's loud-infrastructure arm.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Warmup after runtime `add` | A bespoke backfill path | `spawn_warmup` → `BarsLoaded` → `on_bars_loaded` → WR-02 gate → CR-02 retry (`universe_handler.py:508,516,383-394`) | Complete P7 pipeline; a second warmup path re-opens the parity gate (the LX-09 lesson the feed already learned — `live_bar_feed.py:286-290` explicitly refuses a second state-building path) |
| Force-flat on `remove` | A new close-and-wait state machine | P7 `_on_symbol_removed` / `on_fill` detach-on-flat | D-11; spans event cycles — exactly the machinery P7 built |
| Param coercion / unknown-param rejection | A codec-side validator | `_apply_params` + `_COERCE` (`base.py:138`, `:214`) | Already loud-rejects unknown/missing and coerces enums; codec must not duplicate or the two will drift |
| Atomic param application | A manual snapshot/rollback | Trial-construct `cls(**merged)` then apply | The constructor already runs the full validate chain (`base.py:210-212`) |
| Enum union coercion | Hand-written per-policy serializers | Generic `get_type_hints` + `get_args` unwrap | D-03; policies are frozen dataclasses with `__post_init__` re-validating on the way back |
| External ingress admission | A new API surface | `add_event` allowlist (`live_trading_system.py:57`) | Already admits `STRATEGY_COMMAND` (verified below) |

**Key insight:** P10's dominant risk is **duplicating existing machinery**, not missing machinery.
Every "new" capability in the phase already has a complete implementation one seam away. The phase's
real work is wiring, the D-06 schema change, the D-03 codec, and the verb branches.

## Common Pitfalls

### F-1 (NEW — HIGH SEVERITY): Ring depth is in BASE bars but `warmup` is in STRATEGY-timeframe bars — a coarser strategy can never warm

**What goes wrong:** D-15 makes `timeframe` reconfigurable to any coarser multiple of the base. But the
feed ring holds **base** bars, and `window()` **resamples** them (Item 1). A strategy on a coarser
timeframe therefore needs `warmup × multiple` **base** bars to yield `warmup` **coarse** bars. The ring
does not know this.

**Why it happens (the exact mechanism):**
- `register_strategy_warmup` (`cache_registration.py:229-252`) computes `depth = derive_warmup_depth(strategies)` from `strategy.warmup`, and registers a consumer with that depth.
- `cache_capacity()` (`feed/base.py:125-132`) returns `derive(self._raw_bar_consumers)` — for SMA_MACD, **100**.
- `LiveBarFeed` creates each ring as `deque(maxlen=self.cache_capacity())` (`live_bar_feed.py:675`, `:394`) — **100 BASE bars**.
- `strategy.warmup` is derived from indicator `min_period` (`base.py:391`) — units are the **strategy's own timeframe bars**, not base bars.
- With `base_timeframe == strategy.timeframe` (SMA_MACD on 1d, today's only live shape) the units coincide and the bug is **invisible**.
- Reconfigure that strategy 1h→4h: it still needs 100 bars, now 4h bars = **400 base bars**. The ring holds **100**. `window()` resamples 100×1h → **25×4h**. `warmup=100` is never reached → `calculate_signals` short-circuits forever → **the strategy silently never trades**.
[VERIFIED: source read across all five files]

**Compounding:** `deque(maxlen=...)` fixes capacity **at creation**. `cache_capacity()` is read lazily,
so re-registering a deeper consumer changes the *derived* value — but **existing rings do not resize**.
Only rings created afterwards (new symbols) get the new depth. So even a correct depth recomputation on
`reconfigure` would not fix an already-warm symbol's ring.

**How to avoid (planner options, in preference order):**
1. **Make the depth computation timeframe-aware**: `depth = max(s.warmup × (s.timeframe / base_timeframe))` over strategies, in base-bar units. This is the correct fix and is small.
2. **Add a ring-resize path** for the runtime `add`/`reconfigure` case (rebuild the deque with a larger maxlen, preserving contents), since re-registration alone cannot resize an existing ring.
3. **If (1)+(2) are too large for P10's budget:** narrow D-15 — accept `timeframe` reconfiguration **only** when the new required base depth ≤ current `cache_capacity()`, and **loud-reject** otherwise with a message naming the ring depth. This preserves D-15's owner-approved intent for the common case and fails loud (not silently dark) otherwise — consistent with the project's loud-rejection philosophy.

**Warning signs:** a reconfigured/added strategy that stays permanently `is_ready == False`;
`window()` returning fewer rows than `max_window` with no error (it returns a short frame, it does not
raise).

> This finding **gates D-15** and should be resolved in planning, not discovered in execution. It does
> not re-litigate D-15's owner decision (constrained-mutable timeframe is still right); it identifies
> the mechanism D-15 assumed was free ("plain re-warm on the new grid") and shows it needs one more
> piece. Recommend surfacing to the owner as a scope question.

### F-2 (NEW — MEDIUM): `max_window` ratchets across reconfigure if stored

Covered in Item 3. **Mitigation is D-04's exclusion set — already the locked decision.** Recorded here
so an implementer does not "improve" the codec by adding `max_window` to the blob for completeness.
**Warning sign:** a shrink-window reconfigure that unexpectedly goes dark (D-14 says it should stay
warm).

### F-3 (NEW — MEDIUM): `_declared_hints` is `@cache`-memoized **per class**, and the cache is process-global

`base.py:130-133` — `@cache def _declared_hints(cls)`. This is a **pure-function memo keyed on the
class**, so it is correct across instances of the same class. Two implications:
- **Safe:** rehydrating N instances of one type reuses one `get_type_hints` result. Good for perf.
- **Watch:** if the injected catalog ever provides two *different* classes with the same `__name__`
  (plausible with a submodule + a test double), the memo is keyed on the **class object**, not the name
  — so it is still correct. **No action needed.** Recorded to pre-empt a false alarm during review.
[VERIFIED: source read]

### P-4 (existing, restated): `reconfigure` omission is NOT a reset

`base.py:701-709` documents this explicitly (WR-04): "a field OMITTED from `kwargs` keeps its PRIOR
INSTANCE VALUE, NOT the class default… To reset a field you MUST pass it explicitly." **This is a
FastAPI-shaped hazard for D-22:** a PATCH-style partial payload behaves as a merge, not a replace. The
`reconfigure` verb's payload semantics must be documented as **merge**, and the persisted `config_json`
must be written from the **post-merge full param set**, not from the partial payload — otherwise the
row and the live instance diverge (violating D-13's DB-and-live-never-diverge goal).
**How to avoid:** after a successful trial-validate, serialize the **trial instance's full authoring
set**, not the incoming delta.

### P-5 (existing, restated): the D-07 `is_active` guard sits on the shared hot path

`strategies_handler.py:141` `calculate_signals` is shared by backtest and live. `is_active` defaults
`True` (`base.py:191`) and no backtest path ever calls `deactivate_strategy` — so
`if not strategy.is_active: continue` is behaviour-preserving. **But it must be oracle-verified**
(see `## Validation Architecture`). Place the guard **after** the `check_timeframe` gate to minimize
the touched region, or before — both are equivalent for correctness since `is_active` is loop-invariant.

### P-6 (existing): FK ordering on delete

`strategy_registry_store.py:208-220` deletes children **before** the parent, and `upsert` **updates**
(never deletes) the parent precisely because of the FK (`:126-131`, CR-01 — SQLite
`PRAGMA foreign_keys=ON` enforces it on both dialects). The new
`strategy_portfolio_subscriptions` child inherits this constraint: **D-11's `remove` must delete
portfolio-sub rows before the registry row.**

## Runtime State Inventory

P10 is a feature-add, not a rename/refactor — but it **creates** durable state and **drops a table**,
so the inventory is material.

| Category | Items Found | Action Required |
|---|---|---|
| **Stored data** | `strategy_registry` table — **exists in the migration chain** (`migrations/versions/strategy_registry.py`, revision `strategy_registry`) and is therefore **already deployed** to any DB at head. `strategy_subscriptions` child likewise. Both are **empty in practice** (the store has no production writer — it is unwired). | **Code edit + migration.** D-06: drop `strategy_subscriptions`, add `strategy_portfolio_subscriptions`, add `strategy_type` column to `strategy_registry`. Because the tables are empty, **no data migration is needed** — a plain drop/create is safe. **Verify** on the target DB before assuming empty. |
| **Live service config** | None. No external service (n8n, Datadog, Cloudflare) holds strategy roster state. | None. |
| **OS-registered state** | None. No Task Scheduler / pm2 / launchd entry references strategies. | None. |
| **Secrets / env vars** | None new. P10 reuses the existing `ITRADER_DATABASE_*` surface via `system_db_backend`. No new credential. | None. |
| **Build artifacts** | None. Pure-Python, no compiled artifact or egg-info impact. | None. |

**Migration chain — current head is `system_stats`** [VERIFIED: `grep down_revision migrations/versions/*.py`]:

```
2cbf0bf6b0b6 (operational_baseline)
  └─ 47f2b41f3ffe (portfolio_account_state)
      └─ p05_venue_order_id
          └─ hl5_transaction_venue_trade_id
              └─ d10_halt_records
                  └─ system_store
                      └─ venue_config
                          └─ strategy_registry
                              └─ module_config
                                  └─ system_stats        ◄── CURRENT HEAD
                                      └─ ★ P10 NEW ★     down_revision = "system_stats"
```

> [!NOTE]
> The CONTEXT describes the chain as `d10_halt_records → system_store → venue_config →
> strategy_registry` and says "P10's changes chain after." That is accurate but **incomplete** — two
> further revisions (`module_config`, `system_stats`) landed after `strategy_registry`. **P10's
> `down_revision` must be `"system_stats"`, not `"strategy_registry"`.** [VERIFIED: measured]

**Registrar contract:** `build_strategy_registry_tables` (`strategy_registry_store.py:48`) is the
**single source of truth** feeding both the test-path `create_all` and Alembic `target_metadata`. The
D-06 schema change must land in **both** the registrar and a migration, or the test-path and prod
schemas diverge. The store is **schema-pure** (WR-03/D-14 — never `create_all` at runtime).

## Code Examples

### The exact rehydrate row shape the store already returns

```python
# Source: itrader/storage/strategy_registry_store.py:222-240 (list_active)
    def list_active(self) -> list[Mapping[str, Any]]:
        """Every registry row with ``enabled=True`` — the typed-column query (D-09)."""
        statement = select(
            self.strategy_registry.c.strategy_name,
            self.strategy_registry.c.enabled,
            self.strategy_registry.c.config_json,
            self.strategy_registry.c.updated_at,
        ).where(self.strategy_registry.c.enabled.is_(True))
        ...
        return [{"strategy_name": ..., "config": ..., "enabled": ..., "updated_at": ...} for row in rows]
```
`list_active()` is **exactly** D-01's rehydrate query and needs no change. Note `read_all()`
(`:254-308`) currently JOINs `strategy_subscriptions` — **that method must be reworked** for the D-06
table swap (it returns `subscriptions: [(venue, symbol, timeframe)]` tuples that will no longer exist).

### The `timeframe` alias trap, as `to_dict` already handles it

```python
# Source: itrader/strategy_handler/base.py:766-772
        for nm in _declared_hints(type(self)):
            # `timeframe` resolves to a timedelta at runtime — skip it here and
            # serialize via the stable `timeframe_alias` below (the str the
            # snapshot can round-trip). `name` is surfaced as `strategy_name`.
            if nm in ("timeframe", "name"):
                continue
            val = getattr(self, nm, None)
            if isinstance(val, Enum):
                val = val.value
```
The codec's serialize side must reproduce this skip+alias. `to_dict` diverges only at the policy arm
(`repr(val)`, one-way) — which is precisely D-03's reason for a separate codec.

### The union to derive the `kind → class` registry from

```python
# Source: itrader/core/sizing.py:205, :301
SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent | LeveredFraction
SLTPPolicy   = PercentFromFill | PercentFromDecision
```

### The D-22 external ingress — already open, no change needed

```python
# Source: itrader/trading_system/live_trading_system.py:56-58
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)
```
[VERIFIED: source read] **D-22's assumption is confirmed.** `add_event(StrategyCommandEvent.add(...))`
is admitted today; P10's tests need no ingress change.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact on P10 |
|---|---|---|---|
| `strategy_subscriptions` (venue, symbol, timeframe) | `strategy_portfolio_subscriptions` (strategy_name, portfolio_id) | P10 / D-06 | The P4 table is unwired — near-zero blast radius; `read_all()` must be reworked |
| `to_dict()` policy `repr()` | D-03 tagged-union codec | P10 | `to_dict` **stays** as the one-way observability snapshot; the codec is additive, not a replacement |
| `warmup` author-settable | `warmup` unconditionally derived (WR-03/D-08 footgun fix) | pre-P10 | Confirms `warmup ∈ _DERIVED_FIELDS` |
| Per-value setattr in `_apply_params` | Trial-resolve-then-commit (WR-02) | pre-P10 | D-13's setattr-tear is **already fixed**; only the `validate()`/`_run_init()` tear remains |
| `_replaying_backfill` instance bool | `threading.local` per-thread guard (WR-04) | P7 | Warmup is reachable from the engine thread — relevant to D-10's `add`-driven `spawn_warmup` |

**Deprecated/outdated in the CONTEXT itself** (corrections, flagged above):
- "`universe/` is tabs" → **`universe_handler.py` is 4-space** (measured).
- Migration chain ends at `strategy_registry` → **head is `system_stats`** (measured).
- D-03 policy list omits **`PercentFromDecision`** (`sizing.py:278`), a `SLTPPolicy` union member.

## Project Constraints (from CLAUDE.md)

| Directive | P10 compliance requirement |
|---|---|
| Money is `Decimal` end-to-end; enter via `to_money`/`Decimal(str)`, never `Decimal(float)` | **D-03's codec IS a money boundary.** Every policy `Decimal` field serializes to a **string** and re-enters via `Decimal(str)`. JSON has no Decimal — a naive `json.dumps` of a Decimal raises; a `float()` cast is a **correctness defect**. |
| Queue-only cross-domain communication | Rehydrate runs at composition time (not a handler), so it may call `strategies_handler.add_strategy` directly — same as every existing composition-time registration. Verb handling stays inside `on_strategy_command`. |
| Single UUIDv7 scheme via `idgen` | D-02: `strategy_id` stays ephemeral per-construction. **Do not** add a second durable id. |
| `mypy --strict` clean on new code | New `core/policy_codec.py` and `strategy_handler/registry/` are **not** in the `ignore_errors` overrides → strict applies. Note `live_trading_system.py` **is** under `ignore_errors` — dead code there passes silently (known blindspot; sweep imports by review). |
| `filterwarnings = ["error"]`, `--strict-markers` | Any new marker must be declared; any warning fails. |
| Indentation: match the file, never normalize | See `## Indentation Map` — measured per file. |
| Events are `msgspec.Struct` | D-08's optional `config: dict \| None` field follows Struct rules (defaults must follow non-defaults ordering). |
| No autoformatter; mypy is the only static gate | Match surrounding style by hand. |
| Test root is `tests/`; conftest auto-applies type marker from folder | New tests land in `tests/unit/strategy/`, `tests/unit/storage/`, `tests/integration/`. |
| Zero new dependencies in v1.8 | Confirmed achievable — P10 needs none. |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python | all | ✓ | 3.13 | — |
| Poetry / `.venv` | test execution | ✓ | in-project | — |
| `sqlalchemy` | store + migration | ✓ | ^2.0.50 | — |
| `alembic` | D-06 migration | ✓ | on spine | — |
| `msgspec` | D-08 event field | ✓ | in-tree | — |
| SQLite | store unit/integration tests | ✓ | stdlib | — |
| PostgreSQL (live) | production live store | ✗ (not required for P10 tests) | — | **SQLite** — the store is dialect-portable by design (`json_variant()`, `UtcIsoText`, `PRAGMA foreign_keys=ON` hook); the existing `tests/unit/storage/test_strategy_registry_store.py` runs on SQLite |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** PostgreSQL → SQLite for all P10 tests (existing precedent).

> **Test-environment gotchas (from prior milestones, still live):**
> - `make test` aborts in worktrees on a missing `.env`; use `poetry run pytest tests` there.
> - `make test` exports `ITRADER_DISABLE_LOGS=true`, which breaks `caplog` warn-assertions — relevant
>   because **D-19's quarantine test will assert on the CRITICAL alert path.** Assert against the
>   injected `alert_sink` (a test double), **not** `caplog`, to stay green under both runners.
> - Do not add `__init__.py` to `tests/unit/<x>` dirs (package collision).

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest ^8.4.2 (+ pytest-cov ^7.1.0) |
| Config file | `pyproject.toml::[tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/strategy tests/unit/storage -x -q` |
| Full suite command | `poetry run pytest tests -q` |
| Marker axis | TYPE (`unit`/`integration`/`e2e`) auto-applied by `tests/conftest.py` from folder; PURPOSE (`smoke`/`live`) hand-applied |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| STRAT-01 | `list_active × catalog × codec` → registered instances at construction | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -x` | ❌ Wave 0 |
| STRAT-01 | Full restart lifecycle: seed rows → build → rehydrate → same instance resumes | integration | `poetry run pytest tests/integration/test_strategy_registry_restart.py -x` | ❌ Wave 0 |
| STRAT-01 | D-21 empty registry → boots, zero strategies, no error | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -k empty -x` | ❌ Wave 0 |
| STRAT-01 | D-19 quarantine: unknown `strategy_type` → skip + CRITICAL via `alert_sink`, healthy siblings load, **row NOT mutated** | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -k quarantine -x` | ❌ Wave 0 |
| STRAT-01 | D-19 infrastructure: catalog not injected → **fail loud** | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -k no_catalog -x` | ❌ Wave 0 |
| STRAT-01 | D-06 schema: `strategy_portfolio_subscriptions` CRUD + FK delete order | unit | `poetry run pytest tests/unit/storage/test_strategy_registry_store.py -x` | ✅ (extend) |
| STRAT-01 | Migration up/down against head `system_stats` | integration | `poetry run pytest tests/integration/storage/test_migrations.py -x` | ✅ (extend) |
| STRAT-01 | D-03 codec round-trip: **all 6** policies incl. `PercentFromDecision` + `trail_type` enum-in-union | unit | `poetry run pytest tests/unit/core/test_policy_codec.py -x` | ❌ Wave 0 |
| STRAT-01 | D-03 money boundary: Decimals round-trip **as strings**; no float ever appears | unit | `poetry run pytest tests/unit/core/test_policy_codec.py -k decimal -x` | ❌ Wave 0 |
| STRAT-01 | Round-trip loss-free for **each shipped strategy** (`cls(**decode(encode(s))) == s` on declared surface) | unit | `poetry run pytest tests/unit/strategy/test_config_roundtrip.py -x` | ❌ Wave 0 |
| STRAT-02 | Each verb (`add`/`remove`/`enable`/`disable`/`subscribe_portfolio`/`unsubscribe_portfolio`) applies **and persists** | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -x` | ❌ Wave 0 |
| STRAT-02 | D-02 duplicate-name loud reject | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k duplicate -x` | ❌ Wave 0 |
| STRAT-02 | D-10 unknown `strategy_type` loud reject | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k unknown_type -x` | ❌ Wave 0 |
| STRAT-02 | D-07 `disable` → no new entries, indicators stay **WARM**, `enable` trades next bar with no re-warm | unit | `poetry run pytest tests/unit/strategy/test_is_active_gate.py -x` | ❌ Wave 0 |
| STRAT-02 | D-09 `add_ticker`/`remove_ticker` now **also persist `config_json`** | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k ticker -x` | ❌ Wave 0 |
| STRAT-02 | D-10 `add` on a COLD symbol → dark → `BarsLoaded` → ready → trades | integration | `poetry run pytest tests/integration/test_strategy_add_warmup.py -x` | ❌ Wave 0 |
| STRAT-02 | D-11 `remove` force-flats before dropping; sub rows deleted | integration | `poetry run pytest tests/integration/test_strategy_remove_flat.py -x` | ❌ Wave 0 |
| STRAT-03 | D-13 ordering: bad config → **live untouched** (not torn); persist-fail → reject | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -x` | ❌ Wave 0 |
| STRAT-03 | D-12 reconfigure KEEPS open positions | integration | `poetry run pytest tests/integration/test_reconfigure_positions.py -x` | ❌ Wave 0 |
| STRAT-03 | D-14 window grew → dark+re-warm; shrank/unchanged → stays warm | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -k warm -x` | ❌ Wave 0 |
| STRAT-03 | D-15 allowlist: `strategy_type` immutable; `tickers` via verbs only; finer-than-base **rejected** | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_allowlist.py -x` | ❌ Wave 0 |
| STRAT-03 | **F-1**: coarser-timeframe reconfigure actually warms (or is loud-rejected — see F-1 options) | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_allowlist.py -k timeframe -x` | ❌ Wave 0 |
| STRAT-03 | P-4: partial reconfigure merges; persisted `config_json` = post-merge FULL set | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -k merge -x` | ❌ Wave 0 |
| STRAT-03 | D-17 pair reconfigure refused (loud, documented no-op) | unit | `poetry run pytest tests/unit/strategy/test_pair_dispatch.py -k reconfigure -x` | ✅ (extend) |
| D-22 | External path: `add_event(StrategyCommandEvent.add(...))` → full lifecycle → **restart** → resumes | integration | `poetry run pytest tests/integration/test_strategy_external_add_lifecycle.py -x` | ❌ Wave 0 |
| **GATE** | Backtest oracle byte-exact `134 / 46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ |
| **GATE** | Import inertness (codec in `core/` + catalog seam stay SQL/ccxt-free; store import lazy) | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ |

### Sampling Rate

- **Per task commit:** `poetry run pytest tests/unit/strategy tests/unit/storage tests/unit/core -x -q`
- **Per wave merge:** `poetry run pytest tests/unit tests/integration -q`
- **Per plan touching `calculate_signals` (D-07):** `poetry run pytest tests/integration/test_backtest_oracle.py -x` — **mandatory**, the CONTEXT pins this as a per-plan gate
- **Per plan touching `core/` or the catalog seam:** `poetry run pytest tests/integration/test_okx_inertness.py -x` — **mandatory**
- **Phase gate:** full suite green (`poetry run pytest tests -q`) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/core/test_policy_codec.py` — covers STRAT-01 (D-03 codec, all 6 policies, money boundary)
- [ ] `tests/unit/strategy/test_rehydrate.py` — covers STRAT-01 (D-01/D-19/D-21)
- [ ] `tests/unit/strategy/test_config_roundtrip.py` — covers STRAT-01 (D-04 round-trip per shipped strategy)
- [ ] `tests/unit/strategy/test_strategy_command_verbs.py` — covers STRAT-02 (D-09/D-02/D-10)
- [ ] `tests/unit/strategy/test_is_active_gate.py` — covers STRAT-02 (D-07)
- [ ] `tests/unit/strategy/test_reconfigure_atomic.py` — covers STRAT-03 (D-13/D-14/P-4)
- [ ] `tests/unit/strategy/test_reconfigure_allowlist.py` — covers STRAT-03 (D-15, F-1)
- [ ] `tests/integration/test_strategy_registry_restart.py` — covers STRAT-01
- [ ] `tests/integration/test_strategy_add_warmup.py` — covers STRAT-02 (D-10)
- [ ] `tests/integration/test_strategy_remove_flat.py` — covers STRAT-02 (D-11)
- [ ] `tests/integration/test_reconfigure_positions.py` — covers STRAT-03 (D-12)
- [ ] `tests/integration/test_strategy_external_add_lifecycle.py` — covers D-22 (the FastAPI stand-in)
- [ ] Shared fixture: a **test strategy catalog** + a seeded `strategy_registry` fixture. Recommend `tests/support/` (matches `tests/support/replay_harness.py` precedent), **not** a `conftest.py` in a package-less unit dir.
- Framework install: **none needed** — pytest is present.

## Security Domain

`security_enforcement` is not disabled, so this section applies. P10's surface is a durable store fed by
an **external ingress** (`add_event`, the FastAPI stand-in), which makes V5 the dominant category.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | No auth surface in P10; the FastAPI layer (LR-01) owns it, deferred |
| V3 Session Management | no | No sessions |
| V4 Access Control | **partial** | `add_event`'s D-10 fail-closed allowlist (`live_trading_system.py:57`) is the default-deny gate; P10 adds no new ingress |
| V5 Input Validation | **yes** | `_apply_params` + `_COERCE` (`base.py:138`, `:214`) — loud-rejects unknown/missing params; codec must not weaken it. `__post_init__` re-validates every policy on decode (D-03) |
| V6 Cryptography | no | No crypto in P10; **never hand-roll** |
| V1/V12 (injection) | **yes** | SEC-01 — parameterized SQLAlchemy Core only; the store already complies throughout (`strategy_registry_store.py`) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| SQL injection via `strategy_name` from an external `STRATEGY_COMMAND` | Tampering | Parameterized Core only (SEC-01) — the store already does this; **do not** build any f-string SQL for the new child table |
| **Arbitrary class instantiation via `strategy_type`** | **Elevation of Privilege** | **D-01's catalog IS the control.** `cls = catalog[rec["strategy_type"]]` is a **lookup in an injected allowlist**, never an import-by-name. **Never** add `importlib.import_module(strategy_type)` or `eval` as a "convenience" — that would turn an external payload into arbitrary code execution. This is the single most security-relevant design property of D-01 and must be preserved verbatim. |
| `eval`-based policy reconstruction | Elevation of Privilege | **This is exactly why D-03 exists.** `to_dict`'s `repr()` policies would need `eval` to reconstruct (`base.py:773`). The tagged-union codec is the safe alternative. **Never** `eval(config["sizing_policy"])`. |
| Unknown-param smuggling into a strategy | Tampering | `UnknownParamError` (`base.py:279`) — loud reject; the codec must route through `_apply_params`, not `setattr` |
| Secret leakage into `config_json` / alerts | Information Disclosure | `config_json` holds authoring params only (no credentials). D-19's CRITICAL alert must carry `strategy_name` + error **kind** only — follow the P8 precedent (`live_trading_system.py:1495` comment: "only declared ErrorEvent fields bound; no connector secret leaks, Pitfall 16") |
| Denial of service via unbounded `add` | Denial of Service | Out of scope for P10 (no rate limit); the FastAPI layer owns it. **Note for the deferred todo.** |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | `strategy_registry`/`strategy_subscriptions` tables are **empty in every deployed DB** (the store has no production writer), so D-06's drop needs no data migration | Runtime State Inventory | If a DB has rows, the drop loses data. **Mitigation:** the planner should add a `SELECT count(*)` verification step, or write the migration to be non-destructive on non-empty. Confidence is high (the store is constructed only in tests) but this is a **DB-state claim I cannot verify from source**. |
| A2 | No live test currently seeds `strategy_registry` rows, so construction-time rehydrate is a zero-row no-op everywhere → no existing test changes behaviour | Item 2 | If a test does seed rows, rehydrate could collide with an `add_strategy` on the same name (D-02 loud reject) and fail that test. Verified via `grep -rl StrategyRegistryStore tests/` → only `tests/unit/storage/`. Low risk. |
| A3 | `derive_warmup_depth` uses `strategy.warmup` directly with no timeframe scaling | Pitfall F-1 | I read `register_strategy_warmup` (`cache_registration.py:229-252`) and `cache_capacity` (`feed/base.py:125-132`) but **did not read `derive_warmup_depth`'s body**. If it already scales by timeframe, F-1 is void. **The planner MUST verify `cache_registration.py::derive_warmup_depth` and `derive` before acting on F-1.** This is the one place I am extrapolating across an unread function — flagged explicitly rather than papered over. |
| A4 | The catalog is injected via a new `build_live_system` param or a `SystemSpec` field | Item 2 example | Discretionary per CONTEXT; see OQ-1. No correctness risk, only ergonomics. |

## Open Questions

1. **OQ-1: Where does `build_live_system` receive `strategy_catalog`?** (CONTEXT lists this as Claude's
   discretion.)
   - What we know: `build_live_system(spec, *, status_callback, data_plugins)` (`:1259-1264`). There is
     a precedent for **both** shapes — `data_plugins` is a keyword param, and `spec` is the config-object
     carrier.
   - What's unclear: which the owner prefers for the FastAPI seam.
   - **Recommendation:** a keyword param `strategy_catalog: dict[str, type] | None = None`, mirroring
     `data_plugins`. Rationale: the catalog is an **injected code artifact**, exactly like
     `data_plugins`, not persisted config like `spec`. `None` default keeps every existing caller/test
     working; D-19's infrastructure arm fires only when the registry has rows AND no catalog was
     injected (booting with rows but no catalog is the wiring bug D-19 wants loud).

2. **OQ-2: F-1's scope — fix the depth unit or narrow D-15?** See Pitfall F-1's three options.
   - What we know: D-15's owner decision (timeframe is constrained-mutable) is sound; its *mechanism*
     assumption (plain re-warm suffices) is incomplete.
   - What's unclear: whether the ring-depth fix fits P10's budget.
   - **Recommendation:** surface to the owner during planning. If the answer is "keep P10 tight," take
     option 3 (loud-reject when required depth > ring capacity) — it preserves D-15's intent for the
     common case, fails loud instead of silently dark, and leaves the real fix to the already-planned
     finer-than-base feed-lifecycle todo (which is the natural home for ring-depth work).

3. **OQ-3: `config_version` value/format** (CONTEXT discretion, D-20).
   - **Recommendation:** an integer `"config_version": 1` inside `config_json`. Rationale: integers
     compare trivially, a migration hangs off `if version < N`, and there is no precedent for a semver
     string in a stored blob in this codebase. Keep it inside the blob (not a column) — it describes the
     blob's shape, and D-06 reserves columns for *runtime state* (`enabled`), not blob metadata.

4. **OQ-4: `read_all()`'s fate under D-06.** It currently JOINs `strategy_subscriptions` and returns
   `(venue, symbol, timeframe)` tuples (`strategy_registry_store.py:254-308`).
   - **Recommendation:** rework it to JOIN `strategy_portfolio_subscriptions` and return
     `portfolio_ids: list[...]`. It has the IN-01 deterministic-ordering contract worth preserving. If
     rehydrate uses `list_active()` + a separate portfolio-sub fetch, `read_all` may become the
     read-model/UI query — the planner should decide whether it survives or is replaced.

5. **OQ-5: Does the D-19 quarantine list belong on `state.last_error` or a new field?** (CONTEXT
   discretion.)
   - What we know: RTCFG-06 gives `state.*` (status/halt_reason/last_error/last_started_at) as the UI
     read-model.
   - **Recommendation:** a dedicated `state.quarantined_strategies: list[str]` — `last_error` is
     single-valued and would be overwritten by the next error, losing the quarantine list. A separate
     field survives and is directly renderable by the future UI. Low confidence on owner preference;
     worth a quick confirmation.

## Sources

### Primary (HIGH confidence) — direct source reads in this repo
- `itrader/price_handler/feed/live_bar_feed.py` — `window()` resample (:749-764), `_find_ring` (:786-806), off-grid reject (:262-269), ring creation (:394, :675), `warmup` (:273-301)
- `itrader/price_handler/feed/cache_registration.py` — `register_strategy_warmup` (:229-252)
- `itrader/price_handler/feed/base.py` — `cache_capacity` (:125-132)
- `itrader/strategy_handler/base.py` — `_declared_hints` (:130-133), `_COERCE` (:138-141), class-body annotations (:170-186), `__init__` (:188-212), `_apply_params` (:214-320), `validate` (:325), `_run_init` (:382-406), `reconfigure` (:695-718), `to_dict` (:720-790), `subscribe_portfolio` (:974), `activate_strategy` (:988)
- `itrader/strategy_handler/strategies_handler.py` — `calculate_signals` (:141-175), `add_strategy` (:555-613)
- `itrader/strategy_handler/strategies/` — `SMA_MACD_strategy.py`, `empty_strategy.py`, `eth_btc_pair_strategy.py`
- `itrader/core/sizing.py` — all six policies + the `SizingPolicy` (:205) / `SLTPPolicy` (:301) unions
- `itrader/storage/strategy_registry_store.py` — full read (registrar :48-91, `upsert` :120, `set_subscriptions` :152, `get` :189, `delete` :208, `list_active` :222, `read_all` :254)
- `itrader/trading_system/live_trading_system.py` — allowlist (:56-58), sentinels/D-12 note (:246-255), `_initialize_live_session` (:541-600), `start()` (:681), `_layer_persisted_overrides` (:1145-1257), `build_live_system` (:1259+), P9 gate (:1510-1555)
- `itrader/trading_system/session_initializer.py` — ordering (:104-135)
- `migrations/versions/*.py` — full chain via `grep down_revision`
- `.planning/phases/10-strategies-registry/10-CONTEXT.md`, `.planning/REQUIREMENTS.md` (STRAT-01..03, :268-279)
- `CLAUDE.md` — project constraints

### Secondary (MEDIUM confidence)
- `tests/` grep survey (30 files with `add_strategy`; 3 files monkeypatching `_initialize_live_session`) — sampled, not exhaustively read

### Tertiary (LOW confidence)
- None. **No external sources were used** — P10 is entirely internal-brownfield with zero new
  dependencies, so no web/registry/Context7 lookup was warranted.

## Metadata

**Confidence breakdown:**
- **Research Item 1 (feed timeframe model):** HIGH — resolved by direct read of `window()`/`_find_ring`; the resample mechanism is explicit and documented in-source
- **Research Item 2 (rehydrate call site):** HIGH — resolved by reading the composition root, session initializer, and the three monkeypatching tests; the ordering constraint is enforced by two concrete call sites (`wire_universe`, `register_strategy_warmup`)
- **Research Item 3 (round-trip + `_DERIVED_FIELDS`):** HIGH — verified against all three shipped strategies and all six policies; the aliasing traps are corroborated by `to_dict`'s existing handling
- **Standard stack:** HIGH — zero new dependencies; everything verified present in `pyproject.toml`
- **Architecture patterns:** HIGH — the P9 template is read verbatim from source
- **Pitfall F-1:** MEDIUM-HIGH — the mechanism is verified across five files, but `derive_warmup_depth`'s body is **unread** (see A3). **The planner must verify it.**
- **Pitfall F-2, F-3, P-4..P-6:** HIGH — direct source reads
- **Runtime state / migration chain:** HIGH on the chain (measured); MEDIUM on table-emptiness (see A1 — a DB-state claim unverifiable from source)
- **Validation architecture:** HIGH — framework and commands verified against `pyproject.toml` and `Makefile`

**Research date:** 2026-07-17
**Valid until:** 2026-08-16 (30 days — internal brownfield, no fast-moving external deps; invalidated early only by edits to `base.py`, `live_bar_feed.py`, `cache_registration.py`, or the migration chain)
