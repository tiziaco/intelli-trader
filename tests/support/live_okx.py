"""Store-derived OKX-boot test helpers (11.2-07, ACCT-01/D-20/D-36).

Since 11.2-07 the live account set is STORE-DERIVED, so an OKX boot assembles a lifecycle
only when a durable ``venue_accounts`` row exists (the ``provisioned_okx`` fixture in
``tests/integration/conftest.py`` provides one on a Postgres spine). These plain helpers
read the resulting single-account runtime without depending on the deleted
``_primary_lifecycle`` accessor or on the provider living on the lifecycle.
"""

from __future__ import annotations

from typing import Any


def the_okx_lifecycle(system: Any) -> Any:
    """The single OKX ``VenueLifecycle`` the store-derived boot assembled.

    11.2-07 (D-36) deleted ``_primary_lifecycle``; a single-account boot has exactly one
    entry in the per-account map, so this reads it without depending on a "primary".
    """
    lifecycles = list(system._venue_lifecycles.values())
    assert len(lifecycles) == 1, (
        f"expected exactly one assembled OKX lifecycle, got {len(lifecycles)}")
    return lifecycles[0]


def the_feed_provider(system: Any) -> Any:
    """The ONE data provider the FeedConnectionBinder bound to the feed (11.2-07, D-36).

    Replaces the deleted ``_primary_lifecycle.provider`` read — the provider now lives on
    the binder / the feed, not on the lifecycle.
    """
    return system._feed_binder.feed_provider
