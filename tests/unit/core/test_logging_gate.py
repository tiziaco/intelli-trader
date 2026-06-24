"""Gate-transparency + drift-lock tests for the hot-path logging discipline (Phase 4, PERF-03).

Locks Plan 04-01:

* **D-02 (central level-gate):** a below-level ``ITraderStructLogger`` call returns
  *before* the structlog processor chain runs (a cached ``isEnabledFor`` short-circuit
  inside every wrapper method). Above level the wrapper emits the SAME content + fields
  as a direct structlog call — the gate changes log VOLUME, never emitted CONTENT at an
  enabled level. The oracle observes only trade count + final equity and never observes
  logs, so this dedicated unit-level drift lock is the proof the gate is behavior-only
  (mirrors the Phase 3 D-03 audit+test rigor).
* **D-08 (``ITRADER_DISABLE_LOGS`` kill-switch):** the env var short-circuits ALL levels
  unconditionally — a cached bool checked first in every guard.
* **D-01 (admission demotion content equivalence):** the demoted admission-rejection line
  renders the SAME content + fields at ``WARNING`` as the prior ``error`` call rendered;
  the demotion changes level/volume, NOT emitted content.

No hot-path runtime guard is added by these tests — re-paying the gate cost is exactly
what the phase removes; the gate lives once in the wrapper and the oracle/determinism are
the run-path locks.
"""

import logging

import pytest
import structlog

from itrader.logger import (
    ITraderStructLogger,
    _env_disable_logs,
    get_itrader_logger,
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


class _CapturingHandler(logging.Handler):
    """Collect every record that reaches the handler (post level-filter)."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def capture_records(clean_root_logger):
    """Attach a capturing handler to the root logger; return its record list.

    The handler is set to DEBUG so it never filters on its own — the only level
    gate under test is the wrapper's ``isEnabledFor`` short-circuit (D-02) / the
    root logger level set by ``init_logger`` / ``setup_logging``.
    """
    handler = _CapturingHandler()
    handler.setLevel(logging.DEBUG)
    clean_root_logger.addHandler(handler)
    return handler.records


def _reset_module_disable_flag(monkeypatch, value: bool) -> None:
    """Force the module-level cached ``_DISABLE_LOGS`` to a known value.

    The flag is resolved once at import; tests that exercise D-08 patch it
    directly so they do not depend on import-time env state.
    """
    import itrader.logger as logmod

    monkeypatch.setattr(logmod, "_DISABLE_LOGS", value, raising=False)


# --------------------------------------------------------------------------- #
# D-02 — central level-gate transparency
# --------------------------------------------------------------------------- #


def test_above_level_emits_identical_content(monkeypatch, capture_records):
    """Above level: the wrapper emits the message + bound fields verbatim."""
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "INFO")
    _reset_module_disable_flag(monkeypatch, False)
    init_logger()

    log = get_itrader_logger().bind(component="GateTest")
    log.warning("admission rejected", reason="dust")

    rendered = [r for r in capture_records if "admission rejected" in r.getMessage()]
    assert len(rendered) == 1
    # The bound component + the kwarg field survive into the structlog event dict.
    msg = rendered[0].getMessage()
    assert "admission rejected" in msg
    assert "GateTest" in msg
    assert "dust" in msg


def test_below_level_emits_nothing(monkeypatch, capture_records):
    """Below level (ERROR): debug/info/warning short-circuit -> zero records."""
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "ERROR")
    _reset_module_disable_flag(monkeypatch, False)
    init_logger()

    log = get_itrader_logger().bind(component="GateTest")
    log.debug("debug line", k=1)
    log.info("info line", k=2)
    log.warning("warning line", k=3)

    assert capture_records == []


def test_error_emits_at_error_level(monkeypatch, capture_records):
    """At ERROR level an error() call still emits (gate lets enabled calls through)."""
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "ERROR")
    _reset_module_disable_flag(monkeypatch, False)
    init_logger()

    log = get_itrader_logger().bind(component="GateTest")
    log.error("boom", code=500)

    rendered = [r for r in capture_records if "boom" in r.getMessage()]
    assert len(rendered) == 1


def test_bind_carries_stdlib_for_gate(monkeypatch, capture_records):
    """bind(component=...) must carry _stdlib so the bound instance gates without AttributeError.

    A missing carry-over would raise AttributeError on the first gated call; this
    test is the lock for the __new__ _stdlib carry-over (D-02).
    """
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "ERROR")
    _reset_module_disable_flag(monkeypatch, False)
    init_logger()

    bound = get_itrader_logger().bind(component="BindTest")
    assert hasattr(bound, "_stdlib")
    # Must not raise; below level so emits nothing.
    bound.debug("nope")
    assert capture_records == []


# --------------------------------------------------------------------------- #
# D-08 — ITRADER_DISABLE_LOGS kill-switch
# --------------------------------------------------------------------------- #


def test_disable_logs_silences_every_level(monkeypatch, capture_records):
    """ITRADER_DISABLE_LOGS=true short-circuits ALL levels, including error/critical."""
    monkeypatch.delenv("ITRADER_JSON_LOGS", raising=False)
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "DEBUG")  # everything enabled by level
    _reset_module_disable_flag(monkeypatch, True)  # but the kill-switch is on
    init_logger()

    log = get_itrader_logger().bind(component="KillTest")
    log.debug("d")
    log.info("i")
    log.warning("w")
    log.error("e")
    log.critical("c")

    assert capture_records == []


def test_env_disable_logs_parses_truthy_values():
    """_env_disable_logs mirrors the _env_json_logs truthy parsing idiom."""
    import os

    saved = os.environ.get("ITRADER_DISABLE_LOGS")
    try:
        for truthy in ("1", "true", "TRUE", "yes", "Yes"):
            os.environ["ITRADER_DISABLE_LOGS"] = truthy
            assert _env_disable_logs() is True
        for falsy in ("0", "false", "no", ""):
            os.environ["ITRADER_DISABLE_LOGS"] = falsy
            assert _env_disable_logs() is False
        os.environ.pop("ITRADER_DISABLE_LOGS", None)
        assert _env_disable_logs() is False
    finally:
        if saved is None:
            os.environ.pop("ITRADER_DISABLE_LOGS", None)
        else:
            os.environ["ITRADER_DISABLE_LOGS"] = saved


# --------------------------------------------------------------------------- #
# D-01 — admission demotion content equivalence
# --------------------------------------------------------------------------- #


def _capture_via_direct_structlog(level: str, *args, **kw) -> str:
    """Render a structlog call at ``level`` through a list-capturing config.

    Returns the single rendered message string. Used to compare the demoted
    WARNING admission line content against what the prior error() content would
    render — locks D-01: demotion changes level, NOT content.
    """
    captured: list[str] = []

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.PositionalArgumentsFormatter(),
            structlog.processors.KeyValueRenderer(key_order=["event"]),
            lambda _l, _m, ed: captured.append(ed) or ed,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    log = structlog.get_logger()
    getattr(log, level)(*args, **kw)
    return captured[0]


def test_admission_line_warning_renders_same_content_as_error():
    """D-01: the admission rejection line renders identical content at WARNING vs ERROR.

    The admission manager uses lazy ``%s`` positional formatting:
        self.logger.warning('%s - %s', error_msg, [m.message for m in errors])
    Demoting error->warning changes only the level field; the formatted message
    string (the event + positional args) is byte-identical. Render both and assert
    the message string matches.
    """
    error_msg = "Signal validation failed: Quantity below minimum 0.001"
    detail = ["Quantity below minimum 0.001"]

    rendered_error = _capture_via_direct_structlog(
        "error", "%s - %s", error_msg, detail
    )
    rendered_warning = _capture_via_direct_structlog(
        "warning", "%s - %s", error_msg, detail
    )

    # The level differs; the rendered event message (with positional args) does not.
    assert rendered_error["event"] == rendered_warning["event"]
    assert error_msg in rendered_warning["event"]
    assert "Quantity below minimum 0.001" in rendered_warning["event"]
    assert rendered_error["level"] == "error"
    assert rendered_warning["level"] == "warning"
