---
phase: 2
slug: okx-connector
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-01
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `02-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio 1.4.0 (Wave 0 adds) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/connectors tests/unit/execution/test_okx_exchange.py -x` |
| **Full suite command** | `make test` (worktrees: `poetry run pytest tests` — `make test` aborts on missing `.env`) |
| **Estimated runtime** | ~ full suite baseline + a few s (offline mocked-ccxt, no network) |

**Strict-suite note (VERIFIED):** repo `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`. pytest-asyncio's `PytestDeprecationWarning` is already ignored, but `--strict-config` turns config warnings into errors and `ResourceWarning`/`RuntimeWarning` are NOT ignored. Wave 0 must set both asyncio config keys AND all async tests must close sessions / cancel stream tasks in teardown.

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/connectors tests/unit/execution/test_okx_exchange.py -x`
- **After every plan wave:** Run `poetry run pytest tests` (full suite green)
- **Before `/gsd:verify-work`:** Full suite green + backtest oracle byte-exact (`134 / 46189.87730727451`) + no W1/W2 regression (connector inert on hot path)
- **Max feedback latency:** < 30 seconds for the quick run

---

## Per-Task Verification Map

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| CONN-01 | Native business socket gates on `confirm=="1"`; forming bars dropped | unit (mocked ws + recorded fixture) | `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -x` | ❌ W0 |
| CONN-01 | REST `fetch_ohlcv` backfill returns Decimal-edge bars | unit (mocked ccxt) | `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -k backfill -x` | ❌ W0 |
| CONN-02 | `create_order`/cancel round via `amount_to_precision`; raw fill → `FillEvent` on queue | unit (mocked ccxt) | `poetry run pytest tests/unit/execution/test_okx_exchange.py -x` | ❌ W0 |
| CONN-03 | `sandbox=True` selects `wspap` host for native socket + `set_sandbox_mode` called | unit | `poetry run pytest tests/unit/connectors/test_okx_connector.py -k sandbox -x` | ❌ W0 |
| CONN-04 | Connector loop on daemon thread; coroutine-bridge; no domain import in connector | unit | `poetry run pytest tests/unit/connectors/test_okx_connector.py -k loop -x` | ❌ W0 |
| CONN-05 | Every ccxt float crosses `to_money`; no `Decimal(float)` in adapters | unit + grep guard | `poetry run pytest tests/unit/connectors -k decimal -x` | ❌ W0 |
| CONN-06 | `OkxSettings` reads plain `OKX_API_*`; `SecretStr`; secrets absent from logs/repr | unit | `poetry run pytest tests/unit/config/test_okx_settings.py -x` | ❌ W0 |
| (gate) | Backtest oracle byte-exact; connector inert on hot path | integration | `tests/integration/test_backtest_oracle.py` | ✅ |
| D-09 | Opt-in live smoke (connect demo, subscribe candle, tiny create/cancel) | integration, skipif no creds | `poetry run pytest tests/integration/test_okx_smoke.py -x` | ❌ W0 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `poetry add --group dev pytest-asyncio@^1.4.0` + add `asyncio_mode = "auto"` and `asyncio_default_fixture_loop_scope = "function"` to `pyproject.toml`
- [ ] `tests/unit/connectors/` dir — **keep package-less** (no `__init__.py`; avoids the top-level package collision, per MEMORY)
- [ ] `tests/unit/connectors/conftest.py` — shared async mocked-ccxt fixtures (`AsyncMock` over `watch_ohlcv`/`watch_my_trades`/`watch_orders`/`create_order`/`cancel_order`; sessions closed in teardown)
- [ ] Recorded OKX-demo business-channel candle payload fixture (with `confirm`) + full order→ack→fill payload fixture (captured once via D-09, sanitized, committed)
- [ ] `tests/integration/test_okx_smoke.py` — `pytest.mark.skipif(no creds)` opt-in live smoke

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live OKX demo connect + subscribe + tiny create/cancel round-trip | CONN-02/03/04 | Requires real demo creds + network; auto-skips in CI (D-09) | With `OKX_API_*` in `.env`: `poetry run pytest tests/integration/test_okx_smoke.py -x` |
| Real `confirm="0"` intermediate push cadence for `1D` bars | CONN-01 | OKX-side timing; pinned by recorded fixture, not asserted live | Capture once via D-09; `confirm=="1"` gate is correct regardless of cadence |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

*`wave_0_complete` stays false until Wave 0 lands during execution.*

**Approval:** approved 2026-07-01 (validation strategy verified by gsd-plan-checker against the finalized plans)
