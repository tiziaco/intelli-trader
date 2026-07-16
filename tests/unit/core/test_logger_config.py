"""Regression tests for env-driven logger configuration (M3-03 / D-20).

Locks Plan 04-08 Task 1:

* ``ITRADER_LOG_LEVEL`` / ``ITRADER_JSON_LOGS`` drive ``init_logger`` via
  direct ``os.environ`` reads — never by constructing ``RuntimeSettings()``
  (Pitfall 8: the logger must not instantiate any config/settings model at
  import time, keeping ``import itrader`` side-effect-free).
* Handler installation is guarded and idempotent: repeated setup never stacks
  duplicate handlers and never clobbers handlers installed by embedding
  applications or pytest.
"""

import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import structlog

import itrader
from itrader.logger import (
    _env_json_logs,
    _env_log_level,
    _json_default,
    init_logger,
)

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


def test_json_default_stringifies_uuid():
    """WR-01: _json_default stringifies uuid.UUID rather than raising."""
    cid = uuid.uuid4()
    assert _json_default(cid) == str(cid)


def test_json_default_rejects_other_types():
    """WR-01: _json_default still raises TypeError for unknown types."""
    with pytest.raises(TypeError):
        _json_default(object())


def test_json_renderer_serializes_uuid_correlation_id(monkeypatch, clean_root_logger):
    """WR-01: the JSON renderer serializes uuid.UUID log context without raising.

    The single-UUIDv7 scheme (DEC-03) flows uuid.UUID correlation_id /
    portfolio_id values into the ERROR-route log context. A bare JSONRenderer
    would raise ``TypeError: Object of type UUID is not JSON serializable``;
    the UUID-aware serializer must render them as strings.
    """
    monkeypatch.delenv("ITRADER_LOG_LEVEL", raising=False)
    monkeypatch.setenv("ITRADER_JSON_LOGS", "true")

    init_logger()
    handlers = _itrader_handlers(clean_root_logger)
    assert len(handlers) == 1
    formatter = handlers[0].formatter
    renderer = next(
        p for p in formatter.processors
        if isinstance(p, structlog.processors.JSONRenderer)
    )

    cid = uuid.uuid4()
    rendered = renderer(None, "error", {"event": "boom", "correlation_id": cid})
    payload = json.loads(rendered)
    assert payload["correlation_id"] == str(cid)


def test_init_does_not_clobber_foreign_handlers(monkeypatch, clean_root_logger):
    """Guarded init: handlers installed by embedders/pytest survive setup."""
    monkeypatch.delenv("ITRADER_LOG_LEVEL", raising=False)
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)

    foreign = logging.NullHandler()
    clean_root_logger.addHandler(foreign)

    init_logger()

    assert foreign in clean_root_logger.handlers
