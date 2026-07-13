# Phase 5: Venue Registry + Bundle - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 5-Venue Registry + Bundle
**Areas discussed:** Registry & bundle shape, Kill-scope & P5/P6 boundary, Connector memo & creds, StreamSupervisor & provider Protocol

---

## Area 1 — Registry & bundle shape

### Registration mechanism
| Option | Description | Selected |
|--------|-------------|----------|
| Explicit map in factory | Plain `dict[name -> plugin]`, explicit `register("okx", plugin)`; no import side effects; inertness greppable | ✓ |
| Decorator self-registration | `@execution_venue('okx')` registers on import; inverts inertness (registry must import every plugin module) | |
| Entry-points / plugin discovery | `importlib.metadata` entry_points for out-of-tree venues; machinery no consumer needs | |

**User's choice:** Explicit map (Option A).
**Notes:** User asked for a worked example of each + a recommendation. Decision driven by `test_okx_inertness.py` being the P5 acceptance gate — explicit registration makes "register ≠ import concretion" structurally obvious and matches the no-import-side-effects ethos.

### VenueBundle contents
| Option | Description | Selected |
|--------|-------------|----------|
| Execution-only bundle + shared connector cache | Bundle carries exchange + account_factory (+ optional connector/lifecycle); data provider built by separate registry; connector shared via memo | ✓ |
| One combined bundle (exchange + provider + account) | Single plugin builds everything; collapses VENUE-01 independent selection | |
| Bundle owns connector, providers borrow it | Provider reaches into built execution bundle for connector; couples build order | |

**User's choice:** Execution-only bundle (Option 1).
**Notes:** User initially conflated Option 1 with Option 3 ("Bundle owns connector"); clarified via a comparison table — Option 1 uses a standalone memo, Option 3 couples build order. Then questioned why a cache is needed at all → led to the `ConnectorProvider` (Design B) refinement below.

### Connector sharing mechanism
| Option | Description | Selected |
|--------|-------------|----------|
| Plain memo dict (recipe in each plugin) | `dict` dedupes; build lambda duplicated across exec + data plugin | |
| Shared `ConnectorProvider` (single recipe + memo) | Dedicated provider owns per-venue `ConnectorPlugin.build` recipe + `(venue, account_id)` memo + `close_all()` | ✓ |

**User's choice:** Shared `ConnectorProvider` (Design B).
**Notes:** User asked why a cache is needed (vs "initialize once"). Explained the two-independent-builders double-connector failure mode + that "build once at root and inject" reintroduces the `if venue==` branch. User then asked what happens if `OkxConnector` isn't lazily initialized → confirmed the **triple-deferral** (register inert / lazy import + `OkxSettings()` inside `build()` / network `connect()` at `start()`) as the guard for both the inertness gate and cred-less/backtest machines.

---

## Area 2 — Kill-scope & P5/P6 boundary

### Plugin coverage & backtest firewall
| Option | Description | Selected |
|--------|-------------|----------|
| okx + paper live plugins; backtest stays out | Registry is a live-only overlay; backtest uses compose-built `'simulated'` directly | ✓ |
| okx + paper + simulated all plugins (backtest too) | Routes backtest through the registry; puts it on the byte-exact hot path | |
| okx only; leave paper branch as-is | Smaller diff; violates SC3 (`elif=='paper'` must be removed) | |

**User's choice:** okx + paper live plugins; backtest stays out (Option 1).
**Notes:** Grounded by confirming `compose_engine` builds the `'simulated'` exchange for both modes — the registry is a live-only overlay, giving a zero-oracle-risk firewall.

### P5/P6 rewire boundary
| Option | Description | Selected |
|--------|-------------|----------|
| Helper seam in P5, promoted in P6 | `assemble_venue(...)` seam; branches gone in P5; P6 relocates the call | ✓ |
| Inline in `__init__` now, extract in P6 | ~40 lines authored inline then moved wholesale in P6 (two diffs) | |
| Machinery-only in P5, branches killed in P6 | Violates SC3 | |

**User's choice:** Helper seam (Option 1).
**Notes:** User asked for the recommendation. Chosen to write the assembly logic once (P6 relocates the call, not the logic) and keep the seam independently unit-testable in P5.

---

## Area 3 — Connector memoization & per-account_id credentials

| Option | Description | Selected |
|--------|-------------|----------|
| Shape the seam, single-account creds, defer scheme to P11 | Memo keyed `(venue, account_id)`; single default account; `OKX_API_*` creds; multi-account scheme → P11 | ✓ |
| Full per-account env scheme now | Invents `OKX_<ACCOUNT>_*` + real spec field with no consumer | |
| No account_id in P5; add it all in P11 | Forces re-keying the memo in P11; weakens VENUE-03 | |

**User's choice:** Shape the seam, defer scheme to P11 (Option A).
**Notes:** User raised the two-identifier insight — a generated/connect-time account ID vs a venue-provided UID. Clarified that the memo key must be a config-known **stable name resolved pre-`connect()`** (D-06 alignment), while the **venue-provided UID** is post-connect reconciliation truth — agreed to defer the UID assertion to P7/P11.

---

## Area 4 — StreamSupervisor & provider Protocol

### StreamSupervisor shape + home
| Option | Description | Selected |
|--------|-------------|----------|
| Composition class in `connectors/stream_supervisor.py` | Standalone has-a collaborator (new 4-space file); arms delegate | ✓ |
| Mixin/base class the 3 arms inherit | Inheritance across 3 base classes + tab/space files; body lands in tab files via MRO | |
| Free async function + passed-in state | Re-scatters the WR-03 budget state across call sites | |

**User's choice:** Composition class (Option 1).
**Notes:** Grounded by the ~80-line security-critical donor (transient/fatal classification, unclassified→fail-safe halt, WR-03 payload-only budget reset, scrub discipline) triplicated across two tab files + one space file. Composition quarantines the state and dodges the tab/space transplant hazard.

### VENUE-05 / VENUE-06 reconciliation
| Option | Description | Selected |
|--------|-------------|----------|
| None-guard absent components; no-op-default optional methods | No-op base for present-optional methods; `None`-guard for entirely absent components | ✓ |
| Null-Object for absent components too (branch-free) | Invents `NullConnector`/`NullAccount`; silently masks a failed-to-build component | |

**User's choice:** None-guard + no-op-default (Option 1).
**Notes:** User asked for the recommendation. Reconciled the two requirements as one rule keyed on granularity (present-optional-method vs entirely-absent-component); rejected Null-Object as fail-silent + contradicting the `Optional=None` bundle shape.

---

## Claude's Discretion
- Plan/wave slicing across VENUE-01..07 (subject to byte-exact + inertness gates).
- Exact module paths (`execution_handler/venues/` vs a top-level `venues/`), `StreamSupervisor`/`ConnectorProvider`/registry method names & signatures, the default `account_id` literal, and whether `VenueLifecycle` is a class or an ordered helper.
- `resolve_precision` return shape and the exact home of `_precision_to_scale` in `core/money.py`.

## Deferred Ideas
- Multi-account credential env-naming scheme (`OKX_<ACCOUNT>_*`) + per-`PortfolioSpec` account_id → **P11**.
- Venue-provided account-UID-vs-intent reconciliation assertion (post-connect) → **P7 / P11**.
- Null-Object pattern for absent components — considered, rejected in favor of explicit `None`-guards.
