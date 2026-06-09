---
phase: 3
slug: minimal-real-universe
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `03-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (+ pytest-cov, pytest-watch) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error",...]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit/universe/test_membership.py tests/unit/price/test_bar_feed.py -x` |
| **Full suite command** | `make test` (oracle gate: `make test-integration`) |
| **Estimated runtime** | ~sub-second (quick) · ~tens of seconds (full + integration) |

Markers `unit` / `integration` (+`slow`) are folder-derived in `tests/conftest.py`, registered in `pyproject.toml`. **No new marker needed.**

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/universe/test_membership.py tests/unit/price/test_bar_feed.py -x`
- **After every plan wave:** Run `make test` (full unit + integration, incl. the oracle invariant)
- **Before `/gsd:verify-work`:** Full suite green AND `test_backtest_oracle.py` byte-identical
- **Max feedback latency:** ~30 seconds (full suite)

---

## Per-Task Verification Map

| Req | Behavior | Wave | Test Type | Automated Command | File Exists | Status |
|-----|----------|------|-----------|-------------------|-------------|--------|
| UNIV-01 | `is_active` / `active_membership` return correct sets over a span map (inclusive endpoints, mid-life gap still active, unknown ticker false) | 1 | unit | `poetry run pytest tests/unit/universe/test_membership.py -x` | ✅ (ADD cases) | ⬜ pending |
| UNIV-01 | Span cache built correctly at feed `__init__` from loaded frames | 1 | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k span -x` | ✅ (ADD cases) | ⬜ pending |
| UNIV-02 | `generate_bar_event` silent before listing / after end; warns only on mid-life gap (D-04) | 1 | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k "warn or gap or listing" -x` | ✅ (ADD cases) | ⬜ pending |
| UNIV-02 | Engine over union window w/ mid-run lister + differing end dates: no crash, no fill before listing, fills after | 2 | integration | `poetry run pytest tests/integration/test_universe_spans.py -x` | ❌ W0 (new file) | ⬜ pending |
| D-05 | Strategy-handler warning line removed; `if bar is None: continue` skip preserved | 1 | unit | `poetry run pytest tests/unit/strategy/ -k "sparse or skip" -x` | ⚠️ verify existing | ⬜ pending |
| Oracle-dark | Single-ticker BTCUSD golden run byte-identical (the invariant gate) | 2 | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ (exists) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Edge / Proof-Case Coverage (Nyquist — the three UNIV-02 proofs + the invariant)

| Proof case | Edge sampled | Assertion |
|------------|--------------|-----------|
| Mid-run listing | Tick exactly at listing date; tick one day before | `is_active` False before listing, True on listing day (inclusive); engine produces no fill for the lister before its first bar, ≥1 after |
| Differing end dates | Tick at a ticker's last bar; tick one day after | `is_active` True on last day (inclusive), False after; union grid still ticks; ended ticker absent from `bars`, no fill, no crash |
| Mid-life gap | Tick inside `[first,last]` with no bar at T | `is_active` True (still a member, D-01); `generate_bar_event` WARNS (D-04); no fill (sparse dict) |
| No-look-ahead | First fill timestamp for the lister | strictly `>= listing_date` — no fill leaks onto a pre-listing tick |
| Oracle-dark invariant | The full single-ticker golden run | byte-identical trade log / equity / summary vs `tests/golden/` |

---

## Wave 0 Requirements

- [ ] `tests/integration/test_universe_spans.py` — new tiny multi-ticker engine run (mid-run listing + differing end dates) covering UNIV-02. Depends on the `csv_paths` injection decision (Open Q2 / Pitfall 5).
- [ ] Synthetic fixtures: 2-3 tiny daily CSVs via the existing `write_kline_csv` helper (late-listing lister; early-ending ticker; gapped ticker). Reuse `tests/unit/price/test_bar_feed.py:54-72` — no new fixture format.
- [ ] Confirm no existing strategy-handler test asserts the deleted `'No last close for %s'` warning (D-05) — grep `tests/unit/strategy/`; adjust if present.
- [ ] (Possible enabling task) optional `csv_paths` param on `TradingSystem.__init__` (oracle-dark passthrough to `CsvPriceStore`).

*Framework already present — no install needed. New files are additive.*

---

## Manual-Only Verifications

All phase behaviors have automated verification. (Oracle-darkness is asserted by `test_backtest_oracle.py`.)

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`test_universe_spans.py`, synthetic fixtures)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
