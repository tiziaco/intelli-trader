---
type: todo
status: pending
created: 2026-07-07
source: 07-REVIEW.md (07-10 gap-closure code review)
severity: warning
area: itrader/price_handler/feed/live_bar_feed.py
resolves_phase: null
---

# absorb_warmup: revision-vs-duplicate distinction + off-grid rejection (WR-01, WR-02)

Two non-blocking WARNING findings from the 07-10 CR-01 gap-closure review
(`.planning/phases/07-live-dynamic-universe-hardening/07-REVIEW.md`). Both are in
`LiveBarFeed.absorb_warmup` (the new `_last_delivered` guard, `live_bar_feed.py:334-346`).
Neither is data-corrupting; both are accepted-and-deferred, consistent with the project's
established pattern for deferred review findings.

## WR-01 — `bt == last` always drops silently, even for a genuine revision

The new warmup guard treats every same-timestamp bar as a benign duplicate (silent drop).
The sibling `_deliver` path (`_duplicate_or_revision`, D-07) distinguishes a byte-identical
duplicate (silent) from a genuine **revision** — same `bar.time`, different `close` — and
warns on the revision. `absorb_warmup` swallows a revision silently.

- The plan spec (07-10) explicitly chose `== silent`, so this is NOT a spec violation — it is
  a **design-consistency** gap between the warmup seam and the live-delivery seam.
- The commit's own test `test_same_timestamp_duplicate_drops_silently` builds its "duplicate"
  with a *different* close price and asserts no warning — i.e. it locks in silent revision-swallow.

**If addressed:** mirror `_duplicate_or_revision` — compare the full bar (or at least `close`)
on `==`; silent only when byte-identical, warn on a genuine revision. Update the test accordingly.

## WR-02 — no off-grid rejection in the warmup path

`update()` rejects an off-grid bar (`last < bt < last + tf`) to keep the `L` cursor on the
tf-grid. `absorb_warmup` has no equivalent, so an off-grid warmup bar could misalign
`_last_delivered` off the tf-grid and spuriously trip the gap branch on every subsequent
live delivery.

**If addressed:** add the same off-grid guard `update()` uses, or document why warmup bars
are trusted to be on-grid (venue-closed-bar contract) and assert it.

## Also (info, traceability): `CR-01` tag reused

`CR-01` labels two unrelated findings across 07-09 and 07-10 — a naming collision analogous to
the resolved `PERF-08` precedent. Worth a disambiguating note in a future audit sweep; not a
functional gap.
