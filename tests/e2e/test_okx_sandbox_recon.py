"""Opt-in slow OKX-demo reconciliation suite SCAFFOLD (Phase 5 / 05-02, D-09, RECON-06).

This is the real order -> fill -> reconcile -> restart loop against the OKX **demo** host.
It is opt-in and network-gated: the whole module SKIPS unless demo credentials
(``OKX_API_KEY`` / ``OKX_API_SECRET`` / ``OKX_API_PASSPHRASE``) are present in the
environment (mirrors the Phase-2 ``tests/integration/test_okx_smoke.py`` guard). In CI and
credential-free checkouts it COLLECTS and SKIPS cleanly — no import errors, no network, no
session left open. The gating OFFLINE reconciliation suite (the shared ``FakeLiveConnector``
in ``tests/support``) is what runs credential-free; this file never gates it.

Real-money execution stays gated: the demo host only (``wspap.okx.com`` / REST
``x-simulated-trading``), routed off the connector's single ``sandbox`` flag — never a
production venue (T-05-04 mitigation).

The three test bodies below are SKELETONS. Each names a concrete reconciliation guarantee and
skips with a "not-yet-implemented" reason so a credential-holding developer never hits a false
failure before the feature lands. Later Phase-5 plans replace each ``_pending`` skip with the
real assertion as the feature (real FillEvent, ``VenueAccount`` reconcile, two-sided restart)
is built. All connector imports are LAZY (inside the test body) so a credential-free collection
never touches connector code.
"""

import os

import pytest

_OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
_HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)

# The folder-derived TYPE marker (``e2e``) is auto-applied by the root conftest; ``slow`` is
# added by hand here because this suite makes a real network round-trip against OKX demo — it
# must stay OUT of the default ``make test`` run and be selectable via ``-m slow``.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _HAS_OKX_CREDS,
        reason=(
            "OKX demo credentials absent — opt-in sandbox reconciliation suite skipped "
            "(D-09/RECON-06). Set OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (demo "
            "env) to enable."
        ),
    ),
]


def _pending(feature: str, plan: str) -> None:
    """Skip a scaffold body whose feature has not landed yet (avoids false creds failures)."""
    pytest.skip(f"scaffold: {feature} not yet implemented — lands in plan {plan}")


def test_demo_order_produces_real_fill_event() -> None:
    """(i) A small demo order flows to a real ``FillEvent`` from the live OKX-demo path.

    Later: lazily build the live OKX stack (sandbox connector + ``OkxExchange``), submit a
    tiny demo order, and observe a real ``FillEvent`` on the ``global_queue`` (RECON-01/02).
    """
    _pending("real demo order -> FillEvent", "05-03 (order/fill reconcile)")


def test_venue_account_reconciles_post_fill_within_tolerance() -> None:
    """(ii) ``VenueAccount`` balance/positions reconcile against OKX demo within tolerance.

    Later: after the demo fill, snapshot ``VenueAccount`` (REST + push) and assert the
    engine-computed balance/position diff is within the per-symbol drift tolerance under 1:1
    (LX-04), never a spurious halt (RECON-03/04).
    """
    _pending("VenueAccount post-fill reconciliation", "05-04 (VenueAccount reconcile)")


def test_restart_rehydrate_then_venue_reconcile_no_spurious_halt() -> None:
    """(iii) Restart rehydration + venue reconcile yields no spurious halt.

    Later: rehydrate the operational store (order mirror + portfolio state), run the two-sided
    restart reconcile against the OKX-demo REST snapshot, and assert in-band deltas adopt
    cleanly with NO halt-and-alert (RECON-05, RES-01).
    """
    _pending("two-sided restart reconciliation", "05-05 (restart rehydrate + venue reconcile)")
