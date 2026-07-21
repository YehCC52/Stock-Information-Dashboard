# Stock Daily Research Dashboard

Personal, offline-first stock research system that generates a daily static HTML report. It supports US equities, Taiwan equities/ETFs, and crypto while keeping each market's workspace and rankings separate.

## Product Mission

The report should answer three questions quickly:

1. What needs attention today?
2. Why does it matter?
3. What is the next planned action?

Prefer decision clarity over feature count. Do not add a new top-level section unless it replaces, consolidates, or materially improves an existing daily decision.

## Current Status

Updated: 2026-07-21

- Test suite: 327 tests passing.
- Report output: `reports/YYYY/MM/YYYY-MM-DD.html` plus Markdown and brief text.
- Markets: `us`, `twse`, `tpex`, and `crypto`; UI groups TWSE/TPEX under Taiwan.
- Data policy: free sources by default; no paid API dependency.
- Report cadence: generated snapshots, not intraday real-time data.
- UI language: Traditional Chinese for Taiwan users. Keep standard market terms such as ticker, ETF, EPS, RSI, ATR, P/E, and API when translating them would reduce clarity.

### Major Capabilities

- Morning actions and daily decision summary.
- Market-specific tabs, summaries, rankings, news, valuation, and ticker cards.
- Five-dimension health diagnostic: trend, momentum, volume/price, fundamentals, and risk, with a persisted five-session score trend.
- Strategy screener: overall, breakout, pullback, squeeze, fundamental, daily unusual activity, and risk-first.
- Right-side trading score with persisted five-session trend, execution gates, entry/invalidation/2R planning, and signal validation.
- Moving averages, relative strength, RSI, ATR, volume, gap, squeeze, breakout-hold, Wyckoff, VPA, Adam Theory scenario, and operator discipline analysis.
- Earnings, valuation, compact TTM-to-FY1 EPS outlook, Forward EPS, analyst-consensus targets, attributable major-firm targets, estimate revisions, data-quality confidence, trusted news, manual X signals, and macro context.
- Taiwan monthly revenue, dividends, and institutional flow from official/free sources.
- Portfolio weighting, P&L, concentration, stop-risk, correlation, liquidity, and mixed-currency safeguards.
- Research state, thesis, plans, post-earnings reviews, trade journal, export/import, and local save API.

## Quick Commands

```powershell
# Full daily report using enabled free providers
python run_daily.py

# Data-rich report without news or macro fetches
python run_daily.py --no-news --no-macro

# Fully offline structural/template regeneration
python run_daily.py --no-news --no-valuation --no-macro --no-taiwan-data

# Generate a historical date
python run_daily.py --date 2026-07-17

# Full test suite
python -m pytest tests/ -q

# Focused report tests
python -m pytest tests/test_report.py -q

# Validate configuration
python -c "from stock_daily_research.config import load_config; load_config('watchlist.yaml')"

# Local API used by the report's Save button
python -m stock_daily_research.api_server
```

On Windows, pytest may need an accessible `--basetemp` or an unsandboxed run when the default user temp directory denies access.

## Architecture

```text
watchlist.yaml
    -> config.py
    -> runner.py
       -> news.py / valuation.py / macro.py / taiwan_market.py / x_signals.py
       -> frozen dataclasses in models.py
       -> SQLite persistence in storage.py
       -> analysis and view models in report.py
       -> daily_report.html.j2 / daily_report.md.j2
```

### Key Files

| File | Responsibility |
| --- | --- |
| `watchlist.yaml` | Market, symbol, aliases, capabilities, plan, and position baseline |
| `src/stock_daily_research/models.py` | Frozen domain models and market defaults |
| `src/stock_daily_research/runner.py` | Provider orchestration, cache/fallback flow, persistence, report assembly |
| `src/stock_daily_research/report.py` | Pure analysis helpers, scoring, summaries, portfolio logic, render context |
| `src/stock_daily_research/storage.py` | SQLite schema, migrations, snapshots, research state, history |
| `src/stock_daily_research/valuation.py` | yfinance normalization and technical metric calculation |
| `src/stock_daily_research/taiwan_market.py` | Official Taiwan market disclosures |
| `src/stock_daily_research/templates/daily_report.html.j2` | Static UI, responsive CSS, and local-only interactivity |
| `src/stock_daily_research/api_server.py` | Local research-state save endpoint on `127.0.0.1:8765` |
| `tests/` | Unit and integration coverage |

## State and Persistence

Durable precedence:

```text
YAML defaults -> SQLite overrides -> localStorage session drafts -> export/import -> SQLite
```

- Do not silently overwrite user research state.
- `watchlist.yaml` is the durable baseline for positions and plans.
- SQLite stores research state, valuation/history snapshots, reviews, trades, and report runs.
- localStorage is a session editing layer; preserve intentional empty values.
- Reports are organized by year and month through `report_output_dir()`.

## Market and Asset Rules

- Never mix US, Taiwan, and crypto rows in a market-scoped view.
- Cross-market links such as `TSM` and `2330.TW` are references, not shared market membership.
- Use `TickerConfig.market` as the source of truth; use the report's market bucket helper for UI grouping.
- Respect `has_fundamentals` and `has_earnings`. ETFs and crypto must not trigger meaningless fundamental or earnings calls.
- Missing dimensions are unavailable, not zero. Reweight composite scores across available dimensions.
- Do not label daily data as real-time, smart monitoring, Level 2, or intraday alerts.
- Mixed currencies must not be summed without a valid FX conversion.

## Decision-Engine Rules

The five-dimension diagnostic and strategy screener live in `report.py`.

- Keep rules inspectable and deterministic; every score needs evidence text.
- Keep calculation out of Jinja and JavaScript.
- Clamp scores to 0-100 and test strong, weak, missing-data, ETF/crypto, and regime-reset cases.
- Penalize unstable or negative EPS before rewarding large projected EPS growth.
- Do not let a missing fundamental dimension punish ETFs or crypto.
- A strategy match is a candidate for review, not a buy/sell instruction.
- Persist a signal before evaluating future performance. Never use future data when generating a historical signal.
- Keep new strategy thresholds market-aware and verify per-market ranking limits.

## UI and UX Rules

- The first visible workflow is the actual dashboard, not a landing page.
- Keep the hierarchy: daily decisions -> portfolio risk -> candidates -> ticker detail.
- Put advanced evidence in collapsed details instead of adding more badges or sections.
- Reuse CSS variables and existing spacing. No CDN, external font, or external runtime dependency.
- Preserve offline HTML, dark/light themes, print behavior, and localStorage interactions.
- Test at desktop and at 760px/480px. Text, scores, buttons, and market stats must not overlap or create horizontal page overflow.
- Use the existing market switch event (`stock-daily:market`) for market-scoped UI.
- A new feature must pass at least three of these checks:
  - changes a daily decision;
  - uses reliable available data;
  - can be understood in about 10 seconds;
  - replaces manual work or an existing section.

## Provider Rules

- Free providers are the default. Ask before adding a paid or usage-billed dependency.
- Cache before network, set timeouts, retry transient failures, and do not retry expected 4xx capability gaps.
- Isolate failures into warnings so one ticker/provider cannot abort the report.
- Preserve `source`, `as_of_date`, and retrieval timestamps.
- Prefer official Taiwan disclosures for Taiwan-specific fields.
- yfinance is an unofficial personal-use source; always retain last-known-good fallback behavior.

## Testing Expectations

Scale tests with the change:

| Change | Minimum verification |
| --- | --- |
| Watchlist/config | `tests/test_config.py` plus config load |
| News | `tests/test_news.py` |
| Valuation/earnings | `tests/test_valuation.py` and fallback/storage tests |
| Taiwan data | `tests/test_taiwan_market.py` |
| Scoring/strategy/UI | focused `tests/test_report.py`, rendered report, browser market/mobile checks |
| Storage/schema/state | `tests/test_storage.py`, `tests/test_api_server.py`, migration coverage |
| Runner/provider | provider unit tests plus `tests/test_runner.py` |
| Trading workflow | `tests/test_trading_workflow.py` |

Before declaring a user-facing report change complete:

1. Run focused tests.
2. Run `python -m pytest tests/ -q`.
3. Generate a real report with the required data enabled.
4. Verify US/Taiwan/crypto isolation.
5. Check desktop, mobile, empty states, expand/collapse, and browser console.

## Project Skills

Use the narrowest applicable skill:

| Skill | Use for |
| --- | --- |
| `stock-dashboard-design` | Report layout, information hierarchy, responsive behavior, localization, template interactions |
| `stock-strategy-validation` | Five-dimension scores, screener rules, right-side logic, signal persistence, backtest integrity |
| `stock-watchlist` | Add/remove/configure US, Taiwan, ETF, or crypto symbols |
| `stock-pipeline-provider` | Add or change a data provider and its orchestration/storage boundary |
| `stock-news-curator` | Trusted news collection, relevance, deduplication, classification, ranking |
| `stock-valuation-calendar` | Valuation, technical snapshots, earnings capability, cache/fallback behavior |
| `stock-x-signal-curator` | Manual or official-API X signals without unsafe scraping |

## Known Boundaries

- The seven new strategy categories are current-day rankings; they do not yet have separate persisted performance histories.
- The report is static and generated on demand. It is not a broker terminal.
- No Level 2, options flow, broker order routing, or guaranteed real-time alerts without an appropriate licensed source.
- Avoid building a generic AI chat surface until a concrete daily workflow justifies it.
- Favor background validation and compact confidence indicators over additional visible sections.
