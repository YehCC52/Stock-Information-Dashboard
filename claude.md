# Stock Daily Research Dashboard

Personal stock research dashboard with daily HTML report generation. Features technical analysis, earnings tracking, valuation checks, news clustering, and manual research state management.

## Project Status

**Latest iteration (2026-06-02)**: Features #1 (Investment Plan) and #2 (Right-side Trading Score) planning complete; Features #3 (Event Pre/Post-earnings) and #4 (Data Quality) implemented; recently completed Feature A (News Read Markers) and Feature B (Thesis Manual Fill).

**Test Suite**: 183 tests, all passing. Report generation: ~15s with full fetch, <1s with `--no-news --no-valuation --no-macro`.

## Quick Commands

```bash
# Generate full daily report (fetches news, valuation, earnings, macro)
python run_daily.py

# Fast HTML-only regen (no network)
python run_daily.py --no-news --no-valuation --no-macro

# Run full test suite
python -m pytest tests/ -q

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
| `src/stock_daily_research/templates/daily_report.html.j2` | HTML + JS interactivity |
| `watchlist.yaml` | Ticker config + plan defaults |
| `tests/` | 183 unit tests |

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

Last updated: 2026-06-02 (Features A & B completed, #1/#2/#3/#4 design locked)
