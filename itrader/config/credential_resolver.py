"""The ``CredentialResolver`` seam + its ENV-backed implementation (11-04, D-02/D-12, MPORT-06).

**itrader ships the seam, the app owns the data.** The durable ``venue_accounts``
row holds a POINTER (``secret_ref``), never a secret (D-02, T-11-16): live exchange
keys in a column would land in every ``pg_dump``, read replica and backup snapshot.
This module is what turns that pointer into credential material — at connect time,
in memory, and never written back to any store.

A future Vault/AWS/GCP-backed resolver is ONE more class satisfying the
``CredentialResolver`` Protocol, registered from the web app's own repo with its own
dependency: ``itrader`` requires no change to accept it. That is why the Protocol is
``@runtime_checkable`` and why this module ships exactly ONE implementation —
``EnvCredentialResolver`` — and imports no cloud SDK, no secret-manager client and no
encryption library (the milestone-wide zero-new-dependency gate, P1-P12).

**Why this closes the D-12 caveat.** ``ConnectorProvider._memo`` is keyed on the
``(venue, account_id)`` PAIR, but the ``_plugins`` map behind it is venue-only and
``build(spec)`` receives one spec — so without a resolver two ``account_id``s build two
connectors reading IDENTICAL global ``OKX_API_*`` credentials. Per-account credential
isolation is only real once a per-account POINTER resolves to per-account material.

**The ``env:<PREFIX>`` scheme.** ``resolve("env:OKX_ACCT_A")`` collects every
environment variable named ``OKX_ACCT_A_<SUFFIX>`` and returns ``{suffix.lower():
SecretStr(value)}``. This is the concrete form of the per-account env scheme Phase 5's
D-07 deferred to this phase.

**Redaction is structural, not prose (T-11-17).** ``resolve`` returns
``Mapping[str, SecretStr]``, NOT ``Mapping[str, str]``. Plain ``str`` would lose masking
the moment material enters the mapping — any ``repr()`` of the dict, any exception
carrying it, any structlog ``**kwargs`` spread, any debugger frame would render live
keys. Every value this module returns is credential material BY DEFINITION; non-secret
connection knobs (``sandbox`` / ``region``) belong in the row's ``config_json``, not in
a credential prefix.

**Fail-loud, never fail-open (T-11-18).** An unknown scheme, a malformed reference and
— critically — a well-formed reference matching ZERO variables all raise
``CredentialResolutionError``. A zero-match must never degrade to an empty mapping and
must never fall through to the ambient process environment: that silent fallback is
precisely how account A's keys reach account B's connector. The ONE empty-mapping case
is an explicit ``None`` reference (the paper account, which has nothing to point at).

Import-inert (the GATE-01 / ``test_okx_inertness.py`` discipline): ``from __future__
import annotations`` + ``TYPE_CHECKING``-only concretion annotations, no SQL, no ccxt,
no cloud SDK. This module is DELIBERATELY NOT barrel-exported from
``itrader/config/__init__.py`` — importing it is by path only, mirroring
``okx_settings``.

Indentation: 4-SPACE (``config/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import SecretStr

from itrader.core.exceptions.credential import CredentialResolutionError

if TYPE_CHECKING:
    from collections.abc import Mapping

# The ONE scheme this implementation understands. Kept as a tuple so the fail-loud
# message can name the full supported set without restating it at each raise site.
_ENV_SCHEME = "env"
_SUPPORTED_SCHEMES = (f"{_ENV_SCHEME}:",)


@runtime_checkable
class CredentialResolver(Protocol):
    """Structural seam turning a ``secret_ref`` POINTER into credential material (D-02).

    ``@runtime_checkable`` (mirrors the ``LiveConnector`` / ``VenuePlugin`` /
    ``AlertSink`` seams) so a fake is swap-in for tests and a Vault/AWS/GCP-backed
    implementation — living in the web app's own repo, with its own dependency — is
    swap-in for production without any ``itrader`` change.

    Implementations MUST NOT persist, log or embed a resolved value anywhere. The
    mapping lives in memory for the lifetime of the connector and nowhere else.
    """

    def resolve(self, secret_ref: str | None) -> Mapping[str, SecretStr]:
        """Resolve a pointer to credential material, or raise; ``None`` -> ``{}``."""
        ...


class EnvCredentialResolver:
    """The ONE shipped resolver: the ``env:<PREFIX>`` scheme (D-02, zero new deps).

    ``resolve("env:OKX_ACCT_A")`` -> every ``OKX_ACCT_A_<SUFFIX>`` environment
    variable, keyed by ``suffix.lower()``, valued as ``SecretStr``. The output is
    feedable into a venue's credential model (e.g. ``OkxSettings``) without
    transformation.
    """

    def resolve(self, secret_ref: str | None) -> Mapping[str, SecretStr]:
        """Resolve ``secret_ref`` to credential material (see module docstring).

        Parameters
        ----------
        secret_ref :
            An ``env:<PREFIX>`` pointer, or ``None`` for an account that has no
            credentials at all (the paper case).

        Returns
        -------
        Mapping[str, SecretStr]
            The credential material, keyed by lowercased variable suffix. Empty
            ONLY for an explicit ``None`` reference.

        Raises
        ------
        CredentialResolutionError
            On an unknown scheme, a reference with no scheme, an empty prefix, or a
            well-formed reference matching zero variables (T-11-18 — never a silent
            empty mapping, never an ambient-environment fallback).
        """
        # The paper case (D-06: a paper account's secret_ref column is NULL). This is
        # the ONLY path that yields an empty mapping, and it is reached only via an
        # explicit None — never by a lookup that happened to find nothing.
        if secret_ref is None:
            return {}

        prefix = self._parse_env_prefix(secret_ref)
        # Delimiter-ANCHORED match: a bare startswith(prefix) would fold
        # OKX_ACCT_ABC_API_KEY into the OKX_ACCT_A mapping — a cross-account leak
        # from a naming coincidence.
        marker = f"{prefix}_"
        resolved = {
            name[len(marker):].lower(): SecretStr(value)
            for name, value in os.environ.items()
            if name.startswith(marker) and len(name) > len(marker)
        }

        if not resolved:
            # T-11-18. Naming the MARKER (a variable-name prefix) is safe; naming any
            # value never happens anywhere in this module.
            raise CredentialResolutionError(
                secret_ref,
                f"no environment variables named '{marker}*' are set — refusing to "
                "fall back to ambient process credentials",
            )
        return resolved

    @staticmethod
    def _parse_env_prefix(secret_ref: str) -> str:
        """Extract the ``<PREFIX>`` from an ``env:<PREFIX>`` reference, or raise.

        Rejects an unknown scheme, a reference carrying no scheme at all, and an
        EMPTY prefix — ``env:`` with a naive implementation matches every variable in
        the process and would hand the connector the whole environment as credentials.
        """
        scheme, separator, prefix = secret_ref.partition(":")
        if not separator:
            raise CredentialResolutionError(
                secret_ref,
                "reference carries no scheme; supported schemes: "
                f"{', '.join(_SUPPORTED_SCHEMES)}",
            )
        if scheme != _ENV_SCHEME:
            raise CredentialResolutionError(
                secret_ref,
                f"unsupported scheme '{scheme}'; supported schemes: "
                f"{', '.join(_SUPPORTED_SCHEMES)}",
            )
        if not prefix:
            raise CredentialResolutionError(
                secret_ref,
                "empty env prefix — refusing to collect the entire process "
                "environment as credentials",
            )
        return prefix
