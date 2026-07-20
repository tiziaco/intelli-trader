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
    ValidationError,
    StrategyAdmissionError,
    UnknownParamError,
    MissingParamError,
    StrategyValidationError,
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
from itrader.strategy_handler.registry import (
    StrategyConfigError,
    UnknownStrategyTypeError,
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


# --- StrategyAdmissionError: the shared strategy-payload refusal ancestor -------
#
# Motivating defect CR-01: before this base existed, "catch a bad strategy payload"
# meant hand-listing unrelated names across four sites. Those sets drifted, and one
# drifted tuple let a bare ValueError escape a never-raise boundary into a live HALT
# vector. These tests pin the hierarchy so the four sites can be written as one name.


_REPARENTED = [
    lambda: UnknownParamError(["a", "b"]),
    lambda: MissingParamError("x"),
    lambda: StrategyConfigError("bad blob"),
    lambda: UnknownStrategyTypeError("unknown type"),
    lambda: StrategyValidationError("short_window must be < long_window"),
]


@pytest.mark.parametrize("make", _REPARENTED)
def test_strategy_refusals_share_the_admission_ancestor(make):
    """All four rejection types are catchable through ONE ancestor.

    ``ValueError`` is asserted too: it is what preserves every pre-existing catch
    site across the reparent, and it is why the whole family could not simply be
    rooted at the house ``ValidationError``.
    """
    exc = make()
    assert isinstance(exc, StrategyAdmissionError)
    assert isinstance(exc, ITraderError)
    assert isinstance(exc, ValueError)


def test_unknown_param_error_keeps_its_structured_fields():
    err = UnknownParamError(["a", "b"])
    assert err.names == ["a", "b"]
    assert err.field == "strategy_params"
    assert isinstance(err, ValidationError)


def test_missing_param_error_keeps_its_structured_fields():
    err = MissingParamError("x")
    assert err.name == "x"
    assert err.field == "x"
    assert isinstance(err, ValidationError)


@pytest.mark.parametrize("cls", [StrategyConfigError, UnknownStrategyTypeError])
def test_registry_refusals_construct_from_a_plain_message(cls):
    """Plain-message construction is what makes the ~25 existing raise sites safe.

    ``StrategyConfigError`` is raised throughout the codec with a bare message
    string, so the shared base MUST NOT impose ``ValidationError``'s
    ``(field, value, message)`` signature.
    """
    assert str(cls("plain msg")) == "plain msg"


def test_strategy_validation_error_joins_the_admission_ancestor():
    """WR2-02 / IN2-02 — the typed home for the bare-``ValueError`` residue.

    Catchability through ``StrategyAdmissionError`` is the whole point: it is what
    puts a ``validate()`` refusal inside ``registry.rehydrate._QUARANTINABLE`` so a
    stale row is quarantined instead of aborting the boot. ``ValueError`` keeps
    every pre-existing catch site (and the ``pytest.raises(ValueError, ...)``
    assertions in ``tests/unit/strategy/test_strategy.py``) working unchanged.
    """
    exc = StrategyValidationError("short_window must be < long_window")
    assert isinstance(exc, StrategyAdmissionError)
    assert isinstance(exc, ITraderError)
    assert isinstance(exc, ValueError)


def test_strategy_validation_error_round_trips_the_plain_message():
    """The wrap carries only ``str(exc)``, so plain-message construction is required.

    It is NOT parented on the house ``ValidationError`` — that signature is
    ``(field, value, message)`` and there are no structured fields to supply here.
    """
    assert str(StrategyValidationError("plain msg")) == "plain msg"
    assert not issubclass(StrategyValidationError, ValidationError)


def test_unknown_param_error_mro_order_is_pinned():
    """``ValidationError`` must precede ``StrategyAdmissionError`` in the MRO.

    The order is load-bearing, not cosmetic: ``ValidationError.__init__`` has to win
    the attribute lookup, otherwise the structured-field constructor
    (``field=``/``message=``) breaks and ``.names``/``.field`` stop being populated.
    """
    mro = [cls.__name__ for cls in UnknownParamError.__mro__]
    assert mro[:5] == [
        "UnknownParamError",
        "ValidationError",
        "StrategyAdmissionError",
        "ITraderError",
        "ValueError",
    ]
