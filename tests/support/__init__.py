"""Shared, tree-agnostic test-support package (Phase 5 / 05-02, D-09).

Importable helper package placed OUTSIDE the ``tests/unit/*`` package-less trees
(MEMORY: two same-named top-level test packages break full-suite collection). Everything
here is credential-free and teardown-safe so the offline reconciliation gate runs under
``filterwarnings=["error"]`` without any ``OKX_API_*`` secrets.

Public surface:

* ``FakeLiveConnector`` — the teardown-safe ``LiveConnector`` test double (promoted from
  the Phase-2 connectors conftest, extended with canned account/fill/order streams).
* ``build_fake_recon_client`` — build the fake ccxt.pro client wired with the canned
  ``watch_*`` push streams + ``fetch_*`` REST snapshots from the recon fixtures.
* ``make_fake_venue_connector`` — one-call factory: fixtures -> client -> connector.
* ``load_recon_payloads`` — load the synthetic ``okx_recon_payloads.json`` fixture.
"""

from .fake_venue_connector import (
    FakeLiveConnector,
    build_fake_recon_client,
    load_recon_payloads,
    make_fake_venue_connector,
)

__all__ = [
    "FakeLiveConnector",
    "build_fake_recon_client",
    "load_recon_payloads",
    "make_fake_venue_connector",
]
