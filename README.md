# Stock Daily Research

Personal daily stock research dashboard for tracking a fixed watchlist, trusted news, valuation data, earnings dates, macro events, notes, checklist status, RSI, and a free market sentiment proxy.

This project is built for personal research workflow only. It is not investment advice.

## Features

- Watchlist-driven reports from `watchlist.yaml`
- Trusted news collection from Google News RSS, filtered by allowed domains
- Manual trusted X/Twitter signal input from `data/x_posts.yaml`
- Yahoo Finance style valuation snapshots via `yfinance`
- Last-known-good valuation fallback from SQLite
- Earnings date tracking
- Official macro calendar highlights for FOMC and Employment Situation
- Interactive HTML dashboard with search, filters, pins, notes, tags, checklist status, compare mode, exports, and work modes
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
- `tickers[].trusted_news_domains`: domains allowed for news collection
- `tickers[].trusted_x_accounts`: trusted accounts for manual X signals

Macro example:

```yaml
macro:
  enabled: true
  days_back: 1
  days_ahead: 14
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
- BLS: official Employment Situation calendar, with a local fallback schedule
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
