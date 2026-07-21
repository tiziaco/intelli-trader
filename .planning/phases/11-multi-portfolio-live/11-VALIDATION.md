---
phase: 11
slug: multi-portfolio-live
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-21
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `11-RESEARCH.md` § Validation Architecture. The Per-Task Verification Map is
> filled by `/gsd-validate-phase` once plan task IDs exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/portfolio tests/unit/execution -x -q` |
| **Full suite command** | `poetry run pytest tests -q` |
| **Estimated runtime** | ~30 seconds (full suite); quick run ~8 seconds |

**Phase gates (must stay green — restated, not re-decided):**

| Gate | Command |
|------|---------|
| Backtest oracle byte-exact (`134 / 46189.87730727451`) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` |
| OKX import inertness | `poetry run pytest tests/integration/test_okx_inertness.py -q` |
| Static typing | `poetry run mypy` (strict, `files = ["itrader"]`) |

**Strictness:** `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config` — any
unexpected warning fails the suite, and every marker used must be declared (`unit`, `integration`,
`slow`, `e2e` auto-applied by folder via `tests/conftest.py`; `smoke`, `live` hand-applied).

**Environment gotchas (repo-learned):**
- `make test` exports `ITRADER_DISABLE_LOGS=true`, which breaks `caplog` warning-assertion tests —
  use `poetry run pytest` as the gate, not `make test`.
- In git worktrees `make test` aborts on a missing `.env`; use `poetry run pytest tests` there and
  prepend `PYTHONPATH="$PWD"` to defeat editable-install shadowing.

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/<touched-domain> -x -q`
- **After every task commit in W3/W4 — additionally the oracle gate.** These waves touch
  `add_portfolio` and `ExecutionHandler`, both of which are **backtest-shared**; drift there is the
  phase's primary oracle risk and must be caught per-commit, not per-wave.
- **After every plan wave:** `poetry run pytest tests -q` + oracle gate + inertness gate
- **Before `/gsd-verify-work`:** full suite green + oracle byte-exact + inertness green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Populated by `/gsd-validate-phase` after plans exist. Requirement→behavior coverage is pinned
> below in *Requirement Coverage Targets*; the per-task rows bind those to plan task IDs.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | MPORT-{XX} | T-11-{XX} / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Requirement Coverage Targets

| Req | Behavior | Type | Command | Exists? |
|---|---|---|---|---|
| MPORT-01 | `new_account()` mints per-portfolio account; link fn deleted | integration | `pytest tests/integration/test_live_system_okx_wiring.py -q` | ❌ **rewrite** (calls deleted fn at `:292,319`) |
| MPORT-01 | `VenueAccount` requires `account_id` (TypeError without) | unit | `pytest tests/unit/portfolio/test_account_*.py -q` | ❌ W0 |
| MPORT-02 | duplicate `(venue, account_id)` refuses to start | integration | new `tests/integration/test_distinct_account_invariant.py` | ❌ W0 |
| MPORT-02 | DB unique index rejects out-of-band duplicate | integration | new, in the store test | ❌ W0 |
| MPORT-03 | signal fans out; each portfolio sizes vs its own account | integration | new `tests/integration/test_multi_portfolio_lifecycle.py` (D-25) | ❌ W0 |
| MPORT-04 | `client_order_id` rename; wire spelling preserved (`clOrdId`) | unit | `pytest tests/unit/execution -k client_order_id -q` | ❌ W0 |
| MPORT-04 | fill routes to the correct `Portfolio.on_fill` | integration | in the D-25 lifecycle test | ❌ W0 |
| MPORT-05 | `PortfolioSpec.account_id`; coordinator iterates portfolios | unit + integration | `pytest tests/unit/portfolio/test_reconciliation_coordinator*.py -q` | ⚠️ file exists, needs new cases |
| MPORT-05 / F-2 | baseline guard evaluates **all** portfolios (no first-mismatch return) | unit | new case asserting N mismatches all reported | ❌ W0 |
| MPORT-06 | connectors keyed `(venue, account_id)` | unit | `pytest tests/unit -k connector_provider -q` | ⚠️ memo already tested; add per-account credential case |
| **MPORT-07** | `exchanges` keyed on pair; account B's order never hits A's session | integration | new `tests/integration/test_per_account_exchange_routing.py` — **fake multi-account plugin, NOT paper** (F-3) | ❌ W0 |
| F-1 | `portfolio_id` supplyable + stable across restart | integration | in the D-25 restart test | ❌ W0 |
| D-09 | config blob survives the migration **byte-identical** | integration | new migration test — **assert on the VALUE**, never `is not None` | ❌ W0 |
| D-29 | single Alembic head; `create_all`/migration parity | integration | existing chain-parity gate — **extend by hand** (dynamic enumeration was false in P9) | ⚠️ extend |
| Gate | oracle byte-exact `134 / 46189.87730727451` | integration | `pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists |
| Gate | OKX import inertness | integration | `pytest tests/integration/test_okx_inertness.py -q` | ✅ exists |

---

## Wave 0 Requirements

- [ ] `tests/integration/test_multi_portfolio_lifecycle.py` — D-25 two-paper-account + restart (MPORT-03/04/05, F-1)
- [ ] `tests/integration/test_per_account_exchange_routing.py` — MPORT-07 with a **fake** multi-account venue plugin (F-3: paper cannot prove this — `live_trading_system.py:1473` hands `PaperVenuePlugin` the single `exchanges['simulated']` object, so both paper accounts necessarily resolve to one exchange)
- [ ] `tests/integration/test_distinct_account_invariant.py` — MPORT-02 at **both** layers (app check + DB unique index)
- [ ] Migration data-movement test for D-09 — **assert the migrated value**, not just non-null (a warning-only degrade-clean at `live_trading_system.py:1268` means lost config yields a green suite and silently default-config portfolios)
- [ ] Rewrite `tests/integration/test_live_system_okx_wiring.py:292,319` and `tests/integration/test_live_portfolio_durable_wiring.py:148` (they call the deleted `_link_venue_account_to_portfolios`)
- [ ] Refresh stale prose in `tests/integration/test_early_durable_halt_refusal.py:91` and `tests/integration/test_paper_restart_restore.py:6,15`
- [ ] New cases on the existing reconciliation-coordinator unit tests (D-20 per-symbol baseline, D-21 evaluate-all, D-22 quarantine)
- [ ] Framework install: **none needed** — pytest is present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-venue two-account routing on OKX demo | MPORT-07 | The EEA demo sub-account cannot reach a fill (only BTC/USDC & ETH/USDC tradeable, both pre-seeded non-flat, sells blocked by price-floor > best-bid) and only one demo account exists — a second live account is not available to this project | Deferred to the milestone owner. The automated `test_per_account_exchange_routing.py` fake-plugin gate is the in-repo proof; real-venue confirmation is out of scope for P11 and not a phase gate. |
| Venue-UID trust-on-first-use assertion (D-04) against a real venue | MPORT-01 | Requires a real authenticated `connect()` against two distinct venue accounts | Observe-only by design (CRITICAL alert, never halts). Automated coverage asserts the alert fires on a simulated UID mismatch; real-venue observation is operator-side. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] Oracle gate byte-exact and inertness gate green at every wave merge
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
