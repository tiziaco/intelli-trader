---
phase: quick-260703-dob
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - tests/integration/test_okx_connectivity.py
  - Makefile
autonomous: true
requirements: [QUICK-260703-dob]
must_haves:
  truths:
    - "`live` marker is registered in pyproject.toml, so `@pytest.mark.live` never trips --strict-markers"
    - "`-m live` runs the public reachability test always and the authenticated test only when OKX creds are present"
    - "`-m \"not live\"` deselects BOTH new tests (default `make test` never makes a network round-trip)"
    - "the authenticated test asserts `connector.sandbox is True` BEFORE any network call (T-05-04 real-money-misroute guard)"
    - "`make test-live` exists, is DISTINCT from the pre-existing `test-e2e-live`, and runs `-m live`"
  artifacts:
    - path: "tests/integration/test_okx_connectivity.py"
      provides: "public + authenticated OKX live-connectivity tests, both @pytest.mark.live"
      contains: "pytest.mark.live"
    - path: "pyproject.toml"
      provides: "`live` marker registration in [tool.pytest.ini_options] markers"
      contains: "live:"
    - path: "Makefile"
      provides: "test-live target running -m live"
      contains: "test-live"
  key_links:
    - from: "tests/integration/test_okx_connectivity.py"
      to: "itrader.connectors.okx.OkxConnector"
      via: "lazy import inside Test B body"
      pattern: "from itrader.connectors.okx import OkxConnector"
    - from: "tests/integration/test_okx_connectivity.py"
      to: "connector.client.fetch_balance"
      via: "connector.call(...) — the exact method VenueAccount.snapshot() uses"
      pattern: "connector\\.call\\(connector\\.client\\.fetch_balance"
---

<objective>
Add an OKX live-connectivity integration test module plus a new `live` pytest marker (PURPOSE axis), and wire Make targets so the default test run never makes a network round-trip while `make test-live` opts into the live tests.

Purpose: Give the suite a fast, credential-free proof that the OKX host is reachable, and a credential-gated proof that the demo OkxConnector authenticates read-only — both isolated behind a hand-applied `live` marker so `make test` / CI stay offline.
Output: `live` marker registered in `pyproject.toml`; new `tests/integration/test_okx_connectivity.py` with two tests; Makefile `test`/`test-integration` fenced with `not live` and a new `test-live` target.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md

**Working tree:** run on the MAIN checkout (NOT a worktree) — live verification needs the OKX
demo creds from `.env`, which is absent in worktrees. The tree is currently clean.

**Indentation (match each file, never normalize):**
- `pyproject.toml` — 4 spaces (match the existing `markers = [ ... ]` list entries).
- `tests/integration/test_okx_connectivity.py` — 4 spaces (match the existing OKX test files).
- `Makefile` — recipe lines MUST use real TABS (make requires them); comment/echo style follows the surrounding targets.
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Pinned during planning from the codebase — executor uses these directly, no exploration. -->

From itrader/config/okx_settings.py — OkxSettings(BaseSettings), env-sourced, no-arg
construction reads OKX_API_KEY/SECRET/PASSPHRASE + OKX_SANDBOX (default True) + OKX_REGION
(default "global"). `sandbox` defaults True. Construct with `OkxSettings()`.

From itrader/connectors/okx.py — OkxConnector:
  def __init__(self, settings: OkxSettings | None = None) -> None
  @property sandbox -> bool        # set in __init__ from settings — readable BEFORE connect()
  @property client  -> Any         # the ccxt.pro client (built inside the loop by connect())
  def connect(self) -> None        # network: spins loop thread, builds client, load_markets()
  def call(self, coro) -> T        # synchronous RPC bridged onto the connector loop
  def disconnect(self) -> None     # teardown — cancel streams, close client, stop loop

From itrader/portfolio_handler/account/venue.py — VenueAccount.snapshot() (line ~206) fetches
the venue balance via exactly:  `bal = self._connector.call(self._connector.client.fetch_balance())`
The authenticated test MUST reuse this exact call shape (read-only, no order, no venue mutation).

From tests/integration/test_okx_smoke.py — the module-level creds gate to mirror:
  _OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
  _HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)

From pyproject.toml — the folder-derived TYPE marker for tests/integration/ is `integration`,
auto-applied by tests/conftest.py. Do NOT hand-apply it. Only hand-apply `live`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Register the `live` marker and add the connectivity test module</name>
  <files>pyproject.toml, tests/integration/test_okx_connectivity.py</files>
  <action>
Do BOTH edits in one task so marker registration and first use land together (an unregistered
marker ERRORS the whole suite under --strict-markers + filterwarnings=["error"]).

(1) pyproject.toml — append ONE entry to the `markers = [ ... ]` list (4-space indent, match the
existing `smoke` entry's quoted-string style). Add after the `smoke` line:
    "live: Live-venue test — makes a real network round-trip to a live venue; PURPOSE axis, applied by hand with @pytest.mark.live, orthogonal to the folder-derived TYPE axis"
Do NOT touch any other marker, and do NOT reorder the list.

(2) Create tests/integration/test_okx_connectivity.py (4-space indent throughout). Module docstring:
explain it is an opt-in live OKX connectivity check gated behind the `live` marker; ALL connector
imports are LAZY (inside test bodies) so a credential-free/offline COLLECTION never touches ccxt.pro
or connector code. Module level:
    import os
    import pytest
    _OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
    _HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)
Do NOT hand-apply the `integration` TYPE marker — the root conftest auto-applies it by folder.

Test A — `test_okx_public_endpoint_reachable` (creds-FREE): decorate with `@pytest.mark.live` ONLY
(NO skipif). Body: lazy `import ccxt`, build a public sync client `client = ccxt.okx()` (no creds,
no sandbox — public reachability only), call `markets = client.load_markets()`, assert `markets`
truthy and `len(markets) > 0`. This is an unauthenticated public call proving the OKX host is
reachable. No credentials, no orders. (Sync ccxt REST client holds no persistent socket needing
close; if a ResourceWarning ever surfaces under filterwarnings=["error"], close it in a finally.)

Test B — `test_okx_demo_authenticated_connectivity` (creds-GATED): decorate with BOTH
`@pytest.mark.live` AND `@pytest.mark.skipif(not _HAS_OKX_CREDS, reason="OKX demo credentials absent — authenticated connectivity check skipped; set OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (demo) to enable.")`.
Body: lazy-import `from itrader.config.okx_settings import OkxSettings` and
`from itrader.connectors.okx import OkxConnector`. Build `connector = OkxConnector(OkxSettings())`.
BEFORE any network call, assert `connector.sandbox is True` (T-05-04 real-money-misroute guard —
`sandbox` is set in __init__ from settings and is readable pre-connect). Then in a try/finally:
`connector.connect()`, then the READ-ONLY balance fetch reusing VenueAccount.snapshot()'s exact
method: `bal = connector.call(connector.client.fetch_balance())`; assert `bal is not None` and
`isinstance(bal, dict)` and `bal` non-empty (a ccxt AuthenticationError would raise and fail the
test — that is the assertion). In the `finally`, `connector.disconnect()` so no authenticated
socket leaks under filterwarnings=["error"]. Place NO orders and take NO venue-mutating action.

Rationale to preserve in comments: both tests get `live` (network property); only the
authenticated one gets `skipif` (creds property) — do not conflate.
  </action>
  <verify>
    <automated>poetry run pytest tests/integration/test_okx_connectivity.py -m "not live" -v 2>&1 | grep -Eq "2 deselected|deselected" &amp;&amp; echo "OK: both deselected under 'not live'"</automated>
  </verify>
  <done>`live` is in the pyproject markers list; `tests/integration/test_okx_connectivity.py` collects with NO strict-markers/strict-config error; under `-m "not live"` both tests are deselected (0 selected); `test_okx_smoke.py` still collects/passes unchanged.</done>
</task>

<task type="auto">
  <name>Task 2: Fence default test runs with `not live` and add the `test-live` target</name>
  <files>Makefile</files>
  <action>
Recipe lines use real TABS. Leave the pre-existing `test-e2e-live` and `diagnose-okx` targets
UNTOUCHED — the new `test-live` must sit cleanly alongside them and be distinct from `test-e2e-live`.

(1) `test` target (~line 29): change `poetry run pytest tests/ -v` → `poetry run pytest tests/ -v -m "not live"`.

(2) `test-integration` target (~line 37): change `-m "integration"` → `-m "integration and not live"`.

(3) Add a NEW `test-live` target (follow the surrounding echo-banner style, e.g. a 🛰️/📡 banner)
that runs `poetry run pytest tests/ -v -m live`. It loads `.env` via the top-level `include .env`
+ `.EXPORT_ALL_VARIABLES`, so local demo creds are exported and Test B runs. Add a short comment
above it noting it is DISTINCT from `test-e2e-live` (this runs the fast `-m live` connectivity
checks anywhere in tests/; `test-e2e-live` runs only the slow e2e recon suite with `-m slow`).

(4) Add `test-live` to the `.PHONY` line (line 6), alongside the existing targets.
  </action>
  <verify>
    <automated>grep -q 'test-live' Makefile &amp;&amp; grep -q 'not live' Makefile &amp;&amp; grep -q 'test-e2e-live' Makefile &amp;&amp; echo "OK: test-live added, defaults fenced, test-e2e-live intact"</automated>
  </verify>
  <done>`make test` and `make test-integration` carry `not live`; a distinct `test-live` target runs `-m live` and is on `.PHONY`; `test-e2e-live` and `diagnose-okx` are unchanged.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| test process → OKX venue | authenticated demo credentials cross into ccxt.pro; a sandbox misroute would hit a real-money venue |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-05-04 | Tampering | OkxConnector routing in Test B | mitigate | assert `connector.sandbox is True` BEFORE any network call; test is READ-ONLY (fetch_balance only), places no orders, takes no venue-mutating action |
| T-conn-LEAK | Information Disclosure | OKX credentials | mitigate | creds sourced only via OkxSettings/SecretStr at the client edge; test never logs or asserts secret values |
| T-conn-SOCK | Denial of Service | authenticated ccxt.pro socket | mitigate | `connector.disconnect()` in a `finally` so no session leaks under filterwarnings=["error"] |
</threat_model>

<verification>
Run on the MAIN checkout with `.env` present. If OKX creds are not already exported in the shell,
export them first (`set -a; source .env; set +a`) OR use `make test-live` (which exports `.env`).

Gating matrix to confirm:
- default dev `-m "not live"` → BOTH new tests deselected.
- `-m live`, no creds exported → public test RUNS, authenticated test SKIPS.
- `-m live`, creds exported (local/.env, demo) → BOTH run.

Commands:
1. `poetry run pytest tests/integration/test_okx_connectivity.py -m live -v`
   → BOTH tests run (creds exported via .env; sandbox demo). Both should PASS on a real
     network round-trip. If OKX is unreachable at run time, treat that as an ENVIRONMENT caveat,
     not a code failure. (Equivalently: `make test-live`.)
2. `poetry run pytest tests/integration/test_okx_connectivity.py -m "not live" -v`
   → BOTH deselected (0 selected / all deselected).
3. `poetry run pytest tests/integration/test_okx_smoke.py -v`
   → still collects/passes unchanged (no regression, marker registered).
4. Confirm NO strict-markers/strict-config error and NO filterwarnings=["error"] failure in any
   of the above.
</verification>

<success_criteria>
- `live` marker registered in `pyproject.toml`; `@pytest.mark.live` never trips --strict-markers.
- `tests/integration/test_okx_connectivity.py` exists with Test A (creds-free, `live`) and Test B
  (creds-gated, `live` + `skipif`), lazy connector imports, 4-space indent.
- Test B asserts `connector.sandbox is True` before any network call and does a read-only
  `connector.call(connector.client.fetch_balance())` with `connector.disconnect()` in finally.
- `make test` / `make test-integration` carry `not live`; new distinct `test-live` target runs
  `-m live` and is on `.PHONY`; `test-e2e-live` and `diagnose-okx` untouched.
- The gating matrix holds; no strict-markers/strict-config/filterwarnings failure introduced.
</success_criteria>

<output>
Create `.planning/quick/260703-dob-okx-live-connectivity-marker/260703-dob-SUMMARY.md` when done
</output>
