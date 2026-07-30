"""``LiveTradingSystem.stop()`` must retire EVERY online venue account, one at a time.

Two properties, and neither is free:

  - **Fan-out.** ``stop()`` once snapshotted only the FIRST entry of its venue map and
    tore that one down, on the premise that a shared ``close_all()`` covered the rest.
    Every other account's connector then leaked: a dangling authenticated venue socket in
    production, and a ``ResourceWarning`` (a hard failure) under
    ``filterwarnings=["error"]``.
  - **Isolation.** Each retire is guarded on its own, so one venue exploding cannot strand
    the remaining accounts' sockets, the run-scoped pool teardown or the SQL dispose — and
    cannot mask an exception already propagating out of the try body.

These tests drive the REAL ``LiveTradingSystem.stop()`` body re-bound onto a minimal host
(the in-repo pattern from ``test_live_runner_stats.py``) — no daemon thread, no venue arm,
no credentials, no network. The manager, the pool and the SQL backend are hand-written
recorders, not call-count mocks, so the assertions can name WHICH accounts were retired.

4-space indentation (``tests/unit/*`` convention); NO ``__init__.py`` in this dir on
purpose (same-named-package collision hazard) — ``tests/conftest.py`` supplies the
``unit`` marker from the folder.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from itrader.trading_system.live.system import LiveTradingSystem


class _RecordingManager:
    """A venue-account manager double recording each ``bring_offline`` it is asked for."""

    def __init__(self, account_ids: list[str], calls: list[str],
                 *, raising: str | None = None) -> None:
        self._records = [
            SimpleNamespace(spec=SimpleNamespace(venue_name="okx", account_id=account_id))
            for account_id in account_ids
        ]
        self._calls = calls
        self._raising = raising

    def online_records(self) -> list:
        return list(self._records)

    def bring_offline(self, venue_name: str, account_id: str) -> None:
        # Record FIRST, then raise — so an isolation test can prove the raising account
        # was actually reached rather than skipped.
        self._calls.append(account_id)
        if account_id == self._raising:
            raise RuntimeError(f"venue {account_id} teardown exploded")


class _RecordingPool:
    """A session pool double counting the ONE run-scoped ``close_all()``."""

    def __init__(self) -> None:
        self.close_all_calls = 0

    def close_all(self) -> None:
        self.close_all_calls += 1


class _RecordingBackend:
    """A SQL-spine backend double counting ``dispose()`` calls."""

    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


class _TeardownHost:
    """A light host carrying the REAL ``LiveTradingSystem.stop`` method.

    Re-binds the ACTUAL method onto a minimal object holding only what ``stop()`` touches,
    so these tests exercise the real teardown logic rather than a paraphrase.
    """

    stop = LiveTradingSystem.stop

    def __init__(
        self,
        manager: _RecordingManager,
        *,
        running: bool = False,
        live_runner=None,
        pool: _RecordingPool | None = None,
        backend: _RecordingBackend | None = None,
    ) -> None:
        self._venue_manager = manager
        self._connector_pool = pool
        self._running = running
        self._live_runner = (
            live_runner if live_runner is not None else MagicMock(name="live_runner"))
        self._system_db_backend = backend
        self._safety = MagicMock(name="safety")
        self.logger = MagicMock(name="logger")


def _three_accounts(calls: list[str], *, raising: str | None = None) -> _RecordingManager:
    """Three online accounts in deterministic bring-up order."""
    return _RecordingManager(
        ["acct-a", "acct-b", "acct-c"], calls, raising=raising)


def test_stop_retires_every_online_account() -> None:
    """Every online record is retired, in bring-up order."""
    calls: list[str] = []
    # _running=False exercises the early "not running" return — the teardown lives in a
    # finally, so it must still fan out on that path.
    host = _TeardownHost(_three_accounts(calls), running=False)

    assert host.stop() is True

    assert calls == ["acct-a", "acct-b", "acct-c"]


def test_a_raising_retire_does_not_strand_the_others() -> None:
    """One venue exploding during teardown does not strand the remaining venues."""
    calls: list[str] = []
    pool = _RecordingPool()
    backend = _RecordingBackend()
    host = _TeardownHost(
        _three_accounts(calls, raising="acct-b"), running=False,
        pool=pool, backend=backend)

    # The teardown failure is swallowed at the call site — stop() does not propagate it.
    assert host.stop() is True

    # Isolation is PER ACCOUNT: acct-c is still retired after acct-b raised.
    assert calls == ["acct-a", "acct-b", "acct-c"]
    # The run-scoped pool teardown and the SQL-spine dispose that follow still ran, once.
    assert pool.close_all_calls == 1
    assert backend.dispose_calls == 1
    # The failure was reported, naming the account whose teardown failed.
    assert host.logger.error.call_count == 1
    assert "acct-b" in host.logger.error.call_args.args[0]


def test_teardown_runs_and_does_not_mask_a_raising_stop_body() -> None:
    """A teardown failure never masks an exception propagating out of the try body."""
    calls: list[str] = []
    pool = _RecordingPool()
    backend = _RecordingBackend()
    live_runner = MagicMock(name="live_runner")
    live_runner.stop.side_effect = RuntimeError("boom")
    host = _TeardownHost(
        _three_accounts(calls, raising="acct-b"),
        running=True,
        live_runner=live_runner,
        pool=pool,
        backend=backend,
    )

    # The ORIGINAL exception must surface, unmasked by anything in the finally.
    with pytest.raises(RuntimeError, match="boom"):
        host.stop()

    assert calls == ["acct-a", "acct-b", "acct-c"]
    assert pool.close_all_calls == 1
    assert backend.dispose_calls == 1
