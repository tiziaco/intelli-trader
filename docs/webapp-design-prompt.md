# iTrader Web App — Design Prompt

Prompt for Claude's design/Artifact feature to draft the operator console UI.

**Locked decisions behind this prompt:** live/paper trading only (no backtest
surface), single operator (no team/auth), clean theme-aware SaaS aesthetic.
Pages map onto the v1.8 two-registry architecture (execution accounts + data
providers) and the safety-latch lifecycle.

**Resolved — bind control:** the authoritative account↔portfolio bind lives on
the Portfolio drawer; Settings › Accounts is read-only about it. Binding from a
settings surface would be backwards — the portfolio owns the relationship.

**Resolved — accounts split config from state:** account *config* (registry,
venue, credentials) lives in Settings › Accounts. Account *state* (balances,
reconcile status, sandbox badge in use) surfaces on Portfolio detail and the
Live Console, where the operator actually works.

**Open — per-strategy P&L attribution:** a strategy's `subscribed_portfolios` is
a list and `PositionManager` keys positions by ticker, so two strategies trading
one symbol into one portfolio share a single position and their realized P&L
cannot be split. Either constrain strategy↔portfolio to 1:1 (attribution becomes
free — it is just that portfolio's P&L) or add lot-level `strategy_id` tagging.
Until that is decided, Strategies shows behavioural metrics only, never
attributed P&L.

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
lives (behind a typed confirmation) — no other surface offers halt controls. The
reason string deep-links to Activity › Reconciliation & Halts for the full
record. This encodes the single most important truth about a live engine — what
state the safety latch is in — and it's visible on every page.

The rail also carries a compact ENGINE-HEALTH indicator (market-data stream,
venue connector, queue depth) sitting BESIDE the latch state and never
recoloring it — the two are orthogonal. A dead feed is not PAUSED, and a RUNNING
engine quietly receiving no bars is exactly the failure this indicator exists to
catch; it must be legible without navigating anywhere. It links to Activity ›
Status for the detail.

── METRICS & CHARTS ──
The engine computes far more than any one screen should show. Two rules decide
what goes where.

FAST vs SLOW. Fast numbers change every bar and answer "what is happening right
now": equity, cash, positions value, unrealized P&L, open-position count,
exposure, concentration. They belong on the Live Console and Portfolio detail.
Slow numbers answer "is this any good": Sharpe, Sortino, Calmar, profit factor,
win rate, max drawdown. Over hours they are statistically meaningless, so they
live on Portfolio detail behind a period selector and NEVER on the home page.

MINIMUM SAMPLE. Below a sample threshold a ratio metric renders as its sample
count ("12 trades — too few to rate"), not as a number. A Sharpe of 41.2 over
three days is noise wearing a decimal point, and this design's precision
aesthetic would make it look authoritative. Cold start must degrade honestly.

Chart forms — pick the form from the data's job, before any color:
  • A single current value + trend → STAT TILE (value, delta, sparkline), never
    a one-bar bar chart. The hero equity figure is this, scaled up.
  • Equity over time → one LINE, direct-labeled, no legend box (a single series
    needs none — the title names it).
  • Equity + drawdown → TWO STACKED CHARTS sharing one x-axis. Never a dual-axis
    plot: two y-scales in one frame is the most common charting error there is.
  • Headline ratios (Sharpe / Sortino / Calmar / profit factor) → a KPI ROW of
    stat tiles. They share no common scale, so a grouped bar chart would lie.
  • Portfolio vs benchmark → two lines INDEXED TO A COMMON BASE (100) so one
    axis serves both.
  • Executed vs requested price → SCATTER, on the Fills tab only.
CHART COLOR IS RESERVED. Series draw from the brand/neutral band only:
--positive and --negative mean gain and loss and nothing else, --warning and
--halt mean status and nothing else. A chart series never borrows a semantic
color. Every chart ships a hover crosshair/tooltip and a reachable table view.
Markets and Activity get NO charts — they are lookup surfaces, and a chart there
would be decoration.

── PAGES & WHERE EACH UI ELEMENT LIVES ──
Persistent chrome: left nav (sections) · top status-latch rail (signature) ·
global ⌘K command palette (operator actions: start/stop/pause, jump to portfolio,
cancel order) · a global right SLIDE-OVER for the live alerts/event stream,
reachable from anywhere.

Component-placement rules to apply consistently:
  • DEDICATED PAGE  → surfaces I scan or return to (monitoring, browsing lists).
  • TABS            → sibling views of ONE domain that share a mental model:
                      Orders/Fills · Status/Events/Logs/Reconciliation ·
                      Universe/Screeners. Tabs group; they never hide a
                      different domain.
  • SECOND SIDEBAR  → a sectioned settings surface: many small config areas under
                      one roof, without inflating the primary nav.
  • RIGHT DRAWER    → create / edit / inspect ONE item of an N-item collection
                      without losing the list behind it (non-destructive).
  • MODAL           → short, blocking, decision-forcing: destructive or safety
                      confirms, and secure credential entry.
  • SLIDE-OVER      → the always-available event/alert stream.

Seven nav entries, no more. Each one is somewhere I go for a reason.

1. Live Console (home) — PAGE. The daily driver, and the answer to the question
   an unattended engine actually raises: "what happened while I was away?"
     · Hero: aggregate equity as a large mono number + delta, with a sparkline.
     · A RECENCY control in one row above the cards — 3d / 7d / 30d — governing
       the delta cards AND the equity curve, so the whole page reads as one
       window. It drives FACTUAL deltas only: P&L change, trades executed,
       signals fired, fills, halts, error counts. It never drives ratio metrics
       — that would smuggle the slow numbers onto the home page. This is a
       recency filter, NOT the statistical-period selector on Portfolio detail;
       the two must not look like the same control.
     · The EQUITY CURVE over the selected window (one line, direct-labeled).
     · Cards: open positions, recent fills, recent signals (the cross-strategy
       tail), bound-account balances + reconcile status.
     · A live event-stream feed.
2. Portfolios — list PAGE → detail PAGE (multi-portfolio). Detail shows cash,
   positions, transactions, and the bound account's LIVE state (balances,
   reconcile status, sandbox badge). Metrics obey the fast/slow rule:
     · FAST tiles: total equity, cash, positions value, unrealized P&L, realized
       P&L, total P&L, open-position count, and portfolio concentration.
     · SLOW metrics behind a PERIOD selector (daily / weekly / monthly /
       quarterly / yearly): total and annualized return, volatility, max
       drawdown and its duration, Sharpe, Sortino, Calmar, win rate, profit
       factor, average win/loss, and trade counts. All subject to the
       minimum-sample rule.
     · Charts: equity and drawdown as two stacked charts on a shared x-axis;
       optionally portfolio vs benchmark, both indexed to 100.
   Create/edit a portfolio and its per-instance config → right DRAWER — and the
   account↔portfolio BIND control lives in that drawer and nowhere else.
3. Orders — dense PAGE with two TABS. These are NOT one table filtered two ways:
   a live venue fills an order incrementally, so one order can produce several
   fills. The tabs differ in GRAIN, and a status filter cannot bridge them.
     · "Orders" — one row per ORDER: pending / resting / partially filled /
       filled / cancelled / rejected, with bracket parent→child grouping and a
       filled-vs-total quantity column. Status filtering lives here.
     · "Fills" — one row per EXECUTION: executed price, quantity, fee, venue
       trade id. This is the execution-quality and cash-reconciliation surface —
       fee and actual-vs-requested price exist only at this grain.
   Row → right DRAWER (order detail + lifecycle timeline + that order's own
   fills + modify). Cancel → confirm MODAL.
4. Strategies — list PAGE → detail PAGE. The list is the registry, with an
   inline enable/disable toggle per strategy. The DETAIL is where signals live,
   because a signal is only legible next to the price that produced it:
     · Centerpiece: a PRICE CHART of the bars this strategy trades, with its
       SIGNALS drawn as markers on the candles. A strategy can trade several
       symbols, so a symbol selector sits above the chart.
     · Marker semantics: BUY uses --positive, SELL uses --negative, flatten/exit
       uses --ink-muted. Every marker is positioned by the signal's business
       `time`, never wall clock.
     · Below the chart, the same signals as an exact TABLE (time, side, price,
       size, resulting order) — chart axis labels and table cells both in the
       mono tabular-figure treatment. Row → DRAWER showing the order(s) that
       signal produced.
     · Strategy metrics here are BEHAVIOURAL, not P&L: signals fired,
       signal→order→fill conversion rate, rejection reasons, and fill quality.
       Attributed per-strategy P&L is deliberately ABSENT — see the open
       attribution question above. Do not invent it.
   Per-strategy config + portfolio assignment → right DRAWER.
5. Markets — PAGE with TABS, screener-ready. Tab "Universe": current tracked
   symbols (membership) + manual add/remove + poll-timer status. Tab "Screeners"
   (placeholder for a future subsystem: the rules that auto-populate the
   universe). Add/remove ticker → small MODAL.
6. Activity — PAGE with four TABS: the engine's diagnostic surface — its current
   health, and the written record of how it got there.
     · "Status" — live engine health, read from the append-only system-stats
       series: market-data stream up, venue connector up, queue depth, uptime,
       throttle breaches, and warning / error / critical counts. Because that
       series is historical, each tile carries a SPARKLINE rather than a bare
       boolean — "up right now" and "flapping all morning" must not look alike.
       This is the DETAIL view; the rail indicator is the ambient one.
     · "Events" — full history and filtering of the typed event & error stream.
       The global slide-over is the live tail; this tab is the archive.
     · "Logs" — the structured application log (structlog output), filterable by
       level and component. Distinct from Events on purpose: logs are prose
       about the run, events are typed engine facts.
     · "Reconciliation & Halts" — venue reconcile drift (stored intent vs venue
       truth) plus the durable halt-record history. STRICTLY READ-ONLY: no halt
       controls here. "Halt" and "Reset halt" belong to the status-latch rail
       alone; the rail's reason string deep-links into this tab.
7. Settings — PAGE with a SECOND LEFT SIDEBAR (the primary nav stays put; a
   second column navigates sections). System-wide config only — per-instance
   configs do NOT live here, they live in each entity's drawer.
     · General — RNG seed, timezone, run identity/name, storage, data dirs.
     · Accounts — the money-side registry: per-portfolio trading accounts with
       account_id, type (simulated cash/margin vs venue-truth), bound execution
       venue, and sandbox badge. Add/edit → right DRAWER; API CREDENTIALS in a
       dedicated secure MODAL (masked, never shown again after save); disconnect
       → confirm MODAL. Live balances and reconcile status are deliberately NOT
       here — they belong on Portfolio detail and the Live Console.
     · Data Providers — the data-side registry: market-data feeds (OKX candle
       stream, replay, etc.), connection status, symbols fed, health check.
       Add/edit → right DRAWER.
     · Safety — safety POLICY only: latch rules, thresholds, alert routing.
       Current drift and halt history live in Activity, not here.
     · Logging — log level, sinks, retention.

── QUALITY FLOOR ──
Responsive to mobile; visible keyboard focus; reduced-motion respected; light and
dark both first-class. Copy is operator-facing and active-voice ("Pause trading,"
not "Submit"); an action keeps its name through its whole flow. Empty and error
states give direction, not mood.
```
