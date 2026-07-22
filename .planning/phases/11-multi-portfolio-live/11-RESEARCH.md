# Phase 11 ★: Multi-Portfolio-Live - Research

**Researched:** 2026-07-21
**Domain:** Live multi-account portfolio wiring — per-`(venue, account_id)` account/connector/exchange
cardinality, durable portfolio definition + rehydrate, per-portfolio reconciliation, two-key attribution
**Confidence:** HIGH (all findings verified directly against the working tree; zero external dependencies
researched — the phase is entirely internal refactor + schema work under a zero-new-dependency gate)

---

## Summary

This is a **brownfield internal-architecture phase with no external technology surface**. There is no
library to choose, no framework pattern to import, no npm/PyPI package to vet — the milestone-wide
zero-new-dependency gate forbids it, and nothing in MPORT-01..07 wants one. Accordingly this research
document is **not** a standard-stack survey. It is a *code-truth audit*: every `file:line` citation in
CONTEXT.md that a plan would act on, verified against the tree, plus resolved answers to the four
Research Items and the two Discovered Defects.

**Headline result: CONTEXT.md is remarkably accurate.** Of ~60 citations checked, **56 are exact**,
3 are off-by-a-few-lines in a way that does not change meaning, and **1 factual claim is wrong**
(the `clOrdId` file count — see Correction C-1). All 30 decisions survive contact with the code. This
is a materially better starting position than Phase 10, where a retrospective found 8/8 plans carried
false factual claims. The planner should still treat **code as authoritative over prose**, but the
CONTEXT prose is trustworthy here.

**Three findings the planner did not have**, each of which changes a wave's plan:

1. **[F-3, HIGH] D-25's two-paper-account test cannot prove MPORT-07.** `paper_plugin` is constructed
   with the *already-built shared* `SimulatedExchange` (`live_trading_system.py:1473`), so both paper
   accounts necessarily resolve to one exchange object. The per-account exchange routing (D-27) needs
   its own test with a fake multi-account venue plugin. W7 must carry both.
2. **[F-4, MEDIUM] There are six bare-name `exchanges` lookup sites, not one.** CONTEXT names
   `on_order` (`:126`). D-27 must also cover `:96`, `:115`, `:238`, `:241`, and three sites in
   `live_trading_system.py`.
3. **[F-5, LOW] `Portfolio.__init__` has no `account_id` parameter *and* no `portfolio_id` parameter.**
   F-1's fix and D-06's `account_id NOT NULL` are the *same* signature edit, in the same file, on the
   same lines. W4 should treat them as one change, not two.

**Primary recommendation:** Sequence W1 (schema) to land the `portfolios` table and the D-09 config
move as **two separate commits with a data-movement test between them**, because D-09 is the single
highest-regression-risk edit in the phase and it is the one place where a silent failure survives the
whole test suite (verified: `load_config()` returning `None` degrades clean by design —
`live_trading_system.py:1263-1271` — so a lost config produces a **passing boot with default config**,
not an error).

---

## Project Constraints (from CLAUDE.md)

Extracted directives the planner must verify compliance against. These carry the same authority as
locked CONTEXT decisions.

| Directive | Applies to P11 as |
|---|---|
| **Money is `Decimal` end-to-end**; enter via `to_money(str(x))`, never `Decimal(float)` | `initial_cash` on the new `portfolios` row; any account balance crossing the venue edge |
| **Single UUIDv7 scheme** via the `idgen` singleton — do not introduce a second ID scheme | `portfolio_id` stays UUIDv7 (F-1 makes it *supplyable*, never *re-schemed*); `venue_accounts` uses a **natural composite key**, not a surrogate id |
| **Queue-only cross-domain writes**; reads go through injected read-models | `PortfolioReadModel.account_for` (D-27) is the correct seam for `ExecutionHandler` → portfolio; do NOT import `PortfolioHandler` into `execution_handler` |
| **Indentation: measure the file, never generalize the package** | See the measured table in Architecture Patterns below — `trading_system/` is genuinely mixed |
| **`mypy --strict`** over `itrader` | New code must be strict-clean. **Trap:** `live_trading_system.py` is under a per-module `ignore_errors` override — dead code there passes both mypy and the suite (D-13's PLANNER WARNING is real; see Pitfall 4) |
| **`filterwarnings = ["error"]`, `--strict-markers`, `--strict-config`** | Any new warning fails the suite; every marker used must already be declared (`unit`/`integration`/`slow`/`e2e`/`smoke`/`live`) |
| **Test root is `tests/`**, type-grouped; `conftest.py` auto-applies the type marker from folder | W7's tests go in `tests/integration/` (marker auto-applied, do not hand-add `@pytest.mark.integration`) |
| **Enum maps** (`order_type_map` etc.) convert string input to enums | Not directly touched, but any new config-domain enum belongs in `config/`, not `core/enums/` (the pinned config-enum exception) |

---

## Citation Verification Table

Every CONTEXT.md `file:line` a plan would act on, checked against the tree.

### Verified exact (act on these with confidence)

| Citation | Claim | Verified |
|---|---|---|
| `connectors/provider.py:69` | `_memo: dict[tuple[str, str], LiveConnector]` | ✅ exact — line 69 |
| `connectors/provider.py:72-80` | `get(venue, account_id, spec)`; `_plugins[venue].build(spec)` | ✅ exact — `:79` is the venue-only `_plugins` read (**the D-12 caveat is real**) |
| `venues/bundle.py:64-65` | `exchange`, `account_factory: Callable[..., Account]` | ✅ exact |
| `venues/bundle.py:77` | `class VenuePlugin(Protocol)` | ✅ exact — `@runtime_checkable`, structural |
| `venues/bundle.py:90` | `build_bundle(ctx, spec, connectors)` | ✅ exact |
| `venues/bundle.py:96` | `class DataProviderPlugin(Protocol)` | ✅ exact |
| `venues/okx_plugin.py:96-97` | `spec.account_id or "default"`; `connectors.get("okx", account_id, spec)` | ✅ exact |
| `venues/okx_plugin.py:101-110` | `def account_factory(*args: Any, **kwargs: Any)` returning the **shared** `VenueAccount` | ✅ exact — **the D-11 trap confirmed**; `:105-110` is the `return VenueAccount(connector, quote_currency=..., market_type=..., symbol=...)` with no account scoping |
| `venues/okx_plugin.py:138-139` | data arm, same `spec.account_id or "default"` | ✅ exact (D-26's deferral target) |
| `venues/paper_plugin.py:63` | real signature `account_factory(portfolio, initial_cash=0.0)` | ✅ exact |
| `account/venue.py:75-82` | `__init__` — **every** param after `connector` has a default; no `account_id` | ✅ exact: `:77 connector`, `:78 quote_currency="USDT"`, `:80 market_type="derivative"`, `:81 symbol=None`. **D-11's premise fully confirmed.** |
| `account/base.py:35` | `Account` ABC, no `account_id` member | ✅ exact — surface is `is_venue_truth`/`balance`/`available_balance`/`reserved_balance`/`assert_funds_invariant`/`apply_fill_cash_flow`/`restore_cash`/`reserve`/`release` |
| `portfolio.py:68` | comment claims state survives "a process restart" | ✅ exact — **the false claim** |
| `portfolio.py:71` | `self.portfolio_id = PortfolioId(idgen.generate_portfolio_id())` | ✅ exact — **F-1 confirmed** |
| `portfolio.py:73` | `self.exchange = exchange` | ✅ exact (D-07's derivation target) |
| `portfolio_handler.py:198` | `add_portfolio(name, exchange, cash, portfolio_config=None)` | ✅ exact (CONTEXT said `:198-249`; body ends `:249`) |
| `portfolio_handler.py:217-218` | `max_portfolios` guard | ✅ exact |
| `portfolio_handler.py:365-368` | `exchange_for(portfolio_id) -> str` | ✅ exact — 4 lines, trivially extensible for `account_for` |
| `portfolio_handler.py:918` | `def rehydrate(` | ✅ exact |
| `config/portfolio.py:42` | `max_portfolios: int = Field(default=50, gt=0)` | ✅ exact |
| `reconciliation_coordinator.py:80-91` | ctor with scalar `venue_account` / `connector` / `exchange` | ✅ exact — `:86 venue_account`, `:87 connector`, `:88 exchange` |
| `reconciliation_coordinator.py:103-148` | `run_startup_reconcile` | ✅ exact — `:103` def; `:127` calls `_link_venue_account_to_portfolios` |
| `reconciliation_coordinator.py:151-176` | `_link_venue_account_to_portfolios` + `RuntimeError(>1)` | ✅ exact — `:151` def, `:166` raise. **MPORT-01's deletion target.** |
| `reconciliation_coordinator.py:164` | fail-loud `RuntimeError`-not-`assert` precedent | ✅ within the raise block (`:166` is the `raise` keyword; `:164` is the `len(...) > 1` guard) |
| `reconciliation_coordinator.py:179-216` | `_run_session_baseline_guard` | ✅ exact — `:179` def, `:194` the single-symbol config read, `:215` halt, `:216` `return` |
| `reconciliation_coordinator.py:216` | `return` on first mismatch | ✅ exact — **F-2 confirmed**, it is inside the `for portfolio in ...` loop |
| `execution_handler.py:66` | `self.exchanges: dict[str, Optional[AbstractExchange]]` | ✅ exact |
| `execution_handler.py:123-131` | `on_order` bare-name lookup | ✅ exact — `:126 self.exchanges.get(event.exchange)` |
| `execution_handler.py:136-151` | `on_market_data` + `id()` dedup | ✅ exact — `:141 seen: set[int]`, `:143 id(exchange) in seen`, `:145 seen.add` |
| `okx.py:101` | `__init__(global_queue, connector)` — one connector | ✅ exact; `:119 self._connector = connector`, `:139 self._index = VenueCorrelationIndex()` |
| `okx.py:204-232` | `_client_order_id` | ✅ exact — `:204` def |
| `okx.py:230` | bare `assert clordid.isalnum() and len(clordid) <= 32` | ✅ exact — **D-18 confirmed; strippable under `python -O`** |
| `okx.py:402,407` | precision via `self._connector.client` | ✅ exact — `:397 client = self._connector.client` |
| `venue_correlation.py:81-94` | `_extract_client_order_id` | ✅ exact — `:81` def, `:90 trade.get("clientOrderId")`, `:94 info.get("clOrdId") or info.get("clientOrderId")` |
| `venue_correlation.py:139-151` | five `venue_id`-keyed dicts | ✅ exact — `:139,140,141,144,149,151` (six maps; `:141` is the `clOrdId` one) |
| `venue_correlation.py:141` | `self._orders_by_clOrdId` | ✅ exact — the D-16 rename target |
| `order_handler/storage/models.py:79` | `portfolio_id Uuid(as_uuid=True), nullable=False` | ✅ exact (CONTEXT said `:61-113`; table is `:61`, column `:79`, `venue_order_id :109`, index `:111`) |
| `events/order.py:62,165` | `portfolio_id: PortfolioId` on `OrderEvent` + `OrderAckEvent` | ✅ exact |
| `events/fill.py:64` | `portfolio_id: PortfolioId` | ✅ exact |
| `events/signal.py:89` | `portfolio_id: PortfolioId` | ⚠️ CONTEXT says `:88` — that is the preceding comment line; the field is `:89`. Cosmetic. |
| `order_handler/order.py:57` | `portfolio_id: PortfolioId` | ✅ exact |
| `venue_store.py:40-77` | `_SECRET_KEY_DENYLIST` + `_assert_no_secret_keys` | ✅ exact — denylist `:40-53`, fn `:56`. **`"credential"` singular IS present; `"credentials"` and `"secret_ref"` both pass** — D-02's one-letter warning is correct and load-bearing |
| `venue_store.py:96-99` | typed `enabled` + `config_json` + `UtcIsoText` shape | ✅ exact — the D-05 template |
| `strategy_registry_store.py:113-127` | subs table; `strategy_name` **has** FK, `portfolio_id` is `String` with **no** FK | ✅ exact — and the in-code comment at `:125-126` literally says *"A Uuid column is open as B2, not decided."* **The B2 fold-in is confirmed correct.** |
| `safety_controller.py:146,151,265` | `_submission_paused` / `halt` / `is_submission_paused` | ✅ exact; also `:289 pause_submission`, `:284` the status dict |
| `live_trading_system.py:473,607` | the two `is_submission_paused` consumers | ✅ substantively — `:473` is inside the status-row build (`:471-474`), `:607` inside the `freeze_gate` lambda (`:605-607`). Both real. |
| `live_trading_system.py:191,195` | `self._venue_account = None` then `= lifecycle.bundle.account_factory()` | ✅ exact — **D-13's deletion target**; also read at `:368` (coordinator ctor) and `:1666` |
| `live_trading_system.py:1262-1266` | portfolio-config restart layering via `state_storage.load_config()` | ✅ exact — `:1265` is the `load_config()` call |
| `live_trading_system.py:1583-1585` | the false "restart-stable" claim | ✅ exact — `:1585` reads *"already exist and are restart-stable — portfolios-before-strategies holds."* **F-1's second false comment confirmed.** |
| `system_spec.py:39-48` | `PortfolioSpec(name, cash)` | ✅ exact — `:39` class, `:47 name: str`, `:48 cash: int`. **No `account_id`** — MPORT-05's target |
| `system_spec.py:126` | `SystemSpec.account_id: Any = None` | ✅ exact — D-26's rename target |
| `strategies_handler.py:524-536` | the fan-out loop | ✅ exact — `:524 for portfolio_id in strategy.subscribed_portfolios:` emitting one `SignalEvent` each. **MPORT-03's fan-out already exists; P11 changes nothing here.** |
| `backtest_trading_system.py:507-525` | N-portfolio cross-product subscription | ✅ exact — `:508-521` builds portfolios, `:523-525` the cross-product `subscribe_portfolio` |
| `admission_manager.py` per-`portfolio_id` | already fully keyed | ✅ confirmed — `:178,322,361,386,417,430,445,484,499,808` all read `portfolio_id`. **D-22's gate is genuinely one guard clause.** |
| `conformance.py:3,51` | mypy-only mirror, nothing imports it | ✅ exact — `:3` and `:51` both name `live_trading_system._link_venue_account_to_portfolios` |
| `migrations/` head | `p10_strategy_portfolio_subs` | ✅ **confirmed** — full chain: `2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id → hl5_transaction_venue_trade_id → d10_halt_records → system_store → venue_config → strategy_registry → module_config → system_stats → p10_strategy_portfolio_subs`. Single head. |
| `migrations/versions/venue_config.py` | revision id `venue_config` builds table `venue_store` | ✅ exact — the file's own docstring says so |
| tests calling `_link_venue_account_to_portfolios` | `test_live_system_okx_wiring.py:292,319`, `test_live_portfolio_durable_wiring.py:148` | ✅ exact — **plus two more CONTEXT missed**: `test_early_durable_halt_refusal.py:91` and `test_paper_restart_restore.py:6,15` reference it in **comments/docstrings only** (no call), so they will not break but their prose goes stale |

### Corrections (CONTEXT is wrong — use these instead)

**C-1 — `clOrdId` appears in THREE files, not two; 46 → 46 total but distributed differently.**
CONTEXT D-16 says *"`clOrdId` appears 46 times across just **two** files."* Measured:

| File | Count |
|---|---|
| `execution_handler/exchanges/okx.py` | 23 |
| `execution_handler/exchanges/venue_correlation.py` | 22 |
| `portfolio_handler/reconcile/reconciliation_coordinator.py` | **1** (`:172`) |

The third occurrence is inside the `RuntimeError` message string that **MPORT-01 deletes anyway**
(*"position attribution by clOrdId/tag — deferred"*). So the practical impact is nil — but a W5 plan
that greps only two files and asserts `grep -c clOrdId == 0` afterward will get a **false failure** if
W5 runs before W3 deletes that function, or a **false pass** if it scopes the grep to two files.
**Planner action:** W5's completion grep must be repo-wide (`grep -rn clOrdId itrader/`) and must
account for the W3/W5 ordering. Note D-28 marks W5 as *"independent — parallelizable"*, which makes
this collision **likely**, not hypothetical.

**C-2 — `okx.py:952-955` is docstring, not code.** CONTEXT cites `:952-955` for *"the markets/precision
map lives on the connector"* and `:952-969` for *"the markets-map fail-closed check"*. Verified: `:952`
opens the **docstring** of `validate_symbol`; the actual code is `:972-976`
(`markets = getattr(self._connector.client, "markets", None)` → `isinstance(markets, dict)` →
fail-closed `return False`). The *claim* is correct (the map genuinely lives on the connector's client),
only the line pointer is off. **The architectural premise of D-27 stands.**

**C-3 — `events/signal.py:88` is a comment; the field is `:89`.** Cosmetic.

---

## Research Item 1 — Where portfolio rehydrate runs

### ANSWER

**Portfolios must rehydrate at `live_trading_system.py:~1578`, immediately BEFORE the strategy-rehydrate
block at `:1582-1625` and immediately AFTER `_layer_persisted_overrides` at `:1571-1578` — with the
config-layering call moved to *after* portfolio rehydrate.**

This is a genuine ordering change, not a simple insertion, and CONTEXT does not flag it. Here is why.

### Evidence

The strategy-rehydrate block carries an unusually explicit four-constraint justification comment
(`:1582-1601`). Read literally, constraint (1) says:

> `(1) portfolios are already layered ABOVE (_layer_persisted_overrides iterates
>     portfolio_handler._portfolios), so subscribe_portfolio binds to ids that
>     already exist and are restart-stable — portfolios-before-strategies holds.`

**This comment is doubly wrong today.** Verified:

- `_layer_persisted_overrides` does **not create** portfolios. It *iterates existing ones*
  (`:1264 for _pid, portfolio in portfolio_handler._portfolios.items()`). The reason
  "portfolios-before-strategies holds" today is that **live has zero `add_portfolio` call sites** —
  confirmed: `grep -rn "add_portfolio" itrader/` returns only `portfolio_handler.py:198` (the
  definition) and `backtest_trading_system.py:517`. Live currently boots with **zero portfolios**, so
  the ordering constraint is vacuously satisfied.
- "restart-stable" is F-1's false claim (`:1585`).

**The four-constraint comment is therefore load-bearing documentation that is currently false in two
of its clauses.** F-1's fix makes clause (1)'s *second* half (restart-stable) true; D-08's rehydrate
makes clause (1)'s *first* half (portfolios exist) true for the first time. W4 must **rewrite this
comment**, not merely insert code above it.

### The deferred-session-wiring contract — resolved

The P10 risk CONTEXT flags is real and documented at two places:

- `live_trading_system.py:1291-1296` (`build_live_system` docstring): *"live session wiring
  (`SessionInitializer` via `_initialize_live_session`) stays **DEFERRED** to `start()` … it conflicts
  with the pervasive add-strategy-after-construction + monkeypatch-`_initialize_live_session`-before-
  `start()` contracts across the live test suite."*
- `live_trading_system.py:257-259` (facade `__init__`) restates it.

**Resolution: portfolio rehydrate faces the SAME hazard and takes the SAME answer as strategy
rehydrate — put it in `build_live_system`, NOT in `_initialize_live_session`.** Constraint (3) of the
existing comment states the reason directly:

> `(3) NOT inside _initialize_live_session: three integration tests — including a
>     RESTART test — monkeypatch that method to a no-op, so rehydrate placed there
>     would be silently lost exactly where it matters most.`

That reasoning transfers verbatim and with **more** force: a monkeypatched-away *portfolio* rehydrate
produces a boot with zero portfolios, which then silently passes every assertion that only checks
strategies.

### Required ordering (planner: this is the W4 sequence)

```
build_live_system(spec):
  ...
  [existing] construct portfolio_handler, order_handler, execution_handler, stores
  ── NEW ─────────────────────────────────────────────────────────────
  1. D-14/D-15 distinct-account_id invariant check     ← BEFORE any account is minted
  2. portfolios rehydrate (D-08)                        ← creates Portfolio objects with
                                                           persisted portfolio_ids (F-1)
  3. per-portfolio account minting via new_account()    ← D-10/D-11, needs portfolios to exist
  ── existing, but MOVED ────────────────────────────────────────────
  4. _layer_persisted_overrides(...)                    ← was :1571; its portfolio arm
                                                           (:1263-1271) now has rows to iterate
  ── existing, unchanged position ──────────────────────────────────
  5. rehydrate_strategies(...)                          ← :1625, binds to now-real portfolio ids
  6. [deferred to start()] _initialize_live_session
```

**Why step 4 must move below step 2:** `_layer_persisted_overrides`'s portfolio arm iterates
`portfolio_handler._portfolios` (`:1264`). If it runs before rehydrate, that dict is empty and the loop
is a silent no-op — the config would never be applied. Today this is invisible because the dict is
*always* empty. **After D-08 it becomes a live ordering bug.** This is a near-miss of exactly the
silent-corruption class the Phase-10 retrospective flagged.

**Why step 1 must precede step 2/3:** D-15 says a collision "REFUSES TO START — hard fail before any
account is minted." If the invariant runs after rehydrate, portfolios exist but are unusable; if it
runs after minting, D-11's structural guard has already been bypassed by a colliding pair.

### Test-suite blast radius

| File | Line | What breaks |
|---|---|---|
| `tests/integration/test_live_system_okx_wiring.py` | 292, 319 | **Calls the deleted method** — hard break, must be rewritten |
| `tests/integration/test_live_portfolio_durable_wiring.py` | 148 | **Monkeypatch target string** — hard break |
| `tests/integration/test_early_durable_halt_refusal.py` | 91 | Comment only — prose goes stale, no break |
| `tests/integration/test_paper_restart_restore.py` | 6, 15 | Docstring only — prose goes stale; **but this is the RESTART test, so its behavior assumptions need review** |

---

## Research Item 2 — The D-09 config migration (highest regression risk)

### ANSWER — exact shape stored today

**`portfolio_account_state.config_json` holds a free-form `Dict[str, Any]` partial-config blob written
verbatim, with NO schema validation at the storage layer.**

Evidence — `portfolio_handler/storage/sql_storage.py`:

- `:528 def save_config(self, config: Dict[str, Any], at: datetime) -> None`
- `:539-542` — UPDATE `.values(config_json=config, updated_time=at)`; the dict is passed **as-is** to
  the JSON column, no `model_dump`, no key filtering
- `:544-559` — INSERT-if-absent with **zero-sentinel accumulators** (`cash_balance=0`,
  `realized_pnl=0`, `total_equity=0`, `peak_equity=0`, `open_positions_count=0`)
- `:562 def load_config(self) -> Optional[Dict[str, Any]]` — returns `row["config_json"]` verbatim,
  or `None` when no row / NULL

Column definition — `portfolio_handler/storage/models.py:226`:
`Column("config_json", json_variant(), nullable=True)`

Consumer — `live_trading_system.py:1265-1267`:
```python
portfolio_cfg = portfolio.state_storage.load_config()
if portfolio_cfg:
    portfolio.update_config(portfolio_cfg)
```
`Portfolio.update_config` is at `portfolio.py:212` and takes `Dict[str, Any]` — a **partial** update
merged via `recursive_merge`. So the stored blob is a *partial override*, not a full `PortfolioConfig`.

### RTCFG-03 semantics — preserved, with one condition

Moving the blob from `portfolio_account_state.config_json` to `portfolios.config_json` preserves
semantics **iff all four of these hold**:

1. **Same column type.** Use `json_variant()` (the same helper), not a raw `JSON`. Verified
   `venue_store.py:98` uses `json_variant()` too — consistent.
2. **Same nullability.** `nullable=True` — `load_config()` explicitly handles `None`
   (`sql_storage.py:566-567`).
3. **Same read contract.** `load_config()` must keep returning `Optional[Dict[str, Any]]` verbatim.
   The *storage location* changes; the *shape* must not. Do not "improve" it into a typed model — that
   would break `update_config`'s partial-merge contract.
4. **The INSERT-if-absent path is rehomed correctly.** This is the subtle one. Today `save_config`'s
   INSERT arm creates a `portfolio_account_state` row with zero-sentinel accumulators *because the
   config write can precede the portfolio's first fill*. On the `portfolios` table there **is no such
   race** — D-08 guarantees a definition row exists before the portfolio is constructed. So the
   INSERT-with-sentinels arm should become a **plain UPDATE**, and a `rowcount == 0` should now be a
   **loud error** (no definition row = a bug), not a silent INSERT.

Point 4 is a genuine simplification the planner should take deliberately, with a comment explaining
why the sentinel arm is gone.

### The silent-failure hazard (planner: this is the one to gate)

**Verified: a lost config produces a passing boot, not a failure.** `live_trading_system.py:1268-1271`:

```python
except _degrade_clean as exc:
    logger.warning(
        "Skipping persisted PORTFOLIO-config restart layering — schema unavailable or a "
        "stored override is invalid (%s); boot degrades clean", exc)
```

Combined with `:1266 if portfolio_cfg:` — a `None`/`{}` return is **not even a warning**, it is a
no-op. So if the migration repoints reads to a new column but fails to *move the data*:

- no exception
- no warning
- boot succeeds
- every portfolio silently runs on **default config**
- the full test suite stays green

This is the exact failure mode CONTEXT rates as "the highest-regression-risk item in the phase," and
the verification confirms it is worse than described: it is not merely risky, it is **structurally
undetectable by the existing suite**.

**Required gate (W1):** a migration test that (a) seeds `portfolio_account_state.config_json` with a
non-default blob, (b) runs the revision-2 upgrade, (c) asserts the blob is byte-identical in
`portfolios.config_json`, and (d) asserts `load_config()` returns it. Assert **positively on the
value**, never merely `is not None`.

### P12's TEST-03 gate

TEST-03 (config-restart) exercises `save_config` → restart → `load_config` → `update_config`. Since
all three method *names and signatures* are preserved and only the backing table changes, TEST-03
passes **provided** the D-09 migration moves data and the `load_config` return shape is unchanged.
Add the assertion above and TEST-03 is covered by construction.

---

## Research Item 3 — ExecutionHandler per-account exchange keying (D-27)

### ANSWER (a): the `id()`-based alias dedup needs **NO change**

**Verified correct-by-construction for the new cardinality.** The dedup at
`execution_handler.py:141-145` exists to handle *aliases* — two dict keys pointing at the **same
object**:

```python
# execution_handler.py:173-180 (init_exchanges)
exchanges = {
    'simulated': simulated,
    'csv': simulated,        # ← same object, deliberate alias (DEF-01-B)
    'ccxt': None,
}
```

With `(venue, account_id)` keys, two *different* accounts on one venue produce two **distinct**
`OkxExchange` objects → distinct `id()` → both get driven by `on_market_data`. That is exactly right:
each account has its own `VenueCorrelationIndex` and its own resting state, so each must see every bar.
And genuine aliases (`'simulated'`/`'csv'`, which become `('simulated','...')`/`('csv','...')`) still
collapse to one drive, preserving the byte-exact backtest resting-order book.

**The same reasoning applies to the second dedup at `:190-192` (`seen_connect`)** — CONTEXT does not
mention this one, but it has identical structure and identical correctness. Leave both.

**Planner note:** the dedup is the *reason* the oracle stays byte-exact through D-27. A plan that
"cleans up" the `id()` dedup into a name-based or key-based dedup would double-drive the backtest
resting book and break `134 / 46189.87730727451`. Add an explicit "do not touch" note.

### ANSWER (b): there are **SIX** bare-name lookup sites, not one — [F-4]

CONTEXT names only `on_order` (`:126`). Full inventory:

| Site | Line | Lookup | D-27 treatment |
|---|---|---|---|
| `update_config` | `execution_handler.py:96` | `self.exchanges.get('simulated')` | **Hardcoded literal.** With tuple keys this becomes `('simulated', ...)` — needs an explicit decision |
| `validate_config` | `execution_handler.py:115` | `self.exchanges.get('simulated')` | same |
| **`on_order`** | `execution_handler.py:126` | `self.exchanges.get(event.exchange)` | **the D-27 change** — resolve `account_for(event.portfolio_id)`, key on the pair |
| `on_market_data` | `execution_handler.py:142` | iterates `.items()` | no change (values only) |
| health check | `execution_handler.py:238` | `list(self.exchanges.keys())` | keys become tuples — **any caller passing a bare `exchange_name` breaks** |
| health check | `execution_handler.py:241` | `self.exchanges.get(name)` | same |
| paper plugin ctor | `live_trading_system.py:1473` | `execution_handler.exchanges['simulated']` | **KeyError under tuple keys** |
| venue registration | `live_trading_system.py:1514` | `execution_handler.exchanges[exchange] = bundle.exchange` | **the registration site** — must write the pair key |
| paper-venue probe | `live_trading_system.py:1553-1555` | `isinstance(execution_handler.exchanges.get(venue_name), SimulatedExchange)` | **breaks under tuple keys** |
| status build | `live_trading_system.py:582-584` | `execution_handler.exchanges.get('simulated')` | breaks |

**This is a 10-site change, not a 1-site change.** The `update_config`/`validate_config`/health-check
sites hardcode `'simulated'` and are on the **backtest-shared path** — the oracle runs through
`init_exchanges` and its `'simulated'`/`'csv'` keys.

### Recommended keying approach (Claude's discretion per CONTEXT)

**Recommendation: keep `dict[str, ...]` keyed by a composed string is WRONG (D-27 explicitly rejects
stringly-typed); use `dict[tuple[str, str], AbstractExchange | None]` with a module-level helper.**

But the backtest path needs a stable account: introduce a single named constant, e.g.

```python
# execution_handler.py — module level, 4-space? NO: this file is TABS (measured)
_DEFAULT_ACCOUNT_ID = 'default'   # backtest/simulated venues have exactly one account
```

and key `init_exchanges` as `('simulated', _DEFAULT_ACCOUNT_ID)`, `('csv', _DEFAULT_ACCOUNT_ID)`,
`('ccxt', _DEFAULT_ACCOUNT_ID)`. The three hardcoded `'simulated'` lookups become
`(_SIMULATED, _DEFAULT_ACCOUNT_ID)`. This keeps the oracle byte-exact (same objects, same aliasing,
same dedup) while making the dimension explicit.

`on_order` becomes:
```python
account_id = self.portfolio_read_model.account_for(event.portfolio_id)
exchange = self.exchanges.get((event.exchange, account_id))
```
which requires **injecting `PortfolioReadModel` into `ExecutionHandler`** — it does not have one today
(verified: no `portfolio_read_model` / `portfolio_handler` attribute on `ExecutionHandler`). That is a
constructor change on a class the backtest composition root builds. **Flag as an oracle-gated edit.**

`PortfolioReadModel` (`core/portfolio_read_model.py:84`) gains `account_for` beside `exchange_for`
(`:191`); `PortfolioHandler.exchange_for` (`:365-368`) is a 4-line method — `account_for` mirrors it
exactly.

---

## Research Item 4 — `max_portfolios`, `Account`, `conformance.py`

### `max_portfolios` — NO change needed

`config/portfolio.py:42` → `max_portfolios: int = Field(default=50, gt=0)`, enforced at
`portfolio_handler.py:217-218`. Default 50 is far above any realistic multi-account count, the guard
raises `PortfolioConfigurationError` (loud, correct), and it is a **per-handler** limit orthogonal to
account cardinality. The WR-08 comment at `config/portfolio.py:39-41` confirms it was deliberately
separated from `max_positions`.

**One planner note:** D-08's rehydrate creates portfolios through whatever path W4 chooses. If
rehydrate goes through `add_portfolio`, the limit applies to rehydrated portfolios too — correct
behavior, but a restart with >50 persisted portfolios would fail loud mid-rehydrate leaving a partial
set. Given default 50 and the phase's realistic N=2, **accept as-is**; note it in the plan.

### `Account` ABC — NO change needed, and adding `account_id` would be WRONG

`account/base.py:35` — the ABC surface is `is_venue_truth`, `balance`, `available_balance`,
`reserved_balance`, `assert_funds_invariant`, `apply_fill_cash_flow`, `restore_cash`, `reserve`,
`release`. No `account_id`.

**D-11 puts `account_id` on `VenueAccount.__init__`, not on the ABC** — and that is correct. Adding
`account_id` to the ABC would force `SimulatedCashAccount`/`SimulatedMarginAccount` (the **byte-exact
oracle path**, per `account/base.py:24` *"fails the byte-exact oracle"*) to carry a venue concept they
have no use for. The `account_id` lives on `Portfolio` (D-07's `portfolios.account_id`), and
`VenueAccount` takes it because *it* is the thing scoped to a venue account.

**Recommendation: leave `Account` untouched.** If the reconciliation coordinator needs an account id
per portfolio (D-19), read it from `portfolio.account_id`, not `portfolio.account.account_id`.

### `conformance.py` — SURVIVES MPORT-01, but its docstrings go stale

Verified: nothing imports it at runtime (`grep -rn "conformance" itrader/` finds only the file
itself); it exists solely so `mypy --strict` type-checks the `Portfolio.account = <leaf>` assignment
that `live_trading_system.py`'s `ignore_errors` override would otherwise skip.

- `:3` and `:51` both reference `live_trading_system._link_venue_account_to_portfolios` — **already
  stale today** (the function moved to `reconciliation_coordinator.py` in P7) and about to be deleted.
- `:60-62` — `portfolio.account = cash / margin / venue` — the assignment being mirrored **still
  happens** after MPORT-01, just per-portfolio via `new_account()` instead of via the deleted link
  function.

**Recommendation: KEEP the module, UPDATE both docstrings.** Its purpose (compile-time enforcement
that every leaf is assignable to the ABC-typed field) becomes *more* important under D-27/D-11, not
less, because more code paths now assign accounts. Fold the docstring fix into W3.

---

## Discovered Defects — verified shape

### F-1 — `portfolio_id` is not restart-stable — **CONFIRMED, and larger than described**

| Evidence | Line |
|---|---|
| `self.portfolio_id = PortfolioId(idgen.generate_portfolio_id())` — fresh UUIDv7 every construction | `portfolio.py:71` |
| False claim: state persists "keyed by `portfolio_id` (surviving a process restart)" | `portfolio.py:68` |
| False claim: strategy rehydrate "binds to ids that already exist and are restart-stable" | `live_trading_system.py:1585` |
| **`Portfolio.__init__` has no `portfolio_id` parameter** | `portfolio.py:~54-55` signature |
| **`add_portfolio` has no `portfolio_id` parameter** | `portfolio_handler.py:198` |
| `add_portfolio` constructs `Portfolio(name=, exchange=, cash=, time=, config=, environment=, sql_engine=)` — no id passthrough | `portfolio_handler.py:225-233` |

**[F-5] The fix is the same edit as D-06/D-07.** `Portfolio.__init__` and `add_portfolio` both need
new parameters for **`portfolio_id`** (F-1), **`account_id`** (D-06), and `venue_name`-derived
`exchange` (D-07). These are one signature change per method, in W4, not three. Planning them as
separate tasks invites merge conflict on the same lines.

**Signature-compat caution:** `add_portfolio` is called by `backtest_trading_system.py:517` with
keyword args `(name=, exchange=, cash=)`. New params **must default** so the backtest call site is
untouched (oracle byte-exactness). `portfolio_id: PortfolioId | None = None` → mint when `None`.
This is the one place a default is correct — contrast D-11, where `VenueAccount.account_id` must have
**no** default because there is no legitimate "unscoped" venue account.

### F-2 — baseline guard returns on first mismatch — **CONFIRMED**

`reconciliation_coordinator.py:198-216`. The `for portfolio in self._portfolio_handler.get_active_portfolios():`
loop at `:198` contains `self._halt(...)` at `:215` followed by bare `return` at `:216`. With N>1 the
scan stops at the first mismatch.

**Second latent defect in the same function, confirming D-20:** `:193-195` reads a **single global
symbol**:
```python
from itrader import config as _system_config
symbol = _system_config.stream.okx_stream_symbol
venue_qty = account.positions.get(symbol, Decimal("0"))
```
So a residual in *any other symbol* is invisible today, single-account or not — exactly as D-20
describes. `precision = self._portfolio_handler._drift_precision(symbol)` at `:196`
(verified `_drift_precision` exists at `portfolio_handler.py:720`) is also computed once outside the
loop; under D-20 it must move inside the per-symbol iteration.

---

## Architecture Patterns

### Indentation — MEASURED, per file (do not generalize)

Re-verified this session. **`trading_system/` is genuinely mixed.**

| File | Indent |
|---|---|
| `trading_system/live_trading_system.py` | **4-space** |
| `trading_system/system_spec.py` | **TABS** |
| `trading_system/backtest_trading_system.py` | **TABS** |
| `trading_system/safety/safety_controller.py` | 4-space |
| `portfolio_handler/portfolio.py` | **TABS** |
| `portfolio_handler/portfolio_handler.py` | 4-space |
| `portfolio_handler/reconcile/reconciliation_coordinator.py` | 4-space |
| `portfolio_handler/account/*.py` | 4-space |
| `portfolio_handler/storage/{models,sql_storage}.py` | 4-space |
| `execution_handler/execution_handler.py` | **TABS** |
| `execution_handler/exchanges/{okx,venue_correlation}.py` | **TABS** |
| `order_handler/admission/admission_manager.py` | **TABS** |
| `order_handler/storage/models.py` | 4-space |
| `strategy_handler/strategies_handler.py` | **TABS** |
| `connectors/provider.py`, all of `venues/` | 4-space |
| `storage/*.py`, `config/*.py`, `core/*.py` | 4-space |

**Note the hazard inside `portfolio_handler/`:** `portfolio.py` is TABS while `portfolio_handler.py`
is 4-space. F-5's "same edit" spans both files with **different indentation**.

**Verification-gate warning (repo-learned):** a whole-file "no space-indented lines" check fails on
untouched TAB files because wrapped docstring prose is space-aligned. Scan **added diff lines only**.

### Established patterns P11 must follow

- **Registrar = single source of truth.** `build_*_tables(metadata)` feeds both the test `create_all`
  and Alembic `target_metadata`. Both new tables need a `build_*_tables` registrar
  (`venue_store.py:96-101` is the template).
- **Schema-pure stores** — never `create_all` at runtime; production is Alembic-owned, tests provision
  via `tests.support.schema.provision_schema`.
- **Natural-key PKs** — `venue_store.venue_name`, `strategy_registry.strategy_name`. D-05's composite
  `(venue_name, account_id)` follows; **do not** add a surrogate id.
- **`UtcIsoText` for `updated_at`**, caller-supplied `at` (clock-free).
- **Parameterized Core only** (SEC-01) — no string SQL.
- **Import inertness (GATE-01)** — new store imports stay LAZY inside `build_live_system`; never
  barrel-export.
- **Events are `msgspec.Struct`** (frozen, kw_only, gc=False) — NOT the frozen `@dataclass` CLAUDE.md
  describes. No event changes needed in P11 (D-17 verified: `portfolio_id` already typed on all five).

### Migration template (D-29)

`migrations/versions/p10_strategy_portfolio_subs.py` is the pattern: guard-before-destructive-op
(`_refuse_if_subscriptions_hold_data()`), `batch_alter_table` for the SQLite test path, hand-written
custom-type import. Revision 2's `String`→`Uuid` on `strategy_portfolio_subscriptions.portfolio_id`
needs **both** (SQLite cannot ALTER COLUMN TYPE in place).

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Secret storage | Encrypted-blob-in-Postgres, custom envelope encryption | D-02's `secret_ref` pointer + `CredentialResolver` Protocol | Zero-dep gate blocks `cryptography` promotion; a decryptable blob lands live keys in every `pg_dump` |
| Secret-key rejection | A new denylist | `venue_store._assert_no_secret_keys` (`:56`) — recursive, any-depth | Already ships; **verified `"credential"` singular is in the set, `"secret_ref"` passes** |
| Connector-per-account memo | A new registry | `ConnectorProvider._memo` (`provider.py:69`) — already `(venue, account_id)`-keyed | MPORT-06's shape is shipped |
| Signal fan-out to N portfolios | A new loop | `strategies_handler.py:524` — already loops `subscribed_portfolios` | MPORT-03's fan-out exists; **P11 changes nothing here** |
| Per-portfolio admission | New keying | `AdmissionManager` — already fully `portfolio_id`-keyed (10 sites) | D-22's quarantine gate is one guard clause |
| Quarantine machinery | New subsystem | `SafetyController` scalars (`:146`, `:151`, `:265`, `:289`) as a per-portfolio set | Same shape, already alert-wired |
| Alert egress / read-model | New channels | `alert_sink` (P8) + `state.*` (RTCFG-06) | D-04/D-22/D-24 need no new channel |
| UUID generation | `uuid.uuid4()` or a second scheme | `idgen` singleton (UUIDv7, `uuid-utils`) | Locked project decision |
| Money entry | `Decimal(float)` | `to_money(str(x))` (`core/money.py`) | Binary-float repr artifact |
| Exchange alias dedup | Name/key-based dedup | Existing `id()` dedup (`:141-145`, `:190-192`) | **Byte-exactness depends on it** — see Research Item 3 |

---

## Common Pitfalls

### Pitfall 1 — The D-09 config migration fails silently (CRITICAL)
**What:** Repointing `load_config()` to the new column without moving data produces a green suite and
default-config portfolios. **Why:** `live_trading_system.py:1266` guards with `if portfolio_cfg:` and
`:1268` catches into a warning-only degrade-clean. **Avoid:** assert positively on the migrated *value*
in a dedicated migration test. **Warning sign:** any W1 verification that asserts only
`load_config() is not None`.

### Pitfall 2 — `_layer_persisted_overrides` no-ops because portfolios don't exist yet
**What:** Config layering iterates `portfolio_handler._portfolios` (`:1264`); if it runs before D-08's
rehydrate the dict is empty. **Why:** invisible today (live has zero `add_portfolio` call sites).
**Avoid:** move the layering call below portfolio rehydrate (Research Item 1 sequence). **Warning
sign:** a plan that inserts rehydrate without touching `:1571-1578`.

### Pitfall 3 — Backtest oracle break via `add_portfolio` / `ExecutionHandler` signature change
**What:** F-5's new params and D-27's `PortfolioReadModel` injection touch classes the backtest
composition root builds. **Why:** `backtest_trading_system.py:517` calls `add_portfolio(name=,
exchange='csv', cash=)`; `init_exchanges` keys `'simulated'`/`'csv'`. **Avoid:** every new param
defaults; `_DEFAULT_ACCOUNT_ID` preserves the alias structure. **Gate:** run
`tests/integration/test_backtest_oracle.py` on **every** commit in W3 and W4, not just at wave end.

### Pitfall 4 — Dead code in `live_trading_system.py` passes mypy AND the suite
**What:** D-13 deletes `self._venue_account` (`:191`, `:195`), read at `:368` and `:1666`. A missed
reference or orphaned import ships silently. **Why:** the module is under a `[[tool.mypy.overrides]]`
`ignore_errors` block. **Avoid:** after W3's deletion, `grep -n "_venue_account" itrader/` must return
zero. **Warning sign:** trusting a green `mypy --strict` on this file.

### Pitfall 5 — W5/W3 grep collision on `clOrdId` (see C-1)
**What:** W5 is marked parallelizable; the 46th `clOrdId` lives in the `RuntimeError` string W3 deletes.
**Avoid:** repo-wide grep + explicit W3-before-W5 note on the completion check.

### Pitfall 6 — Tuple-keying `exchanges` breaks 8 non-`on_order` sites (F-4)
**Avoid:** treat D-27 as a 10-site change; inventory in Research Item 3.

### Pitfall 7 — Assuming the two-paper-account test proves MPORT-07 (F-3)
**What:** `live_trading_system.py:1473` builds `PaperVenuePlugin(execution_handler.exchanges['simulated'])`
— paper's `bundle.exchange` **is** the shared `SimulatedExchange`. Two paper accounts → one exchange
object. **Why it's still the right test venue:** D-25 picks paper for the *lifecycle/restart/attribution*
path, which it does exercise. **Avoid:** add a separate MPORT-07 test with a fake venue plugin returning
distinct exchange objects per `account_id`; assert `exchanges[(v,'a')] is not exchanges[(v,'b')]` and
that `on_order` for portfolio-B never reaches exchange-A.

### Pitfall 8 — `filterwarnings=["error"]` + SQLAlchemy on the new tables
**What:** SQLAlchemy emits `SADeprecationWarning`/`RemovedIn20Warning` for some Core constructs; under
`error` these fail. **Avoid:** copy `venue_store.py` / `strategy_registry_store.py` constructs verbatim
rather than inventing new Core idioms.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest ^8.4.2 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` |
| Strictness | `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config` |
| Markers | TYPE (auto-applied by `tests/conftest.py` from folder): `unit`, `integration`, `e2e`, `slow`. PURPOSE (hand-applied): `smoke`, `live` |
| Quick run | `poetry run pytest tests/unit/portfolio tests/unit/execution -x -q` |
| Full suite | `poetry run pytest tests -q` |
| Oracle gate | `poetry run pytest tests/integration/test_backtest_oracle.py -q` |
| Inertness gate | `poetry run pytest tests/integration/test_okx_inertness.py -q` |

**Environment gotchas (repo-learned, verified in memory):** `make test` exports
`ITRADER_DISABLE_LOGS=true`, which breaks `caplog` warning-assertion tests — use
`poetry run pytest` as the gate. In git worktrees `make test` aborts on a missing `.env`; use
`poetry run pytest tests` there and prepend `PYTHONPATH="$PWD"` to defeat editable-install shadowing.

### Phase Requirements → Test Map

| Req | Behavior | Type | Command | Exists? |
|---|---|---|---|---|
| MPORT-01 | `new_account()` mints per-portfolio account; link fn deleted | integration | `pytest tests/integration/test_live_system_okx_wiring.py -q` | ❌ **rewrite** (calls deleted fn at `:292,319`) |
| MPORT-01 | `VenueAccount` requires `account_id` (TypeError without) | unit | `pytest tests/unit/portfolio/test_account_*.py -q` | ❌ Wave 0 |
| MPORT-02 | duplicate `(venue, account_id)` refuses to start | integration | new `tests/integration/test_distinct_account_invariant.py` | ❌ Wave 0 |
| MPORT-02 | DB unique index rejects out-of-band duplicate | integration | new, in the store test | ❌ Wave 0 |
| MPORT-03 | signal fans out; each portfolio sizes vs its own account | integration | new `tests/integration/test_multi_portfolio_lifecycle.py` (D-25) | ❌ Wave 0 |
| MPORT-04 | `client_order_id` rename; wire spelling preserved | unit | `pytest tests/unit/execution -k client_order_id -q` | ❌ Wave 0 |
| MPORT-04 | fill routes to the correct `Portfolio.on_fill` | integration | in the D-25 lifecycle test | ❌ Wave 0 |
| MPORT-05 | `PortfolioSpec.account_id`; coordinator iterates portfolios | unit + integration | `pytest tests/unit/portfolio/test_reconciliation_coordinator*.py -q` | ⚠️ file exists, needs new cases |
| MPORT-05 / F-2 | baseline guard evaluates **all** portfolios | unit | new case asserting N mismatches all reported | ❌ Wave 0 |
| MPORT-06 | connectors keyed `(venue, account_id)` | unit | `pytest tests/unit -k connector_provider -q` | ⚠️ memo already tested; add per-account credential case |
| **MPORT-07** | `exchanges` keyed on pair; B's order never hits A's session | integration | new `tests/integration/test_per_account_exchange_routing.py` — **fake multi-account plugin, NOT paper** (F-3) | ❌ Wave 0 |
| F-1 | `portfolio_id` supplyable + stable across restart | integration | in the D-25 restart test | ❌ Wave 0 |
| D-09 | config blob survives the migration byte-identical | integration | new migration test — **assert on the VALUE** (Pitfall 1) | ❌ Wave 0 |
| D-29 | single Alembic head; create_all/migration parity | integration | existing chain-parity gate — **extend by hand** (the dynamic-enumeration assumption was false in P9) | ⚠️ extend |
| Gate | oracle byte-exact `134 / 46189.87730727451` | integration | `pytest tests/integration/test_backtest_oracle.py -q` | ✅ exists |
| Gate | OKX import inertness | integration | `pytest tests/integration/test_okx_inertness.py -q` | ✅ exists |

### Sampling Rate

- **Per task commit:** `poetry run pytest tests/unit/<touched-domain> -x -q`
- **Per commit in W3/W4:** **additionally** the oracle gate (Pitfall 3 — these waves touch
  `add_portfolio` and `ExecutionHandler`, both backtest-shared)
- **Per wave merge:** `poetry run pytest tests -q` + oracle + inertness
- **Phase gate:** full suite green + oracle byte-exact + inertness green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/integration/test_multi_portfolio_lifecycle.py` — D-25 two-paper-account + restart (MPORT-03/04/05, F-1)
- [ ] `tests/integration/test_per_account_exchange_routing.py` — MPORT-07 with a **fake** multi-account venue plugin (F-3)
- [ ] `tests/integration/test_distinct_account_invariant.py` — MPORT-02 both layers (app + DB index)
- [ ] Migration data-movement test for D-09 — assert the value, not just non-null
- [ ] Rewrite `tests/integration/test_live_system_okx_wiring.py:292,319` and
      `tests/integration/test_live_portfolio_durable_wiring.py:148`
- [ ] Refresh stale prose in `tests/integration/test_early_durable_halt_refusal.py:91` and
      `tests/integration/test_paper_restart_restore.py:6,15`
- [ ] New-case additions to the existing reconciliation-coordinator unit tests (D-20/D-21/D-22)
- [ ] Framework install: **none needed** — pytest is present

---

## Security Domain

`security_enforcement` treated as enabled (absent from config = enabled).

### Applicable ASVS categories

| Category | Applies | Standard control in this phase |
|---|---|---|
| V2 Authentication | **yes** | Per-account venue credentials via D-02's `CredentialResolver`; `OkxSettings` `SecretStr` end-to-end (`config/okx_settings.py:64-66`) |
| V3 Session Management | **yes** | One authenticated `ccxt.pro` session per `(venue, account_id)` (D-12); `watch_my_trades` is a private per-account stream — **MPORT-07 exists to prevent cross-session leakage** |
| V4 Access Control | **yes** | D-15's distinct-`account_id` invariant is an authorization boundary: it guarantees one portfolio per venue account, so `client_order_id` → portfolio attribution is unambiguous |
| V5 Input Validation | **yes** | `_assert_no_secret_keys` on `config_json` (`venue_store.py:56`); D-18 converts the strippable `assert` at `okx.py:230` into a real raise |
| V6 Cryptography | **no (deliberately)** | D-02 stores a **pointer**, never a secret — no crypto in `itrader`. Zero-dep gate blocks promoting `cryptography`. |
| V7 Error Handling / Logging | **yes** | Halt reasons are FIXED literals, never `str(exc)` (`reconciliation_coordinator.py:214-215`; enforced by a grep-0 in `control.py`) — D-22's quarantine reason must follow the same rule |

### Known threat patterns for this phase

| Pattern | STRIDE | Mitigation (verified present or required) |
|---|---|---|
| Account-B orders submitted via account-A's authenticated session | **Elevation of Privilege / Spoofing** | **MPORT-07 / D-27** — the entire reason the requirement exists. Currently *reachable*: `execution_handler.py:126` bare-name lookup + `okx.py:101` single connector |
| Mistyped `secret_ref` → connect with the wrong account's keys | Spoofing | **D-04 TOFU venue-UID assertion** + CRITICAL alert. Observe-only by decision |
| Live credentials leaked into `pg_dump` / backups / read replicas | Information Disclosure | **D-02 pointer-not-secret**; `_assert_no_secret_keys` denylist enforces it at the write boundary |
| Secret name slipping past the denylist by one letter | Information Disclosure | **VERIFIED REAL**: `"credential"` denied, `"credentials"` and `"secret_ref"` pass (`venue_store.py:40-53`, exact lowercased membership). Column MUST be named `secret_ref` |
| Guard vanishing under `python -O` | Tampering | **D-18** — `assert` at `okx.py:230` is stripped in optimized runs; convert to `raise` |
| Cross-portfolio buying-power conflation | Tampering | **D-15** refuse-to-start + **D-14** DB unique index (defense-in-depth, matching the pinned D-03a posture) |
| Drift on one account silently halting all trading | Denial of Service | **D-22** per-portfolio quarantine replaces the global latched halt (`reconciliation_coordinator.py:215`) |
| Error→error livelock on the ERROR route | DoS | Pre-existing WR-06 source-guard; D-22's new CRITICAL alerts must not republish as `ErrorEvent`s |

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | `strategy_portfolio_subscriptions` and `portfolio_account_state` are **empty** in every deployed DB, so D-29's refuse-if-non-empty guard will not block an upgrade | D-29 / Research Item 2 | Migration refuses to run in the owner's environment. **Unverifiable from source.** Worth a manual `SELECT count(*)` before running revision 2. *(Same class as P10's A1, which STATE.md already flags.)* |
| A2 | P12's TEST-03 exercises `save_config`/`load_config` by method, not by direct table read | Research Item 2 | If TEST-03 asserts against `portfolio_account_state` directly, D-09 breaks it and P12 needs a coordinated edit. **Not verified** — P12 does not exist yet |
| A3 | Two paper accounts on `venue_name='paper'` produce two distinct `SimulatedAccount`s via `paper_plugin.account_factory(portfolio, initial_cash)` | D-25 / F-3 | Verified the factory signature (`paper_plugin.py:63`) is per-portfolio, so this holds — but the D-06 requirement that paper accounts be **real `venue_accounts` rows** is a new constraint whose interaction with the plugin is unbuilt |
| A4 | No consumer outside `itrader/` depends on `ExecutionHandler.exchanges` keys being bare strings | Research Item 3 / F-4 | Grepped `itrader/` exhaustively (10 sites, all listed). **Did not grep `tests/` or `scripts/`** — planner should, before finalizing the key change |

---

## Open Questions

1. **Does `PaperVenuePlugin` need per-account exchange instances after all?**
   - Known: `live_trading_system.py:1473` injects the shared `SimulatedExchange`; `SimulatedExchange`
     holds a resting-order book but **no** authenticated session, so sharing is *safe*.
   - Unclear: whether two paper portfolios sharing one `MatchingEngine` resting book creates
     cross-portfolio bracket/OCO interference. Orders carry `portfolio_id`, but the book is one dict.
   - Recommendation: **investigate in W3**, before W7 writes the D-25 test. If interference exists it
     is a real multi-portfolio defect, not a test artifact. Do not assume safety from "no credentials."

2. **Where does the D-15 invariant check read from — the DB or the in-memory spec?**
   - Known: D-14 mandates both a DB unique index and an application check; D-15 says the app check
     fails "before any account is minted."
   - Unclear: at boot, portfolios come from *rehydrate* (the DB), so the DB index already guarantees
     distinctness for persisted rows. The app check's real job is catching duplicates in a
     `SystemSpec` supplied at composition — a different source.
   - Recommendation: run the app check over **the union** of rehydrated rows and spec-supplied
     portfolios. State this explicitly in W4's plan; a check over only one source is a hole.

3. **Does `SystemSpec.account_id`'s rename (D-26) break any test or script call site?**
   - Known: `system_spec.py:126`, read by `okx_plugin.py:96,138`.
   - Unclear: call sites in `tests/` and `scripts/` — not grepped.
   - Recommendation: cheap grep during W3 planning.

---

## Sources

### Primary (HIGH confidence) — direct code verification, this session
- `itrader/` working tree at commit `cab41e77` (branch `v1.8/phase-11-multi-portfolio-live`, clean)
- All ~60 citations in the Citation Verification Table, read via `sed -n`/`grep -n` against real files
- `migrations/versions/` — full revision chain walked, head confirmed `p10_strategy_portfolio_subs`
- `tests/` — grep for `_link_venue_account_to_portfolios` call sites

### Primary (HIGH confidence) — planning artifacts
- `.planning/phases/11-multi-portfolio-live/11-CONTEXT.md` — 30 locked decisions (D-01..D-30)
- `.planning/REQUIREMENTS.md` — MPORT-01..07 (MPORT-07 text read in full, lines ~318-350)
- `.planning/STATE.md` — milestone gate, carried defects, prior-phase decisions
- `./CLAUDE.md` — project constraints table above

### Not consulted (deliberately)
- No web search, no Context7, no package registry. **This phase installs zero external packages** —
  the milestone-wide zero-new-dependency gate (P1–P12) forbids it, and nothing in MPORT-01..07 requires
  one. The `## Package Legitimacy Audit` section is therefore **not applicable** and is omitted.

---

## Metadata

**Confidence breakdown:**
- Citation verification: **HIGH** — every line read directly from the tree
- Research Items 1–4: **HIGH** — each answered from code, with the contradicting evidence quoted
- F-1 / F-2 confirmation: **HIGH** — both defects reproduced by reading the exact cited lines
- F-3 / F-4 / F-5 (new findings): **HIGH** — each traced to specific lines
- Assumptions A1–A4: **LOW by construction** — flagged precisely because they are unverifiable from
  source or out of grep scope

**Research date:** 2026-07-21
**Valid until:** until the first W1 commit lands (this document describes a pre-P11 tree; every line
number becomes stale the moment schema work begins). Treat as a **planning-time snapshot**, and
re-verify any citation before acting on it in a later wave.
