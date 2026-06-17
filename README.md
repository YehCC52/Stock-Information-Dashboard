# Stock Daily Research

Personal daily stock research dashboard for tracking a fixed watchlist, trusted news, valuation data, earnings dates, macro events, notes, checklist status, RSI, and a free market sentiment proxy.

This project is built for personal research workflow only. It is not investment advice.

## Features

- Watchlist-driven reports from `watchlist.yaml`
- Trusted news collection from Google News RSS, filtered by allowed domains
- Manual trusted X/Twitter signal input from `data/x_posts.yaml`
- Yahoo Finance style valuation snapshots via `yfinance`
- EPS and revenue estimate layer: TTM EPS, next FY EPS, EPS growth, FY1 EPS revision, FY1 revenue revision, and next-quarter revenue revision when available
- Last-known-good valuation fallback from SQLite
- Earnings date tracking
- Macro calendar reliability: official BLS selected releases, BLS/FOMC fallback schedules, cached macro events, and optional manual events
- Interactive HTML dashboard with search, filters, pins, notes, tags, checklist status, compare mode, exports, and work modes
- Morning workflow blocks: Today's Focus, My Book Today, overnight / premarket movers, catalyst list, post-earnings scoreboard, sector leadership, thesis state / trigger, and position view
- RSI 14 technical indicator and rule-based alerts
- Free Fear & Greed style market sentiment proxy using SPY, QQQ, VIX, and HYG/LQD
- Optional Telegram daily summary
- Optional Windows Task Scheduler helper

## Setup

```powershell
python -m pip install -e .[dev]
python run_daily.py --init-config
```

To use Telegram notifications, create a local `.env` file:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

`.env` is ignored by git. Do not commit real tokens, API keys, or private credentials.

## Configuration

Main configuration lives in `watchlist.yaml`.

Important settings:

- `settings.report_timezone`: report timezone, default `Asia/Taipei`
- `settings.news.lookback_days`: news lookback window
- `settings.news.max_articles_per_ticker`: max trusted news items per ticker
- `settings.x_signals.manual_file`: manual X signal input file
- `settings.macro.enabled`: enable official macro calendar collection
- `settings.macro.days_back`: include recent macro events from the past N days
- `settings.macro.days_ahead`: include upcoming macro events for the next N days
- `settings.macro.manual_events`: optional manually maintained CPI, auction, Fed speech, or other critical fallback events
- `tickers[].position`: optional lightweight book context (`status`, `shares`, `avg_cost`, `portfolio_weight`, `position_size`)
- `tickers[].trusted_news_domains`: domains allowed for news collection
- `tickers[].trusted_x_accounts`: trusted accounts for manual X signals

Macro example:

```yaml
macro:
  enabled: true
  days_back: 1
  days_ahead: 14
  manual_events:
    - name: CPI Release
      category: inflation
      event_datetime: "2026-05-12T20:30:00+08:00"
      source: manual
      notes: Manually maintained fallback event
```

Position example:

```yaml
position:
  status: holding
  shares: 10
  avg_cost: 120.00
  portfolio_weight: 6.5
```

## Run

Generate today's report:

```powershell
python run_daily.py
```

Skip news or valuation fetching:

```powershell
python run_daily.py --no-news --no-valuation
```

Skip macro events:

```powershell
python run_daily.py --no-macro
```

Send Telegram summary:

```powershell
python run_daily.py --notify-telegram
```

Outputs:

- Markdown report: `reports/YYYY-MM-DD.md`
- HTML dashboard: `reports/YYYY-MM-DD.html`
- SQLite database: `data/stock_daily.sqlite3`

## Interactive Dashboard & Data Management

### Editing Research State in the Report

The HTML dashboard (`reports/YYYY-MM-DD.html`) is fully interactive. You can:

1. **Edit ticker information** via the "Manage" panel on each card:
   - Research thesis (state, trigger, text)
   - Notes and revisit date
   - Investment plan (bull/bear case, entry, add zone, reduce zone, stop loss)
   - Position details (status, shares, avg cost, weight, stop loss)
   - Post-earnings review

2. **Use filters and search**:
   - Quick search by ticker or company name
   - Filter by focus, state, earnings timing, RSI, topic, sector, cluster, or risk
   - Compare multiple tickers side-by-side

3. **Pin and tag** tickers for personalized workflow

4. **Export research state** as JSON for backup or multi-device sync

### Saving Changes to Database

To save all your edits from the report directly to the database:

#### Step 1: Start the API Server

In a terminal:

```powershell
python -m stock_daily_research.api_server
```

Output:
```
[OK] Research State API server started at http://127.0.0.1:8765
     Press Ctrl+C to stop
```

#### Step 2: Edit in the Report

1. Open the HTML report (`reports/2026-06-17.html`)
2. Make changes in the Manage panels
3. Changes are auto-saved to browser localStorage

#### Step 3: Click "Save to Database" Button

- **Button location**: Top toolbar, next to export buttons
- **Feedback**:
  - ⏳ `💫 正在保存...` (saving...)
  - ✅ `已成功保存到資料庫` (saved successfully)
  - ❌ If API server is not running: `保存失敗：...`

Your edits are now persisted to SQLite and will appear in tomorrow's report.

### Alternative: Export & Import via CLI

If you prefer not to run the API server, use the manual export/import workflow:

```powershell
# 1. Edit in the report and click "Export research state"
# 2. Import the JSON file back:
python -m stock_daily_research.cli --import-research-state research-state-2026-06-17.json
```

## Windows Daily Schedule

Register an 08:00 daily scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
```

Register with Telegram notification:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -NotifyTelegram
```

Use a custom time:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 07:30
```

## Data Sources

- Google News RSS: free RSS search, constrained by trusted domains and relevance checks
- `yfinance`: unofficial Yahoo Finance data for valuation, price history, RSI, moving averages, and earnings dates
- Federal Reserve: official FOMC calendar and statements
- BLS: official selected-release calendar for NFP, CPI, and PPI, with BLS-specific and built-in fallback schedules
- X/Twitter: manual input only; this MVP does not call paid or usage-billed X APIs

## Telegram Summary

Telegram summary can include:

- Macro events
- US overnight news
- Earnings within 7 days
- Top trusted news
- Valuation, RSI, and data-quality flags
- Link to the generated report

Troubleshooting:

- Confirm `.env` exists
- Confirm `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Confirm the bot can message the target chat
- Run with `--notify-telegram` or enable Telegram in `watchlist.yaml`

## Tests

```powershell
python -m pytest
```

## Security Notes

- Keep `.env`, local SQLite databases, and generated reports out of git
- Treat `watchlist.yaml` as publishable configuration before pushing
- Do not store API secrets in README, tests, watchlist files, or report templates
