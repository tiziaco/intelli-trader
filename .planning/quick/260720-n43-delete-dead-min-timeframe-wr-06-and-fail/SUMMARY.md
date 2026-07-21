# Quick Task 260720-n43 — Audit Marker

Two Phase 10.1 review findings closed together (coupled: deleting `min_timeframe`
removed one of the two halves WR-01 was about).

- **WR-06** — deleted the dead derived `min_timeframe` roster state. It had **zero
  production readers**: every hit in `itrader/` was a write, a docstring, or the
  recompute machinery itself, and the only readers were tests exercising the
  derivation of a value nothing consumed. Also removed both FALSE *"used from the
  price handler to download historical prices"* docstring claims (the live feed
  sizes its ring from `required_history_depth`, not this value). Those two were
  grep-invisible — no `min_timeframe` symbol in the sentence — so they were deleted
  by reading.

- **WR-01** — ordered the raising `registry_store.delete()` ahead of every in-memory
  mutation in `StrategyLifecycleManager._try_complete_removal`. A store fault now
  mutates nothing and the next FILL retries cleanly, rather than leaving the strategy
  dropped from the roster but still in `_pending_removals` and self-healing only by
  accident of a defensive branch. Pinned by a falsification-proven regression test.

**Design note:** reorder only — `discard_pending` was deliberately NOT folded into
`ManagedStrategies.remove()`. Post-reorder both in-memory mutations are unconditionally
reached, so folding buys encapsulation and zero safety, while broadening a contract
`test_remove_is_guarded_and_mutates_in_place` documents and 2 direct test callers rely on.

**Survivors deliberately kept** (a blind sweep would have destroyed these):
- `itrader/screeners_handler/screeners_handler.py:29,113` — the screener class's own
  unrelated `min_timeframe` field, deferred subsystem
- `tests/integration/test_bar_cache_registration.py` — `test_trigger_seam_allows_base_le_min_timeframe`
  is the FEED's `base_timeframe <= min(timeframe)` ordering constraint, a different
  concept entirely. Zero-byte diff.
- `check_timeframe` — real and live; only the deleted symbol was dropped from the two
  Pitfall-1 comments in `base.py`

**Gates (all observed):** unit 2299 passed (2302 − 3 − 1 + 1, delta accounted) ·
integration 204 passed / 2 skipped · oracle byte-exact `trade_count 134` /
`final_equity 46189.87730727451` · mypy clean, 273 source files ·
0 non-screener `min_timeframe` hits · 0 `recompute_min_timeframe` hits.

**Commits:** `0b11aacf` (WR-01 reorder + test) · `8b60759b` (WR-06 deletion) ·
`a58007d0` (survivor comment excisions) · `dd9c26de` (plan artifact).
