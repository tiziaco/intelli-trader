# Venue / Account / Composition Redesign — Execution Log

**Purpose:** what execution learned that the plan could not know in advance. The plan
(`VENUE-ACCOUNT-REDESIGN-PLAN.md`) remains the authority on sequencing, gating and the
settled decisions ED-1..ED-11 — nothing here overrides it. This file records amendments,
findings and carried-forward dependencies so a later session (or a different agent) does
not re-derive them.

**Status:** Stages 0–3 complete and committed. Next: Stage 4.

| stage | commits | gate state at commit |
|---|---|---|
| 0 | `3a2c7692` | 3028 pass / 6 skip / 4 xfail · baseline 27 / 9,243 / 3,886 |
| 1 | `6d3596dc`, `8497434e` | 3028 pass / 6 skip / 4 xfail · successor +30 |
| 2 | `00afc644` | 3069 pass / 6 skip / 4 xfail · successor +207 |
| 3 | `44d40f71`, `ebf28c7f` | 3053 pass / 6 skip / **3 xfail** · successor **+4** |

CR ledger: **CR-03 fixed (Stage 3)**. CR-01, CR-02, CR-04 still `xfail(strict=True)` in
`tests/integration/test_live_composition_offline.py`.

---

## 1. Amendments to the plan

### 1.1 Appendix omission — one more Stage-3 disposition

`tests/unit/execution/test_supervisor_catchall.py` is NOT in the Test Disposition Table but
its section (2) drove `VenueAccount._stream_account` / `_stream_positions`, which the stage
deletes. Disposed by the table's own rule (mechanism has no successor → DELETE that
section; the `OkxExchange` / provider sections KEEP). Already applied.

### 1.2 ED-10 landed in Stage 3, not Stage 6

Deleting `account/venue.py` left `OkxVenuePlugin.new_account` with nothing to mint.
`build_compute_account(...)` therefore landed in its ED-10 home
(`portfolio_handler/account/simulated.py`) during Stage 3, and both venue arms delegate to
it. **Stage 6 must not re-create it** — only re-point `portfolio_factory.py` at it as
planned.

### 1.3 CR-03's probe asserts the ENUMERATION SOURCE, not the adapter list

`test_cr03_...` reads `system._stream_recovery._accounts()`, not `_streaming_adapters()`.
Deliberate: the offline gate uses a **paper** account, which legitimately carries no
connector and so has no streams to recover — but the handler must still be wired to
something that reports it online. Asserting the filtered adapter list would make the probe
vacuous for paper.

### 1.4 Stage 7's measurement command gains `--gate`

`scripts/measure_redesign_baseline.py` now distinguishes reporting from gating:

```bash
# informational (any stage)
poetry run python scripts/measure_redesign_baseline.py --manifest scripts/redesign_successor_manifest.txt
# the must-have, as an exit code (Stage 7)
poetry run python scripts/measure_redesign_baseline.py --manifest scripts/redesign_successor_manifest.txt --gate
```

Also: `scripts/redesign_successor_manifest.txt` **already exists** and is maintained as
stages land (Stage 7 does not author it, only completes it). See §3.1 for why.

### 1.5 Coordinator surface already reduced

`ReconciliationCoordinator._exchange_for` and its `execution_handler` ctor param were
deleted in Stage 3 as dead code (the adapter now comes off `record.bundle.exchange`). Stage
6 plans no work here, but any Stage-6 rewrite of the construction site should not
re-introduce them.

### 1.6 Manager gained `online_records()`; facade holds `_venue_manager` privately

`VenueAccountManager.online_records()` is the one enumeration the safety and reconcile
planes read. Stage 4 must carry it into `venues/accounts.py`.

The facade already holds `_venue_manager` **privately** (the reconcile coordinator needs it
at `start()`). CR-01 is about the **public** operator surface (`system.venue_accounts`) plus
required constructor arguments — still Stage 6, still red.

---

## 2. Carried-forward dependencies

### 2.1 Stage 5 — OKX public sessions need a credential-free client arm (BLOCKING)

`ConnectorPool.public_session(venue)` is implemented and unit-tested, but
`build_okx_connector(spec=None)` **raises `NotImplementedError`**:
`OkxConnector._build_client` reads all three `OKX_API_*` fields unconditionally, so there is
no credential-free construction to return.

The refusal is deliberate — silently returning an authenticated session under a public name
would recreate, invisibly, the borrowed credentialed session that public sessions exist to
remove. Stage 5 (data adapter over its own public session, CR-02) therefore needs a public
arm in the client build. Tested refusal:
`tests/unit/connectors/test_okx_connector_recipe.py::test_a_public_session_is_refused_loudly_rather_than_returned_authenticated`.

### 2.2 Stage 5 candidate — `catch_up_missed_fills` is not on the adapter contract

`StreamRecoveryHandler.on_reconnect` calls `catch_up_missed_fills()` on every
connector-bearing adapter, but the method is not declared on `AbstractExchange`. It fails
safe today (a missing method lands in the stay-paused + CRITICAL-alert arm), yet the resume
contract is duck-typed rather than declared — the same gap D-5 just closed for
`set_halt_signal`. Worth folding into Stage 5's D-5-style pass.

### 2.3 Stage 6 — `('paper', 'default')` is registered unconditionally

`compose_engine` registers the compute venue's baseline exchange under
`(paper, 'default')` on **every** arm, independent of any durable `venue_accounts` row. On
the live arm that means the default paper account is order-routable with no provisioned row.

Not one of the four Criticals and not in the plan's scope, but Stage 6 rewrites both roots,
so it is a decision point rather than something to preserve by accident. The offline gate
asserts around it (object distinctness), documented in the test.

### 2.4 Stage 6 — WR-03 is observable through the built system

`add_portfolio` on a SQL spine refuses an unprovisioned account with `IntegrityError` from
the composite FK, **not** `VenueAccountNotProvisionedError`: the durable insert runs before
the authority validates. `test_a_portfolio_naming_an_unprovisioned_account_is_refused` is
deliberately type-open (asserts "raises, and no portfolio/row survives") and must be
**tightened to the typed error** when Stage 6 closes WR-03.

### 2.5 Behaviour change to be deliberate about

The startup venue reconcile now runs for every account the manager reports ONLINE,
including one no portfolio holds (it was portfolio-driven, and inert, before). This is
consistent with the reconcile being store-intent-vs-venue and account-scoped, but it means
the `orders` table must exist for any online account —
`tests/integration/test_live_system_okx_wiring.py` provisions it explicitly for this reason.

---

## 3. Process findings (things that bit, so they do not bite again)

### 3.1 The baseline manifest under-reports mid-refactor — a false-green

Code RELOCATED into a new module leaves the baseline manifest without being deleted. At
Stage 1 that silently dropped the measured total to 9,079 / 3,782, which reads as ~100 lines
of progress toward the must-have bought entirely by a move.

Mitigations, all in place: `BASELINE_TOTALS` pins `(27, 9243, 3886)` as a historical fact;
the default manifest says loudly when it stops reproducing them; the successor manifest is
maintained as stages land so the sign is observable throughout (plan risk #3 wants a
trending-positive Stage 6 caught *before* Stage 7).

### 3.2 Scripted replacements must assert, and indentation is per file

Four `str.replace` edits against `portfolio_handler.py` silently no-op'd because they were
written with tabs and the file is 4-space. `str.replace` does not error on a miss. Every
scripted edit should assert the pattern was found and is unambiguous. Measure the file
(`grep -c $'^\t' <file>`); never infer from a sibling.

### 3.3 A broad regex on production code caused ~31 spurious failures

`re.sub(r"\n\s*execution_handler=[^,\n]*,", "", s)` intended for the coordinator also
stripped the argument from `ConfigRouter` and `layer_persisted_overrides`. Scope such edits
to one known call site, or assert the match count.

### 3.4 `git checkout <file>` reverts the whole file, not one hunk

Used to undo a temporary negative-control edit in `okx_plugin.py`, it also discarded two
real, uncommitted changes in the same file. Prefer a targeted inverse edit while a stage is
mid-flight and uncommitted.

### 3.5 Grep BOTH trees for every moved or deleted name

`test_config_restart_layering.py` imported `_layer_persisted_overrides` by name and broke
collection after the Stage-1 move; the initial sweep had covered `itrader/` only.

### 3.6 A green suite did not catch a real wiring defect

The spec→adapter gap in §1.1 of the Stage-3b commit (`quote`/`market_type`/`symbol`
computed but never passed to `OkxExchange`) passed the full suite, mypy and both oracles. It
lived in the gap between "the adapter derives correctly" (unit-tested) and "the plugin wires
it" (untested). A subagent review found it. Where a stage adds constructor parameters,
assert at the CONSTRUCTION SITE that they are threaded, and verify the new test is
load-bearing by reverting the fix.

---

## 4. Verification commands (the gate battery, as run)

```bash
# G1/G2/G3/G4 — oracles (both arms), inertness, offline composition
poetry run pytest tests/integration/test_backtest_oracle.py \
                 tests/integration/test_backtest_oracle_factory_arm.py \
                 tests/integration/test_okx_inertness.py \
                 tests/integration/test_live_composition_offline.py -q
# G5
poetry run mypy
# G6  (never `make test` — it exports ITRADER_DISABLE_LOGS and aborts in worktrees)
poetry run pytest tests -q
# measurement (informational until Stage 7)
poetry run python scripts/measure_redesign_baseline.py --manifest scripts/redesign_successor_manifest.txt
```
