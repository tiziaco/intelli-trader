# Load .env file contents
include .env
.EXPORT_ALL_VARIABLES:

# Define the default target commands
.PHONY: init-env clean test test-unit test-integration test-cov precommit

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
	poetry run pytest test/ -v

test-unit:
	@echo "🔬 Running unit tests..."
	poetry run pytest test/ -v -m "unit"

test-integration:
	@echo "🔗 Running integration tests..."
	poetry run pytest test/ -v -m "integration"

test-portfolio:
	@echo "📊 Running portfolio tests..."
	poetry run pytest test/test_portfolio/ -v

test-events:
	@echo "📡 Running events tests..."
	poetry run pytest test/test_events/ -v

test-orders:
	@echo "📝 Running order handler tests..."
	poetry run pytest test/test_order_handler/ -v

test-execution:
	@echo "⚡ Running execution handler tests..."
	poetry run pytest test/test_execution_handler/ -v

test-strategy:
	@echo "🎯 Running strategy tests..."
	poetry run pytest test/test_strategy/ -v

test-cov:
	@echo "📈 Running tests with coverage..."
	poetry run pytest test/ --cov=itrader --cov-report=html --cov-report=term-missing -v

test-watch:
	@echo "👀 Running tests in watch mode..."
	poetry run pytest-watch test/ -- -v

# test-report:
# 	@echo "📋 Generating test report..."
# 	poetry run pytest tests/ --html=reports/test_report.html --self-contained-html -v

precommit:
	pre-commit run --all-files --hook-stage manual

