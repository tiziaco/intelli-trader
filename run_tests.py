#!/usr/bin/env python3
"""
Test runner script for the itrader trading system.
Provides convenient ways to run different test suites.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle the output."""
    print(f"\n🔄 {description}")
    print(f"Running: {' '.join(cmd)}")
    print("-" * 50)
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed with exit code {e.returncode}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test runner for itrader")
    parser.add_argument(
        "suite", 
        nargs="?", 
        default="all",
        choices=["all", "unit", "integration", "portfolio", "events", "orders", "execution", "strategy", "coverage", "watch"],
        help="Test suite to run"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--failfast", "-x", action="store_true", help="Stop on first failure")
    parser.add_argument("--markers", "-m", help="Run tests with specific markers")
    parser.add_argument("--pattern", "-k", help="Run tests matching pattern")
    
    args = parser.parse_args()
    
    # Base pytest command
    base_cmd = ["poetry", "run", "pytest", "test/"]
    
    # Add common options
    if args.verbose:
        base_cmd.append("-v")
    if args.failfast:
        base_cmd.append("-x")
    if args.markers:
        base_cmd.extend(["-m", args.markers])
    if args.pattern:
        base_cmd.extend(["-k", args.pattern])
    
    # Define test suites
    test_suites = {
        "all": {
            "cmd": base_cmd,
            "desc": "Running all tests"
        },
        "unit": {
            "cmd": base_cmd + ["-m", "unit"],
            "desc": "Running unit tests"
        },
        "integration": {
            "cmd": base_cmd + ["-m", "integration"],
            "desc": "Running integration tests"
        },
        "portfolio": {
            "cmd": base_cmd + ["test/test_portfolio/"],
            "desc": "Running portfolio tests"
        },
        "events": {
            "cmd": base_cmd + ["test/test_events/"],
            "desc": "Running events tests"
        },
        "orders": {
            "cmd": base_cmd + ["test/test_order_handler/"],
            "desc": "Running order handler tests"
        },
        "execution": {
            "cmd": base_cmd + ["test/test_execution_handler/"],
            "desc": "Running execution handler tests"
        },
        "strategy": {
            "cmd": base_cmd + ["test/test_strategy/"],
            "desc": "Running strategy tests"
        },
        "coverage": {
            "cmd": base_cmd + ["--cov=itrader", "--cov-report=html", "--cov-report=term-missing"],
            "desc": "Running tests with coverage"
        },
        "watch": {
            "cmd": ["poetry", "run", "pytest-watch", "test/", "--", "-v"],
            "desc": "Running tests in watch mode"
        }
    }
    
    # Run the selected test suite
    suite_config = test_suites.get(args.suite)
    if not suite_config:
        print(f"❌ Unknown test suite: {args.suite}")
        sys.exit(1)
    
    success = run_command(suite_config["cmd"], suite_config["desc"])
    
    if not success:
        sys.exit(1)
    
    print(f"\n🎉 Test suite '{args.suite}' completed successfully!")


if __name__ == "__main__":
    main()
