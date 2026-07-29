"""The venue catalogue: the facts it states, and the imports it must not pull.

Two kinds of assertion here. The first is that each descriptor says what the design says
it says — cheap, but these values decide which credentials a session authenticates with
and whether a data adapter gets a public session, so a silent edit is expensive. The
second is the inertness probe: the catalogue exists to be consulted BEFORE anything is
built, including on paths that must pull no ccxt and no SQL, so "importing it is cheap" is
a property worth asserting rather than assuming.

This directory is package-less (NO ``__init__.py``); the ``unit`` marker is folder-derived.
Indentation: 4-space.
"""

import subprocess
import sys

import pytest

from itrader.config.okx_settings import OkxSettings
from itrader.venues.catalog import (
    CATALOG,
    VenueCapability,
    VenueDescriptor,
    descriptor_for,
)


def test_okx_declares_execution_and_both_data_capabilities() -> None:
    """OKX executes, and serves both public and private data."""
    okx = CATALOG["okx"]
    assert okx.capabilities == frozenset({
        VenueCapability.EXECUTION,
        VenueCapability.PUBLIC_DATA,
        VenueCapability.PRIVATE_DATA,
    })
    assert okx.supports(VenueCapability.EXECUTION)


def test_okx_market_data_needs_no_authentication() -> None:
    """OKX candles are public.

    This single boolean is what routes a data adapter onto a credential-free session
    instead of borrowing an execution account's authenticated one. Flipping it to ``True``
    would silently reintroduce the borrow.
    """
    assert CATALOG["okx"].data_requires_auth is False


def test_okx_names_its_credential_model_so_the_required_set_is_derivable() -> None:
    """The descriptor names the model, so a recipe derives the required fields from it.

    Asserted as the MODEL rather than a field list: the point of naming the class is that
    the completeness gate tracks it automatically when a credential field is added.
    """
    assert CATALOG["okx"].credential_model is OkxSettings
    required = {
        name for name, field in OkxSettings.model_fields.items() if field.is_required()
    }
    assert required == {"api_key", "api_secret", "api_passphrase"}


def test_paper_executes_only_and_has_no_credential_model() -> None:
    """Paper executes in-process: nothing to authenticate against, no data of its own.

    ``credential_model is None`` is what makes a NULL ``secret_ref`` on a paper account
    the SUPPORTED shape rather than a missing credential.
    """
    paper = CATALOG["paper"]
    assert paper.capabilities == frozenset({VenueCapability.EXECUTION})
    assert paper.credential_model is None
    assert not paper.supports(VenueCapability.PUBLIC_DATA)


def test_paper_defaults_its_data_to_the_okx_live_feed() -> None:
    """Paper has no market data, so it streams OKX — the production paper pairing."""
    assert CATALOG["paper"].default_data_provider == "okx"


def test_every_descriptor_is_self_consistent() -> None:
    """Structural invariants, over the whole catalogue rather than the two known entries.

    Written as a sweep so a venue added later is covered without editing this test: the
    dict key must equal the descriptor's own name (they are read interchangeably), and a
    venue that declares no data capability at all cannot sensibly require data auth.
    """
    for key, descriptor in CATALOG.items():
        assert isinstance(descriptor, VenueDescriptor)
        assert descriptor.name == key, "catalogue key and descriptor name must agree"
        assert descriptor.default_data_provider in CATALOG, (
            f"{key} defaults to data provider {descriptor.default_data_provider!r}, "
            "which is not a catalogued venue")
        serves_data = descriptor.capabilities & {
            VenueCapability.PUBLIC_DATA, VenueCapability.PRIVATE_DATA}
        if not serves_data:
            assert not descriptor.data_requires_auth, (
                f"{key} serves no data but declares data_requires_auth")


def test_a_descriptor_is_frozen() -> None:
    """Descriptors are facts, not per-run state — nothing retunes a venue at runtime."""
    with pytest.raises(Exception):
        CATALOG["okx"].data_requires_auth = True  # type: ignore[misc]


def test_an_unsupported_venue_names_what_is_supported() -> None:
    """A bare KeyError('bybit') tells an operator nothing they can act on."""
    with pytest.raises(KeyError) as excinfo:
        descriptor_for("bybit")
    message = str(excinfo.value)
    assert "bybit" in message
    assert "okx" in message and "paper" in message


_INERTNESS_PROBE = r"""
import sys

import itrader.venues.catalog  # noqa: F401

_FORBIDDEN_ROOTS = ("ccxt", "sqlalchemy", "psycopg2", "alembic")
leaked = sorted({name.split(".")[0] for name in sys.modules} & set(_FORBIDDEN_ROOTS))
assert not leaked, (
    "the venue catalogue must be import-inert; it pulled " + repr(leaked)
)
assert "itrader.connectors.okx" not in sys.modules, (
    "the catalogue pulled the OKX connector concretion — naming a credential model must "
    "not drag a session implementation onto the graph"
)
print("CATALOG_INERT_OK")
"""


def test_importing_the_catalogue_pulls_no_ccxt_and_no_sql() -> None:
    """The catalogue is consulted before anything is built, so importing it must be cheap.

    A subprocess, not an in-process ``sys.modules`` check: this pytest session has already
    imported ccxt and SQLAlchemy via other suites, so an in-process assertion would
    observe another test's import and pass vacuously.
    """
    result = subprocess.run(
        [sys.executable, "-c", _INERTNESS_PROBE],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, (
        f"catalog inertness probe failed:\nstdout={result.stdout}\n"
        f"stderr={result.stderr}")
    assert "CATALOG_INERT_OK" in result.stdout
