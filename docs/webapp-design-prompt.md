# iTrader Web App — Design Prompt

Prompt for Claude's design/Artifact feature to draft the operator console UI.

**Locked decisions behind this prompt:** live/paper trading only (no backtest
surface), single operator (no team/auth), clean theme-aware SaaS aesthetic.
Pages map onto the v1.8 two-registry architecture (execution accounts + data
providers) and the safety-latch lifecycle.

**Open question (not yet resolved):** the authoritative account↔portfolio bind
control — put it on the Portfolio drawer (recommended) and make Accounts
read-only about it, or expose it on both.

---

```
Design a web app: the operator console for "iTrader," a live algorithmic-trading
engine. Single operator (me), live/paper trading only — NO backtesting surface,
NO team/auth/org switching. The app's one job: make operating and monitoring a
running trading engine calm, legible, and safe.

What the engine is (use its real vocabulary — it drives the design):
It's an event-driven system. A FIFO stream flows SIGNAL → ORDER → FILL →
PORTFOLIO UPDATE. Strategies emit signals; orders rest on a venue (OKX, paper-
first); fills update Decimal-precise cash and positions. The whole system sits
behind one safety LATCH with three states: RUNNING, PAUSED, HALTED. HALTED is
terminal — it only clears when I explicitly reset it. Money is exact to the cent;
prices, quantities, order IDs, and timestamps are precision data, not prose.

── AESTHETIC DIRECTION ──
Clean, theme-aware SaaS (light + dark), airy and card-based, Linear/Vercel-grade
restraint. Precision-instrument feel, not terminal-dense and not a marketing
dashboard. Spend boldness in ONE place (the signature below); keep everything
else quiet. Do NOT use the AI-default looks (cream + serif + terracotta;
near-black + acid-green; broadsheet hairlines).

── COLOR SYSTEM (small, deliberate — light / dark) ──
The accent must never blur with gain-green or loss-red, because P&L color is
load-bearing. So brand lives in the violet band, far from both.
  --brand    (iris, interactive/primary/focus)  #5E5CE6 / #7B79F0
  --bg       (app background)                    #F7F8FA / #0D1117
  --surface  (cards)                             #FFFFFF / #161B22
  --border                                        #E4E7EC / #232A33
  --ink      (primary text)                       #1A1D21 / #E6EAF0
  --ink-muted                                     #5B6470 / #8B95A3
Semantic (financial + status — keep these three visually distinct):
  --positive (gain)          #16A34A / #3FB950   (emerald)
  --negative (loss)          #E5484D / #F0616D   (rose)
  --warning  (PAUSED)        #D98A00 / #E3A008   (amber)
  --halt     (HALTED/CRITICAL, deeper than loss) #C4292E / #F85149
Status latch → color: RUNNING=positive, PAUSED=warning, HALTED=halt.

── TYPE SYSTEM ──
Artifacts can't fetch external fonts, so: a strong system-ui stack for all UI/
display text (tight tracking, heavier weights for page titles and the hero
equity number). The typographic SIGNATURE is that EVERY numeric — money, P&L,
quantity, order ID, timestamp — is set in a monospace with TABULAR figures
(ui-monospace, "SF Mono", "JetBrains Mono"). Numbers align in columns and never
reflow. This is true to a Decimal-precise engine, and it's the type personality.

── SIGNATURE ELEMENT ──
A persistent "status latch rail": a thin full-width bar pinned to the top of the
app shell whose color and micro-copy reflect the engine's latched state. It docks
the lifecycle controls (Start / Pause / Stop). When HALTED it turns deep-red with
a subtle pulse, shows the halt reason string, and is the ONLY place "Reset halt"
lives (behind a typed confirmation). This encodes the single most important truth
about a live engine — what state the safety latch is in — and it's visible on
every page.

── PAGES & WHERE EACH UI ELEMENT LIVES ──
Persistent chrome: left nav (sections) · top status-latch rail (signature) ·
global ⌘K command palette (operator actions: start/stop/pause, jump to portfolio,
cancel order) · a global right SLIDE-OVER for the live alerts/event stream,
reachable from anywhere.

Component-placement rules to apply consistently:
  • DEDICATED PAGE  → surfaces I scan or return to (monitoring, browsing lists).
  • RIGHT DRAWER    → create / edit / inspect ONE item of an N-item collection
                      without losing the list behind it (non-destructive).
  • MODAL           → short, blocking, decision-forcing: destructive or safety
                      confirms, and secure credential entry.
  • SLIDE-OVER      → the always-available event/alert stream.

1.  Live Console (home) — PAGE. Hero: aggregate equity as a large mono number +
    delta. Grids/cards: open positions, recent fills, recent signals, and a live
    event-stream feed. The daily driver.
2.  Portfolios — list PAGE → detail PAGE (multi-portfolio). Detail shows cash,
    positions, transactions, metrics, bound account. Create/edit a portfolio and
    its per-instance config → right DRAWER.
3.  Orders — dense PAGE with two tabs: "Orders" (pending / resting / filled /
    cancelled / rejected, with bracket parent→child grouping) and "Fills"
    (executed-fill log). Row → right DRAWER (order detail + lifecycle timeline +
    modify). Cancel → confirm MODAL.
4.  Signals — PAGE: strategy signal-record stream. Row → DRAWER showing the
    order(s) that signal produced.
5.  Strategies — registry PAGE. Inline enable/disable toggle. Per-strategy config
    + portfolio assignment → right DRAWER.
6.  Accounts — PAGE (the money side): per-portfolio trading accounts. Each shows
    account_id, type (simulated cash/margin vs venue-truth), bound execution
    venue, sandbox badge, balances, and reconcile status. Add/edit account →
    DRAWER; API CREDENTIALS entered in a dedicated secure MODAL (masked, never
    shown again after save). Disconnect → confirm MODAL.
7.  Data Providers — PAGE (the data side): market-data feeds (OKX candle stream,
    replay, etc.), connection status, symbols fed, health check. Add/edit → DRAWER.
8.  Markets — PAGE with tabs, screener-ready. Tab "Universe": current tracked
    symbols (membership) + manual add/remove + poll-timer status. Tab "Screeners"
    (placeholder for a future subsystem: the rules that auto-populate the
    universe). Add/remove ticker → small MODAL.
9.  Reconciliation & Halt Center — safety-critical PAGE: venue reconcile drift
    (stored intent vs venue truth) and durable halt-record history. "Halt" and
    "Reset halt" are confirm MODALs (typed confirmation for reset).
10. System Settings — sectioned PAGE (substantial, not a modal): system-wide
    config only (RNG seed, performance, monitoring, storage, logging). Per-
    instance configs do NOT live here — they live in each entity's drawer.
11. Events — PAGE for full history/filtering of the event & error stream (the
    global slide-over is the live tail; this page is the archive).

── QUALITY FLOOR ──
Responsive to mobile; visible keyboard focus; reduced-motion respected; light and
dark both first-class. Copy is operator-facing and active-voice ("Pause trading,"
not "Submit"); an action keeps its name through its whole flow. Empty and error
states give direction, not mood.
```
