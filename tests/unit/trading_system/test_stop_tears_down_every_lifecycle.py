"""WR-08 regression gate — ``LiveTradingSystem.stop()`` must tear down EVERY venue lifecycle.

The defect: ``stop()`` snapshotted only the FIRST entry of ``_venue_lifecycles``
(``next(iter(lifecycles.values()), None)``) and stopped that one lifecycle, while
``start()`` loops over every entry. The shortcut was justified by
``ConnectorProvider.close_all()`` being shared across accounts — which is true for
only ONE of ``VenueLifecycle.stop()``'s two branches. Lifecycles built WITHOUT a
shared provider take the documented ``elif self._bundle.connector is not None:
self._bundle.connector.disconnect()`` fallback, which covers that ONE bundle — so
every non-primary connector leaked: a dangling authenticated venue socket in
production, and a ``ResourceWarning`` (a hard failure) under ``filterwarnings=["error"]``.

These tests drive the REAL ``LiveTradingSystem.stop()`` body re-bound onto a minimal
host (the in-repo pattern from ``test_live_runner_stats.py``) — no daemon thread, no
venue arm, no credentials, no network. The lifecycles and the SQL backend are
hand-written recorders, not call-count mocks, so the assertions can name WHICH
lifecycles were torn down.

4-space indentation (``tests/unit/*`` convention); NO ``__init__.py`` in this dir on
purpose (same-named-package collision hazard) — ``tests/conftest.py`` supplies the
``unit`` marker from the folder.
"""

from unittest.mock import MagicMock

import pytest

from itrader.trading_system.live_trading_system import LiveTradingSystem


class _RecordingLifecycle:
    """A ``VenueLifecycle`` double that records its own account id on ``stop()``."""

    def __init__(self, account_id: str, calls: list[str], *, raises: bool = False) -> None:
        self._account_id = account_id
        self._calls = calls
        self._raises = raises

    def stop(self) -> None:
        # Record FIRST, then raise — so an isolation test can prove the raising
        # lifecycle was actually reached rather than skipped.
        self._calls.append(self._account_id)
        if self._raises:
            raise RuntimeError(f'venue {self._account_id} teardown exploded')


class _RecordingBackend:
    """A SQL-spine backend double counting ``dispose()`` calls."""

    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


class _TeardownHost:
    """A light host carrying the REAL ``LiveTradingSystem.stop`` method.

    Re-binds the ACTUAL method onto a minimal object holding only what ``stop()``
    touches, so these tests exercise the real teardown logic rather than a paraphrase.
    """

    stop = LiveTradingSystem.stop

    def __init__(
        self,
        lifecycles: dict[str, _RecordingLifecycle],
        *,
        running: bool = False,
        live_runner=None,
        backend: _RecordingBackend | None = None,
    ) -> None:
        self._venue_lifecycles = lifecycles
        self._running = running
        self._live_runner = live_runner if live_runner is not None else MagicMock(name='live_runner')
        self._system_db_backend = backend
        self._safety = MagicMock(name='safety')
        self.logger = MagicMock(name='logger')


def _three_lifecycles(calls: list[str], *, raising: str | None = None) -> dict[str, _RecordingLifecycle]:
    """Three lifecycles keyed acct-a/acct-b/acct-c in deterministic insertion order."""
    return {
        account_id: _RecordingLifecycle(account_id, calls, raises=(account_id == raising))
        for account_id in ('acct-a', 'acct-b', 'acct-c')
    }


def test_stop_tears_down_every_lifecycle() -> None:
    """Every entry of _venue_lifecycles is stopped, in insertion order (WR-08)."""
    calls: list[str] = []
    # _running=False exercises the early "not running" return — the teardown lives in a
    # finally, so it must still fan out on that path.
    host = _TeardownHost(_three_lifecycles(calls), running=False)

    assert host.stop() is True

    assert calls == ['acct-a', 'acct-b', 'acct-c']


def test_a_raising_lifecycle_does_not_strand_the_others() -> None:
    """One venue exploding during teardown does not strand the remaining venues (WR-08)."""
    calls: list[str] = []
    backend = _RecordingBackend()
    host = _TeardownHost(
        _three_lifecycles(calls, raising='acct-b'), running=False, backend=backend)

    # The teardown failure is swallowed at the call site — stop() does not propagate it.
    assert host.stop() is True

    # Isolation is PER LIFECYCLE: acct-c is still torn down after acct-b raised.
    assert calls == ['acct-a', 'acct-b', 'acct-c']
    # The SQL-spine dispose that follows the teardown still ran, exactly once.
    assert backend.dispose_calls == 1
    # The failure was reported, naming the account whose teardown failed.
    assert host.logger.error.call_count == 1
    assert 'acct-b' in host.logger.error.call_args.args[0]


def test_teardown_runs_and_does_not_mask_a_raising_stop_body() -> None:
    """A teardown failure never masks an exception propagating out of the try body (WR-08)."""
    calls: list[str] = []
    backend = _RecordingBackend()
    live_runner = MagicMock(name='live_runner')
    live_runner.stop.side_effect = RuntimeError('boom')
    host = _TeardownHost(
        _three_lifecycles(calls, raising='acct-b'),
        running=True,
        live_runner=live_runner,
        backend=backend,
    )

    # The ORIGINAL exception must surface, unmasked by anything in the finally.
    with pytest.raises(RuntimeError, match='boom'):
        host.stop()

    assert calls == ['acct-a', 'acct-b', 'acct-c']
    assert backend.dispose_calls == 1


class _PartialHost:
    """A partially-constructed facade: no _venue_lifecycles, no _system_db_backend."""

    stop = LiveTradingSystem.stop

    def __init__(self) -> None:
        self._running = False
        self.logger = MagicMock(name='logger')


def test_partially_constructed_facade_stop_does_not_raise() -> None:
    """PRESERVATION guard — passes BOTH before and after the WR-08 fix.

    Its green result is NOT evidence that the fan-out defect is fixed; it exists only
    to lock the defensive ``getattr`` reads that must survive the fix, so ``stop()``
    still works on a facade whose construction never reached the venue/SQL wiring.
    """
    host = _PartialHost()

    assert host.stop() is True
