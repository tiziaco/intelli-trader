# Phase 3: M2b — Config, Types, Storage Seam & Oracle Re-Freeze - Context

**Gathered:** 2026-06-05
**Status:** Ready for planning

<domain>
## Phase Boundary

The **structural cleanup + numerical re-baseline** phase. After M2a made money Decimal and IDs
UUIDv7 (behavior-preserving), M2b does the following across eight locked requirements
(M2-06…M2-13), all **behavior-preserving against the M1 behavioral oracle**:

1. **Config collapse (M2-06, #12/#13)** — replace the 3,380-line `config/` package with Pydantic v2
   models + a minimal `pydantic-settings` layer; completes the `#34`/TD2 dual-config span.
2. **Type centralization (M2-07, #15)** — centralize shared enums in `core/enums`; replace scattered
   string→enum map dicts + their buggy `ValueError`s.
3. **Portfolio storage seam (M2-08, #18)** — route portfolio-manager state through an in-memory
   storage seam mirroring the order-storage pattern; decide durable record shapes (Postgres → D-sql).
4. **Order/transaction timestamp determinism (M2-09, #19)** — event-derived timestamps;
   `modify_order` through the validated `add_state_change` path.
5. **time_parser finalization (M2-10, #36)** — correct `check_timeframe` anchoring and `to_timedelta`;
   completes the `#36` M1→M2 span.
6. **Dead-module purge (M2-11)** — delete `legacy_config.py`, `outils/profiling.py`,
   `outils/strategy.py`, the orphaned duplicate `screener_event_handler.py` `EventHandler`.
7. **Bulk pytest conversion (M2-12, #40)** — finish the `unittest`→pytest migration on M1's skeleton.
8. **Oracle re-freeze (M2-13)** — re-freeze the numerical oracle after the Decimal shift; behavioral
   oracle verified unchanged. **The golden-master gate.**

The WHAT is fully locked by `REQUIREMENTS.md` (M2-06…M2-13) and ROADMAP Phase 3's four success
criteria. This discussion resolved only the **HOW**.

**Golden-master position:** M2b is **behavior-preserving** — the behavioral oracle (trade timing +
sides + sequence + `pair` + `trade_count`) stays asserted **byte-exact and active** throughout. M2b
is **numerically inert by design** (no change touches money math); the *only* change with any oracle
risk is the `time_parser` epoch-anchor (it decides strategy/screener firing). M2-13 is one of
PROJECT.md's **two sanctioned re-baseline points** — it closes the M2a transitional window (D-15) and
the DEF-02-08-A deferral by re-freezing the numerical oracle **exact** and removing all tolerance.

**Boundary with adjacent milestones (do NOT pull forward):**
- **M3 (Phase 4)** owns: event immutability + `event_id` + linkage IDs + dispatch registry + the
  **`EventType` redesign** (real field, dedicated error type, #11). M2b leaves `EventType` inline.
- **M4 (Phase 5)** owns: cash-through-`CashManager` (#22), atomic transactions + rollback (#16 — the
  `TransactionState` rework), DEF-01-A commission reconciliation. M2b only *relocates* `FillStatus`
  and routes state through the storage seam — it does NOT change cash-flow routing or transaction
  correctness.
- **M5b (Phase 7)** owns: `calculate_signal` contract (#24), universe collapse (#33), reporting
  split + `EngineLogger` delete (#38/#14). M2b does not touch reporting computation.

</domain>

<decisions>
## Implementation Decisions

### Config collapse (M2-06, #12/#13)
- **D-01: Clean break on the public config API.** Delete `core/registry.py`, `core/provider.py`,
  `core/validator.py`, every `schema.py`, the `to_dict`/`from_dict` machinery, the mtime hot-reload,
  AND the `config/__init__.py` getters (`get_config_registry`, `get_*_config_provider`). Rewire the
  ~4 in-scope call sites (`itrader/__init__.py`, `portfolio_handler.py`, `execution_handler.py`)
  to construct Pydantic models directly. No vestigial compat shim — the surface is small and
  `mypy --strict` catches any missed site. End-state target ~600–900 lines.
- **D-02: Minimal `Settings(BaseSettings)` stub.** Build `Settings(BaseSettings)` with the fields the
  backtest path actually reads (timezone, log_level, environment). Declare secrets (DB URL, API keys)
  as **required-no-default** `SecretStr`/`Optional` so they **fail loud** if live ever runs — but do
  NOT wire DB/exchange auth (that's D-live). This satisfies M2-06's "no working secret defaults"
  without building live infrastructure that won't run in this program.
- **D-03: Reference-data literals → `core/constants.py`; presets → factory classmethods.**
  `FORBIDDEN_SYMBOLS`, `SUPPORTED_CURRENCIES`/`SUPPORTED_EXCHANGES` are not deployment config → move
  to a plain `core/constants.py`. Convert domain presets (`presets.py`/`defaults.py`) to Pydantic
  model factory classmethods (e.g. `PortfolioConfig.default()`). One source of truth per the #13
  table. Fix the `'BTG/USDT' 'USDP/USDT'` implicit-concat literal bug while moving them.

### Type centralization (M2-07, #15)
- **D-04: Relocate + de-map only — keep the three lifecycle vocabularies DISTINCT.** Centralize each
  shared enum in `core/enums`; replace the scattered string→enum dicts (`transaction_type_map`,
  `event_type_map`, `fill_status_map`) and their buggy `ValueError('Value %s', x)` with a
  `_missing_`/`from_string` classmethod **on the enum** (case-insensitive parse, raise a real f-string
  error on unknown). **Do NOT merge** `OrderStatus`/`FillStatus`/`TransactionState` — they model
  different domain boundaries (exchange report vs order-mirror lifecycle vs portfolio-processing
  state); the `FillStatus.EXECUTED → OrderStatus.FILLED` mapping in `order_manager` *is* the intended
  exchange-truth→mirror reconciliation and must be preserved. Merging would lose REFUSED-vs-REJECTED
  and partial-fill semantics and collide with M3/M4. Satisfies M2-07, behavior-preserving, oracle-safe.
- **D-05: Move `FillStatus` now, leave `EventType` for M3.** Relocate `FillStatus` (and the inline
  manager category enums — `CashOperationType`, `PositionEvent`, `MetricsPeriod`, `TransactionState`)
  to `core/enums`. Leave `EventType` inline in `event.py` — M3 (#11) reworks its definition (real
  field, dedicated error type) anyway, so moving it now just creates churn M3 redoes. Minimizes the
  M2b/M3 collision.

### time_parser finalization (M2-10, #36)
- **D-06: Epoch-anchoring now, isolated in one replaceable seam.** `check_timeframe` uses
  `int(ts.timestamp()) % tf == 0` (Unix-epoch anchor) as the single policy, isolated in ONE
  well-named function (e.g. `_aligned(ts, tf)`) so a future session/exchange-calendar anchor can
  replace it without rewriting firing logic. Epoch is DST-immune, correct for 24/7 crypto and for
  *daily* bars, and **oracle-safe**: it fires on the same UTC bars regardless of the `Europe/Paris`
  display tz, reproducing the golden SMA_MACD schedule exactly. **Market-tz local anchoring is
  rejected** — it would shift the 00:00-UTC golden bars to 01:00 Paris and break the behavioral oracle.
- **D-07: UTC-everywhere + tz-for-display is the permanent foundation.** Store/compute instants in UTC
  (epoch); render in `config.TIMEZONE`. This holds for both crypto and (future) stocks — stocks add a
  *session/exchange-calendar* layer, not a change to this foundation.
- **D-08: `to_timedelta` case-insensitive, support `w`, raise on `M`/unknown.** Make it
  case-insensitive (`1H`/`1D`/`1W` work), add `w` (week), and **raise** a clear error on `M` (month —
  not a fixed timedelta) and on any unknown unit (no silent `None`). Delete the dead buggy helpers
  (`format_timeframe`, `elapsed_time`, `round_timestamp_to_frequency`); fix the tab/space mix. Guard
  `timeframe is None`.

### Portfolio storage seam (M2-08, M2-09, #18/#19)
- **D-09: One unified `PortfolioStateStorage` in a peer `portfolio_handler/storage/` package.**
  Cohesion is high (single `Portfolio` aggregate; a fill mutates cash + position + transaction
  together), so a single interface covering transactions/positions/cash-ops/metrics — with one
  in-memory backend per `Portfolio` and one factory entry, mirroring `order_handler/storage/` — beats
  four separate interfaces (which would be 4× wiring for speculative swap-granularity; D-sql is one
  Postgres backend). The `storage/` package stays a **peer** of the subdomain folders — do NOT put a
  storage class inside each manager folder (that drifts back toward four interfaces).
- **D-10: Full mirror of the order pattern — route ALL manager state through the seam.** Working state
  (open positions, reserved cash) AND append-only records (transaction history, closed positions,
  cash operations, metrics snapshots) route through the seam, exactly as order storage holds active +
  historical orders. The single-threaded in-memory backend stays dict-fast; live persistence later is
  a pure backend swap (no working-state-routing left to do).
- **D-11: Per-subdomain subpackage reorg, as isolated pure-move commits.** Restructure
  `portfolio_handler/` into subdomain packages: `position/` (`position.py` + `position_manager.py`),
  `transaction/` (`transaction.py` + `transaction_manager.py`), `cash/` (`cash_manager.py` + its
  entities), `metrics/` (`metrics_manager.py` + snapshot entities), plus the peer `storage/`. This
  also rehomes the inline #15 manager dataclasses (`CashOperation`, `PositionMetrics`, snapshots).
  Golden-master-neutral (pure `git mv`), but **moderate import churn** (~13 sites for `transaction`).
  Do it as **standalone behavior-preserving commits, separate from the storage-seam logic and
  separate from the pytest move**, so any break is bisectable. Folders named by subdomain (`position/`,
  not `position_manager/`).
- **D-12: Timestamp determinism (M2-09).** Thread the real event/fill time through
  `add_state_change` (default to event time, never `datetime.now()`); route `add_fill`'s `fill_time`
  to the recorded transition timestamp; route `modify_order` through the single validated
  `add_state_change` path (remove the duplicated direct append). Transaction record timestamps are
  likewise event-derived. Uses M2a's injected clock mechanism (D-10 from Phase 2 deferred this site
  here). Decide the durable record shapes (Decimal money, UUID ids, event-time) — no DB code.

### pytest conversion + restructure (M2-12, #40)
- **D-13: Full restructure to `tests/{unit,integration}` split-by-type.** Move `test/` → `tests/`,
  split by *type* (`unit/` mirrors the package; `integration/` holds the cascade + smoke + oracle
  tests), layered conftests, and rework M1's `test/conftest.py` `DIR_MARKERS`/`testpaths` from
  path-segment-**domain** to folder-derived **type** markers. This matches the M2-12 requirement
  wording and structurally fixes the current marking gap (component dirs get a domain marker but
  neither `unit` nor `integration`, and `test_backtest_smoke.py` is mislabeled `unit`). Mechanical,
  behavior-preserving: `git mv` to preserve history, **same test count + green suite at every commit**,
  no source/test-content change beyond the `unittest`→pytest mechanics.
- **D-14: Convert ALL remaining `unittest.TestCase` files, file-by-file.** As each file moves into
  `tests/unit|integration`, convert `TestCase`→functions/fixtures, `setUp`→fixtures,
  `self.assertX`→`assert`, `assertRaises`→`pytest.raises`; one file per commit asserting identical
  test count. **No big-bang.** Watch `filterwarnings=["error"]` — fix any surfaced `ResourceWarning`
  at the leak, never widen the filter.
- **D-15: unit/integration boundary = "more than one collaborating component."** **Unit** = drives
  ONE component in isolation and asserts *its* behavior (may import several classes from its own
  domain + use a real `global_queue`). **Integration** = asserts interaction *across* components —
  cross-domain (filled order → transaction), cross-manager within a domain (transaction → position →
  cash), OR the full engine/cascade. The line is "more than one collaborating component," not "more
  than one file/class." Document it in the conftests/README.

### Oracle re-freeze (M2-13) — the golden-master gate
- **D-16: Byte-exact re-freeze, all tolerance removed.** After every other M2b change lands,
  regenerate `test/golden/{trades,equity}.csv` + `summary.json` from the run; assert BOTH behavioral
  identity AND numeric columns (`final_cash`/`final_equity`/`total_realised_pnl`/`total_equity`)
  **byte-exact** henceforth; delete the D-15 transitional tolerance and the DEF-02-08-A skip. This
  reaches D-13's (Phase 1) end-state — no float tolerance — achievable because the deterministic
  Decimal run reproduces exactly. **The re-freeze is the LAST step of the phase.**
- **D-17: Strict inertness gate before re-freeze.** Capture the M2a-end oracle output as a reference
  at M2b start; require the M2b-end run to equal that reference **byte-exact (behavioral AND
  numeric)** before re-freezing — proving the structural changes are numerically inert and isolating
  any `time_parser` firing shift. Any non-zero diff **BLOCKS** the re-freeze pending owner explanation,
  logged as a COVERAGE-INDEX §E delta. (The expected numeric value is the already-characterized M2a
  Decimal-end number, not a new M2b number.)
- **D-18: Behavioral identity stays byte-exact and active throughout.** `test_oracle_behavioral_identity`
  (trade timing/sides/sequence/`pair`/`trade_count`) remains a hard active assertion at every M2b
  commit. If the `time_parser` epoch-anchor change moves the firing schedule, that is a **STOP /
  investigate** — never a reason to re-baseline behavior.

### Claude's Discretion
- Exact Pydantic model field definitions, validators (`Field(gt=0, le=1)`, `@field_validator`), and
  the `model_validate`/`model_dump(mode="json")` round-trip plumbing.
- The `_missing_` vs explicit `from_string` classmethod choice per enum, and exact error messages.
- The `PortfolioStateStorage` method signatures and the in-memory backend's internal structures.
- Layered-conftest fixture placement (root vs `unit/` vs `integration/`), fixture naming-by-intent,
  and the marker registration home (`pyproject.toml markers` list vs `pytest_configure` in conftest —
  pick exactly ONE, never both).
- Dead-module deletion (M2-11) is mechanical — verify zero in-scope importers before each delete.
- Sequencing of the structural moves within the phase (config / enums / time_parser / storage seam +
  reorg / pytest move / dead-code), provided the oracle re-freeze (D-16/D-17) is strictly LAST.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REFACTOR-BRIEF.md` — program goal/scope, locked decisions (Decimal money, UUIDv7),
  golden-master discipline, definition-of-done
- `.planning/COVERAGE-INDEX.md` — all 105 items → milestone (the coverage contract); §E logs
  gap-discovery deltas (the D-17 inertness-gate blocker, if triggered, logs here)
- `.planning/PROJECT.md` — milestone breakdown, two-point numerical-oracle re-baseline rule,
  Out-of-Scope tags (D-live/D-sql/D-screener/D-oanda)
- `.planning/REQUIREMENTS.md` — **M2-06…M2-13** (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 3 goal + 4 success criteria

### Architecture findings driving this phase
- `.planning/codebase/ARCHITECTURE-REVIEW.md` — **#12** (pydantic-settings/secrets), **#13** (config
  package collapse), **#15** (type placement / centralize enums / drop scattered maps), **#18**
  (portfolio storage seam), **#19** (order audit + deterministic timestamps), **#36** (`time_parser`
  timing bugs), **#40** (pytest migration + restructure), **#34** (the dual-config span this completes).
  Boundary refs (do NOT pull forward): **#11** (event/`EventType` redesign — M3), **#16/#22** (txn
  correctness / CashManager — M4), **#14/#38** (reporting — M5b).
- `.planning/codebase/CONCERNS.md` — KB21 (`time_parser`), TD4/TD5/KB14 (dead modules).

### Phase carry-forward (constrains M2b)
- `.planning/phases/02-m2a-identity-money-determinism/02-CONTEXT.md` — **D-15** (behavioral-exact +
  bounded transitional numerical tolerance, re-frozen EXACT at M2b — this phase), **D-10** (order-audit
  & transaction-timestamp determinism deferred to M2b/SC2 — see D-12 above), **D-01…D-04** (Decimal
  quantization policy — money fields already Decimal; cash routing is M4), **D-05/D-06** (config is
  in-scope for `mypy --strict`; `make typecheck` gate already standing — the Pydantic collapse MUST
  land strict-clean).
- M2a numeric drift / DEF-02-08-A is recorded in `test/test_integration/test_backtest_oracle.py`
  (the ~1.5e-6 rel Decimal drift the M2b re-freeze closes).
- `.planning/phases/01-m1-ignition-lock-the-oracle/01-CONTEXT.md` — D-12 (oracle excludes integer-ID
  values + wall-clock/audit timestamps → timestamp-determinism is oracle-safe), D-13 (exact-baseline,
  re-baselined only after M2 & M5).

### Existing patterns to mirror / golden assets
- `itrader/order_handler/storage/` — `OrderStorage` + `in_memory_storage.py` + `storage_factory.py`:
  the template for the unified `PortfolioStateStorage` (D-09/D-10).
- `test/conftest.py` — M1's skeleton (path-based auto-marking + shared fixtures) the pytest
  restructure reworks (D-13).
- `test/golden/{trades,equity}.csv` + `summary.json` — the oracle re-frozen at the end of this phase.
- `test/test_integration/test_backtest_oracle.py` — the behavioral/numeric split assertions
  (D-16/D-17/D-18 modify these).
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — the golden dataset (UTC-stamped, 1d).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `itrader/order_handler/storage/{base.py,in_memory_storage.py,storage_factory.py}` — the exact
  factory + interface + in-memory pattern to generalize into `portfolio_handler/storage/`.
- `itrader/portfolio_handler/{position,transaction}.py` — entities ALREADY in own modules (#15's
  entity-separation is partly done); the reorg (D-11) groups them with their managers.
- `itrader/core/enums/order.py` — `OrderStatus` + `VALID_ORDER_TRANSITIONS` already centralized; the
  home for relocated `FillStatus` + manager enums (D-04/D-05).
- M2a's injected `Clock` (`itrader/core/clock.py`) — the mechanism D-12 applies to order/txn timestamps.
- `itrader/config/` (3,380 lines across ~21 files) — collapsed to ~600–900 lines of Pydantic models.

### Established Patterns
- Queue-only cross-domain communication; handler/manager split; `on_<event>` callbacks.
- **Tab indentation** in handler modules; **spaces** in `config/` and newer modules — match the file.
  (Pydantic models are new code → spaces; the storage seam mirrors order storage's style.)
- `pyproject.toml` is the single source of truth for deps + test config + mypy config; the
  `make typecheck` (mypy --strict) gate is live and the config collapse must pass it.
- `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` — any warning/unregistered marker
  fails the suite (critical for the pytest restructure).

### Integration Points
- Config consumers (clean-break rewire, D-01): `itrader/__init__.py:1-7`,
  `portfolio_handler.py:24,56`, `execution_handler.py:10,63`. `config.TIMEZONE` readers:
  `time_parser.py`, `data_provider.py`, `CCXT.py` (latter two are D-oanda/D-sql-adjacent).
- Enum/map sites (D-04/D-05): `event.py:10-13,22,407` (`EventType`/`FillStatus`/`fill_status_map`),
  `transaction.py:9,80` (`transaction_type_map`), the four portfolio managers' inline enums.
- `time_parser.py` (D-06/D-08): gates `strategies_handler.py:46`, `screeners_handler.py:72`;
  `to_timedelta` feeds `data_provider.py:112`, `CCXT.py:79`.
- Storage seam (D-09/D-10): the four managers' state containers —
  `transaction_manager.py:60-61` (`_pending_transactions`, `_transaction_history`),
  `position_manager.py:72` (`_closed_positions` + open index), `cash_manager.py:67,70`
  (`_reserved_cash`, `_cash_operations`), metrics snapshots — route through `PortfolioStateStorage`,
  injected by `Portfolio`.
- Timestamp determinism (D-12): `order.py` `add_state_change` (`:253,262,269` `datetime.now()`),
  `add_fill` (`:282` `fill_time`), `modify_order` (`:419-427` direct append to remove).
- pytest restructure (D-13): `test/` tree (37 files, ~32 on unittest), `test/conftest.py` `DIR_MARKERS`,
  `pyproject.toml:41` `testpaths`, `:56` `markers`, the Makefile test targets.
- Oracle re-freeze (D-16/D-17): `test/golden/*`, `test/test_integration/test_backtest_oracle.py`,
  the `scripts/run_backtest.py` run path.

</code_context>

<specifics>
## Specific Ideas

- User intends to **trade stocks** with this framework eventually. This validated the time_parser
  decision: keep **UTC-everywhere + tz-for-display** as the permanent foundation (correct for both
  crypto and stocks), use epoch-anchoring now, and isolate it as a replaceable seam so a future
  **session/exchange-calendar anchor** (for intraday stock bars aligning to e.g. a 9:30 ET open,
  holidays, half-days) can slot in. Stocks add a calendar *layer*, not a change to the UTC foundation.
  See Deferred Ideas.
- User proposed and confirmed the **per-subdomain subpackage reorg** of `portfolio_handler/`
  (`position/`, `transaction/`, `cash/`, `metrics/` + peer `storage/`) for clarity/separation of
  concerns — confirmed compatible with (and orthogonal to) the unified-storage decision, with the
  refinement that storage stays a peer package (not inside each manager folder).
- User reasoned that integration tests already exist scattered across the by-domain test modules
  (confirmed: `test_backtest_smoke.py` mislabeled `unit`, `test_event_wiring.py` under `events`),
  which is precisely why the **full type-based restructure** is warranted — type and domain are
  orthogonal axes that collide when type is derived from domain location.
- User asked whether merging the three lifecycle enums would be "more correct"; after seeing concrete
  Option-A vs Option-B examples, locked **relocate-only** — the merge is a domain-modeling regression
  (conflates exchange-report vs order-mirror vs portfolio-processing boundaries).

</specifics>

<deferred>
## Deferred Ideas

- **Stock support — session / exchange-calendar alignment** (trading-calendar holidays/half-days,
  intraday bars anchored to the session open rather than epoch). The time_parser anchor (D-06) is
  built as a single replaceable function specifically so this plugs in later. A separate, additive
  concern — out of scope for the backtest-correctness program (no stock data; BTCUSD only). Likely a
  future milestone, not M2–M5.
- **`EventType` relocation to `core/enums`** → **M3 (Phase 4, #11)**, folded into the event-schema
  redesign. M2b leaves it inline to avoid move-then-rework churn.
- **`TransactionState` rework + atomic transactions/rollback** → **M4 (#16)**. M2b only relocates the
  enum and routes state through the storage seam; it does not fix the write-only state machine.
- **Cash-through-`CashManager` (#22) + DEF-01-A commission reconciliation** → **M4**.
- **Postgres/JSONB backend for `PortfolioStateStorage`** → **D-sql persistence milestone**. M2b ships
  only the in-memory backend behind the unified interface (durable record shapes decided now).
- **Reporting split + `EngineLogger` delete (#14/#38), universe collapse (#33), `calculate_signal`
  contract (#24)** → **M5b (Phase 7)**.
- **General per-cryptocurrency precision registry** (carried from M2a) — only BTCUSD traded; the
  default+override quantization lookup is trivially extensible later.

None — discussion stayed within phase scope (the stock/UTC question informed the in-scope time_parser
decision rather than expanding scope).

</deferred>

---

*Phase: 3-m2b-config-types-storage-seam-oracle-re-freeze*
*Context gathered: 2026-06-05*
