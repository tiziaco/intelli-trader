# Phase 1: Config Centralization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 1-Config Centralization
**Areas discussed:** Config immutability, Constant-fold scope, `extra` policy, HaltReason vocabulary, Lazy `sql` accessor, `runtime` eager placement, SystemConfig aggregation (order/templates cardinality), `__pycache__` handling

---

## Config immutability

| Option | Description | Selected |
|--------|-------------|----------|
| Mutable-by-convention | Rely on P9 RuntimeConfig overlay + snapshot-read; freezable later | ✓ |
| Freeze in P1 | ConfigDict(frozen=True) now; breaks in-place mutators | |
| Freeze eager, defer nested | Freeze top-level only; leave templates mutable | |

**User's choice:** Mutable-by-convention (recommended)
**Notes:** P1 is oracle-gated centralization; freezing has blast radius. "Immutable" enforced by P9 overlay being the mutation path, not a frozen model.

---

## Constant-fold scope

| Option | Description | Selected |
|--------|-------------|----------|
| Define + rewire, defer StreamSupervisor | Config blocks + rewire direct readers now; shared supervisor is P5 | ✓ |
| Define + rewire all now | Also build the shared supervisor path this phase | |
| Define blocks only | Add models; leave consumers on old constants until P5 | |

**User's choice:** Define + rewire, defer StreamSupervisor (recommended)
**Notes:** Goldilocks — CFG-03 grep-clean met (constants gone from source) without inventing P5's StreamSupervisor early.

---

## `extra` policy normalization

| Option | Description | Selected |
|--------|-------------|----------|
| Decide during audit | Empirical: forbid-if-YAML-clean, else keep ignore; env models stay ignore | ✓ |
| Forbid everywhere (except env) | Pin SystemConfig to forbid now, before auditing settings/ | |
| Keep SystemConfig lenient | Leave ignore; document the split rather than unify | |

**User's choice:** Decide during audit (recommended)
**Notes:** SystemConfig is the lone `extra="ignore"` among `forbid` siblings. Resolve by evidence from the dead-config audit rather than pre-committing.

---

## HaltReason vocabulary

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal — replace live strings | Only reasons raised in code today; P8 extends | ✓ |
| Comprehensive — anticipate P7/P8 | Full anticipated vocabulary now | |

**User's choice:** Minimal — replace live strings (recommended)
**Notes:** YAGNI. P1 owns the enum in `core/enums/system.py`; P8's SafetyController owns `halt()` and knows the real vocabulary. Comprehensive-now risks dead members.

---

## Lazy `sql` accessor

| Option | Description | Selected |
|--------|-------------|----------|
| @cached_property, raise-on-access | Resolve on first access, raise uncredentialed, never at import | ✓ |
| Explicit get_sql() method | Plain method + internal cache; sidesteps pydantic quirk | |
| You decide | Lock contract only | |

**User's choice:** @cached_property, raise-on-access (recommended)
**Notes:** Inertness-critical seam. Contract locked; researcher verifies the pydantic-v2 + cached_property idiom.

---

## `runtime` (Settings) eager placement

| Option | Description | Selected |
|--------|-------------|----------|
| Eager — env-read is safe | Keep runtime eager; only SqlSettings is the inertness risk | ✓ |
| Lazy too | Give runtime the same lazy treatment | |

**User's choice:** Eager — env-read is safe (recommended)
**Notes:** Constructing Settings reads env but does not construct the Postgres SqlSettings; inertness gate asserts no SqlSettings, not no env-read.

---

## SystemConfig aggregation — order & per-instance templates (cardinality)

| Option | Description | Selected |
|--------|-------------|----------|
| Templates on SystemConfig (per spec §6a) | Park PortfolioConfig/ExchangeConfig default templates on SystemConfig | |
| `order` as SystemConfig singleton (per spec §6b / CFG-01) | Aggregate order alongside performance/monitoring/runtime/sql | |
| Cardinality rule — singletons only, no templates, order kept out | SystemConfig = performance/monitoring/runtime/sql; order + per-instance configs live with their owner via `.default()` | ✓ |

**User's choice:** Owner override — no per-instance templates on SystemConfig; `order` reclassified cardinality-N and kept out.
**Notes:** Owner pushed back on parking per-instance config in the system singleton ("i don't want the default module config in system config"). Established the cardinality rule: on SystemConfig only if exactly one owner at runtime. `order` may diverge per-portfolio/per-venue in the near future → cardinality-N, kept out, owned by OrderHandler via `OrderConfig.default()`. This supersedes spec §6a/§6b AND the original CFG-01/SC#2 text; CFG-01 was reworded in REQUIREMENTS.md to match (owner amendment 2026-07-09). Downstream must not reintroduce `order`/templates onto SystemConfig.

---

## `__pycache__` / stale-file handling

| Option | Description | Selected |
|--------|-------------|----------|
| Verify .gitignore + rm tracked stragglers | Confirm coverage; git-rm any committed cache | ✓ (default) |
| Just assert gitignored | Only verify coverage | |

**User's choice:** Default accepted (verify + rm stragglers).
**Notes:** Mechanical, low-risk.

## Claude's Discretion

- Exact `StreamSettings`/`ConnectionSettings` field layout and their location in `config/`.
- Exact feed/provider field names for folded `_WARMUP_MARGIN` / `_BACKFILL_PAGE`.
- The precise pydantic-v2 `@cached_property` idiom for the lazy `sql` accessor (contract locked).

## Deferred Ideas

- Shared `StreamSupervisor` consolidation → P5.
- `RuntimeConfig` overlay + runtime mutation platform → P9 (RTCFG-01..06).
- Per-portfolio / per-venue `order` config divergence → future (justifies `order` cardinality-N now).
- Freezing `SystemConfig` → reconsider if P9 wants a hard runtime guarantee.
