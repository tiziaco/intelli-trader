# iTrader test suite

Tests are organized on a **TYPE axis** (D-13/D-15): the top-level split is
`unit/` vs `integration/`, not by domain. The domain structure lives *inside*
`unit/`, mirroring the `itrader/` package.

```
tests/
├── conftest.py            # root: folder-derived TYPE marker auto-marking + global_queue
├── README.md              # this file
├── golden/                # frozen-oracle assets (trades.csv, equity.csv, summary.json)
├── unit/                  # one collaborating component each (mirrors the package)
│   ├── conftest.py
│   ├── config/            # Pydantic config models
│   ├── core/              # enums, clock, money
│   ├── outils/            # id generator, time_parser
│   ├── events/            # event dataclasses / schemas
│   ├── order/             # order handler / manager / validator / storage
│   ├── execution/         # execution handler, matching engine
│   │   └── exchanges/     # simulated exchange
│   ├── portfolio/         # portfolio handler + cash/position/transaction/metrics managers
│   │   ├── positions/     # position-entity behavior
│   │   └── transaction/   # transaction-entity behavior
│   └── strategy/          # strategy composition
└── integration/           # cross-component cascade, run-path smoke, golden oracle
    ├── conftest.py        # golden-path fixtures + backtest_engine factory
    ├── test_backtest_oracle.py        # golden-master oracle
    ├── test_backtest_smoke.py         # run-path smoke (full TradingSystem)
    ├── test_event_wiring.py           # EventHandler chain wiring
    └── test_execution_handler_routing.py  # exchange/execution routing
```

## The unit / integration boundary (D-15)

- **unit** — drives **ONE** collaborating component in isolation. May import
  several classes from its own domain and use a real `global_queue` (root-conftest
  fixture), but it does **not** assert cross-component cascades.
- **integration** — asserts interaction **across** components: cross-domain,
  cross-manager, the full event cascade, the run-path smoke, or the golden oracle.

## Markers

Markers are **folder-derived**: a test under `tests/unit/` is auto-marked `unit`;
a test under `tests/integration/` is auto-marked `integration` (+ `slow`). The
application happens in `tests/conftest.py::pytest_collection_modifyitems`; the
single **registration** home (the `--strict-markers` source of truth) is the
`markers` list in `pyproject.toml`. Never register markers in both places.

`smoke` is a **PURPOSE-axis** marker — orthogonal to the folder-derived TYPE axis
above. It is **NOT** folder-derived: it is applied **by hand** with
`@pytest.mark.smoke` (or a module-level `pytestmark = pytest.mark.smoke`), and it
stacks *on top of* whatever TYPE marker the folder confers (so a smoke test under
`tests/integration/` is both `integration` and `smoke`). It selects the fast
run-path liveness set via `make test-smoke` / `-m smoke`.

**Durable rule:** any new smoke test MUST be tagged `@pytest.mark.smoke` (or carry
a module-level `pytestmark`) so it joins the `make test-smoke` selection — the
marker is never auto-applied.

## Running

```bash
make test              # full suite
make test-unit         # -m "unit"
make test-integration  # -m "integration"
make test-smoke        # -m "smoke"  (PURPOSE axis; hand-tagged)
make test-portfolio    # tests/unit/portfolio/
make test-orders       # tests/unit/order/
make test-execution    # tests/unit/execution/
make test-events       # tests/unit/events/
make test-strategy     # tests/unit/strategy/
```
