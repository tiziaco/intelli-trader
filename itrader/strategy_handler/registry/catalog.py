"""The D-01 injected strategy-type catalog and its allowlist resolver.

**D-01 — the type-vs-instance split.** Strategy *types* are CODE: they are supplied to the
engine by the application through the injected catalog below, because the owner's
proprietary strategies live in a separate private repo imported as a git submodule by the
future FastAPI app — so ``itrader`` never imports a concrete strategy class. Strategy
*instances* are DATA: the store is their source of truth, and rehydrating one reduces to
``catalog x row x codec -> Strategy``.

**The catalog IS the access control.** ``strategy_type`` is an untrusted string: it arrives
from an externally-supplied ``STRATEGY_COMMAND`` payload or from a stored row that an older
code version wrote. ``resolve_strategy_class`` answers it with a plain dict lookup in the
injected allowlist and nothing else — the entire function body is a lookup and a raise. It
never consults the import system to find a class by name, and it never interprets any part
of the string as Python source text. Resolving a type by name "as a convenience" would
silently convert an operator API into remote code execution (T-10-18): the caller would no
longer choose WHICH classes are instantiable, only that SOME class is. Keeping the lookup
closed over an injected dict is what makes an off-list ``strategy_type`` unreachable rather
than merely unlikely.

**Explicitly NOT in scope.** Adding new TYPES to the catalog at RUNTIME (a UI/upload
feature) is a different axis and is deferred. The catalog is composed once, at wiring, by
the application; P10 only resolves against it. Runtime lifecycle verbs (``add`` /
``enable`` / ``reconfigure``) operate on INSTANCES, which are data — never on types.
"""

from typing import TYPE_CHECKING

from itrader.core.exceptions import StrategyAdmissionError

if TYPE_CHECKING:
	from itrader.strategy_handler.base import Strategy

__all__ = [
	"StrategyCatalog",
	"UnknownStrategyTypeError",
	"resolve_strategy_class",
]

# D-01: the injected allowlist. Keyed on the class name (the value stamped into
# ``config_json.strategy_type`` and stored in the ``strategy_registry.strategy_type``
# column). The application composes this dict; ``itrader`` only reads it.
StrategyCatalog = dict[str, type["Strategy"]]


class UnknownStrategyTypeError(StrategyAdmissionError):
	"""A ``strategy_type`` is absent from the injected catalog (D-01 loud reject).

	Never a silent skip at this layer: an unresolvable type means the row/command cannot
	be honoured at all, and swallowing it would make a strategy silently vanish from a
	rehydrate. The caller decides the consequence (Plan 05 quarantines a single bad row
	per D-19 rather than failing the whole rehydrate); this layer's job is to report
	loudly enough that the decision is informed.

	Still a ``ValueError`` through ``StrategyAdmissionError``, so every pre-existing
	catch site is unaffected by the reparent.
	"""


def resolve_strategy_class(
	catalog: StrategyCatalog, strategy_type: str
) -> type["Strategy"]:
	"""Resolve ``strategy_type`` to a class by allowlist lookup ONLY (D-01).

	The lookup below is the whole implementation, deliberately: see the module docstring
	for why a by-name import would be a privilege-escalation bug rather than a
	convenience.

	Raises
	------
	UnknownStrategyTypeError
		When ``strategy_type`` is not a key of ``catalog``. The message names the
		offending type and lists the known keys SORTED, so the message is deterministic
		(a dict-order-dependent message makes a failing test flaky and a log diff noisy).
	"""
	cls = catalog.get(strategy_type)
	if cls is None:
		raise UnknownStrategyTypeError(
			f"unknown strategy_type {strategy_type!r}; known types: "
			f"{sorted(catalog)}"
		)
	return cls
