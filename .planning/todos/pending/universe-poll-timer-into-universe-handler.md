---
status: scheduled
created: "2026-08-01"
source: brainstorming session 2026-08-01 (domain-owned runtime config design) — the poll-timer ownership question that forced `poll_cadence_s` out of the editable config surface
tags: [live, universe, worker-supervisor, threading, lifecycle, runtime-config, follow-up, next-milestone]
---

# Move the universe poll timer into `UniverseHandler` (delete `WorkerSupervisor`)

**Origin:** Brainstorming session 2026-08-01 that produced
[[docs/superpowers/specs/2026-08-01-domain-owned-runtime-config-design]]. That design makes each
handler own, persist and apply its own runtime config. `universe` was the one scope that would not
fit the shape, and the reason turned out to be **who owns the poll timer** — so the config design
deliberately left `poll_cadence_s` construction-time and deferred the timer question here.

## The problem this fixes

`WorkerSupervisor` (`itrader/trading_system/worker_supervisor.py`) captures the cadence as a
**float at construction** (`__init__` param `cadence: float`, read in the loop at `:62` via
`build.py:400`). Nothing can refresh it, so `config.universe.poll_cadence_s` is editable in name
only.

Every fix that keeps the timer outside the handler makes things worse, not better:

- Pass `WorkerSupervisor` the `UniverseConfig` model → a scheduling primitive depends on a
  two-field domain model it doesn't use (Interface Segregation), **and**
- either that or a `Callable[[], float]` forces `UniverseHandler` to abandon the atomic swap for
  **field-wise mutation on a shared instance**, because the supervisor holds a reference the swap
  would strand. That makes `universe` the only scope in the config design with a different
  mutation model and a cross-thread config read.

Both were considered and rejected in the spec. Note also that Nautilus Trader and LEAN don't make
timer intervals runtime-mutable at all — an interval is a registration parameter, changed by
cancel + re-register.

## Why moving it in dissolves the problem

A timer owned by the handler reads `self._config.poll_cadence_s`, **dereferencing through the
owner on every tick**. So the atomic swap keeps working, and `poll_cadence_s` becomes editable by
adding one field to `UniverseConfig`'s editable surface — no design change to the config work.

`WorkerSupervisor` is then **deleted, not slimmed**: the poll timer is all it does
(`_run_poll_timer`, `UniversePollEvent`, the thread named
`WorkerSupervisor-UniversePollTimer`).

## Constraints this must not break

1. **The bus round-trip survives.** The timer thread must keep putting a `UniversePollEvent` on
   the bus; it must NOT call `on_poll` directly. The poll is actuated on the **engine thread** —
   that is the single-writer contract, and a direct call from a timer thread breaks it.
2. **Lifecycle moves.** `LiveRunner` composes `WorkerSupervisor` today and drives start/stop off
   the shared `stop_event`. `UniverseHandler` is only built in `SessionInitializer` during
   `start()`, so something must start its timer after session init and stop it on shutdown. The
   handler's thread should keep honouring the **same** `stop_event`, so `stop()` unblocks the
   sleep immediately instead of waiting out a full cadence.
3. **A domain handler owning a daemon thread is new here.** Handlers are engine-thread event
   consumers today; this makes one a producer with its own lifecycle. Defensible —
   `UniverseHandler` is live-only and the sole consumer of the poll — but it is the real tradeoff
   to weigh, not a free win.

## Follow-on once this lands

Add `poll_cadence_s` to `UniverseConfig`'s editable surface (the `UniverseConfigEvent` consumer
needs no other change) and drop the "No change to `WorkerSupervisor`" non-goal from the config
spec.

## Tie-in / related

- **Depends on:** [[docs/superpowers/specs/2026-08-01-domain-owned-runtime-config-design]] —
  `UniverseHandler` must already hold `UniverseConfig` (that spec deletes
  `UniverseHandlerConfig`) for the swap-through-owner mechanism to apply.
- **Touches:** `worker_supervisor.py` (deleted), `universe/universe_handler.py`,
  `trading_system/live/build.py` (the `WorkerSupervisor` construction at `:399-400`),
  `LiveRunner` composition and the `stop_event` latch, `SessionInitializer`.
- **Adjacent cleanup, same ctor:** `universe_handler.py:447` does `from itrader import config`
  inside a method body to read `config.feed_provider.warmup_margin` — a lazy import in a
  constructor-injection codebase. Cheap to fix while the constructor is open.
