---
name: stock-pipeline-provider
description: "Add or modify a data provider in the stock daily research pipeline. Use for fetch, normalization, caching, fallback, storage, CLI flags, market capability gates, or provider failure handling."
---

# Stock Pipeline Provider

## Goal

Integrate reliable data without making one provider failure abort the report. Free and official sources are the default; ask before adding a paid or usage-billed dependency.

## Current Provider Patterns

| Source | Module | Scope |
| --- | --- | --- |
| Google News RSS | `news.py` | Per ticker |
| yfinance price, valuation, technicals, earnings | `valuation.py` | Per ticker |
| Official macro calendar | `macro.py` | Global |
| Official Taiwan disclosures | `taiwan_market.py` | Taiwan ticker batch |
| Manual X signals | `x_signals.py` | Local file, global load |

Orchestration belongs in `runner.py`. Frozen normalized models belong in `models.py`, persistence in `storage.py`, and decision-oriented presentation in `report.py`.

## Provider Contract

- Return normalized data plus warnings, or a result object with equivalent fields.
- Isolate network, parsing, and missing-data failures to the affected source or ticker.
- Include source attribution, source date, and retrieval time when the model supports them.
- Use a timeout for every HTTP request.
- Retry only transient exceptions, rate limits, and 5xx responses with bounded backoff.
- Do not retry expected capability gaps or ordinary 4xx responses.
- Do not mutate `TickerConfig` or shared mutable state.
- Make per-ticker providers thread-safe.
- Preserve enough raw meaning to distinguish unavailable, stale, fallback, pending, and true zero.

## Capability Gate

Check asset capabilities before a request:

- `ticker.has_fundamentals` gates company fundamentals.
- `ticker.has_earnings` gates earnings-calendar calls.
- ETFs, leveraged ETFs, and crypto should still fetch price and technical history.
- Taiwan-specific disclosures apply only to `twse` and `tpex`.
- A missing ETF earnings endpoint is expected, not evidence that the symbol is delisted.
- Market-scoped data must remain attached to the originating ticker and market.

## Implementation Workflow

1. Inspect the provider's terms, rate limits, update cadence, and attribution needs.
2. Decide whether it is per-ticker, global, or market-batch data.
3. Define or extend a frozen normalized model.
4. Implement fetch and normalization with dependency injection where practical.
5. Add config and a `--no-<source>` CLI switch when users need deterministic disabling.
6. Check fresh cache before network.
7. Add SQLite schema and an idempotent migration only when persistence is necessary.
8. Wire the provider through `runner.py` without adding analysis logic there.
9. Add report logic only after defining the daily decision it supports.
10. Test normalization, capability skips, transient retry, permanent failure, fallback, and runner warning flow.

## Cache and Fallback

- Prefer fresh SQLite cache before network. The valuation cache currently uses a four-hour TTL.
- Save current valid data before deriving report signals.
- Last-known-good fallback must keep its original source and as-of date.
- Never relabel stale fallback as current data.
- Avoid repeated requests when the upstream source cannot provide that asset class.
- One failed ticker must not discard successful results for other tickers.

## Storage Rules

- Choose uniqueness keys that retain legitimate cross-ticker rows, such as `(ticker, url)` for news or `(ticker, as_of_date, source)` for snapshots.
- Add useful ticker/date indexes.
- Detect old schemas before migration and keep migrations rerunnable.
- Preserve existing user research state during provider migrations.

## Free-Source Policy

- Prefer official disclosures, exchange data, RSS, local files, and yfinance personal-use prototypes.
- Treat yfinance as unofficial and unstable; maintain cache and fallback paths.
- Load optional credentials lazily from environment variables.
- Missing optional credentials should disable that provider with a clear warning, not crash the run.
- Do not imply real-time coverage when the source is delayed or the report is generated on demand.

## Verification

Run provider unit tests, runner integration tests, storage tests when applicable, and the full suite. Then generate a report with the provider enabled and disabled. Confirm:

- no uncaught provider exception;
- no repetitive expected-error log;
- source and freshness are visible;
- market views remain isolated;
- unavailable assets show a clear empty state;
- cached and fallback paths behave as documented.
