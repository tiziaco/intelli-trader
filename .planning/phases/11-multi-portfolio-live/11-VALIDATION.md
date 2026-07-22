---
phase: 11
slug: multi-portfolio-live
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: true
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

> Requirement→behavior coverage is pinned below in *Requirement Coverage Targets*; the per-task
> rows bind those to the plan task IDs. The W7 D-25 lifecycle proof (plan 11-11) is the row set
> below; every gate was mutation-tested (see `11-11-SUMMARY.md § Mutation testing`).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-11-01 | 11 | 7 | MPORT-03 | T-11-61 | Two paper accounts with DIFFERENT cash size independently — `qty_A != qty_B` because `cash_A != cash_B` (2:1 exact); one signal fans out to each subscribed portfolio; draining A leaves B able to order | integration (offline) | `poetry run python -m pytest tests/integration/test_multi_portfolio_lifecycle.py -q -k "distinct_account or fans_out or sizes_against or draining"` | ✅ | ✅ green |
| 11-11-02 | 11 | 7 | MPORT-04 | T-11-58 | A fill for A changes A AND leaves B byte-unchanged (asserted both directions on real `Portfolio`s); two portfolios hold independent positions in the same symbol; the durable order row carries the ordering portfolio id | integration (offline) | `poetry run python -m pytest tests/integration/test_multi_portfolio_lifecycle.py -q -k "fill_for or same_symbol or durable_order_row"` | ✅ | ✅ green |
| 11-11-03 | 11 | 7 | MPORT-03 / F-1 / D-08 | T-11-59 / T-11-60 | REAL restart — a second `build_live_system` over the same DB returns BOTH ids from the definition rows; `initial_cash` + `config_json` read off the ROW equal persisted (config by VALUE); strategy subscriptions rebind to the SAME ids so the fan-out still reaches both | integration (Postgres-gated; SKIPs Dockerless) | `poetry run python -m pytest tests/integration/test_multi_portfolio_lifecycle.py -q -k "restart or rebind"` | ✅ | ✅ green |

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

- [x] `tests/integration/test_multi_portfolio_lifecycle.py` — D-25 two-paper-account + restart (MPORT-03/04, F-1/D-08). Delivered by plan 11-11 (10 tests: 8 offline + 2 Postgres-gated). Every gate mutation-tested.
- [x] `tests/integration/test_per_account_exchange_routing.py` — MPORT-07 with a **fake** multi-account venue plugin (F-3: paper cannot prove this). Delivered by plan 11-06; file present, suite green.
- [x] `tests/integration/test_distinct_account_invariant.py` — MPORT-02 at **both** layers (app check + DB unique index). Delivered by plan 11-08; file present, suite green.
- [x] Migration data-movement test for D-09 — **assert the migrated value**, not just non-null. Delivered in `tests/integration/test_p11_migration_chain.py` (plan 11-08 inverted the legacy fallback case to fail-loud); the same value-not-nonnull discipline is re-proven end-to-end by the 11-11 restart test (`config_json` compared by VALUE; mutation M5 confirmed RED).
- [x] Rewrite `test_live_system_okx_wiring.py` / `test_live_portfolio_durable_wiring.py` (they called the deleted `_link_venue_account_to_portfolios`). Delivered by plan 11-09 (deviation 1) — no call sites remain; residual mentions are docstring history only. Suite green.
- [~] Refresh stale prose in `tests/integration/test_early_durable_halt_refusal.py:91` and `tests/integration/test_paper_restart_restore.py:6,15`. `test_early_durable_halt_refusal.py` refreshed (11-09). `test_paper_restart_restore.py:6,15` still references the deleted `_link_venue_account_to_portfolios` / `_venue_account` in its D-23 docstring — a **cosmetic** residual only (the executable test passes; the string is prose). Out of plan 11-11's file scope; carried as doc hygiene.
- [x] New cases on the existing reconciliation-coordinator unit tests (D-20 per-symbol baseline, D-21 evaluate-all, D-22 quarantine). Delivered by plans 11-09/11-10; suite green.
- [x] Framework install: **none needed** — pytest is present.

> `wave_0_complete: true` — every FUNCTIONAL Wave 0 coverage deliverable is present and the full
> suite is green (2813 passed / 6 skipped). The one residual (`[~]`) is a cosmetic docstring in a
> sibling test file, not a coverage gap.

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
