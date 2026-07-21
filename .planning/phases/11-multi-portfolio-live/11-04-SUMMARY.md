---
phase: 11-multi-portfolio-live
plan: 04
subsystem: credentials-boundary
tags: [credentials, security, venues, MPORT-06, D-02, D-03, D-04]
requires:
  - "11-01: VenueAccountStore (venue_accounts row, secret_ref/venue_uid columns)"
  - "05-04/05-06: VenuePlugin Protocol, assemble_venue, VenueLifecycle"
provides:
  - "CredentialResolver Protocol + EnvCredentialResolver (env:<PREFIX> scheme)"
  - "VenuePlugin.credential_model + VenuePlugin.fetch_venue_uid"
  - "assert_venue_uid — trust-on-first-use venue-identity guard, wired post-connect"
  - "VenueAccountStore.record_venue_uid"
  - "VenueSpec.secret_ref — the per-account credential pointer"
affects:
  - "itrader/venues/ (bundle Protocol, both plugins, lifecycle, assemble)"
  - "itrader/trading_system/live_trading_system.py (composition-root wiring)"
  - "itrader/config/okx_settings.py (populate_by_name)"
tech-stack:
  added: []
  patterns:
    - "itrader ships the seam, the app owns the data (Protocol + one env impl)"
    - "pointer-not-secret on the durable row"
    - "trust-on-first-use identity assertion, observe-only"
key-files:
  created:
    - itrader/config/credential_resolver.py
    - itrader/core/exceptions/credential.py
    - itrader/venues/venue_uid_guard.py
    - tests/unit/config/test_credential_resolver.py
    - tests/unit/venues/test_venue_uid_guard.py
  modified:
    - itrader/config/okx_settings.py
    - itrader/core/exceptions/__init__.py
    - itrader/venues/bundle.py
    - itrader/venues/okx_plugin.py
    - itrader/venues/paper_plugin.py
    - itrader/venues/lifecycle.py
    - itrader/venues/assemble.py
    - itrader/storage/venue_account_store.py
    - itrader/trading_system/venue_spec.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/venues/test_registry.py
    - tests/unit/venues/test_okx_plugin.py
    - tests/unit/venues/test_paper_plugin.py
    - tests/unit/storage/test_venue_account_store.py
    - tests/integration/test_okx_inertness.py
decisions:
  - "resolve() returns Mapping[str, SecretStr], not Mapping[str, str] — redaction structural, not prose"
  - "OkxSettings gains populate_by_name rather than keying the resolved mapping by validation alias"
  - "credential_model is a @property with a lazy import, not a plain class attribute"
  - "VenueSpec carries secret_ref; the plugin stays store-free and resolver-injected"
  - "guard normalizes account_id at its own boundary rather than at each hand-off"
metrics:
  duration: ~85m
  completed: 2026-07-21
  tests_added: 38
  suite: "2715 passed / 6 skipped (baseline 2677 / 6)"
status: complete
---

# Phase 11 Plan 04: W2 Credentials Boundary Summary

Per-account venue credentials resolved from a durable `secret_ref` pointer through a
swappable `CredentialResolver` seam, plus a trust-on-first-use venue-identity guard that
detects when an account connects with the wrong account's keys — both wired into the real
production path rather than shipped as referenced-but-unreachable code.

## What was built

**1. The credentials seam (D-02, T-11-16/17/18).** `CredentialResolver` is a
`@runtime_checkable` Protocol with one env-backed implementation over an `env:<PREFIX>`
scheme. The durable row holds a POINTER; resolution happens in memory at connect time and
is never written back. A Vault/AWS/GCP resolver is one more class satisfying the Protocol
from the web app's own repo — zero `itrader` change, zero new dependency.

**2. Self-describing venue plugins (D-03).** `VenuePlugin` gained `credential_model` (so an
integrations page renders per-venue form fields from the registry with no hardcoding) and
`fetch_venue_uid` (so the identity guard stays venue-agnostic).

**3. The trust-on-first-use guard (D-04, T-11-15).** First connect for a
`(venue_name, account_id)` records the venue's self-reported account UID; later connects
assert against it. A mismatch fires one CRITICAL alert with a fixed literal reason, does
not overwrite the recorded value, and returns normally — observe-only by decision.

## Two deliverables that would have shipped INERT

The pre-execution audit predicted both; both were confirmed against the code and fixed.

**The UID guard would never have run.** The plan said to inject the guard's dependencies as
optional kwargs "so every existing construction site keeps working unchanged". The only
production construction site — `assemble.py`'s `VenueLifecycle(bundle, provider, connectors=connectors)`
— supplies none of them, so `assert_venue_uid` would never execute while every unit test
(which drives the function directly with fakes) passed green.

This is not a hypothetical. **Mutation-testing proved it**: deleting the guard call from
`VenueLifecycle.start()` leaves **11 of the 12 guard tests green**. Only
`test_guard_runs_on_the_real_assemble_venue_production_path` — which drives a real
SQLite-backed `VenueAccountStore` through `assemble_venue` → `lifecycle.start()` — goes red.
A second test asserts by source inspection that `build_live_system` actually passes
`account_store=` and `alert_sink=`; dropping that wiring reddens only that one test.

`VenueLifecycle` had no handle on the plugin at all (`assemble_venue` resolved it locally
at line 71 and discarded it), so threading it through was a signature change the plan did
not anticipate.

**The resolver would never have been wired.** `OkxConnectorPlugin.build` did
`return OkxConnector(OkxSettings())`, reading the one global `OKX_API_*` set and ignoring
`spec.account_id`. Two `account_id`s would have connected with identical credentials while
the plan's must_have claimed per-account isolation was real — the exact misroute D-04
exists to detect, shipped green. `build` now resolves `spec.secret_ref` through the
injected resolver; `VenueSpec` carries the pointer, read off the account's `venue_accounts`
row in `build_live_system`.

## Plan drift found

| # | Plan/audit said | Code said | Resolution |
|---|---|---|---|
| 1 | `OkxSettings(api_key=...)` works | **Confirmed broken.** `extra="ignore"` drops the field-named kwarg, then the model errors `OKX_API_KEY Field required` | Added `populate_by_name=True` to `OkxSettings` (audit offered this or alias-keying; chose this so the resolver stays venue-agnostic) and pinned it with a round-trip test |
| 2 | `credential_model` as a plain class attribute is "the simplest thing" | The AST gate in `test_okx_plugin.py:90-94` rejects any module-level import containing `okx_settings`, so the attribute reddens it | `@property` with a lazy import (see "Convention exception" below) |
| 3 | Adding Protocol members is safe | `_FakeVenuePlugin` (`test_registry.py:26`) has only `build_bundle` and `:120` asserts `isinstance(..., VenuePlugin)` | Gave the fake both members in the same commit as the Protocol change |
| 4 | `resolve() -> Mapping[str, str]` | Plain `str` loses `SecretStr` masking into every repr / exception / structlog spread — T-11-17 unenforced | Returns `Mapping[str, SecretStr]`; asserted structurally |
| 5 | Guard takes `account_id: str` | `VenueSpec.account_id` is `Optional[str]`; both plugins apply `or "default"` *inside* `build_bundle`, invisible to the lifecycle | Guard normalizes at its own boundary (one place, not per hand-off); regression test asserts `None` → `"default"` |
| 6 | `None` UID and store failures are silent no-ops | A renamed field or storage outage would disable the only spoofing detector with zero signal | Every degraded path logs; a venue that *declares* a credential model yielding no UID logs a WARNING |
| 7 | Acceptance: `git diff -U0 -- okx_plugin.py \| grep -cE '^\+(import\|from) '` returns 0 | Returns **1** — I added a module-top `from itrader.logger import get_itrader_logger` | Accepted. Audit #10 already declared this gate false-green and named the real AST test as its replacement; that test and the subprocess inertness probe both pass. The import is pure and already on the backtest path |
| 8 | — | `test_okx_connector_plugin_falls_back_to_ambient_env_only_without_a_pointer` passed **before** any change | Recorded rather than counted as proof — it pins pre-existing behaviour I deliberately preserved, not new work |
| 9 | Line anchors `:1510` / `:1410` | Correct after 11-06 | Re-located by symbol anyway |

## Deviations from plan

### Auto-fixed issues

**1. [Rule 1 - Bug] `NameError` in the credential-pointer read**
- **Found during:** Task 3, full-suite run
- **Issue:** `_read_account_secret_ref` called `logger.warning(...)` in its degrade-clean
  branch, but `logger` is a **function-local** binding everywhere in
  `live_trading_system.py` (bound at `:1199` and `:1353`) — there is no module-level
  `logger`. Against a real Postgres missing the `venue_accounts` table, the handler caught
  the `UndefinedTable` error and then died on `NameError` inside its own except block.
- **Fix:** bind a logger inside the helper; comment records why.
- **Why it matters:** `live_trading_system.py` is under a mypy `ignore_errors` override, so
  a `NameError` passed mypy **and** the venues/storage unit suites silently. Only
  `tests/integration/test_store_live_drive.py` (which drives a real Postgres) caught it.
  This is the documented live-facade blindspot, hit again.
- **Commit:** 2f3f9efa

**2. [Rule 2 - Missing critical functionality] Scope expansion, owner-approved**
The two inert-deliverable fixes above required files the plan did not list:
`itrader/venues/assemble.py`, `itrader/trading_system/live_trading_system.py`,
`itrader/trading_system/venue_spec.py`, `itrader/config/okx_settings.py`,
`tests/unit/venues/test_registry.py`.

### Convention exception (declared, not silent)

The owner's standing rule is **no lazy imports, no late init**. `OkxVenuePlugin.credential_model`
lazy-imports `OkxSettings` inside the property body. This is the pre-existing,
test-enforced D-04 triple-deferral exception scoped to `okx_plugin.py` — the file already
lazy-imports at three sites, and `test_okx_plugin.py:90-94` fails the build on any
module-level `okx_settings` import. Following the local convention; flagging it explicitly.

## Security posture

| Threat | Status |
|---|---|
| T-11-15 spoofing (mistyped `secret_ref` / swapped entry) | Mitigated **and proven reachable in production** — mutation-tested |
| T-11-16 credentials in dumps/replicas | Pointer-only row; nothing added to any column |
| T-11-17 values in messages/logs/alerts | `Mapping[str, SecretStr]`; `CredentialResolutionError` has **no parameter that can carry a value**; alert payload asserted secret-free |
| T-11-18 silent ambient-credential fallback | Zero-match **raises**; mutation-tested. A wholly absent pointer takes the legacy path — documented as distinct from fail-open |
| T-11-19 guard aborting a healthy connect | Never raises, never halts; store outage swallowed + logged |
| T-11-20 self-healing overwrite | Not overwritten; mutation-tested (caught by 2 tests) |
| T-11-SC package installs | None. No `pyproject.toml` / `poetry.lock` change |

Also added `itrader.config.credential_resolver` to the inertness `_FORBIDDEN` list, making
"do not barrel-export the resolver" structural rather than prose.

## Mutation testing

Every security gate was proven capable of failing:

| Injected bug | Result |
|---|---|
| Invert the UID comparison (`recorded != uid`) | 4 tests red |
| Overwrite the recorded UID on mismatch (T-11-20) | 2 tests red |
| **Delete the guard call from `VenueLifecycle.start()`** | **only 1 of 12 red** — the real-path test |
| Drop `account_store=`/`alert_sink=` from `build_live_system` | 1 test red (the source-inspection gate) |
| Bare `startswith(prefix)` in the resolver (cross-account leak) | 1 test red (the anchoring test) |
| Zero-match returns `{}` instead of raising | multiple red |

## Verification

| Gate | Result |
|---|---|
| `pytest tests -q` | **2715 passed / 6 skipped** (baseline 2677 / 6; +38) |
| `pytest tests/integration/test_backtest_oracle.py` | passed — oracle byte-exact |
| `pytest tests/integration/test_okx_inertness.py` | passed |
| `mypy` | clean, 256 source files |
| `git diff --stat pyproject.toml poetry.lock` | empty — zero new dependencies |
| Indentation | `venue_spec.py` tabs preserved (0 space-indented lines added); all `venues/` files 4-space |

All commands run as `poetry run python -m pytest` / `PYTHONPATH=<worktree> poetry run mypy`
— bare `poetry run pytest` exercises the main checkout through the editable install.

## Known gaps / follow-ups

1. **`fetch_venue_uid`'s OKX endpoint is unverified against a live session.** It reads
   `private_get_account_config()` → `data[0].uid`. The available demo account is a single
   EEA sub-account, so real-venue confirmation is operator-side — record it in
   `11-VALIDATION.md`. A wrong field degrades to a logged WARNING, not a failure.
2. **No `venue_accounts` rows exist yet**, so `secret_ref` resolves to `None` in practice
   and the legacy ambient-credential path runs. Account **minting is plan 11-07** (D-28);
   the resolution path is reachable and tested, and activates the moment rows exist.
3. **The read-model surface for UID mismatches was not implemented.** The plan's must_have
   truth claims a mismatch is "surfaced in the read-model", but no task specified the
   RTCFG-06 KV sink write (audit #9 flagged this). Only the alert half ships. Either
   implement it in a later plan or reword the truth — flagging rather than silently
   dropping.
4. **`sandbox`/`region` cannot travel through a credential prefix.** The resolver returns
   `SecretStr` values by definition, so a non-credential knob in the prefix fails pydantic
   validation loudly. Those belong in the row's `config_json` (D-05) — documented in the
   module.

## Self-Check: PASSED

Created files verified present; all three task commits verified in `git log`.
