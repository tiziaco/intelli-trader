---
phase: quick-260703-dob
plan: 01
subsystem: testing / OKX live connectivity
tags: [pytest-marker, okx, live, integration, makefile]
requires:
  - itrader.connectors.okx.OkxConnector (existing)
  - itrader.config.okx_settings.OkxSettings (existing)
provides:
  - "`live` pytest marker (PURPOSE axis) registered in pyproject.toml"
  - "tests/integration/test_okx_connectivity.py (public + demo-authenticated live checks)"
  - "make test-live target; default test runs fenced with `not live`"
affects:
  - Makefile test / test-integration targets (now `not live`)
tech-stack:
  added: []
  patterns:
    - "PURPOSE-axis pytest marker orthogonal to folder-derived TYPE marker (mirrors `smoke`)"
    - "lazy connector imports so credential-free/offline collection never touches ccxt.pro"
key-files:
  created:
    - tests/integration/test_okx_connectivity.py
  modified:
    - pyproject.toml
    - Makefile
decisions:
  - "Only the authenticated test carries skipif; both carry `live` — network property (live) and creds property (skipif) kept distinct"
  - "Public test closes the sync ccxt client in a finally defensively against filterwarnings=[error]"
metrics:
  duration: ~6min
  tasks: 2
  files: 3
  completed: 2026-07-03
---

# Quick Task 260703-dob: OKX Live-Connectivity Marker Summary

Added a `live` PURPOSE-axis pytest marker plus a two-test OKX connectivity module
(credential-free public reachability + credential-gated demo authentication), and fenced
the default `make test` / `make test-integration` runs with `not live` while adding a new
`make test-live` opt-in target — so the default suite/CI never makes a network round-trip.

## What Was Built

- **`pyproject.toml`** — registered one new marker in `[tool.pytest.ini_options] markers`
  (4-space indent, matching the `smoke` entry style):
  `"live: Live-venue test — makes a real network round-trip to a live venue; PURPOSE axis..."`.
  This registration is what prevents `@pytest.mark.live` from tripping `--strict-markers`.

- **`tests/integration/test_okx_connectivity.py`** (new, 4-space indent) —
  - Module-level creds gate mirroring `test_okx_smoke.py`
    (`_OKX_ENV_VARS` / `_HAS_OKX_CREDS`), all connector imports LAZY (inside test bodies).
  - **Test A** `test_okx_public_endpoint_reachable` — `@pytest.mark.live` only, NO skipif.
    Lazy `import ccxt`, builds a public `ccxt.okx()` client, `load_markets()`, asserts a
    non-empty market map. Closes the client in a `finally` (defensive vs `filterwarnings=[error]`).
  - **Test B** `test_okx_demo_authenticated_connectivity` — `@pytest.mark.live` **and**
    `@pytest.mark.skipif(not _HAS_OKX_CREDS, ...)`. Builds `OkxConnector(OkxSettings())`,
    asserts `connector.sandbox is True` **before any network call** (T-05-04 guard), then in
    a try/finally does the read-only `connector.call(connector.client.fetch_balance())` —
    the exact shape `VenueAccount.snapshot()` uses — asserting a non-empty dict, and
    `connector.disconnect()` in the `finally` (T-conn-SOCK — no leaked socket).

- **`Makefile`** —
  - `test` → `poetry run pytest tests/ -v -m "not live"`.
  - `test-integration` → `-m "integration and not live"`.
  - New `test-live` target (real TABS) running `poetry run pytest tests/ -v -m live`, with a
    comment noting it is DISTINCT from `test-e2e-live` (fast `-m live` connectivity vs the slow
    `-m slow` recon e2e suite). Added `test-live` to `.PHONY`.
  - `test-e2e-live` and `diagnose-okx` left UNTOUCHED.

## Verification Results

All run on the MAIN checkout with `.env` present. No strict-markers / strict-config /
`filterwarnings=["error"]` failure appeared in ANY run.

| Check | Command | Result |
|-------|---------|--------|
| Live run (creds exported via `.env`) | `set -a; source .env; set +a && poetry run pytest tests/integration/test_okx_connectivity.py -m live -v` | **2 passed** — public + demo-authenticated both PASS against the real OKX demo/public endpoints |
| Deselect (default dev) | `poetry run pytest tests/integration/test_okx_connectivity.py -m "not live" -v` | **2 deselected / 0 selected** |
| No-creds skip | `env -u OKX_API_KEY -u OKX_API_SECRET -u OKX_API_PASSPHRASE poetry run pytest ... -m live -v` | **1 passed (public), 1 skipped (auth skipif fires)** |
| No regression | `poetry run pytest tests/integration/test_okx_smoke.py -v` | collects/skips cleanly (auth-gated; would pass with creds) — no strict/marker error |
| Strict-markers gate | (all runs above) | No "unregistered marker" / strict-config error — `live` registration holds |

Note: the auth test asserts `connector.sandbox is True` before any network call and executed
against the OKX demo venue with a real `fetch_balance` round-trip returning a non-empty dict.

## Deviations from Plan

None — plan executed exactly as written. (Test A's defensive client-close in `finally` was
explicitly anticipated by the plan's ResourceWarning note.)

## Known Stubs

None.

## Commits

- `f3464927` test(quick-260703-dob): register live marker + OKX connectivity tests
- `b97690d5` chore(quick-260703-dob): fence default tests with 'not live' + add test-live target

## Self-Check: PASSED

- FOUND: tests/integration/test_okx_connectivity.py
- FOUND: pyproject.toml `live:` marker entry
- FOUND: Makefile `test-live` target + `not live` fences
- FOUND commit: f3464927
- FOUND commit: b97690d5
