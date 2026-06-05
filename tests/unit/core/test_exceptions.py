"""
Regression tests for the core exception hierarchy (M3-03, D-18/D-19).

Locks in:
* ``ITraderError`` as the single root of all domain exceptions.
* The deleted execution-exception module stays deleted (execution failure is
  data by design — FillEvent/ExecutionErrorCode).
* KB24 — portfolio exceptions construct with their real signatures and expose
  typed context attributes.
* The new order/data exception modules store constructor args as attributes.
"""

import importlib

import pytest

from itrader.core.exceptions import (
    ITraderError,
    ConfigurationError,
    PortfolioError,
    PortfolioNotFoundError,
    PortfolioConfigurationError,
    OrderError,
    UnsizedSignalError,
    DataError,
    MalformedDataError,
    MissingPriceDataError,
)
from itrader import idgen


# --- Hierarchy ---------------------------------------------------------------


def test_itrader_error_is_the_root():
    assert issubclass(ITraderError, Exception)
    assert ITraderError.__bases__ == (Exception,)


@pytest.mark.parametrize("domain_base", [PortfolioError, OrderError, DataError])
def test_domain_bases_subclass_itrader_error(domain_base):
    assert issubclass(domain_base, ITraderError)


def test_legacy_root_name_is_gone():
    import itrader.core.exceptions as exc_pkg
    assert not hasattr(exc_pkg, "ITradingSystemError")


# --- Execution-exception module deleted (D-18) --------------------------------


def test_execution_exception_module_is_deleted():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("itrader.core.exceptions.execution")


def test_concurrency_error_family_is_deleted():
    import itrader.core.exceptions as exc_pkg
    assert not hasattr(exc_pkg, "ConcurrencyError")
    assert not hasattr(exc_pkg, "PortfolioConcurrencyError")


# --- KB24 regression: real signatures ------------------------------------------


def test_portfolio_not_found_error_exposes_typed_context():
    portfolio_id = idgen.generate_portfolio_id()
    err = PortfolioNotFoundError(portfolio_id)
    assert err.portfolio_id == portfolio_id
    assert "Portfolio" in str(err)
    assert str(portfolio_id) in str(err)


def test_portfolio_configuration_error_constructs_with_real_signature():
    err = PortfolioConfigurationError("max_portfolios", 10, "limit reached")
    assert err.config_key == "max_portfolios"
    assert err.config_value == 10
    assert err.reason == "limit reached"
    assert "max_portfolios" in str(err)
    assert isinstance(err, ConfigurationError)


# --- New modules: args stored as attributes ------------------------------------


def test_unsized_signal_error_stores_ticker():
    err = UnsizedSignalError("BTCUSDT")
    assert err.ticker == "BTCUSDT"
    assert "BTCUSDT" in str(err)
    assert isinstance(err, OrderError)


def test_malformed_data_error_stores_source_and_details():
    err = MalformedDataError("golden.csv", "missing columns ['Open']")
    assert err.source == "golden.csv"
    assert err.details == "missing columns ['Open']"
    assert "golden.csv" in str(err)
    assert isinstance(err, DataError)


def test_missing_price_data_error_stores_source_and_reason():
    err = MissingPriceDataError("golden.csv", "empty frame after window slice")
    assert err.source == "golden.csv"
    assert err.reason == "empty frame after window slice"
    assert "golden.csv" in str(err)
    assert isinstance(err, DataError)
