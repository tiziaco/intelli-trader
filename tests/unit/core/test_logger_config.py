"""Regression tests for env-driven logger configuration (M3-03 / D-20).

Locks Plan 04-08 Task 1:

* ``ITRADER_LOG_LEVEL`` / ``ITRADER_JSON_LOGS`` drive ``init_logger`` via
  direct ``os.environ`` reads — never by constructing ``Settings()``
  (Pitfall 8: ``ITRADER_DATABASE_URL`` is a required-no-default ``SecretStr``,
  so ``Settings()`` at import time would raise ``ValidationError`` on every
  ``import itrader``).
* Handler installation is guarded and idempotent: repeated setup never stacks
  duplicate handlers and never clobbers handlers installed by embedding
  applications or pytest.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import structlog

import itrader
from itrader.logger import _env_json_logs, _env_log_level, init_logger

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_root_logger():
    """Snapshot and restore root-logger handlers/level around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def _itrader_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if getattr(h, "_itrader_handler", False)]


def test_defaults_without_env(monkeypatch, clean_root_logger):
    """(a) No env vars set -> log_level INFO, json_logs False."""
    monkeypatch.delenv("ITRADER_LOG_LEVEL", raising=False)
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)

    assert _env_log_level() == "INFO"
    assert _env_json_logs() is False

    init_logger()
    assert clean_root_logger.level == logging.INFO


def test_log_level_env_honored(monkeypatch, clean_root_logger):
    """(b) ITRADER_LOG_LEVEL=DEBUG is honored by init_logger."""
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "DEBUG")

    assert _env_log_level() == "DEBUG"

    init_logger()
    assert clean_root_logger.level == logging.DEBUG


def test_json_logs_env_flips_json_rendering(monkeypatch, clean_root_logger):
    """(c) ITRADER_JSON_LOGS=true installs a JSONRenderer formatter."""
    monkeypatch.delenv("ITRADER_LOG_LEVEL", raising=False)
    monkeypatch.setenv("ITRADER_JSON_LOGS", "true")

    assert _env_json_logs() is True

    init_logger()
    handlers = _itrader_handlers(clean_root_logger)
    assert len(handlers) == 1
    formatter = handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
    assert any(
        isinstance(p, structlog.processors.JSONRenderer)
        for p in formatter.processors
    )


def test_import_itrader_safe_without_database_url():
    """(d) import itrader must not raise when ITRADER_DATABASE_URL is unset."""
    repo_root = Path(itrader.__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("ITRADER_")}
    env["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [sys.executable, "-c", "import itrader; import itrader.logger"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_setup_twice_does_not_stack_handlers(monkeypatch, clean_root_logger):
    """(e) Calling setup twice keeps exactly one itrader handler."""
    monkeypatch.delenv("ITRADER_LOG_LEVEL", raising=False)
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)

    init_logger()
    init_logger()

    assert len(_itrader_handlers(clean_root_logger)) == 1


def test_init_does_not_clobber_foreign_handlers(monkeypatch, clean_root_logger):
    """Guarded init: handlers installed by embedders/pytest survive setup."""
    monkeypatch.delenv("ITRADER_LOG_LEVEL", raising=False)
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)

    foreign = logging.NullHandler()
    clean_root_logger.addHandler(foreign)

    init_logger()

    assert foreign in clean_root_logger.handlers
