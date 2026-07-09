"""SEC-01 / FL-06 — reworked ``SqlHandler`` behavior + the FL-06 grep gates.

Two halves:

* **Single-table behavior (D-07).** Over an in-process ``SqlEngine(SqlSettings())`` SQLite
  engine (NO Docker), OHLCV round-trips, ``get_symbols()`` returns the written symbols, the
  ONLY data table is ``prices`` (never a per-symbol table), and two symbols coexist in that
  one table filtered by a bound ``symbol`` parameter.

* **FL-06 grep gates (SEC-01).** A pathlib scan of ``itrader/`` proves no source file
  carries a hardcoded DB credential or an f-string interpolated inside a ``text()`` call.
  The forbidden patterns are assembled from fragments at runtime so this test module never
  embeds the literal anti-pattern strings (it must not self-trip the gate).

4-space indentation (``tests/unit/*`` convention). The directory is intentionally
package-less (no ``__init__.py``) — test basenames are unique and a ``price_handler`` test
package would collide on collection (ref 30c0f61).
"""

import re
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import inspect

from itrader.config.sql import SqlSettings
from itrader.price_handler.store.sql_store import SqlHandler
from itrader.storage import SqlEngine

# tests/unit/price_handler/test_sql_handler.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ITRADER_DIR = _REPO_ROOT / "itrader"


@pytest.fixture
def handler():
    """A ``SqlHandler`` over a fresh in-process SQLite spine; engine disposed on teardown.

    Disposing the engine in teardown closes the SingletonThreadPool connection so no
    ``ResourceWarning`` escapes under ``filterwarnings=["error"]``.
    """
    backend = SqlEngine(SqlSettings())  # in-process SQLite, no Docker
    sql_handler = SqlHandler(backend)
    try:
        yield sql_handler
    finally:
        sql_handler.stop_engine()


def _ohlcv_frame(close: float = 2.5) -> pd.DataFrame:
    """A small 2-bar date-indexed OHLCV frame (tz-aware UTC index named ``date``)."""
    index = pd.to_datetime(["2018-01-01", "2018-01-02"]).tz_localize("UTC")
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.1],
            "high": [3.0, 3.1],
            "low": [0.5, 0.6],
            "close": [close, close],
            "volume": [10.0, 11.0],
        },
        index=index,
    )
    frame.index.name = "date"
    return frame


# --- SEC-01 single-table behavior (D-07) ------------------------------------


def test_ohlcv_round_trips_for_a_single_symbol(handler):
    """OHLCV written for one symbol reads back equal via the public surface."""
    frame = _ohlcv_frame()
    handler.to_database("BTCUSD", frame, replace=True)

    got = handler.read_prices("BTCUSD")

    assert list(got.columns) == ["open", "high", "low", "close", "volume"]
    assert got["open"].tolist() == frame["open"].tolist()
    assert got["high"].tolist() == frame["high"].tolist()
    assert got["low"].tolist() == frame["low"].tolist()
    assert got["close"].tolist() == frame["close"].tolist()
    assert got["volume"].tolist() == frame["volume"].tolist()
    assert handler.get_symbols() == ["BTCUSD"]


def test_only_data_table_is_prices_no_per_symbol_table(handler):
    """D-07: storage uses a SINGLE ``prices`` table — never a symbol-named table."""
    handler.to_database("BTCUSD", _ohlcv_frame(), replace=True)

    tables = inspect(handler.engine).get_table_names()

    assert tables == ["prices"]
    assert "btcusd" not in tables
    assert "BTCUSD" not in tables


def test_two_symbols_coexist_in_one_table_filtered_by_symbol(handler):
    """Two symbols live in the one ``prices`` table; reads are filtered by ``symbol``."""
    handler.to_database("BTCUSD", _ohlcv_frame(close=2.5), replace=True)
    handler.to_database("ETHUSD", _ohlcv_frame(close=9.0), replace=True)

    assert handler.get_symbols() == ["BTCUSD", "ETHUSD"]
    assert inspect(handler.engine).get_table_names() == ["prices"]

    btc = handler.read_prices("BTCUSD")
    eth = handler.read_prices("ETHUSD")
    assert btc["close"].tolist() == [2.5, 2.5]  # only BTC rows returned
    assert eth["close"].tolist() == [9.0, 9.0]  # only ETH rows returned


def test_replace_overwrites_a_symbol_in_place(handler):
    """A second ``replace=True`` write swaps the symbol's rows without leaking old ones."""
    handler.to_database("BTCUSD", _ohlcv_frame(close=2.5), replace=True)
    handler.to_database("BTCUSD", _ohlcv_frame(close=7.0), replace=True)

    got = handler.read_prices("BTCUSD")
    assert got["close"].tolist() == [7.0, 7.0]
    assert handler.get_symbols() == ["BTCUSD"]


def test_delete_prices_removes_only_the_named_symbol(handler):
    """``delete_prices(symbol)`` is a parameterized delete scoped to one symbol."""
    handler.to_database("BTCUSD", _ohlcv_frame(), replace=True)
    handler.to_database("ETHUSD", _ohlcv_frame(), replace=True)

    handler.delete_prices("BTCUSD")

    assert handler.get_symbols() == ["ETHUSD"]


# --- FL-06 grep gates (SEC-01) ----------------------------------------------
#
# Structural regex gates that match the SHAPE of the anti-pattern (not just the specific
# legacy literal), assembled from fragments so this module never embeds the literal
# anti-pattern strings (it must not self-trip the gate it enforces). The scan covers only
# ``itrader/`` — this test file lives under ``tests/`` and is excluded by construction.


def _hardcoded_credential_pattern() -> "re.Pattern[str]":
    """A structural regex for an embedded ``scheme://user:password@host`` credential.

    Matches a colon-separated user/password pair wedged between ``://`` and ``@`` — the
    SHAPE of any hardcoded DB credential (e.g. ``postgres:password@``, ``itrader:itrader123@``),
    not just the narrow ``user:pass@`` / ``:1234@`` literals the old substring check looked
    for. Assembled from fragments so the pattern is never embedded literally.
    """
    sep = "://"
    user = "[^:" + r"\s" + "/@]+"  # one+ non-(colon/space/slash/at) chars
    pwd = "[^@" + r"\s" + "/]+"  # one+ non-(at/space/slash) chars
    return re.compile(sep + user + ":" + pwd + "@")


def _fstring_in_text_pattern() -> "re.Pattern[str]":
    """A structural regex for an f-string interpolated into a ``text(...)`` call.

    Matches a ``text(`` call followed by optional whitespace/newline and an f-string prefix
    (``f'`` or ``f"``) — so ``text( f"..."`` and a line-broken ``text(`` then ``f"...")`` are
    both caught, which the old whitespace-free substring check missed. A negative lookbehind
    keeps it from tripping on unrelated identifiers that merely END in ``text`` (e.g.
    ``_operation_context(...)``). Assembled from fragments to avoid self-tripping.
    """
    boundary = r"(?<![A-Za-z0-9_])"  # not preceded by an identifier char
    call = "text" + r"\("
    fprefix = "f[" + "\"'" + "]"  # an f" or f' prefix
    return re.compile(boundary + call + r"\s*" + fprefix)


def _itrader_python_sources() -> list[Path]:
    return sorted(_ITRADER_DIR.rglob("*.py"))


def _scan_for(pattern: "re.Pattern[str]") -> list[tuple[str, str]]:
    """Scan every ``itrader/`` source for ``pattern`` over whole-file text.

    Whole-file (not line-by-line) so a ``\\s`` in the pattern can span a newline, catching
    a line-broken ``text(`` / ``f"..."`` injection. Returns ``(path, matched-text)`` pairs.
    """
    offenders: list[tuple[str, str]] = []
    for path in _itrader_python_sources():
        content = path.read_text(encoding="utf-8")
        match = pattern.search(content)
        if match:
            offenders.append((str(path), match.group(0)))
    return offenders


def test_no_hardcoded_db_credentials_anywhere_in_itrader():
    """FL-06 L17: no source file under ``itrader/`` carries a hardcoded DB credential."""
    offenders = _scan_for(_hardcoded_credential_pattern())
    assert not offenders, f"hardcoded credential pattern found: {offenders}"


def test_no_fstring_inside_a_text_call_anywhere_in_itrader():
    """FL-06 L35: no source file under ``itrader/`` interpolates an f-string into text()."""
    offenders = _scan_for(_fstring_in_text_pattern())
    assert not offenders, f"f-string inside text() found: {offenders}"
