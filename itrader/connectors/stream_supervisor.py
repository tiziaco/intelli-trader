"""StreamSupervisor — the ONE shared bounded-retry reconnect ladder for live venue
streams (D-08 / CF-4 / VENUE-07).

This is the single tested home for the security-critical reconnect/halt state that
was hand-copied THREE times across the live stack — ``OkxDataProvider`` (the canonical
donor), ``OkxExchange`` (order arm), and ``VenueAccount`` (venue-cached account leaf).
Each of those arms now **HAS-A** ``StreamSupervisor`` and delegates its consume-loop
supervision to it; the three ``_run_stream_supervisor`` forks are gone.

The three donors are **NOT behaviorally identical** (RESEARCH §StreamSupervisor Donor
Diff) — pointing all three at one verbatim body would silently change behavior for two
of them. The shared class is therefore **parameterized** so it can re-cover each donor
EXACTLY:

- ``transient_exceptions`` — the provider needs the wider
  ``aiohttp.ClientError``/``ConnectionError``/``asyncio.TimeoutError`` set (6 types); the
  exec/account arms use the ccxt-only 3-type set. A union would flip
  ``okx.py``/``venue.py`` behavior (an ``aiohttp.ClientError`` would go
  transient→reconnect instead of unclassified→HALT). Each arm passes its exact tuple.
- ``fatal_exceptions`` — the auth/permission family that escalates to a HALT, never a
  retry.
- ``reconnect_on_clean_return`` — the provider treats a clean return of the consume body
  as a server-closed socket → reconnect (True); the exec/account forever-loops treat a
  clean return as an unexpected stop → return (False).

``mark_up`` / ``reset_budget`` are methods the CONSUME loop calls (not the supervisor
loop): the provider gates ``reset_budget`` on a post-snapshot payload (WR-03
``payload_seen``); ``okx.py`` gates on any payload; ``venue.py`` NEVER calls either — its
reduced surface is PRESERVED, not normalized (RESEARCH Open Q1 / A2). The supervisor
simply exposes them; whether an arm calls them is the arm's business.

Behavior preserved EXACTLY along every enumerated axis (D-08): transient/fatal/
unclassified classification, ``CancelledError`` re-raise, clean-return policy, retry
ceiling → HALT, debounce + capped exponential backoff, pause-on-sustained-drop
(``mark_down``), and the SCRUB discipline (T-05-27 / V7): every reconnect/halt log
carries ``type(exc).__name__`` + a fixed label, NEVER ``str(exc)`` (which may embed
request context / a secret); the halt reason is the fixed ``'connector-fatal'`` string.

Inertness (CONN-04 / the P5 acceptance gate): this module imports **NO ccxt** — the
exception families are constructor parameters, so the class is inert-by-construction and
never lands on ``test_okx_inertness.py::_FORBIDDEN``. The arms lazy-import their ccxt
tuples inside ``__init__`` when they build the supervisor.

Indentation: this file is 4-SPACE (matched to ``connectors/base.py`` beside it).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from itrader.config.stream import StreamSettings


class StreamSupervisor:
    """Bounded-retry reconnect supervisor around one venue-stream consume loop (D-08).

    Owns the reconnect ladder plus the ``_reconnect_attempts`` / ``_streams_down``
    state (quarantined here, off the three arms). Parameterized over the donor-diff
    axes (``transient_exceptions`` / ``fatal_exceptions`` /
    ``reconnect_on_clean_return``) so it reproduces each of the three donor arms
    exactly. Composition, not inheritance — matches the ``MatchingEngine`` /
    ``Portfolio``-manager ethos and dodges the tab/space transplant hazard (the
    security-critical ladder lives in this one 4-space file, never inside a tab file
    via MRO).
    """

    def __init__(
        self,
        config: "StreamSettings",
        *,
        transient_exceptions: tuple[type[BaseException], ...],
        fatal_exceptions: tuple[type[BaseException], ...],
        reconnect_on_clean_return: bool,
        halt_signal: Callable[[str], None] | None,
        on_down: Callable[[str], None] | None,
        on_up: Callable[[str], None] | None,
        logger: Any,
        label: str,
    ) -> None:
        """Bind the tuning + injected seams; open no socket, spawn no task.

        Parameters
        ----------
        config : StreamSettings
            The reconnect-supervisor tuning home (CFG-03 / D-08): debounce, backoff
            base/cap, and retry ceiling are read off it once here.
        transient_exceptions : tuple[type[BaseException], ...]
            The exception family a drop reconnects on (each arm's EXACT tuple — a
            union would change two arms' behavior).
        fatal_exceptions : tuple[type[BaseException], ...]
            The auth/permission family that escalates to a HALT (never retried).
        reconnect_on_clean_return : bool
            True (provider): a clean return of the consume body is a server-closed
            socket → reconnect. False (exec/account): a clean return is an unexpected
            stop → return.
        halt_signal : Callable[[str], None] | None
            The freeze-in-place halt entrypoint, called with the fixed reason
            ``'connector-fatal'`` on a fatal / exhausted-ceiling / unclassified error.
            None until the composition root injects it (an unwired supervisor still
            retries transients; escalation is a no-op).
        on_down : Callable[[str], None] | None
            Fired ONCE per sustained-disconnect transition (pause new submission).
        on_up : Callable[[str], None] | None
            Fired on the down→up transition in :meth:`mark_up` (resume). None for the
            venue leaf (it never resumes-up — reduced surface preserved).
        logger : Any
            The arm's bound logger (component-tagged). Every reconnect/halt log is
            scrubbed to ``type(exc).__name__`` + a fixed label.
        label : str
            The log prefix identifying the arm (e.g. ``"OKX"`` / ``"OKX venue"``).
        """
        self.logger = logger
        self._label = label
        self._transient_exceptions = transient_exceptions
        self._fatal_exceptions = fatal_exceptions
        self._reconnect_on_clean_return = reconnect_on_clean_return
        self._halt_signal = halt_signal
        self._on_down = on_down
        self._on_up = on_up

        # Reconnect-supervisor tuning (read once off the injected config, CFG-03/D-08).
        self._reconnect_debounce_s = config.reconnect_debounce_s
        self._reconnect_backoff_base_s = config.reconnect_backoff_base_s
        self._reconnect_backoff_cap_s = config.reconnect_backoff_cap_s
        self._reconnect_ceiling = config.reconnect_retry_ceiling

        # Quarantined reconnect state (was ×3 on the arms). Per-stream so N dynamic
        # channels never collide (Pitfall 2 / 06-02 D-05): one symbol's drop marks
        # only that symbol down, one symbol's payload resets only its budget.
        self._reconnect_attempts: dict[str, int] = {}
        self._streams_down: set[str] = set()

    async def run(
        self,
        connect_and_consume: Callable[[str], Awaitable[None]],
        stream_name: str,
    ) -> None:
        """Supervise one consume loop with bounded-retry reconnect (D-19/D-20).

        Runs ``connect_and_consume(stream_name)`` (one WS connect + read loop, or a
        forever ``while True: await watch_*()``). Classification ladder (order is
        load-bearing):

        - ``asyncio.CancelledError`` → re-raise (cooperative teardown; never swallow).
        - ``fatal_exceptions`` → escalate a HALT + return (never retried).
        - ``transient_exceptions`` → reconnect with a debounce + capped exponential
          backoff, staying running (publish-and-continue).
        - any OTHER ``Exception`` (unclassified) → fail-safe escalate a HALT + return.
          It NEVER falls through to the reconnect ladder — an unknown/malformed-frame
          error must HALT, not silently reconnect (T-05-03 / D-11 / V17-07).
        - a clean return → reconnect IFF ``reconnect_on_clean_return`` else return.

        The retry ceiling exhausted escalates the same HALT (never spins forever,
        D-20). Scrub (T-05-27): the reconnect log carries the drop LABEL
        (``type(exc).__name__`` or a fixed string), never ``str(exc)``.
        """
        while True:
            try:
                await connect_and_consume(stream_name)
            except asyncio.CancelledError:
                raise  # cooperative teardown — never swallow.
            except self._fatal_exceptions as exc:
                self._escalate_halt(
                    stream_name, exc, "fatal auth/permission error")
                return
            except self._transient_exceptions as exc:
                drop_exc: BaseException | None = exc
                drop_label = type(exc).__name__
            except Exception as exc:
                # D-11 (V17-07): an UNCLASSIFIED error is neither transient nor fatal.
                # Fail safe — escalate + RETURN; NEVER fall through to the ladder.
                self._escalate_halt(stream_name, exc, "unexpected error")
                return
            else:
                # A clean return of the consume body.
                if not self._reconnect_on_clean_return:
                    # A forever-loop returning cleanly is not expected — stop.
                    return
                # The venue closed the socket — reconnect like a transient drop.
                drop_exc = None
                drop_label = "socket closed by server"

            # Transient drop OR clean socket-close -> bounded-retry reconnect.
            attempt = self._reconnect_attempts.get(stream_name, 0) + 1
            self._reconnect_attempts[stream_name] = attempt
            if attempt > self._reconnect_ceiling:
                self._escalate_halt(
                    stream_name,
                    drop_exc if drop_exc is not None else RuntimeError(drop_label),
                    "reconnect retry ceiling exhausted")
                return
            # Debounce first: a blip that clears on the first retry never pauses.
            await asyncio.sleep(self._reconnect_debounce_s)
            if attempt > 1:
                # Still failing past the debounce window -> pause (D-19).
                self.mark_down(stream_name)
            backoff = min(
                self._reconnect_backoff_base_s * (2 ** (attempt - 1)),
                self._reconnect_backoff_cap_s)
            # Scrub (T-05-27): log the drop LABEL (exception type / fixed string),
            # never str(exc) — a connector error may carry request context / a secret.
            self.logger.warning(
                "%s %s stream dropped (%s) — reconnecting "
                "(attempt %d/%d, backoff %.1fs)",
                self._label, stream_name, drop_label, attempt,
                self._reconnect_ceiling, backoff)
            await asyncio.sleep(backoff)

    def _escalate_halt(
        self, stream_name: str, exc: BaseException, cause: str
    ) -> None:
        """Halt the engine on an unrecoverable stream failure (D-20).

        Scrub (T-05-27 / V7): the log carries the exception TYPE + a fixed cause
        string, never ``str(exc)``; the halt entrypoint is called with the fixed reason
        ``'connector-fatal'`` so no secret can reach the CRITICAL alert.
        """
        self.logger.error(
            "%s %s stream unrecoverable (%s: %s) — halting engine",
            self._label, stream_name, type(exc).__name__, cause)
        if self._halt_signal is not None:
            self._halt_signal("connector-fatal")

    def mark_down(self, stream_name: str) -> None:
        """Record a sustained disconnect and fire ``on_down`` once per transition (D-19)."""
        if stream_name in self._streams_down:
            return
        self._streams_down.add(stream_name)
        self.logger.warning(
            "%s %s stream disconnected — pausing new order submission",
            self._label, stream_name)
        if self._on_down is not None:
            self._on_down(stream_name)

    def mark_up(self, stream_name: str) -> None:
        """A successful subscribe: fire ``on_up`` on a down→up transition (D-19). Does NOT reset backoff.

        WR-03: a subscribe is NOT proof of health — it does NOT reset the reconnect
        retry budget (only a delivered payload does, via :meth:`reset_budget`). Resetting
        on a mere subscribe let a subscribe-then-close storm pin ``attempt`` at 1 forever
        and silently defeat the D-20 never-spin-forever HALT guarantee.
        """
        if stream_name in self._streams_down:
            self._streams_down.discard(stream_name)
            self.logger.info(
                "%s %s stream reconnected — resuming after REST reconcile",
                self._label, stream_name)
            if self._on_up is not None:
                self._on_up(stream_name)

    def reset_budget(self, stream_name: str) -> None:
        """WR-03: a delivered payload proves the connection — reset the retry budget.

        Neither a subscribe (:meth:`mark_up`) nor an on-subscribe snapshot resets
        ``_reconnect_attempts``; only a delivered payload does. This keeps the D-20
        ceiling able to trip under a subscribe-then-close storm while a genuine,
        payload-carrying reconnect still clears the accumulated attempts.
        """
        self._reconnect_attempts[stream_name] = 0

    def is_healthy(self) -> bool:
        """True iff no supervised stream is currently down (D-28 / WR-03).

        Read by the engine's compound resume gate on the ENGINE thread while the
        connector loop mutates ``_streams_down`` (a GIL-atomic emptiness read, no lock;
        any staleness self-heals via the re-fired resume Event).
        """
        return not self._streams_down

    def forget(self, stream_name: str) -> None:
        """Clear a stream's per-symbol reconnect state (unsubscribe teardown, 06-02 D-05).

        Discards the down-flag and the accumulated attempt count so a stale down-flag
        cannot permanently pin :meth:`is_healthy` False (wedging the resume gate) and a
        stale attempt count cannot trip the D-20 ceiling on a later re-subscribe. Runs on
        the connector loop (the single writer for the supervisor dicts). Idempotent.
        """
        self._streams_down.discard(stream_name)
        self._reconnect_attempts.pop(stream_name, None)
