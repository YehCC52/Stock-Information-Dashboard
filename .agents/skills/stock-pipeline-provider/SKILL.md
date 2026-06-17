---
name: stock-pipeline-provider
description: "Add or modify a data provider in the stock-daily-research pipeline. Use when integrating a new free/paid data source (e.g. Alpha Vantage earnings, FMP valuation, alternate news RSS, sentiment API), or when changing how an existing provider (Google News RSS, yfinance, official macro calendar) fetches/normalizes data. Knows the runner orchestration, parallel fetch architecture, storage schema, and provider boundary contract."
---

# Stock Pipeline Provider

## When to use

Adding a new data source — sentiment, alt-news, paid earnings calendar, options flow, insider transactions — or changing how an existing one works. The pipeline already has 4 providers as templates:

| Provider | Module | Pattern |
| --- | --- | --- |
| Google News RSS | [news.py](src/stock_daily_research/news.py) | Per-ticker class with `fetch_for_ticker(ticker, ...)` returning `(articles, warnings)` |
| yfinance valuation | [valuation.py](src/stock_daily_research/valuation.py) | Module-level `fetch_yfinance_valuation(ticker)` and `fetch_yfinance_earnings_date(ticker)` |
| Manual X signals | [x_signals.py](src/stock_daily_research/x_signals.py) | File-based loader, called once before per-ticker loop |
| Official macro calendar | [macro.py](src/stock_daily_research/macro.py) | Class with `fetch(report_date, timezone_name, days_ahead)` returning `MacroFetchResult` (events + warnings) |

## Architecture

```
runner.run_daily
├── load_dotenv + load_config
├── pre-flight global_warnings
├── load_manual_x_signals (single, sync)
├── _fetch_all_tickers (ThreadPoolExecutor, max_workers=6)
│   └── _fetch_one_ticker per worker:
│       ├── news_provider.fetch_for_ticker
│       ├── fetch_yfinance_valuation
│       └── fetch_yfinance_earnings_date
├── macro: OfficialMacroCalendarProvider().fetch (single, sync, post-tickers)
├── DailyReport (preliminary)
├── save_report → SQLite
├── send_telegram (optional)
└── write_report → markdown + html
```

Two flavors of provider:

1. **Per-ticker** (news, valuation, earnings) — runs inside `_fetch_one_ticker`, parallelized across tickers. Must be thread-safe and not share state.
2. **Global** (x_signals, macro) — runs once. Can be slow / serial.

## Adding a per-ticker provider

Reference: [news.py](src/stock_daily_research/news.py) and how it's wired in [runner.py:_fetch_one_ticker](src/stock_daily_research/runner.py).

1. **Module** — create `src/stock_daily_research/<source>.py`:
   - Class with `__init__(self, timeout_seconds=20, max_retries=2)` constants
   - Method signature: `fetch_for_ticker(self, ticker: TickerConfig, **provider_kwargs) -> tuple[list[Item], list[str]]`
   - The `tuple[items, warnings]` shape is the contract: items go into the report, warnings are appended per-ticker
   - Per-domain / per-call failures must NOT raise out — catch, append to warnings, continue
   - Use `requests.get` with `timeout=self.timeout_seconds`, plus a `_request_with_retry` helper with exponential backoff (see news.py for the pattern)

2. **Model** — add a `@dataclass(frozen=True)` to [models.py](src/stock_daily_research/models.py) with `ticker`, source-specific fields, `source`, `source_retrieved_at`. Add it to `TickerReport` if it's per-ticker output.

3. **Storage** — in [storage.py](src/stock_daily_research/storage.py):
   - Add a `CREATE TABLE IF NOT EXISTS` block to `SCHEMA`
   - Pick a UNIQUE constraint that prevents legitimate duplicates without losing cross-ticker rows. **Bad: `UNIQUE(url)` alone — see git history for the cross-ticker bug.** **Good: `UNIQUE(ticker, url)`** or `UNIQUE(ticker, as_of_date, source)` for snapshots
   - Add a `save_<source>(conn, item)` function using `INSERT OR REPLACE`
   - Call it from `save_report`'s per-ticker loop
   - Add an index on `ticker` (and any time field): `CREATE INDEX IF NOT EXISTS idx_<source>_ticker ON <source>(ticker)`
   - If you change a constraint on an existing table, add a migration block in `_migrate_schema` that detects the old schema and rewrites — pattern in storage.py for `news_articles` and `earnings_dates`

4. **Runner** — in [runner.py](src/stock_daily_research/runner.py):
   - Add a `fetch_<source>: bool = True` parameter to `run_daily`
   - Add `--no-<source>` global warning if disabled
   - Pass the provider into `_fetch_all_tickers` as a kwarg
   - In `_fetch_one_ticker`, call `provider.fetch_for_ticker(...)`, extend warnings, attach data to `TickerReport`

5. **CLI** — in [cli.py](src/stock_daily_research/cli.py): add `--no-<source>` argparse flag, pass to `run_daily`

6. **Config** — in [config.py](src/stock_daily_research/config.py) + [models.py](src/stock_daily_research/models.py):
   - Add a `<Source>Settings` dataclass to models
   - Add `<source>: <Source>Settings` to `AppSettings`
   - Add `_load_<source>_settings(data)` validator. Use `_positive_int(value, field)` for any int that must be > 0
   - Update `load_config` to load it
   - Update [watchlist.example.yaml](watchlist.example.yaml) with the new section

7. **Report** — in [report.py](src/stock_daily_research/report.py) + [templates/daily_report.html.j2](src/stock_daily_research/templates/daily_report.html.j2):
   - Decide if it surfaces in summary stats, a dedicated section, ticker cards, or all three
   - If new section is needed, see `stock-dashboard-design` skill for layout integration

8. **Test** — add `tests/test_<source>.py`:
   - Unit tests for normalization helpers
   - Per-domain / per-call failure isolation (monkeypatch the network call, verify other items still come back)
   - At least one runner integration test using `monkeypatch` to inject the provider, verifying warnings flow through

## Adding a global provider

Reference: [macro.py](src/stock_daily_research/macro.py).

Simpler shape — fetched once after `_fetch_all_tickers`:

```python
result = OfficialMacroCalendarProvider().fetch(
    report_date=actual_report_date,
    timezone_name=config.settings.report_timezone,
    days_ahead=config.settings.macro.days_ahead,
)
events = result.events
global_warnings.extend(result.warnings)
```

Conventions:
- Return a result dataclass with `(items, warnings)` — same contract as per-ticker
- Items go onto `DailyReport` directly (not `TickerReport`)
- Stays serial — don't add to the ThreadPoolExecutor unless you need to parallelize internal fetches

## Provider contract (the non-negotiables)

- **Never raise** to the caller for transient/data issues — catch and emit a warning string. Only raise for programmer errors (bad config, missing required field).
- **Always include `source` and `source_retrieved_at`** in stored items so reports can display attribution.
- **Don't mutate input** — `TickerConfig` is `frozen=True` for a reason.
- **Per-call timeout** on every HTTP request (`timeout=N` to `requests.get`).
- **Retry transient errors** (`requests.RequestException`, 5xx) with exponential backoff. **Don't retry 4xx** (those are programmer errors or auth issues — fail loud).
- **Thread safety** for per-ticker providers — don't store mutable state on the instance, or guard with `threading.Lock`.

## Free-API hygiene

This project's [README.md](README.md) "No Paid API Policy" — `.env` keeps optional keys but the MVP avoids paid endpoints. If a new provider needs a key:
- Add the env var to `.env.example` with a comment
- `os.getenv(...)`-load lazily inside the provider, never at module top
- Treat missing key as "provider unavailable" — append a warning, not crash
- Prefer free tiers (Alpha Vantage 5 req/min, Finnhub 60/min) and document rate limits in the provider docstring

## Checklist before declaring done

- [ ] Module follows `(items, warnings)` contract; no exceptions leak to caller
- [ ] Storage has a UNIQUE constraint that prevents real duplicates without dropping legit rows
- [ ] If schema changed for an existing table, migration block added & idempotent
- [ ] Runner: kwarg + `--no-<source>` flag + global warning when disabled
- [ ] Config: settings dataclass + validator with friendly error messages
- [ ] watchlist.example.yaml updated
- [ ] Tests: unit + per-call-failure isolation + runner integration via monkeypatch
- [ ] `python -m pytest` green
- [ ] `python run_daily.py` finishes without crashing; check the new section in `reports/<today>.html`
- [ ] No paid endpoints unless the user explicitly asked
