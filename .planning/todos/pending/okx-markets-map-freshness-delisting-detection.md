---
status: scheduled
created: "2026-07-07"
source: Phase 07 CR-01 design discussion (tiziaco, 2026-07-07) — delisting-guard gap surfaced while scoping the CR-01 retry policy
tags: [live, universe, okx, markets, delisting, validate_symbol, D-06, freshness, removal-path, universe-policy, next-milestone]
milestone_target: "v1.8"
folded_into: "v1.8 spec §18 — CF-9 (P6 venue registry / validate_symbol-on-exchange)"
---

# OKX markets-map freshness for mid-session delisting detection (validate_symbol / D-06)

**Origin:** Phase 07 CR-01 design discussion (2026-07-07). While deciding the CR-02 FAILED-retry
policy (settled at **Level 2** — cadence-gate + warn, see
[[warmup-retry-nonidempotent-tradeable-corrupted-cr01]]), we established that **delisting is meant to
be handled upstream of the retry loop** by the D-06 `validate_symbol` guard + the existing removal
path — NOT by dropping symbols inside the retry loop. But that guard has two staleness holes.

## How delisting is supposed to work (and does, when the map is fresh)

`on_poll` filters `desired` through `OkxExchange.validate_symbol` (`okx.py:1016-1032`) BEFORE
computing `retry = failed_symbols() & desired`. `validate_symbol` returns
`self._to_symbol(symbol) in self._connector.client.markets`. A delisting the markets map knows about
→ `validate_symbol` False → symbol leaves `desired` → `apply` emits it in `delta.removed` →
unsubscribe/force-close. Clean, single removal contract; the symbol is never retried.

## The two holes (both staleness, not retry logic)

1. **Stale markets cache.** `load_markets` runs ONCE at connector startup and ccxt caches `markets`.
   With no refresh, a symbol delisted **mid-session** stays in the stale map → `validate_symbol`
   keeps returning True → it stays in `desired` → warmup keeps failing (a delisted symbol has no
   candles) → churns (bounded to bar-cadence + surfaced by a warning under CR-01 Level 2, but never
   actually removed). This is the real infinite-retry-source.
2. **Fail-open before load.** When `markets` is not yet a dict, `validate_symbol` returns True
   (accept, let the venue reject at submit) — a deliberate fail-open window where nothing is filtered.

## The right fix (architecturally)

Keep the markets map fresh so the **existing removal path** catches the delisting — do NOT add a
second, parallel "drop" mechanism in the retry loop. Options to weigh:
- Periodic `load_markets` refresh on a cadence (connector-owned), OR
- A refresh triggered after N repeated warmup failures for a still-`desired` symbol (lazy, targeted),
  so a genuinely-delisted symbol flips `validate_symbol` False and exits via `delta.removed`.
- Consider the fail-open window: is a startup-gate (don't admit before markets load) warranted, or is
  submit-time venue rejection an acceptable backstop?

## Optional last-ditch backstop (Level 3 quarantine — likely unnecessary)

If, after markets-freshness lands, a symbol can STILL churn (e.g. selection source returns a dead
symbol the venue also stale-lists), a hard retry ceiling + **quarantine/suppression set** could drop
it. Note the trap discussed: a naive drop WITHOUT a cooldown suppression set just ping-pongs — the
next poll's `apply` re-adds any symbol still in `desired`. So Level 3 needs a real cooldown/re-admit
policy, which is genuine universe-management machinery. Only build it if markets-freshness + CR-01
Level 2's warning prove insufficient in practice. See
[[warmup-retry-nonidempotent-tradeable-corrupted-cr01]].
