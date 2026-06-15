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

from itrader.core.instrument import Instrument

__all__ = ["Universe"]


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

    @property
    def members(self) -> list[str]:
        """Return the membership list (the SAME object the feed binds, Pitfall 4)."""
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
