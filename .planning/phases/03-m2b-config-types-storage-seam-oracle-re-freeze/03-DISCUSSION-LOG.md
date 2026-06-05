# Phase 3: M2b — Config, Types, Storage Seam & Oracle Re-Freeze - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-05
**Phase:** 3-m2b-config-types-storage-seam-oracle-re-freeze
**Areas discussed:** Config collapse depth, time_parser anchor, Enum rationalization depth, pytest restructure scope, Portfolio storage seam, Oracle re-freeze

---

## Config collapse depth (M2-06)

### API surface
| Option | Description | Selected |
|--------|-------------|----------|
| Clean break | Delete registry/provider/validator + getters; rewire ~4 call sites to Pydantic models directly | ✓ |
| Thin compat shim | Keep getter names as thin wrappers, delete only internal machinery | |

### Secrets / settings layer
| Option | Description | Selected |
|--------|-------------|----------|
| Minimal settings stub | Settings(BaseSettings) with backtest-read fields; secrets required-no-default; no live wiring | ✓ |
| Full secrets layer | Complete PostgresDsn + all API keys + env-discriminated | |
| Just remove hardcoded creds | No BaseSettings; only delete the default credential | |

### Reference-data + presets placement
| Option | Description | Selected |
|--------|-------------|----------|
| constants.py + classmethod presets | Literals → core/constants.py; presets → Pydantic factory classmethods | ✓ |
| Keep literals in data model | Fold literals into DataConfig fields | |
| You decide | Planner picks | |

**User's choice:** Clean break + minimal settings stub + constants.py + classmethod presets.
**Notes:** Confirmed the in-scope config consumer surface is small (~4 call sites), making the clean break low-risk with mypy --strict as a safety net.

---

## time_parser anchor (M2-10)

Initial questions paused — user asked whether to keep UTC-everywhere + tz-for-display given a future
intent to **trade stocks**. Clarified that the UTC foundation holds for both crypto and stocks; stocks
add a session/exchange-calendar *layer* (intraday alignment to session open, holidays), not a change
to the foundation. Reframed accordingly.

### Anchor
| Option | Description | Selected |
|--------|-------------|----------|
| Epoch now, clean seam | Epoch-anchoring isolated in one replaceable function; defer stock session-alignment | ✓ |
| Pluggable anchor now | Anchor-strategy seam + exchange-calendar stub now | |
| Market-tz local | Modulo in market tz — would break the behavioral oracle | |

### Month unit
| Option | Description | Selected |
|--------|-------------|----------|
| Raise on 'M' | Reject month + unknown units; case-insensitive + 'w' support | ✓ |
| Support 'M' via calendar | relativedelta month handling now | |
| You decide | Planner picks | |

**User's choice:** Epoch now with clean replaceable seam + raise on 'M'.
**Notes:** Stock session/exchange-calendar alignment captured as a deferred idea; the single-function anchor is the future extension point.

---

## Enum rationalization depth (M2-07)

Initial questions paused — user asked whether rationalization (merging) would be "more correct" and
requested concrete examples. Provided Option-A (relocate + de-map) vs Option-B (merge to one
LifecycleStatus) code examples showing the merge loses REFUSED-vs-REJECTED and partial-fill semantics
and collides with M3/M4.

### Depth
| Option | Description | Selected |
|--------|-------------|----------|
| Relocate + de-map only | Centralize each enum + _missing_/from_string; keep the 3 vocabularies distinct | ✓ |
| Also rationalize the 3 | Merge OrderStatus/FillStatus/TransactionState | |

### Event-adjacent enum timing
| Option | Description | Selected |
|--------|-------------|----------|
| Move FillStatus, leave EventType | Relocate FillStatus now; leave EventType for M3 | ✓ |
| Move both now | Relocate both | |
| You decide | Planner picks | |

**User's choice:** Relocate + de-map only (keep 3 distinct) + move FillStatus, leave EventType for M3.
**Notes:** User accepted that merging is a domain-modeling regression after seeing the worked examples.

---

## pytest restructure scope (M2-12)

Updated framing: M1 already built the conftest + auto-marking skeleton the original finding said was
missing. Surfaced the concrete marking gap (component dirs lack unit/integration markers;
test_backtest_smoke.py mislabeled `unit`).

### Layout
| Option | Description | Selected |
|--------|-------------|----------|
| Full restructure to tests/{unit,integration} | Move + split by type, folder-derived markers | ✓ |
| In-place convert + extend marking | Keep test/ layout, extend DIR_MARKERS | |
| You decide | Planner picks | |

User leaned full restructure because integration tests are already scattered across by-domain
modules — confirmed by the tree (test_backtest_smoke mislabeled unit, test_event_wiring under events).

### Conversion completeness
| Option | Description | Selected |
|--------|-------------|----------|
| Convert all, file-by-file | Every unittest file → native pytest, one per commit, same count | ✓ |
| Move now, convert opportunistically | Restructure now, convert only where touched | |

### unit/integration boundary
| Option | Description | Selected |
|--------|-------------|----------|
| Yes — multi-component = integration | Unit = one component isolated; integration = cross-component (cross-domain OR cross-manager OR engine) | ✓ |
| Refine further | — | |

**User's choice:** Full restructure + convert all file-by-file + boundary = multi-component is integration.
**Notes:** User's rule "the moment a test exercises more than one collaborating module it's integration" sharpened to "collaborating *component*" (not file/class); covers cross-domain and cross-manager flows.

---

## Portfolio storage seam (M2-08/M2-09)

Initial questions paused — user proposed a per-subdomain subpackage reorg of portfolio_handler and
asked whether it's compatible with unified storage. Confirmed orthogonal + compatible; storage stays
a peer package.

### Granularity
| Option | Description | Selected |
|--------|-------------|----------|
| Unified PortfolioStateStorage | One interface, one in-memory backend per Portfolio | ✓ |
| Four interfaces | Transaction/Position/CashLedger/Metrics stores | |

### Reorg
| Option | Description | Selected |
|--------|-------------|----------|
| Yes — isolated pure-move commits | Subdomain packages (position/transaction/cash/metrics) + peer storage/ | ✓ |
| Keep flat this phase | Only add peer storage/ | |
| You decide | Planner picks | |

### Routing scope
| Option | Description | Selected |
|--------|-------------|----------|
| Full mirror of order pattern | All working + append-only state behind the seam | ✓ |
| Durable records only | Only audit/history collections behind the seam | |

**User's choice:** Unified storage + subdomain reorg (isolated pure-move commits) + full-mirror routing.
**Notes:** Entities already in own modules (position.py/transaction.py); reorg groups them with managers and rehomes the inline #15 dataclasses. ~13 import sites for transaction. Storage stays a peer package, NOT inside each manager folder.

---

## Oracle re-freeze (M2-13)

### Re-freeze target / end-state
| Option | Description | Selected |
|--------|-------------|----------|
| Byte-exact, tolerance removed | Regenerate golden; assert behavioral + numeric byte-exact; delete D-15 tolerance + DEF-02-08-A skip | ✓ |
| Keep a tiny epsilon | Retain a small numeric tolerance | |

### Inertness gate
| Option | Description | Selected |
|--------|-------------|----------|
| Strict inertness gate | Capture M2a-end reference; require M2b-end byte-exact match before re-freeze; any diff blocks pending owner explanation | ✓ |
| Behavioral-gate only | Require behavioral exact; re-freeze whatever numerics M2b produces | |

**User's choice:** Byte-exact re-freeze + strict inertness gate.
**Notes:** Framed M2b as numerically inert by design — re-freeze blesses the known M2a-end Decimal numbers; the time_parser epoch-anchor is the one change that could move firing, and the strict gate isolates it. Behavioral identity stays byte-exact and active throughout; a firing shift is a STOP, not a re-baseline.

---

## Claude's Discretion

- Exact Pydantic field/validator definitions and round-trip plumbing.
- `_missing_` vs `from_string` per enum + error messages.
- `PortfolioStateStorage` method signatures + in-memory internals.
- Layered-conftest fixture placement + naming; single marker registration home.
- Dead-module deletion (M2-11) — mechanical, verify zero importers first.
- Sequencing of structural moves, provided the oracle re-freeze is strictly LAST.

## Deferred Ideas

- Stock support: session/exchange-calendar alignment (intraday session-open anchoring, holidays) — the
  time_parser anchor is built as a replaceable seam for this.
- EventType relocation → M3 (#11). TransactionState rework + atomic transactions → M4 (#16).
  Cash-through-CashManager (#22) + DEF-01-A → M4. Postgres PortfolioStateStorage backend → D-sql.
  Reporting split/EngineLogger/universe/calculate_signal → M5b. Per-crypto precision registry (M2a).
