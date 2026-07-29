"""SEAM-03/D-11 — the shared ``build_venue_spec`` builder + the for_exchange↔build_live_system identity.

After D-04 made ``compose_engine`` spec-free, the ONLY "spec" the live path still needs is
the venue-selection trio the live root reads (``execution_venue`` / ``data_provider`` /
``account_id``). SEAM-03/D-11 centralizes that into ONE typed ``VenueSpec`` + ONE shared
``build_venue_spec`` builder — the SOLE home of the ``{'okx':'okx','paper':'okx'}``
default-provider map — that BOTH ``for_exchange`` and ``build_live_system`` call.

The load-bearing SEAM-03 invariant this test guards: ``for_exchange('X')`` and a direct
``build_live_system(spec)`` produce IDENTICAL ``VenueSpec``s across the venue set, so the two
entry points CANNOT DRIFT. The assertion is on the SPEC the two paths build (via
``VenueSpec.__eq__``), NOT a live facade — CI-safe (no OKX credentials, no venue connect).

Modelling the two entry points faithfully (without standing up a facade):

* **for_exchange path** — for a venue ``V`` with no explicit overrides, ``for_exchange`` calls
  ``build_venue_spec(V, data_provider=None, account_id=None)`` → the default-map resolves the
  provider. That resolved ``VenueSpec`` is what it hands to ``build_live_system``.
* **build_live_system path** — it reads the incoming spec's fields and re-calls
  ``build_venue_spec(V, data_provider=spec.data_provider, account_id=spec.account_id)``. Because
  ``build_venue_spec`` is idempotent (re-resolving an already-resolved provider is stable), the
  spec it feeds the live root equals the one ``for_exchange`` built.

Package-less test dir (no ``__init__.py``) to avoid the full-suite package collision; the
folder-derived ``unit`` marker is auto-applied (nothing marked by hand). Indentation: 4-SPACE.
"""

import pytest

from itrader.trading_system.venue_spec import VenueSpec, build_venue_spec


# The venue set: the two mapped venues (okx, paper) + one "other" that falls through to 'okx'.
_VENUE_SET = ['okx', 'paper', 'binance']

# The default-provider map's expected resolution ('okx'->'okx', 'paper'->'okx', other->'okx').
_EXPECTED_PROVIDER = {'okx': 'okx', 'paper': 'okx', 'binance': 'okx'}


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_build_venue_spec_applies_default_provider_map(venue: str) -> None:
    """build_venue_spec resolves the default provider from the {okx,paper}->okx map (D-11)."""
    spec = build_venue_spec(venue)

    assert isinstance(spec, VenueSpec)
    assert spec.execution_venue == venue
    assert spec.data_provider == _EXPECTED_PROVIDER[venue]
    assert spec.account_id is None


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_build_venue_spec_honors_explicit_overrides(venue: str) -> None:
    """An explicit data_provider / account_id override wins over the default map (D-11)."""
    spec = build_venue_spec(venue, data_provider='replay', account_id='acct-7')

    assert spec.execution_venue == venue
    assert spec.data_provider == 'replay'  # explicit override, NOT the default map
    assert spec.account_id == 'acct-7'


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_for_exchange_and_build_live_system_produce_identical_specs(venue: str) -> None:
    """SEAM-03 identity: the two live entry points build EQUAL VenueSpecs (D-11).

    Models both paths through the shared builder with matching inputs and asserts equality
    via ``VenueSpec.__eq__`` — the invariant that the twice-written spec cannot drift.
    """
    # for_exchange path: no explicit overrides -> the default map resolves the provider.
    for_exchange_spec = build_venue_spec(
        venue, data_provider=None, account_id=None)

    # build_live_system path: consumes the incoming spec's already-resolved fields and
    # re-builds through the SAME builder (idempotent re-resolution).
    build_live_system_spec = build_venue_spec(
        venue,
        data_provider=getattr(for_exchange_spec, 'data_provider', None),
        account_id=getattr(for_exchange_spec, 'account_id', None),
    )

    assert for_exchange_spec == build_live_system_spec
    assert build_live_system_spec.data_provider == _EXPECTED_PROVIDER[venue]


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_the_account_level_connection_knobs_default_to_absent(venue: str) -> None:
    """11.2-06 (D-38): ``sandbox`` / ``region`` / ``market_type`` default to ``None``.

    ``None`` means "this account names no override" — the venue/bundle default stays in
    force. It is deliberately NOT ``False`` / ``"global"`` / ``"spot"``: a concrete
    default here would be a SECOND home for each venue's own default, and the two would
    drift. Absence must be distinguishable from an explicit value, because that is what
    lets ``VenueAccountManager`` merge an account's ``config_json`` without inventing
    overrides the operator never wrote.
    """
    spec = build_venue_spec(venue)

    assert spec.sandbox is None
    assert spec.region is None
    assert spec.market_type is None


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_the_account_level_connection_knobs_survive_the_builder(venue: str) -> None:
    """11.2-06 (D-38): the three allowlisted ``config_json`` keys reach the spec.

    They exist for ONE reason: to be read by a real consumer. ``sandbox`` / ``region``
    select the OKX host the session reaches (an EEA key answers 50119 on the global
    host), and ``market_type`` reaches ``VenueAccount``, where
    ``_cash_stream_nets_holds = market_type != "spot"`` changes CASH ACCOUNTING. A spec
    that dropped them would leave the account-level allowlist accepting keys that change
    nothing — worse than rejecting them (T-11.2-06-02).
    """
    spec = build_venue_spec(
        venue, sandbox=False, region='eea', market_type='derivative')

    assert spec.sandbox is False
    assert spec.region == 'eea'
    assert spec.market_type == 'derivative'


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_the_connection_knobs_survive_the_seam_03_round_trip(venue: str) -> None:
    """SEAM-03: a spec re-built from its own fields is still EQUAL (D-11).

    The identity invariant is what stops the twice-written spec from drifting. Adding
    fields to ``VenueSpec`` without threading them through ``build_venue_spec`` would
    break it silently — the round-trip would quietly drop the knobs and the two entry
    points would produce specs that route to two different hosts.
    """
    first = build_venue_spec(
        venue, account_id='acct-7', sandbox=True, region='eea',
        market_type='derivative')
    second = build_venue_spec(
        venue,
        data_provider=first.data_provider,
        account_id=first.account_id,
        sandbox=first.sandbox,
        region=first.region,
        market_type=first.market_type,
    )

    assert first == second


@pytest.mark.parametrize('venue', _VENUE_SET)
def test_identity_holds_under_explicit_provider_override(venue: str) -> None:
    """The identity also holds when for_exchange carries an explicit data_provider (D-11).

    A bespoke ``for_exchange(V, data_provider='replay')`` spec, once consumed by
    ``build_live_system``, is re-built identically (the explicit provider survives the
    round-trip unchanged).
    """
    for_exchange_spec = build_venue_spec(
        venue, data_provider='replay', account_id='acct-9')
    build_live_system_spec = build_venue_spec(
        venue,
        data_provider=getattr(for_exchange_spec, 'data_provider', None),
        account_id=getattr(for_exchange_spec, 'account_id', None),
    )

    assert for_exchange_spec == build_live_system_spec
    assert build_live_system_spec.data_provider == 'replay'
    assert build_live_system_spec.account_id == 'acct-9'
