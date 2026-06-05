# Load .env file contents
include .env
.EXPORT_ALL_VARIABLES:

# Define the default target commands
.PHONY: init-env clean test test-unit test-integration test-cov backtest precommit typecheck

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
	poetry run pytest tests/ -v

test-unit:
	@echo "🔬 Running unit tests..."
	poetry run pytest tests/ -v -m "unit"

test-integration:
	@echo "🔗 Running integration tests..."
	poetry run pytest tests/ -v -m "integration"

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

test-watch:
	@echo "👀 Running tests in watch mode..."
	poetry run pytest-watch tests/ -- -v

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

precommit:
	pre-commit run --all-files --hook-stage manual

