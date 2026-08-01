"""The venue catalogue — what each supported venue IS, as data rather than as code.

A plugin architecture with two plugins is a plugin architecture with one plugin and a
fallback. The facts the composition root actually needs about a venue — does it execute
orders, does its market data need authentication, which credential model does it
authenticate with, which data provider does it default to — are five values, not five
class hierarchies. So they are five values, and selecting a venue is a dict lookup.

Each descriptor answers exactly the questions a caller has to ask BEFORE anything is
built, which is what lets the decisions be made without importing a concretion:

  - ``credential_model`` — the settings model this venue's credentials are resolved into,
    or ``None`` for a venue that has none. A connector recipe uses it to derive the
    REQUIRED credential field set, so the completeness gate tracks the model
    automatically when a field is added.
  - ``capabilities`` — whether the venue can execute, serve public market data, serve
    private (authenticated) data. Independent facts: a broker may execute without serving
    candles, and a data vendor may serve candles without executing.
  - ``data_requires_auth`` — whether this venue's MARKET DATA needs an authenticated
    session. This is the venue's own declaration rather than something the data plane
    infers, and it is what decides whether a data adapter gets a public session or an
    authenticated one.
  - ``default_data_provider`` — the data venue used when a caller names an execution
    venue and nothing else. Paper executes in-process but has no market data of its own,
    so it defaults to the OKX live feed.

**Import-inertness is the constraint that shapes this module.** It is imported to make
decisions, including on paths that must pull nothing heavy, so it reaches
``pydantic-settings`` (via the credential models it names) and NOTHING else — no ccxt, no
SQLAlchemy, no connector, no exchange. Naming a credential model is safe precisely because
a settings CLASS is inert; constructing one is what reads the environment, and that
happens inside a recipe.

Indentation: 4-space.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic_settings import BaseSettings

from itrader.config.okx_settings import OkxSettings


class VenueCapability(Enum):
    """What a venue can be asked to do. Independent facts, not a hierarchy."""

    #: Accepts orders and reports fills.
    EXECUTION = "execution"
    #: Serves market data over an unauthenticated session.
    PUBLIC_DATA = "public_data"
    #: Serves market data that requires an authenticated session.
    PRIVATE_DATA = "private_data"


@dataclass(frozen=True, slots=True)
class VenueDescriptor:
    """The static facts about one supported venue.

    Frozen because a descriptor is a fact about a venue, not per-run state: two callers
    reading the catalogue must see the same answer, and nothing should be able to retune a
    venue's capabilities at runtime.
    """

    name: str
    credential_model: type[BaseSettings] | None
    capabilities: frozenset[VenueCapability]
    data_requires_auth: bool
    default_data_provider: str

    def supports(self, capability: VenueCapability) -> bool:
        """Whether this venue can be asked to do ``capability``."""
        return capability in self.capabilities


#: The supported venues. A dict, deliberately — adding a venue is adding an entry, and
#: "which venues exist" is a question answerable without constructing anything.
CATALOG: dict[str, VenueDescriptor] = {
    "okx": VenueDescriptor(
        name="okx",
        credential_model=OkxSettings,
        capabilities=frozenset({
            VenueCapability.EXECUTION,
            VenueCapability.PUBLIC_DATA,
            VenueCapability.PRIVATE_DATA,
        }),
        # OKX candles are public: the data arm needs no key, which is what allows a data
        # adapter to own a session that carries no credentials at all.
        data_requires_auth=False,
        default_data_provider="okx",
    ),
    "paper": VenueDescriptor(
        name="paper",
        # Paper executes in-process against a simulated exchange — there is no venue to
        # authenticate against, and a NULL secret_ref on a paper account is the supported
        # shape rather than a missing credential.
        credential_model=None,
        capabilities=frozenset({VenueCapability.EXECUTION}),
        data_requires_auth=False,
        # Paper has no market data of its own, so it streams the OKX live feed.
        default_data_provider="okx",
    ),
}


def descriptor_for(venue: str) -> VenueDescriptor:
    """The descriptor for ``venue``, or a ``KeyError`` naming what IS supported.

    A bare ``KeyError('bybit')`` from a dict subscript tells an operator nothing about
    what they could have typed, and "which venues exist" is the one question the
    catalogue is for.
    """
    try:
        return CATALOG[venue]
    except KeyError:
        raise KeyError(
            f"unsupported venue {venue!r} — the catalogue supports "
            f"{sorted(CATALOG)}") from None
