# Phase 11.1 — External-API Coverage Matrix

**Produced:** 2026-07-22 (plan time)
**Detector:** the `api-coverage scan` query subcommand is **not available** in this GSD
install (`node gsd-tools.cjs query api-coverage scan 11.1 --json` → `Unknown command:
api-coverage`). The matrix below is therefore authored directly rather than skipped, so the
`api-coverage.verify-pre` gate has a well-formed artifact to validate at seal time instead of
re-running a detector that would fire on this phase's OKX/connector vocabulary.

## Scope statement

Phase 11.1 is an **internal structural refactor**. It changes *who constructs* the already-shipped
OKX and paper venue plugins, how the execution registry is keyed, and where the `Account` leaf is
built. It adds **no new external-API capability surface**: no new OKX endpoint, no new ccxt call, no
new credential path, no new stream subscription, no new venue.

The OKX capability surface enumerated below is the one Phases 5, 11 and 11-09 already integrated. It
is restated here so the matrix is a full-coverage baseline rather than an inheritance of a prior
phase's opt-outs, per the "second integration re-decides from the same full-coverage baseline" rule.

## Capability matrix

| # | Capability | External surface | Decision | Note |
|---|------------|------------------|----------|------|
| 1 | Authenticated venue session | `ccxt.pro` client via `OkxConnector` (`itrader/connectors/okx.py`) | INTEGRATE | Unchanged by 11.1. `ConnectorProvider` still memoizes one session per `(venue, account_id)`; D-08 adds a bundle memo one layer above it and cannot create a second session. |
| 2 | Order submission / cancel | `OkxExchange` (`itrader/execution_handler/exchanges/okx.py`) | INTEGRATE | Unchanged. D-06 makes the *paper* plugin build its own `SimulatedExchange`, symmetric with the OKX plugin already building its own `OkxExchange`. |
| 3 | Fill stream / order stream | `OkxExchange.connect()` → `_stream_fills` / `_stream_orders` | INTEGRATE | Unchanged, and D-08's memoization exists specifically to keep this arm single-spawn per account. |
| 4 | Account balance / position truth | `VenueAccount` over the connector (`portfolio_handler/account/venue.py`) | INTEGRATE | Unchanged. D-01 removes the `Portfolio` back-reference from the two **simulated** leaves only; `VenueAccount` already takes none. |
| 5 | Market-data stream (OHLCV) | `OkxDataProvider` via `OkxDataPlugin.build_provider` | INTEGRATE | D-14 reduces the number of *constructed* providers from N-per-account to exactly one (the feed's). The capability is unchanged; the surplus constructions were unwired and credential-bearing (WR-07). |
| 6 | Venue account UID assertion | `OkxVenuePlugin.fetch_venue_uid` + `venue_uid_guard` | INTEGRATE | Unchanged in 11.1. The `venue_uid_guard_active` status flag is Phase 11.2 (D-15, `[informational]`). |
| 7 | Credential resolution | `EnvCredentialResolver` + `venue_accounts.secret_ref` | INTEGRATE | Unchanged as a capability. 11.1 deletes `_read_account_secret_ref` from the composition root only when `_build_account_specs` is restructured; the pointer→resolver contract is untouched. |
| 8 | Regional host / sandbox routing | `OkxConnector` region + sandbox hosts | INTEGRATE | Unchanged. Wiring `venue_accounts.config_json` for `sandbox`/`region`/`market_type` is Phase 11.2 (D-12, `[informational]`). |

**OPT-OUT count: 0.** No capability is opted out of by this phase, and no capability previously
integrated is narrowed.

## Deliberately-not-this-phase (tracked elsewhere, not opt-outs)

- Credential-free public market data (a paper deployment streaming OKX bars with no OKX keys) —
  `11.1-CONTEXT.md` § Deferred Ideas, blocked on `OkxConnector.__init__` requiring the full auth
  triple. D-14 reduces its call sites from N to one, which is preparation, not delivery.
- `venue_accounts.config_json` wiring, provisioning verbs, and the UID-guard status flag — Phase 11.2
  (`D-12` / `D-10` / `D-11` / `D-15`, all `[informational]` here).
- Live commission under-reservation on a real OKX exchange (`compose.py:78` returns `Decimal("0")`
  today) — a **known, documented, deliberately-unfixed** defect. D-18 makes it visible as an explicit
  "this venue exposes no fee model" contract without changing the value. Fixing it here would move
  the byte-exact oracle.
