# Phase 1: Instrument Value Object - Research

**Researched:** 2026-06-15
**Domain:** Decimal money policy, frozen value objects, universe/read-model wiring, byte-exact golden-master discipline
**Confidence:** HIGH (all claims verified against the codebase at file:line; no external-package decisions)

## Summary

Phase 1 lands `core/instrument.py` (a frozen `Instrument` value object), rewires
`core/money.py::quantize()` to read precision off an `Instrument`, deletes the
hard-coded `_INSTRUMENT_SCALES` table, introduces a `Universe` read-model class
(by composition over the existing pure `derive_membership`/`is_active`), and adds a
pure `derive_instruments(...)` sibling. `ExchangeLimits.min_order_size` is demoted
to a venue fallback; `SimulatedExchange` learns Instrument-first → ExchangeLimits-
fallback resolution. The whole phase **re-baselines nothing** — the SMA_MACD spot
oracle (134 trades / `final_equity 46189.87730727451`) must stay byte-for-byte.

The single most important verified finding: **the D-02a blast-radius claim holds
exactly.** `core.money.quantize()` (the module-level function) is imported and
called only from `tests/unit/core/test_money.py` — verified by grep across both
`itrader/` and `tests/`. Every other `.quantize(...)` hit in the tree is the
stdlib `Decimal.quantize()` *method* (e.g. `cash_manager.py:64`, `:502`,
`validators.py:140`), which is a different call site that does not touch
`_INSTRUMENT_SCALES`. So rewiring `quantize()` updates the production money path by
**zero bytes** — the oracle holds because the production rounding path never calls
the module function at all.

The second load-bearing finding (a real planning constraint, not in CONTEXT):
**the CSV is `.astype(float)` at load time** (`csv_store.py:178`). The in-memory
frame is float64, so INST-02 string-inference **cannot** read decimal places off
the loaded frame — it must read the raw CSV cell as a string *before* the float
cast, or be fed the symbol's declared precision so it never runs on BTCUSD at all.
Since D-10 mandates BTCUSD always takes the **declared** branch, the inference path
is provably never exercised on the oracle symbol — making it safe to land but
requiring a non-oracle test fixture to cover INST-02.

**Primary recommendation:** Land `Instrument` in `core/instrument.py` mirroring
`core/bar.py::Bar` (frozen/slots/kw_only, Decimal fields), make `quantize` take an
`Instrument`, update only `test_money.py` call sites, build a `Universe` façade
constructed at the existing `derive_membership` wiring point in `backtest_runner.py`,
leave BTCUSD's `min_order_size` undeclared so it falls through to `ExchangeLimits(0.001)`,
and gate the whole phase on the existing `test_backtest_oracle.py` byte-exact assertions.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `Instrument` value object (type) | `core/` | — | Frozen value object; core depends on nothing inside itrader (D-04); mirrors `core/bar.py::Bar` |
| `quantize()` rounding mechanism | `core/money.py` | — | Pure stateless fn taking an `Instrument` (D-05); owns zero domain state |
| Symbol → `Instrument` resolution | `universe/` (`Universe` class + `derive_instruments`) | — | The universe already owns the symbol set (D-20/D-21); no parallel registry (D-03) |
| Instrument-map construction | wiring (`backtest_runner.py` / live runner) | `universe/derive_instruments` | Derive-once-at-wiring purity; built where `derive_membership` runs today (D-08) |
| `min_order_size` resolution | `Instrument` (source of truth) | `ExchangeLimits` (venue fallback) | D-01; `SimulatedExchange` reads Instrument-first, falls back to limits |
| Declared instrument config | config layer (declared params) | `_DEFAULT_SCALES` (final fallback) | Declared → inferred → default ladder (D-09) |

## Standard Stack

No new external packages. Phase 1 is pure-stdlib (`decimal`, `dataclasses`,
`datetime`, `typing`) over the existing codebase. The frozen-dataclass template,
Decimal money policy, and read-model pattern all already exist in-tree.

| In-tree asset | Location | Role in this phase |
|---------------|----------|--------------------|
| `Bar` frozen value object | `itrader/core/bar.py:29` | Exact shape template for `core/instrument.py` |
| `quantize` / `to_money` / `ONE` | `itrader/core/money.py:53-76` | `quantize` rewired; `_INSTRUMENT_SCALES` deleted; `_DEFAULT_SCALES` kept |
| `derive_membership` / `is_active` / `active_membership` | `itrader/universe/membership.py:44,87,142` | Pure helpers the `Universe` class composes (do NOT reimplement) |
| `ExchangeLimits` | `itrader/config/exchange.py:98` | `min_order_size` demoted to venue fallback |
| `SimulatedExchange._min_order_size` | `itrader/execution_handler/exchanges/simulated.py:117` | Learns Instrument-first → ExchangeLimits-fallback |
| `BacktestRunner._initialise_backtest_session` | `itrader/trading_system/backtest_runner.py:46-81` | Universe construction/injection point (Trap-4 ordering) |
| `CsvPriceStore._load_csv` | `itrader/price_handler/store/csv_store.py:123` | INST-02 string-read must precede the `.astype(float)` at line 178 |

### Package Legitimacy Audit

Not applicable — Phase 1 installs no external packages. All imports are Python
stdlib already present in the runtime (`decimal`, `dataclasses`, `datetime`,
`typing`, `collections.abc`).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INST-01 | `Instrument` (`core/instrument.py`, frozen) is per-symbol source of price/quantity precision + `min_order_size`; `quantize` reads precision from it; `_INSTRUMENT_SCALES` deleted | Verified `quantize` callers are tests-only (§Pitfall blast radius); `Bar` template at `core/bar.py:29`; `_INSTRUMENT_SCALES` at `money.py:44` is the only deletion target (no production reference) |
| INST-02 | Price precision: declared → inferred (string-read, capped) → default; quantity/min_order_size declared-or-default; BTCUSD always declared-8dp | `csv_store.py:178` casts to float — inference must read raw CSV string pre-cast; D-10 keeps BTCUSD on declared branch so inference never runs on the oracle |
| INST-03 | `Instrument` carries `maintenance_margin_rate`, `max_leverage`, `settles_funding: bool`; `ExchangeLimits` demoted to venue fallback | Fields enumerated in §Instrument shape; `ExchangeLimits.min_order_size` at `exchange.py:103`; `SimulatedExchange` read point at `simulated.py:117` |

## Architecture Patterns

### System Architecture Diagram

```
                          WIRING (once, at run-init)
                          ──────────────────────────
 strategies ─┐
 screeners ──┼─► derive_membership() ──► list[str] members (unchanged)
 declared   ─┤        │
 config     ─┤        ▼
 price data ─┴─► derive_instruments() ──► dict[str, Instrument]
                      │
                      ▼
              Universe(members, instrument_map)        ◄── injected read-model
                 .members -> SAME list[str]                (like PortfolioReadModel
                 .instrument(sym) -> Instrument             / BacktestBarFeed)
                 .is_active(sym, asof) -> bool (optional)
                      │
       ┌──────────────┼───────────────────────────┐
       ▼              ▼                            ▼
  feed.bind        SimulatedExchange         core.money.quantize(value, instr, kind)
  (members)        min_order_size:                reads scale off the Instrument
       │           Instrument-first →             handed in — no lookup, no state
       ▼           ExchangeLimits(0.001)               │
  ping-grid                                            ▼
  precompute                                  Decimal at the money boundary
  (Trap-4 order PRESERVED)                    (ROUND_HALF_UP)
```

Trace the oracle path: BTCUSD declares `price_precision=8dp` and leaves
`min_order_size` undeclared → exchange resolves `Instrument(None) → ExchangeLimits(0.001)`
(the value read today) → byte-exact. Inference never runs on BTCUSD (declared wins).

### Recommended Project Structure
```
itrader/
├── core/
│   ├── instrument.py     # NEW: frozen Instrument value object (mirrors bar.py)
│   ├── money.py          # quantize(value, Instrument, kind); _INSTRUMENT_SCALES deleted
│   └── bar.py            # template (unchanged)
└── universe/
    ├── membership.py     # derive_membership / is_active (unchanged — composed)
    ├── instruments.py    # NEW (or fold into membership.py): derive_instruments(...)
    └── universe.py       # NEW: Universe class (façade composing the pure fns)
```
(Exact file split for `derive_instruments` / `Universe` is Claude's-Discretion per
CONTEXT — fold or separate; keep `core` import-clean and `universe/__init__.py` barrel updated.)

### Pattern 1: Frozen value object (mirror `Bar`)
**What:** `@dataclass(frozen=True, slots=True, kw_only=True)`, Decimal fields entered via the string path, optional `from_*` classmethod factory.
**When:** The `Instrument` type.
**Example:**
```python
# Source: itrader/core/bar.py:29 (the in-tree template)
@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    time: datetime
    open: Decimal
    # ... full-precision Decimal, never rounded
```

### Pattern 2: Injected read-model (mirror `PortfolioReadModel` / `BacktestBarFeed`)
**What:** Object-shaped, constructed once at wiring, injected into consumers; queue-only rule governs writes, not read-models.
**When:** The `Universe` class (`.members`, `.instrument(symbol)`, optional `.is_active`).
**Why:** Aligns with D-20 `UniverseSelectionModel` growth target; same seam pattern the codebase already uses for cross-domain reads.

### Pattern 3: Pure derive-once-at-wiring (mirror `derive_membership`)
**What:** A pure function producing derived data at run-init, never event plumbing.
**When:** `derive_instruments(strategies, screeners, declared_config, price_data) -> dict[str, Instrument]`.

### Anti-Patterns to Avoid
- **Putting instrument state in `money.py`** — user explicitly rejected this (CONTEXT §Specific Ideas); `quantize` stays pure/stateless reading off the handed-in `Instrument` (D-05).
- **A standalone `InstrumentRegistry`** — a parallel source of truth for a symbol set the universe already owns (D-03). Use the `Universe`.
- **Reordering the Trap-4 wiring** in `backtest_runner.py:46-81` — membership derive → feed.bind → ping-grid → precompute is byte-exact-sensitive.
- **Reading inference off the loaded frame** — it is float64 (`csv_store.py:178`); read the raw CSV string pre-cast or BTCUSD inference would silently drift.
- **Declaring BTCUSD's `min_order_size`** — D-01a requires it undeclared so the exchange falls through to `ExchangeLimits(0.001)` byte-exact.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Symbol set / membership union | A new registry/union | `derive_membership` (`membership.py:44`) | Carries locked decisions M5-08/D-20/D-21; tuple-pair flattening already correct |
| Availability span query | A new is-live check | `is_active`/`active_membership` (`membership.py:87,142`) | Pure, tz-guarded, already tested |
| Decimal string entry | `Decimal(x)` | `to_money(x)` (`money.py:53`) | Avoids binary-float repr artifact (D-04) |
| Frozen value object boilerplate | Hand-rolled `__eq__`/`__hash__` | `@dataclass(frozen=True, slots=True, kw_only=True)` | Matches `Bar`; mypy-strict clean |
| Oracle diff mechanic | Byte-compare scripts | `test_backtest_oracle.py` (`pdt.assert_frame_equal`, `check_exact=True`) | Already the frozen acceptance gate |

**Key insight:** Phase 1 is almost entirely composition over existing primitives. The only genuinely new logic is the `derive_instruments` map builder and the inference string-counter — everything else is wiring.

## Detailed Findings (research priorities answered)

### 1. `quantize()` rewire surface — D-02a PROVEN

Current signature (`money.py:63`): `quantize(value: Decimal, instrument: str, kind: str) -> Decimal`.

Tables (`money.py:38-50`):
```python
_DEFAULT_SCALES = {"price": Decimal("0.01"), "quantity": Decimal("0.00000001"), "cash": Decimal("0.01")}
_INSTRUMENT_SCALES = {"BTCUSD": {"price": Decimal("0.00000001"), "quantity": Decimal("0.00000001"), "cash": Decimal("0.01")}}
```
`kind → scale`: nested `dict.get(instrument, _DEFAULT_SCALES).get(kind, _DEFAULT_SCALES[kind])`; rounding `ROUND_HALF_UP` (`money.py:76`). BTCUSD price = `0.00000001` (8dp) — this is the value `Instrument(price_precision=8dp)` must reproduce.

**All callers of the module function `quantize()` (verified by grep over `itrader/` AND `tests/`):**
- `tests/unit/core/test_money.py:27` (import), and uses at `:45`, `:50`, `:57`. **This is the ONLY importer.**
- `tests/e2e/matching/entries/limit_entry_crossval/scenario.py:53` — a *comment/docstring* pseudocode line (`qty = quantize(...)`), not a live call.

Every other `.quantize(` hit is the stdlib `Decimal.quantize()` **method** on a Decimal instance, NOT the module function:
- `itrader/portfolio_handler/cash/cash_manager.py:64` — `to_money(initial_cash).quantize(Decimal('0.01'), ...)`
- `itrader/portfolio_handler/cash/cash_manager.py:502` — `to_money(amount).quantize(self.precision, ...)`
- `itrader/portfolio_handler/validators.py:140` — `Decimal(str(value)).quantize(DECIMAL_PRECISION)`

**Conclusion (HIGH confidence):** D-02a is correct. Rewiring `quantize()` + deleting `_INSTRUMENT_SCALES` touches **only `tests/unit/core/test_money.py`** plus the production code that will *newly* call `quantize(value, instrument, kind)` in later margin phases. The production rounding path today is unaffected (it uses inline `Decimal.quantize()`), so the oracle is byte-exact by construction. `_INSTRUMENT_SCALES` has **zero** non-docstring references outside `money.py` itself.

`test_money.py` updates required: the three `quantize(...)` assertions (`:45,:50,:57`) currently pass a `str` instrument ("BTCUSD"/"UNKNOWN"); the rewire makes them pass an `Instrument` object instead. The "unknown instrument → default" test (`:57`) becomes a "default Instrument → default scale" test.

### 2. `Instrument` value object shape

Proposed field set (per design note §6 + D-01a/D-10, YAGNI-gated to named consumers):

| Field | Type | Optional? | Consumer | Notes |
|-------|------|-----------|----------|-------|
| `symbol` | `str` | required | universe key | upper-cased to match store keying |
| `quote_currency` | `str` | default `"USD"` | cash precision | source of `kind="cash"` scale (→ 2dp) |
| `price_precision` | `Decimal` | required (declared) or resolved via ladder | `quantize(kind="price")` | BTCUSD = `Decimal("0.00000001")` (8dp, declared) |
| `quantity_precision` | `Decimal` | declared-or-default | `quantize(kind="quantity")` | BTCUSD = 8dp; NOT inferable from OHLCV (D-10) |
| `min_order_size` | `Decimal \| None` | **Optional — undeclared for BTCUSD** | `SimulatedExchange` | D-01a: `None` → falls through to `ExchangeLimits(0.001)` |
| `maintenance_margin_rate` | `Decimal` | declared-or-default | Phase 4 liquidation | inert in Phase 1 |
| `max_leverage` | `Decimal` | declared-or-default | Phase 2 margin/leverage | inert in Phase 1 |
| `settles_funding` | `bool` | default `False` | Phase B (deferred) | lands inert now |

Conventions to copy from `bar.py`: `@dataclass(frozen=True, slots=True, kw_only=True)`; Decimal entered via string path (`Decimal(str(x))` / `to_money`); intra-`core` import of `to_money`/`Instrument` from `money.py` is allowed (D-05). No `asset_class`, no cash instrument (design note §6 — crypto-first).

**Precision as scale vs places:** `quantize` today rounds against a *scale* (`Decimal("0.00000001")`), not an int place-count. Recommend `Instrument` stores the **scale Decimal** directly (byte-identical to the deleted table entry) so `quantize` stays a one-line `value.quantize(scale, ...)`. If the planner prefers an int `price_precision: int = 8`, the conversion `Decimal(1).scaleb(-precision)` must reproduce `Decimal("0.00000001")` exactly — verify in a test. **Storing the Decimal scale is the lower-risk byte-exact choice.**

### 3. Universe composition seam

`derive_membership(strategies, screener_tickers=()) -> list[str]` (`membership.py:44`) — returns a deduped, **set-derived (unordered)** list; callers must not rely on order (already documented at `:69`).

Wiring point (`backtest_runner.py:60-64`):
```python
membership = derive_membership(
    engine.strategies_handler.strategies,
    engine.screeners_handler.get_screeners_universe())
engine.feed.bind(engine.global_queue, membership)   # ◄ then ping-grid → precompute (Trap-4)
```
Live mirror: `live_trading_system.py:259-263` (same shape; **note this module is mypy-deferred** — `ignore_errors=true` at `pyproject.toml:88`).

To stay byte-exact, the `Universe` façade's `.members` must return the **same `list[str]`** `derive_membership` returns today (same set-derived ordering), and `feed.bind` must receive that exact list. Recommended: construct `Universe` from the already-computed `membership` list + the `derive_instruments` map, then pass `universe.members` to `feed.bind` — identical bytes.

`derive_instruments(...)` placement: `itrader/universe/` (new `instruments.py` or fold into `membership.py` — Claude's Discretion). Inputs: registered strategies (for declared tickers), screener tickers, declared instrument config, and price data (the store, for INST-02 inference). Output: `dict[str, Instrument]`. It is pure derived-once-at-wiring data, exactly like `derive_membership`.

`Engine` is a `@dataclass` (`compose.py:80`) with `store`, `feed`, `strategies_handler`, `screeners_handler`, `execution_handler` fields — the `Universe` can be added as an Engine field and injected into the exchange / (later) margin code.

### 4. Declared instrument config source

There is **no existing per-symbol instrument config** today — precision lives only in the hard-coded `_INSTRUMENT_SCALES["BTCUSD"]`. `ExchangeLimits` (`exchange.py:98`) holds `min_order_size = Decimal("0.001")` (venue-wide, default), `max_order_size`, `max_price`, `supported_symbols`. It is NOT per-symbol.

So the planner must decide where declared `Instrument` params come from (Claude's Discretion bounded by D-09/D-10). Lowest-risk for byte-exactness: a small declared-instrument table/config that gives **BTCUSD: price 8dp, quantity 8dp, min_order_size UNDECLARED (None)**, with undeclared symbols falling through the ladder (price → inferred → `_DEFAULT_SCALES`; quantity/min_order_size → default; min_order_size → `ExchangeLimits`). This reproduces `_INSTRUMENT_SCALES["BTCUSD"]` exactly.

`ExchangeLimits` demotion: keep the class and its `min_order_size` field; reframe it (docstring) as the **venue fallback for undeclared symbols**. The `SimulatedExchange` symbol-seeding path (`_seed_supported_symbols`, `backtest_trading_system.py:45`) is orthogonal and stays untouched.

### 5. Inference path (INST-02)

CSV header (`data/BTCUSD_1d_ohlcv_2018_2026.csv`): `Open time,Open,High,Low,Close,Volume,Close time,...` (Binance-kline). Sample close: `13380.0`, `14675.11`.

**Critical constraint:** `csv_store._load_csv` does `data = data.astype(float)` (`csv_store.py:178`). The in-memory frame is float64 — reading `.astype(str)` off it would give float repr, not the source decimal count. INST-02's "read the price column as a STRING, count decimal places, cap 8dp" must operate on the **raw CSV cell** (e.g. re-read the relevant column with `dtype=str` / `pd.read_csv(..., dtype={'Close': str})`, or read before the float cast). This is a planning-level decision the inference task must encode.

**Oracle safety (verified):** D-10 + the declared table keep BTCUSD on the **declared** branch — inference is **never** invoked on BTCUSD. So the inference path cannot drift the oracle by construction. INST-02 therefore needs a **non-oracle test fixture** (a synthetic symbol with a known decimal count, e.g. a DOGE-like `0.00012345`) to prove the guard + 8dp cap, since the golden run never exercises it.

### 6. SimulatedExchange `min_order_size` resolution

Read point (`simulated.py:117`): `self._min_order_size = self.config.limits.min_order_size` (Decimal `0.001`). Used in admission at `simulated.py:424`: `elif event.quantity < self._min_order_size:`. Also re-derived on config update (`simulated.py:696`).

Teach it Instrument-first → ExchangeLimits-fallback (Claude's Discretion on plumbing): resolve per-order/per-symbol as `instrument.min_order_size if instrument.min_order_size is not None else self.config.limits.min_order_size`. Because BTCUSD's `Instrument.min_order_size` is **undeclared (None)** (D-01a), the resolution returns `ExchangeLimits(0.001)` — byte-identical to today's `self._min_order_size`. The exchange needs access to the `Universe` (inject the read-model) to look up the per-symbol `Instrument`; the per-order symbol is on `event` (the `OrderEvent`).

**Indentation:** `simulated.py` is **TABS** — match it.

### 7. Byte-exact verification method

Oracle generator: `scripts/run_backtest.py::main()` (writes `output/{trades,equity}.csv` + `output/summary.json`). Golden frozen at `tests/golden/{trades,equity}.csv, summary.json` (`summary.json`: `final_equity 46189.87730727451`, `trade_count 134`).

Acceptance gate: `tests/integration/test_backtest_oracle.py` runs the full 2018→2026 run in-process and asserts EXACT (`pdt.assert_frame_equal(..., check_exact=True)`, no tolerance) on:
- `test_oracle_behavioral_identity` — trade count + identity columns (entry/exit/side/pair), equity timestamp grid, `trade_count` (`test_backtest_oracle.py:128`).
- `test_oracle_numeric_values` — all trade/equity numeric columns + `final_cash`/`final_equity`/`total_realised_pnl` + the `metrics` dict, EXACT (`:173`).

**Re-run command:**
```bash
poetry run pytest tests/integration/test_backtest_oracle.py -v   # full byte-exact gate (slow marker)
poetry run python scripts/run_backtest.py                        # regenerate output/ for manual diff
diff <(jq -S . output/summary.json) <(jq -S . tests/golden/summary.json)
```
This test is the verifiable acceptance criterion the plan should pin.

### 8 / 9. mypy --strict and typing

`core/` and `universe/membership.py` and `backtest_runner.py` are **all under `mypy --strict`** — NOT in any override (verified `pyproject.toml:78-120`). Only `live_trading_system.py`, sql/providers, and `screeners_handler.*` are deferred. So `core/instrument.py`, `universe/instruments.py`, and the `Universe` class **must be strict-clean**.

Typing pitfalls:
- Frozen Decimal dataclass: annotate every field; no `Any`. `min_order_size: Decimal | None` (modern union, matches house style).
- `Universe` read-model: a concrete class is fine; if a Protocol is wanted for injection, mirror `PortfolioReadModel`'s structural-Protocol shape (`core/portfolio_read_model.py`). Return types must be precise: `.members -> list[str]`, `.instrument(symbol: str) -> Instrument`.
- `derive_instruments` return: `dict[str, Instrument]` (not `dict[str, Any]`).
- The live wiring touch (`live_trading_system.py`) is mypy-deferred, so a Universe edit there won't break the gate — but keep it behavior-byte-exact anyway.

## Runtime State Inventory

Phase 1 is a **code/config refactor**, not a rename/migration. No stored data,
live-service config, OS-registered state, or secrets carry the touched names.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys on `quantize`/`_INSTRUMENT_SCALES`/`Instrument`. Verified by grep. | none |
| Live service config | None — refactor is in-process. | none |
| OS-registered state | None. | none |
| Secrets/env vars | None — no env var references the touched symbols. | none |
| Build artifacts | Frozen golden artifacts `tests/golden/{trades,equity}.csv, summary.json` must remain UNCHANGED (the gate asserts against them). | verify untouched after phase |

## Common Pitfalls

### Pitfall 1: Inferring precision off the loaded float frame
**What goes wrong:** Reading decimal count off `csv_store`'s in-memory frame yields float repr, not source decimals.
**Why:** `csv_store.py:178` does `.astype(float)`.
**How to avoid:** Read the raw CSV cell as a string (e.g. `dtype=str` on the price column) before any float coercion. Since BTCUSD is declared (D-10), this path never runs on the oracle — but the INST-02 test must exercise it on a synthetic symbol.

### Pitfall 2: Declaring BTCUSD `min_order_size`
**What goes wrong:** If BTCUSD's `Instrument.min_order_size` is set, the exchange stops reading `ExchangeLimits(0.001)` and the admission gate at `simulated.py:424` may change which orders are accepted → oracle drift.
**How to avoid:** Leave it **undeclared (None)** (D-01a); resolution falls through to `ExchangeLimits(0.001)`.

### Pitfall 3: int place-count vs Decimal scale rounding mismatch
**What goes wrong:** Storing `price_precision: int = 8` and reconstructing the scale wrong yields a different `quantize` result than the deleted `Decimal("0.00000001")`.
**How to avoid:** Store the Decimal **scale** directly on `Instrument` (byte-identical to the old table), OR add a test asserting `Decimal(1).scaleb(-8) == Decimal("0.00000001")`.

### Pitfall 4: Breaking the Trap-4 wiring order
**What goes wrong:** Constructing the Universe in a way that changes the `feed.bind` membership list or reorders ping-grid/precompute → byte drift.
**How to avoid:** Compute `membership` exactly as today, pass `universe.members` (same list) to `feed.bind`, keep the `backtest_runner.py:60-81` sequence intact.

### Pitfall 5: Forgetting the tab/space per-file rule
**What goes wrong:** `simulated.py` and `backtest_runner.py` are TABS; `money.py`, `bar.py`, `universe/membership.py`, `core/` are SPACES. A normalized diff breaks a tab file.
**How to avoid:** Match each file. New files in `core/`/`universe/` → 4 spaces (match `bar.py`/`membership.py`).

## Code Examples

### Frozen value object (template to mirror)
```python
# Source: itrader/core/bar.py:29
@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
```

### Current quantize (the rewire target)
```python
# Source: itrader/core/money.py:63
def quantize(value: Decimal, instrument: str, kind: str) -> Decimal:
    scale = _INSTRUMENT_SCALES.get(instrument, _DEFAULT_SCALES).get(
        kind, _DEFAULT_SCALES[kind])
    return value.quantize(scale, rounding=ROUND_HALF_UP)
# After rewire: quantize(value: Decimal, instrument: Instrument, kind: str) ->
#   read scale off instrument.{price,quantity}_precision / quote_currency cash scale
```

### Wiring point (preserve order)
```python
# Source: itrader/trading_system/backtest_runner.py:60
membership = derive_membership(
    engine.strategies_handler.strategies,
    engine.screeners_handler.get_screeners_universe())
engine.feed.bind(engine.global_queue, membership)  # then ping-grid → precompute
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Hard-coded `_INSTRUMENT_SCALES["BTCUSD"]` in `money.py` | Per-symbol `Instrument` resolved via `Universe` | Removes domain state from the rounding mechanism; extensible to new symbols (D-09 ladder) |
| `quantize(value, str, kind)` | `quantize(value, Instrument, kind)` | Pure/stateless; INST-01 met, no dead value object left |
| `ExchangeLimits.min_order_size` as the only source | `Instrument.min_order_size` source-of-truth, `ExchangeLimits` venue fallback | Per-symbol min sizes; BTCUSD undeclared keeps the oracle byte-exact |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (+ pytest-cov, pandas.testing) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/core/test_money.py -v` |
| Full suite command | `make test` |
| Byte-exact gate | `poetry run pytest tests/integration/test_backtest_oracle.py -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INST-01 | `quantize` reads precision off `Instrument`; `_INSTRUMENT_SCALES` deleted | unit | `poetry run pytest tests/unit/core/test_money.py -v` | ✅ (must be updated to pass `Instrument`) |
| INST-01 | `Instrument` is frozen/immutable | unit | `poetry run pytest tests/unit/core/test_instrument.py -v` | ❌ Wave 0 |
| INST-02 | Declared branch wins for BTCUSD (no inference) | unit | `poetry run pytest tests/unit/core/test_instrument.py -k declared` | ❌ Wave 0 |
| INST-02 | Inference reads string, counts dp, caps at 8 (synthetic symbol) | unit | `poetry run pytest tests/unit/universe/test_derive_instruments.py -k infer` | ❌ Wave 0 |
| INST-02 | Default fallback when no data | unit | same file `-k default` | ❌ Wave 0 |
| INST-03 | `Instrument` carries mmr/leverage/settles_funding (inert) | unit | `poetry run pytest tests/unit/core/test_instrument.py -k margin` | ❌ Wave 0 |
| INST-03 | min_order_size: Instrument-first → ExchangeLimits fallback; BTCUSD reads 0.001 | unit | `poetry run pytest tests/unit/execution/ -k min_order` | ❌ Wave 0 |
| INST-01/02/03 | **Byte-exact oracle holds (134 trades / 46189.87730727451)** | integration (slow) | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | ✅ |
| ALL | mypy --strict clean on new core/universe modules | static | `poetry run mypy itrader` | ✅ (gate exists) |
| ALL | Determinism double-run identical | e2e | `poetry run pytest tests/e2e/robust/test_determinism.py -v` | ✅ |

### Sampling Rate
- **Per task commit:** the relevant unit file (e.g. `test_money.py` / `test_instrument.py`) + `poetry run mypy itrader`.
- **Per wave merge:** `make test-unit` + `poetry run pytest tests/integration/test_backtest_oracle.py`.
- **Phase gate:** `make test` green AND `test_backtest_oracle.py` byte-exact AND `mypy --strict` clean AND `test_determinism.py` green before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/core/test_instrument.py` — frozen-ness, field defaults, declared-vs-undeclared `min_order_size`, scale reproduces `Decimal("0.00000001")` (INST-01/03)
- [ ] `tests/unit/universe/test_derive_instruments.py` — declared/inferred(string-count, 8dp cap)/default ladder on a SYNTHETIC non-oracle symbol; BTCUSD-takes-declared assertion (INST-02)
- [ ] `tests/unit/execution/` min_order_size fallback test — Instrument(None) → ExchangeLimits(0.001) (INST-03)
- [ ] Update `tests/unit/core/test_money.py` (`:45,:50,:57`) to pass `Instrument` objects instead of `str` (INST-01)
- [ ] (Optional) `tests/unit/universe/test_universe.py` — `.members` equals `derive_membership(...)` exactly; `.instrument(sym)` round-trips
- No new framework install needed — pytest infrastructure covers all of this.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Storing the Decimal scale on `Instrument` (vs an int place-count) is the lower-risk byte-exact choice | §2, Pitfall 3 | If planner picks int, a place→scale conversion bug drifts the oracle — mitigated by an explicit equivalence test |
| A2 | No existing per-symbol declared-instrument config exists; the planner must introduce a declared source | §4 | If one exists undiscovered, the declared-config task is redundant — low risk, grep found none |
| A3 | INST-02 inference can read the raw CSV cell via `pd.read_csv(dtype=str)` on the price column | §5, Pitfall 1 | If the runner caches only the float frame, a second raw read is needed — confirmed feasible (csv path is on the store) |

All other claims are `[VERIFIED]` against file:line in this session.

## Open Questions (RESOLVED)

1. **`derive_instruments` declared-config home** — where declared params (BTCUSD 8dp, undeclared min_order_size, default mmr/leverage) physically live (a Python dict in `universe/`, a YAML in `settings/`, or constants). CONTEXT marks placement as Claude's Discretion.
   - What we know: no per-symbol config exists today; `ExchangeLimits` is venue-wide.
   - Recommendation: a small in-code declared table in `universe/instruments.py` for Phase 1 (one symbol), keeping byte-exact + strict-clean; YAML later if symbol count grows.
   - **RESOLVED:** in-code declared table in `itrader/universe/instruments.py` (plan 01-02 Task 1, Claude's Discretion).
2. **Fold `is_active`/spans into `Universe` now or defer** — CONTEXT: cheap-to-fold → fold, else defer.
   - Recommendation: defer the span-folding unless the planner needs `.is_active` for a Phase-1 consumer (none identified) — keeps scope to façade + instrument map (D-07 scope discipline).
   - **RESOLVED:** defer — no Phase-1 consumer identified (D-07 scope discipline).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | ✓ (assumed) | 3.13 (pinned) | — |
| Poetry / `.venv` | tests, mypy | ✓ (assumed) | — | — |
| Golden dataset CSV | oracle gate, inference | ✓ | `data/BTCUSD_1d_ohlcv_2018_2026.csv` present | — |
| Frozen golden artifacts | byte-exact gate | ✓ | `tests/golden/summary.json` (46189.87730727451 / 134) present | — |

No external services (PostgreSQL/OANDA/Binance) are needed — Phase 1 is the offline backtest path.

## Sources

### Primary (HIGH confidence — codebase, file:line)
- `itrader/core/money.py:31-76` — quantize signature, tables, kind→scale, ROUND_HALF_UP
- `itrader/core/bar.py:29-68` — frozen value-object template
- `itrader/universe/membership.py:44-167` — derive_membership / is_active / active_membership
- `itrader/universe/__init__.py` — barrel exports
- `itrader/config/exchange.py:98-108` — ExchangeLimits.min_order_size
- `itrader/execution_handler/exchanges/simulated.py:113-118,424,696` — _min_order_size read/use
- `itrader/trading_system/backtest_runner.py:46-81` — Trap-4 wiring order
- `itrader/trading_system/live_trading_system.py:259-263` — live wiring mirror (mypy-deferred)
- `itrader/trading_system/compose.py:80-100` — Engine dataclass fields
- `itrader/trading_system/backtest_trading_system.py:42-57,239-244` — symbol seeding
- `itrader/price_handler/store/csv_store.py:44-194` — CSV load + `.astype(float)` at :178
- `tests/unit/core/test_money.py:27-57` — the ONLY quantize() importer
- `tests/integration/test_backtest_oracle.py:128-229` — byte-exact gate
- `tests/integration/_oracle_harness.py` — oracle run paths
- `tests/golden/summary.json` — 46189.87730727451 / 134
- `tests/e2e/robust/test_determinism.py` — double-run determinism
- `pyproject.toml:78-120` — mypy --strict scope (core/universe in-scope; live deferred)
- grep over `itrader/` + `tests/` for `quantize(` and `_INSTRUMENT_SCALES` — blast-radius proof

### Secondary
- `.planning/phases/01-instrument-value-object/01-CONTEXT.md` — D-01..D-10
- `.planning/REQUIREMENTS.md` — INST-01/02/03
- `.planning/notes/margin-leverage-shorts-999.4.md` §4/§6 — Instrument design

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no external packages; all in-tree assets verified at file:line.
- Architecture: HIGH — wiring point, read-model pattern, Trap-4 order all read directly.
- Pitfalls: HIGH — D-02a blast radius and the `.astype(float)` inference trap both proven by source.
- Byte-exact method: HIGH — the gate test and golden values verified.

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable — internal codebase, no fast-moving external deps)
