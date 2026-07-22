"""Live-only venue-selection spec + its single shared builder (SEAM-03, D-11).

After D-04 made ``compose_engine`` SPEC-FREE, the ONLY "spec" the live path still
needs is the venue-selection trio that ``assemble_venue`` reads:
``execution_venue`` / ``data_provider`` / ``account_id``. This module promotes that
duck-typed ``SimpleNamespace`` into a small typed value object.

Locked decision for this module:

* **D-11 — a small live-only ``VenueSpec`` for ``assemble_venue``, NOT a compose
  spec.** A frozen ``VenueSpec`` carrying exactly ``execution_venue`` /
  ``data_provider`` / ``account_id`` (3 fields, genuinely venue-scoped, not
  backtest-shaped) feeds ``assemble_venue`` ONLY — it NEVER crosses into
  ``compose_engine`` (compose is spec-free since D-04). ONE shared builder
  (``build_venue_spec``) produces it and is the SOLE home of the
  ``{'okx':'okx','paper':'okx'}`` default-provider map; BOTH ``for_exchange`` and
  ``build_live_system`` call it, killing the twice-written ``SimpleNamespace`` +
  default-map. A typed dataclass (frozen ``__eq__``) is preferred over the
  duck-typed ``SimpleNamespace`` — mypy-friendly, self-documenting, and the free
  equality lets the SEAM-03 unit test prove ``for_exchange`` and
  ``build_live_system`` produce IDENTICAL specs.

Import-inert by construction: this module is PURE (strings + a dataclass) — it
imports NO venue substrate / ccxt / SQL, so it never touches the backtest import
graph and stays ``mypy --strict`` clean.

Indentation: TABS (``trading_system/`` package convention; mirrors the sibling
``system_spec.py``).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VenueSpec:
	"""The live venue-selection trio ``assemble_venue`` reads (D-11).

	Exactly the three fields ``assemble_venue`` consumes off ``spec`` —
	``execution_venue`` (selects the ``ExecutionVenueRegistry`` plugin),
	``data_provider`` (selects the ``DataProviderRegistry`` plugin), and
	``account_id`` (keys the ``ConnectorProvider`` memo). Frozen so equality is
	free — two specs built from the same inputs compare equal, which is the
	load-bearing SEAM-03 invariant (``for_exchange`` == ``build_live_system``).

	It feeds ``assemble_venue`` ONLY — never ``compose_engine`` (spec-free since
	D-04).
	"""

	execution_venue: str
	data_provider: str
	account_id: Optional[str] = None
	# 11-04 (D-02/MPORT-06): a POINTER at wherever this ACCOUNT's credentials live
	# (``env:<PREFIX>`` today), read off the durable ``venue_accounts`` row. NEVER a
	# credential itself. The connector plugin resolves it through the injected
	# ``CredentialResolver`` inside ``build``, which is what makes two ``account_id``s
	# connect with DIFFERENT keys instead of the one global ``OKX_API_*`` set (the
	# D-12 caveat). ``None`` = the pre-MPORT-06 single-account deployment.
	secret_ref: Optional[str] = None


def build_venue_spec(
	execution_venue: str,
	*,
	data_provider: Optional[str] = None,
	account_id: Optional[str] = None,
	secret_ref: Optional[str] = None,
) -> VenueSpec:
	"""Build the live ``VenueSpec``, applying the default-provider map (D-11).

	The SOLE home of the ``{'okx':'okx','paper':'okx'}`` default-provider map: when
	``data_provider`` is not given, it is derived from ``execution_venue`` (``okx``
	for the okx venue, the OKX live feed for paper (D-21), else ``okx``). An explicit
	``data_provider`` override is honored verbatim. BOTH ``for_exchange`` and
	``build_live_system`` call this builder so the map + spec construction exist in
	exactly ONE location.

	Parameters
	----------
	execution_venue :
		The venue-name string selecting the execution plugin.
	data_provider :
		An explicit data-provider override; when ``None`` the default-provider map
		is applied over ``execution_venue``.
	account_id :
		The connector-memo key; ``None`` defers to the plugins' ``"default"``
		fallback (``assemble_venue`` does NOT re-default it).
	secret_ref :
		The account's credential POINTER off its ``venue_accounts`` row (D-02).
		``None`` = no per-account credentials (paper, or a pre-MPORT-06 deployment).
	"""
	resolved_provider = data_provider or {
		'okx': 'okx', 'paper': 'okx'}.get(execution_venue, 'okx')
	return VenueSpec(
		execution_venue=execution_venue,
		data_provider=resolved_provider,
		account_id=account_id,
		secret_ref=secret_ref,
	)
