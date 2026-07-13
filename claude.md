# Stock Daily Research Dashboard

Personal stock research dashboard with daily HTML report generation. Features technical analysis, earnings tracking, valuation checks, news clustering, and manual research state management.

## Project Status

**Latest iteration (2026-07-10)**:
- **Multi-market support**: `TickerConfig.market` (us / twse / tpex / crypto), auto-inferred from symbol suffix (`.TW` → twse, `.TWO` → tpex, `-USD` → crypto). `MARKET_DEFAULTS` in `models.py` drives per-market currency, Google News edition (`zh-TW` for Taiwan), and default news domains (cnyes/moneydj/udn for 台股, coindesk/cointelegraph/theblock for crypto). Crypto skips earnings-date + analyst-estimate fetches (`TickerConfig.has_earnings`); data-quality doesn't penalize crypto for missing forward P/E. Mixed-currency holdings hide combined P&L.
- **Sector map (產業地圖)**: `#sector-leadership` section (placed right after `#daily-summary`) renders diverging heat tiles (±0.5/1.5/3% bins, `map_change_bin`) grouped by sector, one panel per market with tabs + 漲跌家數 breadth. Market tabs share ONE state with the ticker-card market tabs: same keys (us/taiwan/crypto), same localStorage key `stock-daily-market-tab`, synced both ways via the `stock-daily:market` CustomEvent. Card/table market-cap sorts are market-scoped (TWD vs USD caps are not comparable). Per-market taxonomies in `report.py`: `SECTOR_GROUPS` (US themes), `TW_SECTOR_GROUPS` (封測/晶圓代工/IC 設計/功率元件/被動元件/電源 重電/散熱…), `CRYPTO_SECTOR_GROUPS`. Assignment is exclusive (first match wins, specific groups first); short ASCII terms (≤4 chars) are word-boundary matched via `_sector_term_matches` to prevent substring false-positives ("ai" in "sustain", "mu" in "communication").
- **Earlier (2026-06-17)**: UI Localization (繁體中文 + language toggle), one-click Save to Database (`api_server.py`)
- **Earlier Features**: C–H (Delta Badges, Valuation Cache, Plan Triggers, Morning Actions, Attention Sparkline, My Book P&L), #1 (Investment Plan), #3 (Event Pre/Post-earnings), #4 (Data Quality), A (News Read Markers), B (Thesis Manual Fill)

**Test Suite**: 255 tests, all passing. Report generation: ~1–2 min full fetch (32 tickers), <1s with `--no-news --no-valuation --no-macro`. API server: HTTP-based, no external dependencies.

## Quick Commands

```bash
# Generate full daily report (fetches news, valuation, earnings, macro)
python run_daily.py

# Fast HTML-only regen (no network)
python run_daily.py --no-news --no-valuation --no-macro

# Run full test suite
python -m pytest tests/ -q

# Start API server for one-click "Save to Database" in report
python -m stock_daily_research.api_server

# Import research state from JSON
python -m stock_daily_research.cli --import-research-state research-state-2026-06-02.json

# Export current research state
# (Available via UI export button or CLI)
```

## Architecture

### Data Flow
1. **YAML config** (`watchlist.yaml`): Ticker list + YAML defaults (plan, position)
2. **Fetchers** (`news.py`, `valuation.py`, `earnings.py`, `macro.py`): Populate dataclasses
3. **Models** (`models.py`): Frozen dataclasses for immutability
4. **SQLite** (`storage.py`): Persists research state, post-earnings reviews
5. **Report** (`report.py`): Computes insights, scores, confidence
6. **Template** (`daily_report.html.j2`): Renders + interactive JS layer

### Precedence (State Wins)
- YAML defaults → DB → localStorage (wins on edit in session) → export JSON → re-import → DB

### Key Files
| File | Purpose |
|------|---------|
| `src/stock_daily_research/report.py` | Hero items, insights, scoring, confidence |
| `src/stock_daily_research/storage.py` | SQLite schema, migrations, CRUD |
| `src/stock_daily_research/models.py` | Frozen dataclasses (TickerResearchState, ValuationSnapshot, etc.) |
| `src/stock_daily_research/api_server.py` | HTTP API for "Save to Database" button in report |
| `src/stock_daily_research/templates/daily_report.html.j2` | HTML + JS interactivity + language toggle |
| `watchlist.yaml` | Ticker config + plan defaults |
| `tests/` | 227 unit tests |

## Recent Features (June 2026)

### Feature A: News Individual Read Marking
- Each news item has a ✓ button
- Click to mark read → dims article (opacity 0.35, strikethrough)
- State persists in localStorage (`stock-daily-read-news`)
- No export/import needed (session-local only)

### Feature B: Thesis Manual Fill (Recommended Choice)
- New field: `TickerResearchState.thesis_text` (max 120 chars)
- Manage panel: one-line text input for thesis statement
- Card head: italic preview of thesis
- Compare table: Thesis column shows thesis_text if set, else thesis_state
- localStorage: `stock-daily-draft-thesis-text`
- Full export/import support

### Feature C: Day-over-Day Delta Badges
- Inline ±delta badges on each ticker card: attention score, RSI, news count, valuation risk direction
- `ticker_delta(report, symbol)` in `report.py` diffs today vs yesterday using `_current_history_point` / `_previous_history_point`
- Reuses stored `news_daily_summary` history; renders nothing on first day (no prior point) and suppresses zero-deltas
- CSS: `.delta-up` (green) / `.delta-down` (red)

### Feature D: Valuation Retry + TTL Cache (robustness)
- `load_fresh_valuation_snapshot(conn, ticker, max_age_hours=4)` in `storage.py`: serves a SQLite snapshot <4h old, skipping the network call
- `runner.py`: pre-fetches cache in the main thread (thread-safe) before the `ThreadPoolExecutor`; uncached tickers get 3 exponential-backoff retries (1s/2s/4s)
- Stricter `_has_usable_valuation()` now requires `last_close` (not just any non-None field) before accepting a fetch
- Constants: `VALUATION_CACHE_TTL_HOURS = 4`, `_VALUATION_MAX_RETRIES = 3`

### Feature E: Plan Triggers (live plan-vs-price signals)
- `plan_triggers(report)` in `report.py` parses numeric levels out of free-text plan fields (`entry_plan`, `add_zone`, `reduce_zone`, `stop_loss`) and compares against `last_close`
- `_parse_price_levels()` extracts price tokens; `_plausible_levels()` filters outliers (keeps 0.3x–3x of last close) to ignore stray numbers
- Emits actionable signals: "NVDA entered add zone $800–820", "broke plan stop", etc.; rendered as colored chips on the card
- Turns the static investment plan (Feature #1) into morning signals — no manual price math needed

### Feature F: Morning Actions (30-sec decision block)
- `morning_actions(report)` consolidates plan triggers + stop-loss proximity + imminent earnings (≤1d) + thesis cracks (weakening/broken) + large overnight gaps (±3%)
- Deduped by (ticker, label), prioritized by severity (stop 6 > earnings 4 > thesis 3 > gap 2), capped at 6
- Renders as the first section of the report (`#morning-actions`) with a red "Actions N" TOC pill; hidden entirely when nothing needs a decision

### Feature G: Attention Sparkline
- `ticker_sparkline(report, symbol)` renders an inline SVG trend line (zero dependencies) of the stored attention-score history (oldest→newest)
- Green if rising, red if falling; needs ≥2 days of history, otherwise renders nothing
- Shown next to the Attn Score metric on each card

### Feature H: My Book P&L (auto-weighted portfolio + total return)
- **Auto portfolio weights**: `derive_portfolio_weights(report)` in `report.py` fills `portfolio_weight` for any holding missing one, from `position_size = shares × last_close` (falls back to `shares × avg_cost`), normalized across holdings. Manual weights are preserved. Called once in `runner.py` after the report is assembled (before `write_report`), so HTML/markdown/notifications all see weights.
- **Why it matters**: weight was the gate for `book_impact_ranking`, `portfolio_impact_summary`, sector concentration, and the `book_today` cards — all previously empty because no weight was set. Auto-weighting lights them up with zero manual input (no need to enter total assets).
- **Total return view**: `portfolio_impact_summary()` now also emits per-holding `pl_pct` / `pl_dollar` (current price vs avg cost), plus `pl_leaders` / `pl_laggards` (top/bottom 3 by total return) and book totals `total_pl_dollar` / `total_pl_pct`.
- **Template** (`#my-book` section): new "Unrealized P&L" stat (`$+X (+Y%)`) and "Total return leaders / laggards" cards, alongside the existing today's-impact winners/losers (daily move × weight) and sector concentration.
- **Position source**: holdings live in `watchlist.yaml` per-ticker `position:` block (`status: holding`, `shares`, `avg_cost`, optional numeric `stop_loss`). YAML is the durable baseline; DB `position_json` overrides field-by-field if edited via the UI and re-imported.

### UI Localization: Traditional Chinese (繁體中文) + Language Toggle
- **Method A (Client-side)**:  All UI text rendered in Traditional Chinese by default (100+ locations)
  - Toolbar buttons, table headers, filter options, manage panel labels, JavaScript state labels, CSS content properties
  - Full test coverage: 227 tests updated and passing
- **Language toggle**: Click button in top-right (next to theme toggle) to switch between 中文 ↔ English
  - Preference saved to `localStorage` as `stock-daily-language`
  - Affects ~50 common UI elements with `data-i18n` attributes
  - Translations dict in JavaScript, no backend required
  - **Future (Phase 2)**: Full i18n infrastructure with dedicated translation files for all 100+ strings

### Save to Database: One-Click Database Persistence
- **API Server** (`api_server.py`): Simple HTTP server (no external dependencies)
  - Listens on `http://127.0.0.1:8765`
  - POST `/api/save-research-state` accepts JSON payload
  - Calls `import_research_state_payload()` to persist to SQLite
  - CORS-enabled for cross-origin requests
- **Report Button**: "💾 Save to Database" button in toolbar
  - Collects all localStorage changes (pins, tags, thesis, notes, positions, etc.)
  - Sends to API in single request
  - Real-time feedback: saving → success/error message
  - Workflow: Edit report → Click save → Changes persist to DB (no export/import needed)
- **Startup**: `python -m stock_daily_research.api_server` (ctrl+C to stop)

## Data Model Highlights

### TickerResearchState (SQLite + localStorage)
```python
ticker: str
tag: str                          # user tag
thesis_state: str                 # Unmarked/watching/building/active/weakening/broken
thesis_trigger: str               # Valuation/Guidance/Regulation/Macro/Execution/...
thesis_text: str                  # New: one-liner thesis statement (Feature B)
note: str                         # Free-text notes
checklist: list[str]              # [earnings, guidance, valuation, news, thesis]
revisit_date: date | None         # Next review
pinned: bool                       # Pin to top
review_status: str                # not-reviewed / reviewed
bull_case, bear_case, entry_plan, add_zone, reduce_zone, stop_loss: str  # Investment plan (Feature #1)
earnings_questions: list[str]     # Pre-earnings card (Feature #3)
position: PositionConfig          # Hold/Watch/Avoid + shares, avg cost, weight, stop loss
```

### PostEarningsReview (SQLite)
```python
ticker: str
earnings_date: date | None
eps, revenue, guide: str          # Beat/Miss/In line
eps_surprise_pct, revenue_surprise_pct: float | None
fy1_eps_revision_after, fy1_revenue_revision_after: float | None
conclusion: str                   # Thesis intact / Cracked / Pivoting
next_step: str                    # Hold / Add / Trim / Re-evaluate
gross_margin_change: str          # Feature #3: manual
management_keywords: str          # Feature #3: manual
thesis_changed: str               # Feature #3: Y/N
```

## localStorage Keys (Session Draft State)

| Key | Value Shape | Purpose |
|-----|-------------|---------|
| `stock-daily-draft-pins` | `string[]` | Pinned ticker symbols |
| `stock-daily-draft-tags` | `{ [sym]: string }` | User tags |
| `stock-daily-draft-thesis` | `{ [sym]: string }` | Thesis state dropdown |
| `stock-daily-draft-thesis-triggers` | `{ [sym]: string }` | Trigger dropdown |
| `stock-daily-draft-thesis-text` | `{ [sym]: string }` | **New (Feature B)**: one-liner thesis |
| `stock-daily-draft-notes` | `{ [sym]: { note, revisit } }` | Notes + revisit date |
| `stock-daily-draft-checklist` | `{ [sym]: string[] }` | Reviewed items |
| `stock-daily-draft-plans` | `{ [sym]: { bull_case, ... } }` | Investment plan fields |
| `stock-daily-draft-earnings-questions` | `{ [sym]: string[] }` | Pre-earnings questions |
| `stock-daily-draft-positions` | `{ [sym]: position object }` | Position editor state |
| `stock-daily-read-news` | `{ [url]: true }` | **New (Feature A)**: read news URLs |
| `stock-daily-theme` | `"auto" \| "light" \| "dark"` | Theme preference |

## CSS Variables (Light/Dark)

```css
:root {
  --bg: #fafafa;
  --surface: #ffffff;
  --text: #1a1a1a;
  --muted: #666;
  --border: #e0e0e0;
  --warning-bg: #fff8f0;
  --danger-bg: #fff5f5;
  --good-bg: #f0fdf4;
  --info-bg: #f0f9ff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a1a;
    --surface: #2a2a2a;
    --text: #f0f0f0;
    --muted: #aaa;
    --border: #444;
  }
}
```

## Filters Available in Template

| Filter | Purpose |
|--------|---------|
| `metric_value` | Format 1.25T, 50M, N/A |
| `days_until` | "today", "tomorrow", "in 3d", "2d ago" |
| `earnings_urgency` | "imminent", "soon", "week", "later", "past" |
| `card_state` | "hot", "warm", "warn", "quiet" |
| `ticker_insights` | dict with setup/risk/watch lists |
| `right_side_score` | Score object (planned Feature #2) |

Jinja globals (registered in `render_html_report`): `ticker_delta(symbol)` (Feature C), `ticker_sparkline(symbol)` (Feature G), `plan_triggers_for(symbol)` (Feature E). `morning_actions` is passed via render context (Feature F).

## Testing

```bash
# Specific test
pytest tests/test_storage.py -q

# Coverage
pytest --cov=src tests/ -q

# Verbose (show failures)
pytest tests/ -v
```

## Common Tasks

### Add a New Ticker
Edit `watchlist.yaml`:
```yaml
- symbol: XYZ
  company_name: XYZ Corp
  aliases: [XYZ]
  keywords: [semiconductor, AI]
```
Run: `python run_daily.py`

### Check Data Quality
Open report → Global Warnings section shows anomaly flags + confidence scores (Feature #4, planned).

### Export Research State
Click "Export research" button in report, or:
```bash
python -m stock_daily_research.cli --export-research-state
```
Import on new machine with `--import-research-state research-state-*.json`.

### Debug Valuation
Valuation fallback → Look for "Valuation fallback used" in warnings. Data Quality confidence will drop (-20pts). Check: ticker aliases match news domain / yfinance query.

## Future Roadmap (Planned)

- **Feature #2 (Right-side Trading Score)**: Composite 0–100 score + status badge (Breakout / Pullback / Extended / Weakening / Avoid) ✓ Planned
- **Feature #4 (Data Quality Check)**: Anomaly detection + 0–100 confidence score + per-ticker freshness flags ✓ Planned
- **Phase 6**: Web dashboard (real-time, charting, alerts) — future iterations

---

Last updated: 2026-07-10 (Multi-market support: 台股/上櫃/加密貨幣 + per-market sector map with tabs and local taxonomies)
