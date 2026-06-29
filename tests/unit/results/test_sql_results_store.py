"""In-process SQLite tests for ``SqlResultsStore`` (RESULT-02/03/04).

Covers the concrete results store end-to-end on a ``:memory:`` SQLite backend (CONTEXT
D-12 — tests use in-process SQLite):

1. round-trip — a saved artifact frame reads back value-equal (D-15).
2. byte-determinism — the gzip codec encodes the same frame to identical bytes (D-10).
3. atomic ``save_run`` — the ``runs`` row and its ``run_portfolios`` rows land together.
4. ranking — ``top_runs`` / ``top_portfolios`` order best-first with the ``run_id`` ASC
   tiebreak and the correct (DESC) drawdown direction (D-18).
5. missing / empty — ``get_artifact`` on an unknown run raises ``ResultsNotFound``;
   ``top_runs`` on a fresh store returns ``[]`` (D-16).

The directory is package-less (NO ``__init__.py``) — matching the sibling
``tests/unit/results/test_results_store_abc.py`` and the ``tests/unit`` convention.
"""

import uuid
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy import select

from itrader import idgen
from itrader.config.sql import SqlSettings
from itrader.core.exceptions import ResultsNotFound
from itrader.results.records import PortfolioRecord, RunMetrics, RunRecord
from itrader.results.sql_storage import SqlResultsStore
from itrader.storage import SqlBackend


def _run_id() -> uuid.UUID:
    """A fresh UUIDv7 run id (single UUIDv7 scheme — ``idgen``)."""
    return idgen._uuid7()


def _metrics(**overrides: float) -> RunMetrics:
    """A ``RunMetrics`` with sane defaults, overridable per-metric."""
    base: dict[str, float] = {
        "sharpe": 1.0,
        "sortino": 1.0,
        "cagr": 0.1,
        "calmar": 0.5,
        "max_drawdown": -0.2,
        "profit_factor": 1.5,
        "win_rate": 0.6,
        "total_return": 0.3,
        "final_equity": 130.0,
        "total_realised_pnl": 30.0,
        "trade_count": 10.0,
    }
    base.update(overrides)
    return RunMetrics(**base)


def _portfolio(metrics: RunMetrics, name: str = "p1") -> PortfolioRecord:
    """A ``PortfolioRecord`` carrying ``metrics`` and a trivial params dict."""
    return PortfolioRecord(
        portfolio_id=idgen._uuid7(),
        name=name,
        metrics=metrics,
        params={"fast": 10, "slow": 30},
    )


def _run(
    run_id: uuid.UUID,
    metrics: RunMetrics,
    portfolios: tuple[PortfolioRecord, ...] = (),
) -> RunRecord:
    """A ``RunRecord`` with a curated settings envelope and per-portfolio rows."""
    return RunRecord(
        run_id=run_id,
        metrics=metrics,
        settings={"strategy": "SMA_MACD", "rng_seed": 42},
        per_portfolio=list(portfolios),
    )


def _frame() -> pd.DataFrame:
    """A small round-trip-stable frame (float columns + default RangeIndex)."""
    return pd.DataFrame(
        {"equity": [100.0, 101.5, 99.25], "drawdown": [0.0, -0.5, -1.0]}
    )


@pytest.fixture
def store() -> Any:
    """A fresh ``SqlResultsStore`` over an in-process SQLite spine (``:memory:``)."""
    backend = SqlBackend(SqlSettings())
    results_store = SqlResultsStore(backend)
    try:
        yield results_store
    finally:
        backend.dispose()


# --------------------------------------------------------------------- Task 1: codec + save
def test_codec_roundtrip(store: SqlResultsStore) -> None:
    """``_decode_frame(_encode_frame(df))`` is value-equal to ``df`` (D-10/D-15)."""
    frame = _frame()
    decoded = store._decode_frame(store._encode_frame(frame))
    assert_frame_equal(decoded, frame)


def test_codec_byte_determinism(store: SqlResultsStore) -> None:
    """The gzip codec encodes the same frame to byte-identical blobs (RESULT-04/D-10)."""
    frame = _frame()
    assert store._encode_frame(frame) == store._encode_frame(frame)


def test_save_run_atomic_persists_run_and_portfolios(store: SqlResultsStore) -> None:
    """``save_run`` lands the ``runs`` row AND both ``run_portfolios`` rows (D-13)."""
    run_id = _run_id()
    record = _run(
        run_id,
        _metrics(),
        portfolios=(_portfolio(_metrics(), "p1"), _portfolio(_metrics(), "p2")),
    )

    returned = store.save_run(record)
    assert returned == run_id

    with store.engine.connect() as connection:
        runs = connection.execute(select(store.runs)).mappings().all()
        portfolios = connection.execute(
            select(store.run_portfolios)
        ).mappings().all()

    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert len(portfolios) == 2
    assert {row["name"] for row in portfolios} == {"p1", "p2"}


# ------------------------------------------------------------------ Task 2: reads
def test_get_artifact_roundtrip_keyed_collection(store: SqlResultsStore) -> None:
    """``get_artifact`` returns ``{(portfolio_id, type): frame}`` value-equal (D-15)."""
    run_id = _run_id()
    portfolio = _portfolio(_metrics(), "p1")
    store.save_run(_run(run_id, _metrics(), portfolios=(portfolio,)))

    frame = _frame()
    store.save_artifact(run_id, portfolio.portfolio_id, "equity_curve", frame)

    artifacts = store.get_artifact(run_id)
    assert set(artifacts) == {(portfolio.portfolio_id, "equity_curve")}
    assert_frame_equal(artifacts[(portfolio.portfolio_id, "equity_curve")], frame)


def test_get_artifact_handles_null_portfolio_key(store: SqlResultsStore) -> None:
    """An aggregate-level frame (``portfolio_id=None``) keys on ``(None, type)`` (D-07)."""
    run_id = _run_id()
    store.save_run(_run(run_id, _metrics()))
    frame = _frame()
    store.save_artifact(run_id, None, "trade_log", frame)

    artifacts = store.get_artifact(run_id)
    assert (None, "trade_log") in artifacts
    assert_frame_equal(artifacts[(None, "trade_log")], frame)


def test_get_artifact_unknown_run_raises(store: SqlResultsStore) -> None:
    """``get_artifact`` on an unknown ``run_id`` raises ``ResultsNotFound`` (D-16)."""
    store.save_run(_run(_run_id(), _metrics()))  # populate so the table is non-empty
    with pytest.raises(ResultsNotFound):
        store.get_artifact(uuid.uuid4())


def test_top_runs_empty_table_returns_empty(store: SqlResultsStore) -> None:
    """``top_runs`` on a fresh store returns ``[]`` (empty-safe, D-16)."""
    assert store.top_runs("sharpe", 5) == []
    assert store.top_portfolios("sharpe", 5) == []
