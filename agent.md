# Agent Guide

This repository builds a personal daily stock research report and interactive HTML dashboard. It is for research workflow only and is not investment advice.

## Project Shape

- Entry point: `run_daily.py`, which delegates to `stock_daily_research.cli:main`.
- Main package: `src/stock_daily_research/`.
- HTML template: `src/stock_daily_research/templates/daily_report.html.j2`.
- Markdown template: `src/stock_daily_research/templates/daily_report.md.j2`.
- Primary config: `watchlist.yaml`; keep `watchlist.example.yaml` publishable.
- Local state/database: `data/stock_daily.sqlite3`.
- Generated reports: `reports/YYYY-MM-DD.md` and `reports/YYYY-MM-DD.html`.

Important modules:

- `config.py`: YAML config loading and validation.
- `runner.py`: end-to-end report orchestration, scheduler-friendly run flow, and state overrides.
- `report.py`: report section builders, rule alerts, portfolio/book summaries, and render helpers.
- `storage.py`: SQLite schema, migrations, saved report runs, research state export/import.
- `valuation.py`: yfinance-backed valuation, price history, RSI, moving averages, and earnings measures.
- `news.py`: trusted Google News RSS collection and deduplication.
- `macro.py`: official/cached macro calendar collection.
- `notify.py`: Telegram summary composition and delivery.

## Common Commands

Install dev dependencies:

```powershell
python -m pip install -e .[dev]
```

Initialize config:

```powershell
python run_daily.py --init-config
```

Generate today's report:

```powershell
python run_daily.py
```

Generate without network-heavy data:

```powershell
python run_daily.py --no-news --no-valuation --no-macro
```

Send Telegram after generating:

```powershell
python run_daily.py --notify-telegram
```

Import edited research state before generating:

```powershell
python run_daily.py --import-research-state path\to\research_state.json
```

Run tests:

```powershell
python -m pytest
```

Targeted tests:

```powershell
python -m pytest tests\test_report.py tests\test_storage.py tests\test_runner.py
```

## Current Dashboard Behavior

- Ticker cards include quick position editing in the Manage panel: `status`, `shares`, `avg_cost`, `portfolio_weight`, `position_size`, and `stop_loss`.
- Position edits are stored in browser `localStorage`, exported with research state JSON, persisted in SQLite as `ticker_research_state.position_json`, and applied back to `TickerConfig.position` during the next run.
- Position display computes live P/L, position weight, and book impact from available close prices and position inputs.
- Thesis state and trigger are user-editable per ticker.
- The `Draft` button can call `window.claude.complete` when available in an Artifacts-like environment. If Claude is unavailable or the response cannot be parsed, it falls back to a local deterministic draft.
- Drafting only fills blank thesis fields and notes; it should not overwrite user-entered thesis, trigger, or note text.
- The "What Changed Since Last Run" header displays the report generation timestamp in Taiwan time via `twn_timestamp`, formatted like `2026-06-02 08:30 TWN`.
- Rule Alerts include RSI 14 overbought details. When `last_close` and `fifty_two_week_high` are available, overbought details also include distance from the 52-week high.

## State And Persistence Notes

- Research state export/import lives in `storage.py`; update tests whenever the JSON shape changes.
- SQLite migrations are intentionally additive. Add new columns through `_ensure_column` and keep old databases loadable.
- Report-side position overrides are applied in `runner._apply_position_overrides`; keep config positions and imported research-state positions merge-friendly.
- Browser-local data keys include:
  - `stock-daily-draft-positions`
  - `stock-daily-draft-thesis`
  - `stock-daily-draft-thesis-triggers`
  - `stock-daily-draft-notes`
  - `stock-daily-draft-checklist`
  - `stock-daily-draft-plans`
  - `stock-daily-draft-earnings-questions`

## Scheduling Notes

- The Windows Task Scheduler helper is in `scripts/register_daily_task.ps1`.
- A local scheduled task cannot generate reports while the computer is fully shut down. The machine must be on, awake, or configured to wake for the task.
- If reports must be generated while the local PC is off, run the project on an always-on host such as a VPS, NAS, cloud VM, or GitHub Actions-style environment with secrets configured safely.

## Development Rules

- Prefer existing project patterns over new abstractions.
- Keep generated reports, local databases, `.env`, and secrets out of git.
- Do not commit real API keys, Telegram tokens, chat IDs, brokerage data, or private account data.
- Treat `watchlist.yaml` as personal data; avoid copying private values into tests or docs.
- For report/template changes, add or update tests in `tests/test_report.py`.
- For SQLite or research-state changes, add or update tests in `tests/test_storage.py`.
- For run orchestration or config merge behavior, add or update tests in `tests/test_runner.py`.
- When touching news curation, trusted domains, ticker keyword matching, or article deduplication, follow the local `stock-news-curator` skill guidance.
- When touching valuation snapshots, RSI, earnings dates, valuation fallback, or estimate revisions, follow the local `stock-valuation-calendar` skill guidance.
- When touching X/Twitter signal ingestion, follow the local `stock-x-signal-curator` skill guidance.

## Verification Checklist

Before handing changes back:

1. Run focused tests for the touched area.
2. Run `python -m pytest` for cross-module changes.
3. If changing the HTML dashboard, render at least one no-network report when practical:

```powershell
python run_daily.py --no-news --no-valuation --no-macro --output-dir .tmp_review_reports --db .tmp_review_data\stock.sqlite3
```

4. Remove temporary output directories after manual rendering checks.
5. Report any tests that could not be run.
