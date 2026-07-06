"""``Universe`` read-model facade (D-06/D-07).

``Universe`` is the injectable seam for symbol-scoped reads: the per-symbol
``Instrument`` resolution (consumed by the exchange now for ``min_order_size``,
and by the margin code in later phases) plus the membership list the feed binds.
It is a THIN facade COMPOSING the already-computed ``membership`` list and the
``derive_instruments`` map (D-07) — it does NOT recompute membership, and it does
NOT reimplement ``derive_membership`` / ``is_active`` (those pure fns stay in
``membership``).

Surface (D-06):

- ``.members -> list[str]`` returns the SAME set-derived list it was constructed
  with — byte-exact identity, so ``feed.bind`` stays byte-identical (Pitfall 4).
- ``.instrument(symbol) -> Instrument`` looks up the injected map; an unknown
  symbol raises ``KeyError`` (the universe resolves only its own members).

A concrete class (RESEARCH §8) — no Protocol is needed because the single
construction site (the runner) and the consumers (the exchange) share this one
type. The per-tick availability query (``is_active`` / spans, OQ2) is DEFERRED:
no Phase-1 consumer needs it, and D-07 scope discipline keeps the facade narrow.
"""

from dataclasses import dataclass

from itrader.core.instrument import Instrument
from itrader.universe.instruments import (
    _DEFAULT_MAINTENANCE_MARGIN_RATE,
    _DEFAULT_MAX_LEVERAGE,
    _DEFAULT_PRICE_SCALE,
    _DEFAULT_QUANTITY_SCALE,
)

__all__ = ["Universe", "UniverseDelta"]


@dataclass(frozen=True, slots=True)
class UniverseDelta:
    """The membership change produced by ``Universe.apply`` (D-03).

    A frozen, dependency-light internal return value (NOT a queue event — the
    ``UniverseUpdateEvent`` carries the same ``tuple[str, ...]`` fields). Mirrors
    LEAN's ``SecurityChanges.Added/Removed`` shape.
    """

    added: tuple[str, ...]
    removed: tuple[str, ...]

    def is_empty(self) -> bool:
        """True iff no symbols were added or removed (the oracle-dark case)."""
        return not self.added and not self.removed


class Universe:
    """Composed read-model over the membership list + ``Instrument`` map (D-06).

    Constructed once at wiring time from the already-derived ``membership`` and
    the ``derive_instruments`` map; injected into the exchange (and, later, the
    margin code). It delegates nothing at runtime — it is a pure lookup facade.
    """

    def __init__(self, *, members: list[str], instrument_map: dict[str, Instrument]) -> None:
        """Hold the constructed membership list + Instrument map by reference.

        Parameters
        ----------
        members : list[str]
            The set-derived membership list from ``derive_membership`` — held by
            identity (NOT copied) so ``.members`` is byte-exact (Pitfall 4).
        instrument_map : dict[str, Instrument]
            The symbol -> ``Instrument`` map from ``derive_instruments``.
        """
        self._members = members
        self._instruments = instrument_map
        # Remove-policy leaving-set (D-03): the plan-04 remove consumer marks a
        # symbol here on orphan-and-track removal; the plan-04 admission gate
        # reads it via ``leaving_symbols()`` to block NEW entries. Starts empty.
        self._leaving: set[str] = set()

    @property
    def members(self) -> list[str]:
        """Return the membership list (the SAME object the feed binds, Pitfall 4).

        IN-02: returned BY IDENTITY (not a defensive copy) because the byte-exact
        ``feed.bind`` consumer requires the same list object. The returned list is
        therefore READ-ONLY by contract — DO NOT mutate it; a mutation rewrites the
        universe's internal membership in place.
        """
        return self._members

    def instrument(self, symbol: str) -> Instrument:
        """Return the resolved ``Instrument`` for ``symbol``.

        Parameters
        ----------
        symbol : str
            A member symbol.

        Returns
        -------
        Instrument
            The resolved per-symbol metadata.

        Raises
        ------
        KeyError
            If ``symbol`` is not a member of this universe.
        """
        return self._instruments[symbol]

    def apply(
        self,
        desired: set[str],
        instruments: dict[str, Instrument] | None = None,
    ) -> UniverseDelta:
        """Reconcile membership to ``desired``, returning the applied delta (D-03).

        Diffs ``desired`` against current membership and, when they differ,
        mutates ``_members`` IN PLACE (slice-assign — the feed binds this list
        by identity, Pitfall 4; NEVER rebind ``self._members = ...``). Removed
        symbols are dropped from the ``Instrument`` map; added symbols resolve
        their ``Instrument`` from the passed ``instruments`` map when present,
        else fall back to the ``_DEFAULT_*`` ladder (paper) so a later
        ``.instrument(sym)`` never ``KeyError``s.

        ``Universe`` stays connector-free (D-03): the poll handler resolves
        precision from the venue markets map and passes it in; ``Universe`` does
        NO I/O and holds NO queue.

        Parameters
        ----------
        desired : set[str]
            The target membership set (poll-resolved by a later plan).
        instruments : dict[str, Instrument], optional
            Pre-resolved ``Instrument``s for added symbols (venue-correct
            precision). A symbol absent here falls back to the default ladder.

        Returns
        -------
        UniverseDelta
            The ``added``/``removed`` symbols. Empty (no mutation) when
            ``desired`` already equals current membership (oracle-dark fast path).
        """
        current = set(self._members)
        added = tuple(sorted(desired - current))
        removed = tuple(sorted(current - desired))
        if not added and not removed:
            # Oracle-dark fast path — no membership mutation, no instrument churn.
            return UniverseDelta(added=(), removed=())

        # Mutate the SAME list object in place (Pitfall 4 — feed holds it by
        # identity). Sorted to match ``derive_membership`` WR-05 ordering.
        self._members[:] = sorted((current - set(removed)) | set(added))

        for sym in removed:
            self._instruments.pop(sym, None)

        resolved = instruments or {}
        for sym in added:
            self._instruments[sym] = resolved.get(sym) or self._default_instrument(sym)

        return UniverseDelta(added=added, removed=removed)

    @staticmethod
    def _default_instrument(symbol: str) -> Instrument:
        """Build a default-ladder ``Instrument`` for an added symbol (paper fallback).

        Uses the ``instruments.py`` ``_DEFAULT_*`` ladder (2dp price / 8dp
        quantity) so a dynamically added symbol with no venue-resolved precision
        still resolves via ``.instrument(sym)`` instead of ``KeyError``ing.
        """
        return Instrument(
            symbol=symbol,
            price_precision=_DEFAULT_PRICE_SCALE,
            quantity_precision=_DEFAULT_QUANTITY_SCALE,
            maintenance_margin_rate=_DEFAULT_MAINTENANCE_MARGIN_RATE,
            max_leverage=_DEFAULT_MAX_LEVERAGE,
        )

    def mark_leaving(self, symbol: str) -> None:
        """Mark ``symbol`` as leaving (remove-policy orphan-and-track, plan 04)."""
        self._leaving.add(symbol)

    def leaving_symbols(self) -> set[str]:
        """Return a COPY of the leaving set (callers must not mutate internal state)."""
        return set(self._leaving)

    def clear_leaving(self, symbol: str) -> None:
        """Clear ``symbol`` from the leaving set (position reached flat, plan 04)."""
        self._leaving.discard(symbol)
