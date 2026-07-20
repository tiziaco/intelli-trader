# Phase 10 — Pre-Execution Plan Audit (10-06 … 10-09)

**Audited at:** `736f3ae2` (post-wave-2, 10-05 in flight)
**Scope:** factual claims only. D-NN decisions and architecture NOT under audit.

## Verdict Summary

| Plan | Findings | Severity | Executor must know |
|------|----------|----------|--------------------|
| 10-06 | 4 | 1 high (binding-decision conflict), 3 medium | WD-1 (resolved after the plan was written) **reverses** the plan's `enable` semantics; the "`symbol = event.symbol` at `universe_handler.py:498`" site does not exist — it is `strategies_handler.py:512` |
| 10-07 | 3 | 1 medium, 1 low, 1 pending | `StrategiesHandler` **already has** `self.feed: BarFeed` — do not inject a second feed handle for the F-1 gate |
| 10-08 | 4 | **1 critical**, 1 high, 1 high, 1 low | `validate()` does **NOT** re-run the SHORT-01/D-07 direction gate — the plan's entire justification for `direction` being safely mutable is false, and T-10-55's mitigation does not exist |
| 10-09 | 2 | 2 low | Both are cosmetic/pending-10-05; the plan's gate list is otherwise clean and correctly avoids the `tests/golden/` trap |

**Cross-cutting `@cache` trap: CLEAN.** No plan among 10-06…10-09 directs adding `@cache`/`@lru_cache` under `itrader/`. Verified: `grep -rn "@cache\|lru_cache" 10-0[6789]-PLAN.md` returns nothing. The locked gate (`tests/integration/test_cache_classification.py:110`, `len(applied) == 3`) is not threatened by these plans.

---

## 10-06 — 4 finding(s)

### F1. WD-1 reverses the plan's `enable` semantics — [CONTRADICTION — binding decision]

**Plan claims:** "D-07: `enable` sets `is_active=True` + persists `enabled=True` … The object STAYS in `self.strategies` and its indicators stay **WARM**, so `enable` trades the next bar with **NO re-warmup**." (10-06-PLAN.md:24)

Restated in the `<action>` (10-06-PLAN.md:386-387): "Comment cites **D-07**: the object STAYS in `self.strategies` with its indicators WARM so `enable` trades the next bar with no re-warmup (removing it would cost a full 100/280-bar re-warm)". And in Test 2 (10-06-PLAN.md:252-253) and `<success_criteria>` (10-06-PLAN.md:486).

**Binding decision (post-dates the plan):** `10-WAVE-DECISIONS.md:22-29` — WD-1:
```
enable(strategy) ->
    strategy.is_active = True
    strategy.mark_unwarm()          # force re-warm
    warmup_pipeline.warm(strategy)  # reuse the P7 warmup path
    # first signal only after the window is contiguous
```
WD-1 explicitly **rejects** the plan's behavior: "*Trade immediately (10-03's raw as-is behavior)*: warmth is monotone so it 'works', but signals silently span the discontinuity. **Rejected on correctness.**" (10-WAVE-DECISIONS.md:37-39). WD-1's header names Plan 10-06 (`enable` verb) as a binder.

**Live code corroborates WD-1's premise:** `itrader/strategy_handler/strategies_handler.py:171` — `if not strategy.is_active:` is placed **first** in the `calculate_signals` loop (as 10-03 shipped), so `strategy.update` never runs while disabled and indicator state **freezes**. The plan's "indicators stay WARM" is true only in the trivial sense that the buffer is untouched; the window acquires an N-bar hole spanning the disabled period.

**Consequence if implemented literally:** a re-enabled SMA/MACD strategy computes its first signal from a window containing a discontinuity — silently wrong indicator values. This is the exact defect class the milestone exists to eliminate. Test 2 as written would also *pin* the wrong behavior, and Test 4's idempotency arm ("`enable` on an already-enabled strategy mutates nothing") stays correct under WD-1 but Test 1's assertion set does not.

**Recommended handling:** implement WD-1, not the plan text. `enable` → `is_active = True` → `mark_unwarm()` → drive the **same** warm path Plan 07's `add` uses (WD-1's implementation note: "`enable` and `add` should converge on one warm path rather than two"). Note `mark_unwarm` does **not** exist on `Strategy` today (`grep -rn "def mark_unwarm" itrader/` → no match) — the warm/dark state is held by `UniverseHandler`'s `_universe.mark_ready`/`mark_failed` (`universe_handler.py:548-557`) and the `_StrategyWarmthReadModel` seam (`universe_handler.py:324`). Resolve where "unwarm" is expressed **before** writing Task 2's tests, and record the choice in the SUMMARY. Rewrite Test 2 and the `<success_criteria>` line accordingly.

---

### F2. The `symbol = event.symbol` call site named for Task 1 does not exist — [FALSE]

**Plan claims:** "`symbol` becomes optional … `__str__` and the `symbol = event.symbol` read at `universe.py:498` are both updated to tolerate its absence" (10-06-PLAN.md:20). Repeated three more times:
- 10-06-PLAN.md:97-98 — "The two assuming call sites — `__str__` and the `symbol = event.symbol` read at `universe_handler.py:498` — are updated in Task 1/Task 2"
- 10-06-PLAN.md:143-145 (Task 1 `<read_first>`) — "`itrader/universe/universe_handler.py:498` — the `symbol = event.symbol` read that assumes presence"
- 10-06-PLAN.md:205-208 (Task 1 `<action>`) — "Edit `itrader/universe/universe_handler.py:498` — the `symbol = event.symbol` read. … Make the read tolerate `None`: this handler only acts on the ticker verbs, so guard on the verb"

Task 1's `<files>` is `itrader/events_handler/events/universe.py, itrader/universe/universe_handler.py` (10-06-PLAN.md:135).

**Live code:** `itrader/universe/universe_handler.py:494` is `def _begin_warmup(self, sym: str) -> None:`; **line 498 is inside its docstring**. `universe_handler.py` contains **no** `on_strategy_command` and **no** read of a `StrategyCommandEvent.symbol` — its `event.symbol` reads (`:544`, `:548-557`, `:572-578`) are all on `BarsLoaded`/`BarsLoadFailed`, which are unrelated events with a genuinely required `symbol`.

The real assuming site is **`itrader/strategy_handler/strategies_handler.py:512`** — `symbol = event.symbol`, inside `on_strategy_command`. A second latent read is the unknown-target warning at `strategies_handler.py:491-493`, which `%`-formats `event.symbol` (lazy-format, so `None` renders as `"None"` rather than raising — cosmetic, not a crash).

**Consequence if implemented literally:** the executor edits the wrong file. Either it invents a guard in `_begin_warmup` (a no-op change to unrelated warmup code, plausibly breaking the BarsLoaded path if it "guards" `event.symbol` there), or it stalls hunting a line that does not exist. Meanwhile the file that actually holds the read — `strategies_handler.py` — is **not in Task 1's `<files>` list**, so the fix is out of Task 1's declared scope.

**Mitigating:** Task 3 *does* cover it correctly — "Move the `symbol = event.symbol` read INSIDE the ticker-verb branches" (10-06-PLAN.md:379-380) with `strategies_handler.py` in `<files>`. So the work lands, in the wrong task.

**Recommended handling:** drop `itrader/universe/universe_handler.py` from Task 1 entirely; it needs no edit. Fold the `symbol` guard into Task 3, where `strategies_handler.py:512` is already being reworked. Keep Task 1's acceptance criterion `grep -cP '^\t' itrader/universe/universe_handler.py == 0` only if the file is still touched — otherwise it is vacuous.

---

### F3. `__str__` is at line 138, not 419 — [FALSE]

**Plan claims:** "the `__str__` at `:419` that formats `self.symbol` unconditionally" (10-06-PLAN.md:142-143).

**Live code:** `itrader/events_handler/events/universe.py` is **142 lines long** (`wc -l` → 142). `StrategyCommandEvent.__str__` is at **`universe.py:138`**:
```python
    def __str__(self) -> str:
        return f"{self.type} ({self.strategy_name}, {self.verb}, {self.symbol})"
```
Line 419 does not exist.

**Consequence if implemented literally:** low — the executor is told to read the file IN FULL and the method is unmissable at 142 lines. Recorded because it is a symptom of the same line-drift as F4, and because the plan's `<read_first>` accuracy is what an executor calibrates its trust on.

**Recommended handling:** read `:138`. The plan's *substantive* claims about this file all check out (see "Clean" below).

---

### F4. Stale line numbers in `strategies_handler.py` (~14-line drift) — [FALSE]

**Plan claims:**
- "`itrader/strategy_handler/strategies_handler.py:438-512` — `on_strategy_command` IN FULL" (10-06-PLAN.md:232)
- "the unknown-target loud no-op at **:477**" (10-06-PLAN.md:233, :29, :360)
- "the CR-01 `isinstance(PairStrategy)` blanket guard at **:491**" (10-06-PLAN.md:234, :361)

**Live code:** `on_strategy_command` is at **`:452`** (def) and its body runs to **`:~545`**. The unknown-target loud no-op (`logger.warning` + `return`) is at **`:489-494`**. The CR-01 blanket `isinstance(strategy, PairStrategy)` guard is at **`:505-511`**. `symbol = event.symbol` is at **`:512`**.

The drift is consistent (~+14) with wave-1's 10-03 edits to the same file (the `is_active` guard block now at `:159-171`).

**Consequence if implemented literally:** low-to-medium. The named anchors are all distinctive enough to find by grep, and the plan says "IN FULL". But `:491` in the live file is inside the *pair-guard comment*, and `:477` is inside the *docstring* — an executor anchoring on line numbers rather than content edits comments instead of code.

**Recommended handling:** locate by symbol, not line. The plan's structural description of the dispatch (by_name locate → unknown-target no-op → pair guard → `symbol` read → `mutated` flag → ticker branches → `mutated`-gated `UniversePollEvent`) matches the live code exactly; only the coordinates drifted.

---

### 10-06 — claims that CHECK OUT CLEAN

These were verified against the tree and are correct. Do not re-litigate them:

- **`StrategyCommandEvent` is a `msgspec.Struct`, not a frozen `@dataclass`** — `universe.py:100`: `class StrategyCommandEvent(Event, frozen=True, kw_only=True, gc=False)`. The plan states this explicitly and correctly flags CLAUDE.md as stale (10-06-PLAN.md:138-140). ✅
- **`type` is a `ClassVar[EventType]`, not a field** — `universe.py:119`. ✅
- **Fields are `strategy_name: str`, `verb: str`, `symbol: str`; `add_ticker`/`remove_ticker` factories exist** — `universe.py:120-136`. ✅
- **The class docstring already anticipates the change** — `universe.py:110-111`: *"the vocabulary grows to enable/disable/reconfigure later"*. ✅
- **`StrategyCommandEvent` spans `:100-142`** — exact. ✅
- **`base.py:974` = `subscribe_portfolio`, `:988` = `activate_strategy`, `:193` = `is_active`** — all three exact. `unsubscribe_portfolio:981` and `deactivate_strategy:991` also exist (both idempotent, WR-01-guarded) — the "sanctioned mutator" the plan tells the executor to look for is real. ✅
- **`pair_base.py` D-17 evidence sites: `_run_init:144`, `is_pair_ready:185`, `_entry:247`** — all three exact. ✅
- **Indentation:** `universe.py` = 0 tab / 59 space (4-space ✅); `universe_handler.py` = 0 tab / 110 space (4-space ✅); `strategies_handler.py` = 617 tab / 0 space (TABS ✅); `live_trading_system.py` = 0 tab / 348 space (4-space ✅). **The plan is right and `10-CONTEXT.md:360` is WRONG** — CONTEXT claims "`universe/` are **tabs**". 10-06 caught this (10-06-PLAN.md:146-149, :205-207). Trust the plan, not CONTEXT, on this point.
- **`live_trading_system.py:1533` = `facade._config_router = ConfigRouter(`** and the `system_store is not None` gate opens at **`:1520`** — the plan's ":1519-1560" and ":1533" precedent are accurate (pre-10-05; 10-05 may shift them). ✅

---

## 10-07 — 3 finding(s)

### F1. `StrategiesHandler` already has a feed reference — [FALSE]

**Plan claims:** "**`StrategiesHandler` has no feed reference today**: read how it could reach the base timeframe and capacity (an injected read-model handle, mirroring the injected `PortfolioReadModel` / `BacktestBarFeed` read-model seams …). **Inject the minimum needed**" (10-07-PLAN.md:213-218). Task 3 repeats it: "If the F-1 warmability gate (Task 1) needs a feed/read-model handle on `StrategiesHandler`, inject it here too, next to the others" (10-07-PLAN.md:419-420). 10-08 then inherits the premise: "the feed/read-model handle injected in Plan 07 Task 3 for the F-1 add gate. **Reuse it; do not inject a second one.**" (10-08-PLAN.md:374-375).

**Live code:** `itrader/strategy_handler/strategies_handler.py:41` — `feed: BarFeed` is the **second positional constructor parameter**, stored at **`:78`**: `self.feed: BarFeed = feed`. And `cache_capacity()` is on the **`BarFeed` ABC itself** — `itrader/price_handler/feed/base.py:125`:
```python
    def cache_capacity(self) -> int:
        """The derived shared recent-bars cache capacity (P5-D16/P5-D22)."""
        return derive(self._raw_bar_consumers)
```
So `self.feed.cache_capacity()` is available **today**, on both the backtest and live feeds, with no injection and no new wiring.

**Partially true residue:** `base_timeframe` is **not** on the `BarFeed` ABC — it is a `LiveBarFeed.__init__` parameter (`live_bar_feed.py:84`). So the F-1 gate does need *a* way to reach the base timeframe, but that is one attribute, not a whole read-model seam.

**Consequence if implemented literally:** the executor injects a redundant second feed/read-model handle onto `StrategiesHandler`, creating two paths to the same object that can diverge — and adds needless wiring to `live_trading_system.py` (the `ignore_errors` mypy blindspot file, where an orphaned name passes mypy *and* the suite silently, per 10-09's own Task 2 step 5). 10-08 then compounds it by instructing "reuse it; do not inject a second one" — pointing at the redundant handle rather than `self.feed`.

**Recommended handling:** use `self.feed.cache_capacity()` directly. For the base timeframe, prefer reading it off `self.feed` (guard with `getattr`/`hasattr` so the backtest feed, which has no `base_timeframe`, skips the gate cleanly — which is exactly the plan's own "Skip the gate cleanly when no feed handle is injected" degrade arm, just keyed on the attribute rather than the handle). Do **not** add a second constructor parameter. Correct 10-08's Task 3 `<read_first>` accordingly.

---

### F2. `_on_symbol_removed` line number contradicts itself — [CONTRADICTION — internal]

**Plan claims (Task 1):** "`itrader/universe/universe_handler.py:490-515` — **`_on_symbol_removed` at :492** in the REMOVE branch, and `spawn_warmup` at :508" (10-07-PLAN.md:132-134).

**Plan claims (Task 2):** "`itrader/universe/universe_handler.py:612-660` — **`_on_symbol_removed(sym, asof)` at :612** IN FULL" (10-07-PLAN.md:264-265).

The same plan gives two different addresses for the same method, 120 lines apart.

**Live code:** **Task 2 is correct.** `universe_handler.py:612` — `def _on_symbol_removed(self, sym: str, asof: datetime) -> None:`. Line **`:494`** is `def _begin_warmup(self, sym: str) -> None:` — the method that *contains* the `spawn_warmup` call at `:508` (`self._provider.spawn_warmup(sym, self._timeframe, depth)`), so Task 1's ":508" anchor is right but its ":490-515" range describes `_begin_warmup`, not the REMOVE branch.

**Consequence if implemented literally:** low-to-medium. Task 1 only *reads* these; the contradiction is a trust signal rather than a defect generator. But an executor anchoring Task 1's warmup-pipeline understanding on ":492 = `_on_symbol_removed`" mis-maps the add path onto the remove path at exactly the moment it is deciding "the `UniversePollEvent` IS the whole warmup wiring."

**Recommended handling:** Task 1's range is `_begin_warmup` at **`:494-513`** (the live-provider `spawn_warmup` arm at `:505-509` and the paper/no-provider synchronous `feed.warmup` + immediate `mark_ready` fallback at `:510-512`), then `on_bars_loaded` at **`:516`**. `_on_symbol_removed` is **`:612`**, `on_fill` is **`:654`**, `_emit_force_close_exit` is **`:707`** — Task 2's coordinates are all exact.

---

### F3. `build_strategy` / `registry/rehydrate.py` — [UNVERIFIABLE (pending 10-05)]

**Plan claims:** "`itrader/strategy_handler/registry/rehydrate.py` — `build_strategy(rec, *, catalog, policy_registry)`. `add` uses the IDENTICAL path so the two cannot drift." (10-07-PLAN.md:126-128, key_links :47-50)

**Live tree:** `itrader/strategy_handler/registry/` contains `__init__.py`, `catalog.py`, `config_codec.py` — **no `rehydrate.py`**. This is 10-05's deliverable and 10-05 is executing in an unmerged worktree.

**What IS verified:** `registry/catalog.py` exists (`resolve_strategy_class`, `UnknownStrategyTypeError` — both referenced by the shipped `config_codec.py:...` import line `from itrader.strategy_handler.registry.catalog import StrategyCatalog, resolve_strategy_class`). `registry/config_codec.py` exists with `decode_strategy_config(rec, catalog, policy_registry) -> tuple[type[Strategy], dict[str, Any]]`, whose docstring states: *"The CALLER constructs. Plan 05's `build_strategy` owns the D-19 quarantine of a construction failure"* — so `build_strategy`'s expected shape is corroborated by shipped code, just not yet present.

**Recommended handling:** treat as pending. Re-verify `build_strategy`'s exact signature against `registry/rehydrate.py` **after 10-05 merges** and before Task 1. The plan's `rec`-shape claim ("`{"strategy_name": ..., "strategy_type": <from event.config>, "config": event.config}`", 10-07-PLAN.md:193-195) is worth special attention: the shipped `decode_strategy_config` reads **`rec["config_json"]`** (not `rec["config"]`) and **`rec["strategy_type"]`** as a top-level column, cross-checking it against the blob's own `strategy_type` key and raising `StrategyConfigError` on disagreement. If `build_strategy` delegates to `decode_strategy_config`, the plan's `"config"` key is wrong — it must be `"config_json"`, and `event.config` (which per 10-06 carries `strategy_type` *inside* the payload) must supply both the column and the blob consistently or the cross-check at decode fires.

---

### 10-07 — claims that CHECK OUT CLEAN

- **No `StrategiesHandler` FILL route slot exists** — `full_event_handler.py:101-102`: `FILL` = `[self.portfolio_handler.on_fill, self.order_handler.on_fill]`. `route_registrar.py:120` **appends** `self._universe_handler.on_fill` after those two. So the plan's instruction to check for a slot, find none, and add one **after** `portfolio_handler.on_fill` is correct — and the precedent (universe appending after the base consumers, `route_registrar.py:117-120`) is exactly the shape to copy. ✅
- **The oracle risk on the FILL route is real** — `_routes` is shared and executed by the backtest; the plan's MANDATORY oracle gate on Task 2 is warranted. ✅
- **`required_base_depth(warmup, strategy_timeframe, base_timeframe) -> int`** exists at `cache_registration.py:231` with `UnwarmableTimeframeError` at `:218`. Its docstring names this exact use: *"the SHARED warmability boundary the D-10 `add` and D-15 `reconfigure` arms call to decide whether a configuration is warmable against an existing ring's capacity (a `deque` `maxlen` is fixed at creation, so a live ring cannot resize — those arms reject rather than resize)"*. F-1 is confirmed real by shipped code. ✅
- **`universe_handler.py` is 4-SPACE and is read-only in this plan** — correct (0 tab / 110 space). ✅
- **`add_strategy` carries the SHORT-01/D-07 gate and the IN-01/IN-06 `min_timeframe` block** — `strategies_handler.py:598-607` and `:613-624`. (Line range is stale — see 10-08 F4 — but the content claim is exact, including the "recompute `min_timeframe` after a drop" hazard: `min_timeframe` is derived only in `add_strategy` and never recomputed on removal.) ✅

---

## 10-08 — 4 finding(s)

### F1. `validate()` does NOT re-run the SHORT-01/D-07 direction gate — [FALSE] ⚠️ **MOST DANGEROUS FINDING IN THE PHASE**

**Plan claims it in four places:**
1. `must_haves.truths` (10-08-PLAN.md:31): "D-15 MUTABLE via `reconfigure`: windows, `sizing_policy`, `sltp_policy`, **`direction` (`validate()` re-runs the SHORT-01/D-07 registration gate)**, `allow_increase`, `max_positions`"
2. Task 3 `<read_first>` (10-08-PLAN.md:367-368): "`itrader/strategy_handler/strategies_handler.py:555-613` — `add_strategy`'s SHORT-01/D-07 direction gate. **`validate()` re-runs it, which is why `direction` is D-15-mutable.**"
3. Task 3 `<action>` (10-08-PLAN.md:396-397): "`direction` (**`validate()` re-runs the SHORT-01/D-07 registration gate**)"
4. Threat register T-10-55 (10-08-PLAN.md:483): "**`validate()` re-runs the SHORT-01/D-07 two-flag registration gate on every reconfigure**, so a non-`LONG_ONLY` direction is admitted only when both `allow_short_selling` and `enable_margin` are on. **This is why `direction` is safely D-15-mutable.** Gated by Test 15."

**Live code — the gate is in the HANDLER, not the strategy:**

`itrader/strategy_handler/strategies_handler.py:598-607` (inside `add_strategy`):
```python
		# SHORT-01/D-07 two-flag registration gate: a non-LONG_ONLY direction is
		# admissible ONLY when BOTH allow_short_selling AND enable_margin are on.
		if strategy.direction is not TradingDirection.LONG_ONLY:
			if not (self._allow_short_selling and self._enable_margin):
				raise ValueError(
					"Non-LONG_ONLY strategies (LONG_SHORT / SHORT_ONLY) require "
					"BOTH allow_short_selling AND enable_margin to be enabled "
					...
				)
```
The two flags it reads are **handler-instance state** — `self._allow_short_selling` / `self._enable_margin`, set in `StrategiesHandler.__init__` at `:91-92`. A `Strategy` has no access to them.

`itrader/strategy_handler/base.py:325-332` — `validate()` is a **no-op**:
```python
	def validate(self) -> None:
		"""Overridable cross-field validation hook (D-09).

		Run after ``_apply_params`` (kwargs applied + enums coerced) on every
		construction and reconfigure. No-op by default; ``SMAMACDStrategy``
		expresses ``short_window < long_window`` through it.
		"""
		...
```

The only shipped overrides check unrelated things:
- `SMA_MACD_strategy.py:38-42` — `if self.short_window >= self.long_window: raise ValueError("short_window must be < long_window")`. **No direction check.**
- `pair_base.py:99` and `eth_btc_pair_strategy.py:81` — pair-shape validators. **No direction check.**

`validate()` is called from `Strategy.__init__` (`base.py:211`) and from `Strategy.reconfigure` (`base.py:695-718`). **Neither reaches `add_strategy`.** `reconfigure` does not touch the handler at all.

**Consequence if implemented literally:** the plan's design is trial-construct `cls(**merged)` → persist → `strategy.reconfigure(**merged)`. The trial construction runs `_apply_params` + `validate()` + `_run_init()` — **none of which check `direction`**. So `reconfigure(config={"direction": "SHORT_ONLY"})` on a handler with `allow_short_selling=False, enable_margin=False` **validates, persists, and applies**. The strategy is now live, emitting short intents, on an engine whose margin/lock-and-settle model was never enabled — the exact capability SHORT-01 exists to gate, reached through an external operator payload that bypasses the only gate in the system. T-10-55 is filed as **mitigated** on a mechanism that does not exist.

**Why this is the phase's most dangerous finding:** this is the 10-04 failure mode *without* 10-04's saving grace. It is a **wrong-but-internally-consistent premise** — repeated in the truths, the read_first, the action, and the threat register, all agreeing with each other. Nothing in the plan's prose contradicts it. The one friction point is Test 15 (10-08-PLAN.md:198-200), which *demands* the reject — so a TDD executor writing Test 15 first will see it go RED and stay RED through Task 2. **But** the plan tells that executor the mechanism already exists ("`validate()` re-runs it"), so the natural diagnosis is "my test is wrong / my fixture's flags are misconfigured," not "the plan's premise is false." An executor who resolves the RED by adjusting the fixture rather than adding the gate ships the hole with a green suite.

**Recommended handling:** the `direction` re-gate must be **built**, not assumed. Options, in preference order:
1. **Handler-side check in the `reconfigure` branch** (recommended — mirrors where the gate already lives, and keeps `Strategy` ignorant of handler policy): after the trial construction and **before** persist, if `trial.direction is not TradingDirection.LONG_ONLY and not (self._allow_short_selling and self._enable_margin)` → loud reject. This reuses the exact predicate from `add_strategy:603` — factor it into a shared private helper (e.g. `_direction_admissible(direction) -> bool`) called from **both** `add_strategy` and the `reconfigure` branch, so the two cannot drift.
2. Add `direction` to `_RECONFIGURE_IMMUTABLE` and defer — a safe but lesser capability, and a D-15 change requiring the owner's sign-off.

**Do NOT** push the check down into `Strategy.validate()` — it has no access to the handler's flags, and threading them onto every strategy instance inverts the D-12 pure-alpha boundary the base's docstring pins (`base.py:174-186`).

Also note: **10-07 Task 1 inherits the same gap in the opposite direction and is FINE.** `add` calls `self.add_strategy(strategy)`, which *does* run the gate at `:598-607`. 10-07's claim "(which runs the SHORT-01/D-07 direction gate and the D-02 duplicate reject)" (10-07-PLAN.md:220-221) is **correct** for `add_strategy`'s SHORT-01 half. (Its D-02 half is pending 10-05 — the duplicate reject is 10-05's addition and is not in `add_strategy` at `:569-627` today.)

---

### F2. `name` is a mutable declared param the D-15 deny-lists do not cover — [FALSE / gap]

**Plan claims:** "`itrader/strategy_handler/base.py:170-186` — **the ten class-body declarations. The D-15 partition is defined over exactly these** plus the subclass extras." (10-08-PLAN.md:365-366)

And: "`_RECONFIGURE_IMMUTABLE = frozenset({"strategy_type"})` … `_RECONFIGURE_VERB_ONLY = frozenset({"tickers"})` … **Everything else on the authoring surface is MUTABLE via `reconfigure`** … **Do NOT build a positive allowlist of mutable names**: `_apply_params` already loud-rejects unknown params … **Deny-list the two closed sets and let the existing validator own the rest.**" (10-08-PLAN.md:391-400)

**Live code — `base.py:173-186`, the ten declarations:**
```python
	timeframe: timedelta          # required — no class-attr value
	tickers: list[str]            # required
	sizing_policy: SizingPolicy   # required
	direction: TradingDirection = TradingDirection.LONG_ONLY
	allow_increase: bool = False
	max_positions: int = 1
	sltp_policy: SLTPPolicy | None = None
	max_window: int = 0
	warmup: int = 0
	name: str = "strategy"        # D-03 discretion: default name (a subclass pins it)
```
The count is exactly ten — the plan is right about that. But enumerate the plan's own D-15 partition against it:

| Declared param | Plan's disposition | Real? |
|---|---|---|
| `timeframe` | constrained-mutable | ✅ covered |
| `tickers` | `_RECONFIGURE_VERB_ONLY` | ✅ covered |
| `sizing_policy` | mutable | ✅ |
| `direction` | mutable "(`validate()` re-gates)" | ❌ **F1** |
| `allow_increase` | mutable | ✅ |
| `max_positions` | mutable | ✅ |
| `sltp_policy` | mutable | ✅ |
| `max_window` | *unaddressed* | ⚠️ falls through to "mutable" |
| `warmup` | *unaddressed* | ⚠️ falls through to "mutable" |
| **`name`** | *unaddressed* | ❌ **falls through to "mutable"** |

`strategy_type` — the sole member of `_RECONFIGURE_IMMUTABLE` — is **not a declared param at all**. It is an *envelope key* (`config_codec.py`: `_ENVELOPE_KEYS: frozenset[str] = frozenset({_TYPE_KEY, _VERSION_KEY})`), and `_apply_params` would already loud-reject it as `UnknownParamError`. So the one deny-list the plan builds guards a name that was never on the surface, while `name` — which **is** on the surface, and **is** the store's primary key — is left mutable.

**`name` is the store PK.** Per 10-06's `_persist_strategy` spec (10-06-PLAN.md:348-350): `self.registry_store.upsert(strategy_name=strategy.name, ...)`. And the shipped codec pins the identity coupling explicitly (`config_codec.py`, `_SKIPPED_FIELDS`): *"Trap 2 (D-02): `name` is the authoring kwarg; `strategy_name` is the store PK — the same value under two spellings. Storing it in the blob would permit a row whose PK and blob disagree; omitting it makes that disagreement UNREPRESENTABLE."*

**Consequence if implemented literally:** `reconfigure(strategy_name="s1", config={"name": "s2"})` →
- allowlist check passes (`name` in neither deny-list),
- trial `cls(**merged)` succeeds (`name: str` is a legal kwarg with a default),
- persist writes `upsert(strategy_name=trial.name → "s2", ...)` — **a brand-new row**,
- apply renames the live instance to `"s2"`,
- the original `"s1"` row is **orphaned**: never deleted, still `enabled=True`.

On the next restart, rehydrate builds **two** instances from two rows — and per 10-07's D-02 duplicate reject, or per `by_name` collision in `on_strategy_command:487`, the roster is now inconsistent with the store in a way no verb can repair. It also silently defeats the codec's stated "makes that disagreement UNREPRESENTABLE" invariant, since the *live instance* now disagrees with the PK it was loaded under.

`warmup` / `max_window` are a lesser variant: both are in the codec's `_DERIVED_FIELDS` (excluded from the blob because `_run_init` unconditionally overwrites them), but `_apply_params` still **accepts** them as kwargs. Passing `max_window=500` through `reconfigure` is accepted, then partially overwritten by `_run_init`'s `max(handle-derived, class value)` — the F-2 ratchet the codec's comment warns about, reachable directly through the verb.

**Recommended handling:** add `name` to `_RECONFIGURE_IMMUTABLE` (identity is not a param — renaming is `remove` + `add`, exactly the plan's own rationale for `strategy_type`), and either add `warmup`/`max_window` to it or route them through the codec's `_DERIVED_FIELDS` (which is the *authoritative* derived set — import it rather than re-listing, or the two drift). Suggested:
```python
_RECONFIGURE_IMMUTABLE = frozenset({"strategy_type", "name"}) | _DERIVED_FIELDS
```
Keep `strategy_type` in the set — it is defense-in-depth even though `_apply_params` would also reject it — but do not let its presence create the impression the set was derived from the real surface. Add a test: reconfigure carrying `name` is a loud reject; assert the store still holds exactly one row under the original PK.

---

### F3. The merge is specified in ENCODED space but consumed as if DECODED — [CONTRADICTION — internal]

**Plan claims (Step 1, 10-08-PLAN.md:273-280):** "Build the merged param set (P-4 merge semantics). **Start from `encode_strategy_config(strategy)`** — the CURRENT full authoring set — and overlay `event.config`'s keys."

**Plan claims (Step 3, 10-08-PLAN.md:285-289):** "`trial = cls(**decoded_merged_params)`"

**Plan claims (Step 5, 10-08-PLAN.md:300-301):** "Call `strategy.reconfigure(**merged_params)`"

Three names — `merged`, `decoded_merged_params`, `merged_params` — for what Step 1 built. The plan never defines a decode step, and `key_links` (10-08-PLAN.md:50-51) says only "the trial construction `cls(**merged)` runs `_apply_params` + `validate` + `_run_init`".

**Live code — what `encode_strategy_config` actually returns** (`itrader/strategy_handler/registry/config_codec.py`):
- **Envelope keys that must never reach the constructor:** the function ends with `blob[_TYPE_KEY] = cls.__name__` and `blob[_VERSION_KEY] = CONFIG_VERSION`. The module pins the rule: `_ENVELOPE_KEYS: frozenset[str] = frozenset({_TYPE_KEY, _VERSION_KEY})` — *"The blob's two envelope keys are not declared params — they must never reach `cls(**params)`."* `decode_strategy_config` skips them explicitly (`if key in _ENVELOPE_KEYS: continue`).
- **Decimals are strings:** `_encode_value` → *"a Decimal crosses JSON as a STRING"* → `return str(value)`.
- **Policies are tagged dicts:** `return encode_policy(value)`.
- **Enums are `.value`:** `return value.value`.
- **`timeframe` is the alias string, `name` is dropped:** `_SKIPPED_FIELDS = _DERIVED_FIELDS | {"name"}`; `blob["timeframe"] = strategy.timeframe_alias`.

**Consequence if implemented literally:** if `merged_params` is the encoded blob (which is what Step 1 literally produces), then:
- `cls(**merged)` / `strategy.reconfigure(**merged_params)` raises `UnknownParamError` on `strategy_type` and `config_version` — a loud failure, so this arm is self-revealing; **but**
- if the executor strips the envelope keys and proceeds *without* a full decode, **`entry_z` lands on the live instance as the str `'2'`** and `sizing_policy` as a raw `dict`. `_COERCE` only coerces `timeframe`/`direction` (`base.py:138-141` — verified: exactly two entries), so **nothing catches it.** `PairStrategy.validate` would then compare `exit_z < entry_z` as `'0.5' < '2'` → lexicographic True → construction succeeds, corruption surfaces later in the alpha.

**That is the 10-04 defect, verbatim, re-entering through the reconfigure path.** 10-04's SUMMARY (10-04-SUMMARY.md:36-37) records both halves of it — the annotated-pair-knobs premise and the omitted Decimal arm — and the shipped codec now carries a prominent docstring warning: *"`entry_z` / `exit_z` / `leverage` / `use_log_prices` are annotated on `PairStrategy` and therefore MERGE into `_declared_hints(EthBtcPairStrategy)` across the MRO: they are settable authoring kwargs and must round-trip like any other param. They are not 'unannotated class constants'."*

**Mitigating:** D-17 refuses `reconfigure` on `PairStrategy` (via 10-06's `_PAIR_REFUSED_VERBS`), so the *pair's* Decimal knobs are unreachable through this verb in P10. But the hazard is structural, not pair-specific: any `Decimal`-annotated param on any catalog strategy, now or later, rides the same path — and D-17 is a P10-only deferral that the next milestone lifts.

**Recommended handling:** make the encode/decode boundary explicit and symmetric. The merge is in **blob space**; the constructor needs **param space**. Route the merged blob back through the shipped `decode_strategy_config`, which is the *only* function that knows the inverse coercions (Decimal via `to_money`, policies via `decode_policy`, `_COERCE` passthrough, envelope-key stripping, `name` from the PK):

```python
merged_blob = encode_strategy_config(strategy) | event.config   # blob space
rec = {"strategy_name": strategy.name,
       "strategy_type": type(strategy).__name__,
       "config_json": merged_blob}
cls, params = decode_strategy_config(rec, self.strategy_catalog, policy_registry)
trial = cls(**params)                    # param space
...
strategy.reconfigure(**params)           # SAME param space — one name, one shape
```
Note `decode_strategy_config` re-injects `name` from `rec["strategy_name"]`, which independently closes F2's rename hole for the *trial* — but **not** for the persist (which reads `strategy.name` after apply), so F2 still needs its own deny-list entry.

Use **one** variable name end-to-end. In the SUMMARY, state explicitly which space the persist reads: Step 4 says `config = encode_strategy_config(trial)` — that is correct and stays correct under this shape, since `trial` is a real instance.

---

### F4. Stale line numbers for `add_strategy` / `update_config` — [FALSE]

**Plan claims:** "`itrader/strategy_handler/strategies_handler.py:555-613` — `add_strategy`'s SHORT-01/D-07 direction gate" (10-08-PLAN.md:367) and "`update_config:615` (the existing `{name: kwargs}` -> `reconfigure(**kwargs)` surface)" (10-08-PLAN.md:148-149, :255).

**Live code:** `add_strategy` is at **`:569`** (body to `:627`); `update_config` is at **`:629`**. Same ~+14 drift as 10-06 F4, from wave-1's 10-03 edits. 10-07 repeats the stale `add_strategy:555-613` at 10-07-PLAN.md:123-125.

**Consequence if implemented literally:** low — both are distinctive symbols. `:615` in the live file is inside `add_strategy`'s `min_timeframe` block, not `update_config`.

**Recommended handling:** locate by symbol. Content claims are accurate at the new coordinates.

---

### 10-08 — claims that CHECK OUT CLEAN

Verified against the tree — notably, **10-08's claims about what 10-04 shipped are all correct**, which is the specific thing this audit was chartered to doubt:

- **`_DERIVED_FIELDS = frozenset({"warmup", "max_window"})`** — exact, in shipped `config_codec.py`. The plan's F-2 ratchet reasoning ("`_apply_params`' reconfigure fallback reads the prior instance value — which after `_run_init` is the post-`max()` derived value … could never shrink, silently defeating D-14's window-shrank-stays-warm case") is reproduced verbatim from the shipped module's own comment. ✅
- **The `Decimal` arm exists** in both `_encode_value` and `_decode_value`, with the float-refusal and non-finite guards. 10-04's Deviation 2 landed. ✅
- **`_COERCE` holds exactly `timeframe` + `direction`** — `base.py:138-141`. The plan's ":138-141" is exact, and its "(`timeframe`/`direction`)" gloss is right (the module's own comment says "these three engine fields," which is stale — the plan does **not** repeat that error). ✅
- **`reconfigure:695`**, **`_apply_params:214`**, **commit phase at `:295-299`**, **`validate:325`**, **`_run_init:382`**, **`__init__:188`**, **`to_dict:720`** — every one exact. ✅
- **`base.py` is 838 tab / 0 space (TABS)** — the plan's Task 2 acceptance criterion states 838/0 exactly. ✅
- **The D-13 core insight is correct:** `_apply_params` *is* already atomic (the resolve-into-locals trial phase commits at `:295-299`), and `reconfigure` *does* call `validate()` + `_run_init()` after that commit (`base.py:695-718`) — so the remaining tear is real and Task 1 Test 1 will genuinely fail against today's implementation, as the plan predicts. ✅
- **`_RECONFIGURE_VERB_ONLY = frozenset({"tickers"})`** — `tickers` is a real declared param (`base.py:174`) genuinely owned by `add_ticker`/`remove_ticker`. ✅
- **WD-1 compatibility:** WD-1 names 10-08 as a binder ("Plan 10-08 (reconfigure re-warm)"), but 10-08's D-14 grew/shrank/unchanged semantics govern *reconfigure*, not *enable*, and do not conflict with WD-1's force-re-warm-on-enable. **No conflict found.** The one thing to carry across: WD-1's "converge on one warm path" applies to `enable` (10-06), `add` (10-07), and this plan's D-14 grow arm — all three should reach the same P7 `spawn_warmup` seam. 10-08 already says so ("drive the P7 re-warm the same way D-10's `add` does … Do NOT build a second warmup path"). ✅

---

## 10-09 — 2 finding(s)

### F1. `tests/integration/test_strategy_registry_restart.py` does not exist — [UNVERIFIABLE (pending 10-05)]

**Plan claims:** "`tests/integration/test_strategy_add_warmup.py` and **`tests/integration/test_strategy_registry_restart.py`** — **the two halves this test joins.** Reuse their harness rather than inventing a third." (10-09-PLAN.md:105)

**Live tree:** `tests/integration/test_strategy_registry_restart.py` → **No such file**. `tests/integration/test_strategy_add_warmup.py` is 10-07's deliverable (also absent, as expected). The restart file is presumably 10-05's, but 10-05's plan should be re-read to confirm the exact filename it produces — 10-09 depends on it by name.

**Recommended handling:** re-verify after 10-05 merges. If 10-05 names the file differently, 10-09's `<read_first>` and its Task 2 step 7 ("confirm each of the twelve Wave 0 files named in `10-VALIDATION.md` exists") both need the corrected name — and Task 2's own instruction ("Correct any row whose `Automated Command` or `File Exists` drifted from what the phase actually built — the map must match reality") already authorizes fixing it.

---

### F2. `add_event` is at `:958`, not `:967` — [FALSE]

**Plan claims:** "`itrader/trading_system/live_trading_system.py:967` — `add_event`. The external ingress the test must call." (10-09-PLAN.md:97-98)

**Live code:** `live_trading_system.py:958` — `def add_event(self, event):`. Line `:967` is inside its docstring (the sentence describing the `STRATEGY_COMMAND` admission). Note 10-05 is editing this file and may shift both.

**Consequence if implemented literally:** negligible — the test calls `system.add_event(...)`, it does not need the line number.

**Recommended handling:** ignore; locate by symbol.

---

### 10-09 — claims that CHECK OUT CLEAN

This plan is in the best factual shape of the four. Verified:

- **`_EXTERNALLY_ADMISSIBLE` at `:56-58` already admits `STRATEGY_COMMAND`** — exact:
  ```python
  _EXTERNALLY_ADMISSIBLE = frozenset(
      {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
  )
  ```
  The plan quotes the frozenset **including `CONFIG_UPDATE`**, which is correct and is a point where **CLAUDE.md is stale** (it says add_event "admits only externally-originated `SIGNAL` and `STRATEGY_COMMAND` events" — `CONFIG_UPDATE` was added by P9 D-23, as the live docstring at `:967-968` confirms). The plan's "P10 needs no ingress change" is correct. ✅
- **`route_registrar.py:106`** — `routes[EventType.STRATEGY_COMMAND] = [` — exact. ✅
- **`itrader/core/policy_codec.py` exists** and **`itrader/strategy_handler/registry/` exists** (`__init__.py`, `catalog.py`, `config_codec.py`). ✅
- **Neither is under a mypy `ignore_errors` override** — `grep -n "policy_codec\|strategy_handler.registry" pyproject.toml` returns **nothing**, so Task 2's acceptance criterion (`== 0`) passes today and is a genuine regression guard rather than a tautology. ✅
- **`live_trading_system.py` IS under an `ignore_errors` override and IS 4-space (0 tab / 348 space)** — both claims correct. The Task 2 step-5 hand-sweep is warranted; this is a known, recorded blindspot. ✅
- **The `tests/golden/` trap is AVOIDED** — the plan's gate list names `tests/integration/test_backtest_oracle.py` for the byte-exact oracle (correct: that is where the SMA_MACD oracle lives; `tests/golden/` is artifacts and collects 0 tests). `grep -rn "tests/golden" 10-09-PLAN.md` → **no match**. Every gate path named (`tests/integration/test_backtest_oracle.py`, `tests/integration/test_okx_inertness.py`, `tests -q`, `mypy itrader`) is real and collectible. ✅
- **`poetry run pytest` over `make test`** — the plan explicitly calls this out with the right reason ("`make test` exports `ITRADER_DISABLE_LOGS=true` … and aborts in git worktrees on a missing `.env`", 10-09-PLAN.md:208-210). Both hazards are real and recorded. ✅
- **Lifecycle assertions are consistent with 10-05…10-08's intended output** — Test 3 (disable → enable → reconfigure → restart rehydrates the *reconfigured* params) and Test 4 (`remove` → force-flat → restart rehydrates nothing) both compose correctly against the verbs as planned. **One carry-forward:** Test 3's `enable` leg must reflect **WD-1** (re-warm before first signal), not 10-06's as-written no-re-warmup semantics — if 10-06 is corrected per its F1, 10-09 Test 3 inherits the correction for free. ✅

---

## Consolidated pattern: line-number drift

Three of the four plans carry ~+14-line stale coordinates into `strategies_handler.py`, and 10-06/10-07 carry bad coordinates into `universe_handler.py` / `universe.py`. Wave-1's 10-03 edits shifted `strategies_handler.py`; the plans were written against the pre-10-03 tree.

| Plan cites | Live |
|---|---|
| `strategies_handler.py:438-512` `on_strategy_command` | `:452` (body → ~`:545`) |
| `strategies_handler.py:477` unknown-target no-op | `:489-494` |
| `strategies_handler.py:491` CR-01 pair guard | `:505-511` |
| `strategies_handler.py:512` (implied) `symbol = event.symbol` | `:512` ✅ *(coincidentally exact)* |
| `strategies_handler.py:555-613` `add_strategy` | `:569-627` |
| `strategies_handler.py:615` `update_config` | `:629` |
| `universe_handler.py:498` `symbol = event.symbol` | **does not exist** (`:494` = `_begin_warmup`) |
| `universe_handler.py:492` `_on_symbol_removed` | `:612` |
| `universe.py:419` `__str__` | `:138` (file is 142 lines) |
| `live_trading_system.py:967` `add_event` | `:958` |

**Every content claim at these sites is accurate — only the coordinates drifted.** Locate by symbol, not by line, and expect further drift once 10-05 merges into `live_trading_system.py`. `base.py` coordinates (`:131`, `:138-141`, `:170-186`, `:188`, `:214`, `:295-299`, `:325`, `:382`, `:695`, `:720`, `:974`, `:981`, `:988`) and `pair_base.py` (`:144`, `:185`, `:247`) are **all exact** — that file was untouched by waves 1–2.

## Consolidated pattern: 10-CONTEXT.md factual claims remain unreliable

`10-CONTEXT.md:360` claims "`universe/` are **tabs**". Measured: `universe_handler.py` = **0 tab / 110 space**; `universe.py` = **0 tab / 59 space**. Both 4-space. 10-06 caught this and says so explicitly (10-06-PLAN.md:146-149) — **trust the plan over CONTEXT here**. This is the third confirmed CONTEXT factual error in the phase (after the Alembic-head error that bit 10-02 and the pair-annotation error that bit 10-04). CONTEXT's *decisions* remain binding; its *measurements* should be re-verified at the tree before use.
