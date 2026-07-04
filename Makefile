# Load .env file contents
include .env
.EXPORT_ALL_VARIABLES:

# Define the default target commands
.PHONY: init-env clean test test-unit test-integration test-e2e test-e2e-live test-live test-smoke test-cov backtest normalize-data precommit typecheck perf-w1 perf-w2 perf-baseline perf-w2-baseline perf-profile perf-view

# Initialize Poetry environment in the service directory
init-env:
	@if ! pyenv versions | grep -q "3.13"; then \
			echo "Python 3.13 not found in pyenv. Installing..."; \
			pyenv install 3.13; \
	else \
			echo "Python 3.13 is already installed"; \
	fi
	pyenv local 3.13
	poetry config virtualenvs.in-project true
	poetry install --no-root
	
# pre-commit install --hook-type pre-commit


clean:
	poetry env remove --all

# Test commands
test:
	@echo "🧪 Running all tests..."
	poetry run pytest tests/ -v -m "not live"

test-unit:
	@echo "🔬 Running unit tests..."
	poetry run pytest tests/ -v -m "unit"

test-integration:
	@echo "🔗 Running integration tests..."
	poetry run pytest tests/ -v -m "integration and not live"

test-e2e:
	@echo "🎬 Running e2e scenario tests..."
	poetry run pytest tests/ -v -m "e2e"

test-smoke:
	@echo "💨 Running smoke tests..."
	poetry run pytest tests/ -v -m "smoke"

# Fast opt-in LIVE-venue connectivity checks (-m live) anywhere under tests/.
# Loads .env (via include .env + .EXPORT_ALL_VARIABLES above), so local OKX_API_* demo
# creds are exported and the credential-gated authenticated test runs alongside the
# credential-free public reachability test. DISTINCT from test-e2e-live: this runs the
# fast `-m live` connectivity checks (tests/integration/test_okx_connectivity.py),
# while test-e2e-live runs only the slow OKX-demo recon e2e suite with `-m slow`.
test-live:
	@echo "📡 Running LIVE-venue connectivity checks (opt-in, real network round-trip)..."
	poetry run pytest tests/ -v -m live

# LIVE opt-in OKX-demo reconciliation suite (RECON-06 / 05-12 Task-3 human gate).
# Loads .env (via include .env above), so OKX_API_* demo creds are exported and the
# credential-skipif no longer trips. Runs ONLY the slow-marked live tests against the
# OKX DEMO venue — the suite asserts connector.sandbox is True before any order, so
# real-money routing is impossible (T-05-04). Requires OKX_API_KEY/SECRET/PASSPHRASE
# (demo) and OKX_SANDBOX=true (or unset — default is demo) in .env; test (iii) also
# needs Docker (testcontainers Postgres) and skips cleanly if Docker is absent.
#
# The DB-gate vars are UNSET for this run: tests (i)/(ii) build a full LiveTradingSystem
# which, when ITRADER_DATABASE_PASSWORD (or ITRADER_DATABASE_URL) is set, takes the
# Postgres operational-store arm and tries to connect to a real DB (localhost:5544 by
# default). Those two tests need only the venue round-trip, so we unset them to force the
# in-memory order/signal fallback. Test (iii) stands up its OWN testcontainers Postgres
# (explicit url=) and is unaffected. (The store gate reads the env at construction, so the
# vars must be unset BEFORE the process starts.)
test-e2e-live:
	@echo "🛰️  Running LIVE OKX-demo reconciliation suite (opt-in, real demo venue)..."
	@test -n "$(OKX_API_KEY)" || { echo "❌ OKX_API_KEY not set in .env — cannot run the live demo suite."; exit 1; }
	env -u ITRADER_DATABASE_PASSWORD -u ITRADER_DATABASE_URL poetry run pytest tests/e2e/test_okx_sandbox_recon.py -m slow -v

test-portfolio:
	@echo "📊 Running portfolio tests..."
	poetry run pytest tests/unit/portfolio/ -v

test-events:
	@echo "📡 Running events tests..."
	poetry run pytest tests/unit/events/ -v

test-orders:
	@echo "📝 Running order handler tests..."
	poetry run pytest tests/unit/order/ -v

test-execution:
	@echo "⚡ Running execution handler tests..."
	poetry run pytest tests/unit/execution/ -v

test-strategy:
	@echo "🎯 Running strategy tests..."
	poetry run pytest tests/unit/strategy/ -v

test-cov:
	@echo "📈 Running tests with coverage..."
	poetry run pytest tests/ --cov=itrader --cov-report=html --cov-report=term-missing -v
	open htmlcov/index.html

# Type-check the in-scope itrader package with mypy --strict (D-05/D-06).
# Errors are expected until the strict-clean pass (Plan 07) — this gate must merely run.
typecheck:
	@echo "🔍 Running mypy --strict..."
	poetry run mypy itrader

# test-report:
# 	@echo "📋 Generating test report..."
# 	poetry run pytest tests/ --html=reports/test_report.html --self-contained-html -v

# Generate the deterministic backtest oracle (output/{trades,equity}.csv + summary.json)
backtest:
	@echo "🚀 Running backtest oracle generator..."
	poetry run python scripts/run_backtest.py

# Normalize provider CSVs (data/raw/) into the golden schema (data/{TICKER}_1d_ohlcv.csv)
normalize-data:
	@echo "🧾 Normalizing provider data into the golden schema..."
	poetry run python scripts/normalize_data.py

precommit:
	pre-commit run --all-files --hook-stage manual

# Performance harness (v1.5). perf/ lives outside shipped itrader/. Targets inherit
# the include .env / .EXPORT_ALL_VARIABLES idiom above, so W1_START_DATE / W1_END_DATE
# env overrides flow through automatically (D-07: pinned default, env-overridable).

# Clean W1 benchmark + delta vs frozen baseline + soft regression guard (gate b).
# Default window pinned to the frozen 2-month slice (D-07); override with
#   make perf-w1 W1_START_DATE=… W1_END_DATE=…
# Carries NO scalene — the gated run is profiler-free (TOOL-02 structural split).
perf-w1:
	@echo "⏱️  W1 benchmark + regression guard (vs frozen baseline)..."
	poetry run python -m perf.runners.run_w1_benchmark --check

# W2 synthetic scaling sweep {1,10,50} symbols + gate (b) guard. The --check REQUIRES
# a >=10% wall-clock win at 50 symbols vs perf/results/W2-BASELINE.json (inverted sense
# vs W1's slowdown guard — this gate must SEE the win). --json for machine output.
perf-w2:
	@echo "📈 W2 scaling sweep {1,10,50} symbols + gate (b) win guard..."
	poetry run python -m perf.runners.run_w2_sweep --check

# RE-FREEZE the W1 baseline: clean run, write committed perf/results/W1-BASELINE.json
# (TOOL-04, consumed in plan 02). Run BEFORE any optimization.
perf-baseline:
	@echo "🧊 Freezing W1 baseline → perf/results/W1-BASELINE.json..."
	poetry run python -m perf.runners.run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json

# FREEZE the W2 baseline: clean sweep, write committed perf/results/W2-BASELINE.json
# (D-05, seeds Phase 5). The AFTER-run reference the --check guard then diffs against.
perf-w2-baseline:
	@echo "🧊 Freezing W2 baseline → perf/results/W2-BASELINE.json..."
	poetry run python -m perf.runners.run_w2_sweep --baseline-out perf/results/W2-BASELINE.json

# Scalene CPU profile (manual review). NEVER wraps the gated run.
# Writes the profile JSON only — viewing is a separate, deliberate `make perf-view`.
# The viewer (`scalene view`) serves the GUI assets itself and prints a localhost
# URL to open in the VS Code Simple Browser.
# Do NOT use `view --html`: the standalone file references jquery/bootstrap by
# relative path, so it only half-renders unless those assets sit next to it.
# `scalene run --html` does NOT parse in 2.3.0 (Pitfall 1). $(CURDIR) = repo root.
# Do NOT pass --profile-all (profiles Scalene's own thread) or --memory.
perf-profile:
	@echo "🔬 Scalene CPU profile — NOT the gated run..."
	poetry run python -m scalene run --cpu-only --program-path $(CURDIR) \
		-o perf/results/scalene-w1.json -m perf.runners.run_w1_benchmark
	@test -s perf/results/scalene-w1.json || { echo "scalene-w1.json missing/empty — profile run failed"; exit 1; }
	@echo "   → run 'make perf-view' to open the native viewer."

# Re-open the native viewer against an EXISTING profile JSON (no re-run).
perf-view:
	@test -s perf/results/scalene-w1.json || { echo "scalene-w1.json missing/empty — run 'make perf-profile' first"; exit 1; }
	@echo "🔬 Opening Scalene viewer for existing perf/results/scalene-w1.json..."
	@echo "   → paste the printed localhost URL into the VS Code browser..."
	poetry run python -m scalene view perf/results/scalene-w1.json

