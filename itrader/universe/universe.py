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

from itrader.core.enums import Readiness
from itrader.core.instrument import Instrument
from itrader.universe.instruments import (
    _DEFAULT_MAINTENANCE_MARGIN_RATE,
    _DEFAULT_MAX_LEVERAGE,
    _DEFAULT_PRICE_SCALE,
    _DEFAULT_QUANTITY_SCALE,
)

__all__ = ["TrackedInstrument", "Universe", "UniverseDelta"]


@dataclass(slots=True)
class TrackedInstrument:
    """One mutable membership record: instrument + readiness + leaving (D-02).

    The single source of truth for a universe entry, mirroring LEAN's mutable
    ``Security`` model. Replaces the desync-prone pair of a symbol-keyed
    ``Instrument`` map and a separate ``leaving`` set (the WR-01 bug class):
    a record's instrument, warmup ``readiness``, and ``leaving`` flag now move
    together, and ``Universe.discard_instrument`` tears all three down in ONE
    ``dict`` pop (D-13) so they can never drift.

    NOT frozen (readiness/leaving mutate in place) and NOT ``kw_only`` — a
    positional ``TrackedInstrument(instrument, ...)`` is the common construction.
    The wrapped ``instrument`` is held BY REFERENCE (D-02): the frozen
    ``Instrument`` is never copied or mutated — only ``readiness``/``leaving``
    change.

    Fields
    ------
    instrument:
        The frozen per-symbol ``Instrument`` (held by reference, D-02).
    readiness:
        Warmup ``Readiness`` (WR-02). Construction-time members default
        ``READY`` (oracle-inert); apply-added members default ``PENDING`` until
        their backfill marks them ``READY``/``FAILED``.
    leaving:
        Remove-policy orphan-and-track flag (D-15): the removed-but-held record
        stays alive until flat; the plan-04 admission gate reads it to block new
        entries. Orthogonal to ``readiness``.
    """

    instrument: Instrument
    readiness: Readiness = Readiness.PENDING
    leaving: bool = False


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
        """Hold the membership list by reference + build the record map (D-02).

        Every construction-time member becomes a ``TrackedInstrument`` record in
        the single ``_entries`` map, resolving its ``Instrument`` from
        ``instrument_map`` (falling back to the ``_DEFAULT_*`` paper ladder when a
        member is absent — e.g. an admission harness passing an empty map) and
        defaulting to ``Readiness.READY``. Construction-time READY is the
        oracle-inertness lever (RESEARCH Pitfall 2): backtest members already
        carry store data, so the WR-02 readiness gate is a no-op on the SMA_MACD
        oracle path. The old ``_instruments`` map + ``_leaving`` set are folded
        into this one record map so they can never desync (WR-01 bug class).

        Parameters
        ----------
        members : list[str]
            The set-derived membership list from ``derive_membership`` — held by
            identity (NOT copied) so ``.members`` is byte-exact (Pitfall 4).
        instrument_map : dict[str, Instrument]
            The symbol -> ``Instrument`` map from ``derive_instruments``. In
            production its key set matches ``members`` (asserted at wiring); a
            member missing here resolves to the default ladder.
        """
        self._members = members
        # Single record map (D-02): instrument + readiness + leaving per symbol.
        self._entries: dict[str, TrackedInstrument] = {
            sym: TrackedInstrument(
                instrument=instrument_map.get(sym) or self._default_instrument(sym),
                readiness=Readiness.READY,
            )
            for sym in members
        }

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
            A symbol with a live record (a current member, or a removed-but-held
            symbol kept until flat — WR-01 keep-until-flat).

        Returns
        -------
        Instrument
            The resolved per-symbol metadata.

        Raises
        ------
        KeyError
            If ``symbol`` has no record in this universe (never added, or fully
            ``discard_instrument``-ed).
        """
        return self._entries[symbol].instrument

    def is_ready(self, symbol: str) -> bool:
        """Return True iff ``symbol`` has a ``READY`` record (WR-02 readiness gate).

        Defensive by design: an absent symbol (never added or already discarded)
        is NOT ready — returns ``False`` rather than raising, so the strategy gate
        can query any symbol safely.
        """
        entry = self._entries.get(symbol)
        return entry is not None and entry.readiness is Readiness.READY

    def mark_ready(self, symbol: str) -> None:
        """Flip ``symbol``'s record to ``READY`` (warmup satisfied, WR-02)."""
        self._entries[symbol].readiness = Readiness.READY

    def mark_failed(self, symbol: str) -> None:
        """Flip ``symbol``'s record to ``FAILED`` (backfill errored, WR-02)."""
        self._entries[symbol].readiness = Readiness.FAILED

    def mark_pending(self, symbol: str) -> None:
        """Flip ``symbol``'s record back to ``PENDING`` (CR-02 warmup retry, WR-02).

        Mirrors ``mark_ready``/``mark_failed``. The poll handler calls this when a
        still-desired member whose warmup previously ``FAILED`` is re-warmed on the
        next poll: readiness returns to ``PENDING`` so the WR-02 gate keeps the
        symbol dark until the re-warm actually lands (``mark_ready`` on success, or
        ``mark_failed`` again on another failure).
        """
        self._entries[symbol].readiness = Readiness.PENDING

    def failed_symbols(self) -> set[str]:
        """Return the set of members whose warmup readiness is ``FAILED`` (CR-02).

        Mirrors ``leaving_symbols`` — derived fresh from the records each call, so
        callers cannot mutate internal state through the returned set. The poll
        handler reads this to re-drive warmup for still-desired FAILED members
        (the "kept in membership, retried next poll" contract).
        """
        return {
            sym
            for sym, entry in self._entries.items()
            if entry.readiness is Readiness.FAILED
        }

    def apply(
        self,
        desired: set[str],
        instruments: dict[str, Instrument] | None = None,
    ) -> UniverseDelta:
        """Reconcile membership to ``desired``, returning the applied delta (D-03).

        Diffs ``desired`` against current membership and, when they differ,
        mutates ``_members`` IN PLACE (slice-assign — the feed binds this list
        by identity, Pitfall 4; NEVER rebind ``self._members = ...``). Removed
        symbols are NO LONGER dropped from the record map (D-13, WR-01
        keep-until-flat): only the membership list shrinks — the record survives
        so mark-to-market / carry / liquidation of a still-held orphan never hit
        a ``KeyError``; teardown is deferred to ``discard_instrument`` on flat.
        Added symbols are clobber-guarded (D-14): a genuinely NEW symbol creates
        a ``PENDING`` record (resolving its ``Instrument`` from ``instruments``
        when present, else the ``_DEFAULT_*`` paper ladder); the re-add of a
        still-held (removed-but-kept) symbol only clears its ``leaving`` flag and
        KEEPS its existing readiness — no re-warmup.

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

        # D-13 / WR-01: removed symbols are intentionally NOT popped here — the
        # record survives (keep-until-flat); teardown is ``discard_instrument``.

        resolved = instruments or {}
        for sym in added:
            entry = self._entries.get(sym)
            if entry is None:
                # Genuinely new symbol -> fresh PENDING record (warmup pending).
                self._entries[sym] = TrackedInstrument(
                    instrument=resolved.get(sym) or self._default_instrument(sym),
                    readiness=Readiness.PENDING,
                )
            else:
                # D-14 re-add of a still-held (leaving) symbol: clear leaving,
                # KEEP existing readiness (no re-warmup, no instrument clobber).
                entry.leaving = False

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

    def discard_instrument(self, symbol: str) -> None:
        """Tear a symbol's record down entirely in ONE pop (D-13 atomic teardown).

        The single point where instrument + readiness + leaving all disappear
        together (WR-01: a desync is impossible when they share one record).
        Idempotent — discarding an absent symbol is a no-op. Called on flat once
        a removed-but-held orphan closes (detach-on-flat, plan 05 wiring).
        """
        self._entries.pop(symbol, None)

    def mark_leaving(self, symbol: str) -> None:
        """Mark ``symbol``'s record as leaving (orphan-and-track, D-15).

        Operates on the record's ``leaving`` flag — orthogonal to readiness. The
        plan-04 admission gate reads ``leaving_symbols()`` to block NEW entries;
        the record stays alive until flat (keep-until-flat, WR-01).
        """
        self._entries[symbol].leaving = True

    def leaving_symbols(self) -> set[str]:
        """Return the set of symbols whose record is currently leaving (D-15).

        Derived fresh from the records each call, so callers cannot mutate
        internal state through the returned set.
        """
        return {sym for sym, entry in self._entries.items() if entry.leaving}

    def clear_leaving(self, symbol: str) -> None:
        """Clear ``symbol``'s ``leaving`` flag (position reached flat, D-15)."""
        self._entries[symbol].leaving = False
