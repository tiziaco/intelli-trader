---
phase: 1
slug: config-centralization
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-09
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `01-RESEARCH.md` → `## Validation Architecture`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/config tests/unit/core -x` |
| **Full suite command** | `make test` (or `poetry run pytest tests` in a worktree) |
| **Estimated runtime** | ~8–15 seconds (unit); full suite longer |

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched domain (`tests/unit/config` and/or `tests/unit/core`).
- **After every plan wave:** Run the two frozen gates + full unit suite.
- **Before `/gsd-verify-work`:** Full suite green; both frozen gates green.
- **Max feedback latency:** ~15 seconds (unit) / gates seconds.

---

## The Two Frozen Gates (must stay green after EVERY plan — oracle-gated pass)

| Gate | Command | Pass criterion |
|------|---------|----------------|
| **Oracle (byte-exact)** | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | SMA_MACD result `134 / 46189.87730727451` unchanged |
| **Inertness** | `poetry run pytest tests/integration/test_okx_inertness.py -v` | Backtest import constructs no `SqlSettings`; sentinel green |

---

## Per-Task Verification Map (requirement → observable check)

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| CFG-01 | `runtime` eager + lazy `sql` present on `SystemConfig`; `order` NOT present | unit | `poetry run pytest tests/unit/config -k "system_config" -x` | ❌ W0 (add) | ⬜ pending |
| CFG-02 | Register-vs-build: `sql` is a `cached_property`, unbuilt at import (`"sql" not in cfg.__dict__`) | unit + integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` (+ new in-process assertion) | ⚠️ extend | ⬜ pending |
| CFG-03 | Constants folded → domain config; grep-clean | unit + shell | grep-clean block returns empty + `poetry run pytest tests/unit -x` | ❌ W0 (grep gate) | ⬜ pending |
| CFG-04 | `SystemConfig` `extra="forbid"`; orphaned YAML removed | unit | `poetry run pytest tests/unit/config -x` (assert forbid raises on extra) | ❌ W0 (add) | ⬜ pending |
| CFG-05 | `HaltReason` enum exists (4 members); `'baseline-residual'` free string retired | unit + grep | `poetry run pytest tests/unit/core -k halt_reason -x`; `grep -rn "'baseline-residual'" itrader/` empty except enum `.value` | ❌ W0 (add) | ⬜ pending |
| CFG-06 | D-03a dual-validator paragraph pasted into `CONVENTIONS.md` | manual/doc | grep the pasted paragraph present in `.planning/codebase/CONVENTIONS.md` | manual (doc) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Non-Inferable Observable Checks (encode literally in plan `<verify>` / `must_haves`)

- **Lazy-sql inertness (CFG-02):** `from itrader import config as c; assert "sql" not in c.__dict__`; `assert isinstance(inspect.getattr_static(SystemConfig, "sql"), cached_property)`; `assert "sql" not in SystemConfig.model_fields`.
- **Grep-clean (CFG-03):** all four grep commands (see RESEARCH.md §Grep-clean) return empty; `_OKX_INTERVALS` intentionally excluded (lookup table, not a tunable).
- **HaltReason retirement (CFG-05):** `grep -rn "'baseline-residual'\|\"baseline-residual\"" itrader/` returns empty **except** the enum `.value` line in `core/enums/system.py`; enum members == the four call-site reasons (no `DRIFT`, no `PAUSED_ON_DISCONNECT`).
- **extra policy (CFG-04):** `SystemConfig.from_dict({"bogus_key": 1})` raises `ValidationError`; `grep -rn "settings/domains" itrader/` stays empty (no new loader introduced).

---

## Wave 0 Requirements

- [ ] `tests/unit/config/test_system_config.py` — CFG-01/CFG-02/CFG-04 (runtime eager, sql lazy register-vs-build, extra=forbid)
- [ ] `tests/unit/config/test_stream_settings.py` (or extend existing) — folded values equal the retired constants
- [ ] `tests/unit/core/test_halt_reason.py` — CFG-05 (4 members, `.value` strings)
- [ ] Extend `tests/integration/test_okx_inertness.py` with the `"sql" not in _cfg.__dict__` assertion
- [ ] Grep-clean shell gate wired into a plan verification step (CFG-03)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-03a dual-validator paragraph present in CONVENTIONS.md | CFG-06 | Doc edit — no runtime surface | `grep -F "defense-in-depth" .planning/codebase/CONVENTIONS.md` returns the pasted paragraph |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
