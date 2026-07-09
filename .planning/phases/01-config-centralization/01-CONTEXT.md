# Phase 1: Config Centralization - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Centralize all system-wide configuration into one import-safe `SystemConfig`, fold scattered
module constants into their domain config, retire dead config, and introduce a typed `HaltReason`
enum — **without disturbing the byte-exact backtest oracle (`134 / 46189.87730727451`) or the OKX
import-inertness gate** (`tests/integration/test_okx_inertness.py`).

Delivers (CFG-01..CFG-06):
- `SystemConfig` aggregating the cardinality-1 singletons with an eager/lazy import-safety split.
- Scattered module constants (`_STREAM_RECONNECT_*`, `_WARMUP_MARGIN`, `_BACKFILL_PAGE`, `_OKX_*`,
  `_PAPER_*`) folded into domain config (grep-clean).
- A dead-config audit (unused settings + stale `__pycache__`) and a normalized `extra` policy.
- A typed `HaltReason` enum in `core/enums/system.py` retiring the `'baseline-residual'` free string.
- The D-03a dual-validator paragraph applied to `.planning/codebase/CONVENTIONS.md` (CF-6).

This is an **oracle-gated centralization pass** — blast radius is the enemy. Requirements are
prescriptive (design spec §6a–6f); what was discussed here are the implementation-strategy calls.

</domain>

<decisions>
## Implementation Decisions

### Config immutability
- **D-01:** `SystemConfig` and nested models stay **mutable-by-convention** — NOT frozen in P1. The
  "immutable base defaults" contract is enforced by the P9 `RuntimeConfig` overlay being the only
  real mutation path (snapshot-read discipline), not by a frozen Pydantic model. Freezing has real
  blast radius (breaks any in-place mutator) and this is the phase that must prove the oracle
  byte-exact — so it's deferred, freezable later if P9 wants it.

### SystemConfig aggregation (cardinality rule) — OWNER OVERRIDE OF SPEC/REQUIREMENT
- **D-02:** The aggregation boundary is **cardinality**, not "is it config." `SystemConfig` aggregates
  only the genuine cardinality-1 singletons: **`performance`, `monitoring`, `runtime`, `sql`(lazy)**.
- **D-03 (deviation):** `order` is **kept OUT of `SystemConfig`** and reclassified **cardinality-N**
  (owner expects order settings to diverge per-portfolio / per-venue in the near future). It lives
  with its owner (`OrderHandler`) via `OrderConfig.default()`, alongside `portfolio` and `exchange`.
  - **This supersedes** both the spec (§6b lists `order` as a `SystemConfig` singleton) AND the
    original CFG-01 / Success-Criteria #2 text (which named `order` in the aggregation).
    `REQUIREMENTS.md` CFG-01 was reworded to match (owner amendment 2026-07-09).
  - **Downstream must NOT "fix" this back** to match spec text. Validation checks `order` lives with
    its owner, not on `SystemConfig`.
- **D-04:** **No per-instance default-template fields on `SystemConfig`.** Per-instance configs
  (`PortfolioConfig`, `ExchangeConfig`, and now `OrderConfig`) own their seed via the existing
  `.default()` classmethod convention and are seeded/persisted by their own instance/store (§6b
  "config lives with its owner"). This supersedes §6a's "default templates … on SystemConfig" wording
  and removes the templates-shape question entirely.

### Lazy `sql` accessor (inertness-critical seam)
- **D-05:** `sql` resolves `SqlSettings` on **first access only, never at import**; uncredentialed
  access **raises** (the Postgres arm needs a credential). Import must construct no `SqlSettings` so
  `test_okx_inertness.py` stays green (extended register-vs-build assertion).
- **D-06:** Mechanism = **`@cached_property`** (matches "resolved on first access"). *Caveat:*
  pydantic-v2 + `@cached_property` has a known interaction — the researcher/planner verifies the exact
  idiom (may need a `model_config` tweak or an `object.__setattr__` cache). Contract is locked;
  mechanism may adjust if the pydantic idiom demands it.

### `runtime` (Settings) eager placement
- **D-07:** `runtime` (pydantic-settings `Settings`, `env_prefix="ITRADER_"`) stays an **eager** field.
  Constructing it reads env vars but does NOT construct the Postgres `SqlSettings` (separate
  `ITRADER_DATABASE_` model that raises uncredentialed). Only `SqlSettings` is the inertness risk —
  the inertness gate asserts *no SqlSettings*, not *no env-read*. Do NOT give `runtime` a lazy seam.

### Constant-fold scope
- **D-08:** **Define the new config blocks AND rewire the direct constant readers now** — but leave
  the shared-`StreamSupervisor` consolidation to P5 (it doesn't exist yet). `_STREAM_RECONNECT_*` →
  `StreamSettings`/`ConnectionSettings`; `_WARMUP_MARGIN`/`_BACKFILL_PAGE` → feed/provider config;
  `_OKX_*`/`_PAPER_*` deleted. Constants gone from source (CFG-03 grep-clean met); the shared-supervisor
  plumbing is P5's job. Touches live-path files → must prove oracle byte-exact + inertness green after.

### `extra` policy normalization
- **D-09:** Resolve **empirically during the dead-config audit**, don't pre-commit. Today `SystemConfig`
  is the lone `extra="ignore"` among `forbid` siblings (`exchange`/`portfolio`/`order`/`sql`). If the
  surviving `settings/` YAML is clean → move `SystemConfig` to `forbid` everywhere-except-env (true
  normalization, catches typos loudly), keeping env models (`Settings`/`OkxSettings`) on `ignore`
  (they legitimately see unrelated env vars). If some YAML legitimately carries extras → keep `ignore`
  there. Record the chosen outcome in the plan.

### `HaltReason` enum vocabulary
- **D-10:** **Minimal** — enumerate only halt reasons raised in code today (retire `'baseline-residual'`
  at `live_trading_system.py:810` + any other free strings at existing `halt()` call sites). Tight
  scope; **P8 extends the enum** as it formalizes `SafetyController` and knows the real vocabulary.
  Avoids shipping dead members. Comprehensive-now was explicitly rejected as YAGNI.
- **D-11:** Enum home = `core/enums/system.py` (which already holds `SystemStatus`). P1 owns the enum
  definition; P8's `SafetyController` owns `halt()` and consumes it (CF-8 split across P1 + P8).

### Dead-config audit / cleanup
- **D-12:** Dead-config audit is **conservative** — remove only provably-unreferenced settings (this
  is oracle-gated; aggressive path-reachability pruning is not worth the blast radius).
- **D-13:** `__pycache__` handling: verify `.gitignore` covers it and `git-rm` any tracked/committed
  cache stragglers. Mechanical, low-risk.

### Claude's Discretion
- Exact `StreamSettings` / `ConnectionSettings` field layout and where they live in `config/`.
- Exact feed/provider config field names for the folded `_WARMUP_MARGIN` / `_BACKFILL_PAGE`.
- The precise pydantic-v2 `@cached_property` idiom for the lazy `sql` accessor (contract is locked).

### Folded Todos
- **CF-6** (`v17-residual-carryforward.md` §6) — apply the D-03a dual-validator paragraph to
  `.planning/codebase/CONVENTIONS.md`. Ready-to-paste in `v17_audit_results.md §6d`; paste, don't
  re-derive. (Already in P1 scope as CFG-06.)
- **CF-8** (`off-vocabulary-halt-reason-baseline-residual-wr04.md`) — the `HaltReason` enum work above
  (D-10/D-11). P1 owns the enum; P8's `SafetyController` owns `halt()`. (Already in P1 scope as CFG-05.)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source (the P1 config contract)
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §6a–6f — centralized
  `SystemConfig` import-safety split (§6a), config-lives-with-owner cardinality rule (§6b), two config
  objects / `RuntimeConfig` overlay (§6c), `system_store` (§6d), runtime-mutation flow (§6e), cleanup
  (§6f). **Note the P1 deviations D-03/D-04 above** — `order` and per-instance templates do NOT go on
  `SystemConfig` despite §6a/§6b wording.

### Requirements
- `.planning/REQUIREMENTS.md` — CFG-01..CFG-06 (CFG-01 reworded 2026-07-09 to drop `order` from the
  aggregation per D-03).

### Ready-to-paste debt
- `.planning/todos/pending/v17_audit_results.md` §6d — the D-03a dual-validator paragraph for CF-6
  (paste into `.planning/codebase/CONVENTIONS.md`).
- `.planning/todos/pending/off-vocabulary-halt-reason-baseline-residual-wr04.md` — CF-8 halt-vocabulary
  context.
- `.planning/todos/pending/v17-residual-carryforward.md` §6 — CF-6 index.

### Gates (must stay green — verify after every plan)
- `tests/integration/test_backtest_oracle.py` — SMA_MACD byte-exact oracle (`134 / 46189.87730727451`).
- `tests/integration/test_okx_inertness.py` — import must construct no `SqlSettings` (extended
  register-vs-build assertion for the lazy `sql` accessor).

### Convention target
- `.planning/codebase/CONVENTIONS.md` — receives the CF-6 D-03a paragraph.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `itrader/config/system.py::SystemConfig` — today holds only `performance` + `monitoring` + scalar
  fields; `runtime`/`sql` are the new aggregations. Has `default()` + `from_dict()` classmethods.
- `.default()` classmethod convention — already established across `config/` (`order.py` docstring
  calls it out; portfolio/exchange models follow it). This is the home for per-instance seed defaults
  (D-04), so no new pattern is introduced.
- `itrader/core/enums/system.py` — already exists and holds `SystemStatus`; `HaltReason` lands here.
- `itrader/config/sql.py::SqlSettings` — `SettingsConfigDict(env_prefix="ITRADER_DATABASE_",
  extra="forbid")`; its Postgres arm raises uncredentialed — this is what the lazy accessor gates.

### Established Patterns
- `extra` policy split: domain models (`exchange`/`portfolio`/`order`/`sql`) use `extra="forbid"`;
  `SystemConfig` + env-var models (`Settings`/`OkxSettings`) use `extra="ignore"`. D-09 resolves the
  `SystemConfig` outlier empirically.
- Import-side-effect singletons: `itrader/__init__.py` builds `config = SystemConfig.default()` at
  import — the eager/lazy split (D-05/D-07) protects this from constructing `SqlSettings`.

### Integration Points — scattered constants to fold (CFG-03, D-08)
- `itrader/price_handler/providers/okx_provider.py` — `_STREAM_RECONNECT_*` (×4), `_BACKFILL_PAGE`,
  `_OKX_INTERVALS`.
- `itrader/portfolio_handler/account/venue.py` — duplicate `_STREAM_RECONNECT_*` (×4).
- `itrader/price_handler/providers/replay_provider.py` — duplicate `_BACKFILL_PAGE`.
- `itrader/price_handler/feed/live_bar_feed.py` — `_WARMUP_MARGIN`.
- `itrader/trading_system/live_trading_system.py` — `_OKX_STREAM_*`, `_PAPER_STREAM_*`,
  `_PAPER_EXPECTED_*`, and the `self.halt('baseline-residual')` free string at line 810.
- Also referenced in `execution_handler/exchanges/okx.py`, `execution_handler/exchanges/venue_correlation.py`,
  `universe/universe_handler.py` (grep the fold set before declaring grep-clean).

</code_context>

<specifics>
## Specific Ideas

- The **cardinality rule** is the load-bearing design principle for this phase, stated by the owner:
  "put a config on `SystemConfig` only if there's exactly one of the owning thing at runtime; if it
  can diverge per-portfolio or per-venue, keep it with its owner." Applied to promote nothing that
  might later need N instances — `order` was demoted on this basis even though it's cardinality-1
  today, to avoid a promote-then-demote churn later.

</specifics>

<deferred>
## Deferred Ideas

- **Shared `StreamSupervisor` consolidation** — the `StreamSettings`/`ConnectionSettings` blocks are
  defined + wired to direct readers in P1, but the shared-supervisor that consumes them is **P5**.
- **`RuntimeConfig` overlay + runtime mutation platform** — P9 (RTCFG-01..06); P1 only ships the
  immutable base defaults.
- **Per-portfolio / per-venue `order` config divergence** — the future need that justified keeping
  `order` cardinality-N (D-03). Not built now; the classification just leaves room for it.
- **Freezing `SystemConfig`** — deferred (D-01); reconsider if P9 wants a hard runtime guarantee.

</deferred>

---

*Phase: 1-Config Centralization*
*Context gathered: 2026-07-09*
