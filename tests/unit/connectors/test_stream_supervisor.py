"""StreamSupervisor behavior-preservation matrix (D-08 / CF-4 / VENUE-07).

The shared ``StreamSupervisor`` (``itrader/connectors/stream_supervisor.py``) replaces
the THREE hand-copied ``_run_stream_supervisor`` forks. This suite proves — parameterized
over the three donor configs — that the parameterized class reproduces each donor's
behavior EXACTLY along every enumerated axis:

- ``okx_provider`` : 6-type transient, clean-return→reconnect, full mark_up/reset_budget;
- ``okx`` exchange : 3-type transient, clean-return→stop, payload-gated reset;
- ``venue`` account: 3-type transient, clean-return→stop, NO mark_up/reset_budget.

And the security-critical invariants that must hold for ALL three (D-08 / T-05-01/02/03):

- a transient×N drop reconnects N times and NEVER halts (bounded by the ceiling);
- a fatal (auth/permission) error calls halt_signal('connector-fatal') exactly once and
  returns — never retried;
- an UNCLASSIFIED error (neither transient nor fatal) HALTS and returns — it NEVER falls
  through to the reconnect ladder (T-05-03);
- the retry ceiling exhausted HALTS (never spins forever, D-20);
- the clean-return policy both ways (reconnect vs stop);
- SCRUB (T-05-27): a secret-bearing ``str(exc)`` NEVER appears in captured log output —
  only ``type(exc).__name__`` + the fixed label; the halt reason is fixed 'connector-fatal'.

Driven fully offline: scripted consume coroutines on per-test ``asyncio.run`` loops
(created + closed cleanly so nothing escapes into the strict ``filterwarnings=["error"]``
suite). No sockets, no ccxt clients. Run via ``poetry run pytest`` (NOT ``make test``,
which exports ITRADER_DISABLE_LOGS and empties caplog — the scrub assertion needs logs).
This directory is package-less (NO ``__init__.py`` — package-collision memory).
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable

import ccxt
import pytest

from itrader.config.stream import StreamSettings
from itrader.connectors.stream_supervisor import StreamSupervisor

_SECRET = "OKX_API_SECRET-supersecret-0xDEADBEEF"


# --- scripted consume double -------------------------------------------------


class _StopSupervisor(BaseException):
    """Control-flow sentinel breaking a reconnect-on-clean-return loop cleanly.

    Subclasses ``BaseException`` (like ``CancelledError``) so the supervisor's
    ``except Exception`` catch-all does NOT treat it as a real venue error and halt.
    """


class _ScriptedConsume:
    """A consume coroutine driven by a step script (one step per connection attempt).

    - ``"transient"`` -> raise ``ccxt.NetworkError`` (reconnect);
    - ``"fatal"``     -> raise ``ccxt.AuthenticationError`` carrying a secret;
    - ``"unclassified"`` -> raise ``ccxt.ExchangeError`` (neither transient nor fatal);
    - ``"ok"``        -> mark_up (if wired) then return cleanly;
    - ``"ok_stop"``   -> mark_up then raise ``_StopSupervisor`` (break a
      reconnect-on-clean-return supervisor after a clean iteration).
    """

    def __init__(
        self, steps: list[str], on_healthy: Callable[[str], None] | None = None
    ) -> None:
        self._steps = list(steps)
        self._i = 0
        self.calls = 0
        self._on_healthy = on_healthy

    async def __call__(self, stream_name: str) -> None:
        step = self._steps[self._i] if self._i < len(self._steps) else "transient"
        self._i += 1
        self.calls += 1
        if step == "transient":
            raise ccxt.NetworkError("transient socket blip")
        if step == "fatal":
            raise ccxt.AuthenticationError(f"auth rejected: {_SECRET}")
        if step == "unclassified":
            raise ccxt.ExchangeError(f"venue rejected: {_SECRET}")
        if self._on_healthy is not None:
            self._on_healthy(stream_name)
        if step == "ok_stop":
            raise _StopSupervisor()
        return


class _Recorder:
    """Records the values a supervisor callback is fired with."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, value: str) -> None:
        self.calls.append(value)


# --- donor config matrix -----------------------------------------------------

# The EXACT tuples each donor arm passes in (RESEARCH §StreamSupervisor Donor Diff).
_PROVIDER_TRANSIENT: tuple[type[BaseException], ...] = (
    ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection,
    ConnectionError, asyncio.TimeoutError)  # (+ aiohttp.ClientError on the real arm)
_CCXT_ONLY_TRANSIENT: tuple[type[BaseException], ...] = (
    ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection)
_FATAL: tuple[type[BaseException], ...] = (
    ccxt.AuthenticationError, ccxt.PermissionDenied)

# (id, transient tuple, reconnect_on_clean_return, label) — the three donors.
_DONORS = [
    ("okx_provider", _PROVIDER_TRANSIENT, True, "OKX"),
    ("okx_exchange", _CCXT_ONLY_TRANSIENT, False, "OKX"),
    ("venue_account", _CCXT_ONLY_TRANSIENT, False, "OKX venue"),
]
_DONOR_IDS = [d[0] for d in _DONORS]


def _fast_config() -> StreamSettings:
    """A StreamSettings with the debounce/backoff shrunk so the test runs instantly."""
    return StreamSettings(
        reconnect_debounce_s=0.0,
        reconnect_backoff_base_s=0.0,
        reconnect_backoff_cap_s=0.0,
        reconnect_retry_ceiling=3,
    )


def _supervisor(
    transient: tuple[type[BaseException], ...],
    reconnect_on_clean_return: bool,
    label: str,
    *,
    halt: Callable[[str], None] | None = None,
    on_down: Callable[[str], None] | None = None,
    on_up: Callable[[str], None] | None = None,
    logger: Any | None = None,
) -> StreamSupervisor:
    return StreamSupervisor(
        _fast_config(),
        transient_exceptions=transient,
        fatal_exceptions=_FATAL,
        reconnect_on_clean_return=reconnect_on_clean_return,
        halt_signal=halt,
        on_down=on_down,
        on_up=on_up,
        logger=logger if logger is not None else logging.getLogger("stream-sup-test"),
        label=label,
    )


# --- transient -> reconnect + survive (all three donors) ---------------------


@pytest.mark.parametrize("name,transient,clean_reconnect,label", _DONORS, ids=_DONOR_IDS)
def test_transient_reconnects_and_survives_never_halts(
    name: str, transient: tuple[type[BaseException], ...],
    clean_reconnect: bool, label: str,
) -> None:
    """A sustained transient drop reconnects, pauses past debounce, and NEVER halts."""
    halt, down, up = _Recorder(), _Recorder(), _Recorder()
    sup = _supervisor(transient, clean_reconnect, label,
                      halt=halt, on_down=down, on_up=up)

    # transient (attempt 1, blip), transient (attempt 2 -> pause), then 'ok' clean.
    consume = _ScriptedConsume(["transient", "transient", "ok"], on_healthy=sup.mark_up)
    if clean_reconnect:
        # provider: a clean return reconnects, so break the loop with a stop sentinel.
        consume = _ScriptedConsume(
            ["transient", "transient", "ok_stop"], on_healthy=sup.mark_up)
        with pytest.raises(_StopSupervisor):
            asyncio.run(sup.run(consume, "s"))
    else:
        asyncio.run(sup.run(consume, "s"))

    assert halt.calls == []            # never halted on a transient
    assert down.calls == ["s"]         # paused once past the debounce (attempt 2)
    assert up.calls == ["s"]           # resumed on the successful 'ok' subscribe
    assert sup.is_healthy()            # back up


# --- fatal -> single halt, never retried (all three donors) ------------------


@pytest.mark.parametrize("name,transient,clean_reconnect,label", _DONORS, ids=_DONOR_IDS)
def test_fatal_error_halts_once_and_returns(
    name: str, transient: tuple[type[BaseException], ...],
    clean_reconnect: bool, label: str,
) -> None:
    """A fatal auth error escalates halt_signal('connector-fatal') once — never retried."""
    halt = _Recorder()
    sup = _supervisor(transient, clean_reconnect, label, halt=halt)

    consume = _ScriptedConsume(["fatal"])
    asyncio.run(sup.run(consume, "s"))

    assert halt.calls == ["connector-fatal"]
    assert consume.calls == 1          # fatal is never retried


# --- unclassified -> fail-safe halt, NEVER the reconnect ladder (T-05-03) -----


@pytest.mark.parametrize("name,transient,clean_reconnect,label", _DONORS, ids=_DONOR_IDS)
def test_unclassified_error_halts_and_never_reconnects(
    name: str, transient: tuple[type[BaseException], ...],
    clean_reconnect: bool, label: str,
) -> None:
    """An UNCLASSIFIED error HALTS and returns — it must NOT fall through to reconnect."""
    halt = _Recorder()
    sup = _supervisor(transient, clean_reconnect, label, halt=halt)

    consume = _ScriptedConsume(["unclassified"])
    asyncio.run(sup.run(consume, "s"))

    assert halt.calls == ["connector-fatal"]
    assert consume.calls == 1          # unclassified never reconnects (T-05-03)
    assert "s" not in sup._reconnect_attempts  # never entered the ladder


# --- retry ceiling exhausted -> halt (D-20) ----------------------------------


@pytest.mark.parametrize("name,transient,clean_reconnect,label", _DONORS, ids=_DONOR_IDS)
def test_retry_ceiling_exhausted_halts(
    name: str, transient: tuple[type[BaseException], ...],
    clean_reconnect: bool, label: str,
) -> None:
    """Endless transient drops exhaust the ceiling (3) and halt — never spin forever."""
    halt = _Recorder()
    sup = _supervisor(transient, clean_reconnect, label, halt=halt)

    consume = _ScriptedConsume(["transient"] * 20)
    asyncio.run(sup.run(consume, "s"))

    assert halt.calls == ["connector-fatal"]
    # attempts 1..3 retried, attempt 4 > ceiling -> halt (bounded).
    assert consume.calls == 4


# --- clean-return policy both ways -------------------------------------------


def test_clean_return_stops_when_reconnect_on_clean_return_false() -> None:
    """reconnect_on_clean_return=False: a clean return of consume stops (no reconnect)."""
    halt = _Recorder()
    sup = _supervisor(_CCXT_ONLY_TRANSIENT, False, "OKX", halt=halt)

    consume = _ScriptedConsume(["ok"])
    asyncio.run(sup.run(consume, "s"))

    assert consume.calls == 1          # returned cleanly -> stopped, did not reconnect
    assert halt.calls == []


def test_clean_return_reconnects_when_reconnect_on_clean_return_true() -> None:
    """reconnect_on_clean_return=True: a clean return reconnects (server-closed socket)."""
    halt = _Recorder()
    sup = _supervisor(_PROVIDER_TRANSIENT, True, "OKX", halt=halt)

    # 'ok' clean returns reconnect; 'ok_stop' finally breaks the loop.
    consume = _ScriptedConsume(["ok", "ok", "ok_stop"])
    with pytest.raises(_StopSupervisor):
        asyncio.run(sup.run(consume, "s"))

    assert consume.calls == 3          # each clean return reconnected


# --- the wider provider transient set classifies where the ccxt-only set halts -


def test_transient_tuple_breadth_is_not_normalized() -> None:
    """A ConnectionError is transient for the provider tuple but UNCLASSIFIED (halt) for ccxt-only.

    Preserving each arm's EXACT tuple is load-bearing: a union would flip the exec/account
    arms (a ConnectionError would reconnect instead of halting).
    """
    # provider tuple: ConnectionError is transient -> reconnects (ceiling then halts).
    prov_halt = _Recorder()
    prov = _supervisor(_PROVIDER_TRANSIENT, True, "OKX", halt=prov_halt)

    async def _raise_conn(_name: str) -> None:
        raise ConnectionError("dropped")

    asyncio.run(prov.run(_raise_conn, "s"))
    assert prov_halt.calls == ["connector-fatal"]      # via ceiling, after reconnects
    assert prov._reconnect_attempts["s"] == prov._reconnect_ceiling + 1

    # ccxt-only tuple: ConnectionError is UNCLASSIFIED -> immediate halt, no reconnect.
    ccxt_halt = _Recorder()
    ccxt_sup = _supervisor(_CCXT_ONLY_TRANSIENT, False, "OKX", halt=ccxt_halt)
    ccxt_consume_calls = {"n": 0}

    async def _raise_conn2(_name: str) -> None:
        ccxt_consume_calls["n"] += 1
        raise ConnectionError("dropped")

    asyncio.run(ccxt_sup.run(_raise_conn2, "s"))
    assert ccxt_halt.calls == ["connector-fatal"]
    assert ccxt_consume_calls["n"] == 1                 # unclassified -> no reconnect
    assert "s" not in ccxt_sup._reconnect_attempts


# --- SCRUB: no secret-bearing str(exc) ever reaches the logs (T-05-27) --------


@pytest.mark.parametrize(
    "step", ["fatal", "unclassified"], ids=["fatal", "unclassified"])
def test_scrub_no_secret_in_logs(step: str, caplog: pytest.LogCaptureFixture) -> None:
    """No secret-bearing ``str(exc)`` payload appears in any captured log record."""
    halt = _Recorder()
    logger = logging.getLogger("stream-sup-scrub")
    logger.propagate = True
    sup = _supervisor(_CCXT_ONLY_TRANSIENT, False, "OKX", halt=halt, logger=logger)

    consume = _ScriptedConsume([step])
    with caplog.at_level(logging.DEBUG, logger="stream-sup-scrub"):
        asyncio.run(sup.run(consume, "fills"))

    assert halt.calls == ["connector-fatal"]
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in blob
    assert "supersecret" not in blob
    # Only the scrubbed exception TYPE + a fixed cause reach the log.
    assert "AuthenticationError" in blob or "ExchangeError" in blob


def test_scrub_reconnect_log_carries_type_not_str(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reconnect (non-halt) warning log carries the exception TYPE, never str(exc)."""
    logger = logging.getLogger("stream-sup-scrub2")
    logger.propagate = True
    sup = _supervisor(_CCXT_ONLY_TRANSIENT, False, "OKX", halt=_Recorder(), logger=logger)

    class _SecretNetworkError(ccxt.NetworkError):
        pass

    calls = {"n": 0}

    async def _consume(_name: str) -> None:
        calls["n"] += 1
        # Exhaust the ceiling so the loop terminates.
        raise _SecretNetworkError(f"boom {_SECRET}")

    with caplog.at_level(logging.DEBUG, logger="stream-sup-scrub2"):
        asyncio.run(sup.run(_consume, "candles"))

    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert _SECRET not in blob
    assert "_SecretNetworkError" in blob   # the drop label is the exception TYPE name


# --- reduced surface: venue never calls mark_up/reset_budget (preserved) ------


def test_reset_budget_and_forget_are_per_stream() -> None:
    """reset_budget zeroes only one stream; forget clears both dicts for one stream."""
    sup = _supervisor(_CCXT_ONLY_TRANSIENT, False, "OKX")
    sup._reconnect_attempts["a"] = 3
    sup._reconnect_attempts["b"] = 2
    sup._streams_down.update({"a", "b"})

    sup.reset_budget("a")
    assert sup._reconnect_attempts["a"] == 0
    assert sup._reconnect_attempts["b"] == 2   # untouched

    sup.forget("b")
    assert "b" not in sup._reconnect_attempts
    assert "b" not in sup._streams_down
    assert "a" in sup._streams_down            # only b forgotten
