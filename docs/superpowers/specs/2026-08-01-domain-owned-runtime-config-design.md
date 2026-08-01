# Domain-Owned Runtime Config

**Date:** 2026-08-01
**Status:** Design approved, not implemented
**Scope:** Live path only. The backtest path is untouched and must stay byte-exact
(oracle 134 trades / `46189.87730727451`).

## Problem

Runtime config editing is currently split across a central `ConfigRouter`
(`itrader/trading_system/config_router.py`, 442 lines) and a duplicate validation ladder on
the live facade (`LiveTradingSystem._validate_config_ingress` / `_dry_validate_config_ingress`,
`live/system.py:744` and `:814`). Both re-derive the same `(scope, key)` allowlist, and
`bootstrap._layer_persisted_config` re-derives it a third time.

Three copies of one allowlist, already drifted:

| | `ConfigRouter` | `bootstrap` | facade ingress |
|---|---|---|---|
| system/universe keys | `config_router.py:213-220` | `bootstrap.py:214,218` | `system.py:770-773` |
| order keys | `:241` | `:231` | `:781` |
| venue keys | `_VENUE_KEYS` — 3 keys, `:70` | inline — **2 keys**, `:257` | inline — 3 keys, `:789` |
| immutable portfolio keys | `:329` | (via `Portfolio.update_config`) | **absent** |

Two consequences visible today:

1. The facade does not know about `IMMUTABLE_PORTFOLIO_CONFIG_KEYS`, so `add_event` returns
   `True` for an `enable_margin` edit that the engine is guaranteed to refuse.
2. A rejection on the engine thread surfaces only as a *deduped* WARNING `ErrorEvent`
   (`config_router.py:425`, throttled at 5s), so the caller that got `True` has no way to
   learn the edit never applied.

### The deeper finding

The two scopes that no handler owns are exactly the two scopes that do not work.

- **`system`** — `SystemSettings` has four fields (`enable_auto_restart`,
  `auto_restart_delay_seconds`, `enable_graceful_shutdown`, `shutdown_timeout_seconds`).
  A grep across `itrader/` finds **zero readers** for all four. The scope is validated,
  persisted, routed, and controls nothing.
- **`universe`** — both keys are snapshotted at construction, never read live:
  `poll_cadence_s` → `WorkerSupervisor._cadence` (`build.py:400` → `worker_supervisor.py:46`);
  `remove_policy` → `UniverseHandlerConfig` → `UniverseHandler._remove_policy`
  (`live/system.py:444` → `universe_handler.py:218`). `ConfigRouter._apply_system` justifies
  having no push step by claiming these are read live off the mutable config object. That
  claim is false — an edit validates, persists, mutates `config.universe`, reports success,
  and never reaches the running engine.

This is structural, not accidental. A central router can persist on a domain's behalf, but it
cannot know what the domain cached at construction. **An owner that holds the store also holds
the field it must refresh.**

### The venue scope was never about a live venue

- `ExecutionHandler.update_config` hardcodes its target as `(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)`
  and raises unless it is a `SimulatedExchange` (`execution_handler.py:129-133`);
  `COMPUTE_VENUE = 'paper'` (`:34`).
- `ConfigRouter._apply_venue` independently rejects fee/slippage for a live venue via
  `_venue_is_simulated` — *"real-venue fees come from actual fills, not engine config"*
  (`config_router.py:262-264`).
- `VenueStore.enabled` is written but never read: `list_enabled` has zero callers, and the
  store's only reader (`bootstrap.py:245`) extracts `{fee_model, slippage_model}` only (`:257`).
- `VenueStore`'s only writer is `config_router.py:301`.

A real venue's fees come from fills and its slippage is not modelled at all. For the paper
exchange, changing fee or slippage mid-run makes the run's PnL incoherent — that is
construction-time config, which `ExchangeConfig.default()` / `.high_fee()` already are.
The runtime venue-disable knob that *is* wanted already exists elsewhere:
`VenueAccountManager.set_enabled` (`accounts.py:891`), writing to `VenueAccountStore`.

## Principle

**A runtime config edit is a domain event addressed to the domain that owns the config.**
The owning handler validates it, persists it to its own store, and applies it to its own
state. No central router, no shared allowlist, no cross-domain store.

This is the pattern `STRATEGY_COMMAND` already follows: `StrategyLifecycleManager` validates
against a trial instance, persists via `registry_store.upsert` (`lifecycle/manager.py:729`),
then applies (`:741`). The strategy domain needs no router because it owns its own store.

It is consistent with decision D-08 on `StrategyCommandEvent`, which rejects separate typed
events per *command family within one domain*. That is a different axis. Applied consistently,
D-08 says: one event per **domain**, discriminator inside. `STRATEGY_COMMAND` is the strategy
domain's event; this design gives the other domains theirs.

## Design

### Ownership map

| Domain | Event | Consumer | Store |
|---|---|---|---|
| order | `OrderConfigEvent` | `OrderHandler.on_config_update` | `order_handler.storage` (already owned) |
| portfolio | `PortfolioConfigEvent` | `PortfolioHandler.on_config_update` | each `Portfolio.state_storage` (already owned) |
| universe | `UniverseConfigEvent` | `UniverseHandler.on_config_update` | **new** `UniverseStore` |
| strategy | `StrategyCommandEvent` | `StrategiesHandler.on_strategy_command` | `strategy_registry_store` (unchanged) |

Two of the three new consumers need no new dependency — they already hold their store.

### Events

Three new CONTROL-tier events, each in its domain's `events/*.py`, each with factory
classmethods per the `FillEvent.new_fill` house convention.

```python
class OrderConfigEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.ORDER_CONFIG
    updates: dict[str, Any]

class PortfolioConfigEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.PORTFOLIO_CONFIG
    portfolio_id: PortfolioId
    updates: dict[str, Any]

class UniverseConfigEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.UNIVERSE_CONFIG
    updates: dict[str, Any]
```

`updates` carries **merge, not replace** semantics: a field omitted from the delta keeps its
prior value. This matches every existing `update_config(updates: dict[str, Any])` signature and
`StrategyCommandEvent.reconfigure`'s documented contract. Each factory classmethod docstring
must state it, because that is where a caller reasons about payload shape.

`PortfolioConfigEvent` carries a typed `PortfolioId`, which eliminates the
`portfolio:{uuid}` scope string, its prefix match (`config_router.py:177`) and its re-parse
(`:333`).

The `(scope, key, value)` triple disappears. It was a lowest-common-denominator shape that fit
no domain, which is why `ConfigRouter` spent its body translating it back into the dict every
handler already accepts (`config_router.py:342-345`).

### Consumer contract

Uniform across all three: **validate → persist → apply**, persist-first, loud no-op on a bad
payload. A consumer never raises into the queue — same contract as
`StrategiesHandler.on_strategy_command` (`strategies_handler.py:499-500`).

```python
def on_config_update(self, event: UniverseConfigEvent) -> None:
    try:
        merged = UniverseConfig.model_validate(
            recursive_merge(self._config.model_dump(), event.updates))
    except pydantic.ValidationError as exc:
        self.logger.warning('Universe config refused: %s', exc)
        return
    self._store.save_config(merged.model_dump(mode='json'), event.time)
    self._apply(merged)
```

`OrderManager` and `Portfolio` already hold their Pydantic model (`order_config`, `config`) and
can validate a merge directly. `UniverseHandler` does not — it holds a dataclass snapshot — so
it needs the change described under "Making `universe` genuinely live" below.

Unknown keys are rejected by `extra="forbid"` on each Pydantic model. There is no
hand-maintained allowlist anywhere in the design — the model *is* the allowlist, and it cannot
drift from itself.

`Portfolio.update_config` keeps its `IMMUTABLE_PORTFOLIO_CONFIG_KEYS` guard
(`portfolio.py:306`); with `ConfigRouter` gone it becomes the single refusal layer rather than
one of two, so its docstring's "duplicates a refusal `ConfigRouter` already makes" note must be
corrected.

Persist-first matches the strategy precedent and its rationale: the durable row holds operator
intent and a restart heals a failed apply. An apply failure after a successful persist is
logged, not rolled back.

### Making `universe` genuinely live

The only scope with real work behind it rather than plumbing. It is also the only config with
**two** collaborators reading it — `UniverseHandler` and `WorkerSupervisor` — which is what
makes it different from `order` and `portfolio`.

Today each reader takes its own snapshot at construction and nothing refreshes them:

```
config.universe.poll_cadence_s      ─(build.py:400, a float)─▶ WorkerSupervisor._cadence   → :62
config.universe.remove_policy       ─(system.py:444)─▶ UniverseHandlerConfig ─▶ _remove_policy → :565
config.stream.okx_stream_timeframe  ─(system.py:443)─▶ UniverseHandlerConfig ─▶ _timeframe     → :347,449,452
```

After: **one object, read live by both readers, written by one owner.**

```
config.universe : UniverseConfig ──┬──▶ WorkerSupervisor._config.poll_cadence_s  (read each tick, :62)
      ▲                            └──▶ UniverseHandler._config.remove_policy / .poll_timeframe
      │ setattr, field-wise
  UniverseHandler.on_config_update  (sole writer)
```

This works because `config.universe` is a MUTABLE Pydantic sub-model with
`validate_assignment=True`, mounted on the frozen root and mutated field-wise, never reassigned
(`itrader_config.py:78-86`).

1. **`poll_timeframe` does NOT move and does NOT become editable.** It is sourced from
   `config.stream.okx_stream_timeframe` (`live/system.py:443`), which has two other readers:
   `okx_provider.py:721` — the timeframe the venue stream actually subscribes to — and
   `live/system.py:552`. Making the universe copy independently editable would let the warmup
   timeframe drift from the subscribed timeframe (warm 1d bars, stream 1h), with nothing
   detecting it; `tests/support/replay_harness.py:344` already carries a comment about that
   hazard. It stays a construction-time snapshot, and `UniverseConfig`'s editable surface stays
   `poll_cadence_s` + `remove_policy`.
2. **`UniverseHandlerConfig` is deleted** (`universe_handler.py:64-79`), replaced by two ctor
   params with honestly different lifecycles: `config: UniverseConfig` (owned, live, editable)
   and `poll_timeframe: str` (a construction snapshot that must match the stream). The handler
   keeps the REFERENCE (`self._config = config`) instead of unpacking (`:217-218`), so
   `self._remove_policy` (`:565`) becomes `self._config.remove_policy`. `self._timeframe`
   (`:347`, `:449`, `:452`) stays exactly as it is. This is still constructor injection of a
   domain model, so the handler stays off the config root — the decoupling
   `UniverseHandlerConfig` existed for is preserved.
3. **`WorkerSupervisor` takes the model, not a float.** `cadence: float`
   (`worker_supervisor.py:41`) becomes `universe_config: UniverseConfig`, and `:62` becomes
   `self._stop_event.wait(self._config.poll_cadence_s)`. `build.py:400` passes `config.universe`
   instead of `config.universe.poll_cadence_s`. A `Callable[[], float]` was considered and
   rejected: it closes over the same object for the same effect, with a lambda in between.
4. **The consumer mutates field-wise**, not by swapping:

```python
def on_config_update(self, event: UniverseConfigEvent) -> None:
    try:
        merged = UniverseConfig.model_validate(
            recursive_merge(self._config.model_dump(), event.updates))
    except pydantic.ValidationError as exc:
        self.logger.warning('Universe config refused: %s', exc)
        return
    self._store.save_config(merged.model_dump(mode='json'), event.time)
    for field in event.updates:
        setattr(self._config, field, getattr(merged, field))
```

Field-wise mutation is REQUIRED here, not stylistic: `ITraderConfig` is frozen so
`config.universe` cannot be reassigned, and both collaborators hold a reference to the
INSTANCE — an atomic swap would leave them pointing at the old object. This is the mutation
model `validate_assignment=True` exists for.

It differs deliberately from `order` and `portfolio`, which DO atomic-swap
(`self.order_config = new_config`, `self.config = new_config`). That is correct for them: each
is the sole reader of its own model. Do not "unify" the two — the difference tracks a real
difference in ownership.

**Thread-safety.** The poll thread reads `poll_cadence_s` while the engine thread writes it. A
single attribute read/write is atomic under the GIL, so no torn read is possible; worst case the
timer sleeps one more interval at the old cadence before picking up the new one. This is the one
place in the design where a config field is read off the engine thread, and it is why the
supervisor reads a plain field rather than calling into the handler.

### `UniverseStore`

New store in `itrader/storage/universe_store.py`, following the `order_config` singleton
template (`order_handler/storage/sql_storage.py:544`): one row under a constant id, JSON
`config_json` blob, delete-then-insert in a single `engine.begin()`, caller-supplied `at`,
parameterized Core only, schema-pure with a `build_universe_store_table` registrar consumed by
both the test-path `create_all` and `migrations/env.py`. Alembic migration required.

`SystemStore` loses its config tenancy and becomes a pure system-*state* store, which is what
its other three uses already are: `state.last_started_at` (`live/system.py:504`),
`state.last_error` (`error_handler.py:145`), and the safety controller's halt record
(`safety_controller.py:415`).

### Routing and ingress

Three route slots in `LiveRouteRegistrar.install`, each pointing straight at the owning
handler. Unlike `STREAM_STATE` / `CONNECTOR_FATAL`, no private consumer method on the registrar
is needed, because each event has exactly one owner and no branch.

```python
routes[EventType.ORDER_CONFIG]     = [self._order_handler.on_config_update]
routes[EventType.PORTFOLIO_CONFIG] = [self._portfolio_handler.on_config_update]
routes[EventType.UNIVERSE_CONFIG]  = [self._universe_handler.on_config_update]
```

The registrar gains references to `OrderHandler` and `PortfolioHandler` (it holds only
`StrategiesHandler` and `UniverseHandler` today, `route_registrar.py:56-57`).

Dispatch is the route table — the codebase's one documented dispatch mechanism. Default-deny
comes free at two levels: `EventHandler._dispatch` raises `NotImplementedError` on an unrouted
type, and `extra="forbid"` rejects an unknown key within a domain.

Add the three to `_EXTERNALLY_ADMISSIBLE` (`live/system.py`) and to `_CONTROL_EVENT_TYPES`
(`bus.py:48`) so they keep CONTROL-tier dequeue priority. `add_event` performs **no**
config-specific validation — the same contract `STRATEGY_COMMAND` already has, where `True`
means queued, not applied.

### Restart layering

`bootstrap._layer_persisted_config` keeps its order and portfolio arms, gains a universe arm,
and loses its system arm (`:207-223`) and venue arm (`:244-264`). Each arm reads the store the
owning handler writes, so "what persists" and "what is editable" cannot drift.

The boot ordering contract in `bootstrap_session` is unchanged.

## Deletions

- `itrader/trading_system/config_router.py` (442 lines) and `tests/unit/trading_system/test_config_router.py`
- `ConfigUpdateEvent` (`events/control.py:74`) and `EventType.CONFIG_UPDATE`
- `LiveTradingSystem._validate_config_ingress` + `_dry_validate_config_ingress` (~90 lines),
  plus the now-unused `SystemSettings` / `UniverseConfig` / `OrderConfig` imports at
  `live/system.py:30-32`
- `itrader/storage/venue_store.py`, its table and a drop migration. Its `_assert_no_secret_keys`
  guard is imported by `venue_account_store.py:55` and must be **relocated, not deleted**.
- `ExecutionHandler.update_config` / `validate_config` (`:116`, `:136`) and
  `SimulatedExchange.validate_config` (`:820`). Their only callers are `config_router.py:307`
  / `:285` and `bootstrap.py:260`, all deleted here. **These three are contingent on dropping
  the venue scope, not independent judgements** — if paper fee/slippage ever becomes runtime-
  editable, `ExecutionHandler.update_config` is precisely the push target and comes back.
  `SimulatedExchange.update_config` **stays** regardless — `configure()` delegates to it for
  `AbstractExchange` Protocol conformance (`:769`).
- `PortfolioHandler.update_config` / `validate_config` / `rollback_config` / `get_config` /
  `update_portfolio_config` / `get_portfolio_config` (`:1308-1369`) — a handler-level config API
  with no caller, including two stubs that log a warning and return `False`/`None`.
  `self.config_data` and `self.max_portfolios` **stay**: they are read at `:324` (the
  portfolio-count limit) and `:1285`. Only the mutators and readers go, making `max_portfolios`
  construction-time by decision. A handler-level defaults event was considered and rejected —
  the setting is not worth an event, and `PortfolioHandler` owns no store to persist it to.
- `StrategiesHandler.update_config` (`:612`) — no caller, and duplicated by the more rigorous
  `STRATEGY_COMMAND` reconfigure path.
- The `system` config scope: `SystemSettings`, the `config.system` field on `ITraderConfig`, and
  the `SystemSettings` re-export from the `config/` barrel (`config/__init__.py:36-40`, `__all__`).
  All four fields have zero readers, and an empty sub-model is worse than none. The
  `Environment` and `LogLevel` enums in `config/system.py` **stay** — they are imported by
  `itrader_config.py` and re-exported from the same barrel.

`BacktestBarFeed.update_config` (`bar_feed.py:344`) stays: it is an interface-conformance stub
that fails loudly, and it is on the backtest path.

## Testing

- Per-domain unit tests replace `test_config_router.py`. For each of the three events: a valid
  edit persists and applies; an invalid value is a loud no-op with nothing persisted; an unknown
  key is refused by `extra="forbid"`; a store failure is logged without corrupting live state.
- `Portfolio.update_config`'s immutable-key refusal keeps its existing coverage
  (`tests/unit/portfolio/test_update_config.py`) — it is now the only layer enforcing it.
- `tests/integration/test_config_ingress.py` and `test_config_restart_layering.py` are rewritten
  against the three events.
- A live-apply test for `universe`: after a `UniverseConfigEvent`, `WorkerSupervisor` observes
  the new cadence and `UniverseHandler` the new remove policy. This is the regression that would
  have caught the current silent no-op.
- `tests/integration/test_okx_inertness.py` must stay green — `UniverseStore` is a SQL module
  and must not reach the backtest import graph.
- `tests/integration/test_backtest_oracle.py` must stay byte-exact. All three events are
  live-only and the backtest route table is untouched, so this is a guard, not a risk.
- Migration tests (`tests/integration/storage/test_migrations.py`) cover the `universe_config`
  add and the `venue_config` drop.

## Non-goals

- No new class, no scope table, no dispatch dict, no `precheck` helper. The route table is the
  dispatch.
- No change to how strategy config is edited. `STRATEGY_COMMAND` already implements this design.
- No runtime editing of fee or slippage. It is construction-time config
  (`ExchangeConfig.default()` / `.high_fee()`), and mid-run changes make a run's PnL incoherent.
- No widening of the editable surface. `stream`, `feed_provider` and `safety` remain
  construction-time; adding one later is a new event plus a consumer, in obvious places.
- No config **read** surface. The engine needs none, and the deleted `PortfolioHandler.get_config`
  / `get_portfolio_config` had no caller. A FastAPI layer wanting "show me this portfolio's
  config" is a separate piece of work, and its natural source is each store's `load_config`
  rather than a handler method.
- No change to the backtest path.

## Open items for implementation planning

1. **`UniverseHandlerConfig` has wide test reach.** Eight test modules construct it directly
   (`tests/unit/universe/*`, four `tests/integration/test_strategy_*`, `test_reconfigure_positions.py`,
   `tests/integration/conftest.py:487`). Deleting it is a mechanical two-param change at each
   site, but it is the largest single edit surface in this design and should be its own plan step.
2. **`PortfolioConfigEvent` and an unknown `portfolio_id`.** `get_portfolio` raises
   `PortfolioNotFoundError`; the consumer must catch it and log a loud no-op rather than let it
   reach the error policy.
3. **`VenueStore` drop migration** and the relocation of `_assert_no_secret_keys` into a shared
   home that `venue_account_store.py` can import.
4. **Adjacent, out of scope unless wanted:** `universe_handler.py:447` does
   `from itrader import config` inside a method body to read `config.feed_provider.warmup_margin`
   — a lazy import in a constructor-injection codebase. The ctor is being touched anyway, so
   injecting that value is cheap, but it is a different sub-model and not part of this design.
