"""
Credential-resolution exceptions (11-04, D-02, T-11-17/T-11-18).

``CredentialResolutionError`` is the ONE typed failure a ``CredentialResolver``
raises when a ``secret_ref`` pointer cannot be turned into credential material.

SECURITY — this exception is a redaction boundary. Its ``__init__`` accepts the
``secret_ref`` (a POINTER, safe to name) and, optionally, the NAMES of the
variables it looked for. It has NO parameter that could carry a credential VALUE,
so no call site can accidentally build a message that leaks one (T-11-17). That
is why it does not reuse ``ConfigurationError``'s ``config_value`` slot.
"""

from typing import Optional

from .base import ITraderError


class CredentialResolutionError(ITraderError):
    """A ``secret_ref`` could not be resolved to credential material (D-02).

    Raised on an unknown scheme, a malformed reference, and — critically — on a
    well-formed reference matching ZERO sources. That last case must NEVER
    degrade to an empty mapping or to the ambient process credentials: a silent
    fallback is how account A's keys reach account B's connector (T-11-18).

    Parameters
    ----------
    secret_ref: `str`
        The pointer that failed to resolve. A pointer, never a secret.
    reason: `str`
        Why it failed, in terms of schemes and variable NAMES only.
    """

    def __init__(self, secret_ref: str, reason: Optional[str] = None):
        self.secret_ref = secret_ref
        self.reason = reason
        message = f"Could not resolve credential reference '{secret_ref}'"
        if reason:
            message += f": {reason}"
        super().__init__(message)
